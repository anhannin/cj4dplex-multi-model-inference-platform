"""Generate separate source copies and preserve baseline code."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from generate import render_burst_node

p = argparse.ArgumentParser()
p.add_argument("--repo", type=Path, required=True)
p.add_argument("--output", type=Path, required=True)
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=True)
for model in ("qwen", "yolo"):
    with (a.output / (model + "_burst_node.py")).open("x") as f:
        f.write(
            render_burst_node(
                (a.repo / "ros2" / (model + "_node.py")).read_text(), model
            )
        )
