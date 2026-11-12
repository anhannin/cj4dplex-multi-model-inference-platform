"""Observer timestamps are upper bounds; do not assume Ready precedes real recovery."""

import shlex
from pathlib import PurePosixPath


def pod_snapshot(pod):
    if not pod:
        return None
    meta = pod.get("metadata", {})
    status = pod.get("status", {})
    candidates = [
        x for x in status.get("containerStatuses", []) if x.get("name") == "yolo"
    ]
    c = candidates[0] if candidates else {}
    return {
        "pod_uid": meta.get("uid"),
        "pod_name": meta.get("name"),
        "phase": status.get("phase"),
        "container_id": c.get("containerID", ""),
        "restart_count": c.get("restartCount", 0),
        "ready": bool(c.get("ready", False)),
        "state": c.get("state", {}),
        "last_state": c.get("lastState", {}),
        "pod_conditions": status.get("conditions", []),
    }


def transition(old, new):
    if new is None:
        return {
            "detected": True,
            "restarted": False,
            "ready": False,
            "pod_replaced": True,
        }
    same = old["pod_uid"] == new["pod_uid"]
    restarted = (
        same
        and new["container_id"] not in ("", old["container_id"])
        and bool(new["state"].get("running"))
        and new["restart_count"] > old["restart_count"]
    )
    detected = (
        not same
        or not new["ready"]
        or new["restart_count"] > old["restart_count"]
        or "terminated" in new["state"]
        or "waiting" in new["state"]
        or new["container_id"] not in ("", old["container_id"])
    )
    return {
        "detected": detected,
        "restarted": restarted,
        "ready": restarted and new["ready"],
        "pod_replaced": not same,
    }


def validate_target(pid, uid, cmdline, models, clients):
    args = shlex.split(cmdline)
    valid = (
        pid == models.get("yolo")
        and pid != models.get("qwen")
        and uid == 1000
        and len(clients) == 2
        and set(clients) == set(models.values())
        and len(args) >= 2
        and PurePosixPath(args[0]).name in ("python", "python3", "python3.12")
        and args[1] == "/experiment/src/yolo_burst_node.py"
    )
    if not valid:
        raise ValueError("Refuse signal to an unverified owned idle model PID")
    return True
