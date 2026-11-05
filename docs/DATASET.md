# 3단계: 로컬 데이터셋 생성(macOS) — 카메라·녹화·검사·이관

녹화는 공식 `lerobot-record`가 하고, 데이터는 공식 LeRobotDataset v3 형식으로 저장됩니다. 이 저장소는 사전 점검, 실행, 정리, 기록만 붙입니다.

**지키는 것**
- Hub 업로드는 하지 않습니다: `push_to_hub=false`로 고정하고 `HF_HUB_OFFLINE=1`로 실행합니다. HF 로그인·토큰이 필요 없습니다.
- 데이터는 Git에 넣지 않습니다(`datasets/`는 Git 제외).
- 학습은 이 맥에서 하지 않습니다. 연구실 PC로 옮긴 뒤 별도로 진행합니다.

**전제 조건**: [SETUP.md](SETUP.md)·[TELEOP.md](TELEOP.md)를 마쳤고, 30초 추종이 정상입니다.

```bash
cd ~/so101-ws_for-mac
cp configs/cameras.example.yaml configs/cameras.local.yaml        # 처음 한 번
cp configs/recording.example.yaml configs/recording.local.yaml    # 처음 한 번
```

## 1. 카메라 선택

**연결**: 녹화용 USB(UVC) 카메라를 연결합니다. 카메라 모델은 아직 정해지지 않았으므로, 일반 UVC 카메라를 기준으로 합니다.

**실행**

```bash
./03_dataset/cameras.sh --dry-run    # 명령·설정만 확인(카메라를 열지 않음)
./03_dataset/cameras.sh              # 공식 lerobot-find-cameras opencv
```

- 처음 실행하면 macOS가 **이 터미널 앱(VS Code 등)의 카메라 접근 허용**을 묻습니다. 사용자가 직접 허용합니다.
  - 거부했다면 시스템 설정 > 개인정보 보호 및 보안 > 카메라에서 바꿉니다.
  - 손쉬운 사용·입력 모니터링 권한은 필요 없습니다.
- 공식 도구가 모든 카메라의 index와 기본 해상도·FPS를 보여 줍니다. 확인용 사진은 `logs/cameras-<시각>/`에 저장됩니다.
- **사진을 보고 녹화용 카메라의 index를 고릅니다.**
  - 내장 카메라나 iPhone(연속성 카메라)도 목록에 나올 수 있습니다.
  - index는 재연결할 때마다 바뀔 수 있으므로 **녹화하는 날마다 다시 확인**합니다.

**설정**: `configs/cameras.local.yaml`에 `index_or_path`, `width`, `height`, `fps`를 적습니다.
- 첫 시험 권장값은 640×480, 30 FPS입니다.
- 카메라가 지원하지 않으면 공식 도구가 보여 준 값으로 바꾸고, 바꾼 이유를 적어 둡니다.

**확인**

```bash
./03_dataset/cameras.sh --test front
```

- 공식 `OpenCVCamera`로 3초간 읽습니다. 프레임 형태, **측정 FPS**, 확인용 사진 경로가 나옵니다.
- 공식 연결은 요청 FPS와 실제 FPS가 다르면 오류를 냅니다. 그 경우 지원되는 FPS로 바꿉니다.
- 측정 FPS는 카메라가 실제로 프레임을 주는 속도입니다. 녹화 루프 FPS나 저장 timestamp와는 다른 값입니다(아래 4번).

## 2. 녹화 설정

`configs/recording.local.yaml`을 채웁니다.

| 키 | 의미 | 첫 시험 값 |
|---|---|---|
| `name` | 데이터셋 폴더 이름 → `datasets/<name>/`, 공식 `repo_id=local/<name>` | 예: `so101_trial_20261010` |
| `task` | 작업 설명(필수). 공식 `meta/tasks.parquet`에 저장됩니다 | 예: `Pick the red cube and place it in the box` |
| `fps` | 녹화 fps. 카메라 fps와 같아야 합니다 | 30 |
| `episode_time_s` / `reset_time_s` | 에피소드 시간 / 에피소드 사이 정리 시간(초) | 20 / 10 |
| `num_episodes` | **이번 실행에서** 녹화할 에피소드 수(`--resume`이면 추가로 녹화할 수) | 2 |
| `datasets_dir` | null이면 `datasets/`. 외장 저장소는 이미 있는 절대경로 폴더 | null |
| `vcodec` | 공식 기본 `libsvtav1`. 대안: `h264`, `h264_videotoolbox` | libsvtav1 |

