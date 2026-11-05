# SO-101 프로젝트 지도 — 어떤 파일이 있고, 무엇을 실행하면 무엇이 생기나

> 기준: `~/so101-ws_for-mac` 실제 파일(2026-10-10 확인, 브랜치 `macos-support`). 계획 문서와 다르면 이 문서(실제 구현)가 맞다.

## 1. 전체 그림

- 이 프로젝트는 맥북(Apple Silicon)에 **SO-101 로봇팔 두 대(리더·팔로워)** 를 USB로 연결해 쓰기 위한 작업 폴더다.
- 사람이 **리더** 팔을 손으로 움직이면 **팔로워** 팔이 따라 움직인다(텔레옵). 그동안 카메라 영상과 관절 값을 **데이터셋**으로 저장할 수 있다.
- 실제로 로봇을 움직이는 코드는 직접 만들지 않고 **공식 LeRobot(v0.6.1)** 을 그대로 쓴다.
- 이 폴더에 있는 것은 공식 LeRobot을 감싸는 **설치기, 실행 스크립트, 안전 점검, 기록 장치**다.

```
 ① 초기 세팅            ② 텔레옵               ③ 데이터셋 생성              ④ 학습
 01_setup/        →     02_teleop/       →     03_dataset/          →     연구실 NVIDIA PC
 설치·포트·보정          리더→팔로워 추종         카메라+관절 녹화·검사           (이 프로젝트에 없음)
 [구현·실기 확인]        [구현·실기 확인]         [구현·합성 데이터로 확인]         [미구현·범위 밖]
```

- **학습은 이 프로젝트에 구현되어 있지 않다.** 데이터셋을 체크섬과 함께 복사해 가는 방법까지만 있다(`docs/DATASET.md` 5절).

**실행할 때의 구조**: 사용자는 번호 폴더의 `.sh`만 실행한다. 나머지는 자동으로 이어진다.

```
./01_setup/*.sh, ./02_teleop/run.sh, ./03_dataset/*.sh   ← 사용자가 실행
        │  (역할 인자 확인 후 그대로 넘김)
        ▼
scripts/so101  →  scripts/so101.py (+ so101_dataset.py)   ← 공통 래퍼: 설정 읽기·안전 점검·기록·종료 정리
        │
        ▼
.venv/bin/lerobot-*  (공식 LeRobot 명령: teleoperate·calibrate·setup-motors·record·find-cameras)
        │                                    ← 맥에서는 scripts/so101_launch.py를 거쳐 실행(래퍼가 비정상 종료해도 정리되게)
        ▼
USB 보드 → 모터 6개(팔마다) / 카메라
```

## 2. 폴더별 역할

| 폴더 | 쉬운 설명 | 들어가는 파일·결과 | 사용자가 직접 확인할 때 |
|---|---|---|---|
| `01_setup/` | 처음 준비: 설치·점검·USB 포트·모터 확인·보정 | 실행 스크립트 6개 | 처음 한 번, 그리고 문제가 생겼을 때 |
| `02_teleop/` | 리더→팔로워 추종 실행 | `run.sh` | 로봇을 움직일 때마다 |
| `03_dataset/` | 카메라 확인·녹화·데이터 검사 | `cameras.sh`, `record.sh`, `inspect.sh` | 데이터를 모을 때마다 |
| `configs/` | 설정 파일. `*.example.yaml`은 견본, `*.local.yaml`은 이 PC의 실제 값 | `robot.local.yaml`(포트·팔 이름), `cameras.local.yaml`, `recording.local.yaml` | 포트·카메라·녹화 조건을 바꿀 때 |
| `calibration/` | 팔별 보정 결과(공식 형식 JSON) | `robots/so_follower/so101_follower.json`, `teleoperators/so_leader/so101_leader.json` | 보정 후 파일이 생겼는지, 백업할 때 |
| `datasets/` | 녹화한 데이터셋. **첫 녹화 때 생김(아직 없음)** | `datasets/<이름>/` + `<이름>.so101.json`(수집 기록) + `<이름>.sha256`(체크섬) | 녹화 후, 연구실 PC로 옮길 때 |
| `logs/` | 모든 실행 기록 | `runs.jsonl`(실행 요약 한 줄씩), `teleop-*.log`, `calibrate-*.log`, `inspect-*.json` | 결과·오류를 확인할 때 |
| `scripts/` | 공통 래퍼와 설치기(실제 동작의 중심) | `so101`, `so101.py`, `so101_dataset.py`, `so101_launch.py`, `install_macos.sh`, `install.sh`(Linux) | 보통은 열어 볼 필요 없음 |
| `lock/` | 설치 버전 고정표 | `lerobot.env`(공통), `macos-arm64/`(맥), 나머지는 Linux용 | 버전을 확인할 때 |
| `tools/` | 로봇 없이 하는 검증 도구 | `verify_offline.py`, `verify_dataset.py`, `lock_tools.py`, `compare_envs.py` | 코드를 바꾼 뒤 검증할 때 |
| `docs/` | 매뉴얼·상태·보고서 | `SETUP.md`, `TELEOP.md`, `DATASET.md`, `CURRENT_STATE.md` 등 | 절차와 현재 상태를 볼 때 |
| `.venv/` (1.0 GB) | Python 가상환경(설치된 패키지 67개) | 공식 `lerobot-*` 명령 포함 | 직접 건드리지 않음 |
| `.tools/` (106 MB) | 이 프로젝트 전용 uv·Python 3.12.15 | `uv/`, `python/` | 직접 건드리지 않음 |
| `.cache/` (약 1 GB) | 다운로드 캐시 | `uv/`, `huggingface/` | 지워도 다시 받아짐 |
| `external/lerobot/` (31 MB) | 공식 LeRobot 원본(고정 버전, 비교·참고용) | 수정 금지 | 공식 코드를 찾아볼 때 |
| `.tmp/` | 임시 파일·검증 결과 | 합성 시험 데이터셋(`verify_dataset/`), 검증 로그 | 지워도 됨 |

