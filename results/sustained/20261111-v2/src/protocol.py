"""Pure scheduling/selection rules fixed before sustained measurements."""

import math
import random

CONDITIONS = ("control", "mps-only", "static-q8-y40", "static-q16-y32")


def percentile(values, p=95):
    a = sorted(values)
    if not a:
        return None
    index = (len(a) - 1) * p / 100
    lo, hi = math.floor(index), math.ceil(index)
    return a[lo] + (a[hi] - a[lo]) * (index - lo)


def scheduled_offsets(rate, duration):
    if (
        not math.isfinite(rate)
        or not math.isfinite(duration)
        or rate <= 0
        or duration <= 0
    ):
        raise ValueError("Positive finite rate/duration required")
    return [
        round(i * 1e9 / rate)
        for i in range(math.ceil(rate * duration))
        if round(i * 1e9 / rate) < round(duration * 1e9)
    ]


def choose_rates(rows):
    stable = sorted(
        {
            r["rate"]
            for r in rows
            if r["errors"] == 0
            and r["tail_queue_mean_ms"] <= 100
            and r["queue_slope_rps"] <= 0.1
        }
    )
    if len(stable) < 2:
        raise ValueError("Need two stable pilot rates")
    high = stable[-1]
    low = min(stable[:-1], key=lambda r: abs(r - high * 0.5))
    return [low, high]


def make_schedule(rates, rounds=5, seed=20261111):
    rng = random.Random(seed)
    out = []
    for index in range(rounds):
        names = list(CONDITIONS)
        rng.shuffle(names)
        for name in names:
            shuffled = list(rates)
            rng.shuffle(shuffled)
            for rate in shuffled:
                out.append(
                    {
                        "condition": name,
                        "round": index,
                        "rate": rate,
                        "label": f"r{index}-{name}-rate{rate}",
                    }
                )
    return out


def validity(lags_ms, errors):
    p95, maximum = percentile(lags_ms), max(lags_ms, default=0)
    return {
        "valid": not errors and p95 is not None and p95 <= 10 and maximum <= 100,
        "lag_p95_ms": p95,
        "lag_max_ms": maximum,
        "errors": errors,
    }


def pilot_queue(rows, t0, duration):
    ys = [r for r in rows if r["model"] == "yolo" and r["status"] == "ok"]
    tail = [r for r in ys if r["sent_ns"] >= t0 + duration * 0.5e9]
    waits = [r["response"]["queue_wait_ms"] for r in tail]
    # Regression of server FIFO depth sampled once/sec in the second half.
    samples = []
    for second in range(math.ceil(duration / 2), math.ceil(duration)):
        now = t0 + second * 1_000_000_000
        depth = sum(
            r["response"]["server_enqueued_perf_ns"]
            <= now
            < r["response"]["server_started_perf_ns"]
            for r in ys
        )
        samples.append((second, depth))
    mx = sum(x for x, _ in samples) / max(1, len(samples))
    my = sum(y for _, y in samples) / max(1, len(samples))
    den = sum((x - mx) ** 2 for x, _ in samples)
    slope = sum((x - mx) * (y - my) for x, y in samples) / den if den else 0
    return {
        "tail_queue_mean_ms": sum(waits) / len(waits) if waits else float("inf"),
        "queue_slope_rps": slope,
        "errors": sum(r["status"] != "ok" for r in rows),
    }


def apply_send_record(entry, sent, returned, scheduled):
    """Reconcile publisher shared memory independently of response callback order."""
    if sent <= 0:
        raise ValueError("No published timestamp")
    entry.update(sent_ns=sent, publish_return_ns=returned, scheduled_ns=scheduled)
    if entry["status"] == "unissued":
        entry["status"] = "pending"
    if "received_ns" in entry:
        entry["request_e2e_ms"] = (entry["received_ns"] - sent) / 1e6
        entry["scheduled_e2e_ms"] = (entry["received_ns"] - scheduled) / 1e6
