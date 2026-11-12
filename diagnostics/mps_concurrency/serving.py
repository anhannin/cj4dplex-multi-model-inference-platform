"""Generate normal serving artifacts, without profiler or forced-length workload."""

import argparse
import json
from pathlib import Path

from diagnostics.green_e2e.generate import make_template, render_node
from diagnostics.mps_concurrency.overlay import with_mps


def serving_template(original, model, root):
    t = make_template(original, model, 16, 32, root, "serving-mps-green")
    c = t["spec"]["containers"][0]
    c["env"] = [
        e
        for e in c["env"]
        if e["name"] not in ("BENCH_FORCE_LENGTH", "PROFILE_CAPTURE_SEQUENCE")
    ]
    for e in c["env"]:
        if e["name"] == "ROS_DOMAIN_ID":
            e["value"] = "42"
    c["command"][-1] = (
        'set -eo pipefail; test -S "$CUDA_MPS_PIPE_DIRECTORY/control"; '
        + 'printf "get_server_list\\n" | nvidia-cuda-mps-control >/dev/null; '
        + c["command"][-1]
    )
    return with_mps(t, root + "/mps-pipe")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--remote-root", default="/home/avees/cj-serving/mps-green-v1")
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    (a.output / "src").mkdir(exist_ok=True)
    for model in ("qwen", "yolo"):
        source = render_node(Path(f"ros2/{model}_node.py").read_text(), model)
        compile(source, "serving", "exec")
        (a.output / "src" / f"{model}_green_node.py").write_text(source)
        deployment = json.loads(Path(f"k8s/serving/{model}.json").read_text())
        deployment["spec"]["template"] = serving_template(
            deployment["spec"]["template"], model, a.remote_root
        )
        (a.output / f"{model}.json").write_text(json.dumps(deployment, indent=2))


if __name__ == "__main__":
    main()
