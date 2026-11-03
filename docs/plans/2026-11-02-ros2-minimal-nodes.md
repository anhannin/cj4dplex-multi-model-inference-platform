# Minimal ROS 2 nodes implementation plan

User-approved design: two standalone files, ros2/qwen_node.py and ros2/yolo_node.py.
No workload mode, shared node, Backend class, FastAPI dependency or custom inference wrapper.
Each file: load one stock model once in its own worker thread; subscription callback
only enqueues raw message + sequence/monotonic timestamp; bounded FIFO; worker converts
inputs, calls stock model.generate()/model.predict(), publishes JSON results.

- ROS 2 Jazzy in separate NVIDIA-parent images, matching Ubuntu24.04/ARM64/Python3.12.
- Qwen std_msgs/String accepts plain text or JSON {text,request_id,max_new_tokens};
  result std_msgs/String JSON. YOLO sensor_msgs/CompressedImage accepts JPEG/PNG;
  result std_msgs/String JSON echoes source header stamp/frame_id for correlation.
- Topics /qwen/request,/qwen/result,/yolo/request,/yolo/result; explicit FIFO (not latest-only).
- App queue default8; callback uses nonblocking put, logs queue-full drops. No middleware
  QoS guarantee of infinite buffering. Reliable KEEP_LAST32 on request/result topics.
- Each file independently owns queue, model and worker; no cross-model signals/locks.
- Keep original API/dev images and containers. For isolated ROS tests, stop only our two
  API containers after checking active requests, preserving them for later restart.
  Leave ROS nodes resident if tests succeed; document which services are running.
- ROS_DOMAIN_ID42 and localhost-only discovery; host networking + shared host IPC for
  same-host DDS. No host ROS installation, sudo or firewall change.
- Tests first: two-file AST contract, callbacks FIFO/overflow/no-inference with ROS
  stubs; actual Jazzy DDS + real model requests on Spark prove runtime behavior.
- Real tests: discovery/readiness, FIFO ordering/results, model load once, two clients,
  invalid inputs, Qwen-active/Yolo-result interval overlap, standard ros2 CLI publish.
- Store code locally and server; compare deployed/local SHA256 and publish a ZIP for review.
- No retry, recovery, Action/Service, external queue, model-source patches or K8s deployment.

Implemented and verified. Evidence: results/ros2/audit.json; review files: ros2/ and downloads/ros2_nodes.zip.
