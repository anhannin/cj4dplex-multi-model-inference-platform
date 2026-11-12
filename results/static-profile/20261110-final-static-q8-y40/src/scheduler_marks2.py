"""Root SYS_ADMIN collector, GID1000, dedicated group-writable output only; no GPU work."""

import json
from pathlib import Path
import time
import torch

root = Path("/scheduler")


def anchor(tag):
    name = f"clock:scheduler:{tag}:{time.perf_counter_ns()}"
    pre = time.perf_counter_ns()
    wall_pre = time.time_ns()
    torch.cuda.nvtx.mark(name)
    wall_post = time.time_ns()
    post = time.perf_counter_ns()
    record = {
        "name": name,
        "tag": tag,
        "model": "scheduler",
        "pre_ns": pre,
        "post_ns": post,
        "wall_pre_ns": wall_pre,
        "wall_post_ns": wall_post,
    }
    with (root / "clocks.jsonl").open("a") as f:
        f.write(json.dumps(record) + "\n")


anchor("capture-start")
(root / "ready").write_text(str(time.perf_counter_ns()))
deadline = time.monotonic() + 75
while not (root / "stop").exists():
    if time.monotonic() > deadline:
        raise TimeoutError("Scheduler collector stop")
    anchor("periodic")
    time.sleep(0.5)
anchor("capture-stop")
