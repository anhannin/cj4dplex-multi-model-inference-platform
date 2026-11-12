#!/usr/bin/env python3
"""Summarize raw benchmark aggregates without mixing nested spans or protocols."""
import argparse
import csv
import json
from pathlib import Path


def rows(root):
    for path in sorted(root.glob('*/summary.json')):
        if not (path.parent / 'manifest.json').exists():
            continue
        manifest = json.loads((path.parent / 'manifest.json').read_text())
        summary = json.loads(path.read_text())
        if manifest['state'] != 'PASS':
            continue
        for model in ('qwen', 'yolo'):
            if model not in summary:
                continue
            s = summary[model]
            row = {'run': path.parent.name, 'model': model, 'cv_rate_ceiling': manifest.get('cv_launch_rate_ceiling', 0), 'n': s['successful'], 'failed': s['failed'], 'throughput': s['successful_requests_per_second']}
            for key in ('request_e2e_ms', 'queue_wait_ms', 'generate_wall_ms', 'server_ttft_ms', 'tpot_ms', 'yolo_inference_ms', 'processing_ms'):
                value = s.get(key, {})
                for stat in ('mean', 'p95'):
                    row[key + '_' + stat] = value.get(stat)
            yield row


def main():
    p = argparse.ArgumentParser()
    p.add_argument('root', type=Path)
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    values = list(rows(a.root))
    if a.output and values:
        with a.output.open('w') as f:
            writer = csv.DictWriter(f, fieldnames=list(values[0]))
            writer.writeheader()
            writer.writerows(values)
    for r in values:
        print(f"{r['run']:30s} {r['model']:5s} n={r['n']:5} fail={r['failed']} E2E={r['request_e2e_ms_mean']:.2f}/{r['request_e2e_ms_p95']:.2f}ms rate={r['throughput']:.2f}")


if __name__ == '__main__':
    main()
