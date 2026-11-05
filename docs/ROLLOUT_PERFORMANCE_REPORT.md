# rollout 제어 루프 병목 분석 보고서 (ACT ball_to_bowl v1, 앙상블 0.01)

> **갱신(2026-10-17)**: 이 보고서의 일부 결론은 후속 검증으로 정정됐다. Core ML 출력 차이는 0이 아니라 관절 단위 최대 약 5×10⁻⁵(FP32 구현 차이 수준)이고, "Core ML 적용 시 20 Hz 안팎"은 근거 없는 추정이었다. 지속 부하에서는 계산 시간 자체가 크게 늘어난다(MPS 57→77~100 ms). 최신 결과는 [ACT_INFERENCE_OPTIMIZATION_REPORT.md](ACT_INFERENCE_OPTIMIZATION_REPORT.md).

- 작성: 2026-10-17, MacBook Air M4(GPU 8코어), macOS 26.5.2, 배터리 전원(저전력 모드 꺼짐), 발열 경고 기록 없음
- 대상: `act_so101_ball_to_bowl_v1/checkpoints/100000`, `n_action_steps=1`, `temporal_ensemble_coeff=0.01`, `--fps=30`, `--device=mps`
- 공식 코드: LeRobot v0.6.1 `7e241bd6`(설치본 `modeling_act.py`·`configuration_act.py`가 고정 SHA 원본과 동일함을 확인). 공식 파일은 수정하지 않음
- 사용자 실측 출발점: 실제 rollout이 목표 30 Hz 대비 약 12.5 Hz(틱당 약 80 ms)

## 1. 결론

| 항목 | 결과 |
|---|---|
| 가장 큰 병목 | **모델 추론(ACT 순전파)**: PyTorch-MPS 52.8 ms = 계산 시간(57.5 ms)의 92% |
| 모델 안에서 | ResNet18 백본(카메라 2대 × 480×640) 약 2/3, 트랜스포머 인코더(토큰 602개 × 4층) 약 1/4, 디코더 3% |
| 계산만으로 낼 수 있는 최대 주기 | 17.4 Hz(모터 입출력 제외). 이미 30 Hz(33.3 ms) 예산을 넘는다 |
| 실측 12.5 Hz와의 차이 약 23 ms | 모터 읽기 2번(관측 + `max_relative_target` 제한용)·쓰기 1번과 그 밖의 부하로 추정. **실기 계측 전이라 미확정** → 아래 `--timing`으로 측정 |
| PyTorch 안에서 값이 같은 개선 | 찾지 못함(아래 표: 메모리 배치·배치 계산·GPU 변환·fp16·torch.compile 모두 효과 없음 또는 실패) |
| 값이 같은 상태로 가능한 개선 | **Core ML(GPU, fp32)로 같은 가중치 실행: 추론 52.8 → 36.1 ms, 틱 계산 57.5 → 37.7 ms(최대 17.4 → 26.5 Hz)**, 최종 관절 명령 차이 없음(300틱) |
| 30 Hz 달성 여부 | Core ML을 써도 계산만 37.7 ms라 **30 Hz는 아직 불가**(모터 입출력 전). 목표 FPS 낮추기·PTE로 가리기는 하지 않음 |
| 적용 상태 | Core ML은 **실험만 함(프로젝트 환경 미변경)**. 새 의존성(coremltools)이라 적용 여부는 사용자 결정 필요 |

## 2. 측정 방법

- 로봇·카메라 미연결 상태(USB 허브 분리)여서 계산 부분은 **녹화 데이터 실제 프레임**(Hub `user/so101_ball_to_bowl_v1` 에피소드 0, 778프레임, 정책이 받는 회전 적용 영상과 관절값)으로 쟀다.
- 공식 `SyncInferenceEngine.get_action`과 같은 순서(텐서 변환 → 전처리 → `predict_action_chunk` → `ACTTemporalEnsembler.update` → 후처리)를 단계별로 나누고, 각 단계 끝에서 `torch.mps.synchronize()`로 GPU 비동기 실행을 기다려 시간을 귀속했다.
- 처음 20틱(워밍업, 첫 틱 273~521 ms)은 제외하고 280틱 평균. 같은 조건 반복 시 모델 52.7·52.9 ms로 재현됨.
- 카메라 `read_latest`는 이전 실측(실제 카메라 2대)에서 p99 0.2 ms 이하로 병목이 아님.
- 모터 입출력과 실제 루프 주기는 실기 계측 도구(4절)로 측정해야 한다(이번에는 미실시).

## 3. 단계별 시간(기준: 공식 경로, PyTorch-MPS)

