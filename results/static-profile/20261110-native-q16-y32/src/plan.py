"""New-driver randomized fixed-work comparison: control, MPS, STATIC partitions only."""

import random

try:
    from diagnostics.green_burst.generate import burst_template
    from diagnostics.mps_concurrency.overlay import with_mps
    from diagnostics.mps_burst.plan import check_membership as check_membership
except ModuleNotFoundError:
    from base_burst_generate import burst_template
    from overlay import with_mps
    from base_mps_plan import check_membership as check_membership

CONDITIONS = {
    "control": {"mps": False, "static": False, "green": False, "qsm": 48, "ysm": 48},
    "mps-only": {"mps": True, "static": False, "green": False, "qsm": 48, "ysm": 48},
    **{
        f"static-q{q}-y{48 - q}": {
            "mps": True,
            "static": True,
            "green": False,
            "qsm": q,
            "ysm": 48 - q,
        }
        for q in (8, 16, 24, 32, 40)
    },
}


def schedule(rounds=5, seed=20261110):
    rng = random.Random(seed)
    out = []
    for index in range(rounds):
        names = list(CONDITIONS)
        rng.shuffle(names)
        out.extend(
            {
                "round": index,
                "condition": name,
                "label": f"r{index}-{name}",
                **CONDITIONS[name],
            }
            for name in names
        )
    return out


def condition_template(original, model, case, root, label, pipe, partitions):
    t = burst_template(original, model, 48, 48, root, label, False)
    c = t["spec"]["containers"][0]
    c["env"] = [e for e in c["env"] if not e["name"].startswith("GREEN_")]
    c["env"] += [
        {
            "name": "EXPECTED_SMS",
            "value": str(case["qsm"] if model == "qwen" else case["ysm"]),
        },
        {"name": "CUDA_HOME", "value": "/usr/local/cuda-13.1"},
        {
            "name": "LD_LIBRARY_PATH",
            "value": "/usr/local/cuda-13.1/lib64:/usr/local/cuda/lib64:/usr/local/nvidia/lib64",
        },
    ]
    t["spec"]["volumes"].append(
        {
            "name": "cuda131",
            "hostPath": {"path": "/usr/local/cuda-13.1", "type": "Directory"},
        }
    )
    c["volumeMounts"].append(
        {"name": "cuda131", "mountPath": "/usr/local/cuda-13.1", "readOnly": True}
    )
    if case["mps"]:
        t = with_mps(t, pipe)
    if case["static"]:
        t["spec"]["containers"][0]["env"].append(
            {"name": "CUDA_MPS_SM_PARTITION", "value": partitions[model]}
        )
    return t
