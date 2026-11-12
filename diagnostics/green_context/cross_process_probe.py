"""Empirical SM-ID mapping across fresh processes; not a global reservation proof."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import green_bridge


def worker(root, index):
    pair = green_bridge.GreenPair(16)
    try:
        (root / f"{index}.ready").write_text("ready")
        deadline = time.monotonic() + 30
        while not (root / "go").exists():
            if time.monotonic() > deadline:
                raise TimeoutError("start barrier")
            time.sleep(0.01)
        ids = set()
        for _ in range(10):
            ids.update(pair.sample_smids(index))
        part = pair.metadata()["parts"][index]
        result = {
            "index": index,
            "actual_sms": part["actual_sms"],
            "smids": sorted(ids),
        }
        (root / f"{index}.json").write_text(json.dumps(result))
        while not (root / f"{1 - index}.json").exists():
            if time.monotonic() > deadline:
                raise TimeoutError("end barrier")
            time.sleep(0.01)
    finally:
        pair.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--worker", type=int)
    p.add_argument("--root", type=Path)
    a = p.parse_args()
    if a.worker is not None:
        worker(a.root, a.worker)
        return
    a.output.mkdir(exist_ok=False)
    rounds = []
    for i, order in enumerate(((0, 1), (1, 0), (0, 1))):
        root = a.output / str(i)
        root.mkdir()
        children = []
        try:
            for index in order:
                children.append(
                    subprocess.Popen(
                        [
                            sys.executable,
                            __file__,
                            "--output",
                            str(a.output),
                            "--root",
                            str(root),
                            "--worker",
                            str(index),
                        ]
                    )
                )
                deadline = time.monotonic() + 20
                while not (root / f"{index}.ready").exists():
                    if time.monotonic() > deadline:
                        raise TimeoutError("context ready")
                    time.sleep(0.01)
            (root / "go").write_text("start")
            for child in children:
                if child.wait(timeout=30):
                    raise RuntimeError("probe process failed")
            parts = [
                json.loads((root / f"{index}.json").read_text()) for index in (0, 1)
            ]
            overlap = sorted(set(parts[0]["smids"]).intersection(parts[1]["smids"]))
            rounds.append(
                {
                    "creation_order": list(order),
                    "parts": parts,
                    "overlapping_observed_ids": overlap,
                }
            )
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                    child.wait()
    result = {
        "state": "PASS",
        "scope": "empirical mapping only; no global/exclusive SM reservation claim",
        "rounds": rounds,
        "all_rounds_observed_disjoint": all(
            not r["overlapping_observed_ids"] for r in rounds
        ),
    }
    (a.output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
