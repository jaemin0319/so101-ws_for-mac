# ACT 추론 지연 개선 — 최종 보고 (Core ML backend)

- 작성: 2026-10-17. 기준 계획: [ACT_INFERENCE_OPTIMIZATION_PLAN.md](ACT_INFERENCE_OPTIMIZATION_PLAN.md)
- 환경: MacBook Air M4(GPU 8코어, RAM 16 GB), macOS 26.5.2, 배터리 전원(저전력 모드 꺼짐), 발열 경고 기록 없음, 스왑 사용 12.4~14.1 GB(높음)
- 모델: `act_so101_ball_to_bowl_v1/checkpoints/100000`, `n_action_steps=1`, `temporal_ensemble_coeff=0.01`(그대로 유지)
- 로봇·카메라: 미연결. 모든 결과는 **오프라인**(녹화 데이터 실제 프레임 재생)이다. **실기 성능·성공률은 미확인**이다.

## 1. 요약

| 항목 | 결과 |
|---|---|
| 구현 | **완료**. 선택형 Core ML backend(`--backend=coreml`)를 구현했다. 같은 가중치를 GPU FP32로 실행한다. `predict_action_chunk`만 교체하고, 전처리·앙상블 0.01·reset·후처리·위치 제한·카메라는 공식 경로 그대로다. 기본은 기존 MPS다 |
| 의존성 | `coremltools==9.0`을 macOS lock에 추가했다(사용자 승인). protobuf는 공식 lock과 같은 6.32.0이다. 기존 67개 패키지는 버전·해시 그대로다(공식 lock 대비 해시 67/67 일치) |
| 수치 동일성 | **통과**. Core ML 대 MPS의 최종 관절 명령 차이는 최대 5.3×10⁻⁵다. 이 값은 PyTorch CPU 대 MPS 차이(5.3~6.1×10⁻⁵)와 같은 수준이라 FP32 구현 차이 범위다. reset 독립성 OK |
| 속도(같은 발열 상태 교차 비교, 8분) | 틱 계산 p50 **77.0 → 52.8 ms(−31%)**, p95 **91.5 → 63.0 ms(−31%)**, p99 104.8 → 74.6 ms |
| 지속 실행(10분) | Core ML 평균 64~74 ms, p95 증가 +5.4%. MPS는 87~101 ms, +8.7%. 메모리(RSS) 증가 없음 |
| 새로 확인한 사실 | **지속 부하에서는 두 backend 모두 짧은 측정보다 크게 느려진다.** MPS 57.5 → 약 77~100 ms, Core ML 37.7 → 약 53~70 ms. 팬 없는 Air의 발열·전력 관리와 메모리 압력이 원인으로 추정되나 GPU 클럭은 관리자 권한이 필요해 확인하지 못했다 |
| 30 Hz | **오프라인 계산만으로도 미달**(지속 상태 Core ML p50 52.8 ms > 33.3 ms) |
| 시험 | `tools/verify_offline.py` **145/145**(이번 단계에서 8개 추가), `tools/verify_dataset.py` 19/19, `doctor --scope software` FAIL 0 |

## 2. 정정 사항(이전 보고 대비)

- **"Core ML 출력 차이 0"**: 정확하지 않았다. 실제로는 0이 아닌 아주 작은 차이(관절 단위 최대 약 5×10⁻⁵)가 있다. 이전 비교가 거칠었다.
- **"Core ML 적용 시 실기 20 Hz 안팎"**: 근거 없는 추정이었다.
  - 이전에는 실측 80 ms − 오프라인 57.5 ms = 23 ms를 모터 등 "잔여 시간"으로 봤다.
  - 그런데 지속 부하에서는 MPS 계산 자체가 약 77 ms다. 따라서 실기 80 ms는 대부분 **지속 상태의 계산 시간**일 가능성이 있다. 이 경우 모터 등 잔여 시간은 23 ms보다 작다.
  - 실기 단계별 계측(`--timing=light`) 전에는 확정하지 않는다.

## 3. 구현 내용

