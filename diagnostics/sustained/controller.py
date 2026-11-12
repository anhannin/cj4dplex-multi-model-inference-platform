"""Own pilot and 40 sustained runs; existing frozen nodes, restore in finally."""

import datetime
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import base_runner as base
import eval_runner as native
import control_runner as common
from live_logs import LiveLogs
from plan import CONDITIONS
from protocol import make_schedule

ROOT = Path(os.environ["GREEN_BURST_ROOT"])
assert ROOT == base.ROOT == native.ROOT


def save(value):
    target = ROOT / "verification/controller-status.json"
    tmp = target.with_suffix(".new")
    tmp.write_text(json.dumps(value, indent=2))
    tmp.replace(target)


def case(name, label):
    return {"condition": name, "label": label, **CONDITIONS[name]}


def trial(entry, rate, duration, phase, index=-1, label=None):
    label = label or entry["label"]
    output = ROOT / "results" / label
    for kind in ("deployment", "pods"):
        (ROOT / "verification" / f"{label}-{kind}.json").write_text(
            base.k("get", kind, "-o", "json", capture_output=True).stdout
        )
    start = datetime.datetime.now(datetime.timezone.utc).isoformat()
    followers = LiveLogs(ROOT / "logs", label, ("qwen", "yolo"), start)
    child = None
    with (ROOT / "logs" / f"{label}-client.log").open("x") as log:
        followers.start()
        try:
            child = subprocess.Popen(
                [
                    "python3",
                    str(ROOT / "src/sustained_client.py"),
                    "--root",
                    str(ROOT),
                    "--output",
                    str(output),
                    "--duration",
                    str(duration),
                    "--rate",
                    str(rate),
                    "--condition",
                    entry["condition"],
                    "--phase",
                    phase,
                    "--round",
                    str(index),
                    "--qwen-sm",
                    str(entry["qsm"]),
                    "--yolo-sm",
                    str(entry["ysm"]),
                ],
                env={**os.environ, "ROS_DOMAIN_ID": "74"},
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            rc = child.wait(timeout=duration + 420)
            if rc:
                raise RuntimeError(f"Sustained client failed: {label}, exit={rc}")
        finally:
            if child is not None and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            time.sleep(2)
            followers.close()
    result = json.loads((output / "manifest.json").read_text())
    assert result["state"] == "PASS"
    common.membership(label + "-post", True) if entry["mps"] else native.check_no_mps(
        label + "-post"
    )
    print(
        json.dumps(
            {
                "event": "trial_complete",
                "label": label,
                "phase": phase,
                "expected": result["expected"],
                "generator": result["generator"],
                "pilot_queue": result["pilot_queue"],
            }
        ),
        flush=True,
    )
    return result


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
    for m, old in backups.items():
        actual = json.loads(
            base.k("get", "deployment", m, "-o", "json", capture_output=True).stdout
        )
        assert actual["spec"]["template"] == old["spec"]["template"]
        assert actual["spec"]["replicas"] == old["spec"]["replicas"] == 1
    common.PIPE = Path.home() / "cj-serving/mps-green-v1/mps-pipe"
    common.membership("preflight-serving", True, True)
    common.PIPE = native.PIPE
    assert (
        base.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True,
        ).stdout.strip()
        == "595.99.02"
    )
    assert subprocess.run(["pgrep", "-x", "nsys"], capture_output=True).returncode == 1
    state = {
        "state": "RUNNING",
        "phase": "preflight",
        "started_wall_ns": time.time_ns(),
        "pid": os.getpid(),
        "completed": [],
        "pilot": [],
        "restoration": "PENDING",
    }
    save(state)
    monitor = None
    try:
        with (ROOT / "logs/host-monitor.log").open("x") as monitor_log:
            monitor = subprocess.Popen(
                [
                    "python3",
                    str(ROOT / "src/monitor_host.py"),
                    "--output",
                    str(ROOT / "verification/host-samples.jsonl"),
                    "--interval",
                    "1",
                ],
                stdout=monitor_log,
                stderr=subprocess.STDOUT,
            )
            common.alert(
                "CJ 지속부하 실험 시작: 예비 요청률 선정 후 MPS없음/일반/8·40/16·32, 120초×2부하×5회. "
                + str(ROOT)
            )
            # v2 keeps v1 control-only rate selection. All main runs restart with one generator revision.
            selection = json.loads((ROOT / "rates-locked.json").read_text())
            chosen = selection["rates"]
            assert chosen == [8, 15]
            for condition, duration, label in [
                ("control", 30, "validation-control-rate15"),
                ("mps-only", 120, "validation-mps-rate15"),
            ]:
                state.update(phase="generator-validation", current=label)
                save(state)
                entry = case(condition, label)
                native.apply(entry, originals)
                base.batch(label + "-warmup", entry["qsm"], entry["ysm"], False, True)
                result = trial(entry, 15, duration, "validation", label=label)
                state.setdefault("validation", []).append(result)
                save(state)
            selection.update(
                generator_revision="v2-dedicated-yolo-publisher-process",
                pilot_source="../20261111-v1/rates.json",
                main_started_wall_ns=time.time_ns(),
            )
            (ROOT / "rates.json").write_text(json.dumps(selection, indent=2))
            plan = make_schedule(chosen)
            (ROOT / "schedule.json").write_text(json.dumps(plan, indent=2))
            state.update(rates=chosen, total_trials=len(plan))
            save(state)
            common.alert(
                "CJ 지속부하 예비 완료. 고정 YOLO 요청률 "
                + str(chosen)
                + " req/s. 본실험40회 진행. "
                + str(ROOT)
            )
            for i, item in enumerate(plan):
                state.update(phase="main-apply", index=i, current=item)
                save(state)
                entry = case(item["condition"], item["label"])
                native.apply(entry, originals)
                state["phase"] = "main-warmup"
                save(state)
                base.batch(
                    entry["label"] + "-warmup", entry["qsm"], entry["ysm"], False, True
                )
                state["phase"] = "main-measure"
                save(state)
                result = trial(entry, item["rate"], 120, "main", item["round"])
                assert monitor.poll() is None
                state["completed"].append(
                    {
                        **item,
                        "expected": result["expected"],
                        "generator": result["generator"],
                        "finished_wall_ns": time.time_ns(),
                    }
                )
                state["phase"] = "drained"
                save(state)
                if (i + 1) % 8 == 0:
                    common.alert(
                        f"CJ 지속부하 {(i + 1) // 8}/5라운드 완료 ({i + 1}/40), 발행/응답 검증 통과. "
                        + str(ROOT)
                    )
            state["state"] = "PASS"
    except BaseException as error:
        state.update(state="FAIL", error=repr(error))
        save(state)
        common.alert(
            "CJ 지속부하 오류: " + repr(error) + ". 원래 서빙 복구 진행. " + str(ROOT)
        )
        raise
    finally:
        try:
            state["phase"] = "restore"
            save(state)
            state["restored_membership"] = native.restore(backups)
            state["restoration"] = "PASS"
        except BaseException as error:
            state["restoration"] = repr(error)
            common.alert("CJ 지속부하 서빙복구 확인 실패: " + repr(error))
            raise
        finally:
            if monitor is not None:
                monitor.terminate()
                try:
                    monitor.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    monitor.kill()
                    monitor.wait()
            state.update(phase="finished", end_wall_ns=time.time_ns())
            save(state)
            common.alert(
                f"CJ 지속부하 종료: {state['state']}, {len(state['completed'])}/40, 운영복구 {state['restoration']}. "
                + str(ROOT)
            )


if __name__ == "__main__":
    main()