**확인**(포트·카메라를 열지 않음)

```bash
./03_dataset/record.sh --dry-run
```

**dry-run이 보여 주는 내용**
- 공식 인자 파싱 결과(업로드 false 포함)
- 저장 경로
- 같은 이름의 데이터셋이 있는지
- 저장 공간 추정

명령행 옵션이 설정 파일 값보다 우선합니다: `--name`, `--task "..."`, `--episodes N`, `--episode-time-s`, `--reset-time-s`, `--fps`, `--datasets-dir`.

## 3. 녹화

- **02_teleop/run.sh를 동시에 띄우지 않습니다.** 녹화가 리더·팔로워 추종을 함께 합니다.
- 맥 준비 사항(전원 어댑터, 덮개 열림)은 [TELEOP.md](TELEOP.md) 0번과 같습니다.

**실행**

```bash
./03_dataset/record.sh
```

**사전 점검**(어느 하나라도 실패하면 모터를 움직이기 전에 멈춥니다)
1. 설정
2. 저장 경로와 공간
3. **카메라 실제 열기**(해상도·FPS)
4. 포트, USB 지문, 보정 파일과 레지스터의 일치, 6개 모터 응답(모두 읽기 전용)

자세 차이 표와 체크리스트를 확인하고 `yes`를 입력하면 녹화가 시작됩니다.

**스페이스바 진행 모드**(`recording.local.yaml`의 `manual_advance: true`, 이 맥의 현재 설정)

| 단계 | 화면 안내 | 키 |
|---|---|---|
| 준비(세션 시작, 저장 안 함, 리더 추종은 됨) | `▶ 준비` | **스페이스바** → 녹화 시작 |
| 녹화 중(시간 제한 없음) | `● 녹화 중` | **스페이스바** → 종료·저장 / **r** → 이번 에피소드 버림 |
| 환경 재설정(저장 안 함) | `■ 환경 재설정` | **스페이스바** → 다음(또는 다시) 녹화 시작. 여기서 r을 누르면 방금 에피소드를 버림 |

- `q`를 누르면 녹화를 끝냅니다.
- 스페이스바를 누르지 않으면 에피소드는 `max_episode_time_s`(기본 120초)에서 끝나 저장됩니다. 영상이 끝없이 쌓이지 않게 하는 안전 상한입니다.
- **마지막 에피소드**는 스페이스바로 끝내면 바로 저장·마무리됩니다. 공식 코드에는 마지막 뒤 재설정 단계가 없습니다. 마지막을 다시 하려면 녹화 중에 `r`을 누릅니다.
- 이번 실행만 시간 자동 진행으로 하려면 `--auto`를, 반대로 스페이스바 진행으로 하려면 `--manual`을 붙입니다.
- 구현: 공식 파일은 수정하지 않습니다. 녹화를 실행할 때 런처(`scripts/so101_launch.py`)가 `scripts/so101_record_hooks.py`로 공식 `record_loop`와 키 연결만 감쌉니다.

**시간 자동 진행 모드 조작**(`manual_advance: false` 또는 `--auto`, 이 터미널에 초점을 둡니다)

| 키 | 동작 |
|---|---|
| `n` 또는 → | 이번 에피소드를 저장하고 다음으로 |
| `r` 또는 ← | 이번 에피소드를 다시 녹화 |
| `q` 또는 Esc | 녹화 종료 |
| Ctrl+C | 비상 종료. 진행 중인 에피소드는 저장되지 않습니다 |

- 시간이 지나면 다음 단계로 자동으로 넘어갑니다.
- `pynput`을 설치하지 않았으므로 공식 터미널 키 입력 방식을 씁니다. 손쉬운 사용 권한이 필요 없습니다.

