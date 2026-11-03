# Separate model containers implementation plan

Goal: build Qwen3.5-9B and YOLO26l ARM64 images from an official NVIDIA base,
with unmodified upstream model implementations and validated GPU acceleration.
User approved separate containers and dependency installation, not Kubernetes installation.

Architecture: public NVIDIA PyTorch CUDA13.0 base pinned by digest; isolated dependency
sets in separate images. No host driver/OS changes. Stock Hugging Face generate and
Ultralytics predict; test harness code is ours, not a patch to upstream packages.

1. Verify host driver, ARM64, SM121 and base CUDA/compiler compatibility using official docs.
2. Add tests for fail-closed acceleration validation before implementing it.
3. Build Qwen with pinned Transformers, FLA and upstream causal-conv1d wheel matching
   aarch64, CPython3.12, CUDA13, torch2.9 ABI. Use upstream source build only if needed.
4. Build YOLO with pinned Ultralytics and dependencies, retain NVIDIA torch/torchvision.
5. Numerically test causal conv kernels; require all four Qwen acceleration functions
   to resolve to external library symbols. Profile real generation for kernel execution.
   Reject reference-fallback logs, missing symbols or GPU runtime errors.
6. Run stock model examples and standalone/co-resident/concurrent timed trials with
   separate GPU containers and identical settings. Do not suppress errors/warnings.
7. Save digests, dependency inventories, source integrity checks, raw measurements,
   logs and reproduction instructions. Verify clean shutdown of our containers.

Validation excludes production readiness, Kubernetes GPU sharing configuration,
model accuracy and final SLO. No monkeypatching, source edits or fallback on failure.
