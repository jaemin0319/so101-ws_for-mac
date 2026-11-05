# 시험 녹화·저장본 검증 보고서 (2026-10-13)

MacBook Air M4(macOS 26.5.2), 작업공간 `~/so101-ws_for-mac`, LeRobot v0.6.1(`7e241bd6`), 코드 기준 커밋 `757b252` + 미커밋 변경.

- 실제 로봇(리더·팔로워)과 카메라 2대로 1에피소드를 녹화하고, 저장본을 다시 열어 검사했다.
- 녹화 시작(`yes` 입력)과 조작은 사용자가 로봇 옆 터미널에서 직접 했다.
- 이전 보고서 결과는 쓰지 않았고, 아래 수치는 모두 이번 실행의 로그와 파일에서 얻었다.

## 최종 판정(재시험 반영): **무결성 통과 / 수집 품질 보완 필요**

시험 녹화를 두 번 했다. 두 번 모두 녹화·finalize·종료 정리·저장본 무결성은 정상이어서, **녹화·저장 파이프라인 자체는 실측으로 정상 동작**한다.

| 시험 | 데이터셋 | 무결성 | 수집 품질 문제 |
|---|---|---|---|
| 1차(11:29) | `so101_trial_20261013` | PASS(inspect FAIL 0) | task 문장(`…marker…`)이 실제 시연(빨간 테이프 롤)과 다름 |
| 2차(11:34) | `so101_trial_20261013_b` | PASS(inspect FAIL 0) | task는 일치(`Pick up the red tape roll and place it in the box`). 그러나 **2.5~4초에 사람 손이 화면에 들어와 테이프를 상자에서 꺼내 바닥에 놓음**(초기 배치를 녹화 중에 함). 12~16초 화면 오른쪽 가장자리에도 손이 살짝 보임 |

- 두 에피소드 모두 학습 데이터로는 쓰지 않는다. 데이터는 지우거나 고치지 않고 보존했다.
- 남은 보완점은 소프트웨어가 아니라 **수집 절차**다(6절).
- 반복 프레임은 움직이는 구간 기준 0.7~1.5%다. 공식 `read_latest` 구조에서 생기며, 지연 경고는 두 번 모두 0회다.

## 1. 1차 시험 — 명령·경로

| 항목 | 값 |
|---|---|
| 시험 직전 점검 | `./01_setup/doctor.sh --hardware` → FAIL 0 / WARN 2(cv2·av libavdevice 중복, `max_relative_target` 미설정)<br>`./01_setup/probe.sh both` → 양팔 6/6, 보정 match<br>`./03_dataset/cameras.sh --test front` 30.4 fps, `--test wrist` 30.5 fps(640×480). 사진으로 역할 확인 |
| dry-run | `./03_dataset/record.sh --dry-run --name so101_trial_20261013 --task "Pick up the marker and place it in the box" --episodes 1` → FAIL 0 |
| 녹화(사용자 실행) | `./03_dataset/record.sh --name so101_trial_20261013 --task "Pick up the marker and place it in the box" --episodes 1` |
| 검사 | `./03_dataset/inspect.sh datasets/so101_trial_20261013` |
| 데이터셋 | `datasets/so101_trial_20261013/`(11 MB)<br>수집 기록 `datasets/so101_trial_20261013.so101.json` |
| 로그 | `logs/record-so101_trial_20261013-20261013_112900.log`<br>`logs/runs.jsonl`(record 항목)<br>`logs/inspect-so101_trial_20261013-20261013_113011.json`<br>샘플 `logs/trial-check-20261013/montage_front_wrist.png` |

**사용 설정**: 설정 변경은 없었다.
- fps 30, 에피소드 20초, num_episodes 1, video true, vcodec libsvtav1, `video_encoding_batch_size=1`
- `push_to_hub=false`, `no_stamp=true`, `resume=false`
- 카메라 `front`: index 1, 640×480@30, 180° 회전
- 카메라 `wrist`: index 0, 640×480@30
- 팔로워 `/dev/cu.usbmodem5B901515041`, 리더 `/dev/cu.usbmodem5B901517511`
- 보정 파일 hash: 리더 `97b9afec5d27…`, 팔로워 `ae844d1bc16e…`(현재 보정과 같음)

