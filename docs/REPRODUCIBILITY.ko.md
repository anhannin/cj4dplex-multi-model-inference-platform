# 재현 안내: 보존 자료, CPU 감사, GPU 재실험의 경계

## 무엇을 재현하는가

서로 다른 환경/부하의 결과를 합치지 않는다.

| 구분 | 기준 자료 | 해석 |
|---|---|---|
| 원래 기준선 | `baseline/MANIFEST.json`, `baseline/FILES.sha256`, `results/latency-baseline/` | 2026-11-03 동결본. SM/MPS 최적화 없는 모델별 closed-loop C1, Qwen 최대128 출력/early EOS |
| 최종 native static burst | `results/static-eval/20261110-v1/` | native driver595.99.02, 실제 CUDART13.1, Green 없음. Qwen512입력/128고정출력10건 + YOLO300건, 7설정×5회 |
| 지속 부하 | `results/sustained/20261111-v2/` | 같은 새 환경, Qwen C1 + YOLO open-loop 8/15req/s, 120초 유입 후 drain, 40회. v1과 합산하지 않음 |
| 유휴 장애 | `results/fault-idle/20261110-v1/` | static8/40에서 GPU 동기화/빈 큐 확인 후 YOLO Node 전체 프로세스 SIGKILL 3회. 진행 중 GPU 장애 검증 아님 |
| 복원한 일반 서빙 | `k8s/mps-green/README.ko.md` 및 각 실험 restoration 증거 | 일반 MPS + Green Qwen16/YOLO32. static8/40을 운영에 영구 적용했다는 뜻 아님 |

새 환경에서도 frozen 모델 이미지는 유지하고 호스트 CUDA13.1 라이브러리를 read-only overlay했다. Torch build CUDA13.0과 실제 로드 CUDART13.1을 구별한다. 과거 compat/580/590 진단을 최종 native595 결과로 인용하지 않는다. 문서의 복원 상태는 저장된 관측이며 현재 클러스터 상태 보장은 아니다.

## CPU만으로 실행 가능한 검증

저장소 루트에서 실행한다. Python3.12 개발 환경이 필요하다. `requirements-dev.txt`는 현재 Pillow와Ruff만 포함한다. 사용하지 않는HTTP테스트/의존성은제거했으며 CUDA/ROS설치를대신하지않는다.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -p 'test_mps_static.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_fault_idle.py' -v
python3 scripts/check_submission.py --baseline-only
```

위 주요 CPU 테스트는 static6개·fault3개를 확인했다. 전체 suite에는 보관된 다른 연구 자료의 회귀도 포함하며 본문의 성능 표본에 합치지 않는다. 제출본 루트 README는 안내를 위해 갱신되며 원문은 `docs/history/baseline-root-README.md`에 보존한다. 따라서 작업 트리에 `sha256sum -c baseline/FILES.sha256`를 직접 적용하면 README·개발/빌드설정과승인된삭제경로의차이가발생하는것이의도된상태다. Git 저장소에서는 `python3 scripts/check_submission.py --baseline-only`로 원래 기준선677개 파일의 Git 객체를 검증한다. 정리된 Git 없는 제출본에서는 별도로 `python3 scripts/verify_export.py .`를 실행해 payload manifest를 검사한다. 두 명령은 환경에 따라 직접 선택하며 자동 fallback이 아니다. 소스 스냅샷 검사는 현재 원격 클러스터 상태를 증명하지 않는다. 작업 트리677개 파일이 모두 원본과 같다고 주장하지 않는다. 실제 GPU 성능, ROS 배포, 모델 가중치 존재를 증명하는 테스트는 아니다. 전체 테스트는 `.venv/bin/python -m unittest discover -s tests -v`이며, `tests/ros2/`의 실제 호스트 통합 스크립트는 별도로 취급한다.

## 원시 결과를 바꾸지 않는 오프라인 재집계

분석기는 `analysis/`, `verification/`에 출력하므로 **먼저 임시 복사본을 만든다**. 결과별 `src/`는 당시 모은 helper 파일명까지 보존한 실행 묶음이다. 아래 명령은 ROS/GPU/클러스터 없이 검증했다.

```bash
T=$(mktemp -d)
for run in static-eval/20261110-v1 fault-idle/20261110-v1; do
  mkdir -p "$T/$(dirname "$run")"
  cp -a "results/$run" "$T/$run"
done
.venv/bin/python "$T/static-eval/20261110-v1/src/analyze_eval.py" \
  --root "$T/static-eval/20261110-v1"
.venv/bin/python "$T/fault-idle/20261110-v1/src/analyze.py" \
  --root "$T/fault-idle/20261110-v1"
