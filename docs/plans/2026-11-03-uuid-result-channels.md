# ROS request-specific result channels

User approved Topic approach, no Service/Action.
- Fixed String JSON requests /qwen/request and /yolo/request.
- request_id strictly r_ plus32 lowercase hex digits; response /MODEL/result/ID.
- Qwen text; YOLO JSON image_base64 (up to10MiB decoded JPEG/PNG,16M pixels).
  This intentionally replaces YOLO CompressedImage input; no UUID in frame_id.
- Each Node stays one file, callback only FIFO enqueue, one model/worker, stock SDK calls unchanged.
- Result publisher per request, bounded discovery wait, reliable ACK wait and destroy in finally.
  No shared results, arbitrary reply paths, wildcard subscriptions, publisher cache/leaks.
- Native host clients create subscriber before request, match server, publish once, wait with
  total timeout, check response ID, print text or draw/save detection image then exit.
- Keep old HTTP clients at clients/http and old ROS images/containers for rollback.
- Tests first: extracted result publisher lifecycle, rejection, callback contracts, client
  unique ID/filter/timeout/image output; actual host concurrent processes prove no mixups.
- Save source hashes, raw outputs, publisher cleanup evidence, ZIP. Update user docs.
