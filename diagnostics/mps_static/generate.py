"""Reuse frozen native inference and event instrumentation; NO Green Context API."""

try:
    from diagnostics.green_burst.generate import render_burst_node
except ModuleNotFoundError:
    from base_burst_generate import render_burst_node


def render_static_node(source, model):
    code = render_burst_node(source, model)
    lo = code.index("    def _worker(self):\n")
    hi = code.index("    def _frozen_worker(self):\n", lo)
    wrapper = """    def _worker(self):
        torch = None
        try:
            import torch
            import ctypes
            torch.set_num_threads(4)
            torch.cuda.set_device(0)
            actual = int(torch.cuda.get_device_properties(0).multi_processor_count)
            expected = int(os.environ["EXPECTED_SMS"])
            if actual != expected:
                raise RuntimeError(f"MPS visible SM mismatch: {actual} != {expected}")
            self._green_mode = False
            self._green_sms = actual
            self._expected_stream = torch.cuda.current_stream().cuda_stream
            runtime = ctypes.c_int()
            ctypes.CDLL("libcudart.so.13").cudaRuntimeGetVersion(ctypes.byref(runtime))
            metadata = {"event":"gpu_resource_ready", "enabled":False,
                "selected_sms":actual, "observed_smids":None,
                "partition_id":os.environ.get("CUDA_MPS_SM_PARTITION"),
                "torch_build_cuda":torch.version.cuda, "cuda_runtime":runtime.value,
                "pid":os.getpid(), "time_ns":time.time_ns(), "pair":os.environ["PAIR_LABEL"]}
            if runtime.value != 13010:
                raise RuntimeError("Expected actually loaded CUDA13.1 runtime, not only toolkit installation")
            folder = Path("/experiment/metadata")
            folder.mkdir(exist_ok=True)
            name = os.environ["PAIR_LABEL"] + "-MODEL-" + str(os.getpid()) + "-" + str(time.time_ns()) + ".json"
            (folder/name).write_text(json.dumps(metadata,indent=2))
            self.get_logger().info(json.dumps(metadata))
            self._frozen_worker()
        except BaseException as error:
            self.load_error = error
            self.loaded.set()
            self.get_logger().error("MPS worker failure: " + repr(error))
        finally:
            if hasattr(self, "_gpu_timer"):
                self._gpu_timer.close()
            if torch is not None:
                torch.cuda.synchronize()
                gc.collect()
                torch.cuda.empty_cache()

""".replace("MODEL", model)
    code = code[:lo] + wrapper + code[hi:]
    assert "green_bridge" not in code and "GreenPair" not in code
    return code
