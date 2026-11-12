"""Predeclared descriptive decision rule, not a statistical equivalence test."""


def ranking(rows, band=0.03):
    fastest = min(rows, key=lambda r: r["total"])
    eligible = [r for r in rows if r["total"] <= fastest["total"] * (1 + band)]
    chosen = min(eligible, key=lambda r: (r["cv"], r["total"]))
    pareto = [
        r["label"]
        for r in rows
        if not any(
            o["total"] <= r["total"]
            and o["cv"] <= r["cv"]
            and (o["total"] < r["total"] or o["cv"] < r["cv"])
            for o in rows
        )
    ]
    return {
        "strict_fastest": fastest["label"],
        "balanced": chosen["label"],
        "band": band,
        "eligible": [r["label"] for r in eligible],
        "pareto": pareto,
        "note": "descriptive mean-total tie band then minimumCV completion; not SLO/statistical equivalence",
    }
