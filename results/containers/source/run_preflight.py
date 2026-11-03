"""Bounded standalone/co-resident/concurrent model exploration inside container."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

from metrics import summarize, overlapping
from worker import write


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds', type=int, default=60)
    args = parser.parse_args()
    run = Path('/work/results') / time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    run.mkdir()
    write(Path('/work/results/latest.json'), {'path': str(run)})
    metadata = {'scope': 'exploration; model-call latency, NOT API E2E',
                'seconds': args.seconds, 'python': sys.version, 'machine': platform.machine(),
                'packages': {d.metadata['Name']: d.version for d in importlib.metadata.distributions()},
                'code_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in Path('/work/scripts').glob('*.py')}}
    write(run / 'environment.json', metadata)
    handles = []
    workers = {}
    phases = []

    def launch(kind, group):
        directory = run / group
        directory.mkdir(exist_ok=True)
        log = (directory / (kind + '.log')).open('w')
        handles.append(log)
        process = subprocess.Popen([sys.executable, '/work/scripts/worker.py', kind,
                                    '--out', str(directory)], stdout=log, stderr=subprocess.STDOUT)
        workers[kind] = (process, directory)

    def wait_for(path, timeout=360):
        deadline = time.time() + timeout
        while not path.exists():
            for process, _ in workers.values():
                if process.poll() is not None:
                    raise RuntimeError('Worker exited: ' + str(process.returncode))
            if time.time() > deadline:
                raise TimeoutError(str(path))
            time.sleep(.2)

    def ready():
        for kind, (_, directory) in workers.items():
            wait_for(directory / (kind + '-ready.json'))

    def stop():
        for process, _ in workers.values():
            if process.poll() is None:
                process.terminate()
        for process, _ in workers.values():
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        workers.clear()

    def phase(name, active):
        start = time.time() + 1
        end = start + args.seconds
        command = {'id': name, 'start': start, 'end': end}
        for kind, (_, directory) in workers.items():
            write(directory / (kind + '-command.json'), dict(command, active=kind in active))
        samples = []
        import psutil
        while time.time() < end:
            for process, _ in workers.values():
                if process.poll() is not None:
                    raise RuntimeError('Worker failed during phase')
            sample = {'time': time.time(), 'cpu_percent': psutil.cpu_percent(),
                      'available_memory_bytes': psutil.virtual_memory().available,
                      'workers': {kind: {'rss': psutil.Process(p.pid).memory_info().rss}
                                  for kind, (p, _) in workers.items()}}
            gpu = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu,power.draw,temperature.gpu',
                                  '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=5)
            sample['gpu_util_power_temp_csv'] = gpu.stdout.strip()
            samples.append(sample)
            time.sleep(1)
        summary = {'name': name, 'start': start, 'end': end, 'active': active, 'models': {}}
        for kind, (_, directory) in workers.items():
            wait_for(directory / (kind + '-' + name + '-done.json'), timeout=180)
            path = directory / (kind + '-' + name + '.jsonl')
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            inside = overlapping(rows, start, end)
            good = [r for r in inside if r['ok']]
            summary['models'][kind] = {
                'attempted_including_boundary': len(rows),
                'errors_including_boundary': sum(not r['ok'] for r in rows),
                'fully_contained_requests': len(good),
                'latency': summarize([r['latency_ms'] for r in good]),
                'requests_per_second_contained': len(good) / args.seconds,
                'ttft': summarize([r['ttft_ms'] for r in good if r.get('ttft_ms') is not None]),
                'tpot': summarize([r['tpot_ms'] for r in good if r.get('tpot_ms') is not None])}
        write(run / (name + '-resources.json'), samples)
        phases.append(summary)
        write(run / 'summary.json', {'state': 'running', 'phases': phases})
        print(json.dumps(summary), flush=True)

    try:
        launch('llm', 'llm-only')
        ready()
        phase('llm-alone', ['llm'])
        stop()
        launch('cv', 'cv-only')
        ready()
        phase('cv-alone', ['cv'])
        stop()
        launch('llm', 'pair')
        launch('cv', 'pair')
        ready()
        phase('llm-cv-idle', ['llm'])
        phase('cv-llm-idle', ['cv'])
        phase('concurrent', ['llm', 'cv'])
        write(run / 'summary.json', {'state': 'complete', 'phases': phases})
    except Exception as exc:
        write(run / 'summary.json', {'state': 'failed', 'error': str(exc), 'phases': phases})
        raise
    finally:
        stop()
        for handle in handles:
            handle.close()


if __name__ == '__main__':
    main()
