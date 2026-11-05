# 데이터셋 생성 준비 점검 보고서

점검 일시: 2026-10-12 11:33~11:48(+0900), MacBook Air M4(macOS 26.5.2), 작업공간 `~/so101-ws_for-mac`.

- 아래 결과는 모두 **이번에 다시 실행해 얻은 값**이다. 이전 보고서의 결과를 옮겨 적지 않았다.
- 모터 ID·보정은 변경하지 않았다. 실제 로봇 녹화는 실행하지 않았다.

## 판정: **시험 녹화 가능**

- 통신, 보정 일치, 카메라 매핑·해상도·FPS, 저장 경로·공간, 업로드 꺼짐, 공식 녹화 명령 파싱이 모두 통과했다.
- 다만 **실제 녹화와 녹화본 검사는 아직 하지 않았다.** 그래서 데이터 수집 실기 검증은 `NOT VERIFIED`다.

## 1. 로봇(통신·보정)

| 검사 | 결과 |
|---|---|
| `./01_setup/doctor.sh --hardware`(11:33) | FAIL 2: 사용자가 실행 중이던 텔레옵(11:32 시작)이 두 포트를 쓰고 있었음. 텔레옵을 강제로 끄지 않고 종료를 기다림 |
| 같은 검사 재실행(텔레옵 종료 후, 11:47) | **FAIL 0** / WARN 2: cv2·av의 libavdevice 중복 objc 경고, `max_relative_target` 미설정. 포트 2개, USB 지문, 보정 파일 2개 모두 OK |
| `./01_setup/probe.sh both`(읽기 전용) | 리더·팔로워 모두 **6/6 응답**, 모델 777(STS3215), 펌웨어 3.10, 보정 파일 상태 **match**. 두 팔 자세 차이는 모든 관절 2° 이내(쉬는 자세) |
| 참고: 점검 중 끝난 텔레옵(11:32:35) | exit 0, 루프 구간 858.88초(약 14분 19초), 60.0 Hz(최대 48.4 ms), 양팔 토크 해제 성공. 이 시험이 아니라 사용자가 실행한 세션의 기록 |

## 2. 설정 파일

| 항목 | 설정값 |
|---|---|
| `configs/cameras.local.yaml` | `front`(외부): index 1, 640×480, fps 30, `rotation: 180` / `wrist`(손목): index 0, 640×480, fps 30. fourcc 없음. 형식 오류 0 |
| `configs/recording.local.yaml` | fps 30, episode 20초, reset 10초, num_episodes 2, datasets_dir 기본(`datasets/`), video true, vcodec libsvtav1. **name·task는 비워 둠**(시험 명령에서 지정). 형식 오류 0 |
| 카메라 FPS = 데이터셋 FPS | 30 = 30 |
| 저장 경로·공간 | `~/so101-ws_for-mac/datasets/`(아직 없음, 녹화 시 생성). 여유 약 29~31 GB. 20초 에피소드 1개는 최대 약 0.68 GB 필요(래퍼 추정: 임시 PNG + 영상 + 표) |
| Hub 자동 업로드 | **꺼짐**. 래퍼가 `--dataset.push_to_hub=false`를 고정하고 `HF_HUB_OFFLINE=1`로 실행한다. 공식 RecordConfig 파싱 결과도 `push_to_hub=False` |

설정 수정은 필요하지 않았다(백업·변경 없음).

## 3. 카메라 실측(모터를 움직이지 않음, 두 카메라 동시 60초)

`tools/camera_check.py`: 공식 OpenCVCamera 경로를 쓰고, 새 프레임만 센다(중복은 따로 셈). 동시에 30 Hz 소비 루프를 돌렸다.

| 구분 | `front`(외부) | `wrist`(손목) |
|---|---|---|
| 설정값 | 640×480, 30 fps, 180° 회전 | 640×480, 30 fps |
| 드라이버 보고값(OpenCV) | 640×480, 30.00 fps | 640×480, 30.00 fps |
| **실제 프레임** | 480×640×3 → 처리 후 480×640×3 | 480×640×3 → 480×640×3 |
| **실제 새 프레임 FPS** | **30.12**(1807장/60초) | **30.15**(1809장/60초) |
| 간격 중앙값 / p95 / 최대 | 33.0 / 34.4 / 67.3 ms | 33.0 / 34.5 / 67.1 ms |
| 50 ms 초과 / 100 ms 초과 멈춤 | 12 / 0 | 11 / 0 |
| 중복 / 읽기 오류 / 소비 시간초과 | 0 / 0 / 0 | 0 / 0 / 0 |

- **역할 확인**(확인용 이미지 `logs/camera-check-20261012_114728/`)
  - `front_processed.png`: 작업면 위에서 상자·테이프·팔로워를 내려다보는 외부 시점이고, 똑바로 서 있다.
  - `wrist_processed.png`: 아래쪽에 그리퍼 두 손가락 끝이 보이는 손목 시점이다.
  - 매핑이 설정과 일치한다.
