"""Produce diagnostic-only copies; do not edit the frozen serving sources."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def instrument(model, source):
    gate = f"""        capture_phase = None
        control = Path("/profiles/control/capture")
        while not self.stopping.is_set():
            try:
                requested_phase = control.read_text().strip()
            except FileNotFoundError:
                requested_phase = None
            if requested_phase and capture_phase is None:
                torch.cuda.profiler.start()
                torch.cuda.nvtx.range_push("phase:" + requested_phase)
                capture_phase = requested_phase
                Path("/profiles/control/{model}.started").write_text(capture_phase)
            elif not requested_phase and capture_phase is not None:
                ended_phase = capture_phase
                torch.cuda.nvtx.range_pop()
                torch.cuda.profiler.stop()
                capture_phase = None
                Path("/profiles/control/{model}.stopped").write_text(ended_phase)
"""
    old = "        while not self.stopping.is_set():\n"
    assert source.count(old) == 1
    output = source.replace(old, gate, 1)
    if model == "qwen":
        begin = output.index("                    output = model.generate(")
        end = output.index('                    timing["generate_wall_ms"]', begin)
        # Complete GPU boundary included; same original generate arguments.
        block = output[begin:end]
        output = (
            output[:begin]
            + '                    with torch.cuda.nvtx.range("qwen.generate"):\n'
            + "".join(
                "    " + line if line.strip() else line
                for line in block.splitlines(keepends=True)
            )
            + output[end:]
        )
    else:
        line = "                    result = model.predict(image, **options)[0]\n"
        assert line in output
        output = output.replace(
            line,
            '                    with torch.cuda.nvtx.range("yolo.predict"):\n    '
            + line,
            1,
        )
    return output


def benchmark_copy(source):
    assert source.count("a.warmup < 1") == 1
    return source.replace("a.warmup < 1", "a.warmup < 0", 1)


def main():
    out = Path(__file__).resolve().parent / "generated"
    out.mkdir(exist_ok=True)
    for model in ("qwen", "yolo"):
        (out / f"{model}_node.py").write_text(
            instrument(model, (ROOT / f"ros2/{model}_node.py").read_text())
        )
    (out / "bench_profile.py").write_text(
        benchmark_copy((ROOT / "benchmark/bench_ros2.py").read_text())
    )


if __name__ == "__main__":
    main()
