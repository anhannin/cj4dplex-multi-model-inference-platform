"""Use frozen stock Qwen calls in a separate diagnostic process, no ROS endpoints."""

import argparse
import ast
import contextlib
import gc
import hashlib
import json
from pathlib import Path
import time
import torch
from transformers import AutoTokenizer, Qwen3_5ForConditionalGeneration

MODEL = (
    "/cache/models--Qwen--Qwen3.5-9B/snapshots/c202236235762e1c871ad0ccb60c8ee5ba337b9a"
)
TEXT = "Explain GPU resource contention in six concise bullet points."


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--green-sms", type=int)
    p.add_argument("--max-new-tokens", type=int, default=128)
    p.add_argument("--target-mlp", action="store_true")
    args = p.parse_args()
    torch.set_num_threads(4)
    torch.cuda.set_device(0)
    source = Path("/app/ros2/qwen_node.py").read_text()
    tree = ast.parse(source)
    clock = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "TokenClock"
    )
    scope = {"time": time}
    exec(
        compile(
            ast.Module(body=[clock], type_ignores=[]), "<frozen-TokenClock>", "exec"
        ),
        scope,
    )
    tokenizer = AutoTokenizer.from_pretrained(MODEL, local_files_only=True)
    model = (
        Qwen3_5ForConditionalGeneration.from_pretrained(
            MODEL,
            dtype=torch.bfloat16,
            local_files_only=True,
            attn_implementation="sdpa",
        )
        .eval()
        .to("cuda")
    )
    prompt = tokenizer.apply_chat_template(
        [{"role": "user", "content": TEXT}],
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    cpu_inputs = tokenizer(prompt, return_tensors="pt")
    inputs = {k: v.to("cuda") for k, v in cpu_inputs.items()}
    options = dict(
        max_new_tokens=args.max_new_tokens,
        do_sample=False,
        use_cache=True,
        pad_token_id=tokenizer.eos_token_id,
    )
    pair = None
    stream = None
    result = {
        "state": "running",
        "model": "Qwen3.5-9B",
        "torch": torch.__version__,
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "mode": "green-functional" if args.green_sms else "baseline-counter-diagnostic",
        "input_tokens": int(inputs["input_ids"].shape[-1]),
        "max_new_tokens": args.max_new_tokens,
        "scope": "diagnostic only, not a baseline latency measurement",
    }
    try:
        with torch.inference_mode():
            print("MODEL_LOADED", flush=True)
            reference = model.generate(
                **inputs, **options, streamer=scope["TokenClock"]()
            )
            torch.cuda.synchronize()
            print("WARMUP_COMPLETE", flush=True)
            if args.green_sms is not None:
                import green_bridge

                pair = green_bridge.GreenPair(args.green_sms)
                result["green_allocation"] = pair.metadata()
                stream = torch.cuda.ExternalStream(pair.stream_ptr(0), device=0)
                stream.wait_stream(torch.cuda.current_stream())
            handles = []
            if args.target_mlp:
                from ncu_analysis import select_linear_targets

                modules = dict(model.named_modules())
                targets = select_linear_targets(modules)
                result["selected_modules"] = [
                    {"name": n, "weight_shape": list(modules[n].weight.shape)}
                    for n in targets
                ]

                def pre_hook(module, inputs):
                    torch.cuda.nvtx.range_push("selected.linear")

                def post_hook(module, inputs, output):
                    torch.cuda.nvtx.range_pop()

                for target in targets:
                    handles.append(modules[target].register_forward_pre_hook(pre_hook))
                    handles.append(modules[target].register_forward_hook(post_hook))
            torch.cuda.profiler.start()
            name = (
                "qwen.green.generate"
                if stream is not None
                else "qwen.baseline.generate"
            )
            with torch.cuda.nvtx.range(name):
                with (
                    torch.cuda.stream(stream)
                    if stream is not None
                    else contextlib.nullcontext()
                ):
                    output = model.generate(
                        **inputs, **options, streamer=scope["TokenClock"]()
                    )
                if stream is not None:
                    stream.synchronize()
                else:
                    torch.cuda.synchronize()
            torch.cuda.profiler.stop()
            for handle in handles:
                handle.remove()
            count = int(cpu_inputs["input_ids"].shape[-1])
            result.update(
                state="PASS",
                output_tokens=int(output.shape[-1] - count),
                output_text=tokenizer.decode(
                    output[0, count:], skip_special_tokens=True
                ),
                exact_token_match_to_default=bool(torch.equal(reference, output)),
                eos_or_length_finite_output=True,
            )
            del output, reference, inputs, model
        gc.collect()
        torch.cuda.synchronize()
        torch.cuda.empty_cache()
    except Exception as error:
        result.update(state="FAIL", error=repr(error))
        raise
    finally:
        if pair is not None:
            del stream
            pair.close()
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
