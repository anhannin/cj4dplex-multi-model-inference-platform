"""Actual host-clock worker phases and queue occupancy; never fabricate GPU activity."""

from collections import defaultdict
import json
from pathlib import Path


def worker_record(row, finish_event, t0):
    r = row["response"]
    start = r["server_started_perf_ns"]
    model_start = r["model_start_perf_ns"]
    model_end = r["model_end_perf_ns"]
    processing_end = start + round(r["processing_ms"] * 1e6)
    worker_end = start + round(finish_event["worker_busy_ms"] * 1e6)
    times = [
        r["server_enqueued_perf_ns"],
        start,
        model_start,
        model_end,
        processing_end,
        worker_end,
    ]
    if any(b < a for a, b in zip(times, times[1:])):
        raise ValueError(
            ("Invalid actual worker phase order", row["request_id"], times)
        )

    def relative(value):
        return (value - t0) / 1e9

    phases = []

    def add(kind, a, b):
        if b > a:
            phases.append({"kind": kind, "start": relative(a), "end": relative(b)})

    add("preprocess", start, model_start)
    first = None
    if row["model"] == "qwen":
        first = r["server_enqueued_perf_ns"] + round(
            r["timings_ms"]["server_ttft_ms"] * 1e6
        )
        if not model_start <= first <= model_end:
            raise ValueError("Token timestamp outside generate call")
        add("first_token", model_start, first)
        add("generation", first, model_end)
    else:
        add("predict", model_start, model_end)
    add("postprocess", model_end, processing_end)
    add("publication", processing_end, worker_end)
    return {
        "id": row["request_id"],
        "model": row["model"],
        "index": row["index"] + 1,
        "sent": relative(row["sent_ns"]),
        "enqueued": relative(r["server_enqueued_perf_ns"]),
        "worker_start": relative(start),
        "worker_end": relative(worker_end),
        "received": relative(row["received_ns"]),
        "queue": [relative(r["server_enqueued_perf_ns"]), relative(start)],
        "phases": phases,
        "first_token": relative(first) if first is not None else None,
        "queue_ms": r["queue_wait_ms"]
        if "queue_wait_ms" in r
        else (start - r["server_enqueued_perf_ns"]) / 1e6,
    }


def queue_events(intervals):
    events = defaultdict(int)
    for a, b in intervals:
        if b < a:
            raise ValueError("Negative queue interval")
        events[a] += 1
        events[b] -= 1
    depth = 0
    out = []
    for stamp, delta in sorted(events.items()):
        depth += delta
        if depth < 0:
            raise ValueError("Queue underflow")
        out.append([stamp, depth])
    if depth:
        raise ValueError("Unfinished queue")
    return out


def parse_finishes(path):
    out = {}
    for line in Path(path).read_text().splitlines():
        i = line.find('{"event"')
        if i < 0:
            continue
        try:
            e = json.loads(line[i:])
        except ValueError:
            continue
        if e.get("event") == "processing_finished":
            out[e["request_id"]] = e
    return out


def load_round(root, index):
    root = Path(root)
    cases = []
    for condition, title in [
        ("control", "MPS 없음"),
        ("mps-only", "일반 MPS"),
        ("static-q8-y40", "MPS 정적 Qwen8 / YOLO40"),
    ]:
        name = f"r{index}-{condition}"
        path = root / "results" / name
        manifest = json.loads((path / "manifest.json").read_text())
        summary = json.loads((path / "summary.json").read_text())
        assert manifest["state"] == "PASS" and manifest["completed"] == 310
        rows = [
            json.loads(line)
            for line in (path / "final-requests.jsonl").read_text().splitlines()
        ]
        t0 = manifest["batch_t0_perf_ns"]
        lanes = {}
        for model in ("qwen", "yolo"):
            finishes = parse_finishes(root / "logs" / f"{name}-{model}.log")
            selected = sorted(
                [r for r in rows if r["model"] == model], key=lambda x: x["index"]
            )
            assert len(selected) == (10 if model == "qwen" else 300)
            records = [
                worker_record(row, finishes[row["request_id"]], t0) for row in selected
            ]
            assert all(
                b["worker_start"] + 1e-6 >= a["worker_end"]
                for a, b in zip(records, records[1:])
            )
            received = max(r["received"] for r in records)
            assert abs(received - summary["model_completion_ms"][model] / 1000) < 1e-8
            lanes[model] = {
                "requests": records,
                "queue": queue_events([r["queue"] for r in records]),
                "last_received": received,
                "last_worker_end": max(r["worker_end"] for r in records),
            }
        cases.append(
            {
                "trial": name,
                "condition": condition,
                "title": title,
                "round": index,
                "makespan": summary["overall_completion_ms"] / 1000,
                "lanes": lanes,
            }
        )
    return cases