**종료 순서**(공식 v0.6.1 코드)
1. 각 에피소드 영상은 저장 시점(`save_episode`)에 바로 인코딩됩니다. 래퍼가 `video_encoding_batch_size=1`로 고정합니다.
2. 종료하면 공식 코드가 `finalize`로 데이터셋을 마무리한 뒤 팔 연결을 끊습니다.
3. 그다음 래퍼가 양팔 토크 해제를 다시 시도합니다.
4. 마무리하는 동안 팔로워는 토크를 유지하므로 받쳐 둡니다.

**녹화 중 카메라 보기**

```bash
./03_dataset/record.sh --resume --name <이름> --episodes 10 --view     # 창 자동(위 front / 아래 wrist)
./03_dataset/record.sh --resume --name <이름> --episodes 10 --mirror   # 내보내기만 → 다른 터미널에서:
swift tools/camera_view_dual.swift --mirror .tmp/live --no-focus   # 저장소 폴더에서
```

- 카메라를 다시 열지 않습니다. 녹화 프로세스가 이미 읽은 프레임(데이터셋에 저장되는 것과 같은 영상)을 약 10장/초로 `.tmp/live/`에 내보내고, 창은 그 파일만 읽습니다.
- 창은 키보드 초점을 가져가지 않습니다(`--no-focus`). 스페이스바·r·q는 녹화 터미널에서 누릅니다.
- `camera_view_dual.swift`를 `--mirror` 없이 띄우면 카메라를 직접 열어 녹화 카메라가 멈춥니다. 녹화 중에는 쓰지 않습니다.

**녹화 후 자동으로 하는 일**
- 저장된 데이터셋 검사(4번과 같은 검사). 에피소드별 검사는 **이번 녹화에서 저장된 에피소드만** 합니다.
  - 녹화 전후 `meta/info.json`의 `total_episodes` 차이로 이번에 저장된 에피소드를 찾습니다(예: 기존 50개 + 10개 → 50~59).
  - 기존 에피소드는 이미 검사했으므로 영상을 다시 디코드하지 않습니다. 데이터셋 수준 검사(열기·파일 존재·전체 행 수·task·stats)는 전체에 대해 합니다.
  - 새로 만든 데이터셋은 전부 새 에피소드이므로 전체를 검사합니다. 전체를 다시 보려면 `./03_dataset/inspect.sh datasets/<name>`을 실행합니다.
- 수집 기록 `datasets/<name>.so101.json` 작성. 다음 내용이 들어갑니다.
  - 코드 SHA, lock hash, 장치 ID, 보정 파일 sha256
  - 카메라·녹화 설정
  - 종료 결과, 루프 지연 경고 수, 검사 결과(이번에 저장된 에피소드 번호·검사한 에피소드 수 포함)
- 공식 `meta/`는 수정하지 않습니다.

**이어서 녹화**(같은 카메라·관절·fps만 가능)

```bash
./03_dataset/record.sh --resume --name <기존 이름> --episodes 2   # 2개를 '추가'로 녹화
```

- 기존 데이터를 덮어쓰거나 지우지 않습니다.
- 같은 이름이 있으면 새 녹화를 거부합니다. `--resume`을 쓰거나 다른 이름을 고릅니다.

**실패하면**

| 증상 | 조치 |
|---|---|
| 카메라 확인 실패 | `./03_dataset/cameras.sh`로 index를 다시 확인합니다(재연결하면 바뀜). 권한 창에서 허용했는지 확인합니다 |
| "Record loop is running slower" 경고 | 카메라 FPS, USB 대역, CPU 부하 때문입니다. 해상도를 낮추거나 `vcodec`을 바꿔 비교합니다. 경고 횟수는 기록에 남습니다 |
| 녹화 시작 때 `torchcodec ... cannot be loaded` 긴 경고 | 정상입니다. 외부 FFmpeg가 없어 공식 코드가 pyav 디코더로 대체합니다(인코딩은 PyAV 내장 FFmpeg) |
| 종료 후 토크 해제 실패 | [TELEOP.md](TELEOP.md) 3번과 같이 조치합니다 |

## 4. 검사(모터·카메라를 열지 않음)

```bash
./03_dataset/inspect.sh datasets/<name>                   # 전체 에피소드
./03_dataset/inspect.sh datasets/<name> --episodes 50-59  # 에피소드별 검사는 이 범위만(예: 3,5,7 / 0-2,10)
```

