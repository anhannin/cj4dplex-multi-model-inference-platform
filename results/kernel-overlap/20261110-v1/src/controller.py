#!/usr/bin/env python3
"""Local launcher: remote runner owns finite-burst stages and template restoration."""

import json
import os
from pathlib import Path
import shlex
import subprocess
import urllib.request


def alert(message):
    url = os.environ.get("SLACK_WEBHOOK_DATASPLIT_URL") or os.environ.get(
        "SLACK_WEBHOOK_URL"
    )
    if url:
        try:
            request = urllib.request.Request(
                url,
                json.dumps({"text": message}).encode(),
                {"Content-Type": "application/json"},
            )
            urllib.request.urlopen(request, timeout=8).close()
        except Exception:
            pass


def main():
    root = os.environ.get(
        "KERNEL_OVERLAP_ROOT", "/home/avees/cj-kernel-overlap/20261110-v1"
    )
    local = Path("results/kernel-overlap") / Path(root).name
    local.mkdir(parents=True, exist_ok=True)
    script = (
        "source ~/.config/cj-ros2/spark-jazzy.bash; export ROS_DOMAIN_ID=76; export KERNEL_OVERLAP_ROOT="
        + shlex.quote(root)
        + "; export GREEN_BURST_ROOT="
        + shlex.quote(root)
        + "; python3 -u "
        + shlex.quote(root + "/src/runner.py")
    )
    alert(
        "CJ GPU kernel 겹침 진단 시작: Green16/32·기본 두 Pod 실제 동시 요청, clock anchor로 공통 GPU 타임라인 검증 후 원본 복구합니다."
    )
    result = subprocess.run(
        [
            "ssh",
            "-o",
            "ConnectTimeout=10",
            "avees@192.168.24.204",
            "bash -lc "
            + shlex.quote(script)
            + " > "
            + shlex.quote(root + "/logs/controller.log")
            + " 2>&1",
        ]
    )
    status = subprocess.run(
        [
            "ssh",
            "-o",
            "ConnectTimeout=10",
            "avees@192.168.24.204",
            "cat " + root + "/verification/controller-status.json",
        ],
        text=True,
        capture_output=True,
    )
    (local / "controller-status.json").write_text(
        status.stdout
        or json.dumps({"ssh_exit": result.returncode, "error": status.stderr})
    )
    if result.returncode:
        alert("CJ GPU timeline 진단 오류/중단. 원상복구 상태 확인 필요: " + root)
        raise SystemExit(result.returncode)
    alert(
        "CJ GPU timeline 캡처 완료. 원본 배포·실제 요청 확인 완료. 커널 겹침 분석 진행: "
        + root
    )


if __name__ == "__main__":
    main()
