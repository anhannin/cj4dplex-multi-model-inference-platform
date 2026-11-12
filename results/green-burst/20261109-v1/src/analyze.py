#!/usr/bin/env python3
"""Fixed simultaneous-batch completion, request queue/pipeline/device submetrics, ranking."""

import argparse
import csv
import json
from pathlib import Path
from metrics import burst_completion, select_candidate
from stage_metrics import distribution


def load_trial(path):
    manifest = json.loads((path / "manifest.json").read_text())
    assert manifest["state"] == "PASS" and manifest["expected"] == {
        "qwen": 10,
        "yolo": 300,
    }
    rows = [
        json.loads(s) for s in (path / "final-requests.jsonl").read_text().splitlines()
    ]
    completion = burst_completion(
        rows, manifest["batch_t0_perf_ns"], manifest["expected"]
    )
    result = {
        "trial": path.name,
        "completion": completion,
        "dispatch_window_ms": json.loads((path / "summary.json").read_text())[
            "dispatch_window_ms"
        ],
        "models": {},
    }
    for model in ("qwen", "yolo"):
        selected = [r for r in rows if r["model"] == model]
        keys = ["request_e2e_ms", "batch_origin_e2e_ms"]
        metrics = {k: distribution([r[k] for r in selected]) for k in keys}
        for key in (
            "app_queue_ms",
            "model_pipeline_ms",
            "server_nonpipeline_ms",
            "transport_client_residual_ms",
            "gpu_forward_span_ms",
        ):
            metrics[key] = distribution([r["components"][key] for r in selected])
        if model == "qwen":
            for key in (
                "gpu_prefill_span_ms",
                "gpu_decode_ms_per_token",
                "gpu_decode_total_span_ms",
                "generate_ttft_ms",
                "tpot_ms",
            ):
                metrics[key] = distribution(
                    [r["response"]["timings_ms"][key] for r in selected]
                )
        result["models"][model] = {"n": len(selected), "metrics": metrics}
    last_cv = max(
        r["response"]["model_end_perf_ns"] for r in rows if r["model"] == "yolo"
    )
    qrows = [r for r in rows if r["model"] == "qwen"]
    result["tail"] = {
        "cv_last_model_end_from_t0_ms": (last_cv - manifest["batch_t0_perf_ns"]) / 1e6,
        "qwen_jobs_start_after_cv_inference_done": sum(
            r["response"]["model_start_perf_ns"] >= last_cv for r in qrows
        ),
        "note": "host model-pipeline windows, not proof of GPU kernel overlap",
    }
    result["negative_residuals"] = sum(
        r["components"]["transport_client_residual_ms"] < 0
        or r["components"]["server_nonpipeline_ms"] < 0
        for r in rows
    )
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    a = p.parse_args()
    status = json.loads((a.root / "verification/controller-status.json").read_text())
    assert status["state"] == "PASS" and status["restoration"] == "PASS"
    trials = [
        load_trial(path)
        for path in sorted((a.root / "results").iterdir())
        if path.is_dir()
    ]
    assert len(trials) == 21
    groups = {}
    for trial in trials:
        label = trial["trial"].rsplit("-r", 1)[0]
        groups.setdefault(label, []).append(trial)
    assert all(len(v) == 3 for v in groups.values())
    records = []
    for label, items in groups.items():
        records.append(
            {
                "label": label,
                "repetitions": len(items),
                "total_ms": distribution(
                    [t["completion"]["overall_completion_ms"] for t in items]
                ),
                "qwen_ms": distribution(
                    [t["completion"]["model_completion_ms"]["qwen"] for t in items]
                ),
                "yolo_ms": distribution(
                    [t["completion"]["model_completion_ms"]["yolo"] for t in items]
                ),
                "dispatch_ms": distribution([t["dispatch_window_ms"] for t in items]),
                "qwen_tail_jobs": distribution(
                    [
                        t["tail"]["qwen_jobs_start_after_cv_inference_done"]
                        for t in items
                    ]
                ),
            }
        )
    # Pool before/after controls explicitly, retaining their separate records and drift.
    defaults = groups["default-pre"] + groups["default-post"]
    pooled = {
        "label": "default",
        "repetitions": 6,
        "total_ms": distribution(
            [t["completion"]["overall_completion_ms"] for t in defaults]
        ),
        "qwen_ms": distribution(
            [t["completion"]["model_completion_ms"]["qwen"] for t in defaults]
        ),
        "yolo_ms": distribution(
            [t["completion"]["model_completion_ms"]["yolo"] for t in defaults]
        ),
        "dispatch_ms": distribution([t["dispatch_window_ms"] for t in defaults]),
        "qwen_tail_jobs": distribution(
            [t["tail"]["qwen_jobs_start_after_cv_inference_done"] for t in defaults]
        ),
    }
    comparison = [pooled] + [r for r in records if not r["label"].startswith("default")]
    ranking = select_candidate(
        [
            {
                "label": r["label"],
                "total_mean_ms": r["total_ms"]["mean"],
                "yolo_mean_ms": r["yolo_ms"]["mean"],
            }
            for r in comparison
        ]
    )
    out = {
        "groups": records,
        "comparison": comparison,
        "ranking": ranking,
        "trials": trials,
        "scope": "all trials simultaneous finite10Q/300Y; no solo baseline; GPU forward span nested inside pipeline wall",
    }
    (a.root / "analysis/summary.json").write_text(json.dumps(out, indent=2))
    rows = []
    for trial in trials:
        row = {
            "trial": trial["trial"],
            "total_ms": trial["completion"]["overall_completion_ms"],
            "qwen_completion_ms": trial["completion"]["model_completion_ms"]["qwen"],
            "yolo_completion_ms": trial["completion"]["model_completion_ms"]["yolo"],
            "dispatch_ms": trial["dispatch_window_ms"],
            "qwen_tail_jobs": trial["tail"]["qwen_jobs_start_after_cv_inference_done"],
            "negative_residuals": trial["negative_residuals"],
        }
        for model, r in trial["models"].items():
            for metric, values in r["metrics"].items():
                for stat in ("mean", "p95"):
                    row[f"{model}_{metric}_{stat}"] = values[stat]
        rows.append(row)
    with (a.root / "analysis/trials.csv").open("w") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(json.dumps({"ranking": ranking, "comparison": comparison}, indent=2))


if __name__ == "__main__":
    main()
