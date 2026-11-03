# Spark 호스트 ROS 2 설치·검증

- 대상은 Spark(spark-e6d6 / Ubuntu24.04 ARM64)이며 로컬 PC의 Ubuntu20.04는 변경하지 않았다.
- 공식 ros2-apt-source1.3.0 및 Jazzy ros-base/std_msgs/sensor_msgs를 호스트에 설치했다.
- /opt/ros/jazzy/bin/ros2와 시스템 Python/rclpy로 실행한다. Docker wrapper가 아니다.
- avees의 새 대화형 shell에서 ROS 환경이 자동으로 source되고 Domain42/localhost discovery를 사용한다.
- 기존 Docker/모델 컨테이너·NVIDIA 드라이버·OS 릴리스·방화벽을 유지했다.

## 실제 검증

1. 호스트 ros2 node list로 qwen_node/yolo_node 확인.
2. 호스트 ros2 topic pub으로 프롬프트를 보내고 Qwen 실제 생성 결과 수신.
3. 호스트 rclpy로 bus.jpg CompressedImage를 보내고 YOLO 실제 검출 결과 수신.
4. 요청 ID/원본 stamp/frame_id로 본인 응답을 구분해 검사했다.
5. 새 대화형 shell의 ROS 경로/배포판/Domain을 확인했다.

native-host-test.json, nodes.txt, topics.txt, interactive-shell.txt, ros-packages.txt,
services-after.txt, containers.txt, kubernetes.txt에 증거를 저장했다.

호스트에 추가한 것은 ROS client SDK와 설정이며 새로운 모델 프로세스를 호스트에서 실행하지 않는다.
다른 PC와의 직접 LAN 통신/SROS2/새 GPU 최적화는 이번 범위가 아니다.
설치 script: ros2/install/spark-host.sh. 사용 방법: ros2/SPARK_HOST.md.
