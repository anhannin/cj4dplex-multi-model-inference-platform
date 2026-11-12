"""Predeclared complete-block finite burst design and reversible scheduling overlay."""

import random

try:
    from diagnostics.green_burst.generate import burst_template
    from diagnostics.mps_concurrency.overlay import with_mps
except ModuleNotFoundError:
    from base_burst_generate import burst_template
    from overlay import with_mps

CONDITIONS = {
    "control": {"mps": False, "green": False, "qsm": 48, "ysm": 48},
    "mps-only": {"mps": True, "green": False, "qsm": 48, "ysm": 48},
    **{
        f"mps-q{q}-y{48 - q}": {"mps": True, "green": True, "qsm": q, "ysm": 48 - q}
        for q in (8, 16, 24, 32, 40)
    },
}


def schedule(rounds=5, seed=20261110):
    rng = random.Random(seed)
    out = []
    for index in range(rounds):
        order = list(CONDITIONS)
        rng.shuffle(order)
        out.extend(
            {
                "round": index,
                "condition": name,
                "label": f"r{index}-{name}",
                **CONDITIONS[name],
            }
            for name in order
        )
    return out


def condition_template(original, model, case, root, label, pipe):
    t = burst_template(
        original, model, case["qsm"], case["ysm"], root, label, case["green"]
    )
    return with_mps(t, pipe) if case["mps"] else t


def check_membership(clients, model_pids, enabled):
    if len(set(model_pids)) != 2:
        raise ValueError("Exactly two known actual model processes required")
    if enabled:
        valid = len(clients) == 2 and set(clients) == set(model_pids)
    else:
        valid = not clients
    if not valid:
        raise ValueError(
            f"MPS membership mismatch: clients={clients}, models={model_pids}, enabled={enabled}"
        )
    return True
