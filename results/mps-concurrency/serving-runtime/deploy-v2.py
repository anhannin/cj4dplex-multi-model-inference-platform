"""Apply validated MPS/Green normal serving; restore baseline on deployment failure."""

import json
import os
from pathlib import Path
import subprocess
import time

import burst_runner as base
from runtime import live_daemon_pid

ROOT = Path.home() / "cj-serving/mps-green-v1"
DIAG = Path.home() / "cj-mps-concurrency/20261110-v1"
assert base.ROOT == ROOT
state = {"state": "RUNNING", "start_wall_ns": time.time_ns()}
status = ROOT / "verification/deployment-status.json"
backups = {
    m: json.loads((ROOT / "backup" / f"{m}.json").read_text()) for m in ("qwen", "yolo")
}


def save():
    status.write_text(json.dumps(state, indent=2))


def control(pipe, command):
    env = {**os.environ, "CUDA_MPS_PIPE_DIRECTORY": str(pipe)}
    return base.run(
        ["nvidia-cuda-mps-control"], input=command + "\n", env=env, capture_output=True
    ).stdout


save()
try:
    base.run(["python3", "-c", "import rclpy"], capture_output=True)
    prior = json.loads(
        (DIAG / "verification/controller-mps-r1-status.json").read_text()
    )
    assert prior["state"] == "PASS" and prior["restoration"] == "PASS"
    evidence = json.loads(
        (ROOT / "verification/mps-concurrency-summary.json").read_text()
    )
    assert evidence["conservative_overlap_in_uninterrupted_mps_residence_ms"] > 50
    for m, old in backups.items():
        actual = json.loads(
            base.k("get", "deployment", m, "-o", "json", capture_output=True).stdout
        )
        assert actual["spec"]["template"] == old["spec"]["template"]
    # Only our diagnostic daemon, and only after its own clients have drained.
    pipe = DIAG / "mps-pipe"
    if live_daemon_pid(pipe) is not None:
        servers = control(pipe, "get_server_list").split()
        for server in servers:
            assert not control(pipe, f"get_client_list {server}").split()
        control(pipe, "quit")
    unit = Path.home() / ".config/systemd/user/cj-cuda-mps.service"
    unit.parent.mkdir(parents=True, exist_ok=True)
    desired_unit = (ROOT / "cj-cuda-mps.service").read_text()
    if unit.exists():
        assert unit.read_text() == desired_unit, "Refuse replacing another user unit"
    else:
        unit.write_text(desired_unit)
    base.run(["systemctl", "--user", "daemon-reload"])
    base.run(["systemctl", "--user", "enable", "--now", "cj-cuda-mps.service"])
    for _ in range(100):
        if (ROOT / "mps-pipe/control").is_socket():
            break
        time.sleep(0.1)
    assert (ROOT / "mps-pipe/control").is_socket()
    control(ROOT / "mps-pipe", "get_server_list")
    for m in backups:
        t = json.loads((ROOT / f"{m}.json").read_text())["spec"]["template"]
        patch = ROOT / "verification" / f"{m}-serving-patch.json"
        patch.write_text(
            json.dumps([{"op": "replace", "path": "/spec/template", "value": t}])
        )
        base.k("patch", "deployment", m, "--type=json", "--patch-file", str(patch))
    for m in backups:
        base.k("rollout", "status", "deployment/" + m, "--timeout=750s", timeout=770)
    servers = control(ROOT / "mps-pipe", "get_server_list").split()
    assert len(servers) == 1
    clients = control(ROOT / "mps-pipe", "get_client_list " + servers[0]).split()
    assert len(set(clients)) == 2
    state["membership"] = {"server": servers[0], "clients": clients}
    # Existing native ROS client exercises unchanged request/result protocol.
    env = {**os.environ, "ROS_DOMAIN_ID": "42"}
    with (ROOT / "verification/health.log").open("w") as log:
        base.run(
            [
                "python3",
                str(Path.home() / "cj-ros2/benchmark/bench_ros2.py"),
                "--models",
                "both",
                "--output",
                str(ROOT / "verification/health"),
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
    state["state"] = "PASS"
except BaseException as error:
    state.update(state="FAIL", error=repr(error))
    save()
    try:
        base.restore(backups)
        state["rollback"] = "PASS"
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", "cj-cuda-mps.service"],
            check=False,
        )
    except BaseException as rollback_error:
        state["rollback"] = repr(rollback_error)
    raise
finally:
    state["end_wall_ns"] = time.time_ns()
    save()
print(json.dumps(state), flush=True)
