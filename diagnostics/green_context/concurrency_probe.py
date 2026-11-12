"""Fixed arithmetic work: compare one process/two threads and two CUDA processes."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import threading
import time


def overlap_ratios(first, second, both):
    if any(not math.isfinite(x) or x <= 0 for x in (first, second, both)):
        raise ValueError("positive finite timings required")
    return {
        "both_over_sum": both / (first + second),
        "both_over_max": both / max(first, second),
    }


def worker(root, index):
    import green_bridge

    pair = green_bridge.GreenPair(16)
    try:
        pair.fixed_work(index, 1000)
        (root / f"{index}.ready").write_text("ready")
        deadline = time.monotonic() + 30
        while not (root / f"{index}.solo-go").exists():
            if time.monotonic() > deadline:
                raise TimeoutError("solo barrier")
            time.sleep(0.001)
        solo = [pair.fixed_work(index, 20000000) for _ in range(3)]
        (root / f"{index}.solo.json").write_text(json.dumps({"solo_ms": solo}))
        while not (root / "go").exists():
            if time.monotonic() > deadline:
                raise TimeoutError("start")
            time.sleep(0.001)
        start = time.perf_counter_ns()
        duration = pair.fixed_work(index, 20000000)
        (root / f"{index}.json").write_text(
            json.dumps(
                {
                    "solo_ms": solo,
                    "concurrent_call_ms": duration,
                    "start_ns": start,
                    "end_ns": time.perf_counter_ns(),
                }
            )
        )
        while not (root / f"{1 - index}.json").exists():
            if time.monotonic() > deadline:
                raise TimeoutError("end")
            time.sleep(0.001)
    finally:
        pair.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--worker", type=int)
    a = p.parse_args()
    if a.worker is not None:
        worker(a.output, a.worker)
        return
    import green_bridge

    a.output.mkdir(exist_ok=False)
    result = {
        "scope": "fixed-work synthetic concurrency probe; not model performance or a guarantee"
    }
    pair = green_bridge.GreenPair(16)
    try:
        for index in (0, 1):
            pair.fixed_work(index, 1000)
        solo = [
            statistics.median(pair.fixed_work(index, 20000000) for _ in range(3))
            for index in (0, 1)
        ]
        measurements = []
        for _ in range(3):
            barrier = threading.Barrier(3)

            def job(index):
                barrier.wait()
                return pair.fixed_work(index, 20000000)

            with ThreadPoolExecutor(2) as pool:
                f = [pool.submit(job, index) for index in (0, 1)]
                barrier.wait()
                started = time.perf_counter()
                calls = [v.result() for v in f]
                elapsed = (time.perf_counter() - started) * 1000
            measurements.append(
                {
                    "calls_ms": calls,
                    "wall_ms": elapsed,
                    **overlap_ratios(*solo, elapsed),
                }
            )
        result["one_process"] = {"solo_median_ms": solo, "runs": measurements}
    finally:
        pair.close()
    rounds = []
    for i in range(3):
        root = a.output / str(i)
        root.mkdir()
        children = [
            subprocess.Popen(
                [
                    sys.executable,
                    __file__,
                    "--output",
                    str(root),
                    "--worker",
                    str(index),
                ]
            )
            for index in (0, 1)
        ]
        try:
            deadline = time.monotonic() + 30
            while not all((root / f"{index}.ready").exists() for index in (0, 1)):
                if time.monotonic() > deadline:
                    raise TimeoutError("ready")
                time.sleep(0.001)
            for index in (0, 1):
                (root / f"{index}.solo-go").write_text("start")
                while not (root / f"{index}.solo.json").exists():
                    if time.monotonic() > deadline:
                        raise TimeoutError("solo complete")
                    time.sleep(0.001)
            (root / "go").write_text("start")
            for child in children:
                if child.wait(timeout=30):
                    raise RuntimeError("worker failed")
            records = [
                json.loads((root / f"{index}.json").read_text()) for index in (0, 1)
            ]
            first, second = [statistics.median(r["solo_ms"]) for r in records]
            overlap_wall = (
                max(r["end_ns"] for r in records) - min(r["start_ns"] for r in records)
            ) / 1e6
            rounds.append(
                {
                    "records": records,
                    "union_wall_ms": overlap_wall,
                    **overlap_ratios(first, second, overlap_wall),
                }
            )
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                    child.wait()
    result["two_processes"] = rounds
    result["state"] = "PASS"
    (a.output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
