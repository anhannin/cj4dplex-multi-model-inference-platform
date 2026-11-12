"""Tool positive/negative controls only: synthetic kernel intervals, not model performance."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
import torch
import green_bridge
from clock_marks import anchor

pair = green_bridge.GreenPair(16)
try:
    for index in (0, 1):
        pair.fixed_work(index, 1000)
    torch.cuda.profiler.start()
    anchor("positive", "capture-start")
    serial = []
    for index in (0, 1):
        with torch.cuda.nvtx.range("control.serial" + str(index)):
            serial.append(pair.fixed_work(index, 20000000))
    anchor("positive", "after-serial")
    barrier = threading.Barrier(3)

    def job(index):
        pair.fixed_work(index, 1000)
        barrier.wait()
        with torch.cuda.nvtx.range("control.parallel" + str(index)):
            return pair.fixed_work(index, 20000000)

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(job, index) for index in (0, 1)]
        anchor("positive", "before-parallel")
        barrier.wait()
        parallel = [f.result() for f in futures]
    anchor("positive", "capture-stop")
    torch.cuda.profiler.stop()
    Path("/experiment/verification/positive.json").write_text(
        json.dumps(
            {
                "serial_calls_ms": serial,
                "parallel_calls_ms": parallel,
                "scope": "synthetic tool concurrency validation only;not model performance/equal-total-work claim",
            },
            indent=2,
        )
    )
finally:
    pair.close()
