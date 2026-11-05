# ACT 추론 지연 개선 — 진행 보고 (중간)

> **완료됨(2026-10-17)**: 이 중간 보고 이후 구현·검증을 마쳤다. 최종 결과는 [ACT_INFERENCE_OPTIMIZATION_REPORT.md](ACT_INFERENCE_OPTIMIZATION_REPORT.md).

- 시점: 2026-10-17 14:01
- 기준 계획: [ACT_INFERENCE_OPTIMIZATION_PLAN.md](ACT_INFERENCE_OPTIMIZATION_PLAN.md) (승인됨)
- 로봇·카메라: 미연결(USB 허브 분리 상태). 모터는 움직이지 않았다.
- 전원: 배터리, 저전력 모드 꺼짐.

## 1. 단계별 진행 상황

| 계획 단계 | 상태 |
|---|---|
| 계획서 저장(`docs/`, Downloads) | **완료** |
| 10-1 실기 `--timing` 계측(사용자) | **대기**: 로봇 연결 필요. 도구는 준비됨 |
| 10-2 Core ML 오프라인 수치·지연 검증 | **진행 중**: 시험 실행 통과, 본 실행 시작(약 40분 소요 예상) |
| 10-3 `--backend=coreml` 정식 적용 | **대기**: coremltools를 lock에 추가하는 승인이 필요하고, 10-2 결과가 먼저 나와야 함 |
| light 계측 모드(10-3의 일부) | **코드 작성 완료**, 시험은 본 측정이 끝난 뒤 실행(측정에 방해되지 않게) |

## 2. 이번에 한 일

### 2.1 검증 도구 `tools/act_backend_compare.py`(새 파일)

- 녹화 데이터셋(Hub `so101_ball_to_bowl_v1`)의 실제 프레임·관절을 **공식 `SyncInferenceEngine`**에 넣는다. backend별로 `predict_action_chunk`만 바꾼다.
- `numeric`: 같은 관측 시퀀스로 4단계를 비교한다.
  - ① chunk(정규화)
  - ② 앙상블 출력(정규화)
  - ③ 역정규화 목표(관절 °, gripper 0~100)
  - ④ 기록된 관측 위치 기준 `ensure_safe_goal_position` 적용 명령
- 기준 편차: MPS 대 MPS 반복, CPU 대 MPS.
- reset 검사: 에피소드 A → B → reset → A가 처음 A와 같은지 본다.
- `latency`: 한 backend로 N초 연속 추론한다. 추가 동기화는 없다. 분당 p50·p95·p99, 메모리·스왑, 발열 경고를 기록한다.
- Core ML 변환
  - 설정: FP32 명시, `CPU_AND_GPU`, mlprogram, macOS15 대상
  - 컴파일본은 `.tmp/act_eval/coreml_cache/<키>/model.mlmodelc`에 고정 저장한다. 키는 가중치·config sha256 + 버전 + 설정이다.
  - 연산 배치(1,493개 모두 GPU)를 기록한다.
- coremltools는 아직 `.tmp/coreml_pkgs`(격리)에서만 쓴다. **프로젝트 `.venv`와 lock은 바꾸지 않았다.**

### 2.2 시험 실행 결과(에피소드 0·15, 각 30틱 — 본 결과 아님)

| 비교 | ① chunk(정규화) 최대 | ③ 목표(관절 단위) 최대 | 완전히 같은 값 비율(③) |
|---|---|---|---|
| Core ML 대 MPS | 5.1e-6 | **1.5e-5** | 60% |
| MPS 대 MPS 반복 | 0 | 0 | 100% |
| CPU 대 MPS | 5.7e-6 | 4.6e-5 | 39% |
| Core ML 대 CPU | 6.8e-6 | 3.8e-5 | 47% |

- **정정**: 이전 보고의 "출력 차이 0"은 정확하지 않았다. 실제로는 아주 작은 차이(관절 단위 최대 1.5×10⁻⁵)가 있다.
- 이 차이는 PyTorch CPU 대 MPS 차이(4.6×10⁻⁵)보다 작다. 즉 FP32 구현 차이 수준이다.
- MPS는 같은 입력에 항상 같은 결과를 냈다(결정적).
- reset 검사는 MPS와 Core ML 모두 통과했다(차이 0).
- Core ML 컴파일본 로드 시간은 0.31초다. 1,493개 연산 모두 GPU에 배치됐다.
- 이 시험 구간(30틱)에서는 제한(`max_relative_target`)이 걸린 틱이 없었다. 더 긴 구간에서는 제한이 걸리는 것을 확인했고, 본 실행에서 비율을 기록한다.

### 2.3 light 계측 모드(코드만)

- `tools/rollout_with_view.sh --timing=light`를 추가했다.
  - 추가 동기화 없이 틱·관측·추론 전체·전송·모터만 기록한다(전체 루프 성능용).
  - `--timing`(=detail)은 기존처럼 단계별로 동기화하며 잰다(병목 귀속용).
  - 알 수 없는 모드는 실행 전에 거부한다.
- 오프라인 시험 2개를 추가했다(아직 실행 안 함).

## 3. 진행 중인 측정(본 실행)

순서: `numeric`(에피소드 0·15·35·55·75·95, 전체 3,073틱 × backend 4개) → MPS 10분 연속 → Core ML 10분 연속.

- 결과 위치: `.tmp/act_eval/numeric.json`, `latency_*.json`(Git 제외)
- 끝나면 수치·지연 결과를 [ROLLOUT_PERFORMANCE_REPORT.md](ROLLOUT_PERFORMANCE_REPORT.md)에 반영하고 이 보고서를 갱신한다.

## 4. 결정이 필요한 것

1. **coremltools를 macOS lock에 추가해도 되는지**: `--backend=coreml` 정식 적용의 전제다. 본 측정 결과를 보고 결정해도 된다.
2. 실기 계측: 로봇을 연결하면 기존 명령 앞에 `--timing`을 붙이고, 한 번은 `--no-mirror --timing`으로 30~60초씩 실행한다. 잔여 약 23 ms의 구성을 확인하는 데 필요하다.

## 5. 아직 하지 않은 것

- 실기 측정(모터 읽기·쓰기 시간, 실제 Hz, 제한 비율)
- Core ML 정식 적용(의존성·훅·래퍼 옵션)
- PTE: 계획 범위 밖, 보류
