"""Representative BF16 linear operator: counter permission/support preflight only."""

import argparse
import json
from pathlib import Path
import torch

p = argparse.ArgumentParser()
p.add_argument("--output", type=Path, required=True)
a = p.parse_args()
torch.set_num_threads(4)
torch.manual_seed(42)
with torch.inference_mode():
    weight = torch.randn((4096, 4096), device="cuda", dtype=torch.bfloat16)
    x = torch.randn((1, 4096), device="cuda", dtype=torch.bfloat16)
    for _ in range(5):
        y = torch.nn.functional.linear(x, weight)
    torch.cuda.synchronize()
    torch.cuda.profiler.start()
    y = torch.nn.functional.linear(x, weight)
    torch.cuda.synchronize()
    torch.cuda.profiler.stop()
    a.output.write_text(
        json.dumps(
            {
                "state": "PASS",
                "scope": "counter support probe, not model baseline",
                "shape": [1, 4096, 4096],
                "dtype": "bfloat16",
                "finite": bool(torch.isfinite(y).all()),
            },
            indent=2,
        )
        + "\n"
    )
