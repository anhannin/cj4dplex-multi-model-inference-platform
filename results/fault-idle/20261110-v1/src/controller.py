"""Three GPU-idle YOLO Node crash/recovery trials. Never SIGKILL active GPU work."""

import datetime
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
import uuid

import base_runner as base
import eval_runner as native
from plan import CONDITIONS
from fault_metrics import pod_snapshot, transition, validate_target
from ros_client import atomic

ROOT = Path(os.environ["GREEN_BURST_ROOT"])
assert base.ROOT == native.ROOT == ROOT
CASE = {
    "label": "fault-static-q8-y40",
    "condition": "static-q8-y40",
    **CONDITIONS["static-q8-y40"],
}
stock_template = native.condition_template


def fault_template(*args, **kwargs):
    t = stock_template(*args, **kwargs)
    for e in t["spec"]["containers"][0]["env"]:
        if e["name"] == "ROS_DOMAIN_ID":
            e["value"] = "81"
    return t


native.condition_template = fault_template


def json_file(path):
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def wait(fn, seconds, label):
    deadline = time.monotonic() + seconds
    while True:
        value = fn()
        if value:
            return value
        q = json_file(ROOT / "verification/qwen-monitor-status.json")
        if q and q["state"] == "FAIL":
            raise RuntimeError("Qwen monitor failed: " + str(q))
        if time.monotonic() > deadline:
            raise TimeoutError(label)
        time.sleep(0.05)


def current_pod():
    v = json.loads(
        base.k(
            "get", "pods", "-l", "app=yolo", "-o", "json", capture_output=True
        ).stdout
    )
    rows = [p for p in v["items"] if not p["metadata"].get("deletionTimestamp")]
    assert len(rows) == 1, rows
    return rows[0]


class PodObserver:
    def __init__(self, pod, folder):
        self.pod, self.folder = pod, folder
        self.rows = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        with (self.folder / "pod-observations.jsonl").open("x") as stream:
            while not self.stop.is_set():
                before = time.perf_counter_ns()
                try:
                    p = subprocess.run(
                        [
                            "kubectl",
                            "-n",
                            "cj-inference",
                            "get",
                            "pod",
                            self.pod,
                            "-o",
                            "json",
                        ],
                        text=True,
                        capture_output=True,
                        timeout=6,
                    )
                except (subprocess.TimeoutExpired, OSError) as error:
                    p = subprocess.CompletedProcess([], 124, "", repr(error))
                after = time.perf_counter_ns()
                try:
                    snapshot = (
                        pod_snapshot(json.loads(p.stdout))
                        if p.returncode == 0
                        else None
                    )
                except ValueError:
                    snapshot = None
                row = {
                    "poll_before_ns": before,
                    "poll_after_ns": after,
                    "poll_elapsed_ms": (after - before) / 1e6,
                    "exit": p.returncode,
                    "snapshot": snapshot,
                    "error": p.stderr[-200:] if p.returncode else None,
                }
                self.rows.append(row)
                stream.write(json.dumps(row) + "\n")
                stream.flush()
                self.stop.wait(max(0, 0.25 - (time.perf_counter_ns() - before) / 1e9))

    def start(self):
        self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=10)
        assert not self.thread.is_alive()


def qwen_state():
    return json_file(ROOT / "verification/qwen-monitor-status.json") or {}


def qwen_rows():
    p = ROOT / "results/qwen-requests.jsonl"
    if not p.exists():
        return []
    return [json.loads(v) for v in p.read_text().splitlines() if v]