| 파일 | 내용 |
|---|---|
| `tools/act_coreml_export.py`(새 파일) | 체크포인트 → Core ML 변환을 한 번만 한다. 설정: FP32 명시, `CPU_AND_GPU`, mlprogram, macOS15. 결과는 `.cache/coreml/<키>/`(`model.mlmodelc`, `manifest.json`, `probes.npz`). 키 = 가중치·config sha256 + 입력 shape + coremltools·torch 버전 + 설정. 검증 입력 4개로 PyTorch CPU와 대조하고, 허용치(정규화 단위 1×10⁻⁴)를 넘으면 저장하지 않는다. 연산 배치를 기록한다 |
| `scripts/so101_act_coreml.py`(새 파일) | 런처 훅이다. `ACTPolicy.from_pretrained` 직후(로봇 연결 전) 다음을 한다. ① 장치가 cpu인지 확인 ② 키 재계산·manifest 대조 ③ 컴파일본 로드 ④ 워밍업 ⑤ 저장된 참조와 현재 가중치 둘 다로 출력 대조. 실패하면 **시작을 거부**하고, 실행 중 다른 backend로 조용히 넘어가지 않는다. 클래스 수준에서 감싸서 계측 훅도 Core ML 호출을 잰다 |
| `scripts/so101_launch.py` | `SO101_ACT_BACKEND=coreml`이면 위 훅을 설치한다. 순서: 카메라 미러 → Core ML → 계측 → 녹화 |
| `tools/rollout_with_view.sh` | `--backend=mps|coreml` 추가. coreml이면 `--device=cpu`를 필수로 하고 `--policy.device=cpu`를 자동으로 넣는다(공식 rollout은 실행 장치와 정책 설정 장치를 따로 둔다). `--timing=light|detail` 추가. 잘못된 값은 실행 전에 거부한다 |
| `scripts/so101_rollout_timing.py` | light 모드 추가(추가 동기화 없이 틱·관측·엔진·전송·모터만). detail은 기존 단계별 측정 |
| `tools/act_backend_compare.py`(새 파일) | 오프라인 검증 도구. `numeric`은 4단계 수치 비교·reset, `latency`는 지속 실행, `ab`는 같은 프로세스에서 교차 비교. Core ML은 배포 코드(export + attach)를 그대로 쓴다 |
| `lock/macos-arm64/pyproject.toml`, `uv.lock` | coremltools 9.0(+cattrs·pyaml), protobuf 6.32.0 제약 추가. `install_macos.sh --relock`으로 생성했고 lock 점검을 통과했다 |
| `tools/verify_offline.py` | 시험 8개 추가: light 계측 2, Core ML 변환·설치·대조·계측 연동·장치 거부·변환본 없음 거부·래퍼 옵션 6 |
| `docs/REFERENCES.md` | lock 값과 공식 lock 비교 결과 갱신 |

공식 LeRobot 파일, 체크포인트, config, 정규화 통계, 보정은 바꾸지 않았다.

## 4. 검증 결과

### 4.1 수치(같은 관측 시퀀스, 공식 `SyncInferenceEngine`)

- 데이터: Hub `so101_ball_to_bowl_v1` 에피소드 0·15·35·55·75·95, **3,073틱**
- 배포 코드 경로로 다시 확인: 에피소드 0·55, 1,213틱
- 단위: chunk·앙상블은 정규화 단위, 목표·제한 후 명령은 관절 °(gripper 0~100)

| 비교(최대 \|Δ\|) | chunk | 앙상블 | 역정규화 목표 | 제한 후 명령 |
|---|---|---|---|---|
| Core ML 대 MPS(6에피소드) | 1.6e-5 | 1.9e-6 | 5.3e-5 | 5.3e-5 |
| Core ML 대 MPS(배포 경로, 2에피소드) | 1.5e-5 | 1.4e-6 | 4.6e-5 | 4.6e-5 |
| 기준: CPU 대 MPS | 1.2~1.3e-5 | 1.9e-6 | 5.3~6.1e-5 | 5.3~6.1e-5 |
| 기준: MPS 대 MPS 반복 | 0 | 0 | 0 | 0 |

- **reset 검사**: 에피소드 A → B → reset → A가 처음 A와 완전히 같았다(MPS·Core ML 모두).
- **판정**: Core ML 차이가 같은 FP32 PyTorch의 CPU 대 MPS 차이 이내다. 기존 허용 제안(≤0.01°)보다 수백 배 작다. 제한·반올림이 차이를 가렸을 가능성은 단계별 비교(chunk부터)로 배제했다.
- **시작 검증**(실제 `lerobot-rollout` 경로): 저장 참조·현재 가중치 모두 |Δ| 2.3×10⁻⁶(허용 1×10⁻⁴). 연산 1,493개 모두 GPU. 컴파일본 로드 0.3~1.7 s. 그다음 로봇 연결 단계로 넘어감을 확인했다(존재하지 않는 포트로 시험, 하드웨어 미사용).

### 4.2 지연(틱 계산 = 텐서 변환~후처리 CPU 복사 완료, 추가 동기화 없음, 30 Hz 간격)

