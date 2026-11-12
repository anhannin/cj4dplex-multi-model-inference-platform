"""Offline pooling of equivalent-protocol windows, never mix paced/unpaced loads."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'benchmark'))
from aggregate_latency import aggregate


def pool_runs(directories):
    reference, rows, seen, windows = None, [], set(), {}
    for directory in directories:
        manifest = json.loads((directory / 'manifest.json').read_text())
        if manifest['state'] != 'PASS':
            raise ValueError('Cannot pool a failed run')
        protocol = {key: manifest[key] for key in ('models', 'max_new_tokens', 'timing_mode', 'prompts', 'images', 'concurrency_per_model')}
        protocol['cv_launch_rate_ceiling'] = manifest.get('cv_launch_rate_ceiling', 0)
        if reference is not None and protocol != reference:
            raise ValueError('Different protocols must not be pooled')
        reference = protocol
        with (directory / 'requests.jsonl').open() as stream:
            for line in stream:
                row = json.loads(line)
                if row['request_id'] in seen:
                    raise ValueError('Duplicate request UUID in pooling inputs')
                seen.add(row['request_id'])
                rows.append(row)
        for model, seconds in manifest['measurement_seconds'].items():
            windows[model] = windows.get(model, 0) + seconds
    return {'runs': [str(d) for d in directories], 'protocol': reference, 'summary': aggregate(rows, windows)}


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('directories', type=Path, nargs='+')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.output.write_text(json.dumps(pool_runs(a.directories), indent=2))