```

확인한 출력: static 감사12,005요청(워밍업 포함), fault restoration PASS/전체결과28개. static timed 본측정은10,850개(35×310)이며 감사 수와 구별한다. 본문 밖 연구 자료의 재집계는 실험 인덱스의 보관 자료를 참고한다. 재집계는 저장된 원시 관측의 일관성 확인이지 새 실험이 아니다.

## GPU 재실험 전 필요한 호스트 준비

이 저장소는 임의 PC에서 한 명령으로 GPU 실험 전체를 구축하는 배포 제품이 아니다. 다음 준비/검증이 별도로 필요하다.

1. ARM64 DGX Spark GB10/48SM, 기록된 kernel/driver595/Toolkit13.1 환경 및 NVIDIA runtime을 확인한다. 드라이버 변경은 단순 재집계가 아니며 기존 워크로드에 영향을 준다.
2. `baseline/README.ko.md`의 외부 `model-images.tar` 해시와 `MANIFEST.json` 이미지 ID를 확인한다. 약19.8GB archive, 모델 가중치, 입력 이미지, runtime 캐시는 Git만으로 확보되지 않는다. 모델 revision/입력 해시와 hostPath를 실제 자산에 맞춘다.
3. ROS2 Jazzy, localhost/domain 설정, 별도 Kubernetes containerd 및 NVIDIA device-plugin을 `k8s/README.ko.md`, `k8s/serving/README.md`에 맞춰 준비한다. `gpu.shared=2`는 접근권/스케줄링 슬롯이지 SM 하드웨어 분할이 아니다.
4. 실험마다 새 runtime 루트, `src/` helper 묶음, baseline/backup Deployment JSON, workload/schedule, 로그/verification 경로를 준비한다. 기존 결과 경로를 재사용하지 않는다.
5. MPS socket/UID1000, native runtime 및 실제 SM 수/partition membership을 검증한다. 원래 Deployment와 일반 MPS+Green 복원 절차를 준비한 뒤에만 실험을 시작한다.

### 실행 코드와 호스트 의존성

- `diagnostics/mps_static/`: native probe, partition 계획, eval/profile runner, 분석 코드. `prepare_final_profile.sh`는 `$HOME/cj-static-eval/...`, `$HOME/cj-static-profile/...`의 기존 `src`와 백업을 복사한다. `upgrade_*`는 드라이버/환경 변경 도구이지 필수 자동 실행 단계가 아니다.
- `diagnostics/sustained/controller.py`: `base_runner`, `eval_runner`, `control_runner`, `live_logs`, `plan`, `protocol`을 호스트 묶음에서 import하고 `GREEN_BURST_ROOT`가 helper의 ROOT와 같은지 검사한다. `src/sustained_client.py` 등 재명명한 파일도 필요하다.
- `diagnostics/fault_idle/controller.py`, `resource_supervisor.py`: 실제 Kubernetes/MPS/host PID와 idle barrier에 의존한다. PID만 골라 수동 kill하는 방식으로 대체하면 안전 검증이 사라진다.

따라서 이 세 디렉터리에 `python controller.py`만 실행하라는 이식형 명령은 제공하지 않는다. 저장된 `results/<실험>/<run>/src/`, `metadata/`, `backup/`, `verification/`와 실제 호스트 경로를 대조해 새 묶음을 준비해야 한다. API 인증정보/kubeconfig/SSH 키는 저장소에 넣지 않는다. 이 안내 작성 중 GPU 작업·원격 배포·드라이버 변경은 실행하지 않았다.

## 보존 원칙과 남은 제약

`baseline/`, 원시 JSONL/로그, 이전 실패·수정 전 실험을 덮어쓰지 않는다. 원래 기준선 복구와 새595환경 성능 재측정은 별도 작업이다. 가중치/외부 이미지 archive와 전용 호스트 없이 완전한 실험 재현은 불가능하며, 통계적 동등성·장기 가용성·보안 격리·in-flight GPU fault tolerance는 입증 범위 밖이다.

## 실행기 제거 이후 재현

baseline측정기·최적화본체·필수진단helper·결과src사본은유지했다. 삭제된PID대기wrapper대신[직접명령](REPRO_COMMANDS.ko.md)을사용한다. `check_submission.py`는동결Git객체677개와승인삭제/변경SHA,보존소스145개SHA를별도로검사한다. 실행파일 정리 당시162개중HTTP전용24개는구현과함께제거하고정리경계5개를추가했다. 이후표·그림·동결참조·제출구조의회귀를보강했다. 현재실행결과는 `docs/submission/validation-summary.json`을따른다.

본문에서 제외한 기타 실험 코드와 원시 자료도 보존한다. 새 전체 테스트 수를 과거149/143/144 기록과 혼동하지 않는다. main 정리에서는 실제 GPU·Kubernetes 재배포 없이 CPU·정적검사와 기존 raw 사본 재집계를 수행한다.

## 배포 모드와 읽는 순서

[실험 인덱스](EXPERIMENT_INDEX.ko.md) → [배포 모드](DEPLOYMENT_MODES.ko.md) → [구현 범위](IMPLEMENTATION.ko.md)를 함께 읽는다. `main`은 기존 README를 보존하고 `baseline`의 최신 코드·삭제내역·근거를 통합한 제출 경로다. 동결 원본은 브랜치 이름이 아니라 태그 `baseline-frozen-20261103`와 commit `6a99fdaf26307e2f0b41f708478fdec3fcfad7ac`으로 식별한다.