| 조건 | MPS | Core ML | 비고 |
|---|---|---|---|
| 짧은 측정(이전, 식은 상태) | 57.5 ms | 37.7 ms | 단계별 동기화 측정 |
| **교차 비교 1분 블록 × 4회 왕복(같은 상태)** | p50 77.0 / p95 91.5 / p99 104.8 | p50 **52.8** / p95 **63.0** / p99 **74.6** | **−31%** |
| 배포 경로 교차 비교 30초 × 2회 왕복 | p50 74.3 / p95 88.7 | p50 52.6 / p95 73.8 | 짧아서 p95 변동 큼(스왑 높음) |
| 10분 지속(분당 평균) | 86.8~101.2 ms, p95 증가 +8.7% | 64.5~73.7 ms, p95 증가 +5.4% | Core ML은 MPS 10분 직후 실행(더 불리한 조건) |
| 첫 틱들 | 59 → 73 ms(10틱 안에 상승) | 39 → 50 ms | 부하 시작 직후 빠르게 느려짐 |
| 메모리(RSS) | 1.43 GB 고정 | 1.58 GB 고정 | 증가 없음 |

- **채택 기준**(계획 7.2): p95 개선 ≥25%(−31% ✓), 10분 p95 증가 ≤10%(+5.4% ✓), 메모리 증가 없음(✓).
- **한계**
  - 배터리 전원이었고 스왑이 높은 상태에서 측정했다.
  - GPU 클럭·온도는 `powermetrics`(관리자 권한)가 필요해 측정하지 않았다.
  - "발열 경고 기록 없음"이 스로틀링이 없다는 뜻은 아니다.

## 5. 30 Hz 가능성

- 지속 상태 오프라인 계산만으로 Core ML p50 52.8 ms다. 여기에 모터 입출력이 더해진다. **30 Hz(33.3 ms)는 이 환경·의미 유지 최적화로는 어렵다.**
- 실기 기대 범위(추정, 미측정)
  - MPS 실측 약 80 ms(12.5 Hz) 중 계산이 약 77 ms라면, Core ML 적용 시 약 55~60 ms(약 17~18 Hz)가 된다.
  - 이 경우 작업 시간은 같은 동작 기준 약 1.3~1.4배 빨라진다.
  - 실기 `--timing=light`로 확인해야 한다.
- 30 Hz가 필요하면 별도 결정이 필요하다.
  - 추론·입출력 중첩 또는 주기 분리: 의미가 바뀌고 앙상블 시간 정렬을 새로 설계해야 한다.
  - 더 빠른 장치
  - 가벼운 모델(재학습)

## 6. 사용 방법(실기 비교, 사용자 수행)

- 이 체크포인트(`100000`)의 변환본은 이미 만들었다(`.cache/coreml/d52b23ddcd0f43d1bb76`). 다른 체크포인트는 먼저 변환한다.

  ```bash
  .venv/bin/python tools/act_coreml_export.py --checkpoint <pretrained_model 경로>
  ```

- **비교 조건(공정성)**
  - 전원 어댑터를 연결한다.
  - 다른 앱을 닫는다. 지금 스왑이 높으니 가능하면 재부팅 후 측정한다.
  - 두 backend를 번갈아 실행한다(MPS → Core ML → Core ML → MPS). 같은 위치와 시작 자세를 쓴다.
  - 래퍼 옵션(`--no-view`·`--timing=light`)을 두 backend에 같게 준다.

**A. 기준(MPS, 기존 동작)**
```bash
cd ~/so101-ws_for-mac
./tools/rollout_with_view.sh --no-view --timing=light \
--strategy.type=base \
--policy.path="$PWD/.cache/models/act_so101_ball_to_bowl_v1/checkpoints/100000/pretrained_model" \
--policy.n_action_steps=1 \
--policy.temporal_ensemble_coeff=0.01 \
--device=mps \
--robot.type=so101_follower \
--robot.port=/dev/cu.usbmodem5B901515041 \
--robot.id=so101_follower \
--robot.disable_torque_on_disconnect=true \
'--robot.max_relative_target={"shoulder_pan":15.0,"shoulder_lift":35.0,"elbow_flex":30.0,"wrist_flex":20.0,"wrist_roll":10.0,"gripper":25.0}' \
'--robot.cameras={"front":{"type":"opencv","index_or_path":1,"width":640,"height":480,"fps":30,"rotation":180},"wrist":{"type":"opencv","index_or_path":0,"width":640,"height":480,"fps":30}}' \
'--task=Pick up the ball and place it in the bowl' \
--fps=30 --play_sounds=false
```

