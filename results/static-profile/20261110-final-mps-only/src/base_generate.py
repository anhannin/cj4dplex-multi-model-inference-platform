"""Diagnostic-only node copies and reversible Kubernetes template overlays."""

import copy


def combinations():
    return [(16, 32), (24, 24), (32, 16), (8, 40), (40, 8)]


def classify_change(solo, concurrent, band=0.05):
    if solo <= 0 or concurrent <= 0:
        raise ValueError("Positive durations required")
    ratio = concurrent / solo
    return {
        "ratio": ratio,
        "change_percent": 100 * (ratio - 1),
        "classification": "slower"
        if ratio > 1 + band
        else "faster"
        if ratio < 1 - band
        else "near_equal",
        "note": "descriptive practical band, not statistical equivalence",
    }


def render_node(source, model, profile=False):
    if model not in ("qwen", "yolo") or source.count("    def _worker(self):") != 1:
        raise ValueError("Unexpected frozen node source")
    source = source.replace(
        "import itertools\n", "import itertools\nimport gc\nimport hashlib\n", 1
    )
    wrapper = """    def _worker(self):
        pair = None
        stream = None
        torch = None
        try:
            import torch
            torch.set_num_threads(4)
            torch.cuda.set_device(0)
            enabled = os.environ.get("GREEN_ENABLED", "0") == "1"
            index = int(os.environ.get("GREEN_PARTITION_INDEX", "0"))
            expected = int(os.environ.get("GREEN_EXPECTED_SM", "48"))
            self._green_mode = enabled
            if enabled:
                import green_bridge
                pair = green_bridge.GreenPair(int(os.environ["GREEN_LEFT_SMS"]))
                metadata = dict(pair.metadata())
                selected = metadata["parts"][index]
                actual = int(selected["actual_sms"])
                ids = pair.sample_smids(index)
                if actual != expected or not 0 < len(ids) <= actual:
                    raise RuntimeError("Wrong Green allocation or sampled SM set")
                stream = torch.cuda.ExternalStream(pair.stream_ptr(index), device=0)
                stream.wait_stream(torch.cuda.current_stream())
                metadata.update(selected_index=index, selected_sms=actual, observed_smids=ids)
            else:
                stream = torch.cuda.current_stream()
                actual = int(torch.cuda.get_device_properties(0).multi_processor_count)
                if actual != 48:
                    raise RuntimeError("Unexpected full-GPU control size")
                metadata = {"selected_sms": actual, "observed_smids": None}
            self._green_sms = actual
            self._expected_stream = stream.cuda_stream
            metadata.update(event="gpu_resource_ready", enabled=enabled,
                            pair=os.environ.get("PAIR_LABEL"), pid=os.getpid(), time_ns=time.time_ns())
            folder = Path("/experiment/metadata")
            folder.mkdir(exist_ok=True)
            name = os.environ["PAIR_LABEL"] + "-MODEL-" + str(os.getpid()) + "-" + str(time.time_ns()) + ".json"
            (folder / name).write_text(json.dumps(metadata, indent=2))
            self.get_logger().info(json.dumps(metadata))
            with torch.cuda.stream(stream):
                self._frozen_worker()
        except BaseException as error:
            self.load_error = error
            self.loaded.set()
            self.get_logger().error("GPU worker failure: " + repr(error))
        finally:
            if torch is not None:
                torch.cuda.synchronize()
                gc.collect()
                torch.cuda.empty_cache()
            if pair is not None:
                del stream
                pair.close()

""".replace("MODEL", model)
    source = source.replace(
        "    def _worker(self):", wrapper + "    def _frozen_worker(self):", 1
    )
    # Tiny diagnostic fields, identical between solo/concurrent. Original queue/protocol unchanged.
    mark = """            try:
                envelope = json.loads(message.data)"""
    assert source.count(mark) == 1
    source = source.replace(
        mark,
        """            reply["green_enabled"] = self._green_mode
            reply["assigned_sms"] = self._green_sms
"""
        + mark,
        1,
    )
    if model == "qwen":
        mark = '                reply["input_tokens"] = int(input_tokens)\n'
        assert source.count(mark) == 1
        source = source.replace(
            mark,
            mark
            + """                reply["input_ids_sha256"] = hashlib.sha256(
                    json.dumps(inputs["input_ids"][0].tolist()).encode()
                ).hexdigest()
""",
            1,
        )
        mark = "                    output = model.generate(\n"
        assert source.count(mark) == 1
        source = source.replace(
            mark,
            """                    if os.environ.get("BENCH_FORCE_LENGTH") == "1":
                        generation_options["min_new_tokens"] = maximum
"""
            + mark,
            1,
        )
        start = "                    generate_start = time.perf_counter_ns()\n"
        finish = '                    timing["generate_wall_ms"] = (\n'
        label = "qwen.green.serving"
    else:
        start = "                    predict_start = time.perf_counter_ns()\n"
        # Synchronize at the existing predict boundary in CUDA13 stock Profile; extra explicit sync is outside ROI already CPU blocks.
        finish = '                    timing["predict_wall_ms"] = (\n'
        label = "yolo.green.serving"
    guard = """                    if torch.cuda.current_stream().cuda_stream != self._expected_stream:
                        raise RuntimeError("Request GPU work escaped selected stream")
"""
    if profile:
        guard += """                    capture_this = sequence == int(os.environ.get("PROFILE_CAPTURE_SEQUENCE", "3"))
                    if capture_this:
                        torch.cuda.profiler.start()
                        torch.cuda.nvtx.range_push("LABEL")
""".replace("LABEL", label)
    assert source.count(start) == 1 and source.count(finish) == 1
    source = source.replace(start, guard + start, 1)
    if profile:
        source = source.replace(
            finish,
            """                    if capture_this:
                        torch.cuda.synchronize()
                        torch.cuda.nvtx.range_pop()
                        torch.cuda.profiler.stop()
"""
            + finish,
            1,
        )
    return source


def make_template(
    original, model, q_sms, y_sms, root, label, enabled=True, profile=False
):
    if enabled and (q_sms + y_sms != 48 or q_sms not in (8, 16, 24, 32, 40)):
        raise ValueError("Complementary GB10 split required")
    t = copy.deepcopy(original)
    c = t["spec"]["containers"][0]
    env = {e["name"]: e for e in c["env"] if not e["name"].startswith("CUDA_MPS_")}
    for name, value in {
        "ROS_DOMAIN_ID": "73",
        "GREEN_ENABLED": "1" if enabled else "0",
        "GREEN_PARTITION_INDEX": "1" if model == "qwen" else "0",
        "GREEN_LEFT_SMS": str(y_sms),
        "GREEN_EXPECTED_SM": str(q_sms if model == "qwen" else y_sms),
        "PAIR_LABEL": label,
        "BENCH_FORCE_LENGTH": "1",
        "PROFILE_CAPTURE_SEQUENCE": "3",
        "PYTHONPATH": "/experiment/src",
    }.items():
        env[name] = {"name": name, "value": value}
    c["env"] = list(env.values())
    c["args"] = []
    if profile:
        c["command"] = ["/bin/bash", "/experiment/src/launch_profile.sh", model]
    else:
        c["command"] = [
            "/bin/bash",
            "-c",
            "source /opt/ros/jazzy/setup.bash && exec python /experiment/src/"
            + model
            + "_green_node.py",
        ]
    t["spec"]["volumes"].append(
        {"name": "green-experiment", "hostPath": {"path": root, "type": "Directory"}}
    )
    c["volumeMounts"].append({"name": "green-experiment", "mountPath": "/experiment"})
    return t
