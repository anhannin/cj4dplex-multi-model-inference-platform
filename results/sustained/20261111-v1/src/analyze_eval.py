"""Full native-static experiment audit + distributions; profile runs never pooled."""

import argparse
import csv
import json
from pathlib import Path
from burst_analysis import load_trial
from metrics import request_parts, burst_completion
from stage_metrics import distribution
from summary_math import ranking

p = argparse.ArgumentParser()
p.add_argument("--root", required=True, type=Path)
a = p.parse_args()
root = a.root
status = json.loads((root / "verification/controller-status.json").read_text())
assert status["state"] == "PASS" and status["restoration"] == "PASS"
workload = json.loads((root / "workload.json").read_text())
plan = json.loads((root / "schedule.json").read_text())
assert len(plan) == 35 and len(status["completed"]) == 35
assert {d.name for d in (root / "results").iterdir() if d.is_dir()} == {
    e["label"] for e in plan
}
trials = []
audits = []
groups = {}
allrows = {}
for e in plan:
    name = e["label"]
    path = root / "results" / name
    t = load_trial(path)
    t.update(condition=e["condition"], round=e["round"])
    rows = [
        json.loads(v) for v in (path / "final-requests.jsonl").read_text().splitlines()
    ]
    for model in ("qwen", "yolo"):
        selected = [r for r in rows if r["model"] == model]
        extra = (
            ("server_ttft_ms",)
            if model == "qwen"
            else (
                "yolo_preprocess_ms",
                "yolo_inference_ms",
                "yolo_postprocess_ms",
                "predict_overhead_ms",
            )
        )
        for key in extra:
            t["models"][model]["metrics"][key] = distribution(
                [r["response"]["timings_ms"][key] for r in selected]
            )
    trials.append(t)
    groups.setdefault(e["condition"], []).append(t)
    allrows.setdefault(e["condition"], []).extend(rows)
    part = json.loads((root / "verification" / f"{name}-partitions.json").read_text())
    assert bool(part["case"]["static"]) == e["static"]
    for stage, expected in (
        ("warmup", {"qwen": 3, "yolo": 30}),
        ("results", {"qwen": 10, "yolo": 300}),
    ):
        run = name + "-warmup" if stage == "warmup" else name
        directory = root / stage / run
        manifest = json.loads((directory / "manifest.json").read_text())
        records = [
            json.loads(line)
            for line in (directory / "final-requests.jsonl").read_text().splitlines()
        ]
        assert (
            manifest["state"] == "PASS"
            and manifest["expected"] == expected
            and manifest["ros_domain"] == 74
        )
        burst_completion(records, manifest["batch_t0_perf_ns"], expected)
        ids = {m: set() for m in expected}
        for r in records:
            response = r["response"]
            model = r["model"]
            assert (
                abs(r["request_e2e_ms"] - (r["received_ns"] - r["sent_ns"]) / 1e6)
                < 1e-6
            )
            assert (
                abs(
                    r["batch_origin_e2e_ms"]
                    - (r["received_ns"] - manifest["batch_t0_perf_ns"]) / 1e6
                )
                < 1e-6
            )
            assert r["sent_ns"] <= response["server_enqueued_perf_ns"] + 1_000_000
            ids[model].add(r["request_id"])
            assert response["status"] == "ok" and not response["green_enabled"]
            assert response["assigned_sms"] == e["qsm" if model == "qwen" else "ysm"]
            assert (
                response["request_id"] == r["request_id"]
                and response["run_id"] == manifest["run_id"]
            )
            assert (
                response["server_started_perf_ns"]
                >= response["server_enqueued_perf_ns"]
            )
            assert response["model_start_perf_ns"] >= response["server_started_perf_ns"]
            assert response["model_end_perf_ns"] >= response["model_start_perf_ns"]
            assert (
                abs(
                    (
                        response["server_started_perf_ns"]
                        - response["server_enqueued_perf_ns"]
                    )
                    / 1e6
                    - response["queue_wait_ms"]
                )
                < 0.001
            )
            timings = response["timings_ms"]
            key = "generate_wall_ms" if model == "qwen" else "predict_wall_ms"
            parts = request_parts(
                r["request_e2e_ms"],
                response["queue_wait_ms"],
                response["processing_ms"],
                timings[key],
                timings["gpu_forward_span_ms"],
            )
            assert all(abs(parts[k] - r["components"][k]) < 1e-6 for k in parts)
            assert (
                abs(
                    sum(v for k, v in parts.items() if k != "gpu_forward_span_ms")
                    - r["request_e2e_ms"]
                )
                < 1e-5
            )
            if model == "qwen":
                assert (
                    response["input_tokens"] == 512 and response["output_tokens"] == 128
                )
                assert response["gpu_forward_lengths"] == [512] + [1] * 127
            else:
                assert response["gpu_forward_shape"] == [1, 3, 640, 640]
        publications = {}
        for model in expected:
            found = {}
            overflow = []
            for line in (root / "logs" / f"{run}-{model}.log").read_text().splitlines():
                start = line.find('{"event"')
                if start < 0:
                    continue
                try:
                    v = json.loads(line[start:])
                except ValueError:
                    continue
                if v.get("event") == "queue_full":
                    overflow.append(v)
                if (
                    v.get("event") == "publication_finished"
                    and v.get("request_id") in ids[model]
                ):
                    found[v["request_id"]] = v
            assert not overflow
            assert set(found) == ids[model], (
                "Missing publication log",
                run,
                model,
                len(found),
                len(ids[model]),
            )
            assert all(v.get("acknowledged") for v in found.values()), (
                "ACK failed",
                run,
                model,
            )
            publications[model] = len(found)
        audits.append(
            {
                "run": run,
                "kind": stage,
                "state": "PASS",
                "counts": expected,
                "publications": publications,
            }
        )
    for phase in ("pre", "warm", "post"):
        member = json.loads(
            (root / "verification" / f"{name}-{phase}-mps-membership.json").read_text()
        )
        assert member["expected_mps"] == e["mps"]
        assert (
            (
                len(member["clients"]) == 2
                and set(member["clients"]) == set(member["models"].values())
            )
            if e["mps"]
            else not member["clients"]
        )
