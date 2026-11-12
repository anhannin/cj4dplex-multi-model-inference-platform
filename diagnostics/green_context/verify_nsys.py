"""Require CUPTI greenContextId, not just a hand-written NVTX label."""

import argparse
import json
from pathlib import Path
import sqlite3


def verify_window(connection, label):
    ranges = connection.execute(
        "SELECT start,end FROM NVTX_EVENTS WHERE text=?", (label,)
    ).fetchall()
    assert len(ranges) == 1, (label, ranges)
    lo, hi = ranges[0]
    rows = connection.execute(
        "SELECT start,end,greenContextId FROM CUPTI_ACTIVITY_KIND_KERNEL WHERE start<? AND end>?",
        (hi, lo),
    ).fetchall()
    assert rows, "No CUDA kernels in the model range"
    assert all(lo <= start and end <= hi for start, end, _ in rows), (
        "GPU work crosses instrumentation boundary"
    )
    assert all(green not in (None, 0) for _, _, green in rows), (
        "Model kernel escaped to primary context"
    )
    groups = {}
    for _, _, green in rows:
        groups[green] = groups.get(green, 0) + 1
    return {
        "state": "PASS",
        "all_model_roi_kernels_green": True,
        "kernel_groups": [
            {"greenContextId": k, "kernels": v} for k, v in sorted(groups.items())
        ],
        "roi_ms": (hi - lo) / 1e6,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("root", type=Path)
    a = p.parse_args()
    output = {}
    for model, name, label in (
        ("qwen", "qwen-green16", "qwen.green.generate"),
        ("yolo", "yolo-green16", "yolo.green.predict"),
    ):
        c = sqlite3.connect(a.root / (name + ".sqlite"))
        output[model] = verify_window(c, label)
        c.close()
    (a.root / "model-green-coverage.json").write_text(
        json.dumps(output, indent=2) + "\n"
    )
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
