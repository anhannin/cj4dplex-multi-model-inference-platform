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
    root = os.environ.get("GREEN_BURST_ROOT", "/home/avees/cj-green-burst/20261109-v1")
    local = Path("results/green-burst") / Path(root).name
    local.mkdir(parents=True, exist_ok=True)
    script = (
        "source ~/.config/cj-ros2/spark-jazzy.bash; export ROS_DOMAIN_ID=74; export GREEN_BURST_ROOT="
        + shlex.quote(root)
        + "; python3 -u "
        + shlex.quote(root + "/src/runner.py")
    )
    alert(
        "CJ 고정 동시 burst 비교 시작: Qwen10/YOLO300, Green미적용+5조합, Queue/GPU 구간 기록. 원본 배포는 종료 후 복구합니다."
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
        alert(
            "CJ 동시 burst 실험 오류/중단. 요청 유실·원상복구 상태 확인 필요: " + root
        )
        raise SystemExit(result.returncode)
    alert(
        "CJ 동시 burst 전조합 비교 종료. 원본 배포·실제 요청 확인 완료. 분석 진행: "
        + root
    )


if __name__ == "__main__":
    main()
