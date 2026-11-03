# Spark ROS 2 Kubernetes serving

Qwen3.5-9B / YOLO26l each run in a single-replica Recreate Deployment.
This is a trusted single-node deployment, not a public multi-tenant service.
ROS Domain 42, localhost discovery, hostNetwork + hostIPC preserve native Spark clients.
No HTTP Service or Ingress is needed.

## GPU sharing (not an inference optimization)

The device plugin advertises two references to the same physical GPU as
`nvidia.com/gpu.shared`. Each Pod requests one. This does **not** reserve half
the SMs, memory, or execution time. No MPS, MIG, Green Context or priority is
configured. This sharing configuration must remain identical in later baseline
and optimized comparisons unless it is itself the controlled variable.

## Files / deployment order

JSON files are native Kubernetes manifests.
Do not apply this entire directory: the patch is not a resource and the probes
temporarily consume both GPU references.

1. Build `containers/qwen/Dockerfile.ros` as `cj-qwen-ros:9b-timing-v1`
   and YOLO equivalent as `cj-yolo-ros:26l-timing-v1`.
2. Export with `docker save`, import into K8s containerd namespace `k8s.io`:
   `sudo ctr --address /run/containerd-k8s/containerd.sock --namespace k8s.io images import --platform linux/arm64 models.tar`.
   Docker and Kubernetes have separate image stores. imagePullPolicy is Never.
3. Save existing device-plugin DaemonSet and Docker container configurations.
4. Apply namespace.json. Dry-run both model manifests.
5. Stop only `cj-qwen-ros` and `cj-yolo-ros`, preserving them for rollback.
6. Apply gpu-sharing.json; patch existing plugin:
   `kubectl -n kube-system patch ds nvidia-device-plugin-daemonset --type strategic --patch-file device-plugin-patch.json`.
7. Wait for plugin rollout; check node allocatable shared GPU is 2.
8. Apply probe-1.json and probe-2.json, compare their logged physical GPU UUID,
   then delete both probe Pods.
9. Apply qwen.json and yolo.json. Wait for both Deployments to become available.
10. Run native host CLI and UUID concurrency tests after sourcing Spark ROS env.

The manifests are intentionally pinned to the current Spark host and immutable
local image tags. Host weight directories are read-only. Writable caches are
per-Pod emptyDir and regenerated on replacement.

## Readiness and resource requests

The only Node code change is a ready-file marker: stale marker removed at startup,
PID written after model load + request subscription, removed before graceful stop.
Startup probe allows 600 seconds; readiness checks marker + live process.
Readiness is not a ROS traffic gate and is not a warmed performance measurement.
No liveness probe or additional recovery mechanism is introduced.

Qwen requests CPU 1 / RAM 24Gi, YOLO CPU 1 / RAM 4Gi. These are scheduler
reservations, not caps. They allow headroom over observed ~19GB Qwen GPU model
allocation and ~1.4Gi YOLO cgroup memory. GB10 uses unified memory; cgroup RSS
and GPU reporting do not establish a reliable isolated per-Pod VRAM budget.
No CPU quota or RAM hard limit is added to bias initial contention experiments.
Each Pod has GPU shared limit/request 1. The system remains vulnerable to memory
exhaustion and unbounded EOS generation; functional tests use bounded output.

## Native clients on Spark

```bash
source ~/.config/cj-ros2/spark-jazzy.bash
cd ~/cj-ros2/clients
python3 request_qwen.py --text "안녕하세요" --max-new-tokens 128
python3 request_yolo.py --image ~/cj-containers/assets/bus.jpg --output /tmp/k8s-bus.png
```

Output files must not already exist. Request topics remain /qwen/request,
/yolo/request; responses are /{model}/result/{request_id}. Each model has its own
FIFO capacity 8 and a single inference worker. The models do not coordinate.

## Rollback

First scale both Deployments to zero and wait until their Pods are deleted.
Restore the backed-up device-plugin Pod template (or rollout undo the single
sharing patch), wait for plugin readiness, then remove sharing ConfigMap.
Only after new model processes are gone:
`docker start cj-qwen-ros cj-yolo-ros`.
Do not run old and new subscribers concurrently. Recreate does not imply strict
at-most-one during manual deletion; avoid force deletion or simultaneous copies.

Recreation loses in-memory queued requests. No HA, persistence, SLO proof or
failure recovery experiment is claimed by this deployment.

## Latency instrumentation

Current timing-v1 images include request stage timings. See ../../benchmark/README.ko.md.
Older k8s-v1 images remain available for rollback; no model/kernel implementation changed.
