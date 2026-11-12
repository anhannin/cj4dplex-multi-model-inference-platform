"""CPU-only NVTX clock marks; no CUDA synchronization or cross-model barriers."""

import json
import os
from pathlib import Path
import time


def anchor(model, tag):
    import torch

    name = f"clock:{model}:{tag}:{time.perf_counter_ns()}"
    pre = time.perf_counter_ns()
    wall_pre = time.time_ns()
    torch.cuda.nvtx.mark(name)
    wall_post = time.time_ns()
    post = time.perf_counter_ns()
    record = {
        "name": name,
        "tag": tag,
        "model": model,
        "pre_ns": pre,
        "post_ns": post,
        "wall_pre_ns": wall_pre,
        "wall_post_ns": wall_post,
    }
    root = Path("/experiment/clocks")
    root.mkdir(exist_ok=True)
    file = root / (os.environ.get("PAIR_LABEL", "positive") + "-" + model + ".jsonl")
    with file.open("a") as out:
        out.write(json.dumps(record) + "\n")
    return record
