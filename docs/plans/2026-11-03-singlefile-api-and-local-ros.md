LATEST USER OVERRIDE: task2 cancelled; task1 only. No further local ROS or network work.

# Single-file model APIs and native local ROS connection

User-approved tasks: model-specific standalone FastAPI files, and a local (not Docker)
ROS2 client installation capable of real communication with Spark ROS containers.

1. Preserve old serving modules/containers and their tests as regression baseline.
2. Create fastapi/qwen_api.py and fastapi/yolo_api.py: each owns startup, raw FIFO,
   worker thread, direct stock SDK calls, request/result handling. No shared mode,
   Backend classes, imports of old serving modules or project-specific helpers.
3. Lock old HTTP contracts, same-model FIFO, full-queue behavior, real-TCP disconnect
   handling, and cross-model independence with tests before implementation.
4. Local OS is Ubuntu20.04/glibc2.31; use isolated user-space RoboStack Jazzy/Pixi,
   matching Spark Jazzy without OS upgrade, EOL Foxy or Docker client. Keep lockfile.
5. Use domain42, explicit peer IPs192.168.24.169 and192.168.24.204; only narrowly scoped
   DDS rules on Spark UFW if needed. Preserve all SSH/firewall/driver settings.
6. Verify local ROS CLI discovery, actual prompt result and JPEG detection result
   across LAN; no fabricated relay or HTTP bridge. Provide activation and clients.
7. Build API images with new tags; real HTTP smoke test then keep ROS as current
   two-model resident service (do not silently double resident models long-term).
8. Save deployment versions, source hashes, actual test outputs and review ZIP.
