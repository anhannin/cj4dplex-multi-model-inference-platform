"""Create fresh profiling copies from the already measured exact burst implementation."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from generate import instrument

p = argparse.ArgumentParser()
p.add_argument("--repo", type=Path, required=True)
p.add_argument("--output", type=Path, required=True)
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=True)
for model in ("qwen", "yolo"):
    source = (
        a.repo / "results/green-burst/20261109-v1-generated" / f"{model}_burst_node.py"
    ).read_text()
    code = instrument(source, model)
    compile(code, "profiled", "exec")
    with (a.output / f"{model}_overlap_node.py").open("x") as f:
        f.write(code)
source = (a.repo / "diagnostics/green_burst/client.py").read_text()
source = (
    source.replace("=='74'", "=='76'")
    .replace('== "74"', '== "76"')
    .replace('"ros_domain": 74', '"ros_domain": 76')
)
start = """        barrier = threading.Barrier(
            3,
            action=lambda: barrier_time.update(
                t0=time.perf_counter_ns(), wall_ns=time.time_ns()
            ),
        )"""
# Keep other logic byte-identical; only add a diagnostic barrier marker for controller capture duration.
if start not in source:
    raise RuntimeError("Review frozen burst barrier source before instrumentation")
replacement = """        def release_barrier():
            barrier_time.update(t0=time.perf_counter_ns(), wall_ns=time.time_ns())
            file=a.root/"control/client-t0.new"
            file.write_text(json.dumps(barrier_time))
            file.replace(a.root/"control/client-t0.json")
        barrier = threading.Barrier(3, action=release_barrier)"""
source = source.replace(start, replacement)
with (a.output / "client.py").open("x") as f:
    f.write(source)
