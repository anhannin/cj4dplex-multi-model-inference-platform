"""Interval union/intersection and independently anchored per-report clock alignment."""

import statistics


def union(intervals):
    out = []
    for lo, hi in sorted(intervals):
        if hi <= lo:
            continue
        if out and lo <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def intersect(a, b):
    a, b = union(a), union(b)
    i = j = 0
    out = []
    while i < len(a) and j < len(b):
        lo = max(a[i][0], b[j][0])
        hi = min(a[i][1], b[j][1])
        if lo < hi:
            out.append((lo, hi))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return out


def duration(intervals):
    return sum(b - a for a, b in intervals)


def overlap_bounds(a, b, error_a, error_b):
    observed = duration(intersect(a, b))
    lower = duration(
        intersect(
            [(x + error_a, y - error_a) for x, y in a if y - x > 2 * error_a],
            [(x + error_b, y - error_b) for x, y in b if y - x > 2 * error_b],
        )
    )
    upper = duration(
        intersect(
            [(x - error_a, y + error_a) for x, y in a],
            [(x - error_b, y + error_b) for x, y in b],
        )
    )
    return {"observed": observed, "lower": lower, "upper": upper}


def fit_clock(anchors):
    if len(anchors) < 3:
        raise ValueError("At least3 independent bracketed clock anchors required")
    anchors = sorted(anchors, key=lambda r: r["trace_ns"])
    base_trace = anchors[0]["trace_ns"]
    base_host = (anchors[0]["pre_ns"] + anchors[0]["post_ns"]) // 2
    xs = [r["trace_ns"] - base_trace for r in anchors]
    ys = [(r["pre_ns"] + r["post_ns"]) / 2 - base_host for r in anchors]
    slope, intercept = statistics.linear_regression(xs, ys)
    if abs(slope - 1) > 0.001:
        raise ValueError("Clock scale mismatch >1000ppm")

    def mapping(value):
        return base_host + round(intercept + slope * (value - base_trace))

    residuals = [
        abs(mapping(r["trace_ns"]) - (r["pre_ns"] + r["post_ns"]) / 2) for r in anchors
    ]
    halfwidths = [(r["post_ns"] - r["pre_ns"]) / 2 for r in anchors]
    uncertainty = max(err + half for err, half in zip(residuals, halfwidths))
    return {
        "map": mapping,
        "anchors": len(anchors),
        "base_trace_ns": base_trace,
        "base_host_ns": base_host,
        "slope": slope,
        "intercept_relative_ns": intercept,
        "max_midpoint_residual_ns": max(residuals),
        "max_anchor_bracket_ns": 2 * max(halfwidths),
        "empirical_alignment_error_ns": uncertainty,
        "note": "empirical anchor-fit/bracket tolerance, not a hardware clock accuracy guarantee",
    }