## 2. 녹화 실행 결과

| 항목 | 결과 | 판정 |
|---|---|---|
| 공식 프로세스 | 11:29:00 시작 → 11:29:37 종료, 전체 36.81초, **exit 0**, 사용자 중단 없음, 강제 종료 없음 | PASS |
| 진행 순서(로그) | 11:29:03 리더 연결 → 11:29:06 카메라(1) → 11:29:09 카메라(0)·팔로워 연결<br>11:29:09 `Recording episode 0`(공식 터미널 키 입력 모드)<br>600행 저장 → 두 영상 SVT-AV1 인코딩(640×480, 30/1) → 11:29:37 `Stop recording` → 카메라 2대·팔로워·리더 연결 해제 → `Exiting` | PASS |
| 기록 프레임 수·길이 | 600프레임, 20.00초 | PASS |
| 녹화 루프 지연 경고 | **0회**(`Record loop is running slower`). 공식 코드는 반복 한 번의 작업 시간이 1/30초를 넘을 때 경고한다. 600번 모두 33.3 ms 안에 끝났다는 뜻이다 | PASS |
| 반복별 루프 Hz·주기 분포 | 공식 녹화 로그에 반복별 시간이 남지 않음 | **미측정** |
| 카메라·인코딩 오류 | 0. 카메라 읽기 경고 없음, 인코딩 오류 없음 | PASS |
| finalize | `Stop recording` 이후 정상 종료, 메타데이터 완성(공식 재열기 성공) | PASS |
| 종료 후 양팔 토크 해제 재시도 | 리더·팔로워 모두 **성공**(12개 관절 ok) | PASS |
| 절전 방지 | caffeinate 실행 → 종료(`ended: true`) | PASS |
| 예상된 경고 | torchcodec 로드 실패 traceback 1회. 외부 FFmpeg가 없어 공식 코드가 pyav 디코더로 대체한다. 인코딩(PyAV)에는 영향 없음<br>objc 중복 클래스 경고 6줄(cv2·av의 libavdevice). 녹화와 영상에 이상 없음 | 영향 없음 |

## 3. 저장본 검사

**`inspect.sh` 전체 결과: FAIL 0 / WARN 0**

| 항목 | 결과 | 판정 |
|---|---|---|
| 공식 LeRobotDataset 재개방 | 성공. codebase v3.0, robot_type so_follower, fps 30 | PASS |
| 에피소드·프레임 | 에피소드 1, 600프레임(20.00초), info.total_frames = 데이터 행 600 | PASS |
| 메타데이터가 가리키는 파일 | data 1, front MP4 7.3 MB, wrist MP4 4.1 MB 모두 있음 | PASS |
| 영상 디코드 | front·wrist 모두 AV1 yuv420p 480×640, **디코드 600프레임 = 행 600**(v3 영상 구간 0.00~20.00초 기준) | PASS |
| 공식 `__getitem__` 샘플 | index 0·300·599 디코드 정상 | PASS |
| state·action | 각 float32 (6,). 순서 `shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper`(.pos), 공식 SO101과 같음. NaN·Inf 0 | PASS |
| 관절 값 고정 여부 | 모든 관절이 움직임: state 범위 shoulder_pan 44.6°, shoulder_lift 111.5°, elbow_flex 83.0°, wrist_flex 35.7°, wrist_roll 9.2°, gripper 19.6. action과 state의 평균 차이 0.9~2.3 | PASS |
| 그리퍼 동작 | state 25(열림) → 8초부터 6~7(닫힘) → 14초부터 19(놓음) | PASS |
| timestamp·인덱스 | 0.000~19.967초, 간격 33.333~33.335 ms, frame_index·index 연속 | PASS |
| task | 1개 저장됨: `Pick up the marker and place it in the box` | **FAIL(실제 시연과 불일치)** |
| 카메라 역할 | front = 위에서 내려다본 작업면(180° 회전 후 똑바름), wrist = 그리퍼 끝 시점 | PASS |
| 작업 과정(샘플 프레임) | 0~4초 테이프로 접근 → 8초 테이프 테두리를 집음 → 12초 상자 위로 이동 → 16초 상자 안에 놓음 → 19.9초 복귀(테이프는 상자 안). 두 영상 모두에서 확인 | PASS(물체는 테이프 롤) |
| 영상 손상·검은 화면 | 검은 프레임 0. 평균 밝기 front 121~140, wrist 89~137 | PASS |
| stats | `meta/stats.json` 있음 | PASS |

