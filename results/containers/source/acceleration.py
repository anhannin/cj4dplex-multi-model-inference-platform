"""Fail-closed validation; does not modify any upstream implementation."""
EXPECTED = {
    'causal_conv1d_fn': 'causal_conv1d.',
    'causal_conv1d_update': 'causal_conv1d.',
    'chunk_gated_delta_rule': 'fla.',
    'fused_recurrent_gated_delta_rule': 'fla.',
}


def validate_bindings(bindings):
    for name, prefix in EXPECTED.items():
        if not bindings.get(name, '').startswith(prefix):
            raise RuntimeError('Missing external acceleration binding: ' + name)


def selected_implementation(function):
    """Inspect the pinned Transformers dispatcher without patching its function."""
    import inspect
    seen = set()
    while callable(function) and id(function) not in seen:
        seen.add(id(function))
        nonlocals = inspect.getclosurevars(function).nonlocals if inspect.isfunction(function) else {}
        if 'implementation' in nonlocals:
            return nonlocals['implementation']
        function = getattr(function, '__wrapped__', None)
    raise RuntimeError('Cannot verify dispatcher implementation')


def inspect_qwen_bindings():
    from transformers.models.qwen3_5 import modeling_qwen3_5 as implementation
    names = {'causal_conv1d_fn': 'causal_conv1d_fn',
             'causal_conv1d_update': 'causal_conv1d_update',
             'chunk_gated_delta_rule': 'torch_chunk_gated_delta_rule',
             'fused_recurrent_gated_delta_rule': 'torch_recurrent_gated_delta_rule'}
    bindings = {name: selected_implementation(getattr(implementation, attribute)).__module__
                for name, attribute in names.items()}
    validate_bindings(bindings)
    return bindings


def inspect_cv_backend(yolo):
    """Validate the executing AutoBackend, not the untouched original CPU model."""
    backend = yolo.predictor.model
    parameter = next(backend.model.parameters())
    if (backend.device.type != 'cuda' or not backend.fp16
            or parameter.device.type != 'cuda' or str(parameter.dtype) != 'torch.float16'):
        raise RuntimeError('YOLO executing backend is not native CUDA FP16')
    return {'actual_parameter_dtype': str(parameter.dtype),
            'actual_parameter_device': str(parameter.device),
            'actual_backend': type(backend).__module__ + '.' + type(backend).__name__}
