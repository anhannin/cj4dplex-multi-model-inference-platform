"""Reversible three-window profiling. Run only on the Spark host."""

import copy
import datetime
import json
from pathlib import Path
import subprocess
import time

MODELS = ("qwen", "yolo")
ROOT = Path.home() / "cj-nsys-diagnostics/20261103-v1"


def make_diagnostic(original, model, root):
    obj = copy.deepcopy(original)
    obj.pop("status", None)
    for key in (
        "resourceVersion",
        "uid",
        "generation",
        "creationTimestamp",
        "managedFields",
    ):
        obj["metadata"].pop(key, None)
    obj["metadata"].get("annotations", {}).pop(
        "kubectl.kubernetes.io/last-applied-configuration", None
    )
    pod = obj["spec"]["template"]["spec"]
    container = next(c for c in pod["containers"] if c["name"] == model)
    container["command"] = ["/bin/bash", "/diagnostics/launch_node.sh", model]
    container["args"] = []
    container["volumeMounts"] += [
        {"name": "nsight-diagnostics", "mountPath": "/diagnostics", "readOnly": True},
        {"name": "nsight-reports", "mountPath": "/profiles"},
    ]
    pod["volumes"] += [
        {"name": "nsight-diagnostics", "configMap": {"name": "cj-nsys-diagnostics"}},
        {
            "name": "nsight-reports",
            "hostPath": {"path": str(Path(root) / "reports"), "type": "Directory"},
        },
    ]
    return obj


def execute(args, **kwargs):
    return subprocess.run(
        args, check=True, timeout=kwargs.pop("timeout", 180), **kwargs
    )


def kubectl(*args, **kwargs):
    return execute(["kubectl", "-n", "cj-inference", *args], **kwargs)


def podexec(model, *args, **kwargs):
    return kubectl("exec", "deployment/" + model, "--", *args, **kwargs)


def wait_until(predicate, seconds, label):
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() > deadline:
            raise TimeoutError(label)
        time.sleep(0.2)


def benchmark_environment(original, benchmark_dir):
    import os

    env = dict(original)
    env["PYTHONPATH"] = str(benchmark_dir) + os.pathsep + env.get("PYTHONPATH", "")
    return env


def map_capture_files(files, phases):
    import re

    assert len(files) == len(phases), (files, phases)

    def number(name):
        match = re.search(r"\.(\d+)\.nsys-rep$", name)
        return int(match.group(1)) if match else 0

    return dict(zip(phases, sorted(files, key=number)))


