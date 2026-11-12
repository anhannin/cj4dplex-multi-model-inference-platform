"""Low-rate host sampling; GB10 GPU memory N/A is recorded, never converted to zero."""

import argparse
import json
from pathlib import Path
import signal
import subprocess
import time

p = argparse.ArgumentParser()
p.add_argument("--output", type=Path, required=True)
p.add_argument("--interval", type=float, default=1)
a = p.parse_args()
running = True


def stop(*_):
    global running
    running = False


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
previous = None
with a.output.open("x") as stream:
    while running:
        row = {"wall_ns": time.time_ns(), "monotonic_ns": time.perf_counter_ns()}
        cpu = list(map(int, Path("/proc/stat").read_text().splitlines()[0].split()[1:]))
        total = sum(cpu[:8])
        idle = cpu[3] + cpu[4]
        if previous:
            dt = total - previous[0]
            row["host_cpu_percent"] = (
                100 * (1 - (idle - previous[1]) / dt) if dt else None
            )
        previous = (total, idle)
        mem = {
            k: int(v.split()[0]) * 1024
            for k, v in (
                line.split(":", 1)
                for line in Path("/proc/meminfo").read_text().splitlines()
            )
        }
        row.update(
            memory_total_bytes=mem["MemTotal"],
            memory_available_bytes=mem["MemAvailable"],
        )
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,temperature.gpu,power.draw,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=3,
            )
            row["gpu_query_csv"] = result.stdout.strip()
            row["gpu_query_returncode"] = result.returncode
        except Exception as error:
            row["gpu_query_error"] = type(error).__name__
        stream.write(json.dumps(row) + "\n")
        stream.flush()
        time.sleep(a.interval)
