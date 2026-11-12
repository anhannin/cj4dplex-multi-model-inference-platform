"""Validate observed allocation, without claiming global or memory isolation."""


def validate_native(result):
    assert len(result["parts"]) == 2
    counts = [p["actual_sms"] for p in result["parts"]]
    assert all(n > 0 for n in counts) and sum(counts) == result["total_sms"]
    sets = [set(p["smids"]) for p in result["parts"]]
    assert all(s and len(s) <= n for s, n in zip(sets, counts))
    assert not sets[0].intersection(sets[1]), "Observed physical SM overlap"
    return {
        "observed_disjoint": True,
        "observed_sm_counts": [len(s) for s in sets],
        "assigned_sm_counts": counts,
        "global_reservation_claimed": False,
    }
