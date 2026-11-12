"""Minimal same-UID MPS socket overlay, leaving model application code untouched."""

import copy
from pathlib import PurePosixPath


def with_mps(template, pipe):
    if not PurePosixPath(pipe).is_absolute():
        raise ValueError("MPS socket path must be absolute")
    t = copy.deepcopy(template)
    c = t["spec"]["containers"][0]
    # Green resource caps remain the only resource-cap mechanism in this experiment.
    c["env"] = [
        e
        for e in c.get("env", [])
        if e["name"]
        not in ("CUDA_MPS_PIPE_DIRECTORY", "CUDA_MPS_ACTIVE_THREAD_PERCENTAGE")
    ]
    c["env"].append({"name": "CUDA_MPS_PIPE_DIRECTORY", "value": pipe})
    c["volumeMounts"] = [
        v for v in c.get("volumeMounts", []) if v["name"] != "mps-pipe"
    ]
    c["volumeMounts"].append({"name": "mps-pipe", "mountPath": pipe})
    t["spec"]["volumes"] = [
        v for v in t["spec"].get("volumes", []) if v["name"] != "mps-pipe"
    ]
    t["spec"]["volumes"].append(
        {"name": "mps-pipe", "hostPath": {"path": pipe, "type": "Directory"}}
    )
    return t
