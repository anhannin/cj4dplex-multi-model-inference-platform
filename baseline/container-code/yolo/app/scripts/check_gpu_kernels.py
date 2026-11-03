"""Exercise installed acceleration libraries; reference math is validation only."""
import json
from pathlib import Path
import torch
import torch.nn.functional as F
from causal_conv1d import causal_conv1d_fn, causal_conv1d_update
from fla.ops.gated_delta_rule import chunk_gated_delta_rule
from transformers.models.qwen3_5 import modeling_qwen3_5
from acceleration import inspect_qwen_bindings


def main():
    torch.manual_seed(42)
    assert torch.cuda.is_available()
    results = {'bindings': inspect_qwen_bindings(), 'gpu': torch.cuda.get_device_name(),
               'capability': torch.cuda.get_device_capability(), 'torch': torch.__version__}
    for dtype in (torch.float32, torch.bfloat16):
        x = torch.randn(1, 128, 64, device='cuda', dtype=dtype)
        weight = torch.randn(128, 4, device='cuda', dtype=dtype) * .1
        actual = causal_conv1d_fn(x, weight, activation='silu')
        expected = F.silu(F.conv1d(x, weight[:, None, :], padding=3, groups=128)[:, :, :64])
        tolerance = 1e-5 if dtype == torch.float32 else .01
        torch.testing.assert_close(actual, expected, atol=tolerance, rtol=tolerance)
        state = torch.randn(1, 128, 4, device='cuda', dtype=dtype)
        new_x = torch.randn(1, 128, device='cuda', dtype=dtype)
        shifted = torch.cat([state[:, :, 1:], new_x[:, :, None]], dim=-1)
        expected_update = F.silu((shifted * weight[None]).sum(-1))
        actual_update = causal_conv1d_update(new_x, state.clone(), weight, activation='silu')
        torch.testing.assert_close(actual_update, expected_update, atol=tolerance, rtol=tolerance)
        results[str(dtype)] = {'conv_max_abs_error': (actual-expected).abs().max().item(),
                               'update_max_abs_error': (actual_update-expected_update).abs().max().item()}
    q, k, v = [torch.randn(1, 64, 4, 64, device='cuda', dtype=torch.bfloat16) for _ in range(3)]
    g = -torch.rand(1, 64, 4, device='cuda')
    beta = torch.rand(1, 64, 4, device='cuda')
    actual, _ = chunk_gated_delta_rule(q, k, v, g=g, beta=beta, use_qk_l2norm_in_kernel=True)
    # The undecorated stock reference is used only for numerical testing.
    reference = modeling_qwen3_5.torch_chunk_gated_delta_rule.__wrapped__
    expected, _ = reference(q, k, v, g=g, beta=beta, use_qk_l2norm_in_kernel=True)
    torch.testing.assert_close(actual, expected, atol=.02, rtol=.02)
    results['fla_max_abs_error'] = (actual-expected).abs().max().item()
    torch.cuda.synchronize()
    results['state'] = 'PASS'
    path = Path('/output/kernel-validation.json')
    path.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
