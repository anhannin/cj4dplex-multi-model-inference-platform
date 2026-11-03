import importlib.util
import inspect
from pathlib import Path
import textwrap
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def client():
    spec = importlib.util.spec_from_file_location(
        "qwen_eos_client", ROOT / "clients/request_qwen.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EOSPolicyTests(unittest.TestCase):
    def policy(self, maximum, context=262144, inputs=20):
        source = (ROOT / "ros2/qwen_node.py").read_text()
        block = source.split(
            "# Resolve the generation budget from the model context.", 1
        )[1].split("with torch.inference_mode():", 1)[0]
        scope = {
            "model": SimpleNamespace(
                config=SimpleNamespace(
                    text_config=SimpleNamespace(max_position_embeddings=context)
                )
            ),
            "input_tokens": inputs,
            "maximum": maximum,
            "reply": {},
        }
        exec(textwrap.dedent(block), scope)
        return scope["maximum"]

    def test_default_client_has_no_fixed_output_budget(self):
        self.assertIsNone(
            inspect.signature(client().request_qwen)
            .parameters["max_new_tokens"]
            .default
        )

    def test_default_uses_remaining_context_not_128_or_512(self):
        self.assertEqual(self.policy(None), 262144 - 20)

    def test_explicit_budget_above_1028_is_accepted(self):
        self.assertEqual(self.policy(4096), 4096)

    def test_explicit_budget_cannot_exceed_model_context(self):
        with self.assertRaises(ValueError):
            self.policy(4096, context=2048)

    def test_client_accepts_large_explicit_budget(self):
        class InitReached(Exception):
            pass

        ros = ModuleType("rclpy")

        def init(**kw):
            raise InitReached()

        ros.init = init
        qos = ModuleType("rclpy.qos")
        qos.DurabilityPolicy = object
        qos.QoSProfile = object
        msg = ModuleType("std_msgs.msg")
        msg.String = object
        with patch.dict(
            "sys.modules", {"rclpy": ros, "rclpy.qos": qos, "std_msgs.msg": msg}
        ):
            with self.assertRaises(InitReached):
                client().request_qwen("test", 4096)
