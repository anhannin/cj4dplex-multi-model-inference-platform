"""File-gated actual request tracing; benchmark/math/queue contract otherwise unchanged."""


def instrument(source, model):
    assert source.count("        while not self.stopping.is_set():\n") == 1
    source = source.replace(
        "import hashlib\n", "import hashlib\nfrom clock_marks import anchor\n", 1
    )
    gate = """        capture_active = False
        capture_file = Path("/experiment/control/capture")
        capture_case = os.environ["PAIR_LABEL"]
        while not self.stopping.is_set():
            capture_requested = capture_file.exists()
            if capture_requested and not capture_active:
                torch.cuda.profiler.start()
                capture_active = True
                stamp = anchor("MODEL", "capture-start")
                Path("/experiment/control/" + capture_case + "-MODEL.started").write_text(json.dumps(stamp))
            elif not capture_requested and capture_active:
                stamp = anchor("MODEL", "capture-stop")
                torch.cuda.profiler.stop()
                capture_active = False
                Path("/experiment/control/" + capture_case + "-MODEL.stopped").write_text(json.dumps(stamp))
""".replace("MODEL", model)
    source = source.replace("        while not self.stopping.is_set():\n", gate, 1)
    before = (
        '                    reply["model_start_perf_ns"] = time.perf_counter_ns()\n'
    )
    after = '                    reply["model_end_perf_ns"] = time.perf_counter_ns()\n'
    assert source.count(before) == source.count(after) == 1
    source = source.replace(
        before,
        f'''                    if capture_active:
                        anchor("{model}", "request-begin:" + request_id)
                        torch.cuda.nvtx.range_push("request:{model}:" + request_id)
'''
        + before,
        1,
    )
    source = source.replace(
        after,
        """                    if capture_active:
                        torch.cuda.current_stream().synchronize()
                        torch.cuda.nvtx.range_pop()
                        anchor("MODEL", "request-end:" + request_id)
""".replace("MODEL", model)
        + after,
        1,
    )
    return source


try:
    from diagnostics.green_burst.generate import burst_template as burst_template
except ModuleNotFoundError:
    from base_burst_generate import burst_template as burst_template
