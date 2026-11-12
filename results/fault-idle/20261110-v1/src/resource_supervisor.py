"""Bounded resource sampler, cleaned when the owned fault controller finishes."""

import json
from pathlib import Path
import subprocess
import time

root = Path.home() / "cj-fault-idle/20261110-v1"
with (root / "logs/host-monitor.log").open("x") as log:
    p = subprocess.Popen(
        [
            "python3",
            str(root / "src/monitor_host.py"),
            "--output",
            str(root / "verification/host-resources.jsonl"),
            "--interval",
            "1",
        ],
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 2400
        while time.monotonic() < deadline:
            try:
                v = json.loads(
                    (root / "verification/controller-status.json").read_text()
                )
            except (FileNotFoundError, json.JSONDecodeError):
                v = {}
            if v.get("phase") == "finished":
                break
            if p.poll() is not None:
                raise RuntimeError("Resource sampler exited unexpectedly")
            time.sleep(1)
    finally:
        p.terminate()
        try:
            p.wait(timeout=8)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
