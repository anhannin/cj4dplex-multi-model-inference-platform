#!/usr/bin/env python3
"""Offline protocol/fidelity checks; retain raw result files unchanged."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'benchmark'))
from aggregate_latency import stats


def audit(root):
    manifests = sorted(root.glob('*/manifest.json'))
    control = json.loads((root / 'control-screen/manifest.json').read_text())
    references = {}
    for line in (root / 'control-screen/requests.jsonl').open():
        row = json.loads(line)
        if row['model'] == 'qwen' and not row['warmup']:
            references[row['input_hash']] = row['response']['text']
    results = []
    for path in manifests:
        manifest = json.loads(path.read_text())
        rows = [json.loads(line) for line in (path.parent / 'requests.jsonl').open()]
        seen, errors, exact, qcount = set(), [], 0, 0
        if manifest['state'] != 'PASS':
            errors.append('manifest not PASS')
        for key in ('prompts', 'max_new_tokens', 'timing_mode', 'images'):
            if manifest[key] != control[key] and not (key == 'images' and manifest['models'] == ['qwen']):
                errors.append('protocol mismatch: ' + key)
        for row in rows:
            rid = row['request_id']
            if rid in seen:
                errors.append('duplicate request_id')
            seen.add(rid)
            if row['status'] != 'ok' or row.get('response', {}).get('request_id') != rid:
                errors.append('failed or mismatched response')
            if row['model'] == 'qwen' and not row['warmup']:
                qcount += 1
                if row['response']['output_tokens'] != 128:
                    errors.append('generated token count not128')
                if row['input_hash'] not in references:
                    errors.append('unknown Qwen input hash')
                exact += row['response']['text'] == references.get(row['input_hash'])
        publications = {}
        for model in manifest['models']:
            rids = {row['request_id'] for row in rows if row['model'] == model and not row['warmup']}
            log = root / (path.parent.name + '-' + model + '.log')
            if not log.exists():
                continue
            events = []
            for line in log.open():
                at = line.find('{"event"')
                if at < 0:
                    continue
                try:
                    event = json.loads(line[at:])
                except ValueError:
                    continue
                if event.get('event') == 'publication_finished' and event.get('request_id') in rids:
                    events.append(event)
            publications[model] = {'matched': len(events), 'measured': len(rids), 'acknowledged_false': sum(e.get('acknowledged') is not True for e in events), 'ack_wait_ms': stats([e['ack_wait_ms'] for e in events]), 'publisher_create_ms': stats([e['publisher_create_ms'] for e in events])}
        results.append({'run': path.parent.name, 'pass': not errors, 'errors': sorted(set(errors)), 'requests_including_warmup': len(rows), 'qwen_exact_text_vs_initial_control': exact, 'qwen_measured': qcount, 'publications': publications})
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    results = audit(args.root)
    args.output.write_text(json.dumps(results, indent=2))
    for result in results:
        print(result['run'], 'PASS' if result['pass'] else result['errors'])