## 3. 사용자가 실제로 만지는 것

| 질문 | 답 |
|---|---|
| USB 포트와 리더·팔로워 이름은 어디에? | `./01_setup/ports.sh` → 안내대로 리더·팔로워 USB를 차례로 꽂으면 `configs/robot.local.yaml`에 저장된다. 저장되는 값: `leader/follower`의 `port`(예: `/dev/cu.usbmodem…`), `id`(팔 이름 = 보정 파일 이름, 현재 `so101_leader`·`so101_follower`), `usb`(보드 확인 정보). 직접 고쳐도 되지만 마법사 사용을 권장 |
| 모터 ID(1~6)는 어떻게 설정? | `./01_setup/motors.sh follower` 또는 `leader`(공식 `lerobot-setup-motors`). **응답이 없거나 ID가 겹칠 때만** 한다. 확인은 `./01_setup/probe.sh <역할>`. 지금 두 팔은 이미 정상이라 하지 않았다 |
| 보정 결과는 어디에? 어떻게 재사용? | `./01_setup/calibrate.sh <역할>` → `calibration/…/<id>.json`에 저장. 텔레옵·녹화 때 같은 `id`의 파일을 자동으로 쓴다. 시작 전에 래퍼가 파일과 모터 값이 같은지 확인하고, 다르면 시작하지 않는다(그때는 다시 보정). 다른 팔의 파일을 복사해 쓰지 않는다 |
| 카메라·FPS·작업 설명·에피소드 수는? | 카메라: `configs/cameras.local.yaml`(`index_or_path`, `width`, `height`, `fps`). 녹화: `configs/recording.local.yaml`(`name`, `task`, `fps`, `episode_time_s`, `reset_time_s`, `num_episodes`, `vcodec`). 처음엔 `configs/*.example.yaml`을 복사해 만든다. 명령행 `--name --task --episodes`로 한 번만 바꿀 수도 있다 |
| 텔레옵·녹화는 어떤 파일? | 텔레옵: `./02_teleop/run.sh`(`--dry-run`, `--time-s 30`). 녹화: `./03_dataset/record.sh`(`--dry-run`, `--resume`). 녹화도 리더·팔로워를 움직이므로 **둘을 동시에 실행하지 않는다** |
| 녹화 데이터·오류 로그는 어디서? | 데이터: `datasets/<name>/` → 검사는 `./03_dataset/inspect.sh datasets/<name>`. 로그: `logs/runs.jsonl`(각 실행의 종료 코드·루프 Hz·토크 해제 결과), `logs/<명령>-<시각>.log`(공식 프로그램 화면 출력 전체) |

**언제 하는 작업인가**

