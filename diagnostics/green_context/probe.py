"""Bounded functional probe only; no model or serving deployment changes."""

import argparse
import gc
import json
from pathlib import Path
import torch
import green_bridge
from validate import validate_native


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sms", type=int, default=16)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    pair = None
    result = {
        "state": "running",
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "requested_first_partition_sms": args.sms,
        "scope": "functional binding probe; not performance optimization",
    }
    try:
        torch.cuda.init()
        torch.set_num_threads(4)
        torch.manual_seed(42)
        original_stream = torch.cuda.current_stream()
        pair = green_bridge.GreenPair(args.sms)
        metadata = pair.metadata()
        for index, part in enumerate(metadata["parts"]):
            with torch.cuda.nvtx.range("native.smid.partition" + str(index)):
                part["smids"] = pair.sample_smids(index)
        result.update(metadata)
        result["native_validation"] = validate_native(metadata)
        a = torch.randn((512, 512), device="cuda")
        b = torch.randn((512, 512), device="cuda")
        reference = (a @ b).cpu()
        original_stream.synchronize()
        results = []
        streams = []
        for index in range(2):
            stream = torch.cuda.ExternalStream(pair.stream_ptr(index), device=0)
            streams.append(stream)
            stream.wait_stream(original_stream)
            with torch.cuda.nvtx.range("torch.partition" + str(index)):
                with torch.cuda.stream(stream):
                    value = a @ b
                    activated = torch.relu(value)
                stream.synchronize()
                cpu = value.cpu()
                activated_cpu = activated.cpu()
            torch.testing.assert_close(cpu, reference, rtol=1e-4, atol=1e-4)
            torch.testing.assert_close(
                activated_cpu, torch.relu(reference), rtol=1e-4, atol=1e-4
            )
            results.append(
                {
                    "partition": index,
                    "correct": True,
                    "max_abs_error": float((cpu - reference).abs().max()),
                }
            )
            del value, activated, cpu, activated_cpu
        result["pytorch_results"] = results
        result["state"] = "PASS"
        del a, b, reference, stream
        streams.clear()
        gc.collect()
        torch.cuda.synchronize()
        torch.cuda.empty_cache()
    except Exception as error:
        result.update(state="FAIL", error=repr(error))
        raise
    finally:
        if pair is not None:
            pair.close()
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
