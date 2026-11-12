#!/usr/bin/env python3
"""Local serialized experiment owner; restores original deployments even on failure."""
import argparse
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import time
import urllib.request

REMOTE='avees@192.168.24.204'
ROOT=os.environ.get('CJ_SM_SWEEP_ROOT','/home/avees/cj-sm-sweep/20261109-v1')
LOCAL=Path('results/sm-sweep')/Path(ROOT).name
IMAGES={'qwen':'cj-qwen-ros:9b-timing-v1','yolo':'cj-yolo-ros:26l-timing-v1'}


def alert(message):
    url=os.environ.get('SLACK_WEBHOOK_DATASPLIT_URL') or os.environ.get('SLACK_WEBHOOK_URL')
    if url:
        try:
            req=urllib.request.Request(url,json.dumps({'text':message}).encode(),{'Content-Type':'application/json'})
            urllib.request.urlopen(req,timeout=8).close()
        except Exception:
            pass


def remote(cmd,timeout=120):
    return subprocess.run(['ssh','-o','ConnectTimeout=10',REMOTE,cmd],text=True,check=True,capture_output=True,timeout=timeout).stdout


def restore(backups):
    for model,original in backups.items():
        patch=json.dumps([{'op':'replace','path':'/spec/template','value':original['spec']['template']},{'op':'replace','path':'/spec/replicas','value':original['spec']['replicas']}])
        remote('kubectl -n cj-inference patch deployment '+model+' --type=json -p '+shlex.quote(patch))
    for model in backups:
        print(remote('kubectl -n cj-inference rollout status deployment/'+model+' --timeout=600s',timeout=620),flush=True)
    checks={}
    for model,original in backups.items():
        live=json.loads(remote('kubectl -n cj-inference get deployment '+model+' -o json'))
        assert live['spec']['template']==original['spec']['template']
        assert live['spec']['replicas']==original['spec']['replicas']
        checks[model]={'template_equal':True,'replicas':live['spec']['replicas']}
    remote('printf %s '+shlex.quote(json.dumps(checks,indent=2))+' > '+ROOT+'/verification/restored.json')
    # Actual native ROS requests after restore, not just ready-file status.
    command='source ~/.config/cj-ros2/spark-jazzy.bash; python3 ~/cj-ros2/benchmark/bench_ros2.py --models both --output '+ROOT+'/verification/health-'+str(time.time_ns())+' --samples 1 --warmup 1 --max-new-tokens 8 > '+ROOT+'/verification/health.log 2>&1'
    remote('bash -lc '+shlex.quote(command),timeout=300)


