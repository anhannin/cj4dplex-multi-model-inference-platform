"""Host-side bounded tests of independent Qwen and YOLO GPU containers."""
import argparse
import hashlib
import json
import os
import signal
from pathlib import Path
import subprocess
import time

import psutil
from metrics import summarize, overlapping
from worker import write


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds', type=int, default=60)
    parser.add_argument('--root', type=Path, default=Path.home() / 'cj-containers')
    args = parser.parse_args()
    root = args.root.resolve()
    prefix = 'cj-verified-' + time.strftime('%H%M%S', time.gmtime())
    run = root / 'results' / time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    run.mkdir()
    write(root / 'results/latest.json', {'path': str(run)})
    gpu_jobs = subprocess.check_output(['nvidia-smi', '--query-compute-apps=pid', '--format=csv,noheader'], text=True)
    if gpu_jobs.strip():
        raise RuntimeError('Foreign compute job present; test not started')
    images = {'llm': 'cj-qwen:9b-cu130', 'cv': 'cj-yolo:26l-cu130'}
    write(run / 'images.json', {kind: json.loads(subprocess.check_output(['docker', 'image', 'inspect', image], text=True))[0]
                              for kind, image in images.items()})
    write(run / 'sources.json', {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (root / 'scripts').glob('*.py')})
    workers = {}
    handles = []
    phases = []

    def launch(kind, group):
        directory = run / group
        directory.mkdir(exist_ok=True)
        home = directory / ('home-' + kind)
        home.mkdir(exist_ok=True)
        name = prefix + '-' + kind
        command = ['docker', 'run', '--rm', '--name', name, '--gpus', 'all', '--network', 'none',
                   '--shm-size', '2g', '--user', f'{os.getuid()}:{os.getgid()}',
                   '-e', 'HOME=/runtime', '-e', 'TRITON_CACHE_DIR=/runtime/triton',
                   '-e', 'HF_HUB_OFFLINE=1', '-e', 'YOLO_CONFIG_DIR=/runtime/ultralytics',
                   '-v', str(directory) + ':/output', '-v', str(home) + ':/runtime',
                   '-v', str(root / 'assets') + ':/assets:ro',
                   '-v', str(Path.home() / '.cache/huggingface/hub') + ':/cache:ro',
                   images[kind], '--out', '/output', '--assets', '/assets', '--profile']
        if kind == 'llm':
            command.append('--require-acceleration')
        handle = (directory / (kind + '.log')).open('w')
        handles.append(handle)
        process = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT)
        workers[kind] = (process, directory, name)

    def wait_for(path, timeout=480):
        deadline = time.time() + timeout
        while not path.exists():
            for process, _, _ in workers.values():
                if process.poll() is not None:
                    raise RuntimeError('Container worker exited: ' + str(process.returncode))
            if time.time() > deadline:
                raise TimeoutError(str(path))
            time.sleep(.2)

    def ready():
        for kind, (_, directory, _) in workers.items():
            wait_for(directory / (kind + '-ready.json'))

    def stop():
        for process, _, name in workers.values():
            if process.poll() is None:
                subprocess.run(['docker', 'stop', '--time', '10', name], capture_output=True, timeout=30)
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        workers.clear()

    def phase(name, active):
        start = time.time() + 1
        end = start + args.seconds
        for kind, (_, directory, _) in workers.items():
            write(directory / (kind + '-command.json'),
                  {'id': name, 'start': start, 'end': end, 'active': kind in active})
        resources = []
        while time.time() < end:
            if any(p.poll() is not None for p, _, _ in workers.values()):
                raise RuntimeError('Worker exited during measurement')
            gpu = subprocess.check_output(['nvidia-smi', '--query-gpu=utilization.gpu,power.draw,temperature.gpu',
                                           '--format=csv,noheader,nounits'], text=True, timeout=5).strip()
            resources.append({'time': time.time(), 'cpu_percent': psutil.cpu_percent(),
                              'available_memory_bytes': psutil.virtual_memory().available,
                              'gpu_util_power_temp_csv': gpu})
            time.sleep(1)
        summary = {'name': name, 'start': start, 'end': end, 'active': active, 'models': {}}
        for kind, (_, directory, _) in workers.items():
            wait_for(directory / (kind + '-' + name + '-done.json'), timeout=180)
            rows = [json.loads(line) for line in (directory / (kind + '-' + name + '.jsonl')).read_text().splitlines()]
            good = [row for row in overlapping(rows, start, end) if row['ok']]
            summary['models'][kind] = {
                'attempted_including_boundary': len(rows),
                'errors_including_boundary': sum(not r['ok'] for r in rows),
                'fully_contained_requests': len(good),
                'latency': summarize([r['latency_ms'] for r in good]),
                'requests_per_second_contained': len(good) / args.seconds,
                'ttft': summarize([r['ttft_ms'] for r in good if r.get('ttft_ms') is not None]),
                'tpot': summarize([r['tpot_ms'] for r in good if r.get('tpot_ms') is not None])}
        write(run / (name + '-resources.json'), resources)
        phases.append(summary)
        write(run / 'summary.json', {'state': 'running', 'phases': phases})
        print(json.dumps(summary), flush=True)

    def terminate(signum, frame):
        raise TimeoutError('Experiment terminated by signal ' + str(signum))

    signal.signal(signal.SIGTERM, terminate)
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
