"""Finite35-burst owner: complete blocks, no profiler, restore current serving in finally."""

import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
import urllib.request

import base_runner as base
from plan import schedule, condition_template, check_membership

ROOT = Path(os.environ["GREEN_BURST_ROOT"])
PIPE = Path.home() / "cj-serving/mps-green-v1/mps-pipe"
assert base.ROOT == ROOT


def alert(message):
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        return
    try:
        urllib.request.urlopen(
            urllib.request.Request(
                url,
                json.dumps({"text": message}).encode(),
                {"Content-Type": "application/json"},
            ),
            timeout=8,
        ).close()
    except Exception:
        pass


def model_processes(serving=False):
    table = base.run(
        ["ps", "-u", "1000", "-o", "pid=,args="], capture_output=True
    ).stdout
    values = {}
    suffix = "green" if serving else "burst"
    for m in ("qwen", "yolo"):
        pattern = re.compile(
            r"^\S*python(?:3(?:\.\d+)?)?\s+/experiment/src/"
            + m
            + "_"
            + suffix
            + r"_node\.py(?:\s|$)"
        )
        matched = [
            int(line.strip().split(None, 1)[0])
            for line in table.splitlines()
            if len(line.strip().split(None, 1)) == 2
            and pattern.match(line.strip().split(None, 1)[1])
        ]
        assert len(matched) == 1, (m, matched)
        values[m] = matched[0]
    return values


def membership(label, enabled, serving=False):
    env = {**os.environ, "CUDA_MPS_PIPE_DIRECTORY": str(PIPE)}
    servers = base.run(
        ["nvidia-cuda-mps-control"],
        input="get_server_list\n",
        env=env,
        capture_output=True,
    ).stdout.split()
    assert len(servers) == 1, servers
    clients = [
        int(v)
        for v in base.run(
            ["nvidia-cuda-mps-control"],
            input=f"get_client_list {servers[0]}\n",
            env=env,
            capture_output=True,
        ).stdout.split()
    ]
    processes = model_processes(serving)
    check_membership(clients, list(processes.values()), enabled)
    value = {
        "server": int(servers[0]),
        "clients": clients,
        "models": processes,
        "expected_mps": enabled,
        "wall_ns": time.time_ns(),
    }
    (ROOT / "verification" / f"{label}-mps-membership.json").write_text(
        json.dumps(value, indent=2)
    )
    return value


def preflight(backups):
    assert (ROOT / "workload.json").is_file()
    assert (Path.home() / "cj-containers/assets/bus.jpg").is_file()
    base.run(["python3", "-c", "import rclpy"], capture_output=True)
    base.run(
        ["systemctl", "--user", "is-active", "cj-cuda-mps.service"], capture_output=True
    )
    # Catch missing helper/native dependencies before replacing any model Pods.
    for file in (
        "qwen_burst_node.py",
        "yolo_burst_node.py",
        "client.py",
        "gpu_observer.py",
        "stage_metrics.py",
        "base_generate.py",
        "base_burst_generate.py",
        "metrics.py",
        "live_logs.py",
        "monitor_host.py",
    ):
        assert (ROOT / "src" / file).is_file(), file
        compile((ROOT / "src" / file).read_text(), file, "exec")
    assert (ROOT / "src/green_bridge.cpython-312-aarch64-linux-gnu.so").is_file()
    assert subprocess.run(["pgrep", "-x", "nsys"], capture_output=True).returncode == 1
    for m, old in backups.items():
        actual = json.loads(
            base.k("get", "deployment", m, "-o", "json", capture_output=True).stdout
        )
        assert (
            actual["spec"]["template"] == old["spec"]["template"]
            and actual["spec"]["replicas"] == old["spec"]["replicas"]
        )
    membership("preflight-serving", True, True)


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
    plan = schedule()
    (ROOT / "schedule.json").write_text(json.dumps(plan, indent=2))
    state = {
        "state": "RUNNING",
        "started_wall_ns": time.time_ns(),
        "total_trials": 35,
        "completed": [],
        "load": "simultaneous10Q/300Y only;5randomized complete blocks",
        "pid": os.getpid(),
    }

    def save():
        (ROOT / "verification/controller-status.json").write_text(
            json.dumps(state, indent=2)
        )

    preflight(backups)
    save()
    monitor = None
    log = None
    try:
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
        alert(
            "CJ 동시 burst 재측정 시작:7설정×5회, Qwen10/YOLO300. 약3시간 예상. 단독실험/Nsight 없음. 정상 서빙은 종료 후 복원합니다. "
            + str(ROOT)
        )
        for index, entry in enumerate(plan):
            state.update(index=index, phase="apply", current=entry)
            save()

            def template(original, model, qsm, ysm, root, label, enabled):
                return condition_template(
                    original, model, entry, root, label, str(PIPE)
                )

            base.burst_template = template
            base.apply(
                originals, entry["label"], entry["qsm"], entry["ysm"], entry["green"]
            )
            membership(entry["label"] + "-pre", entry["mps"])
            state["phase"] = "warmup"
            save()
            base.batch(
                entry["label"] + "-warmup",
                entry["qsm"],
                entry["ysm"],
                entry["green"],
                True,
            )
            membership(entry["label"] + "-warm", entry["mps"])
            state["phase"] = "measure"
            save()
            result = base.batch(
                entry["label"], entry["qsm"], entry["ysm"], entry["green"], False
            )
            membership(entry["label"] + "-post", entry["mps"])
            assert monitor.poll() is None, "Host monitor stopped"
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
                        "label": entry["label"],
                        "summary": result,
                    }
                ),
                flush=True,
            )
            if (index + 1) % 7 == 0:
                alert(
                    f"CJ 동시 burst {(index + 1) // 7}/5라운드 완료 ({index + 1}/35조건). 누락 없이 처리 중. "
                    + str(ROOT)
                )
        state["state"] = "PASS"
    except BaseException as error:
        state.update(state="FAIL", error=repr(error))
        save()
        alert(
            "CJ 동시 burst 오류/중단: "
            + repr(error)
            + ". 현재 서빙 설정 복원 진행. "
            + str(ROOT)
        )
        raise
    finally:
        try:
            state["phase"] = "restore"
            save()
            base.restore(backups)
            state["serving_membership"] = membership("restored-serving", True, True)
            state["restoration"] = "PASS"
        except BaseException as error:
            state["restoration"] = repr(error)
            alert("CJ 동시 burst 원상복구 확인 실패: " + repr(error) + " " + str(ROOT))
            raise
        finally:
            if monitor is not None:
                monitor.terminate()
                try:
                    monitor.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    monitor.kill()
                    monitor.wait()
            if log is not None:
                log.close()
            state.update(end_wall_ns=time.time_ns(), phase="finished")
            save()
            alert(
                "CJ 동시 burst 측정 종료: "
                + state["state"]
                + ", 복원 "
                + str(state.get("restoration"))
                + ". 분석 대상 "
                + str(len(state["completed"]))
                + "/35. "
                + str(ROOT)
            )
    print(json.dumps(state), flush=True)


if __name__ == "__main__":
    main()
