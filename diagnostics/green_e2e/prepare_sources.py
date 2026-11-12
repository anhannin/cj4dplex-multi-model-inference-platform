"""Create experiment source copies without editing frozen serving/benchmark files."""

from pathlib import Path
from generate import render_node


def benchmark_copy(source):
    start = source.index("PROMPTS = [")
    end = source.index("\n\n\ndef request_payload", start)
    source = (
        source[:start]
        + """WORKLOAD = json.loads((Path(__file__).resolve().parents[1] / "workload.json").read_text())
PROMPTS = [WORKLOAD["text"]]
"""
        + source[end:]
    )
    old = 'for name in ("bus.jpg", "zidane.jpg"):'
    assert source.count(old) == 1
    source = source.replace(old, 'for name in ("bus.jpg",):', 1)
    marker = "            reply = json.loads(message.data)\n"
    assert source.count(marker) == 1
    source = source.replace(
        marker,
        marker
        + """            if reply.get("status") == "ok":
                expected = int(__import__("os").environ["EXPECTED_" + model.upper() + "_SMS"])
                assert reply["assigned_sms"] == expected, "Wrong model SM allocation"
                if model == "qwen":
                    assert reply["input_tokens"] == 512 and reply["output_tokens"] == 128
                    assert reply["input_ids_sha256"] == WORKLOAD["input_ids_sha256"]
""",
        1,
    )
    marker = "    rows = []\n"
    assert source.count(marker) == 1
    source = source.replace(
        marker,
        """    manifest["fixed_workload"] = {k: v for k, v in WORKLOAD.items() if k not in ("text", "input_ids")}
    manifest["ros_domain"] = 73
"""
        + marker,
        1,
    )
    return source


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    for model in ("qwen", "yolo"):
        source = (a.repo / "ros2" / f"{model}_node.py").read_text()
        for profile in (False, True):
            name = model + ("_green_profile_node.py" if profile else "_green_node.py")
            with (a.output / name).open("x") as f:
                f.write(render_node(source, model, profile))
    with (a.output / "bench_green.py").open("x") as f:
        f.write(benchmark_copy((a.repo / "benchmark/bench_ros2.py").read_text()))
