# SO101 ACT 추론 지연 원인 점검 및 개선 계획

> 작성: 2026-10-17, Plan 모드. 읽기 전용 확인만 했다. 설치·변환·벤치마크·로봇 연결은 하지 않았다.
> **저장 경로**: Plan 모드에서는 이 계획 파일만 쓸 수 있다. 승인 후 첫 작업으로 같은 내용을 `~/so101-ws_for-mac/docs/ACT_INFERENCE_OPTIMIZATION_PLAN.md`에 저장한다. 같은 이름 파일은 없음을 확인했다. 이 파일의 이전 내용(macOS 지원 계획)은 이미 `docs/so101_macos_plan.md`로 보존되어 있다.
> README와 CURRENT_STATE의 구현 완료 상태는 이 계획만으로 바꾸지 않는다.

## Context

- **현상**: 학습 시연과 같은 동작 설정(ACT ball_to_bowl v1 `100000`, `n_action_steps=1`, `temporal_ensemble_coeff=0.01`)으로 rollout하면 목표 30 Hz 대비 약 12.5 Hz(사용자 실측 경고)로 돈다.
- **작업 시간에 미치는 영향**: 이 설정에서는 정책이 **틱마다 1스텝**씩 진행한다.
  - 근거: `ACTPolicy.select_action`이 매 틱 `predict_action_chunk` 후 `ACTTemporalEnsembler.update`로 한 칸을 꺼낸다([modeling_act.py:107-112](.venv/lib/python3.12/site-packages/lerobot/policies/act/modeling_act.py#L107)).
  - 그래서 실제 작업 완료 시간은 대략 **(30 / 실제 Hz)배**로 늘어난다(12.5 Hz면 약 2.4배, 추정).
  - 즉 루프 주기를 올리는 것이 곧 작업 시간을 줄이는 길이다. 단, 관측→명령 지연도 함께 줄어야 동작 의미가 유지된다.
- **목표**: 성공률을 유지하면서 실제 작업 완료 시간을 줄인다. 모델·앙상블 0.01·카메라 구성·제한(`max_relative_target`)의 의미는 그대로 둔다.

---

## 1. 우선 결론

- **주원인(근거 있음)**: 모델 순전파 실행 효율이다. 백본 2회와 인코더가 대부분이다.
  - PyTorch-MPS에서 모델이 52.8 ms로, 계산 57.5 ms의 92%를 차지한다(기존 측정).
  - 같은 가중치·FP32를 Core ML GPU로 돌리면 36.1 ms다. 같은 GPU에서 **백엔드(실행 경로) 효율 차이가 33%** 난다는 뜻이다.
  - 따라서 "GPU 하드웨어 한계"만으로는 설명되지 않는다. 실행 경로를 바꿀 여지가 있다.
- **2차 원인(미확인)**: 실측 약 80 ms와 오프라인 계산 57.5 ms의 차이 약 23 ms다. 이것은 **추정 잔여 시간**이다.
  - 후보: 모터 읽기 2번(관측 + 제한용)과 쓰기 1번, 미러 JPEG 내보내기, 카메라 스레드 부하, 메모리 압력.
  - 실기 계측 기록(`logs/rollout-timing-*`)이 아직 없다.
- **근거가 약하거나 아직 판단할 수 없는 것**
  - CPU 성능 부족: 계산 경로는 GPU다. 전·후처리는 합 3~4 ms다.
  - 발열: "경고 기록 없음"일 뿐 스로틀링이 없다고 증명된 것은 아니다. 팬 없는 Air라 지속 측정이 필요하다.
  - 메모리: **스왑 사용 11.96 GB**가 관측되어 위험 신호다. 실행 중 증감은 미측정이다.
- **가장 먼저 할 개선**
  1. 실기 `--timing`으로 잔여 23 ms를 분해한다.
  2. 같은 모델을 **Core ML GPU FP32 backend**로 선택 실행할 수 있게 만든다(rollout 경로에서 `predict_action_chunk`만 교체).
- **30 Hz 전망**
  - Core ML을 써도 계산만 37.7 ms다. 30 Hz 예산(33.3 ms)을 모터 입출력 전에 이미 넘는다.
  - 의미를 유지하는 최적화만으로 기대할 범위는 약 16.5~26 Hz(추정)다.
  - 30 Hz에는 추론과 입출력 중첩(의미 변경) 또는 더 빠른 장치·모델이 필요하다.
  - 기존 보고서의 "20 Hz 안팎"은 잔여 시간을 약 10 ms로 가정한 근거 없는 추정이었다. 잔여 23 ms를 그대로 더하면 60.7 ms, 약 16.5 Hz다. 이 계획에서 정정한다.

## 2. 증거 표

| 항목 | 값 | 구분 | 확인 방법 |
|---|---|---|---|
| 기기 | MacBook Air Mac16,12, Apple M4, CPU 10코어(성능 4 + 효율 6), **GPU 8코어**, RAM 16 GB, Metal 4 | 직접 확인 | `system_profiler SPHardwareDataType SPDisplaysDataType`, `sysctl` |
| 공식 사양 | M4 Air 13: GPU 8코어(기본)/10코어(선택), Neural Engine 16코어, 메모리 대역폭 120 GB/s | 공식 문서 열람 | support.apple.com/ko-kr/122209 |
| OS | macOS 26.5.2 (25F84) | 직접 확인 | `sw_vers` |
| 전원 | 배터리, 저전력 모드 0 | 직접 확인 | `pmset -g`, `pmset -g batt` |
| 발열 | "No thermal warning level has been recorded" | 직접 확인. 스로틀링 없음의 증명은 아님 | `pmset -g therm` |
| 메모리 | 스왑 used 11.96 GB / 13.3 GB, memory_pressure free 45% | 직접 확인(현재 시점) | `sysctl vm.swapusage`, `memory_pressure` |
| 아키텍처 | Python 3.12.15 arm64 네이티브, proc_translated=0, torch 2.11.0, MPS built·available | 직접 확인 | `file`, `platform.machine()`, `torch.backends.mps` |
| CPU fallback | 환경변수 미설정. lerobot에 안내 주석만 있음([factory.py:280](.venv/lib/python3.12/site-packages/lerobot/policies/factory.py#L280)) | 직접 확인. 실제 fallback 발생 여부는 미확인 | `env`, `grep` |
| LeRobot | 0.6.1 wheel(site-packages), `modeling_act.py`·`configuration_act.py`가 `external/lerobot`(7e241bd6)과 동일 | 직접 확인(이번 세션) | `diff` |
| 체크포인트 | chunk_size 100, 저장된 n_action_steps 100·TE null(실행 시 CLI로 1·0.01), resnet18, dim 512, enc 4층·dec 1층, 정규화 MEAN_STD(이미지 포함), 전처리: rename→batch→device→normalizer, 후처리: unnormalizer→cpu | 직접 확인 | `config.json`, `policy_*processor.json` |
| 앙상블 방향 | 가중치 `exp(-c·i)`, **i=0이 가장 오래된 예측** → c=+0.01은 오래된 예측을 더 크게 반영 | 직접 확인(설치 소스 docstring·코드) | [modeling_act.py:167-](.venv/lib/python3.12/site-packages/lerobot/policies/act/modeling_act.py#L167) |
| 단계별 시간(MPS) | 텐서 변환 2.53 / 전처리 1.12 / 모델 52.82 / 앙상블 0.58 / 후처리 0.33 / 합 57.46 ms | 기존 측정(이번 세션 실행). 원본: `.tmp/perf/stage_bench.py`, `run_.log` | 녹화 프레임 재생, 구간마다 동기화 |
| 모델 내부 비중 | 백본 1장 22.1(×2) / 인코더 14.9 / 디코더 1.7 / 기타 5.1, 합 65.9 ms | 기존 측정. 구간 동기화로 부풀려져 가산 불가 | `.tmp/perf/model_breakdown.py` |
| Core ML GPU FP32 | 모델 36.1, 틱 계산 37.7 ms. 연산 1,493개 모두 GPU 배치. 300틱 최종 명령 차이 0 | 기존 측정. 원본: `run_coreml.log`, `coreml_try2.log`, `outs_coreml.npy` | |
| coremltools 호환 | 9.0이 "Torch 2.11.0 has not been tested… 2.7.0 most recent tested" 경고. 변환 중 int64→int32, float64→fp32 저장 경고 | 직접 확인(로그) | `coreml_try2.log` |
| Core ML 기본 정밀도 | mlprogram 기본은 **FLOAT16**. FP32는 `compute_precision=ct.precision.FLOAT32`로 명시해야 함. FP32 모델은 NE 불가(CPU/GPU만) | 공식 문서 열람 | coremltools typed-execution |
| FastPrediction·캐시 | `optimization_hints={'specializationStrategy': ct.SpecializationStrategy.FastPrediction}`. `get_compiled_model_path()`를 고정 경로 `.mlmodelc`로 복사 → `CompiledMLModel`. 첫 로드는 여전히 느릴 수 있음. 지원 버전 명시 없음 | 공식 문서 열람 | coremltools model-prediction |
| 카메라 | `read_latest` p99 ≤0.2 ms(호출 비용). 프레임 나이·중복률·두 카메라 동시성은 미측정. 카메라 스레드가 BGR→RGB와 180° 회전을 수행. 나이 한도 500 ms 초과 시 예외 | 호출 비용은 기존 측정, 나머지는 직접 확인(코드)·미확인 | [camera_opencv.py:414-450, 582-](.venv/lib/python3.12/site-packages/lerobot/cameras/opencv/camera_opencv.py#L414) |
| 모터 | 관측 `sync_read(Present_Position, num_retry=2)`. 제한 사용 시 `send_action`에서 한 번 더 읽고 `sync_write` | 직접 확인(코드). 시간은 미측정 | [so_follower.py:180-230](.venv/lib/python3.12/site-packages/lerobot/robots/so_follower/so_follower.py#L180) |
| 실기 80 ms | 사용자 경고 기준 약 12.5 Hz | 사용자 보고(미재검증) | — |
| 잔여 23 ms 구성 | — | **미확인** | 실기 `--timing` 필요 |

## 3. 실제 호출 경로와 병목

`tools/rollout_with_view.sh`(옵션: `--no-view`는 창만 끔·미러 내보내기는 유지, `--no-mirror`는 내보내기·창 모두 끔, `--timing`은 계측)
→ `scripts/so101_launch.py`(부모 사망 감시, `SO101_CAMERA_MIRROR`·`SO101_ROLLOUT_TIMING` 훅 설치, `runpy`로 공식 CLI 실행)
→ `lerobot-rollout` → `build_rollout_context`: 정책 로드 → `policy.eval()`([context.py:271](.venv/lib/python3.12/site-packages/lerobot/rollout/context.py#L271)) → **그다음 로봇 연결**. 그래서 정책 로드 단계 검증은 하드웨어 연결 전에 끝난다.
→ `BaseStrategy.run` 루프([base.py:42-](.venv/lib/python3.12/site-packages/lerobot/rollout/strategies/base.py#L42)), 틱마다 순서대로:
1. `robot.get_observation()`: 모터 읽기 + 카메라 2대 `read_latest()`. 직렬.
2. `robot_observation_processor`: 기본 항등.
3. `send_next_action` → `SyncInferenceEngine.get_action`([sync.py:97-](.venv/lib/python3.12/site-packages/lerobot/rollout/inference/sync.py#L97), `torch.inference_mode`)
   - `prepare_observation_for_inference`: CPU에서 float/255 변환, CHW, `.to(mps)`
   - preprocessor: 정규화
   - `ACTPolicy.select_action` → `predict_action_chunk`(**매 틱 1회, 주 병목**) → `ACTTemporalEnsembler.update`
   - postprocessor: 역정규화, `.cpu()`로 동기화
4. `robot_action_processor` → `send_action`: 제한용 `sync_read` + `ensure_safe_goal_position` + `sync_write`. 직렬.
5. 남는 시간이 있으면 sleep. 없으면 경고.
- 현재 **추론과 모터 입출력은 완전히 직렬**이다. 겹치는 구간이 없다.
- 앙상블 초기화는 엔진 시작 때 한 번이다(`engine.reset()`, [core.py:66](.venv/lib/python3.12/site-packages/lerobot/rollout/strategies/core.py#L66)). 추가 초기화는 torch.compile 워밍업 플러시 때만 있다(이번 설정은 해당 없음). 에피소드 중 잘못 초기화되는 경로는 없다.
- 중복 모델 호출이나 학습 경로는 없다. 전처리는 틱당 1회다.

## 4. 기존 실험의 유효성

- **재현성**: MPS 모델 시간 52.7/52.8/52.9 ms(3회)로 재현됐다. 처음 20틱(워밍업 273~521 ms)은 제외했다.
- **입력의 한계**
  - 입력은 에피소드 0의 앞 300틱뿐이다. 동작 구간과 공 위치가 다양하지 않다.
  - 오프라인 개루프다. 실제 관측-행동 피드백이 아니다.
- **계측 영향**
  - 단계마다 `torch.mps.synchronize()`를 넣었다. 모델 끝 동기화는 후처리 `.cpu()`가 어차피 기다리는 시간을 앞으로 옮긴 것이라 합계 영향은 작을 것으로 본다(미검증).
  - 모델 내부 분해는 구간 동기화 때문에 65.9 ms로 부풀었다. 비중만 참고한다.
- **"출력 차이 0"의 한계**
  - 비교 대상은 앙상블·역정규화 후 최종 명령(float32)만이다. **chunk(정규화) 단위 차이, 제한 후 명령, 여러 에피소드는 미비교**다.
  - 제한·반올림이 내부 차이를 가렸을 가능성이 있다. 다만 이 비교에는 제한 적용 단계가 없었다.
  - 차이가 정확히 0인 점 자체도 재확인한다(동일 커널 결과인지, 비교 버그는 없는지).
- **부족한 증거**
  - 실기 단계별 시간(모터·미러·카메라 부하)
  - 지속 실행(5~10분) 지연 추이와 스왑 증감
  - Core ML의 torch 2.11 비공식 조합에서 다른 입력에 대한 안정성
  - FastPrediction·컴파일 캐시 효과
- **반복하지 않을 실험**: channels_last, 백본 배치, PyTorch fp16·전체 fp16, torch.compile. 새 가설이 없으면 재실험하지 않는다.

## 5. 추천 1차 구현안: 같은 모델의 Core ML GPU FP32 backend(선택형)

**원칙**
- `ACTPolicy.predict_action_chunk`만 교체한다.
- 전처리·정규화·`select_action`·`ACTTemporalEnsembler`(0.01)·reset·후처리·제한·카메라는 공식 코드 그대로다.
- 기본값은 기존 MPS다. 옵션을 줄 때만 Core ML을 쓴다.

**구성**

| 구성 요소 | 내용 |
|---|---|
| 의존성 | `lock/macos-arm64/pyproject.toml`에 macOS 전용 `coremltools==9.0`(+ protobuf·cattrs·pyaml 고정)을 추가하고 `install_macos.sh --relock`. Linux lock은 그대로. 공식 lock 대비 비교(`tools/lock_tools.py`)와 `docs/REFERENCES.md`를 갱신 |
| torch 2.11 미검증 경고 대응 | 변환(trace)은 export 도구에서 한 번만 한다. 실행 중에는 **컴파일된 모델만 로드**한다(실행 시 torch–coremltools 변환 경로를 타지 않음) |
| `tools/act_coreml_export.py`(새 파일) | 체크포인트 → 정규화된 입력(state·front·wrist, batch 1, 고정 shape) → chunk(정규화)를 내는 래퍼를 trace한다. 설정: `ct.convert(compute_precision=FLOAT32, compute_units=CPU_AND_GPU, convert_to="mlprogram", minimum_deployment_target=macOS15)`. 입력 이름은 `state` 예약어를 피해 `joint_state`. `.mlpackage` → `get_compiled_model_path()`를 `.cache/coreml/<키>/model.mlmodelc`로 복사 |
| 캐시 키·manifest | 키 = sha256(model.safetensors) + sha256(config.json) + 입력 shape + coremltools·torch 버전 + 정밀도 + 배포 대상. `manifest.json`에 위 값, 연산 배치 결과(MLComputePlan의 GPU 비율), 검증용 고정 입력 몇 개와 PyTorch 참조 출력, 변환 경고 요약을 기록 |
| `scripts/so101_act_coreml.py`(새 훅) | 런처가 `SO101_ACT_BACKEND=coreml`이면 설치. `ACTPolicy.__init__` 뒤 처리(제어 루프 밖, 로봇 연결 전): ① 체크포인트로 키 재계산 → manifest 일치 확인(불일치·없음이면 export 명령 안내 후 **시작 거부**) ② `CompiledMLModel(compute_units=CPU_AND_GPU)` 로드 ③ 워밍업 몇 회 ④ manifest 고정 입력으로 Core ML과 참조 출력 대조(허용 오차 초과 시 거부) ⑤ 인스턴스의 `predict_action_chunk`를 Core ML 호출로 교체(입력 `.numpy()` → 출력 `torch.from_numpy`) |
| 실행 중 대체 금지 | 실행 중 예외가 나면 MPS로 **조용히 넘어가지 않는다**(지연 급증·의미 혼동 방지). 예외는 공식 루프로 올려 정상 종료 경로(시작 자세 복귀·토크 해제)를 탄다 |
| 장치 정책 | Core ML 모드에서는 `--device=cpu`를 요구한다(전·후처리·앙상블 CPU, MPS 왕복 제거, 기존 측정 1.5 ms). 아니면 정책 로드 단계에서 거부 |
| `tools/rollout_with_view.sh` | 래퍼 옵션 `--backend=coreml`(기본 `mps`). 잘못된 값은 Python 실행 전에 거부 |
| 계측 | `scripts/so101_rollout_timing.py`에 **light 모드**(`--timing=light`: 틱 간격·단계 경계 시각만 기록, 추가 동기화 없음) 추가. 상세 모드(현재)와 루프 성능을 구분해 잰다. 시작 로그에 backend·장치·캐시 키·연산 배치 비율을 남긴다 |
| 시험 | `tools/verify_offline.py`에 추가: 옵션 전달·거부(장치·캐시 불일치), 훅 미설치 시 원래 경로, 교체 후 `select_action`·앙상블·reset 호출 순서가 같은지. 작은 무작위 ACT(기존 `timing_child` 패턴 재사용)로 export → 로드 → 대조까지 |

**2순위(1차 위에 한 번에 하나씩 비교)**
1. FastPrediction 힌트(지원 여부부터 확인)
2. 컴파일 캐시 재사용(시작 시간만 개선 대상)
3. 입력 변환·버퍼 재할당 줄이기

- 계산 37.7 ms 중 모델 외 경계 비용이 약 1.6 ms다. 그래서 경계 최적화의 최대 효과는 작다(수치 근거).
- 전처리(/255·정규화)를 그래프에 넣는 것은 색상·회전·정규화 의미를 먼저 보장할 수 있을 때만 검토한다.

## 6. 개선 후보 비교

| 순위 | 후보 | 근거·기대 | 불확실성 | 출력·제어 의미 | 재학습 | 부담 | 채택 기준 |
|---|---|---|---|---|---|---|---|
| 0 | 실기 계측으로 잔여 23 ms 분해(`--timing`·`--no-mirror`·light) | 다음 변경 대상을 좁힘 | 없음(측정만) | 불변 | 없음 | 작음(도구 있음) | 단계별 p95와 미러 유무 차이 확보 |
| 1 | Core ML GPU FP32 backend | 모델 52.8→36.1 ms(기존 측정) | torch 2.11 미검증 조합, 다른 입력 안정성 | 불변 목표(검증 필요) | 없음 | 중간(의존성·relock·훅·도구) | 6.1·6.2 기준 모두 통과 |
| 2 | Core ML 경계 최적화(FastPrediction·캐시·버퍼) | 최대 약 1~2 ms 또는 로드 시간 | 지원 버전 | 불변 | 없음 | 작음 | 변동 폭보다 큰 개선일 때만 |
| 2 | 미러·카메라 부하 줄이기 | 잔여 시간에 포함 가능 | 미측정 | 불변 | 없음 | 작음 | 실측에서 의미 있는 차이일 때 |
| 별도 | 제한용 추가 읽기를 관측값으로 대체 | 모터 읽기 1회 절감(미측정) | 기준 위치가 추론 시간만큼 오래됨 | **변함**(제한 의미) | 없음 | 작음 | 실측 근거 + 사용자 승인 |
| 별도 | Core ML FP16·NE 분할·양자화 | GPU FP16 32.1 ms(기존). NE는 컴파일 실패 | 정확도 영향 | **변함** | 없음 | 중간 | 별도 실기 비교 |
| 별도 | 추론과 입출력 중첩, 추론 주기와 명령 주기 분리 | 30 Hz에 근접할 유일한 소프트웨어 경로 | 관측 시각·대상 시각·chunk 지연·앙상블 시간 정렬을 새로 설계해야 함(결과 도착마다 `update` 1회로는 정렬이 틀어짐). 공식 RTC는 ACT 미지원([context.py:260](.venv/lib/python3.12/site-packages/lerobot/rollout/context.py#L260)) | **변함** | 없음 | 큼 | 별도 설계 문서 + 승인 |
| 별도 | 해상도·카메라 수 축소, 작은 백본 | 큰 효과 가능 | 성공률 | **변함** | **필요** | 큼 | 범위 밖(별도 결정) |
| 별도 | 더 빠른 장치(NVIDIA PC 등) | 효과 클 가능성 | 환경 이관 | 불변 | 없음 | 환경 작업 | 비교용 참고 |

## 7. 단계별 검증과 완료 기준

### 7.1 오프라인 수치 검증(로봇 없음)

- **입력**
  - Hub `so101_ball_to_bowl_v1`에서 여러 에피소드를 받는다. 예: 세션별로 하나씩 0·15·35·55·75·95를 골라 공 위치와 동작 구간이 다양하게 한다.
  - 원본은 `.tmp`에 두고 사용 후 삭제한다.
- **비교 단위**: 같은 관측 시퀀스를 MPS 경로와 Core ML 경로에 각각 넣고 아래 네 단계를 비교한다.
  - ① chunk(정규화 단위)
  - ② 앙상블 출력(정규화)
  - ③ 역정규화 후 목표(관절 °, gripper 0~100)
  - ④ 기록된 관측 위치를 현재 위치로 써서 `ensure_safe_goal_position`을 적용한 명령
- **보고 형식**: 단위별 최대·평균·p99와 분포를 낸다. 정규화 차이를 "관절 각도 차이"라고 부르지 않는다.
- **포함할 상황**: 첫 틱, 100틱 이상 누적된 앙상블, reset 뒤 같은 시퀀스 재실행(이전 상태 무영향 확인).
- **허용 오차 근거**
  - 먼저 MPS 대 MPS 반복 편차와 MPS 대 CPU-torch 편차를 잰다.
  - 제안: ③에서 관절 최대 |Δ| ≤ 0.01°, gripper ≤ 0.01. 단 이 값은 측정한 기준 편차의 몇 배 이내로 최종 확정한다.
  - 실패하면 원인(정밀도·캐스트 경고·연산)부터 조사한다. 기준을 넓혀서 통과시키지 않는다.
- **"차이 0" 재확인**: 비교 코드가 다른 배열을 읽는지, dtype이 맞는지 점검한다.

### 7.2 지연 검증

- **조건**: 같은 데이터·전원 상태·워밍업에서 잰다. 전원(AC/배터리)·온도·스왑을 기록한다.
- **세 단계로 구분해 측정**
  - 모델 단독(동기화 경계 명시)
  - 틱 계산 전체(light 모드)
  - 실기 루프
- 상세 계측을 켤 때와 끌 때의 차이를 확인한다.
- **지속 실행**: 10분 연속 추론으로 p50·p95·p99 추이, 메모리(RSS)·스왑 증감, `pmset -g therm` 기록을 남긴다. 처음 1분과 마지막 1분을 비교한다.
- **채택 기준**
  - Core ML 틱 계산 p95가 MPS 대비 25% 이상 개선
  - 10분 동안 p95 증가 10% 이내
  - 메모리 증가 없음
  - 2순위 최적화는 측정 변동(반복 표준편차)보다 클 때만 채택

### 7.3 실기 검증(사용자 수행, 이번 단계에서 실행하지 않음)

- **조건**: 같은 공 위치 5곳 × 각 2회, 같은 시작 자세. 앙상블 +0.01은 유지한다.
- **비교 순서**
  1. MPS 기준(`--timing`)
  2. Core ML(`--backend=coreml --device=cpu --timing`, 1차 구현 후 생기는 옵션)
- **기록 항목**
  - 결과 분류: 완전 성공 / 집기 실패 / 이동 중 낙하 / 그릇 투입 실패 / 시간 초과
  - 작업 시작→공 놓기 시간
  - 실제 Hz와 p95·p99
  - 제한 적용 비율
- **판정**: 10회로 성공률을 통계적으로 입증했다고 하지 않는다. 탐색 비교로만 쓴다.
- **중단 기준**: 이상 동작이나 성공률이 눈에 띄게 떨어지면 즉시 Ctrl+C 또는 전원 차단 등 기존 절차를 따른다. `--backend` 옵션을 빼면 기준 경로로 돌아간다.
- **완료 기준**
  - 성공 분류가 기준과 같은 수준이다(실패가 늘지 않음).
  - 작업 시간이 줄었다.
  - 실기 Hz p95가 개선됐다.
- 30 Hz는 평균이 아니라 p95·p99까지 33.3 ms 이하여야 주장한다.

## 8. 현재 환경의 30 Hz 가능성

- **확인된 사실**
  - MPS 계산 57.5 ms, Core ML 계산 37.7 ms. 둘 다 33.3 ms를 넘는다.
  - 추론과 입출력은 직렬이다.
- **예상 범위(추정)**
  - Core ML + 잔여 23 ms 고정: 60.7 ms ≈ 16.5 Hz
  - 잔여 시간이 일부 줄면(미러 끔 등) 약 20 Hz 전후
  - 잔여 시간이 0이어도 26.5 Hz가 상한
  - 작업 시간 기준으로는 12.5 Hz 대비 약 1.3~2배 빨라질 가능성(추정, 실측 전)
- **30 Hz를 안정적으로 내려면**
  - 의미를 바꾸는 중첩·주기 분리 설계(관측·대상 시각과 앙상블 정렬을 새로 정의)
  - 또는 더 빠른 장치나 더 가벼운 모델(재학습)
- 목표 FPS 숫자만 낮춰 경고를 없애는 것은 개선으로 보고하지 않는다.

## 9. 원복 방법과 남은 결정

- **원복**
  - `--backend` 옵션을 빼면 기존 MPS 경로다.
  - `.cache/coreml/` 삭제.
  - 의존성은 lock을 이전 커밋으로 되돌린 뒤 `install_macos.sh --relock`을 실행하거나 `--repair`.
  - 새 파일 3개(export 도구·Core ML 훅·light 계측)와 런처·래퍼의 해당 블록을 제거.
- **남은 결정(사용자)**
  1. macOS lock에 coremltools를 추가해도 되는지(1차 구현의 전제)
  2. 의미가 바뀌는 후보(제한 읽기 대체, FP16, 중첩·주기 분리)를 별도로 검토할지
  3. 30 Hz가 필수인지, 아니면 작업 시간 단축이 충분하면 되는지
- **이 계획의 범위 밖**: PTE(행동 선택 기법, 계산 가속 아님), 재학습, 하드웨어 구매.

## 10. 바로 다음에 할 작업 3개

1. **(사용자, 실기)** 기존 명령에 `--timing`을 붙여 30~60초 실행한다. 한 번은 `--no-mirror --timing`으로 실행한다. `logs/rollout-timing-*.json`으로 잔여 23 ms를 모터·미러·카메라 부하로 분해한다. 두 옵션 모두 이미 존재한다.
2. **(구현)** Core ML 오프라인 수치·지연 검증 도구를 만든다(7.1·7.2, 여러 에피소드, 10분 지속).
   - 지금은 `.tmp/coreml_pkgs`의 격리 패키지로 돌린다. coremltools 승인 전이라 lock은 바꾸지 않는다.
   - 통과하면 승인을 받아 의존성을 lock에 넣는다.
3. **(구현)** `--backend=coreml` 선택형 backend와 light 계측을 구현한다(5절). verify_offline 시험을 추가한 뒤, 7.3 실기 비교 명령을 사용자에게 전달한다.

## 승인 후 실행 순서(이 계획 실행 시)

1. 이 계획을 `docs/ACT_INFERENCE_OPTIMIZATION_PLAN.md`로 저장한다. 사용자 요청에 따라 같은 내용을 다운로드 경로 `/Users/user/Downloads/ACT_INFERENCE_OPTIMIZATION_PLAN.md`에도 저장한다.
2. 위 10절의 2번을 진행한다. 그동안 1번 실기 계측 결과를 받으면 반영한다.
3. 의존성 추가는 별도 확인 후 진행한다. 그다음 3번을 구현한다.
4. 각 단계의 완료 보고서(.md)는 저장소 `docs/`에 두고, 다운로드 경로(`/Users/user/Downloads/`)에도 같은 파일로 저장한다.

## 검증(이 계획 자체의 산출물)

- 각 단계 완료 시 `tools/verify_offline.py`를 실행한다(현재 기준 137/137은 이전 실행 결과이며, 다음 실행 수치를 따로 기록).
- 수치 검증(7.1)과 지연 검증(7.2) 결과는 `docs/ROLLOUT_PERFORMANCE_REPORT.md`를 갱신하는 방식으로 남긴다. 실기 결과(7.3)는 `docs/CURRENT_STATE.md`에 실측만 기록한다.
