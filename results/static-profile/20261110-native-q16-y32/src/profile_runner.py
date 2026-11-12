"""Additional Q16/Y32 capture: disambiguate overlapping spans with GPU scheduling/SM metrics."""

import json
import signal
import subprocess
import threading
import time
from pathlib import Path

import trace_owner as original
import burst_runner as base
import eval_runner as native
from plan import CONDITIONS

ROOT = original.ROOT
CASE = "native-static-q16-y32"


entry = {"label": CASE, "condition": "static-q16-y32", **CONDITIONS["static-q16-y32"]}
stock_template = native.condition_template


def profile_template(*args, **kwargs):
    t = stock_template(*args, **kwargs)
    c = t["spec"]["containers"][0]
    for e in c["env"]:
        if e["name"] == "ROS_DOMAIN_ID":
            e["value"] = "76"
    c["command"] = ["/bin/bash", "/experiment/src/launch_profile.sh", args[1], CASE]
    return t


native.condition_template = profile_template


def apply_native(backups, case, enabled):
    assert not enabled
    originals = {
        m: json.loads((ROOT / "baseline" / f"{m}.json").read_text())
        for m in ("qwen", "yolo")
    }
    return native.apply(entry, originals)


original.apply = apply_native
base.restore = native.restore


def main():
    def interrupted(*args):
        raise KeyboardInterrupt()

    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    import fcntl

    lock = (Path.home() / ".cache/cj-gpu-experiment.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    backups = {
        m: json.loads((ROOT / "backup" / f"{m}.json").read_text())
        for m in original.MODELS
    }
    native = json.loads((ROOT / "verification/docker-native-summary.json").read_text())
    assert len(native) == 2 and {r["sms"] for r in native} == {16, 32}
    state = {
        "state": "RUNNING",
        "scope": "Native595 static MPS16/32; NO Green; pairedactualmodels; diagnosticprofileonly",
        "start_wall_ns": time.time_ns(),
    }
    file = ROOT / "verification/profile-status.json"

    def save():
        file.write_text(json.dumps(state, indent=2))

    collector = None
    client = None
    errors = []
    save()
    try:
        original.apply(backups, CASE, False)
        base.batch(CASE + "-warmup", 16, 32, False, True)
        folder = ROOT / "validation" / CASE / "scheduler"
        folder.mkdir(parents=True)
        folder.chmod(0o770)
        stop = folder / "stop"
        stop.unlink(missing_ok=True)
        command = [
            "docker",
            "run",
            "--rm",
            "--name",
            "cj-overlap-scheduler",
            "--gpus",
            "all",
            "--network",
            "none",
            "--user",
            "0:1000",
            "--cap-drop",
            "ALL",
            "--cap-add",
            "SYS_ADMIN",
            "-e",
            "HOME=/tmp",
            "-e",
            "PYTHONPATH=/src",
            "-e",
            "PAIR_LABEL=" + CASE,
            "-v",
            str(ROOT / "src") + ":/src:ro",
            "-v",
            str(folder) + ":/scheduler",
            "--entrypoint",
            "/usr/local/cuda/bin/nsys",
            "cj-qwen-ros:9b-timing-v1",
            "profile",
            "--trace=nvtx",
            "--gpuctxsw=true",
            "--gpu-metrics-devices=0",
            "--gpu-metrics-set=gb20b",
            "--gpu-metrics-frequency=10000",
            "--sample=none",
            "--cpuctxsw=none",
            "--output",
            "/scheduler/trace",
            "python",
            "/src/scheduler_marks2.py",
        ]
        with (ROOT / "logs/scheduler.log").open("w") as log:
            collector = subprocess.Popen(
                command, stdout=log, stderr=subprocess.STDOUT, text=True
            )
            original.wait(
                lambda: (folder / "ready").exists() or collector.poll() is not None,
                60,
                "scheduler ready",
            )
            assert collector.poll() is None, "Scheduler collector failed before ready"
            (ROOT / "verification" / f"{CASE}-host-processes.txt").write_text(
                "\n".join(
                    line
                    for line in base.run(
                        ["ps", "-eo", "pid,uid,comm,args"], capture_output=True
                    ).stdout.splitlines()
                    if "_burst_node.py" in line or "nvidia-cuda-mps-server" in line
                )
            )
            (ROOT / "control/client-t0.json").unlink(missing_ok=True)
            (ROOT / "control/capture").write_text(CASE)
            for m in original.MODELS:
                original.wait(
                    lambda model=m: (
                        ROOT / "control" / f"{CASE}-{model}.started"
                    ).exists(),
                    120,
                    "model capture start",
                )

            def run_client():
                try:
                    base.batch(CASE + "-burst", 16, 32, False, False)
                except BaseException as e:
                    errors.append(e)

            client = threading.Thread(target=run_client, daemon=True)
            client.start()
            original.wait(
                lambda: (ROOT / "control/client-t0.json").exists() or errors,
                120,
                "client t0",
            )
            if errors:
                raise errors[0]
            t0 = json.loads((ROOT / "control/client-t0.json").read_text())["t0"]
            original.wait(
                lambda: time.perf_counter_ns() >= t0 + 20_000_000_000 or errors,
                90,
                "20s capture",
            )
            (ROOT / "control/capture").unlink()
            for m in original.MODELS:
                original.wait(
                    lambda model=m: (
                        ROOT / "control" / f"{CASE}-{model}.stopped"
                    ).exists(),
                    120,
                    "model stop",
                )
            stop.write_text("stop")
            code = collector.wait(timeout=180)
            if code:
                raise RuntimeError(f"Scheduler profiler exit{code}")
            client.join(timeout=900)
            if client.is_alive():
                raise TimeoutError("Client drain")
            if errors:
                raise errors[0]
        original.flush(CASE)
        export = [
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
            f"/experiment/validation/{CASE}/scheduler/trace.sqlite",
            f"/experiment/validation/{CASE}/scheduler/trace.nsys-rep",
        ]
        with (ROOT / "logs/scheduler-export.log").open("w") as log:
            base.run(export, timeout=600, stdout=log, stderr=subprocess.STDOUT)
        folder.chmod(0o700)
        state["state"] = "PASS"
    except BaseException as e:
        state.update(state="FAIL", error=repr(e))
        save()
        raise
    finally:
        (ROOT / "control/capture").unlink(missing_ok=True)
        (ROOT / "validation" / CASE / "scheduler" / "stop").write_text("stop") if (
            ROOT / "validation" / CASE / "scheduler"
        ).exists() else None
        if collector is not None and collector.poll() is None:
            collector.terminate()
            try:
                collector.wait(timeout=10)
            except subprocess.TimeoutExpired:
                collector.kill()
                collector.wait()
        subprocess.run(
            ["docker", "rm", "-f", "cj-overlap-scheduler"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            base.restore(backups)
            state["restoration"] = "PASS"
        except BaseException as e:
            state["restoration"] = repr(e)
            raise
        finally:
            state["end_wall_ns"] = time.time_ns()
            save()
    print(json.dumps(state), flush=True)


if __name__ == "__main__":
    main()
