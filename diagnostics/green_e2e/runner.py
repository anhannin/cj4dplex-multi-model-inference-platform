#!/usr/bin/env python3
"""Run on Spark after native ROS setup: serialized complementary-partition E2E trials."""

import argparse
import datetime
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import time

from generate import make_template, combinations
from live_logs import LiveLogs
from verify_trace import verify

ROOT = Path(
    os.environ.get("GREEN_E2E_ROOT", str(Path.home() / "cj-green-e2e/20261109-v1"))
)
MODELS = ("qwen", "yolo")


def run(args, timeout=180, **kwargs):
    return subprocess.run(args, check=True, text=True, timeout=timeout, **kwargs)


def kubectl(*args, **kwargs):
    return run(["kubectl", "-n", "cj-inference", *args], **kwargs)


def save_state(state):
    (ROOT / "verification/controller-status.json").write_text(
        json.dumps(state, indent=2)
    )


def apply(backups, qsm, ysm, label, enabled=True, profile=False):
    for model in MODELS:
        template = make_template(
            backups[model]["spec"]["template"],
            model,
            qsm,
            ysm,
            str(ROOT),
            label,
            enabled,
            profile,
        )
        patch = [
            {"op": "replace", "path": "/spec/template", "value": template},
            {"op": "replace", "path": "/spec/replicas", "value": 1},
        ]
        path = ROOT / "verification" / f"{label}-{model}-patch.json"
        path.write_text(json.dumps(patch))
        kubectl(
            "patch",
            "deployment",
            model,
            "--type=json",
            "--patch-file",
            str(path),
            stdout=subprocess.DEVNULL,
        )
    for model in MODELS:
        kubectl(
            "rollout", "status", "deployment/" + model, "--timeout=750s", timeout=770
        )
    metadata = {}
    for model in MODELS:
        paths = list((ROOT / "metadata").glob(label + "-" + model + "-*.json"))
        records = [json.loads(p.read_text()) for p in paths]
        if not records:
            raise RuntimeError("Missing worker allocation metadata")
        metadata[model] = max(records, key=lambda r: r["time_ns"])
        assert metadata[model]["enabled"] == enabled
        expected = qsm if model == "qwen" else ysm
        assert metadata[model]["selected_sms"] == expected
    if enabled:
        a = set(metadata["qwen"]["observed_smids"])
        b = set(metadata["yolo"]["observed_smids"])
        metadata["observed_smid_intersection"] = sorted(a & b)
        metadata["sampled_sets_disjoint"] = not bool(a & b)
        # Preserve overlapping observations instead of calling them global physical reservations.
    (ROOT / "verification" / f"{label}-allocation.json").write_text(
        json.dumps(metadata, indent=2)
    )


def measure(label, models, samples, qsm, ysm, warmup=3):
    env = dict(os.environ)
    env["ROS_DOMAIN_ID"] = "73"
    env["EXPECTED_QWEN_SMS"] = str(qsm)
    env["EXPECTED_YOLO_SMS"] = str(ysm)
    env.pop("FASTRTPS_DEFAULT_PROFILES_FILE", None)
    env["PYTHONPATH"] = (
        str(ROOT / "src")
        + os.pathsep
        + str(Path.home() / "cj-ros2/benchmark")
        + os.pathsep
        + env.get("PYTHONPATH", "")
    )
    for kind in ("deployment", "pods"):
        (ROOT / "results" / f"{label}-{kind}.json").write_text(
            kubectl("get", kind, "-o", "json", capture_output=True).stdout
        )
    command = [
        "python3",
        str(ROOT / "src/bench_green.py"),
        "--models",
        models,
        "--output",
        str(ROOT / "results" / label),
        "--samples",
        str(samples),
        "--warmup",
        str(warmup),
        "--max-new-tokens",
        "128",
        "--timing-mode",
        "tokens",
        "--timeout",
        "240",
    ]
    start = datetime.datetime.now(datetime.timezone.utc).isoformat()
    followers = LiveLogs(ROOT / "results", label, MODELS, start)
    with (ROOT / "logs" / (label + "-client.log")).open("x") as out:
        followers.start()
        child = None
        try:
            child = subprocess.Popen(
                command, env=env, stdout=out, stderr=subprocess.STDOUT
            )
            if child.wait(timeout=1500):
                raise RuntimeError("Benchmark failed: " + label)
        finally:
            if child is not None and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            time.sleep(2.2)
            followers.close()
    summary = json.loads((ROOT / "results" / label / "summary.json").read_text())
    concise = {
        m: {
            "n": r["successful"],
            "failed": r["failed"],
            "mean_e2e_ms": r["request_e2e_ms"]["mean"],
            "p95_e2e_ms": r["request_e2e_ms"]["p95"],
            "rate": r["successful_requests_per_second"],
        }
        for m, r in summary.items()
    }
    print(
        json.dumps(
            {
                "event": "measured",
                "label": label,
                "summary": concise,
                "time": time.time(),
            }
        ),
        flush=True,
    )
    return summary