def main():
    assert subprocess.check_output(["hostname"], text=True).strip() == "spark-e6d6"
    root = ROOT
    state = {
        "state": "running",
        "phase": "preparing",
        "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "diagnostic only, not a performance baseline",
        "reports": {},
    }

    def save():
        (root / "controller-status.json").write_text(json.dumps(state, indent=2) + "\n")

    save()
    backups = {
        m: json.loads((root / "backup" / (m + ".json")).read_text()) for m in MODELS
    }
    control = root / "reports/control/capture"
    applied = False
    client = ["python3", str(root / "scripts/generated/bench_profile.py")]
    env = benchmark_environment(
        __import__("os").environ, Path.home() / "cj-ros2/benchmark"
    )

    def bench(name, models, n, warmup):
        dest = root / "clients" / name
        with (root / "evidence" / (name + "-client.log")).open("w") as output:
            execute(
                client
                + [
                    "--models",
                    models,
                    "--output",
                    str(dest),
                    "--samples",
                    str(n),
                    "--warmup",
                    str(warmup),
                    "--max-new-tokens",
                    "128",
                    "--timing-mode",
                    "tokens",
                ],
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=420,
            )

    try:
        data = {"launch_node.sh": (root / "scripts/launch_node.sh").read_text()}
        for m in MODELS:
            data[m + "_node.py"] = (
                root / "scripts/generated" / (m + "_node.py")
            ).read_text()
        cm = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "cj-nsys-diagnostics", "namespace": "cj-inference"},
            "data": data,
        }
        (root / "evidence/configmap.json").write_text(json.dumps(cm))
        kubectl("apply", "-f", str(root / "evidence/configmap.json"))
        for m in MODELS:
            target = make_diagnostic(backups[m], m, str(root))
            file = root / "evidence" / (m + "-diagnostic.json")
            file.write_text(json.dumps(target, indent=2))
            applied = True
            kubectl("apply", "-f", str(file))
        for m in MODELS:
            kubectl(
                "rollout", "status", "deployment/" + m, "--timeout=660s", timeout=680
            )
        state["phase"] = "warming"
        save()
        bench("warmup", "both", 1, 5)
        phases = [
            ("qwen-only", "qwen", 2),
            ("yolo-only", "yolo", 100),
            ("concurrent", "both", 2),
        ]
        for phase, models, count in phases:
            state["phase"] = phase
            save()
            print("START", phase, flush=True)
            temp = control.with_suffix(".new")
            temp.write_text(phase)
            temp.replace(control)
            for m in MODELS:
                started = root / "reports/control" / (m + ".started")
                wait_until(
                    lambda p=started: p.exists() and p.read_text() == phase,
                    120,
                    m + " capture start",
                )
            bench(phase, models, count, 0)
            time.sleep(1)
            control.unlink()
            for m in MODELS:
                stopped = root / "reports/control" / (m + ".stopped")
                wait_until(
                    lambda p=stopped: p.exists() and p.read_text() == phase,
                    120,
                    m + " capture stop",
                )
            for m in MODELS:
                with (root / "evidence" / (phase + "-" + m + ".log")).open(
                    "w"
                ) as output:
                    kubectl("logs", "deployment/" + m, stdout=output)
            state.setdefault("captured_phases", []).append(phase)
            save()
            print("CAPTURED_RANGE", phase, flush=True)
        state["phase"] = "flushing"
        save()
        for m in MODELS:
            podexec(
                m,
                "nsys",
                "shutdown",
                "--session=cj-" + m + "-diagnostic",
                "--kill=none",
                timeout=240,
            )
            directory = root / "reports" / m
            wait_until(
                lambda d=directory: len(list(d.glob("*.nsys-rep"))) == 3,
                120,
                m + " report flush",
            )
            mapped = map_capture_files(
                [p.name for p in directory.glob("*.nsys-rep")], [p[0] for p in phases]
            )
            for phase, filename in mapped.items():
                state["reports"].setdefault(phase, {})[m] = filename
        save()
        state["phase"] = "exporting"
        save()
        for phase, mapping in state["reports"].items():
            for m, filename in mapping.items():
                input_file = "/profiles/" + m + "/" + filename
                sql = "/profiles/" + m + "/" + phase + ".sqlite"
                with (root / "evidence" / (phase + "-" + m + "-export.log")).open(
                    "w"
                ) as log:
                    podexec(
                        m,
                        "nsys",
                        "export",
                        "--type",
                        "sqlite",
                        "--output",
                        sql,
                        input_file,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        timeout=240,
                    )
                    podexec(
                        m,
                        "nsys",
                        "stats",
                        "--report",
                        "cuda_gpu_kern_sum,cuda_api_sum,cuda_gpu_mem_time_sum,osrt_sum,nvtx_sum",
                        "--format",
                        "csv",
                        sql,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        timeout=240,
                    )
        state["state"] = "PASS"
    except Exception as error:
        state.update(state="FAIL", error=repr(error))
        raise
    finally:
        control.unlink(missing_ok=True)
        if applied:
            state["phase"] = "restoring"
            save()
            restored = True
            for m in MODELS:
                patch = [
                    {
                        "op": "replace",
                        "path": "/spec/template",
                        "value": backups[m]["spec"]["template"],
                    },
                    {
                        "op": "replace",
                        "path": "/spec/replicas",
                        "value": backups[m]["spec"]["replicas"],
                    },
                ]
                try:
                    kubectl(
                        "patch",
                        "deployment/" + m,
                        "--type=json",
                        "-p",
                        json.dumps(patch),
                    )
                except Exception:
                    restored = False
            for m in MODELS:
                try:
                    kubectl(
                        "rollout",
                        "status",
                        "deployment/" + m,
                        "--timeout=660s",
                        timeout=680,
                    )
                except Exception:
                    restored = False
            state["baseline_restored"] = restored
            if not restored:
                state["state"] = "FAIL"
            else:
                kubectl(
                    "delete",
                    "configmap",
                    "cj-nsys-diagnostics",
                    "--ignore-not-found=true",
                )
        state["phase"] = "complete"
        state["finished_at_utc"] = datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat()
        save()
        print(json.dumps(state, indent=2), flush=True)


if __name__ == "__main__":
    main()