| 구분 | 작업 |
|---|---|
| 처음 한 번 | `./01_setup/install.sh` → `./01_setup/ports.sh` → `probe.sh` → (필요 시) `motors.sh` → `calibrate.sh` → `configs/cameras.local.yaml`·`recording.local.yaml` 만들기 |
| 바뀌면 다시 | 보드를 다른 보드로 바꿈·포트를 못 찾음 → `ports.sh` / 모터 교체·ID 오류 → `motors.sh` / 팔 분해·조립, "보정 불일치" → `calibrate.sh` / 카메라를 다시 꽂음(번호가 바뀔 수 있음) → `cameras.sh` / 설치가 깨짐 → `install.sh --repair` |
| 매번 | `./01_setup/doctor.sh --hardware`(점검, 포트를 열지 않음) → `./02_teleop/run.sh` 또는 `./03_dataset/record.sh` → 녹화했다면 `inspect.sh` |

종료는 항상 **리더를 쉬는 자세로 → 팔로워를 손으로 받치기 → `Ctrl+C`** 순서다. 응답이 없으면 팔로워 전원을 뽑는다.

## 4. 데이터셋 안에는 무엇이 들어가나

공식 LeRobotDataset v3 형식이다. 아래는 **합성 시험 데이터**(`.tmp/verify_dataset/SYNTHETIC_TEST_so101_av1`)를 열어서 확인한 내용이다. 로봇 없이 만든 가짜 관절 값과 무늬 영상, 2 에피소드 × 45프레임, 30 fps다. **실제 로봇으로 녹화한 데이터셋은 아직 없다.**

```
datasets/<이름>/
├─ meta/                       ← "설명서": 이 데이터셋이 어떻게 생겼는지
│  ├─ info.json                   fps, 로봇 종류(so_follower), 에피소드·프레임 수, 각 항목의 이름·형태
│  ├─ tasks.parquet               작업 설명 문장 목록(번호 ↔ 문장)
│  ├─ episodes/…parquet           에피소드별 길이, 데이터·영상 파일 안에서의 위치(시작/끝)
│  └─ stats.json                  값의 평균·최소·최대(학습 때 정규화에 사용)
├─ data/chunk-000/file-000.parquet ← "표": 프레임 한 줄씩(모든 에피소드가 한 파일에 이어서)
└─ videos/observation.images.front/chunk-000/file-000.mp4 ← "영상": 카메라별 MP4(에피소드들이 이어 붙음)
```

**data 표의 한 줄 = 한 순간(프레임)**

| 열 | 뜻 |
|---|---|
| `observation.state` | 그 순간 **팔로워**의 실제 관절 값 6개(shoulder_pan … gripper, 몸체는 도·그리퍼는 0~100) |
| `action` | 그 순간 **리더가 내린 명령**(팔로워가 가야 할 목표) 6개 |
| `timestamp` | 에피소드 시작부터의 시간(초). 에피소드마다 0부터 시작 |
| `frame_index` / `episode_index` / `index` | 에피소드 안 번호 / 몇 번째 에피소드 / 전체 통틀어 번호 |
| `task_index` | 작업 설명 번호 → `meta/tasks.parquet`의 문장 |

**함께 묶이는 방식**
- 영상은 표에 들어가지 않는다. `meta/episodes`에 적힌 "이 에피소드는 MP4의 몇 초부터 몇 초까지"와 `timestamp`로 **같은 순간의 영상 프레임을 찾는다**.
  - 합성 데이터에서는 에피소드 0이 0.0~1.5초, 에피소드 1이 1.5~3.0초였다.
- 작업 설명은 문장 대신 번호(`task_index`)로 저장된다.
- 데이터셋 폴더 옆에 이 프로젝트가 만드는 파일 두 개가 생긴다. 공식 폴더 안은 건드리지 않는다.
  - `<이름>.so101.json`: 언제·어떤 팔(보정 파일 hash)·어떤 카메라 설정으로 모았는지
  - `<이름>.sha256`: 옮길 때 깨지지 않았는지 확인하는 체크섬

## 5. 보관 구분

| 구분 | 무엇 | 어디에 보관 |
|---|---|---|
| **GitHub에 저장**(코드·견본·버전표·문서) | `01_setup/` `02_teleop/` `03_dataset/` `scripts/` `tools/` `lock/` `docs/` `configs/*.example.yaml` `AGENTS.md` `README.md` `.gitignore` | Git(브랜치 `macos-support`) |
| **따로 보관**(이 PC·이 팔에만 해당, Git 제외) | `calibration/`(보정 — 백업 권장), `configs/*.local.yaml`(포트·팔 이름·카메라·녹화 설정), `datasets/`(녹화 데이터 — 외장 저장소·연구실 PC로 복사), 필요하면 `logs/` | 외장 저장소·백업 압축(`tar czf …`) |
| **다시 만들 수 있음**(지워도 됨) | `.venv/` `.tools/` `.cache/` `external/` → `./01_setup/install.sh`로 복구. `.tmp/`, `__pycache__/`, `configs/*.local.yaml.bak-*`(설정 백업) | 보관 불필요 |

