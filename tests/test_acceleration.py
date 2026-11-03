import unittest
from scripts.acceleration import validate_bindings

class AccelerationTests(unittest.TestCase):
    def test_rejects_reference(self):
        with self.assertRaises(RuntimeError):
            validate_bindings({'causal_conv1d_fn': 'transformers.reference'})
    def test_rejects_missing(self):
        with self.assertRaises(RuntimeError):
            validate_bindings({})
    def test_accepts_external_kernels(self):
        validate_bindings({
            'causal_conv1d_fn': 'causal_conv1d.causal_conv1d_interface',
            'causal_conv1d_update': 'causal_conv1d.causal_conv1d_interface',
            'chunk_gated_delta_rule': 'fla.ops.gated_delta_rule.chunk',
            'fused_recurrent_gated_delta_rule': 'fla.ops.gated_delta_rule.fused_recurrent'})

class ResolutionTests(unittest.TestCase):
    def test_finds_selected_implementation_inside_wrapper(self):
        from scripts.acceleration import selected_implementation
        def external():
            pass
        def decorate(implementation):
            def wrapped():
                return implementation()
            return wrapped
        self.assertIs(selected_implementation(decorate(external)), external)

class CVBackendTests(unittest.TestCase):
    def make_yolo(self, device, dtype, fp16):
        from types import SimpleNamespace as NS
        class Parameters:
            def parameters(self):
                return iter([NS(device=NS(type=device), dtype=dtype)])
        # Ultralytics can keep the original model on CPU and clone the actual backend.
        return NS(model='original CPU model', predictor=NS(model=NS(
            model=Parameters(), device=NS(type=device), fp16=fp16)))
    def test_checks_executing_backend_not_original(self):
        from scripts.acceleration import inspect_cv_backend
        result = inspect_cv_backend(self.make_yolo('cuda', 'torch.float16', True))
        self.assertEqual(result['actual_parameter_dtype'], 'torch.float16')
    def test_rejects_cpu_backend(self):
        from scripts.acceleration import inspect_cv_backend
        with self.assertRaises(RuntimeError):
            inspect_cv_backend(self.make_yolo('cpu', 'torch.float16', True))
    def test_rejects_fp32_backend(self):
        from scripts.acceleration import inspect_cv_backend
        with self.assertRaises(RuntimeError):
            inspect_cv_backend(self.make_yolo('cuda', 'torch.float32', False))
