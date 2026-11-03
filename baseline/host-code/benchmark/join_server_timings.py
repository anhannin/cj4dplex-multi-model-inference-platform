"""Join post-publication server timings offline; never fake fields in sent responses."""

import argparse
import json
from pathlib import Path
from aggregate_latency import aggregate


def join(directory):
    rows = [
        json.loads(x) for x in (directory / "requests.jsonl").read_text().splitlines()
    ]
    events = {}
    for kind in ("qwen", "yolo"):
        path = directory / f"{kind}-server.log"
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            start = line.find('{"event"')
            if start < 0:
                continue
            try:
                event = json.loads(line[start:])
            except ValueError:
                continue
            rid = event.get("request_id")
            if rid and event["event"] in (
                "publication_finished",
                "processing_finished",
            ):
                events.setdefault(rid, {})[event["event"]] = event
    for row in rows:
        found = events.get(row["request_id"], {})
        publication = found.get("publication_finished", {})
        processing = found.get("processing_finished", {})
        metrics = {k: v for k, v in publication.items() if k.endswith("_ms")}
        metrics["worker_busy_ms"] = processing.get("worker_busy_ms")
        response = row.get("response", {})
        callback_ready = response.get("timings_ms", {}).get(
            "callback_to_result_ready_ms"
        )
        pieces = [
            publication.get(k)
            for k in (
                "publisher_create_ms",
                "result_discovery_ms",
                "response_serialize_ms",
            )
        ]
        if callback_ready is not None and all(x is not None for x in pieces):
            metrics["transport_client_residual_ms"] = (
                row["request_e2e_ms"] - callback_ready - sum(pieces)
            )
        row["negative_residual_flag"] = (
            metrics.get("transport_client_residual_ms", 0) < 0
        )
        row["post_response_server_timings_ms"] = metrics
        row["server_events_complete"] = bool(publication and processing)
    (directory / "joined-requests.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    )
    manifest = json.loads((directory / "manifest.json").read_text())
    summary = aggregate(rows, manifest["measurement_seconds"])
    (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("directory", type=Path)
    print(json.dumps(join(p.parse_args().directory), indent=2))