## 6. 현재 상태(2026-10-09 작업 기준)

| 확인 완료 | 아직 안 됨 |
|---|---|
| 맥 설치·점검(doctor FAIL 0) | 3분 연속 추종(최장 157초까지 함) |
| USB 포트 인식, 양팔 모터 6/6 응답 | 관절 방향 관찰 기록, 모터 전압·어댑터 확인표 |
| 양팔 보정(일치 확인) | 카메라 선택·실카메라 시험 |
| 30초 추종 60 Hz, 119초·157초 추종, 종료 후 토크 해제 성공, 재실행 | 실제 로봇 녹화, 연구실 PC로 옮겨 읽기 |
| 로봇 없는 검증 116/116, 합성 데이터셋 검증 15/15 | 학습(이 프로젝트 범위 밖), 이번 변경의 Ubuntu 실행 확인 |

---

## 부록. 파일별 역할

표기: **실행**=사용자가 직접 실행 / **수정**=사용자가 값을 고침 / **자동**=프로그램이 만듦 / **참조**=읽기만 함

### 실행 스크립트(사용자 입구)

| 파일 | 한 줄 역할 | 구분 |
|---|---|---|
| `01_setup/install.sh` | 설치(맥이면 `scripts/install_macos.sh`, Linux면 `scripts/install.sh`). `--repair`, `--reset-venv` | 실행 |
| `01_setup/doctor.sh` | 장치를 열지 않는 점검. `--hardware`면 포트·보드 정보·보정 파일까지 확인 | 실행 |
| `01_setup/ports.sh` | USB 포트 지정 마법사. `--list`(현재 매핑), `--find-port`(공식 방식) | 실행 |
| `01_setup/probe.sh` | 모터 6개 응답·위치·보정 일치를 **읽기만** 함(`leader`/`follower`/`both`) | 실행 |
| `01_setup/motors.sh` | 공식 모터 ID·통신속도 설정(필요한 팔만) | 실행 |
| `01_setup/calibrate.sh` | 공식 보정 | 실행 |
| `02_teleop/run.sh` | 공식 텔레옵 + 시작 전 점검 + 끝난 뒤 양팔 토크 해제 재시도 | 실행 |
| `03_dataset/cameras.sh` | 공식 카메라 탐색, `--test <이름>`으로 설정한 카메라 시험 | 실행 |
| `03_dataset/record.sh` | 공식 녹화(Hub 업로드 없음 고정) + 점검 + 녹화 후 자동 검사 | 실행 |
| `03_dataset/inspect.sh` | 데이터셋을 다시 열어 검사, `--write-manifest`로 체크섬 생성 | 실행 |
| `01_setup/README.md` 등 3개 | 각 폴더의 짧은 안내 | 참조 |

### 설정

| 파일 | 한 줄 역할 | 구분 |
|---|---|---|
| `configs/robot.example.yaml` | 로봇 설정 견본 | 참조 |
| `configs/robot.local.yaml` | 이 PC의 포트·팔 이름·USB 정보·fps·이동량 제한 | 자동(ports.sh) / 수정 |
| `configs/robot.local.yaml.bak-*` | ports.sh가 저장 전에 만드는 이전 설정 백업 | 자동 |
| `configs/cameras.example.yaml` | 카메라 설정 견본(640×480·30 fps) | 참조 → 복사해 `cameras.local.yaml` |
| `configs/recording.example.yaml` | 녹화 설정 견본(20초 × 2개) | 참조 → 복사해 `recording.local.yaml` |

### 공통 래퍼·설치(scripts/)

