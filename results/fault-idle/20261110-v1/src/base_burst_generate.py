"""Same burst-capability/timing instrumentation for noGreen control and every split."""

try:
    from diagnostics.green_e2e.generate import render_node, make_template
except ModuleNotFoundError:
    from base_generate import render_node, make_template


def render_burst_node(source, model):
    text = render_node(source, model)
    text = text.replace(
        "import hashlib\n",
        "import hashlib\nfrom gpu_observer import ForwardTimer\nfrom stage_metrics import summarize_forward\n",
        1,
    )
    qos = "QoSProfile(depth=32, durability=DurabilityPolicy.TRANSIENT_LOCAL)"
    assert text.count(qos) == 1
    text = text.replace(
        qos, "QoSProfile(depth=512, durability=DurabilityPolicy.TRANSIENT_LOCAL)", 1
    )
    cleanup = """            if torch is not None:
                torch.cuda.synchronize()"""
    assert text.count(cleanup) == 1
    text = text.replace(
        cleanup,
        """            if hasattr(self, "_gpu_timer"):
                self._gpu_timer.close()
                self._gpu_timer = None
"""
        + cleanup,
        1,
    )
    ready = """            self.get_logger().info(
                json.dumps(
                    {
                        "event": "model_loaded","""
    assert text.count(ready) == 1
    module = "model" if model == "qwen" else "model.predictor.model.model"
    text = text.replace(
        ready,
        f'''            self._gpu_timer = ForwardTimer(torch, {module}, "{model}")
            self._gpu_timer.configure(torch.cuda.current_stream(), {128 if model == "qwen" else 1})
'''
        + ready,
        1,
    )
    marker = '            reply["green_enabled"] = self._green_mode\n'
    assert text.count(marker) == 1
    text = text.replace(
        marker,
        """            reply["server_enqueued_perf_ns"] = int(enqueued * 1e9)
            reply["server_started_perf_ns"] = int(started * 1e9)
"""
        + marker,
        1,
    )
    if model == "qwen":
        marker = "                    generate_start = time.perf_counter_ns()\n"
        text = text.replace(
            marker,
            """                    self._gpu_timer.reset()
                    reply["model_start_perf_ns"] = time.perf_counter_ns()
"""
            + marker,
            1,
        )
        marker = "                    if token_clock is not None:\n"
        assert text.count(marker) == 1
        text = text.replace(
            marker,
            """                    reply["model_end_perf_ns"] = time.perf_counter_ns()
                    forward_times = self._gpu_timer.elapsed()
                    stages = summarize_forward(self._gpu_timer.lengths, forward_times, int(input_tokens), int(maximum))
                    timing["gpu_prefill_span_ms"] = stages["prefill_forward_ms"]
                    timing["gpu_decode_total_span_ms"] = stages["decode_forward_total_ms"]
                    timing["gpu_decode_ms_per_token"] = stages["decode_forward_ms_per_token"]
                    timing["gpu_forward_span_ms"] = sum(forward_times)
                    reply["gpu_forward_event_ms"] = forward_times
                    reply["gpu_forward_lengths"] = list(self._gpu_timer.lengths)
"""
            + marker,
            1,
        )
    else:
        marker = "                    predict_start = time.perf_counter_ns()\n"
        text = text.replace(
            marker,
            """                    self._gpu_timer.reset()
                    reply["model_start_perf_ns"] = time.perf_counter_ns()
"""
            + marker,
            1,
        )
        marker = "                    result = model.predict(image, **options)[0]\n"
        assert text.count(marker) == 1
        text = text.replace(
            marker,
            marker + "                    torch.cuda.current_stream().synchronize()\n",
            1,
        )
        marker = '                    timing["yolo_preprocess_ms"] = result.speed["preprocess"]\n'
        assert text.count(marker) == 1
        text = text.replace(
            marker,
            """                    reply["model_end_perf_ns"] = time.perf_counter_ns()
                    forward_times = self._gpu_timer.elapsed()
                    if len(forward_times) != 1 or self._gpu_timer.lengths != [[1, 3, 640, 640]]:
                        raise RuntimeError("Wrong native YOLO forward count/shape")
                    timing["gpu_forward_span_ms"] = forward_times[0]
                    reply["gpu_forward_shape"] = [1, 3, 640, 640]
"""
            + marker,
            1,
        )
    return text


def burst_template(original, model, qsm, ysm, root, label, enabled=True):
    t = make_template(original, model, qsm, ysm, root, label, enabled=enabled)
    c = t["spec"]["containers"][0]
    c["command"][-1] = (
        c["command"][-1].replace("_green_node.py", "_burst_node.py")
        + f" --ros-args -p queue_capacity:={16 if model == 'qwen' else 512}"
    )
    for item in c["env"]:
        if item["name"] == "ROS_DOMAIN_ID":
            item["value"] = "74"
    return t
