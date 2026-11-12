# Restore real two-process GPU concurrency

Goal: Keep independent model Pods/queues and original model code while enabling real cross-process GPU coexecution. User requested resolving previously observed context alternation.

Design: same-UID host MPS daemon with private hostPath Unix socket mount into both Pods. No active-thread-percentage cap (avoid conflicting with Green SM resource limits); retain Green16/32 first. Prefer this minimal deployment change over combining independent services. If unsupported, preserve evidence and fall back to MPS without Green, then same-process Green only if needed.

1. Test immutable/idempotent MPS overlay (same absolute socket path, no accidental percentage env, UID compatibility).
2. Isolated MPS+Green native feature probe before changing Pods. Check membership and observed SM IDs.
3. Reuse finite Q10/Y300 diagnostic and warmup, both active only, new output root. Confirm both clients attach. Capture common CUDA/NVTX/context/GPU metric timeline. No timing ranking from profiled run.
4. Validate meaningful cross-model kernel overlap after eliminating separate-context descheduling, selected resource enforcement, all310 results; compare to captured no-MPS trace.
5. Finally restore baseline during diagnostics and shut down only own MPS service. Once valid, apply minimal persistent MPS overlay to original serving Pods, run native ROS health, capture membership and operational docs. Keep baseline branch/images/source immutable.
6. Test/lint/hash audit, local artifacts, record limits: concurrency is not guaranteed E2E improvement. Do not claim global SM exclusivity from separate process local partition metadata alone.