| 파일 | 한 줄 역할 | 구분 |
|---|---|---|
| `scripts/so101` | 공통 진입점: 환경을 깨끗이 하고 `.venv`의 Python으로 `so101.py` 실행 | 참조 |
| `scripts/so101.py` | 핵심 래퍼: 설정 검증, 점검(doctor), 포트 마법사, probe, 공식 명령 실행·기록, 종료 후 토크 해제 | 참조 |
| `scripts/so101_dataset.py` | 녹화·카메라 설정 읽기, 공식 녹화 명령 인자 만들기, 데이터셋 검사 | 참조 |
| `scripts/so101_launch.py` | 맥 전용: 래퍼가 갑자기 죽어도 공식 프로그램이 정리하고 끝나게 하는 실행기 | 참조 |
| `scripts/entry_common.sh` | 번호 폴더 스크립트들의 공통 부분(역할 인자 확인) | 참조 |
| `scripts/install_macos.sh` | 맥 설치기(uv·Python·공식 LeRobot·패키지를 작업 폴더 안에만 설치) | 실행(install.sh가 호출) |
| `scripts/install.sh` | Ubuntu 설치기(기존 그대로) | Linux에서 실행 |

### 버전 고정(lock/)

| 파일 | 한 줄 역할 | 구분 |
|---|---|---|
| `lock/lerobot.env` | 공통: LeRobot 버전·고정 SHA, uv 버전 | 참조 |
| `lock/macos-arm64/platform.env` | 맥: uv 파일 체크섬, Python 3.12.15, 최소 macOS | 참조 |
| `lock/macos-arm64/pyproject.toml` | 맥: 설치할 패키지 정의(`lerobot[feetech,dataset]`, torch) | 참조 |
| `lock/macos-arm64/uv.lock` | 맥: 67개 패키지의 정확한 버전·해시(그대로만 설치) | 참조 |
| `lock/pyproject.toml`, `lock/uv.lock` | Ubuntu용(변경 없음) | 참조 |

### 검증 도구(tools/)

| 파일 | 한 줄 역할 | 구분 |
|---|---|---|
| `tools/verify_offline.py` | 로봇 없이 가짜 모터로 안전 동작 검증 | 실행(코드 변경 후) |
| `tools/verify_dataset.py` | 합성 데이터셋을 만들고 검사가 제대로 잡는지 검증 | 실행(코드 변경 후) |
| `tools/lock_tools.py` | lock 비교·점검(유지보수용) | 참조 |
| `tools/compare_envs.py` | 두 설치 환경이 같은지 비교(재현 확인용) | 참조 |

### 문서(docs/)와 루트

| 파일 | 한 줄 역할 | 구분 |
|---|---|---|
| `README.md` | 프로젝트 소개와 세 단계 명령 | 참조 |
| `AGENTS.md` | 작업 규칙(무엇을 하면 안 되는지, 실기 조건) | 참조 |
| `docs/SETUP.md` · `TELEOP.md` · `DATASET.md` | 단계별 매뉴얼(연결 → 명령 → 확인 → 실패 시) | 참조 |
| `docs/PROJECT_MAP.md` | 이 문서 | 참조 |
| `docs/CURRENT_STATE.md` | 현재 상태 기록(Ubuntu + macOS, 실기 결과) | 수정(결과 기록) |
| `docs/macos_setup_report.md` | 맥 설치·검증 결과 보고서 | 참조 |
| `docs/HARDWARE.md` | 실물 확인표·포트·probe·보정 기록 | 수정(실물 확인 기록) |
| `docs/REFERENCES.md` | 공식 출처·고정 버전·라이선스 | 참조 |
| `docs/REPRODUCE.md` | Ubuntu PC 재현 절차 | 참조 |
| `docs/so101_macos_plan.md` · `.original.md` · `so101_macos_execution_request.md` | 계획(실행 반영판·원본)과 실행 요청 | 참조 |
| `.gitignore` | Git에서 제외할 것(환경·캐시·보정·데이터셋·로그·로컬 설정) | 참조 |

### 실행하면 생기는 결과물

| 경로 | 언제 생기나 |
|---|---|
| `calibration/robots/so_follower/<id>.json`, `calibration/teleoperators/so_leader/<id>.json` | `calibrate.sh` |
| `datasets/<이름>/`, `<이름>.so101.json` | `record.sh` |
| `datasets/<이름>.sha256` | `inspect.sh --write-manifest` |
| `logs/runs.jsonl` | 모든 명령(한 줄씩 추가) |
| `logs/teleop-*.log`, `calibrate-*.log`, `setup-motors-*.log`, `record-*.log`, `find-cameras-*.log` | 각 공식 명령 실행 |
| `logs/inspect-*.json` | `inspect.sh` |
| `logs/cameras-*/` | `cameras.sh`(확인용 사진) |
| `.venv/so101_install_stamp.json` | `install.sh`(설치 기준 기록) |
