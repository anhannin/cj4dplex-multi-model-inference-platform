#!/usr/bin/env python3
"""Spark-native two-Pod real kernel traces with common monotonic clock anchors."""

import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time

import burst_runner as base
from generate import burst_template

ROOT = Path(os.environ["KERNEL_OVERLAP_ROOT"])
assert base.ROOT == ROOT
MODELS = ("qwen", "yolo")


def save(state):
    (ROOT / "verification/controller-status.json").write_text(
        json.dumps(state, indent=2)
    )


def wait(predicate, seconds, label):
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() > deadline:
            raise TimeoutError(label)
        time.sleep(0.05)


def apply(backups, case, enabled):
    qsm, ysm = (16, 32) if enabled else (48, 48)
    for model in MODELS:
        t = burst_template(
            backups[model]["spec"]["template"],
            model,
            qsm,
            ysm,
            str(ROOT),
            case,
            enabled,
        )
        c = t["spec"]["containers"][0]
        for item in c["env"]:
            if item["name"] == "ROS_DOMAIN_ID":
                item["value"] = "76"
        c["command"] = ["/bin/bash", "/experiment/src/launch_profile.sh", model, case]
        # launch script forwards original experimental queue capacities explicitly.
        patch = ROOT / "verification" / f"{case}-{model}-patch.json"
        patch.write_text(
            json.dumps(
                [
                    {"op": "replace", "path": "/spec/template", "value": t},
                    {"op": "replace", "path": "/spec/replicas", "value": 1},
                ]
            )
        )
        base.k(
            "patch",
            "deployment",
            model,
            "--type=json",
            "--patch-file",
            str(patch),
            stdout=subprocess.DEVNULL,
        )
    for model in MODELS:
        base.k(
            "rollout", "status", "deployment/" + model, "--timeout=750s", timeout=770
        )
    meta = {}
    for model in MODELS:
        candidates = [
            json.loads(p.read_text())
            for p in (ROOT / "metadata").glob(case + "-" + model + "-*.json")
        ]
        assert candidates
        meta[model] = max(candidates, key=lambda r: r["time_ns"])
        assert meta[model]["enabled"] == enabled and meta[model]["selected_sms"] == (
            qsm if model == "qwen" else ysm
        )
        code = "import json,os,time;print(json.dumps({'ns':os.readlink('/proc/self/ns/time'),'offsets':open('/proc/self/timens_offsets').read(),'clock':time.get_clock_info('perf_counter').implementation}))"
        clock = json.loads(
            base.k(
                "exec",
                "deployment/" + model,
                "--",
                "python3",
                "-c",
                code,
                capture_output=True,
            ).stdout
        )
        host = {
            "ns": os.readlink("/proc/self/ns/time"),
            "offsets": Path("/proc/self/timens_offsets").read_text(),
            "clock": time.get_clock_info("perf_counter").implementation,
        }
        assert clock == host
        meta[model]["clock"] = clock
    if enabled:
        meta["sampled_smid_intersection"] = sorted(
            set(meta["qwen"]["observed_smids"]) & set(meta["yolo"]["observed_smids"])
        )
    (ROOT / "verification" / f"{case}-allocation.json").write_text(
        json.dumps(meta, indent=2)
    )


