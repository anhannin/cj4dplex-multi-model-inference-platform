"""Hardware-context attribution can name MPS client PIDs, not the server PID."""

try:
    from diagnostics.kernel_overlap.analysis import union
except ModuleNotFoundError:
    from analysis import union


def associated_residence(intervals, server, clients):
    known = {server, *clients}
    return union([(a, b) for a, b, context, pid in intervals if pid in known])
