# CUDA>=13.1 / MPS 정적 SM 분할 사전 검증

현재 상태(2026-11-10 02:31 KST): **사용자 승인에 따라 드라이버595.99.02 + 서명된 커널7.0.0-1025-nvidia 업그레이드·재부팅·SSH 재접속 확인 완료. CUDA Toolkit13.1.2 유지. SecureBoot 활성화. 최신 요청은 재부팅까지만이므로 MPS 정적 분할 실험은 여기서 멈춤. 두 모델 Deployment replicas0, 기존 사용자 MPS 서비스 disabled/inactive.**

아래는 재부팅 전 사전 검증 및 당시 승인 대기 기록이다. 새595환경의 정적 MPS 실행 결과는 아직 없다.

## 완료
- 이전35조건 MPS+Green sweep을 사용자 계획 변경으로 SIGTERM 중단. 해당 sweep은0개 완주 측정 조건이며 부분 요청/워밍업/중단 로그 보존. 기존 정상 서빙 template/ROS응답 복원PASS를 확인한 후 새 테스트 진행.
- CUDA Toolkit13.1.2를13.0과 나란히 설치. nvcc13.1.115, nativecudaRuntimeGetVersion13010. Toolkit 설치만으로 호스트 NVIDIA580.173.02/커널6.17.0-1031-nvidia는 변경되지 않음.
- native CUDA13.1 프로그램을 공식590.48.01 compat user-space로 실행: runtime13010/driverAPI13010, visibleSM48, 실제 커널값42PASS. host-native-no-mps-query.txt.
- 공식590.48.01 MPS control의 -S 지원 확인. GB10에서8chunk/16chunk 요청으로 서로 다른 partitionID 생성, 추가1chunk 요청은error915로거부. **생성 성공만으로 실제16/32SM 할당 성공이라고 주장하지 않음.**

## 미성공인 검증
- 기존580 kernel driver에 격리된590.48.01 user-space/MPS를 조합. 기존MPS/모델프로세스와 동시 실행한 probe 및 그들을 모두 중지한 isolatedprobe에서 CUDA client805 오류.
- 호스트에서도 CUDA13.1로 컴파일한 최소 kernelquery 프로그램을 같은 staticMPS에 연결하면cudaGetDeviceProperties부터805오류. Docker namespace/PyTorch만의 문제로 단정할 수 없음.
- 같은 조합의 일반MPS 대조군도805오류. 즉 이 호환 조합의 **MPS 연결 문제**이며, 정적 기능만의 미지원 또는 GB10전체 미지원이라고 일반화하지 않음.
- Qwen/YOLO 모델 실제 추론과 병렬성 측정은 아직 수행하지 못함. 성공 결과/성능 수치를 만들지 않음.

## 필요한 다음 결정
Spark는 SecureBoot가 활성화되어 있고 등록된 로컬DKMS MOK 키가 없다. 현재Ubuntu590패키지는595로전환되는 transitionalpackage다. 현재6.17커널용 signed595모듈은595.84에고정되어 repository595.99.02 user-space와맞지않는다.

검증된 설치 후보는 **595.99.02 + signed NVIDIA kernel7.0.0-1025** 조합. 새모듈은Canonical서명 확인. no-DKMS explicitpackage simulation은16new/16remove(기존580패키지교체). 이 변경과재부팅은 다른사용자로그인세션도끊으므로, 사용자에게 별도승인을요청했다. **아직드라이버/커널설치·재부팅·SecureBoot해제는하지않았다.** 승인후정상branch환경에서sameMPS-staticnativeprobe→모델동시추론→GPUtimeline 검증이필요하다.

## 보존/재현
원격루트 `/home/avees/cj-mps-static/20261110-v1`. 로컬 `20261110-v1/`에 OS/package snapshots, aptsimulations, outputs, nativeCUDA source, scripts를 보존한다. 대용량.deb/추출라이브러리는 원격packages/compat590/mps590/signed595에 남아 있다. 기존baseline이미지/소스/이전실험결과 불변, Gitpush없음.

- nativeprobe: `diagnostics/mps_static/native_probe.py`, config.py.
- 최소CUDA: `diagnostics/mps_static/native_query.cu`.
- 기존서빙복원: `diagnostics/mps_static/restore.sh`(ROS환경보존/실제응답검사).
- 원격복원상태: `verification/original-serving-restoration.json` 및 `logs/restore-original.log`.
- 전체142개 unit tests/Ruff/shellsyntax PASS.

공식근거: [CUDA13.1 MPS static](https://docs.nvidia.com/cuda/archive/13.1.0/cuda-programming-guide/04-special-topics/green-contexts.html), [NVIDIA MPS 고정SM분할](https://docs.nvidia.com/deploy/mps/latest/when-to-use-mps.html#static-sm-partitioning), [Spark에서590.48.01을 설치하는 공식Aerial문서](https://docs.nvidia.com/aerial/cuda-accelerated-ran/26-1/install_guide/installing_tools_spark.html), [forwardcompat지원/제약](https://docs.nvidia.com/deploy/cuda-compatibility/forward-compatibility.html).

2026-11-10 02:03 KST: 원래 MPS+Green 서빙 복원PASS, 두 Pod1/1Ready 및 실제 native ROS 요청/결과PASS. 원본MPS 서비스active. 테스트용590 daemon은 종료. Toolkit13.1만 추가 설치된 상태이며 호스트580 driver와6.17kernel은 변경되지 않았다.