| 단계 | 평균 ms | p95 ms |
|---|---|---|
| 텐서 변환·장치 이동(`prepare_observation_for_inference`) | 2.53 | 3.64 |
| 전처리(정규화) | 1.12 | 1.19 |
| **모델 추론(`predict_action_chunk`)** | **52.82** | 53.48 |
| 앙상블(`ACTTemporalEnsembler.update`) | 0.58 | 0.78 |
| 후처리(역정규화·CPU 복사) | 0.33 | 0.38 |
| 기타(관절 dict 변환 등) | 0.06 | 0.09 |
| **계산 합계** | **57.46** | 59.31 |

모델 내부(구간마다 동기화해 합계가 약간 커짐): 백본 1장 22.1 ms × 2 = 44.1 ms, 인코더 14.9 ms, 디코더 1.7 ms, 기타 5.1 ms(합 65.9 ms).

## 4. 시도한 개선

| 방법 | 모델 ms | 틱 계산 ms | 최대 Hz | 출력 차이(관절 명령) | 판정 |
|---|---|---|---|---|---|
| 기준(공식) | 52.8 | 57.5 | 17.4 | — | — |
| 백본 channels_last | 61.1 | 66.5 | 15.0 | 0 | 느려짐 |
| 이미지 uint8로 GPU 전송 후 변환 | 53.0 | 57.0 | 17.5 | 0 | 0.5 ms 개선(무의미) |
| 카메라 2장 백본 배치 계산 | 57.4 | 60.9 | 16.4 | 0 | 느려짐 |
| fp16 autocast | 59.4 | 62.8 | 15.9 | 최대 0.05 | 느려짐·값 변화 |
| 모델 전체 fp16 | — | — | — | — | MPS 행렬곱 dtype 단언 오류로 실행 불가 |
| torch.compile(MPS) | — | — | — | — | Metal 커널 버퍼 한도 오류로 실행 불가 |
| **Core ML GPU fp32**(같은 가중치) | **36.1** | **37.7** | **26.5** | **0**(300틱) | **유일하게 의미 있는 개선** |
| Core ML GPU fp16 | 32.1 | — | — | 정규화 단위 최대 0.015 | 값 변화, 이득 작음 |
| Core ML Neural Engine fp16 | 78.8 | — | — | 정규화 단위 최대 0.093 | ANE 컴파일 실패 → CPU로 대체되어 느림 |
| Core ML CPU만 fp32 | 64.8 | — | — | 1e-5 | 느림 |

- Core ML GPU fp32는 연산 1,493개가 모두 GPU에 배치됨을 Core ML 실행 계획으로 확인했다.
- 실험은 `.tmp/coreml_pkgs`(coremltools 9.0, protobuf, cattrs, pyaml)에만 설치해서 했다. `.venv`·lock은 바꾸지 않았다.

## 5. 30 Hz 예산 분석

- 30 Hz 한 틱 예산은 33.3 ms다.
- 기준 계산 57.5 ms는 예산의 1.7배다. 실측 80 ms에는 모터 입출력 등 약 23 ms가 더해진 것으로 보인다(미확정).
- Core ML을 적용해도 계산이 37.7 ms라 모터 입출력 전에 이미 예산을 넘는다. 실기 예상은 **20 Hz 안팎**(37.7 ms + 모터 입출력)인데, 이 값은 추정이며 측정하지 않았다.
- 30 Hz를 맞추려면 다음 중 하나가 더 필요하다. 모두 범위·방식이 바뀌므로 사용자 결정 사항이다.
  1. 더 빠른 추론 장치(예: NVIDIA GPU PC에서 실행)
  2. 추론과 모터 입출력을 겹치는 파이프라인 또는 비동기 추론. 명령이 1틱 늦어지는 등 제어 방식이 바뀐다. 공식 비동기 엔진(RTC)은 ACT를 지원하지 않는다.
  3. `max_relative_target` 제한용 추가 모터 읽기를 관측 읽기로 대체. 공식 안전 로직이 바뀌므로 실측 후 판단한다.
- 하지 않은 것: 목표 FPS 낮추기, PTE로 지연 가리기, 앙상블 계수·모델·해상도 변경.

## 6. 추가한 계측 도구(실기용)

`tools/rollout_with_view.sh --timing`을 쓰면 공식 rollout 프로세스 안에서 틱마다 다음 단계 시간을 기록한다. 값은 바꾸지 않는다.
- 관측(모터 읽기 / 카메라)
- 텐서 변환, 전처리, 모델, 앙상블, 후처리, 엔진 전체
- 명령 전송(제한용 모터 읽기 / 목표 쓰기)
- 실제 틱 간격과 `max_relative_target`로 잘린 비율

