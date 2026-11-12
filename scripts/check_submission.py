#!/usr/bin/env python3
"""Offline submission checks. Findings identify paths/types, never secret values."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "6a99fdaf26307e2f0b41f708478fdec3fcfad7ac"
DOCS = [
    "README.md",
    "docs/TECHNICAL_REPORT.ko.md",
    "docs/EXECUTIVE_SUMMARY.ko.md",
    "docs/ARCHITECTURE.ko.md",
    "docs/REPRODUCIBILITY.ko.md",
    "docs/CODE_MAP.ko.md",
    "docs/USAGE_AND_LICENSES.ko.md",
    "docs/SUBMISSION_CHECKLIST.ko.md",
    "docs/CLEANUP_REPORT.ko.md",
]
PATTERNS = {
    "private_key": r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    "github_token": r"\bgh[pousr]_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b",
    "slack_webhook": r"https://hooks\.slack\.com/services/[A-Za-z0-9]+/[A-Za-z0-9]+/[A-Za-z0-9]+",
    "aws_access_key": r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
    "embedded_kube_credential": r"(?:client-key-data|client-certificate-data):\s*[A-Za-z0-9+/=]{80,}",
}


def secret_kinds(text):
    return [kind for kind, pattern in PATTERNS.items() if re.search(pattern, text)]


def local_links(text):
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    found = []
    for target in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", text):
        target = target.split(' "', 1)[0].strip("<> ")
        if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
            continue
        found.append(unquote(target.split("#", 1)[0]))
    return found


def git_files():
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return sorted({Path(p.decode()) for p in result.stdout.split(b"\0") if p})


def baseline_check():
    actual = subprocess.check_output(
        ["git", "rev-parse", BASELINE + "^{commit}"], cwd=ROOT, text=True
    ).strip()
    if actual != BASELINE:
        raise ValueError("Frozen baseline commit is unavailable or changed")
    tag = subprocess.run(
        [
            "git",
            "rev-parse",
            "--verify",
            "--quiet",
            "refs/tags/baseline-frozen-20261103^{commit}",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if tag.returncode == 0 and tag.stdout.strip() != BASELINE:
        raise ValueError("Frozen preservation tag points to a different commit")
    manifest = subprocess.check_output(
        ["git", "show", BASELINE + ":baseline/FILES.sha256"], cwd=ROOT, text=True
    )
    entries = [line.split("  ", 1) for line in manifest.splitlines()]
    proc = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=ROOT,
        input=("\n".join(BASELINE + ":" + p for _, p in entries) + "\n").encode(),
        capture_output=True,
        check=True,
    )
    stream = io.BytesIO(proc.stdout)
    working_changes = []
    for digest, path in entries:
        header = stream.readline().split()
        if len(header) != 3 or header[1] != b"blob":
            raise ValueError("Missing frozen baseline object: " + path)
        data = stream.read(int(header[2]))
        stream.read(1)
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("Frozen SHA mismatch: " + path)
        current = ROOT / path
        if (
            not current.is_file()
            or hashlib.sha256(current.read_bytes()).hexdigest() != digest
        ):
            working_changes.append(path)
    return {
        "state": "PASS",
        "ref": BASELINE,
        "preservation_tag": "baseline-frozen-20261103",
        "verified_files": len(entries),
        "working_tree_differences": working_changes,
        "note": "Frozen Git objects verified independently; submission README/config updates and approved obsolete removals are audited separately",
    }


def unexpected_worktree_changes(changes, manifest):
    """Accept reviewed deletion paths or exact updated hashes, never arbitrary drift."""
    allowed = set()
    for row in manifest.get("removed", []):
        if not (ROOT / row["path"]).exists():
            allowed.add(row["path"])
    for row in manifest.get("updated", []):
        path = ROOT / row["path"]
        if (
            path.is_file()
            and hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
        ):
            allowed.add(row["path"])
    return sorted(set(changes) - allowed)


def check():
    issues = []
    for path in DOCS:
        p = ROOT / path
        if not p.is_file():
            issues.append({"kind": "missing_deliverable", "path": path})
            continue
        for target in local_links(p.read_text()):
            if not (p.parent / target).exists():
                issues.append(
                    {"kind": "broken_local_link", "path": path, "target": target}
                )
    checked = 0
    large = []
    for path in git_files():
        file = ROOT / path
        if not file.is_file():
            continue
        size = file.stat().st_size
        if size > 50 * 1024 * 1024:
            large.append({"path": str(path), "bytes": size})
        if size > 50 * 1024 * 1024:
            continue
        data = file.read_bytes()
        if b"\0" in data[:8192]:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        checked += 1
        for kind in secret_kinds(text):
            issues.append({"kind": kind, "path": str(path)})
    # Verify rendered metrics and their source hashes, not manually rounded copies.
    try:
        from scripts.render_submission_tables import render, render_burst
    except ImportError:
        from render_submission_tables import render, render_burst
    tables, facts = render()
    if (ROOT / "docs/submission/RESULT_TABLES.ko.md").read_text() != tables:
        issues.append({"kind": "stale_generated_tables"})
    if json.loads((ROOT / "docs/submission/metrics.json").read_text()) != facts:
        issues.append({"kind": "stale_metric_provenance"})
    tech = (ROOT / "docs/TECHNICAL_REPORT.ko.md").read_text()
    fragment = tech.split("<!-- RESULT_TABLES_START -->\n", 1)[-1].split(
        "<!-- RESULT_TABLES_END -->", 1
    )[0]
    if fragment != render_burst():
        issues.append({"kind": "technical_report_table_drift"})
    if (ROOT / "docs/submission/BURST_TABLES.ko.md").read_text() != render_burst():
        issues.append({"kind": "stale_burst_tables"})
    baseline = baseline_check()
    manifest_path = ROOT / "docs/submission/cleanup-removals.json"
    cleanup = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
    unexpected = unexpected_worktree_changes(
        baseline["working_tree_differences"], cleanup
    )
    if unexpected:
        issues.append(
            {
                "kind": "unexpected_baseline_worktree_change",
                "paths": unexpected,
            }
        )
    for row in cleanup.get("protected_source_before", []):
        path = ROOT / row["path"]
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]
        ):
            issues.append({"kind": "protected_source_changed", "path": row["path"]})
    return {
        "state": "PASS" if not issues else "FAIL",
        "issues": issues,
        "baseline": baseline,
        "text_files_scanned": checked,
        "secret_scan_scope": "Git tracked+nonignored untracked UTF8 text <=50MiB; signatures only, no guarantee for binary/ignored/large",
        "large_raw_files_preserved": large,
        "packaging": "Use explicit exporter; do not git add all raw traces",
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--baseline-only", action="store_true")
    p.add_argument("--output", type=Path)
    a = p.parse_args()
    result = baseline_check() if a.baseline_only else check()
    if a.output:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["state"] == "PASS" else 1)
