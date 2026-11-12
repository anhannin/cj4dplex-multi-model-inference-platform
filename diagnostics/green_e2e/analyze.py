#!/usr/bin/env python3
"""Paired solo-active/concurrent analysis; no inference of GPU overlap from E2E alone."""

import argparse
import csv
import json
from pathlib import Path

from generate import classify_change


def analyze_case(root, label):
    directory = root / "results"
    both = json.loads((directory / (label + "-both") / "summary.json").read_text())
    output = {"label": label, "models": {}}
    for model in ("qwen", "yolo"):
        solo_dir = directory / (label + "-" + model + "-solo")
        solo = json.loads((solo_dir / "summary.json").read_text())[model]
        concurrent = both[model]
        assert solo["failed"] == 0 and concurrent["failed"] == 0
        primary = "generate_wall_ms" if model == "qwen" else "yolo_inference_ms"
        result = {
            "solo_n": solo["successful"],
            "concurrent_n": concurrent["successful"],
            "solo_rate": solo["successful_requests_per_second"],
            "concurrent_rate": concurrent["successful_requests_per_second"],
            "metrics": {},
        }
        for metric in (
            "request_e2e_ms",
            primary,
            "processing_ms",
            "queue_wait_ms",
            "server_ttft_ms",
            "tpot_ms",
        ):
            if metric not in solo:
                continue
            entry = {
                stat: {
                    "solo": solo[metric][stat],
                    "concurrent": concurrent[metric][stat],
                }
                for stat in ("mean", "p95")
            }
            entry["mean"].update(
                classify_change(solo[metric]["mean"], concurrent[metric]["mean"])
            )
            if solo[metric]["p95"] > 0:
                entry["p95"]["change_percent"] = 100 * (
                    concurrent[metric]["p95"] / solo[metric]["p95"] - 1
                )
            result["metrics"][metric] = entry
        e2e = result["metrics"]["request_e2e_ms"]["mean"]
        inference = result["metrics"][primary]["mean"]
        result["possible_transport_masking"] = (
            e2e["ratio"] <= 1.05 and inference["ratio"] > 1.05
        )
        output["models"][model] = result
    output["both_means_near_equal"] = all(
        r["metrics"]["request_e2e_ms"]["mean"]["classification"] == "near_equal"
        for r in output["models"].values()
    )
    output["both_means_not_worse_5pct"] = all(
        r["metrics"]["request_e2e_ms"]["mean"]["ratio"] <= 1.05
        for r in output["models"].values()
    )
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    state = json.loads((args.root / "verification/controller-status.json").read_text())
    if state["state"] != "PASS":
        raise RuntimeError("Incomplete experiment")
    cases = [analyze_case(args.root, label) for label in state["completed"]]
    out = args.root / "analysis"
    out.mkdir(exist_ok=True)
    (out / "comparison.json").write_text(json.dumps(cases, indent=2))
    rows = []
    for case in cases:
        for model, record in case["models"].items():
            row = {
                "case": case["label"],
                "model": model,
                "solo_n": record["solo_n"],
                "both_n": record["concurrent_n"],
                "solo_rate": record["solo_rate"],
                "both_rate": record["concurrent_rate"],
                "possible_transport_masking": record["possible_transport_masking"],
            }
            for metric, result in record["metrics"].items():
                for stat, values in result.items():
                    for key in (
                        "solo",
                        "concurrent",
                        "ratio",
                        "change_percent",
                        "classification",
                    ):
                        if key in values:
                            row[f"{metric}_{stat}_{key}"] = values[key]
            rows.append(row)
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with (out / "comparison.csv").open("w") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    for case in cases:
        print(
            case["label"],
            {
                m: {
                    "solo_ms": r["metrics"]["request_e2e_ms"]["mean"]["solo"],
                    "both_ms": r["metrics"]["request_e2e_ms"]["mean"]["concurrent"],
                    "change_pct": r["metrics"]["request_e2e_ms"]["mean"][
                        "change_percent"
                    ],
                }
                for m, r in case["models"].items()
            },
        )


if __name__ == "__main__":
    main()