records = []
for label, items in groups.items():
    assert len(items) == 5
    record = {
        "label": label,
        "n_bursts": 5,
        "total_ms": distribution(
            [t["completion"]["overall_completion_ms"] for t in items]
        ),
        "yolo_ms": distribution(
            [t["completion"]["model_completion_ms"]["yolo"] for t in items]
        ),
        "qwen_ms": distribution(
            [t["completion"]["model_completion_ms"]["qwen"] for t in items]
        ),
        "dispatch_ms": distribution([t["dispatch_window_ms"] for t in items]),
        "models": {},
    }
    for model in ("qwen", "yolo"):
        subsets = [r for r in allrows[label] if r["model"] == model]
        per_request = {
            k: distribution([r[k] for r in subsets])
            for k in ("request_e2e_ms", "batch_origin_e2e_ms")
        }
        for k in subsets[0]["components"]:
            per_request[k] = distribution([r["components"][k] for r in subsets])
        for k in items[0]["models"][model]["metrics"]:
            if k not in per_request:
                per_request[k] = distribution(
                    [r["response"]["timings_ms"][k] for r in subsets]
                )
        record["models"][model] = {
            "n_requests": len(subsets),
            "pooled_descriptive": per_request,
            "per_trial_metrics": [t["models"][model]["metrics"] for t in items],
        }
    records.append(record)
rankrows = [
    {"label": r["label"], "total": r["total_ms"]["mean"], "cv": r["yolo_ms"]["mean"]}
    for r in records
]
paired = []
for n in range(5):
    subset = {t["condition"]: t for t in trials if t["round"] == n}
    for condition, t in subset.items():
        for reference in ("control", "mps-only"):
            paired.append(
                {
                    "round": n,
                    "condition": condition,
                    "reference": reference,
                    "total_change_percent": 100
                    * (
                        t["completion"]["overall_completion_ms"]
                        / subset[reference]["completion"]["overall_completion_ms"]
                        - 1
                    ),
                    "yolo_change_percent": 100
                    * (
                        t["completion"]["model_completion_ms"]["yolo"]
                        / subset[reference]["completion"]["model_completion_ms"]["yolo"]
                        - 1
                    ),
                }
            )
summary = {
    "conditions": records,
    "ranking": ranking(rankrows),
    "tie_sensitivity": [ranking(rankrows, b) for b in (0, 0.01, 0.03, 0.05)],
    "trials": trials,
    "paired_round_changes": paired,
    "scope": "Native595/actualCUDA131; noGreen; exactly5independentbursts/case. Pooledrequestsdescriptive,notsamplesindependent. No profile timings mixed. GPUeventspan nestedinsidehostpipeline,notpureSMactive.",
}
(root / "analysis/summary.json").write_text(json.dumps(summary, indent=2))
(root / "verification/protocol-audit.json").write_text(
    json.dumps(
        {
            "state": "PASS",
            "runs": audits,
            "requests": sum(sum(r["counts"].values()) for r in audits),
        },
        indent=2,
    )
)
flat = []
for t in trials:
    row = {
        "trial": t["trial"],
        "round": t["round"],
        "condition": t["condition"],
        "total_ms": t["completion"]["overall_completion_ms"],
        "qwen_completion_ms": t["completion"]["model_completion_ms"]["qwen"],
        "yolo_completion_ms": t["completion"]["model_completion_ms"]["yolo"],
        "dispatch_ms": t["dispatch_window_ms"],
    }
    for model, value in t["models"].items():
        for metric, stats in value["metrics"].items():
            for stat in ("mean", "p95"):
                row[f"{model}_{metric}_{stat}"] = stats[stat]
    flat.append(row)
with (root / "analysis/trials.csv").open("w") as f:
    writer = csv.DictWriter(f, fieldnames=list(flat[0]))
    writer.writeheader()
    writer.writerows(flat)
print(
    json.dumps(
        {
            "ranking": summary["ranking"],
            "means": [
                {
                    "label": r["label"],
                    "total_ms": r["total_ms"]["mean"],
                    "yolo_ms": r["yolo_ms"]["mean"],
                }
                for r in records
            ],
            "audited_requests": sum(sum(r["counts"].values()) for r in audits),
        },
        indent=2,
    )
)
