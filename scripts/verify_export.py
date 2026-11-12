#!/usr/bin/env python3
"""Verify curated payload without Git; never equate it to complete raw archives."""

import hashlib
import json
from pathlib import Path
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
manifest = json.loads((root / "SUBMISSION_MANIFEST.json").read_text())
for row in manifest["included"]:
    path = (root / row["path"]).resolve()
    if root not in path.parents:
        raise ValueError("Path escapes payload")
    if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
        raise ValueError("SHA mismatch: " + row["path"])
print(
    json.dumps(
        {
            "state": "PASS",
            "included_files": len(manifest["included"]),
            "omitted_files": len(manifest["excluded"]),
            "complete_raw_archive": False,
        }
    )
)
