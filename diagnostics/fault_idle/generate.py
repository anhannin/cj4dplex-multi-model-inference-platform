"""Diagnostic gate in the real YOLO inference thread; no in-flight GPU kill."""


def add_idle_gate(source):
    marker = "        while not self.stopping.is_set():\n"
    if source.count(marker) != 1:
        raise ValueError("Review source before adding idle-only fault gate")
    gate = """        while not self.stopping.is_set():
            idle_gate = Path("/experiment/control/yolo-idle-gate.json")
            if idle_gate.exists():
                idle_request = json.loads(idle_gate.read_text())
                if not self.requests.empty():
                    raise RuntimeError("Refuse idle fault acknowledgement with pending requests")
                # Synchronize in THIS inference process/context, not an exec helper.
                torch.cuda.synchronize()
                if not self.requests.empty():
                    raise RuntimeError("Request arrived while establishing idle barrier")
                idle_ack = {"nonce":idle_request["nonce"], "pid":os.getpid(),
                    "gpu_synchronized":True, "queue_empty":True,
                    "perf_ns":time.perf_counter_ns(), "wall_ns":time.time_ns()}
                ack_path = Path("/experiment/control/idle-ack-" + idle_request["nonce"] + ".json")
                temporary = ack_path.with_suffix(".new")
                temporary.write_text(json.dumps(idle_ack))
                temporary.replace(ack_path)
                while idle_gate.exists() and not self.stopping.is_set():
                    time.sleep(0.01)
                continue
"""
    return source.replace(marker, gate, 1)
