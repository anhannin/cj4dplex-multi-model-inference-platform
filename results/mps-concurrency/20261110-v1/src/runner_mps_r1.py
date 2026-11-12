"""Additional Q16/Y32 capture: disambiguate overlapping spans with GPU scheduling/SM metrics."""

import json
import signal
import subprocess
import threading
import time

import runner as original
import burst_runner as base
from overlay import with_mps

ROOT = original.ROOT
CASE = "mps-green-q16-y32-r1"


_stock_template = original.burst_template


def mps_template(*args, **kwargs):
    return with_mps(_stock_template(*args, **kwargs), str(ROOT / "mps-pipe"))


original.burst_template = mps_template
_stock_batch = base.batch


def membership(label):
    import os

    env = {**os.environ, "CUDA_MPS_PIPE_DIRECTORY": str(ROOT / "mps-pipe")}
    servers = base.run(
        ["nvidia-cuda-mps-control"],
        input="get_server_list\n",
        env=env,
        capture_output=True,
    ).stdout
    clients = {}
    for server in servers.split():
        if server.isdigit():
            clients[server] = base.run(
                ["nvidia-cuda-mps-control"],
                input=f"get_client_list {server}\n",
                env=env,
                capture_output=True,
            ).stdout
    info = {"servers": servers, "clients": clients}
    (ROOT / "verification" / (label + "-mps-membership.json")).write_text(
        json.dumps(info, indent=2)
    )
    assert len(clients) == 1 and len(next(iter(clients.values())).split()) == 2, info


def attached_batch(label, *args, **kwargs):
    membership(label)
    return _stock_batch(label, *args, **kwargs)


base.batch = attached_batch


def main():
    def interrupted(*args):
        raise KeyboardInterrupt()

    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    assert (
        json.loads((ROOT / "verification/controller-status.json").read_text())[
            "restoration"
        ]
        == "PASS"
    )
    assert (ROOT / "workload.json").is_file()
    assert (
        __import__("pathlib").Path.home() / "cj-containers/assets/bus.jpg"
    ).is_file()
    backups = {
        m: json.loads((ROOT / "backup" / f"{m}.json").read_text())
        for m in original.MODELS
    }
    for m in original.MODELS:
        actual = json.loads(
            base.k("get", "deployment", m, "-o", "json", capture_output=True).stdout
        )
        assert (
            actual["spec"]["template"] == backups[m]["spec"]["template"]
            and actual["spec"]["replicas"] == backups[m]["spec"]["replicas"]
        )
    state = {
        "state": "RUNNING",
        "scope": "additional diagnostic scheduling/aggregate GPU metrics; rootCAP_SYS_ADMIN only collector; model Pods unchanged UID1000",
        "start_wall_ns": time.time_ns(),
    }
    file = ROOT / "verification/controller-mps-r1-status.json"

    def save():
        file.write_text(json.dumps(state, indent=2))

    collector = None
    client = None
    errors = []
    save()
    try:
        original.apply(backups, CASE, True)
        base.batch(CASE + "-warmup", 16, 32, True, True)
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
                    if "_overlap_node.py" in line or "nvidia-cuda-mps-server" in line
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
                    base.batch(CASE + "-burst", 16, 32, True, False)
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