def docker_model(model,label,args,profile=False,timeout=7200):
    name='cj-sm-sweep-'+label
    image=IMAGES[model]
    options=['docker','run','--rm','--name',name,'--gpus','all','--ipc=host','--network','none','--user','1000:1000','--cap-drop','ALL','-e','HOME=/tmp','-e','HF_HUB_OFFLINE=1','-e','YOLO_CONFIG_DIR=/tmp/yolo','-e','PYTHONPATH=/experiment/src','-e','TRITON_CACHE_DIR=/experiment/cache/triton','-v',ROOT+':/experiment','-v','/home/avees/.cache/huggingface/hub:/cache:ro','-v','/home/avees/cj-containers/assets:/assets:ro']
    script=['python','/experiment/src/run_model.py','--model',model,'--output','/experiment/'+('validation/' if profile else 'results/')+label]+args
    if profile:
        options+=['--entrypoint','/usr/local/cuda/bin/nsys',image,'profile','--trace=cuda,nvtx','--sample=none','--cpuctxsw=none','--capture-range=cudaProfilerApi','--capture-range-end=stop','--output','/experiment/validation/'+label]
    else:
        options+=['--entrypoint','python',image]
        script=script[1:]
    command=shlex.join(options+script)+' > '+ROOT+'/logs/'+label+'.log 2>&1'
    print(json.dumps({'event':'launch','label':label,'time':time.time()}),flush=True)
    try:
        remote(command,timeout=timeout)
    finally:
        remote('docker rm -f '+name+' >/dev/null 2>&1 || true')
    if profile:
        export=['docker','run','--rm','--runtime','runc','--network','none','--user','1000:1000','-e','HOME=/tmp','-v',ROOT+':/experiment','--entrypoint','/usr/local/cuda/bin/nsys',image,'export','--type','sqlite','--output','/experiment/validation/'+label+'.sqlite','/experiment/validation/'+label+'.nsys-rep']
        remote(shlex.join(export)+' > '+ROOT+'/logs/'+label+'-export.log 2>&1',timeout=600)
        remote('python3 '+ROOT+'/src/verify_trace.py '+ROOT+'/validation/'+label+'.sqlite --model '+model+' --output '+ROOT+'/verification/'+label+'-coverage.json',timeout=120)
    print(json.dumps({'event':'complete','label':label,'time':time.time()}),flush=True)
    alert('CJ 실제 모델 SM sweep: '+label+' 완료.')


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--pilot-only',action='store_true')
    a=p.parse_args()
    LOCAL.mkdir(parents=True,exist_ok=True)
    signal.signal(signal.SIGTERM,lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    remote('mkdir -p '+ROOT+'/logs '+ROOT+'/cache/triton')
    backups={m:json.loads(remote('cat '+ROOT+'/backup/'+m+'.json')) for m in IMAGES}
    for model,original in backups.items():
        current=json.loads(remote('kubectl -n cj-inference get deployment '+model+' -o json'))
        assert current['spec']['template']==original['spec']['template'],'Concurrent deployment modification'
        assert current['spec']['replicas']==original['spec']['replicas']
    assert not remote("pgrep -u 1000 -af '^nvidia-cuda-mps-(control|server)' || true").strip(),'MPS running'
    started=time.time()
    status={'state':'RUNNING','start':started,'root':ROOT}
    try:
        remote('kubectl -n cj-inference scale deployment qwen yolo --replicas=0')
        deadline=time.monotonic()+330
        while True:
            pods=json.loads(remote('kubectl -n cj-inference get pods -o json'))['items']
            if not any(p['metadata'].get('labels',{}).get('app') in IMAGES for p in pods):
                break
            if time.monotonic()>deadline:
                raise TimeoutError('Original model Pods did not terminate')
            time.sleep(2)
        remote('nvidia-smi --query-compute-apps=pid,process_name --format=csv > '+ROOT+'/verification/quiescent-gpu.txt')
        for model in ('yolo','qwen'):
            docker_model(model,'pilot-'+model,['--sms','8','48','--rounds','1','--samples-per-round','1','--warmup','1','--reference-samples','1','--trace-probe'],profile=True,timeout=1000)
        if not a.pilot_only:
            docker_model('yolo','main-yolo',['--samples-per-round','50','--rounds','2','--warmup','10','--reference-samples','50'],timeout=900)
            docker_model('qwen','main-qwen',['--samples-per-round','15','--rounds','2','--warmup','3','--reference-samples','5'],timeout=7200)
        status['state']='PASS'
    except BaseException as error:
        status.update(state='FAIL',error=repr(error))
        alert('CJ SM sweep 실패/중단: '+type(error).__name__+' — 원본 배포 복구를 진행합니다.')
        raise
    finally:
        try:
            restore(backups)
            status['restoration']='PASS'
        except BaseException as error:
            status['restoration']=repr(error)
            alert('CJ SM sweep 원본 복구 실패. Spark cj-inference 확인 필요: '+type(error).__name__)
            raise
        finally:
            status['end']=time.time()
            (LOCAL/'controller-status.json').write_text(json.dumps(status,indent=2))
            remote('printf %s '+shlex.quote(json.dumps(status,indent=2))+' > '+ROOT+'/verification/controller-status.json')
        alert('CJ 실제 모델 SM sweep 종료: '+status['state']+'. 원본 두 서비스 복구·E2E 확인 완료.')


if __name__=='__main__':
    main()