종료(Ctrl+C) 때 터미널에 요약이 나오고 `logs/rollout-timing-<시각>.json`·`.csv`에 저장된다. 처음 30틱은 워밍업으로 따로 표시한다. `--no-mirror`를 붙이면 카메라 영상 내보내기를 끄고 공식 rollout과 같은 부하로 비교할 수 있다.

```bash
cd ~/so101-ws_for-mac
./tools/rollout_with_view.sh --no-view --timing \
--strategy.type=base \
--policy.path="$PWD/.cache/models/act_so101_ball_to_bowl_v1/checkpoints/100000/pretrained_model" \
--policy.n_action_steps=1 \
--policy.temporal_ensemble_coeff=0.01 \
--device=mps \
--robot.type=so101_follower \
--robot.port=/dev/cu.usbmodem5B901515041 \
--robot.id=so101_follower \
--robot.disable_torque_on_disconnect=true \
'--robot.max_relative_target={"shoulder_pan": 15.0, "shoulder_lift": 35.0, "elbow_flex": 30.0, "wrist_flex": 20.0, "wrist_roll": 10.0, "gripper": 25.0}' \
'--robot.cameras={"front":{"type":"opencv","index_or_path":1,"width":640,"height":480,"fps":30,"rotation":180},"wrist":{"type":"opencv","index_or_path":0,"width":640,"height":480,"fps":30}}' \
'--task=Pick up the ball and place it in the bowl' \
--fps=30 \
--play_sounds=false
```

- 영상 내보내기까지 끈 비교는 첫 줄을 `./tools/rollout_with_view.sh --no-mirror --timing \`으로 바꾼다.
- 정책은 평소처럼 팔을 움직인다. 팔을 받치고 30~60초 돌린 뒤 Ctrl+C로 끝낸다.

검증(로봇 없이): 가짜 서보(pty) + 실제 `SO101Follower`(`max_relative_target` 포함) + 실제 `SyncInferenceEngine`으로 런처 아래에서 실행해 확인했다.
- 모든 단계가 기록되고, 제한 비율·Hz·CSV가 나온다.
- 계측을 켜고 보낸 목표값이 끄고 보낸 것과 같다.
- `--timing`·`--no-mirror` 옵션이 순서와 무관하게 전달된다.

`tools/verify_offline.py` **137/137 통과**(이번에 4개 추가).

## 7. 변경 파일

| 파일 | 내용 |
|---|---|
| `scripts/so101_rollout_timing.py`(새 파일) | 단계별 계측 훅(값 불변, 시간·횟수만 기록) |
| `scripts/so101_launch.py` | `SO101_ROLLOUT_TIMING`이 있으면 계측 훅 설치(카메라 미러 다음, 녹화 훅 전) |
| `tools/rollout_with_view.sh` | 래퍼 옵션 `--timing`, `--no-mirror` 추가(`--no-view`와 순서 무관) |
| `tools/verify_offline.py` | 계측 훅 종단 시험·옵션 전달 시험 추가, `--timing-child` 자식 모드 |

공식 LeRobot 파일, 체크포인트, config, 정규화 통계는 그대로다. 실험 스크립트와 결과는 `.tmp/perf/`(Git 제외)에 있다. Core ML 실험 패키지는 `.tmp/coreml_pkgs/`에 있다.

## 8. 아직 하지 않은 것

- 실제 로봇에서 `--timing` 측정. 모터 입출력 시간, 실제 Hz, 제한 비율, 미러 유무 비교가 여기서 확정된다.
- Core ML 실제 적용. coremltools를 macOS lock에 추가하고 relock해야 하므로 승인이 필요하다. 적용하면 시작 시 같은 체크포인트를 변환하고, MPS 결과와 대조해 차이가 기준을 넘으면 거부하는 방식으로 넣을 수 있다.
- PTE 구현. 이 성능 확인 뒤로 보류 중이다.

## 9. 원복 방법

- 계측은 `--timing`을 빼면 꺼지고, 기존 명령은 그대로 동작한다.
- 코드를 되돌리려면 `scripts/so101_rollout_timing.py`를 삭제하고 `scripts/so101_launch.py`·`tools/rollout_with_view.sh`·`tools/verify_offline.py`의 해당 블록을 제거한다. Git 변경으로 확인할 수 있다.
- Core ML 실험 흔적은 `rm -rf .tmp/coreml_pkgs .tmp/perf`로 지운다.
