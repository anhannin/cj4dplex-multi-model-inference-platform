# 사용 모델·OSS·외부 서비스·AI 도구 고지

확인일: 2026-11-12. 이 문서는 출처 및 확인 상태를 기록하며 법률 자문이나 배포 허가서가 아니다.

## 모델과 입력 데이터

| 항목 | 실제 사용 식별자·출처 | 이용 조건·확인 상태 |
|---|---|---|
| Qwen3.5-9B | `Qwen/Qwen3.5-9B`, snapshot `c202236235762e1c871ad0ccb60c8ee5ba337b9a`; 텍스트 생성에 사용 | 해당 snapshot의 [LICENSE](https://huggingface.co/Qwen/Qwen3.5-9B/blob/c202236235762e1c871ad0ccb60c8ee5ba337b9a/LICENSE)에서 Apache-2.0 확인. 재배포 시 라이선스·관련 NOTICE 유지 등 조건 검토 필요. |
| YOLO26l | [공식 v8.4.0 release의 yolo26l.pt](https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26l.pt); 로컬 해시 근거 `results/latency-baseline/evidence/yolo-weights.sha256` | [Ultralytics 공식 라이선스 안내](https://www.ultralytics.com/license)에 따르면 AGPL-3.0 또는 별도 Enterprise 계약. 비공개 저장소 제출만으로 의무가 충족되었다고 판단하지 않는다. 전체 결합 저작물·네트워크 사용·가중치 배포 범위를 검토하고 필요한 권한을 확보하기 전 공개/이미지 재배포는 보류. 상업 사용이 일률적으로 금지된다는 뜻은 아니다. |
| 스모크 입력 이미지 | [bus.jpg](https://ultralytics.com/images/bus.jpg), [zidane.jpg](https://ultralytics.com/images/zidane.jpg) | 다운로드 출처만 확인. 개별 사진의 저작권자·초상권·재배포 허가는 미확정. [assets 저장소 LICENSE](https://github.com/ultralytics/assets/blob/main/LICENSE)만으로 개별 사진의 권리까지 확정하지 않는다. 제출 이미지/영상/컨테이너 포함 전 권리 확인 또는 직접 촬영·허가된 입력으로 교체. 정확도 평가 데이터셋으로 사용하지 않음. |

가중치는 Git에 포함하지 않는 구성이며 기준선 manifest도 미포함을 기록한다. 제출 패키징 도구의 사진·가중치 제외 정책도 실제 출력물에서 검증해야 하며, 코드 이미지의 재배포 권리까지 자동 해결하지 않는다. 실제 배포 직전에는 이미지 layer와 제출 아카이브를 별도로 검사해야 한다.

## 주요 OSS 및 런타임

버전 근거는 `containers/{common,qwen,yolo}/Dockerfile`, `requirements-api.txt`, `baseline/MANIFEST.json` 및 각 실행의 환경 기록이다. 아래는 주요 구성요소 목록이지 모든 전이 의존성의 완전한 SBOM은 아니다.

| 구성요소 | 저장소에 고정/기록된 버전 | 공식 조건/출처 |
|---|---|---|
| NVIDIA PyTorch 기반 컨테이너 | `nvcr.io/nvidia/pytorch:25.09-py3`, digest `sha256:f3b4a33fd60d5e0358287bb44d57e91eda45e8f1681fef1bfd6c969371417130` | [NVIDIA 라이선스 개요](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-software-licensing-overview-and-faq/) 및 해당 제품 약관 적용. CUDA 등 NVIDIA 구성요소와 제3자 OSS 조건은 구분한다. 접근 가능/다운로드 가능하다고 이미지 전체의 무제한 재배포를 뜻하지 않는다. |
| PyTorch / CUDA | 기반 이미지 PyTorch `2.9.0a0`, build CUDA `13.0`; 별도 실험의 CUDA runtime `13.1` overlay는 구분 | [PyTorch LICENSE](https://github.com/pytorch/pytorch/blob/main/LICENSE): BSD 계열 본문 및 포함된 제3자 고지. NVIDIA 배포판의 개별 패치·구성요소 고지도 보존. |
| Transformers | `5.22.1` | [해당 태그 LICENSE](https://github.com/huggingface/transformers/blob/v5.22.1/LICENSE), Apache-2.0 |
| flash-linear-attention / fla-core | 각각 `0.4.2` | [상위 프로젝트 LICENSE](https://github.com/fla-org/flash-linear-attention/blob/main/LICENSE), MIT 확인. 배포할 정확한 wheel의 고지와 전이 의존성은 별도 확인 필요. |
| causal-conv1d | `1.7.0`, CUDA 13 / torch 2.9 / CPython 3.12 / aarch64 wheel | [프로젝트 LICENSE](https://github.com/Dao-AILab/causal-conv1d/blob/main/LICENSE), BSD-3-Clause; 정확한 release wheel 고지 확인 필요. |
| Ultralytics | `ultralytics-opencv-headless==8.4.198` | [공식 라이선스](https://www.ultralytics.com/license), 위 YOLO 조건과 동일하게 결합/배포 범위 검토 |
| ROS 2 | Jazzy; 패키지별 버전은 실행 환경 기록 참조 | 예: [rclpy Jazzy LICENSE](https://github.com/ros2/rclpy/blob/jazzy/LICENSE), Apache-2.0. ROS 2 전체를 단일 라이선스로 간주하지 않으며 DDS·기타 패키지는 개별 고지 확인. |
| FastAPI / Uvicorn (과거탐색,활성구현제거) | `0.162.0` / `0.54.0` | [FastAPI](https://github.com/fastapi/fastapi/blob/master/LICENSE) MIT / [Uvicorn](https://github.com/Kludex/uvicorn/blob/main/LICENSE.md) BSD-3-Clause. 버전별 배포물 확인 필요. |

호스트는 kernel `7.0.0-1025`, NVIDIA driver `595.99.02`, CUDA Toolkit `13.1.2`로 업그레이드하고 재부팅 후 검증했다. 반면 동결한 컨테이너 이미지와 PyTorch의 compile CUDA `13.0`은 보존했다. CUDA runtime `13.1` overlay는 별도 적용·관측 항목이며 호스트 Toolkit, PyTorch compile CUDA, 실제 CUDART를 같은 버전으로 간주하지 않는다. 완전한 배포 검토에는 실제 이미지의 `/opt/requirements-resolved.txt`, 패키지 LICENSE/NOTICE, OS 패키지 및 NVIDIA 제품 약관까지 필요하다. 기존 개발 이미지나 Docker-save 백업의 존재는 외부 제출 권리 및 수신자 접근성 검증을 대체하지 않는다.

## 외부 서비스와 AI 도구

- 추론은 로컬 모델 가중치 기반이다. 현재활성요청경로는로컬ROS2이고과거FastAPI코드는제거했으며, 외부 유료 LLM 추론 API를 필수 경로로 사용하지 않는다.
- Hugging Face·GitHub·NVIDIA NGC·패키지 저장소는 모델/패키지/이미지 취득 출처다. 재현 시 네트워크·인증·이용약관에 제약이 있을 수 있다.
- Codex AI Coding Assistant를 코드, 테스트, 실험 보조 스크립트, 결과 정리 및 문서 작성·수정에 사용했다. 제출 준비 중 공식 라이선스 웹 문서를 확인했다. AI가 작성한 내용 자체를 실행 증거나 법적 허가로 취급하지 않는다.
- 프로젝트별 구현·수정 범위는 과거`api/`·`serving/`(현재제거)와 `ros2/`, `clients/`, `scripts/`, `benchmark/`, `optimization/`, `diagnostics/`, `k8s/`, `tests/` 및 문서/실험 설정이다. 이는 지원자 작업공간에서 AI 보조로 구현·수정한 통합 코드와 컴파일러·GPU 커널 진단을 포함한다는 의미이며 전부 사람이 단독 작성했다는 주장이 아니다.
- Qwen/YOLO 모델 구조·사전학습 가중치, PyTorch/Transformers/FLA/ROS 2/Kubernetes/CUDA 엔진 자체를 신규 개발했다고 주장하지 않는다. 복구 관련 스크립트와 실험은 해당 범위의 증거이며 독자적인 범용 HA 플랫폼 구현을 의미하지 않는다.

## 제출 전 남은 권리 확인

1. YOLO 결합·비공개 제출·컨테이너 배포 방식에 대한 AGPL 의무 또는 Enterprise 권한 확인.
2. 샘플 사진의 개별 이용·재배포 권리 확인 또는 대체.
3. 실제 배포 이미지의 NVIDIA 약관, OSS LICENSE/NOTICE, 전이 의존성 및 전체 SBOM 확인.
4. 프로젝트 자체 코드의 공개/이용 허락 범위 결정. 이 고지 문서가 프로젝트 전체에 일괄 라이선스를 부여하지는 않는다.