**B. Core ML**: A와 다른 곳은 두 군데뿐이다. 첫 줄에 `--backend=coreml`을 넣고, `--device=mps`를 `--device=cpu`로 바꾼다.
```bash
cd ~/so101-ws_for-mac
./tools/rollout_with_view.sh --no-view --timing=light --backend=coreml \
--strategy.type=base \
--policy.path="$PWD/.cache/models/act_so101_ball_to_bowl_v1/checkpoints/100000/pretrained_model" \
--policy.n_action_steps=1 \
--policy.temporal_ensemble_coeff=0.01 \
--device=cpu \
--robot.type=so101_follower \
--robot.port=/dev/cu.usbmodem5B901515041 \
--robot.id=so101_follower \
--robot.disable_torque_on_disconnect=true \
'--robot.max_relative_target={"shoulder_pan":15.0,"shoulder_lift":35.0,"elbow_flex":30.0,"wrist_flex":20.0,"wrist_roll":10.0,"gripper":25.0}' \
'--robot.cameras={"front":{"type":"opencv","index_or_path":1,"width":640,"height":480,"fps":30,"rotation":180},"wrist":{"type":"opencv","index_or_path":0,"width":640,"height":480,"fps":30}}' \
'--task=Pick up the ball and place it in the bowl' \
--fps=30 --play_sounds=false
```

- 시작할 때 `[so101-coreml] Core ML backend 켜짐 … 검증 |Δ| …` 줄이 보여야 한다. 검증에 실패하면 로봇 연결 전에 멈춘다.
- 끝(Ctrl+C)에 `[so101-timing]` 요약이 출력되고 `logs/rollout-timing-*.json`에 저장된다. 실제 Hz·p95·제한 비율이 들어 있다.
- 병목을 단계별로 나눠 보려면 `--timing=light` 대신 `--timing`(detail)을 쓴다. 단계마다 동기화하므로 전체 Hz는 약간 달라질 수 있다.
- 이상 동작이 보이면 기존 절차대로 Ctrl+C 또는 팔로워 전원 차단을 한다. `--backend` 옵션을 빼면 바로 기준 경로로 돌아간다.

**기록 양식**(backend마다 공 위치 5곳 × 2회. 10회는 탐색 비교이며 성공률 입증이 아니다)

| backend | 위치 | 회차 | 결과(완전 성공/집기 실패/이동 중 낙하/그릇 투입 실패/시간 초과) | 시작→공 놓기(초) | 실제 Hz(평균/p95 틱 ms) | 제한 비율 | 비고 |
|---|---|---|---|---|---|---|---|
| mps | 1 | 1 | | | | | |
| coreml | 1 | 1 | | | | | |

**채택 판단**: 실패 분류가 늘지 않고 작업 시간과 틱 p95가 줄면 Core ML을 기본 후보로 삼는다. 성공률이 떨어지면 `--backend`를 빼고 원인을 조사한다.

## 7. 원복

- **실행만**: `--backend` 옵션을 빼면 기존 MPS 경로다. 변환본은 `rm -rf .cache/coreml`로 지운다.
- **의존성**
  1. `git checkout -- lock/macos-arm64/pyproject.toml lock/macos-arm64/uv.lock`
  2. `scripts/install_macos.sh`(lock에 없는 패키지는 sync가 제거한다)
- **코드**: 새 파일 3개(`scripts/so101_act_coreml.py`, `tools/act_coreml_export.py`, `tools/act_backend_compare.py`)를 지우고, 런처·래퍼·계측·verify_offline의 해당 블록을 제거한다(Git 변경으로 확인).

## 8. 남은 일

1. **실기 비교(사용자)**: 6절. MPS·Core ML 각각 `--timing=light` 기록과 성공·시간 기록.
2. 실기 결과로 잔여 시간(모터·미러·카메라)을 확정한다. 필요하면 다음 의미 유지 후보를 검토한다: 미러 끄기 효과, FastPrediction 힌트.
3. 의미가 바뀌는 후보(중첩·주기 분리, FP16, 제한 읽기 대체)와 PTE는 별도 결정 전까지 하지 않는다.

## 9. 측정 원본(Git 제외)

- 수치: `.tmp/act_eval/numeric.json`(6에피소드), `.tmp/act_eval/official/numeric.json`(배포 경로)
- 지연: `.tmp/act_eval/latency_mps_*.json`, `latency_coreml_*.json`, `ab_*.json`, `official/ab_*.json`
- 변환본: `.cache/coreml/d52b23ddcd0f43d1bb76/manifest.json`