def flush_profiles():
    reports = {}
    for model in MODELS:
        folder = ROOT / "validation" / model
        files = list(folder.glob("*.nsys-rep"))
        if not files:
            try:
                result = kubectl(
                    "exec",
                    "deployment/" + model,
                    "--",
                    "nsys",
                    "sessions",
                    "list",
                    "--output-format=json",
                    capture_output=True,
                )
                sessions = json.loads(result.stdout)
            except Exception:
                sessions = []
            if any(s.get("name") == "green-e2e-" + model for s in sessions):
                result = subprocess.run(
                    [
                        "kubectl",
                        "-n",
                        "cj-inference",
                        "exec",
                        "deployment/" + model,
                        "--",
                        "nsys",
                        "shutdown",
                        "--session=green-e2e-" + model,
                        "--kill=none",
                    ],
                    text=True,
                    capture_output=True,
                    timeout=240,
                )
                (ROOT / "logs" / f"profile-{model}-shutdown.log").write_text(
                    result.stdout + result.stderr + f"\nexit={result.returncode}\n"
                )
        deadline = time.monotonic() + 120
        while not (files := list(folder.glob("*.nsys-rep"))):
            if time.monotonic() > deadline:
                raise TimeoutError("No flushed profiler report: " + model)
            time.sleep(1)
        assert len(files) == 1, files
        report = files[0]
        database = folder / "trace.sqlite"
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
            "--output",
            "/experiment/validation/" + model + "/trace.sqlite",
            "/experiment/validation/" + model + "/" + report.name,
        ]
        with (ROOT / "logs" / f"profile-{model}-export.log").open("w") as log:
            run(command, timeout=600, stdout=log, stderr=subprocess.STDOUT)
        with sqlite3.connect(database) as connection:
            reports[model] = verify(connection, model + ".green.serving")
    (ROOT / "verification/serving-green-kernel-coverage.json").write_text(
        json.dumps(reports, indent=2)
    )
    print(json.dumps({"event": "profile_validation", "reports": reports}), flush=True)


def restore(backups):
    for model, original in backups.items():
        path = ROOT / "verification" / f"{model}-restore-patch.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "op": "replace",
                        "path": "/spec/template",
                        "value": original["spec"]["template"],
                    },
                    {
                        "op": "replace",
                        "path": "/spec/replicas",
                        "value": original["spec"]["replicas"],
                    },
                ]
            )
        )
        kubectl(
            "patch",
            "deployment",
            model,
            "--type=json",
            "--patch-file",
            str(path),
            stdout=subprocess.DEVNULL,
        )
    result = {}
    for model, original in backups.items():
        kubectl(
            "rollout", "status", "deployment/" + model, "--timeout=750s", timeout=770
        )
        actual = json.loads(
            kubectl(
                "get", "deployment", model, "-o", "json", capture_output=True
            ).stdout
        )
        assert (
            actual["spec"]["template"] == original["spec"]["template"]
            and actual["spec"]["replicas"] == original["spec"]["replicas"]
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-profile", action="store_true")
    parser.add_argument("--cases", nargs="*")
    a = parser.parse_args()

    def interrupted(*args):
        raise KeyboardInterrupt()

    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, interrupted)
    backups = {
        m: json.loads((ROOT / "backup" / f"{m}.json").read_text()) for m in MODELS
    }
    for m in MODELS:
        actual = json.loads(
            kubectl("get", "deployment", m, "-o", "json", capture_output=True).stdout
        )
        assert actual["spec"]["template"] == backups[m]["spec"]["template"], (
            "Concurrent deployment modification"
        )
        assert actual["spec"]["replicas"] == backups[m]["spec"]["replicas"]
    assert (
        subprocess.run(
            ["pgrep", "-u", "1000", "-f", "^nvidia-cuda-mps-(control|server)"],
            capture_output=True,
        ).returncode
        == 1
    )
    state = {
        "state": "RUNNING",
        "start": time.time(),
        "root": str(ROOT),
        "completed": [],
    }
    save_state(state)
    try:
        if not a.skip_profile:
            state["phase"] = "profile-pilot"
            save_state(state)
            apply(backups, 16, 32, "pilot-q16-y32", profile=True)
            measure("profile-pilot", "both", 1, 16, 32, warmup=3)
            flush_profiles()
        cases = [("default", 48, 48, False)] + [
            (f"q{q}-y{y}", q, y, True) for q, y in combinations()
        ]
        for label, qsm, ysm, enabled in cases:
            if a.cases and label not in a.cases:
                continue
            state["phase"] = label
            save_state(state)
            print(
                json.dumps(
                    {"event": "case_start", "label": label, "time": time.time()}
                ),
                flush=True,
            )
            apply(backups, qsm, ysm, label, enabled)
            measure(label + "-qwen-solo", "qwen", 10, qsm, ysm)
            measure(label + "-yolo-solo", "yolo", 300, qsm, ysm)
            measure(label + "-both", "both", 10, qsm, ysm)
            state["completed"].append(label)
            save_state(state)
        state["state"] = "PASS"
    except BaseException as error:
        state.update(state="FAIL", error=repr(error))
        save_state(state)
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
            save_state(state)
    print(json.dumps(state), flush=True)


if __name__ == "__main__":
    main()