## 4. 수집 품질 관찰

- **반복 프레임**
  - v0.6.1 공식 `SOFollower.get_observation()`은 카메라를 `read_latest()`(새 프레임을 기다리지 않음)로 읽는다. 카메라와 녹화 루프의 박자가 어긋나면 직전 카메라 프레임이 한 번 더 저장될 수 있다.
  - 팔이 1° 넘게 움직인 133구간 중 화면이 거의 같은 경우: front 2(1.5%), wrist 1(0.8%). 바로 다음 프레임에서 크게 변하는 반복 후 따라잡기 모양이다.
  - 정지 구간에서 화면이 거의 같은 경우(front 95/466, wrist 70/466)는 정지 장면인지 반복인지 구분할 수 없다.
  - 정확한 반복 수는 확인 불가다.
- **동기화 한계**: timestamp는 공식 규칙(frame_index/fps)으로 저장되고, 카메라가 실제로 찍은 시각은 저장되지 않는다. 그래서 영상과 관절 값이 같은 순간이라는 것은 녹화 루프의 같은 반복에서 저장됐다는 수준까지만 보장되고, 카메라 노출 시각까지 엄밀히 동기화됐다고 할 수 없다.
- **카메라 단독 측정과 다름**: 이번 수치는 실제 녹화 기준이다. 카메라 단독 30 fps나 텔레옵 단독 60 Hz 측정으로 대신하지 않았다.

## 5. 1차 시험 판정 근거(재시험 전)

| 기준 | 상태 |
|---|---|
| 실제 1회 녹화·finalize | PASS |
| inspect FAIL 0, 영상 2개·state/action·메타데이터 | PASS |
| 종료 정리(양팔 토크 해제) | PASS |
| task 문장 = 실제 시연 | **FAIL** |
| 녹화 루프 지연 | 경고 0(PASS), 반복별 분포는 미측정 |
| 연구실 PC 읽기 | NOT VERIFIED(이번 범위 밖) |

**다음 단계**
1. 장면과 task를 맞춰 다시 시험 녹화한다. 기존 데이터는 보존하고 새 이름을 쓴다.
   - 테이프 롤을 옮긴다면:
     ```bash
     ./03_dataset/record.sh --name so101_trial_20261013_b --task "Pick up the red tape roll and place it in the box" --episodes 1
     ```
   - 마커를 쓴다면 마커를 작업면에 놓고 원래 문장을 쓴다.
2. 다시 녹화한 데이터가 inspect FAIL 0이고 task가 일치하면 "녹화·저장본 검증 완료"로 바꾼다.
3. `so101_trial_20261013`은 task가 틀렸으므로 학습 데이터에 섞지 않는다. 삭제는 사용자가 판단한다.
4. 연구실 PC로 옮겨 읽기(`./03_dataset/inspect.sh … --write-manifest` → 복사 → 체크섬 → 공식 API로 열기)를 한다.

---

## 6. 2차 시험(재녹화) — `so101_trial_20261013_b`

