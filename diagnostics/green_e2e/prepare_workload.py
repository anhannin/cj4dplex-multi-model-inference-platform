"""CPU-only: use original tokenizer path to reproduce the prior exact512-token chat."""

import json
import hashlib
from pathlib import Path
from transformers import AutoTokenizer

ROOT = Path("/experiment")
prior = json.loads(Path("/prior/results/main-qwen/manifest.json").read_text())[
    "workload"
]
tok = AutoTokenizer.from_pretrained(
    "/cache/models--Qwen--Qwen3.5-9B/snapshots/c202236235762e1c871ad0ccb60c8ee5ba337b9a",
    local_files_only=True,
)
placeholder = "CJ_E2E_UNIQUE_PLACEHOLDER_48129"
render = tok.apply_chat_template(
    [{"role": "user", "content": placeholder}],
    tokenize=False,
    add_generation_prompt=True,
    enable_thinking=False,
)
prefix, suffix = render.split(placeholder)
assert prior["rendered_input"].startswith(prefix) and prior["rendered_input"].endswith(
    suffix
)
text = prior["rendered_input"][len(prefix) : -len(suffix)]
prompt = tok.apply_chat_template(
    [{"role": "user", "content": text}],
    tokenize=False,
    add_generation_prompt=True,
    enable_thinking=False,
)
ids = tok(prompt)["input_ids"]
assert len(ids) == 512, len(ids)
sha = hashlib.sha256(json.dumps(ids).encode()).hexdigest()
assert sha == prior["input_ids_sha256"], (sha, prior["input_ids_sha256"])
result = {
    "text": text,
    "input_ids": ids,
    "input_tokens": len(ids),
    "input_ids_sha256": sha,
    "matches_prior_sm_sweep": True,
    "output_tokens": 128,
    "image": "bus.jpg",
    "image_sha256": hashlib.sha256(Path("/assets/bus.jpg").read_bytes()).hexdigest(),
    "generation": "stock min_new_tokens=max_new_tokens=128,greedy,cache=True",
    "ros_domain": 73,
}
(ROOT / "workload.json").write_text(json.dumps(result, indent=2))
print(
    json.dumps(
        {k: v for k, v in result.items() if k not in ("text", "input_ids")}, indent=2
    )
)
