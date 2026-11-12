"""Exactly the frozen Qwen node's read-only native dispatcher check."""
import inspect


def native_bindings(module):
    bindings={}
    for attribute,prefix in [('causal_conv1d_fn','causal_conv1d.'),('causal_conv1d_update','causal_conv1d.'),('torch_chunk_gated_delta_rule','fla.'),('torch_recurrent_gated_delta_rule','fla.')]:
        function=getattr(module,attribute)
        selected=inspect.getclosurevars(function).nonlocals.get('implementation')
        name=getattr(selected,'__module__','')
        if not name.startswith(prefix):
            raise RuntimeError('Missing GPU acceleration: '+attribute)
        bindings[attribute]=name
    return bindings
