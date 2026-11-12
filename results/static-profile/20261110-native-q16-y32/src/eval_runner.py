"""Native595, noGreen, fixed-work35trial complete-block experiment with restoration."""

import fcntl
import json
import os
import signal
import subprocess
import time
from pathlib import Path
import base_runner as base
import control_runner as common
from config import parse_partition
from plan import schedule, condition_template
from runtime import live_daemon_pid

ROOT = Path(os.environ["GREEN_BURST_ROOT"])
PIPE = ROOT / "eval-pipe"
common.PIPE = PIPE
assert common.ROOT == base.ROOT == ROOT


def ctl(command, pipe=PIPE, check=True):
    r = subprocess.run(
        ["/usr/bin/nvidia-cuda-mps-control"],
        input=command + "\n",
        env={**os.environ, "CUDA_MPS_PIPE_DIRECTORY": str(pipe)},
        text=True,
        capture_output=True,
        timeout=20,
    )
    if check and r.returncode:
        raise RuntimeError(f"MPS control failed: {command}: {r.stderr}")
    return r.stdout


def stop_daemon(pipe=PIPE):
    if live_daemon_pid(pipe) is None:
        return
    servers = ctl("get_server_list", pipe).split()
    for pid in servers:
        assert not ctl("get_client_list " + pid, pipe).split(), (
            "Refuse stopping active MPS clients"
        )
    ctl("quit", pipe)
    deadline = time.monotonic() + 20
    while live_daemon_pid(pipe) is not None:
        if time.monotonic() > deadline:
            raise TimeoutError("MPS daemon exit")
        time.sleep(0.1)


def stop_models():
    base.k(
        "scale",
        "deployment/qwen",
        "deployment/yolo",
        "--replicas=0",
        stdout=subprocess.DEVNULL,
    )
    for m in ("qwen", "yolo"):
        base.k(
            "wait",
            "--for=delete",
            "pod",
            "-l",
            "app=" + m,
            "--timeout=360s",
            timeout=380,
        )


def configure(entry):
    stop_models()
    stop_daemon()
    PIPE.mkdir(exist_ok=True)
    PIPE.chmod(0o700)
    out = {
        "case": entry,
        "parts": {},
        "native_driver": True,
        "green": False,
        "actual_chunk_sms": 2,
    }
    if entry["mps"]:
        logs = ROOT / "logs" / ("mps-" + entry["label"])
        logs.mkdir()
        env = {
            **os.environ,
            "CUDA_MPS_PIPE_DIRECTORY": str(PIPE),
            "CUDA_MPS_LOG_DIRECTORY": str(logs),
        }
        args = ["/usr/bin/nvidia-cuda-mps-control", "-d"] + (
            ["-S"] if entry["static"] else []
        )
        base.run(args, env=env, capture_output=True)
        deadline = time.monotonic() + 20
        while True:
            if live_daemon_pid(PIPE) is not None:
                probe = subprocess.run(
                    ["/usr/bin/nvidia-cuda-mps-control"],
                    input="get_server_list\n",
                    env=env,
                    text=True,
                    capture_output=True,
                    timeout=5,
                )
                if probe.returncode == 0:
                    break
            if time.monotonic() > deadline:
                raise TimeoutError("MPS daemon readiness")
            time.sleep(0.1)
        if entry["static"]:
            uuid = base.run(
                ["nvidia-smi", "--query-gpu=uuid", "--format=csv,noheader"],
                capture_output=True,
            ).stdout.strip()
            raw = {}
            for m, sm in (("qwen", entry["qsm"]), ("yolo", entry["ysm"])):
                raw[m] = ctl(f"sm_partition add {uuid} {sm // 2}")
                out["parts"][m] = parse_partition(raw[m])
            excess = ctl(f"sm_partition add {uuid} 1")
            assert "Failed to create partition" in excess, (
                "Oversubscription was not rejected"
            )
            out.update(raw=raw, overallocate_output=excess)
    (ROOT / "verification" / f"{entry['label']}-partitions.json").write_text(
        json.dumps(out, indent=2)
    )
    return out["parts"]


def apply(entry, originals):
    parts = configure(entry)

    def template(original, model, qsm, ysm, root, label, enabled):
        return condition_template(original, model, entry, root, label, str(PIPE), parts)

    base.burst_template = template
    base.apply(originals, entry["label"], entry["qsm"], entry["ysm"], False)
    common.membership(entry["label"] + "-pre", True) if entry["mps"] else check_no_mps(
        entry["label"] + "-pre"
    )
    for m in ("qwen", "yolo"):
        rows = [
            json.loads(p.read_text())
            for p in (ROOT / "metadata").glob(entry["label"] + "-" + m + "-*.json")
        ]
        meta = max(rows, key=lambda x: x["time_ns"])
        assert meta["cuda_runtime"] == 13010 and meta["torch_build_cuda"] == "13.0"
        assert meta["partition_id"] == parts.get(m)
    return parts