- 기록: `logs/camera-check-20261012_114728.json`
- **50 ms 초과 간격 11~12회**: 평균 30 fps가 유지되어 전달 지연으로 보인다. 프레임 손실 여부는 카메라 타임스탬프가 없어 확인할 수 없다.
- **장면 참고**: 이번 사진에서는 빨간 마커가 작업면에 보이지 않는다. 시험 녹화 전에 장면과 작업 설명을 맞춘다.

## 4. 최종 녹화 명령 검사(`record.sh --dry-run`, 포트·카메라를 열지 않음)

```bash
./03_dataset/record.sh --dry-run --name so101_trial_20261012 --task "Move the red marker into the box" --episodes 1
```

- 결과: **FAIL 0 / WARN 0**, 공식 RecordConfig 파싱 OK
  - `repo_id=local/so101_trial_20261012`
  - `root=~/so101-ws_for-mac/datasets/so101_trial_20261012`
  - fps 30, episodes 1, vcodec libsvtav1, `push_to_hub=False`, `resume=False`
  - 카메라: front(1, 640, 480, 30, 회전 180), wrist(0, 640, 480, 30)
- 실제로 실행될 공식 명령(요약): `lerobot-record`
  - 팔로워 `--robot.port=/dev/cu.usbmodem5B901515041 --robot.id=so101_follower`
  - 리더 `--teleop.port=/dev/cu.usbmodem5B901517511 --teleop.id=so101_leader`
  - `--robot.cameras=` 위 두 카메라
  - `--dataset.episode_time_s=20 --dataset.num_episodes=1 --dataset.push_to_hub=false --dataset.no_stamp=true --dataset.video_encoding_batch_size=1 --play_sounds=false --resume=false`

## 5. 사람이 옆에서 실행할 시험 녹화(1에피소드)

**준비**
- 두 팔 전원 ON, 맥북 전원 어댑터 연결, 덮개 열림
- 카메라 미리보기 창 닫기, 텔레옵 꺼짐
- 작업할 물체를 작업면에 둔다
- 작업 설명(`--task`)을 실제 장면에 맞게 정한다(아래 예시는 빨간 마커를 상자에 넣는 작업)

```bash
cd ~/so101-ws_for-mac
./03_dataset/record.sh --name so101_trial_20261012 --task "Move the red marker into the box" --episodes 1
```

1. 래퍼가 먼저 점검한다(이 중 하나라도 실패하면 모터를 움직이기 전에 멈춘다).
   - 두 카메라를 실제로 열어 해상도와 FPS 확인
   - 포트, USB 지문, 보정 일치, 모터 응답
2. 자세 차이 표를 보고 리더를 팔로워 자세에 맞춘 뒤 **`yes`**를 입력한다(녹화는 Enter가 아니라 `yes`).
3. 20초 동안 리더로 작업을 수행한다.
   - 일찍 끝내려면 `n`(또는 →): 저장하고 종료
   - 다시 하려면 `r`(또는 ←): 다시 녹화
   - 중단하려면 `q`(또는 Esc)
4. 끝나면 공식 코드가 영상 인코딩과 마무리(finalize)를 한 뒤 팔 연결을 끊는다. 그동안 **팔로워를 받쳐 둔다.**
5. 래퍼가 양팔 토크 해제를 다시 시도하고, 저장된 데이터셋을 자동으로 한 번 검사한다.

**녹화 후 검사**

```bash
./03_dataset/inspect.sh datasets/so101_trial_20261012
./03_dataset/inspect.sh datasets/so101_trial_20261012 --write-manifest
```

- 첫 줄은 형식, 프레임 수, timestamp, 영상 디코드, NaN, task를 검사한다.
- 둘째 줄은 연구실 PC로 옮길 때 쓸 체크섬(`datasets/so101_trial_20261012.sha256`)과 manifest를 만든다.
- **합격 기준**
  - `결과: FAIL 0`
  - 에피소드 1개, 길이 약 600프레임(20초 × 30 fps)
  - 두 영상 디코드 프레임 수 = 길이
  - 녹화 요약의 "루프 지연 경고"가 없거나 적음

## 6. 남은 위험·미검증

- **녹화 상태 전체**: 실제 녹화(모터 + 카메라 2대 + 인코딩 동시 동작)와 녹화본 검사는 아직 하지 않았다(`NOT VERIFIED`).
- **카메라 번호**: 재연결·재부팅 후 OpenCV index가 바뀔 수 있다. 녹화하는 날마다 `./03_dataset/cameras.sh --test front`, `./03_dataset/cameras.sh --test wrist` 사진으로 확인한다.
- **cv2·av의 libavdevice 중복 경고**: 카메라만 쓴 시험에서는 문제가 없었다. 실제 녹화에서도 문제가 없는지 확인해야 한다.
- **이동량 제한**: `max_relative_target`이 미설정이다. 시작 전 자세를 맞추는 것으로 대신한다.
- **팔로워 wrist_flex 범위**: 73~2435로 0 경계에 가깝다. 넘어가지는 않았다.
- 연구실 PC로 옮겨 읽기는 아직 하지 않았다.