| 항목 | 결과 | 판정 |
|---|---|---|
| 명령(사용자 실행) | `./03_dataset/record.sh --name so101_trial_20261013_b --task "Pick up the red tape roll and place it in the box" --episodes 1` | — |
| 공식 프로세스 | 11:34:22 → 11:34:59, 전체 37.12초, **exit 0**, 사용자 중단 없음 | PASS |
| 진행 순서(로그) | 11:34:25 리더 → 11:34:28 카메라(1) → 11:34:31 카메라(0)·팔로워 연결 → `Recording episode 0` → 600행 저장 → 인코딩 → 11:34:58 `Stop recording` → 연결 해제 → `Exiting` | PASS |
| 녹화 루프 지연 경고 | **0회** | PASS |
| 오류 | Traceback 10개는 모두 torchcodec 로드 실패 블록 안에 있음(예상된 pyav 대체). 그 밖의 오류 0 | PASS |
| 종료 후 양팔 토크 해제 | 리더·팔로워 **성공**, caffeinate 종료 | PASS |
| 보정 파일 hash | 리더 `97b9afec5d27…`, 팔로워 `ae844d1bc16e…`(1차와 같음) | — |
| `inspect.sh` | **FAIL 0 / WARN 0**: 에피소드 1, 600프레임(20.00초), state·action (6,) 공식 순서, task 1개 연결, `__getitem__` 샘플 정상, stats 있음 | PASS |
| 영상 | front 6.9 MB·wrist 3.8 MB, AV1 640×480, **디코드 600/600 = 행 600**, 검은 프레임 0 | PASS |
| state·action | NaN·Inf 0. 범위: shoulder_pan 48.2°, shoulder_lift 123.2°, elbow_flex 90.1°, wrist_flex 30.2°, wrist_roll 18.2°, gripper 18.9. action과 state 평균 차이 0.9~2.1 | PASS |
| 그리퍼 | 19 → 8~12초 5(집기) → 14초부터 24(놓기) | PASS |
| timestamp·인덱스 | 0.000~19.967초, 간격 33.333~33.335 ms, 연속 | PASS |
| task 문장 = 실제 시연 | 로봇이 빨간 테이프 롤을 집어 상자에 넣음 | PASS |
| 카메라 역할 | front 외부(똑바름), wrist 그리퍼 시점 | PASS |
| 작업 과정(샘플 프레임) | 4초 테이프 옆 → 8초 집기 → 12초 상자 위 → 16초 상자 안 → 19.9초 복귀 | PASS |
| **장면 개입** | 0~2초 테이프가 상자 안에 있음 → 2.5~3.5초 사람 손이 테이프를 꺼내 팔 옆에 놓음 → 4초부터 로봇 작업. 12~16초 오른쪽 가장자리에 손 일부 | **수집 품질 FAIL** |
| 반복 프레임 | 움직이는 152구간 중 front 1·wrist 1(0.7%), 둘 다 시작 직후(3번째 프레임) | 관찰(경미) |

증거 이미지
- `logs/trial-check-20261013/montage_front_wrist_b.png`(0~19.9초, 위 front·아래 wrist)
- `logs/trial-check-20261013/front_0-4s_b.png`(0~4초, 0.5초 간격)

검사 기록: `logs/inspect-so101_trial_20261013_b-20261013_113545.json`, 로그: `logs/record-so101_trial_20261013_b-20261013_113422.log`

## 7. 남은 일(수집 절차 보완)

1. **물체를 먼저 놓고 `yes`를 입력한다.** 녹화가 시작된 뒤에는 사람 손이 두 카메라 시야에 들어가지 않게 한다. 여러 에피소드를 녹화할 때 장면 정리는 에피소드 사이 리셋 시간(`reset_time_s`, 기본 10초)에 한다. 리셋 구간은 저장되지 않는다.
2. 같은 조건으로 1에피소드를 다시 녹화하고, inspect FAIL 0 + 샘플 프레임에 사람 손이 없는지 확인한 뒤 "녹화·저장본 검증 완료"로 바꾼다.
   ```bash
   ./03_dataset/record.sh --name so101_trial_20261013_c --task "Pick up the red tape roll and place it in the box" --episodes 1
   ./03_dataset/inspect.sh datasets/so101_trial_20261013_c
   ```
3. 연구실 PC 읽기는 NOT VERIFIED(이번 범위 밖)로 유지한다.

> 2026-10-13 11:41: 사용자 요청으로 시험 데이터셋 `so101_trial_20261013`, `so101_trial_20261013_b`와 각 수집 기록(.so101.json)을 삭제했다. 위 수치는 삭제 전 검사 결과이며, 로그(`logs/record-*`, `logs/inspect-*`, `logs/trial-check-20261013/`)는 남아 있다.
