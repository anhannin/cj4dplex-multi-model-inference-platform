"""Offline aggregation: successful latencies plus explicit failure denominator."""

import argparse
import json
from pathlib import Path
import statistics


def stats(values):
    values = sorted(x for x in values if x is not None)

    def q(p):
        if not values:
            return None
        i = (len(values) - 1) * p
        lo = int(i)
        hi = min(lo + 1, len(values) - 1)
        return values[lo] + (values[hi] - values[lo]) * (i - lo)

    return {
        "n": len(values),
        "mean": statistics.mean(values) if values else None,
        "p50": q(0.5),
        "p95": q(0.95),
        "p99": q(0.99),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
    }


def aggregate(rows, windows):
    out = {}
    for kind in sorted({r["model"] for r in rows}):
        all_rows = [r for r in rows if r["model"] == kind and not r["warmup"]]
        good = [r for r in all_rows if r["status"] == "ok"]
        seconds = windows.get(kind, 0)
        result = {
            "attempted": len(all_rows),
            "successful": len(good),
            "failed": len(all_rows) - len(good),
            "failure_rate": (len(all_rows) - len(good)) / len(all_rows)
            if all_rows
            else None,
            "measurement_seconds": seconds,
            "successful_requests_per_second": len(good) / seconds if seconds else None,
            "request_e2e_ms": stats([r["request_e2e_ms"] for r in good]),
        }
        metrics = {}
        for r in good:
            response = r.get("response", {})
            for k, v in {
                **response.get("timings_ms", {}),
                **r.get("post_response_server_timings_ms", {}),
            }.items():
                if v is None or isinstance(v, (int, float)):
                    metrics.setdefault(k, []).append(v)
            for k in ("queue_wait_ms", "processing_ms"):
                if k in response:
                    metrics.setdefault(k, []).append(response[k])
        result.update({k: stats(v) for k, v in metrics.items()})
        if kind == "qwen":
            result["output_tokens"] = stats(
                [r["response"]["output_tokens"] for r in good]
            )
            result["input_tokens"] = stats(
                [r["response"].get("input_tokens") for r in good]
            )
            result["output_tokens_per_second"] = (
                sum(r["response"]["output_tokens"] for r in good) / seconds
                if seconds
                else None
            )
            result["pooled_itl_ms"] = stats(
                [x for r in good for x in r["response"].get("itl_ms", [])]
            )
        out[kind] = result
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("directory", type=Path)
    a = p.parse_args()
    metadata = json.loads((a.directory / "manifest.json").read_text())
    rows = [
        json.loads(line)
        for line in (a.directory / "requests.jsonl").read_text().splitlines()
    ]
    summary = aggregate(rows, metadata["measurement_seconds"])
    (a.directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
