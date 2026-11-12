#!/usr/bin/env python3
"""Serialized Kubernetes experiment runner, restoring backed-up templates in finally."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
from overlays import candidate_template, template_patch
from live_logs import LiveLogs

ROOT = Path.home() / 'cj-optimization/20261104-v1'


def run(args, **kw):
    return subprocess.run(args, check=True, text=True, **kw)


def alert(message):
    url = os.environ.get('SLACK_WEBHOOK_DATASPLIT_URL') or os.environ.get('SLACK_WEBHOOK_URL')
    if url:
        try:
            req = urllib.request.Request(url, json.dumps({'text': message}).encode(), {'Content-Type': 'application/json'})
            urllib.request.urlopen(req, timeout=8).close()
        except Exception:
            pass


def apply(candidate):
    for model in ('qwen', 'yolo'):
        original = json.loads((ROOT / 'backup' / (model + '.json')).read_text())['spec']['template']
        patch = ROOT / 'config' / (model + '-active.json')
        patch.write_text(json.dumps(template_patch(candidate_template(original, candidate, model, str(ROOT)))))
        run(['kubectl', '-n', 'cj-inference', 'patch', 'deployment', model, '--type=json', '--patch-file', str(patch)], stdout=subprocess.DEVNULL)
    for model in ('qwen', 'yolo'):
        run(['kubectl', '-n', 'cj-inference', 'rollout', 'status', 'deployment/' + model, '--timeout=600s'])


def measure(candidate, label, samples, warmup, cv_rate=0, models="both"):
    dest = ROOT / 'results' / label
    record = ROOT / 'results' / (label + '-deployment.json')
    record.write_text(run(['kubectl', '-n', 'cj-inference', 'get', 'deployment', 'qwen', 'yolo', '-o', 'json'], capture_output=True).stdout)
    (ROOT / 'results' / (label + '-pods.json')).write_text(run(['kubectl', '-n', 'cj-inference', 'get', 'pods', '-o', 'json'], capture_output=True).stdout)
    source_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (ROOT / 'src').glob('*.py')}
    (ROOT / 'results' / (label + '-source-hashes.json')).write_text(json.dumps(source_hashes, indent=2))
    env = os.environ.copy()
    if 'dds' in candidate.split('-'):
        env['FASTRTPS_DEFAULT_PROFILES_FILE'] = str(ROOT / 'config/low-latency.xml')
    else:
        env.pop('FASTRTPS_DEFAULT_PROFILES_FILE', None)
    start = datetime.datetime.now(datetime.timezone.utc).isoformat()
    command = ['python3', str(Path.home() / 'cj-ros2/benchmark/bench_ros2.py'), '--models', models, '--output', str(dest), '--samples', str(samples), '--warmup', str(warmup), '--max-new-tokens', '128']
    if cv_rate:
        command[1] = str(ROOT / 'src/bench_paced.py')
        command += ['--yolo-max-rate', str(cv_rate)]
        env['PYTHONPATH'] = str(Path.home() / 'cj-ros2/benchmark') + os.pathsep + env.get('PYTHONPATH', '')
    followers = LiveLogs(ROOT / 'results', label, ['qwen', 'yolo'] if models == 'both' else [models], start)
    with (ROOT / 'results' / (label + '.log')).open('x') as f:
        followers.start()
        process = None
        try:
            process = subprocess.Popen(command, env=env, stdout=f, stderr=subprocess.STDOUT)
            time.sleep(8)
            if 'mps' in candidate.split('-'):
                mpsenv = {**env, 'CUDA_MPS_PIPE_DIRECTORY': str(ROOT / 'mps-pipe')}
                servers = run(['nvidia-cuda-mps-control'], input='get_server_list\n', env=mpsenv, capture_output=True).stdout
                membership = {'servers': servers, 'clients': {}}
                for pid in servers.split():
                    if pid.isdigit():
                        membership['clients'][pid] = run(['nvidia-cuda-mps-control'], input=f'get_client_list {pid}\n', env=mpsenv, capture_output=True).stdout
                (ROOT / 'results' / (label + '-mps-membership.json')).write_text(json.dumps(membership, indent=2))
                count = sum(len([p for p in v.split() if p.isdigit()]) for v in membership['clients'].values())
                if count < 2:
                    raise RuntimeError('MPS two-client attachment not proven; refuse mislabeled result')
            code = process.wait(timeout=1200)
            if code:
                raise RuntimeError(f'benchmark exited {code}: {label}')
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            # Publication ACK logs occur after client response; wait outside measured windows.
            time.sleep(2.2)
            followers.close()
    summary = json.loads((dest / 'summary.json').read_text())
    print(json.dumps({'candidate': candidate, 'label': label, 'summary': summary}), flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('candidates', nargs='+')
    p.add_argument('--samples', type=int, default=5)
    p.add_argument('--warmup', type=int, default=5)
    p.add_argument('--prefix', default='screen')
    p.add_argument('--cv-rate', type=float, default=0)
    a = p.parse_args()
    status = []
    try:
        for index, candidate in enumerate(a.candidates):
            label = f'{a.prefix}-{index:02d}-{candidate}'
            print(json.dumps({'event': 'candidate_start', 'candidate': candidate, 'time': time.time()}), flush=True)
            try:
                apply(candidate)
                measure(candidate, label, a.samples, a.warmup, a.cv_rate)
                status.append({'candidate': candidate, 'label': label, 'status': 'PASS'})
            except Exception as error:
                status.append({'candidate': candidate, 'label': label, 'status': 'FAIL', 'error': repr(error)})
                alert(f'CJ 최적화 실험 {candidate} 실패: {type(error).__name__}. 원본 템플릿 복구 후 다음 실험 진행.')
                print(json.dumps(status[-1]), flush=True)
                apply('control')
            (ROOT / 'results' / (a.prefix + '-status.json')).write_text(json.dumps(status, indent=2))
    finally:
        apply('control')
        alert('CJ 최적화 비교 실험 종료. 원본 두 Pod 복구 완료. 결과: ~/cj-optimization/20261104-v1/results')


if __name__ == '__main__':
    main()
