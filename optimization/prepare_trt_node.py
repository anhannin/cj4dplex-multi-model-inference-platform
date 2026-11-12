"""Make a diagnostic node copy; only replace Torch-specific startup validation."""
from pathlib import Path


def trt_node(source):
    old = '''            parameter = next(backend.model.parameters())
            if (
                backend.device.type != "cuda"
                or not backend.fp16
                or parameter.dtype != torch.float16
            ):
                raise RuntimeError("Executing backend is not native CUDA FP16")'''
    new = '''            import numpy as np
            if (
                backend.format != "engine"
                or backend.device.type != "cuda"
                or backend.bindings["images"].dtype not in (np.float16, np.float32)
            ):
                raise RuntimeError("Executing backend is not TensorRT CUDA floating-point")'''
    if source.count(old) != 1:
        raise ValueError('Frozen startup block changed; review before adapting')
    source = source.replace(old, new)
    source = source.replace('"device": str(parameter.device)', '"device": str(backend.device)')
    source = source.replace('"dtype": str(parameter.dtype)', '"dtype": str(backend.bindings["images"].dtype)')
    return source


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    with a.output.open('x') as f:
        f.write(trt_node(Path('ros2/yolo_node.py').read_text()))
