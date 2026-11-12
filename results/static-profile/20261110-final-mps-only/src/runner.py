#!/usr/bin/env python3
"""Spark-native fixed-burst trial owner; no solo phases; rollback in finally."""

import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from generate import burst_template
from live_logs import LiveLogs

ROOT = Path(
    os.environ.get("GREEN_BURST_ROOT", str(Path.home() / "cj-green-burst/20261109-v1"))
)
MODELS = ("qwen", "yolo")


def run(args, timeout=180, **kw):
    return subprocess.run(args, check=True, text=True, timeout=timeout, **kw)


def k(*args, **kw):
    return run(["kubectl", "-n", "cj-inference", *args], **kw)


def save(state):
    (ROOT / "verification/controller-status.json").write_text(
        json.dumps(state, indent=2)
    )


def apply(backups, label, qsm, ysm, enabled):
    for model in MODELS:
        template = burst_template(
            backups[model]["spec"]["template"],
            model,
            qsm,
            ysm,
            str(ROOT),
            label,
            enabled,
        )
        file = ROOT / "verification" / f"{label}-{model}-patch.json"
        file.write_text(
            json.dumps(
                [
                    {"op": "replace", "path": "/spec/template", "value": template},
                    {"op": "replace", "path": "/spec/replicas", "value": 1},
                ]
            )
        )
        k(
            "patch",
            "deployment",
            model,
            "--type=json",
            "--patch-file",
            str(file),
            stdout=subprocess.DEVNULL,
        )
    for model in MODELS:
        k("rollout", "status", "deployment/" + model, "--timeout=750s", timeout=770)
    metadata = {}
    for model in MODELS:
        records = [
            json.loads(p.read_text())
            for p in (ROOT / "metadata").glob(label + "-" + model + "-*.json")
        ]
        assert records
        metadata[model] = max(records, key=lambda r: r["time_ns"])
        assert metadata[model]["selected_sms"] == (qsm if model == "qwen" else ysm)
        assert metadata[model]["enabled"] == enabled
        code = "import json,os,time;print(json.dumps({'time_namespace':os.readlink('/proc/self/ns/time'),'offsets':open('/proc/self/timens_offsets').read(),'clock':time.get_clock_info('perf_counter').implementation}))"
        metadata[model]["clock_check"] = json.loads(
            k(
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
        "time_namespace": os.readlink("/proc/self/ns/time"),
        "offsets": Path("/proc/self/timens_offsets").read_text(),
        "clock": time.get_clock_info("perf_counter").implementation,
    }
    for model in MODELS:
        assert metadata[model]["clock_check"] == host, (
            "Cross-process timeline clock not shared"
        )
    metadata["shared_clock"] = host
    if enabled:
        metadata["observed_smid_intersection"] = sorted(
            set(metadata["qwen"]["observed_smids"])
            & set(metadata["yolo"]["observed_smids"])
        )
    (ROOT / "verification" / f"{label}-allocation.json").write_text(
        json.dumps(metadata, indent=2)
    )


def batch(label, qsm, ysm, enabled, warmup=False):
    expected = (3, 30) if warmup else (10, 300)
    env = dict(os.environ)
    env["ROS_DOMAIN_ID"] = "74"
    env.pop("FASTRTPS_DEFAULT_PROFILES_FILE", None)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    target = ROOT / ("warmup" if warmup else "results") / label
    for kind in ("deployment", "pods"):
        (ROOT / "verification" / f"{label}-{kind}.json").write_text(
            k("get", kind, "-o", "json", capture_output=True).stdout
        )
    start = datetime.datetime.now(datetime.timezone.utc).isoformat()
    followers = LiveLogs(ROOT / "logs", label, MODELS, start)
    with (ROOT / "logs" / (label + "-client.log")).open("x") as out:
        child = None
        followers.start()
        try:
            child = subprocess.Popen(
                [
                    "python3",
                    str(ROOT / "src/client.py"),
                    "--root",
                    str(ROOT),
                    "--output",
                    str(target),
                    "--qwen-count",
                    str(expected[0]),
                    "--yolo-count",
                    str(expected[1]),
                    "--qwen-sm",
                    str(qsm),
                    "--yolo-sm",
                    str(ysm),
                    "--green",
                    str(int(enabled)),
                ],
                env=env,
                stdout=out,
                stderr=subprocess.STDOUT,
            )
            code = child.wait(timeout=900)
            if code:
                raise RuntimeError(f"Burst failed: {label}, exit={code}")
        finally:
            if child is not None and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            time.sleep(3)
            followers.close()
    result = json.loads((target / "summary.json").read_text())
    print(
        json.dumps(
            {
                "event": "burst_complete",
                "label": label,
                "warmup": warmup,
                "summary": result,
                "time": time.time(),
            }
        ),
        flush=True,
    )
    return result


def restore(backups):
    for model, old in backups.items():
        file = ROOT / "verification" / f"{model}-restore.json"
        file.write_text(
            json.dumps(
                [
                    {
                        "op": "replace",
                        "path": "/spec/template",
                        "value": old["spec"]["template"],
                    },
                    {
                        "op": "replace",
                        "path": "/spec/replicas",
                        "value": old["spec"]["replicas"],
                    },
                ]
            )
        )
        k(
            "patch",
            "deployment",
            model,
            "--type=json",
            "--patch-file",
            str(file),
            stdout=subprocess.DEVNULL,
        )
    result = {}
    for model, old in backups.items():
        k("rollout", "status", "deployment/" + model, "--timeout=750s", timeout=770)
        actual = json.loads(
            k("get", "deployment", model, "-o", "json", capture_output=True).stdout
        )
        assert (
            actual["spec"]["template"] == old["spec"]["template"]
            and actual["spec"]["replicas"] == old["spec"]["replicas"]
        )
        result[model] = {"template_equal": True, "replicas": actual["spec"]["replicas"]}
    env = dict(os.environ)
    env["ROS_DOMAIN_ID"] = "42"
    env.pop("FASTRTPS_DEFAULT_PROFILES_FILE", None)
    with (ROOT / "verification/health.log").open("w") as log:
        run(
            [
                "python3",
                str(Path.home() / "cj-ros2/benchmark/bench_ros2.py"),
                "--models",
                "both",
                "--output",
                str(ROOT / "verification" / ("health-" + str(time.time_ns()))),
                "--samples",
                "1",
                "--warmup",
                "1",
                "--max-new-tokens",
                "8",
            ],
            env=env,
            timeout=300,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    (ROOT / "verification/restored.json").write_text(json.dumps(result, indent=2))


def main():
    def interrupted(*args):
        raise KeyboardInterrupt()

    for s in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(s, interrupted)
    backups = {
        m: json.loads((ROOT / "backup" / (m + ".json")).read_text()) for m in MODELS
    }
    for model in MODELS:
        actual = json.loads(
            k("get", "deployment", model, "-o", "json", capture_output=True).stdout
        )
        assert actual["spec"]["template"] == backups[model]["spec"]["template"]
        assert actual["spec"]["replicas"] == backups[model]["spec"]["replicas"]
    assert (
        subprocess.run(
            ["pgrep", "-u", "1000", "-f", "^nvidia-cuda-mps-(control|server)"],
            capture_output=True,
        ).returncode
        == 1
    )
    cases = [
        ("default-pre", 48, 48, False),
        ("q16-y32", 16, 32, True),
        ("q24-y24", 24, 24, True),
        ("q8-y40", 8, 40, True),
        ("q32-y16", 32, 16, True),
        ("q40-y8", 40, 8, True),
        ("default-post", 48, 48, False),
    ]
    state = {
        "state": "RUNNING",
        "start": time.time(),
        "root": str(ROOT),
        "completed": [],
        "scope": "simultaneous finite bursts only, no solo comparisons",
        "measured_burst_counts": {"qwen": 10, "yolo": 300},
        "replicates": 3,
    }
    save(state)
    try:
        for label, qsm, ysm, enabled in cases:
            state["phase"] = label
            save(state)
            print(
                json.dumps(
                    {"event": "case_start", "label": label, "time": time.time()}
                ),
                flush=True,
            )
            apply(backups, label, qsm, ysm, enabled)
            batch(label + "-warmup", qsm, ysm, enabled, True)
            for repetition in range(3):
                state["burst_repetition"] = repetition
                save(state)
                batch(label + f"-r{repetition}", qsm, ysm, enabled)
            state["completed"].append(label)
            save(state)
        state["state"] = "PASS"
    except BaseException as error:
        state.update(state="FAIL", error=repr(error))
        save(state)
        raise
    finally:
        try:
            restore(backups)
            state["restoration"] = "PASS"
        except BaseException as error:
            state["restoration"] = repr(error)
            raise
        finally:
            state["end"] = time.time()
            save(state)
    print(json.dumps(state), flush=True)


if __name__ == "__main__":
    main()
