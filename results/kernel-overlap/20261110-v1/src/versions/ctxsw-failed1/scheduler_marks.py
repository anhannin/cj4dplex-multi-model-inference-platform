"""System-scope GPU scheduler/metrics collector clock marks; no model or GPU kernels."""

import os
from pathlib import Path
import time
from clock_marks import anchor

case = os.environ["PAIR_LABEL"]
root = Path("/experiment/control")
anchor("scheduler", "capture-start")
(root / (case + "-scheduler.ready")).write_text(str(time.perf_counter_ns()))
end = time.monotonic() + 75
while not (root / (case + "-scheduler.stop")).exists():
    if time.monotonic() > end:
        raise TimeoutError("Scheduler stop gate")
    anchor("scheduler", "periodic")
    time.sleep(0.5)
anchor("scheduler", "capture-stop")
