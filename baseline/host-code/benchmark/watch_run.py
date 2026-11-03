"""Local fail-open Slack alerts for a long remote benchmark. No credentials logged."""

import json
import os
import subprocess
import time
import urllib.request


def notify(text):
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        return
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps({"text": text}).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10).close()
    except Exception:
        pass


unreachable = False
started = time.monotonic()
while True:
    try:
        r = subprocess.run(
            [
                "ssh",
                "-o",
                "ConnectTimeout=10",
                "avees@192.168.24.204",
                "cat ~/cj-latency/evidence/five-phases-status.txt 2>/dev/null || true",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if r.returncode:
            if not unreachable:
                notify("Spark 성능 측정 중 SSH 연결 실패. 서버 상태를 확인 중입니다.")
            unreachable = True
        else:
            unreachable = False
            if r.stdout.startswith(("PASS", "FAIL")):
                notify(
                    "Spark 5조건 성능 측정 "
                    + (
                        "완료."
                        if r.stdout.startswith("PASS")
                        else "실패. 원인 확인 필요."
                    )
                    + " 결과: ~/cj-latency/phases"
                )
                break
    except Exception:
        if not unreachable:
            notify("Spark 성능 측정 감시 연결 타임아웃. 서버 상태를 확인 중입니다.")
        unreachable = True
    if time.monotonic() - started > 7200:
        notify(
            "Spark 성능 측정이 2시간을 초과했습니다. 중단하지 않고 상태 점검이 필요합니다."
        )
        break
    time.sleep(30)
