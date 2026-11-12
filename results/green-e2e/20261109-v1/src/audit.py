"""Offline per-request fixed-work/resource/routing and live-log coverage checks."""

import argparse
import json
from pathlib import Path
import hashlib
import re


def detection_fidelity(reference, actual):
    assert len(reference) == len(actual)
    available = set(range(len(actual)))
    for ref in reference:
        choices = []
        for index in available:
            box = actual[index]
            if box["class_id"] != ref["class_id"]:
                continue
            a, b = ref["xyxy"], box["xyxy"]
            intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
                0, min(a[3], b[3]) - max(a[1], b[1])
            )
            union = (
                (a[2] - a[0]) * (a[3] - a[1])
                + (b[2] - b[0]) * (b[3] - b[1])
                - intersection
            )
            choices.append((intersection / union if union else 0, index))
        assert choices, "Unmatched detection class"
        overlap, index = max(choices)
        assert (
            overlap >= 0.98
            and abs(ref["confidence"] - actual[index]["confidence"]) <= 0.02
        )
        available.remove(index)
    assert not available


def audit_run(root, directory, workload, reference):
    manifest = json.loads((directory / "manifest.json").read_text())
    assert manifest["state"] == "PASS"
    assert manifest["ros_domain"] == 73
    assert manifest["images"] == (
        [{"name": "bus.jpg", "sha256": workload["image_sha256"]}]
        if "yolo" in manifest["models"]
        else []
    )
    rows = [
        json.loads(line)
        for line in (directory / "requests.jsonl").read_text().splitlines()
    ]
    match = re.match(r"q(\d+)-y(\d+)", directory.name)
    expected = (
        {"qwen": int(match[1]), "yolo": int(match[2])}
        if match
        else (
            {"qwen": 16, "yolo": 32}
            if directory.name == "profile-pilot"
            else {"qwen": 48, "yolo": 48}
        )
    )
    enabled = (
        directory.name != "profile-pilot"
        and bool(match)
        or directory.name == "profile-pilot"
    )
    seen = set()
    counts = {}
    outputs = set()
    for row in rows:
        rid = row["request_id"]
        assert rid not in seen
        seen.add(rid)
        response = row["response"]
        assert (
            row["status"] == "ok"
            and response["status"] == "ok"
            and response["request_id"] == rid
        )
        assert response["assigned_sms"] == expected[row["model"]]
        assert response["green_enabled"] == enabled
        if row["model"] == "qwen":
            assert response["input_tokens"] == 512 and response["output_tokens"] == 128
            assert response["input_ids_sha256"] == workload["input_ids_sha256"]
            outputs.add(hashlib.sha256(response["text"].encode()).hexdigest())
        else:
            assert (
                response["width"] > 0
                and response["height"] > 0
                and response["detections"]
            )
        if not row["warmup"]:
            counts[row["model"]] = counts.get(row["model"], 0) + 1
    for row in rows:
        if row["model"] == "yolo":
            detection_fidelity(reference, row["response"]["detections"])
    publication = {}
    for model in manifest["models"]:
        expected = {
            r["request_id"] for r in rows if r["model"] == model and not r["warmup"]
        }
        events = {}
        for line in (
            (root / "results" / (directory.name + "-" + model + ".log"))
            .read_text()
            .splitlines()
        ):
            start = line.find('{"event"')
            if start < 0:
                continue
            try:
                event = json.loads(line[start:])
            except ValueError:
                continue
            if (
                event.get("event") == "publication_finished"
                and event.get("request_id") in expected
            ):
                events[event["request_id"]] = event
        publication[model] = {
            "expected": len(expected),
            "captured": len(events),
            "coverage_complete": len(events) == len(expected),
            "acknowledged_false": sum(
                not event.get("acknowledged", False) for event in events.values()
            ),
        }
    return {
        "run": directory.name,
        "state": "PASS",
        "counts": counts,
        "requests_with_warmup": len(rows),
        "qwen_output_text_hashes": len(outputs),
        "publications": publication,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    a = p.parse_args()
    workload = json.loads((a.root / "workload.json").read_text())
    assert (
        hashlib.sha256(json.dumps(workload["input_ids"]).encode()).hexdigest()
        == workload["input_ids_sha256"]
    )
    reference_rows = [
        json.loads(line)
        for line in (a.root / "results/default-yolo-solo/requests.jsonl")
        .read_text()
        .splitlines()
    ]
    reference = next(
        r["response"]["detections"] for r in reference_rows if not r["warmup"]
    )
    reports = []
    for file in sorted((a.root / "results").glob("*/manifest.json")):
        reports.append(audit_run(a.root, file.parent, workload, reference))
    (a.root / "verification/protocol-audit.json").write_text(
        json.dumps(reports, indent=2)
    )
    print(
        json.dumps(
            {
                "runs": len(reports),
                "requests_with_warmup": sum(r["requests_with_warmup"] for r in reports),
                "log_coverage_gaps": [
                    (r["run"], m)
                    for r in reports
                    for m, v in r["publications"].items()
                    if not v["coverage_complete"]
                ],
            }
        )
    )


if __name__ == "__main__":
    main()