def flush(case):
    files = {}
    for model in MODELS:
        folder = ROOT / "validation" / case / model
        reports = list(folder.glob("*.nsys-rep"))
        if not reports:
            sessions = json.loads(
                base.k(
                    "exec",
                    "deployment/" + model,
                    "--",
                    "nsys",
                    "sessions",
                    "list",
                    "--output-format=json",
                    capture_output=True,
                ).stdout
            )
            if any(s.get("name") == f"overlap-{case}-{model}" for s in sessions):
                p = subprocess.run(
                    [
                        "kubectl",
                        "-n",
                        "cj-inference",
                        "exec",
                        "deployment/" + model,
                        "--",
                        "nsys",
                        "shutdown",
                        f"--session=overlap-{case}-{model}",
                        "--kill=none",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=240,
                )
                (ROOT / "logs" / f"{case}-{model}-shutdown.log").write_text(
                    p.stdout + p.stderr + f"\nexit={p.returncode}\n"
                )
        wait(
            lambda: bool(list(folder.glob("*.nsys-rep"))), 120, "report flush " + model
        )
        reports = list(folder.glob("*.nsys-rep"))
        assert len(reports) == 1
        files[model] = reports[0]
        command = [
            "docker",
            "run",
            "--rm",
            "--runtime",
            "runc",
            "--network",
            "none",
            "--user",
            "1000:1000",
            "-e",
            "HOME=/tmp",
            "-v",
            str(ROOT) + ":/experiment",
            "--entrypoint",
            "/usr/local/cuda/bin/nsys",
            "cj-qwen-ros:9b-timing-v1",
            "export",
            "--type",
            "sqlite",
            "--ts-normalize=true",
            "--output",
            f"/experiment/validation/{case}/{model}/trace.sqlite",
            f"/experiment/validation/{case}/{model}/{reports[0].name}",
        ]
        with (ROOT / "logs" / f"{case}-{model}-export.log").open("w") as log:
            base.run(command, timeout=600, stdout=log, stderr=subprocess.STDOUT)
    return files


def capture(case, enabled):
    qsm, ysm = (16, 32) if enabled else (48, 48)
    base.batch(case + "-warmup", qsm, ysm, enabled, True)
    gate = ROOT / "control/capture"
    t0file = ROOT / "control/client-t0.json"
    t0file.unlink(missing_ok=True)
    gate.write_text(case)
    for model in MODELS:
        wait(
            lambda m=model: (ROOT / "control" / f"{case}-{m}.started").exists(),
            120,
            "start " + model,
        )
    errors = []

    def client():
        try:
            base.batch(case + "-burst", qsm, ysm, enabled, False)
        except BaseException as e:
            errors.append(e)

    thread = threading.Thread(target=client, daemon=True)
    thread.start()
    try:
        wait(lambda: t0file.exists() or errors, 120, "client barrier")
        if errors:
            raise errors[0]
        t0 = json.loads(t0file.read_text())["t0"]
        wait(
            lambda: time.perf_counter_ns() >= t0 + 20_000_000_000 or errors,
            90,
            "capture20s",
        )
    finally:
        gate.unlink(missing_ok=True)
    for model in MODELS:
        wait(
            lambda m=model: (ROOT / "control" / f"{case}-{m}.stopped").exists(),
            120,
            "stop at request boundary " + model,
        )
    thread.join(timeout=900)
    if thread.is_alive():
        raise TimeoutError("Client failed to drain")
    if errors:
        raise errors[0]
    flush(case)


def positive():
    root = "/experiment/validation/positive"
    (ROOT / "validation/positive").mkdir(exist_ok=True)
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        "cj-overlap-positive",
        "--gpus",
        "all",
        "--network",
        "none",
        "--user",
        "1000:1000",
        "--cap-drop",
        "ALL",
        "-e",
        "HOME=/tmp",
        "-e",
        "PYTHONPATH=/experiment/src",
        "-e",
        "PAIR_LABEL=positive",
        "-v",
        str(ROOT) + ":/experiment",
        "--entrypoint",
        "/usr/local/cuda/bin/nsys",
        "cj-qwen-ros:9b-timing-v1",
        "profile",
        "--trace=cuda,nvtx",
        "--sample=none",
        "--cpuctxsw=none",
        "--capture-range=cudaProfilerApi",
        "--capture-range-end=stop",
        "--output",
        root + "/trace",
        "python",
        "/experiment/src/positive.py",
    ]
    try:
        with (ROOT / "logs/positive.log").open("w") as log:
            base.run(command, timeout=180, stdout=log, stderr=subprocess.STDOUT)
    finally:
        subprocess.run(
            ["docker", "rm", "-f", "cj-overlap-positive"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    command = [
        "docker",
        "run",
        "--rm",
        "--runtime",
        "runc",
        "--network",
        "none",
        "--user",
        "1000:1000",
        "-e",
        "HOME=/tmp",
        "-v",
        str(ROOT) + ":/experiment",
        "--entrypoint",
        "/usr/local/cuda/bin/nsys",
        "cj-qwen-ros:9b-timing-v1",
        "export",
        "--type",
        "sqlite",
        "--ts-normalize=true",
        "--output",
        root + "/trace.sqlite",
        root + "/trace.nsys-rep",
    ]
    with (ROOT / "logs/positive-export.log").open("w") as log:
        base.run(command, timeout=300, stdout=log, stderr=subprocess.STDOUT)


def main():
    def interrupted(*args):
        raise KeyboardInterrupt()

    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    for name in (
        "qwen_overlap_node.py",
        "yolo_overlap_node.py",
        "client.py",
        "clock_marks.py",
    ):
        file = ROOT / "src" / name
        assert file.exists()
        compile(file.read_text(), name, "exec")
    backups = {
        m: json.loads((ROOT / "backup" / f"{m}.json").read_text()) for m in MODELS
    }
    for model in MODELS:
        actual = json.loads(
            base.k("get", "deployment", model, "-o", "json", capture_output=True).stdout
        )
        assert (
            actual["spec"]["template"] == backups[model]["spec"]["template"]
            and actual["spec"]["replicas"] == backups[model]["spec"]["replicas"]
        )
    assert (
        subprocess.run(
            ["pgrep", "-u", "1000", "-f", "^nvidia-cuda-mps-(control|server)"],
            capture_output=True,
        ).returncode
        == 1
    )
    state = {
        "state": "RUNNING",
        "start_wall_ns": time.time_ns(),
        "completed": [],
        "root": str(ROOT),
        "scope": "diagnostic GPU timeline ONLY, not performance benchmark",
    }
    save(state)
    try:
        for case, enabled in [("q16-y32", True), ("default", False)]:
            state["phase"] = case
            save(state)
            print(
                json.dumps({"event": "start", "case": case, "time": time.time()}),
                flush=True,
            )
            apply(backups, case, enabled)
            capture(case, enabled)
            state["completed"].append(case)
            save(state)
            print(
                json.dumps({"event": "captured", "case": case, "time": time.time()}),
                flush=True,
            )
        positive()
        state["state"] = "PASS"
    except BaseException as error:
        state.update(state="FAIL", error=repr(error))
        save(state)
        raise
    finally:
        (ROOT / "control/capture").unlink(missing_ok=True)
        try:
            base.restore(backups)
            state["restoration"] = "PASS"
        except BaseException as error:
            state["restoration"] = repr(error)
            raise
        finally:
            state["end_wall_ns"] = time.time_ns()
            save(state)
    print(json.dumps(state), flush=True)


if __name__ == "__main__":
    main()
