"""Stock Module hooks; preallocated CUDA events, no per-forward synchronization."""
import time


def check_stream(expected, actual):
    if expected != actual:
        raise RuntimeError(f'Forward escaped selected PyTorch stream: {actual} != {expected}')


class ForwardTimer:
    def __init__(self, torch, module, kind):
        self.torch, self.kind = torch, kind
        self.handles = [module.register_forward_pre_hook(self.before, with_kwargs=True), module.register_forward_hook(self.after, with_kwargs=True)]
        self.events = []
        self.stream = None
        self.lengths = []
        self.count = 0
        self.active = False

    def configure(self, stream, maximum):
        self.stream = stream
        self.events = [(self.torch.cuda.Event(enable_timing=True), self.torch.cuda.Event(enable_timing=True)) for _ in range(maximum)]
        for start, stop in self.events:
            start.record(stream)
            stop.record(stream)
        stream.synchronize()
        self.reset()

    def reset(self):
        self.count, self.active = 0, False
        self.lengths = []
        self.host_starts, self.host_ms = [], []

    def before(self, module, args, kwargs):
        if self.active or self.count >= len(self.events):
            raise RuntimeError('Unexpected nested/excess model forwards')
        check_stream(self.stream.cuda_stream, self.torch.cuda.current_stream().cuda_stream)
        tensor = kwargs.get('input_ids') if self.kind == 'qwen' else args[0]
        if tensor is None:
            raise RuntimeError('Missing actual forward input')
        self.lengths.append(int(tensor.shape[-1]) if self.kind == 'qwen' else list(tensor.shape))
        self.host_starts.append(time.perf_counter_ns())
        self.events[self.count][0].record(self.stream)
        self.active = True

    def after(self, module, args, kwargs, output):
        if not self.active:
            raise RuntimeError('Missing pre-hook')
        self.events[self.count][1].record(self.stream)
        self.host_ms.append((time.perf_counter_ns()-self.host_starts[-1])/1e6)
        self.active = False
        self.count += 1

    def elapsed(self):
        if self.active:
            raise RuntimeError('Incomplete forward')
        return [a.elapsed_time(b) for a,b in self.events[:self.count]]

    def close(self):
        for handle in self.handles:
            handle.remove()
        self.handles.clear()
        self.events.clear()
