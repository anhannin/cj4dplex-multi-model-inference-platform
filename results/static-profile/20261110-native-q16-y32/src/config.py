"""Strict static-partition selection; never substitute percentage-based provisioning."""

import re


def parse_partition(output):
    if "Failed" in output or "Invalid" in output:
        raise ValueError(output)
    matches = re.findall(r"GPU-[\w-]+/[A-Za-z0-9+/=_-]+", output)
    if len(matches) != 1:
        raise ValueError("Expected exactly one created partition ID")
    return matches[0]


def static_env(pipe, partition, compat):
    if not partition.startswith("GPU-") or "/" not in partition:
        raise ValueError("Opaque GPU/partition ID required")
    return {
        "CUDA_MPS_PIPE_DIRECTORY": pipe,
        "CUDA_MPS_SM_PARTITION": partition,
        "LD_LIBRARY_PATH": compat
        + ":/usr/local/cuda-13.1/lib64:/usr/local/cuda/lib64:/usr/local/nvidia/lib64",
    }
