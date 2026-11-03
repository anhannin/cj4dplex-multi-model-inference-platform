# Standalone per-model FastAPI files

Current user scope: task1 only. Local ROS installation happened to finish before cancellation;
no activation profile, network or Spark firewall change was performed. Do not continue ROS work.

Target api/qwen_api.py and api/yolo_api.py, each independently runnable, no workload mode,
shared runtime/helper module or model Backend/infer wrapper. Each file owns FastAPI lifecycle,
raw bounded FIFO, one model-owning worker thread, stock generate()/predict(), and result Futures.
Request/response contracts, same-model serialization, independent model operation, capacity8,
normal queueing, overflow429 and disconnected-waiter skipping must stay unchanged.

1. Tests first against standalone file structure + mocked stock SDK calls; preserve existing tests.
2. Implement two files only for deployment code; use loop.call_soon_threadsafe for Future delivery.
3. Build new image tags, preserve old versions and current ROS containers. Test HTTP APIs with
   real GPU requests using temporary new containers; sufficient available RAM for duplicate test
   models, no performance improvement claims. Stop temporary APIs after validation, keep ROS active.
4. Save source hashes, responses, versions and review ZIP, with clear execution instructions.
