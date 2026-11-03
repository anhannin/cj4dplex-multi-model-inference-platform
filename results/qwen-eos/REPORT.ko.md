# Qwen 출력 제한 변경

- ROS Qwen 서버/클라이언트의 임의512 허용 상한을 제거했다.
- 요청 옵션을 생략하면 기본128을 전송하지 않으며 서버 parameter0은 EOS/남은 모델 문맥까지 생성한다.
- HF generate에 길이 인자를 단순 생략하면 라이브러리 기본 max_length가 작을 수 있어, 실제 config의 max_position_embeddings에서 입력 토큰 수를 뺀 값을 상한으로 전달했다.
- 모델 config의 문맥 한계262144토큰은 유지한다. 입력의 기존2048토큰/32768문자 제한도 유지한다.
- 명시4096 등 큰 양의 정수를 허용하되 남은 문맥을 넘으면 오류를 반환한다.
- finish_reason(eos/length), generation_mode, effective_max_new_tokens, context_limit을 결과에 기록한다.

## 실제 검증

기본 옵션으로 '롤토체스가 뭐야'를 요청해420토큰 생성 후 EOS로 정상 종료했다.
기존128토큰 상한으로 끊긴 것과 달리 EOS 종료를 실제 응답 metadata로 확인했다.
명시4096 상한을 요청한 짧은 인사도 허용돼5토큰 생성 후 EOS로 종료했다.
Qwen 컨테이너만 재배포하고 YOLO는 유지했다. CPU 테스트51개 및 Ruff/Bash 검사 통과.

완전 무한 생성이나 답변의 사실 정확도를 보장하지 않는다. EOS 미발생 시 긴 작업/메모리 부족과 Queue 대기 증가가 가능하다.
기본 클라이언트 timeout300초는 별도이며 요청자가 나가도 실행 중 GPU 추론은 자동 취소되지 않는다.
