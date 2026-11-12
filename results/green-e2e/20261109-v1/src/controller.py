#!/usr/bin/env python3
"""Local SSH owner/Slack notifier; remote runner owns restoration and raw files."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import urllib.request


def alert(text):
    url=os.environ.get('SLACK_WEBHOOK_DATASPLIT_URL') or os.environ.get('SLACK_WEBHOOK_URL')
    if url:
        try:
            request=urllib.request.Request(url,json.dumps({'text':text}).encode(),{'Content-Type':'application/json'})
            urllib.request.urlopen(request,timeout=8).close()
        except Exception:pass


def main():
    root=os.environ.get('GREEN_E2E_ROOT','/home/avees/cj-green-e2e/20261109-v1')
    local=Path('results/green-e2e')/Path(root).name
    local.mkdir(parents=True,exist_ok=True)
    script='source ~/.config/cj-ros2/spark-jazzy.bash; export ROS_DOMAIN_ID=73; export GREEN_E2E_ROOT='+shlex.quote(root)+'; python3 -u '+shlex.quote(root+'/src/runner.py')
    cmd=['ssh','-o','ConnectTimeout=10','avees@192.168.24.204','bash -lc '+shlex.quote(script)+' > '+shlex.quote(root+'/logs/controller.log')+' 2>&1']
    alert('CJ Green Context E2E 조합 실험 시작: 원본 두 Pod를 실험 설정으로 임시 전환, 종료 후 원상복구합니다.')
    p=subprocess.run(cmd)
    result=subprocess.run(['ssh','-o','ConnectTimeout=10','avees@192.168.24.204','cat '+root+'/verification/controller-status.json'],text=True,capture_output=True)
    (local/'controller-status.json').write_text(result.stdout or json.dumps({'ssh_exit':p.returncode,'status_read_error':result.stderr}))
    if p.returncode:
        alert('CJ Green E2E 실험 오류/중단. 원격 controller-status의 원상복구 결과 확인 필요: '+root)
        raise SystemExit(p.returncode)
    alert('CJ Green E2E 조합 실험 완료. 원본 두 서비스 복구·실제 요청 검사 완료. 결과: '+root)


if __name__=='__main__':main()