def check_no_mps(label):
    assert live_daemon_pid(PIPE) is None
    assert (
        subprocess.run(
            ["pgrep", "-x", "nvidia-cuda-mps-control"], capture_output=True
        ).returncode
        == 1
    ), "Unexpected MPS daemon contaminates control"
    (ROOT / "verification" / f"{label}-mps-membership.json").write_text(
        json.dumps(
            {"expected_mps": False, "clients": [], "models": common.model_processes()}
        )
    )


def restore(backups):
    stop_models()
    stop_daemon()
    base.run(["systemctl", "--user", "enable", "--now", "cj-cuda-mps.service"])
    base.restore(backups)
    old = common.PIPE
    common.PIPE = Path.home() / "cj-serving/mps-green-v1/mps-pipe"
    try:
        info = common.membership("restored-serving", True, True)
    finally:
        common.PIPE = old
    return info


def main():
    def interrupted(*args):
        raise KeyboardInterrupt()

    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    lock = (Path.home() / ".cache/cj-gpu-experiment.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    backups = {
        m: json.loads((ROOT / "backup" / f"{m}.json").read_text())
        for m in ("qwen", "yolo")
    }
    originals = {
        m: json.loads((ROOT / "baseline" / f"{m}.json").read_text()) for m in backups
    }
    base.run(["python3", "-c", "import rclpy"], capture_output=True)
    assert (ROOT / "workload.json").is_file() and (
        Path.home() / "cj-containers/assets/bus.jpg"
    ).is_file()
    assert (ROOT / "verification/docker-native-summary.json").is_file()
    assert subprocess.run(["pgrep", "-x", "nsys"], capture_output=True).returncode == 1
    assert (
        base.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True,
        ).stdout.strip()
        == "595.99.02"
    )
    for m in backups:
        assert "green_bridge" not in (ROOT / "src" / f"{m}_burst_node.py").read_text()
    plan = schedule()
    (ROOT / "schedule.json").write_text(json.dumps(plan, indent=2))
    state = {
        "state": "RUNNING",
        "started_wall_ns": time.time_ns(),
        "pid": os.getpid(),
        "total_trials": 35,
        "completed": [],
        "green": False,
        "driver": "595.99.02",
        "actual_cuda_runtime": 13010,
    }

    def save():
        (ROOT / "verification/controller-status.json").write_text(
            json.dumps(state, indent=2)
        )

    monitor = None
    log = None
    save()
    try:
        stop_daemon(ROOT / "native-pipe")
        log = (ROOT / "logs/host-monitor.log").open("w")
        monitor = subprocess.Popen(
            [
                "python3",
                str(ROOT / "src/monitor_host.py"),
                "--output",
                str(ROOT / "verification/host-samples.jsonl"),
                "--interval",
                "1",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        common.alert(
            "CJ native595 정적MPS 성능 비교 시작: Green없이7설정×5회, 동시Q10/Y300. 약3시간 예상. baseline/일반MPS/고정SM5조합. "
            + str(ROOT)
        )
        for index, entry in enumerate(plan):
            state.update(index=index, current=entry, phase="apply")
            save()
            apply(entry, originals)
            state["phase"] = "warmup"
            save()
            base.batch(
                entry["label"] + "-warmup", entry["qsm"], entry["ysm"], False, True
            )
            common.membership(entry["label"] + "-warm", True) if entry[
                "mps"
            ] else check_no_mps(entry["label"] + "-warm")
            state["phase"] = "measure"
            save()
            result = base.batch(
                entry["label"], entry["qsm"], entry["ysm"], False, False
            )
            common.membership(entry["label"] + "-post", True) if entry[
                "mps"
            ] else check_no_mps(entry["label"] + "-post")
            assert monitor.poll() is None
            state["completed"].append(
                {**entry, "summary": result, "finished_wall_ns": time.time_ns()}
            )
            state["phase"] = "drained"
            save()
            print(
                json.dumps(
                    {
                        "event": "trial_complete",
                        "index": index,
                        "case": entry,
                        "summary": result,
                    }
                ),
                flush=True,
            )
            if (index + 1) % 7 == 0:
                common.alert(
                    f"CJ 정적MPS {(index + 1) // 7}/5라운드 완료({index + 1}/35). 요청누락없이처리. "
                    + str(ROOT)
                )
        state["state"] = "PASS"
    except BaseException as error:
        state.update(state="FAIL", error=repr(error))
        save()
        common.alert(
            "CJ 정적MPS 비교 오류: " + repr(error) + ". 서빙복원진행. " + str(ROOT)
        )
        raise
    finally:
        try:
            state["phase"] = "restore"
            save()
            state["serving_membership"] = restore(backups)
            state["restoration"] = "PASS"
        except BaseException as e:
            state["restoration"] = repr(e)
            common.alert("CJ 정적MPS 서빙복원확인실패: " + repr(e))
            raise
        finally:
            if monitor is not None:
                monitor.terminate()
                try:
                    monitor.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    monitor.kill()
                    monitor.wait()
            if log is not None:
                log.close()
            state.update(end_wall_ns=time.time_ns(), phase="finished")
            save()
            common.alert(
                f"CJ 정적MPS 측정 종료: {state['state']}, {len(state['completed'])}/35, 복원{state.get('restoration')}. "
                + str(ROOT)
            )
    print(json.dumps(state), flush=True)


if __name__ == "__main__":
    main()