공식 `LeRobotDataset`(디코더 pyav)으로 다시 열어 다음을 확인합니다.
- `--episodes`를 주면 아래의 에피소드별 항목(프레임·행 범위·영상 디코드·NaN·샘플 읽기)은 그 범위만 봅니다. 파일 존재·관절 이름·전체 행 수·task는 항상 전체를 봅니다.
- 소요 참고: `so101_tape_to_box`(50 에피소드, 카메라 2대) 전체 디코드는 약 3.5분, 2개만은 약 9초였습니다.

- **파일**: 메타데이터가 가리키는 `data/`와 `videos/` 파일이 모두 있습니다.
- **관절**: `observation.state`·`action`이 float32, 형태 (6,)이고, 관절 이름과 순서가 공식 SO101(`shoulder_pan.pos` … `gripper.pos`)과 같습니다. 숫자 6개만 맞는다고 통과시키지 않습니다.
  - 값의 범위가 공식 단위와 맞는지 봅니다: 몸체는 도(°), gripper는 0~100.
- **에피소드 안 프레임**: `frame_index`가 0부터 연속입니다. timestamp가 단조 증가하고 간격이 1/fps입니다.
  - 에피소드마다 0부터 시작하는 것은 정상입니다.
- **행 범위**: 전역 index와 `dataset_from/to_index`가 이어집니다.
- **영상**: v3에서는 여러 에피소드가 MP4 하나를 함께 씁니다. 메타데이터의 `from/to_timestamp` 구간을 실제로 디코드해서 **프레임 수 = 에피소드 길이**인지 봅니다(누락·중복 검사).
- **값 이상**: NaN·Inf가 없습니다.
- **task**: 프레임의 `task_index`가 `meta/tasks.parquet`의 작업 설명과 연결됩니다.
- **공식 읽기 경로**: 공식 `__getitem__`으로 영상 디코드를 샘플링합니다.

**측정 한계**
- 공식 기록 규칙상 timestamp는 `frame_index/fps`로 저장됩니다. 실제 루프 지연은 녹화 로그의 "Record loop is running slower" 경고 수로 확인합니다.
- 카메라 프레임의 실제 촬영 시각은 저장되지 않습니다.

**결과**: 종료 코드 0=OK, 1=FAIL, 2=WARN만. 상세 기록은 `logs/inspect-<name>-<시각>.json`에 남습니다.

## 5. 연구실 PC로 옮기기

**맥에서**

```bash
./03_dataset/inspect.sh datasets/<name> --write-manifest
# → datasets/<name>.sha256   (전체 파일 sha256 목록)
# → datasets/<name>.so101.json (수집 기록 + 마지막 검사 결과)
```

**옮길 파일**: 데이터셋 폴더, `<name>.sha256`, `<name>.so101.json`을 함께 옮깁니다(외장 SSD 또는 `scp -r`).

**연구실 PC에서**

```bash
cd <옮긴 위치의 부모 폴더>
shasum -a 256 -c <name>.sha256        # Linux는 sha256sum -c <name>.sha256 도 같음
```

- 체크섬이 모두 OK인지 확인한 뒤, 같은 LeRobot v0.6.1과 dataset extra가 있는 환경에서 `LeRobotDataset("local/<name>", root=<경로>, video_backend="pyav")`로 엽니다.
- 연구실 PC의 dataset 환경(Linux lock에 dataset extra 추가)과 학습은 이 저장소의 이번 범위가 아닙니다. 별도로 승인받은 뒤 진행합니다.
- 이 맥에서 연구실 PC에 접속하거나 그곳에 설치하지 않습니다.

## 6. 이 맥에서 실제로 확인한 범위

| 항목 | 상태 |
|---|---|
| 합성 데이터셋 생성·재열기·검사·손상 탐지·체크섬 이관 시뮬레이션(`tools/verify_dataset.py`) | 확인함 — **합성 데이터, 실로봇 수집 아님** |
| 실카메라 프레임 읽기, 실로봇 녹화, 연구실 PC 읽기 | NOT VERIFIED |

상세 결과는 [macos_setup_report.md](macos_setup_report.md)를 보세요.
