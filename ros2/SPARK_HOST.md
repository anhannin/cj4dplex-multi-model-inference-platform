# Spark 호스트 ROS 요청 (현재 UUID 프로토콜)

호스트 OS에 ROS 2 Jazzy가 설치돼 있으므로 Docker exec 없이 실행한다.
새 SSH 터미널에는 자동 적용되며, 기존 터미널은 다음을 실행한다:

```bash
source ~/.config/cj-ros2/spark-jazzy.bash
cd ~/cj-ros2/clients
python3 request_qwen.py --text "질문 내용"
python3 request_yolo.py --image ~/cj-containers/assets/bus.jpg --output ~/bus_result.png
```

실행 프로세스마다 UUID를 생성하고 자기 결과를 받아 출력/파일 저장 후 종료한다.
별도 ros2 topic echo는 필요 없다. 기존 공통 result 토픽에는 더 이상 결과를 보내지 않는다.
[클라이언트 상세](../clients/README.md), [서버 구조·버전 변경](README.md).

환경은 `/opt/ros/jazzy/setup.bash`, ROS_DOMAIN_ID42, LOCALHOST discovery,
RMW_IMPLEMENTATION=rmw_fastrtps_cpp다. 이 구성은 Spark 내부용이며 별도 PC와의 LAN 통신을 뜻하지 않는다.
기존 v1 호스트 시험은 `results/spark-host-ros/`에 기록돼 있고 현재 검증은 `results/uuid-channels/`다.