def yolo_request(label):
    folder = ROOT / "results" / label
    folder.mkdir(exist_ok=True)
    with (folder / "client.log").open("x") as log:
        base.run(
            [
                "python3",
                str(ROOT / "src/yolo_probe.py"),
                "--root",
                str(ROOT),
                "--trial",
                label,
            ],
            timeout=150,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    result = json_file(folder / "probe-result.json")
    assert result and result["state"] == "PASS"
    return result


def reset_yolo(index):
    template = json.loads(
        base.k("get", "deployment", "yolo", "-o", "json", capture_output=True).stdout
    )["spec"]["template"]
    template["metadata"].setdefault("annotations", {})["cj/fault-independent-trial"] = (
        f"{index}-{uuid.uuid4().hex}"
    )
    file = ROOT / "verification" / f"trial{index}-reset-patch.json"
    file.write_text(
        json.dumps([{"op": "replace", "path": "/spec/template", "value": template}])
    )
    base.k(
        "patch",
        "deployment",
        "yolo",
        "--type=json",
        "--patch-file",
        str(file),
        stdout=subprocess.DEVNULL,
    )
    base.k("rollout", "status", "deployment/yolo", "--timeout=180s", timeout=200)


def run_trial(index):
    label = f"trial{index}"
    folder = ROOT / "results" / label
    folder.mkdir()
    if index:
        reset_yolo(index)
    before = current_pod()
    old = pod_snapshot(before)
    assert old["ready"] and old["restart_count"] == 0, old
    atomic(folder / "pod-before.json", before)
    yolo_request(label + "-warm")
    member = native.common.membership(label + "-before", True)
    pid = member["models"]["yolo"]
    qpid = member["models"]["qwen"]
    proc = Path(f"/proc/{pid}")
    start_ticks = proc.joinpath("stat").read_text().split()[21]
    uid = int(
        next(
            x
            for x in proc.joinpath("status").read_text().splitlines()
            if x.startswith("Uid:")
        ).split()[1]
    )
    cmdline = (
        proc.joinpath("cmdline").read_bytes().replace(b"\0", b" ").decode().strip()
    )
    validate_target(pid, uid, cmdline, member["models"], member["clients"])
    # Pre-create patient reader/writer but publish nothing before the signal.
    log = (folder / "client.log").open("x")
    probe = subprocess.Popen(
        [
            "python3",
            str(ROOT / "src/yolo_probe.py"),
            "--root",
            str(ROOT),
            "--trial",
            label,
            "--wait-fault",
        ],
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
    )
    observer = PodObserver(old["pod_name"], folder)
    nonce = uuid.uuid4().hex
    gate = ROOT / "control/yolo-idle-gate.json"
    ackfile = ROOT / "control" / ("idle-ack-" + nonce + ".json")
    try:
        wait(
            lambda: json_file(folder / "probe-ready.json"),
            20,
            "Recovery reader/writer prepared",
        )
        # Ensure a Qwen request is in progress; C1 not a claim of continuous kernel occupancy.
        wait(
            lambda: (
                v
                if (v := json_file(ROOT / "control/qwen-inflight.json"))
                and v.get("state") == "waiting"
                and time.perf_counter_ns() - v["sent_ns"] > 1_000_000_000
                else None
            ),
            30,
            "Active Qwen request",
        )
        atomic(gate, {"nonce": nonce, "trial": label})
        ack = wait(
            lambda: json_file(ackfile), 15, "Actual worker CUDA idle synchronization"
        )
        assert ack["nonce"] == nonce and ack["gpu_synchronized"] and ack["queue_empty"]
        latest = current_pod()
        assert pod_snapshot(latest)["container_id"] == old["container_id"]
        assert proc.joinpath("stat").read_text().split()[21] == start_ticks
        validate_target(
            pid,
            uid,
            proc.joinpath("cmdline").read_bytes().replace(b"\0", b" ").decode().strip(),
            member["models"],
            member["clients"],
        )
        fresh_member = native.common.membership(label + "-idle-confirmed", True)
        assert (
            fresh_member["server"] == member["server"]
            and fresh_member["models"] == member["models"]
        )
        status = native.ctl("get_server_status " + str(member["server"])).strip()
        assert status == "ACTIVE", status
        atomic(folder / "idle-barrier.json", ack)
        observer.start()
        wait(lambda: observer.rows, 10, "Observer ready")
        before_kill = time.perf_counter_ns()
        wall = time.time_ns()
        os.kill(pid, signal.SIGKILL)
        after_kill = time.perf_counter_ns()
        gate.unlink(missing_ok=True)
        fault = {
            "fault_before_ns": before_kill,
            "fault_after_ns": after_kill,
            "fault_wall_ns": wall,
            "target_host_pid": pid,
            "target_uid": uid,
            "target_cmdline": cmdline,
            "target_proc_start_ticks": start_ticks,
            "qwen_host_pid": qpid,
            "idle_nonce": nonce,
            "kind": "SIGKILL_GPU_IDLE_ROS_NODE",
            "not_inflight_gpu_crash": True,
        }
        atomic(folder / "fault.json", fault)
        result = wait(
            lambda: json_file(folder / "probe-result.json"),
            110,
            "Functional recovery result",
        )
        assert result["state"] == "PASS", result
        assert (
            result["sent_ns"] >= before_kill
            and result["response"]["server_enqueued_perf_ns"] >= before_kill
        )

        def ready_event():
            return next(
                (
                    v
                    for v in observer.rows
                    if v["poll_after_ns"] >= before_kill
                    and transition(old, v["snapshot"])["ready"]
                ),
                None,
            )

        ready = wait(ready_event, 35, "New-container readiness observed")
        probe.wait(timeout=10)
        assert probe.returncode == 0
        observer.close()
        changes = [v for v in observer.rows if v["poll_after_ns"] >= before_kill]
        detected = next(
            v for v in changes if transition(old, v["snapshot"])["detected"]
        )
        restarted = next(
            v for v in changes if transition(old, v["snapshot"])["restarted"]
        )
        after = current_pod()
        new = pod_snapshot(after)
        atomic(folder / "pod-after.json", after)
        assert (
            new["pod_uid"] == old["pod_uid"]
            and new["container_id"] != old["container_id"]
            and new["restart_count"] == 1
            and new["ready"]
        )
        terminated = new["last_state"].get("terminated", {})
        assert (
            terminated.get("exitCode") == 137
            and terminated.get("reason") != "OOMKilled"
        ), terminated
        for previous, filename in (
            (True, "yolo-previous.log"),
            (False, "yolo-restarted.log"),
        ):
            args = ["logs", old["pod_name"], "-c", "yolo", "--timestamps=true"] + (
                ["--previous"] if previous else []
            )
            (folder / filename).write_text(base.k(*args, capture_output=True).stdout)
        post = native.common.membership(label + "-after", True)
        assert post["server"] == member["server"] and post["models"]["qwen"] == qpid, (
            "Unexpected shared MPS/Qwen reset"
        )
        assert post["models"]["yolo"] != pid
        for i in range(2):
            yolo_request(label + f"-post{i}")
        summary = {
            "trial": label,
            "state": "PASS",
            "fault": fault,
            "before": old,
            "after": new,
            "termination": terminated,
            "mps_before": member,
            "mps_after": post,
            "detect_observed_ms": (detected["poll_after_ns"] - before_kill) / 1e6,
            "container_start_observed_ms": (restarted["poll_after_ns"] - before_kill)
            / 1e6,
            "ready_observed_ms": (ready["poll_after_ns"] - before_kill) / 1e6,
            "first_valid_response_ms": (result["received_ns"] - before_kill) / 1e6,
            "probe_publish_after_fault_ms": (result["sent_ns"] - before_kill) / 1e6,
            "probe_e2e_ms": result["request_e2e_ms"],
            "probe_server_enqueued_after_fault_ms": (
                result["response"]["server_enqueued_perf_ns"] - before_kill
            )
            / 1e6,
            "observer_poll_max_ms": max(v["poll_elapsed_ms"] for v in observer.rows),
            "observer_target_period_ms": 250,
            "functional_may_precede_ready": True,
            "queued_at_fault": 0,
            "yolo_inflight_at_fault": 0,
            "probe_application_retries": 0,
            "probe_publish_count": result["publish_count"],
            "outage_failure_rate_not_established": True,
        }
        atomic(folder / "summary.json", summary)
        return summary
    finally:
        gate.unlink(missing_ok=True)
        if observer.thread.is_alive():
            observer.close()
        if probe.poll() is None:
            probe.terminate()
            try:
                probe.wait(timeout=5)
            except subprocess.TimeoutExpired:
                probe.kill()
                probe.wait()
        log.close()


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
    for m, old in backups.items():
        v = json.loads(
            base.k("get", "deployment", m, "-o", "json", capture_output=True).stdout
        )
        assert (
            v["spec"]["template"] == old["spec"]["template"]
            and v["spec"]["replicas"] == old["spec"]["replicas"]
        )
    assert (ROOT / "workload.json").is_file() and (
        ROOT / "src/qwen_monitor.py"
    ).is_file()
    state = {
        "state": "RUNNING",
        "scope": "3independentGPU-idleYOLO_NODE_SIGKILL;notbusyGPUfatalfault;exploratoryrecovery",
        "trials": [],
        "start_wall_ns": time.time_ns(),
        "pid": os.getpid(),
    }
    file = ROOT / "verification/controller-status.json"
    atomic(file, state)
    qprocess = None
    qlog = None
    live = None
    try:
        native.common.alert(
            "CJ 장애복구실험 시작: nativeMPS정적8/40, GPU완료·Queue빈YOLO Node만SIGKILL,3독립반복. Qwen영향/실제응답복구계측후원본복원. "
            + str(ROOT)
        )
        native.apply(CASE, originals)
        for i in range(3):
            yolo_request(f"initial-yolo-warm{i}")
        # Qwen stays in this Pod for all independent YOLO trials.
        qlog = (ROOT / "logs/qwen-monitor.log").open("x")
        qprocess = subprocess.Popen(
            ["python3", str(ROOT / "src/qwen_monitor.py"), "--root", str(ROOT)],
            stdout=qlog,
            stderr=subprocess.STDOUT,
            text=True,
        )
        from live_logs import LiveLogs

        live = LiveLogs(
            ROOT / "logs",
            "fault-qwen",
            ("qwen",),
            datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )
        live.start()
        state["phase"] = "qwen-warmup-baseline"
        atomic(file, state)
        wait(
            lambda: qwen_state().get("measured", 0) >= 3,
            240,
            "Qwen3warm+3stablebaseline",
        )
        state["qwen_baseline_rows"] = len(qwen_rows())
        atomic(file, state)
        for index in range(3):
            assert qprocess.poll() is None
            state.update(phase="trial", current=index)
            atomic(file, state)
            summary = run_trial(index)
            state["trials"].append(summary)
            atomic(file, state)
            print(
                json.dumps({"event": "fault_trial_complete", "summary": summary}),
                flush=True,
            )
            native.common.alert(
                f"CJ YOLOidle장애{index + 1}/3복구: 탐지관측{summary['detect_observed_ms'] / 1000:.3f}s, 첫정상응답{summary['first_valid_response_ms'] / 1000:.3f}s. Qwen/MPS PID유지."
            )
        count = qwen_state().get("measured", 0)
        state["phase"] = "post-recovery"
        atomic(file, state)
        wait(
            lambda: qwen_state().get("measured", 0) >= count + 2,
            65,
            "Two post-recovery Qwen successes",
        )
        (ROOT / "control/stop-qwen").write_text("finish-current-request")
        qprocess.wait(timeout=85)
        assert qprocess.returncode == 0 and qwen_state().get("state") == "PASS"
        state.update(state="PASS", qwen_monitor=qwen_state())
        atomic(file, state)
    except BaseException as error:
        state.update(state="FAIL", error=repr(error))
        atomic(file, state)
        native.common.alert(
            "CJ 장애복구실험 오류: " + repr(error) + " 원본복원진행 " + str(ROOT)
        )
        raise
    finally:
        (ROOT / "control/yolo-idle-gate.json").unlink(missing_ok=True)
        (ROOT / "control/stop-qwen").write_text("finish-current-request")
        if qprocess is not None and qprocess.poll() is None:
            try:
                qprocess.wait(timeout=85)
            except subprocess.TimeoutExpired:
                qprocess.terminate()
                qprocess.wait(timeout=8)
        if qlog is not None:
            qlog.close()
        if live is not None:
            time.sleep(2)
            live.close()
        try:
            state["phase"] = "restore"
            atomic(file, state)
            state["serving_membership"] = native.restore(backups)
            state["restoration"] = "PASS"
        except BaseException as error:
            state["restoration"] = repr(error)
            native.common.alert("CJ 장애실험 원상복구확인실패: " + repr(error))
            raise
        finally:
            state.update(end_wall_ns=time.time_ns(), phase="finished")
            atomic(file, state)
            native.common.alert(
                "CJ 장애복구실험 종료: "
                + state["state"]
                + ", 원본복원 "
                + str(state.get("restoration"))
                + " "
                + str(ROOT)
            )
    print(json.dumps(state), flush=True)


if __name__ == "__main__":
    main()
