#!/usr/bin/env python3
"""Non-destructive, explicit working-tree export; never publish or delete originals."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil

try:
    from scripts.check_submission import ROOT, git_files, secret_kinds
except ImportError:
    from check_submission import ROOT, git_files, secret_kinds


def exclusion_reason(path, size):
    if size > 50 * 1024 * 1024:
        return "large raw >50MiB; original retained"
    if path.suffix.lower() in (
        ".sqlite",
        ".nsys-rep",
        ".ncu-rep",
        ".so",
        ".whl",
        ".tar",
        ".zst",
        ".zip",
        ".pt",
        ".safetensors",
        ".jpg",
        ".jpeg",
    ):
        return "profiling/runtime/model/photo binary; original retained"
    if (
        path.suffix.lower() == ".png"
        and "/plots/" not in "/" + path.as_posix()
        and path.parts[0] != "docs"
    ):
        return "non-chart image; individual photo rights not established"
    if path.name in ("admin.conf", "super-admin.conf") or path.suffix == ".kubeconfig":
        return "administrator credential prohibited"
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    dest = a.output.resolve()
    if dest == ROOT or ROOT in dest.parents:
        raise ValueError("Export outside source tree to prevent recursive copies")
    if dest.exists():
        raise ValueError("Refuse overwriting an existing export")
    selected = []
    excluded = []
    for path in git_files():
        source = ROOT / path
        if not source.is_file():
            continue
        if source.is_symlink():
            raise ValueError("Review symlink before export: " + str(path))
        data = source.read_bytes()
        reason = exclusion_reason(path, len(data))
        if b"\0" in data[:8192] and path.suffix.lower() not in (".png", ".pdf"):
            reason = reason or "compiled/runtime binary; rebuild from source"
        if reason:
            excluded.append(
                {
                    "path": path.as_posix(),
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "reason": reason,
                }
            )
            continue
        if len(data) <= 50 * 1024 * 1024:
            try:
                findings = secret_kinds(data.decode("utf-8"))
            except UnicodeDecodeError:
                findings = []
            if findings:
                raise ValueError(
                    "Credential signature: "
                    + str(path)
                    + " ("
                    + ",".join(findings)
                    + ")"
                )
        selected.append(
            (
                path,
                {
                    "path": path.as_posix(),
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                },
            )
        )
    dest.mkdir(parents=True)
    for path, _ in selected:
        target = dest / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / path, target)
    manifest = {
        "source": "working tree including untracked source/docs/results; not git-only archive",
        "not_publication": True,
        "included": [r for _, r in selected],
        "excluded": excluded,
        "bytes": sum(r["bytes"] for _, r in selected),
        "limits": "Omitted binaries/large raw are retained at origin; original run SHA lists may reference omitted files. This manifest verifies included payload only.",
    }
    (dest / "SUBMISSION_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    (dest / "EXCLUDED_ARTIFACTS.ko.md").write_text(
        "# 제출 묶음에서 제외한 원본\n\n원본은 삭제하지 않았으며 SUBMISSION_MANIFEST.json에 경로·크기·SHA·이유를 기록했다. 모델/사진/컴파일 산출물/대형 profiler 바이너리는 자동 재배포하지 않는다. 원래 run의 raw-files.sha256 전체가 이 묶음에 포함됐다는 뜻이 아니다. 포함 파일은 아래 검증 명령을 사용한다.\n\n`python3 scripts/verify_export.py .`\n"
    )
    print(
        json.dumps(
            {
                "output": str(dest),
                "included": len(selected),
                "excluded": len(excluded),
                "bytes": manifest["bytes"],
                "published": False,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
