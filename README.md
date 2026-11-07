# so101-ws_for-mac

SO-ARM101(SO-101) 모방학습을 **맥북(Apple Silicon) 한 대에서** 처음부터 끝까지 하는 작업 공간.
보정·카메라 → 텔레옵 → 데이터 녹화/업로드/다운로드 → 학습 → 로봇에서 추론까지 모두 `scripts/` 로 한다.

## 가장 쉬운 세팅: AI 에이전트에게 맡기기

Claude Code 나 Codex 에 **이 저장소 주소를 붙여 넣고 "이 레포대로 세팅해줘"** 라고만 보낸다.

- 에이전트는 [AGENTS.md](AGENTS.md)를 따라 다음을 한다. Claude Code 는 [CLAUDE.md](CLAUDE.md)가 같은 내용을 불러온다.
  1. 설치
  2. 이 PC 값 자동 설정: Hugging Face 계정, 팔 포트, 카메라 번호
  3. 점검
- 사람이 직접 하는 일은 세 가지다.
  - Hugging Face 로그인: 토큰 입력
  - 팔 보정: 손으로 팔을 움직이는 일
  - 팔이 움직이는 명령 실행

저장소에는 특정 사람의 계정·포트·카메라·보정 값이 없다. 모두 각자의 맥에서 `scripts/setup_local.sh` 가 찾아 `config/so101.local.env` 에 저장한다(Git 에 올라가지 않음).

## 구성

- **LeRobot**: GitHub `huggingface/lerobot` 을 `lerobot/` 에 clone 해 editable 설치한다. 검증한 커밋 `d490e472`(0.7.1, 2026-11-05)로 고정.
- **conda 환경 `so-arm_ws`**: Python 3.12.16, torch 2.15.0(Apple GPU = `mps`), torchcodec 0.17.0, ffmpeg 9.0.2, bash 5
- **패키지 버전**: `requirements/constraints.txt` 로 고정
- **대상**: macOS 14 이상, Apple Silicon(M1~)
  - `install.sh` 는 Ubuntu 24.04 도 감지한다(원본 so-arm101_ws 동작). 이 저장소에서 확인한 것은 macOS 다.

## 직접 세팅하기

### 1) 설치 (처음 한 번, 약 2~10분)

```bash
xcode-select --install                                                 # git 이 없을 때만
git clone https://github.com/<user>/so101-ws_for-mac.git ~/so101-ws_for-mac   # <user> = 이 저장소를 올린 GitHub 계정
bash ~/so101-ws_for-mac/scripts/install.sh
```

- conda 가 없으면 Miniforge 를 `~/miniforge3` 에 설치한다. 버전을 고정하고 sha256 을 확인한다.
- `~/.zshrc` 는 고치지 않는다(`conda init` 안 함).
- 다시 실행해도 안전하다(있는 것은 건너뛴다).

### 2) 이 PC 에 맞게 자동 설정

두 팔의 USB 와 전원(follower 12V, leader 5V), 카메라 2대를 연결한 뒤 실행한다.

```bash
cd ~/so101-ws_for-mac
bash scripts/hub.sh login                 # Hugging Face 로그인(토큰 입력, 한 번). 업로드할 때 필요
bash scripts/setup_local.sh               # 계정·팔 포트 자동 저장 → config/so101.local.env
source scripts/activate.sh
python scripts/cameras.py snap --all      # 카메라 번호마다 사진 1장 → outputs/cameras/index<N>_*.jpg
bash scripts/setup_local.sh --front 1 --wrist 0   # 사진을 보고 front(작업면)·wrist(그리퍼) 번호 저장
```

- **계정**: 로그인한 Hugging Face 계정을 `HF_USER` 로 저장한다. 데이터셋·모델 이름 앞에 붙는다.
- **팔 포트**
  - 각 보드의 모터 전압을 **읽기만** 해서 follower(약 12V)와 leader(약 5~6V)를 구분한다. 모터는 움직이지 않는다.
  - 맥에서 포트 이름은 `/dev/cu.usbmodem<보드 시리얼>` 이다.
  - 전원이 꺼져 있으면 구분하지 못한다. 그때는 `lerobot-find-port` 로 하나씩 찾아 `--follower <포트> --leader <포트>` 로 지정한다.
- **카메라**
  - macOS 는 카메라를 **번호**(0, 1, ...)로 연다.
  - 같은 모델 카메라 2대는 이름으로 구분되지 않는다.
  - 번호는 재연결·재부팅 뒤 바뀔 수 있다. 녹화·추론 전에 `python scripts/cameras.py snap` 으로 확인한다.
- 처음 카메라를 열 때 macOS 가 터미널(또는 VS Code)의 카메라 권한을 묻는다. 허용한다.
- 끝에 **"남은 일"** 이 나오면 그대로 따른다.

### 3) 보정 (팔마다 한 번, 직접)

```bash
bash scripts/calibrate.sh follower     # → calibration/robots/so_follower/so101_follower.json
bash scripts/calibrate.sh leader       # → calibration/teleoperators/so_leader/so101_leader.json
bash scripts/check_devices.sh          # 포트·카메라·보정 파일 확인(장치를 열지 않음) → FAIL 0
```

- 진행은 LeRobot 안내를 따른다.
  1. 모든 관절을 가운데 자세에 두고 Enter
  2. wrist_roll 을 뺀 관절을 끝에서 끝까지 움직이고 Enter
- 기존 보정 파일이 있으면 LeRobot 이 묻는다. **Enter = 기존 파일 사용**, `c` + Enter = 새로 보정. 이전 파일은 `calibration/backup/` 에 백업된다.
- 새로 조립한 팔(모터 ID 미설정)은 먼저 `bash scripts/setup_motors.sh follower|leader` 를 실행한다.

**다른 맥에서 쓰던 같은 팔**이면 보정과 설정을 묶음 파일 하나로 옮길 수 있다.

```bash
bash scripts/migrate.sh export                        # 예전 맥: ~/Downloads/so101_local_bundle_<날짜>.tar.gz
bash scripts/migrate.sh import ~/Downloads/so101_local_bundle_<날짜>.tar.gz   # 새 맥
bash scripts/setup_local.sh                           # 새 맥에서 포트·카메라 번호 다시 확인
```

## 새 터미널마다

```bash
source ~/so101-ws_for-mac/scripts/activate.sh     # conda 환경 + 설정 불러오기 (zsh·bash 모두)
cd ~/so101-ws_for-mac
```

- `scripts/*.sh` 는 이 과정을 알아서 하므로 생략해도 된다. `lerobot-*` 명령이나 `python scripts/*.py` 를 직접 쓸 때는 필요하다.
- 모든 `.sh` 가 지원하는 옵션
  - `--help`
  - `--dry-run`: 명령만 출력
  - `--check`: 장치를 열지 않고 LeRobot 이 해석한 설정만 출력
  - `--` 뒤의 인자는 lerobot 명령에 그대로 넘긴다.

## 폴더

```
so101-ws_for-mac/
├── config/so101.env          ← 공용 기본값(카메라 해상도·저장 위치·녹화/학습 기본값)
├── config/so101.local.env    ← (git 제외) 이 PC 값: HF_USER, 팔 포트, 카메라 번호 — setup_local.sh 가 만듦
├── calibration/              ← (git 제외) 팔 보정 파일
├── scripts/                  ← 모든 작업 스크립트
├── requirements/             ← 고정 패키지 버전
├── lerobot/                  ← (설치 때 생성) LeRobot 소스
├── data/                     ← (git 제외) 데이터셋. 녹화: data/<HF_USER>/<name>, 허브에서 받은 것: data/hub/
├── models/                   ← (git 제외) 허브에서 받은 모델: models/<repo 이름>/
└── outputs/                  ← (git 제외) 학습 결과 outputs/train/<job>/, 카메라 사진 outputs/cameras/
```

## 카메라

```bash
python scripts/cameras.py list         # 열리는 카메라 번호와 front/wrist 대응
python scripts/cameras.py snap         # front/wrist 한 장씩 → outputs/cameras/
python scripts/cameras.py snap --all   # 열리는 모든 번호 한 장씩(어느 번호가 front/wrist 인지 찾기)
python scripts/cameras.py live         # 실시간 창(front | wrist). s = 저장, q = 종료
python scripts/cameras.py live --overlay <HF_USER>/<학습 데이터셋>
                                       # 학습 데이터의 front 화면을 반투명으로 겹쳐(o 로 켜고 끔) 카메라 위치를 학습 때와 맞춘다
```

- 설정: 640×480, 30fps, front 180° 회전(`config/so101.env`).
- macOS 는 MJPG 지정을 지원하지 않아 쓰지 않는다.
- 카메라는 한 프로그램만 열 수 있다. 창을 닫고 teleop/record/rollout 을 실행한다.

## 텔레옵 (leader → follower)

```bash
bash scripts/teleop.sh                 # 팔만
bash scripts/teleop.sh --display       # 카메라까지 열고 Rerun 창에 영상·관절값 표시
```

Ctrl+C 로 멈추면 follower 토크가 꺼져 팔이 힘없이 내려온다. **손으로 받친다.**

## 데이터셋 만들기·올리기·받기

```bash
# 녹화 (로컬 data/<HF_USER>/ball_to_bowl 에 저장)
bash scripts/record.sh --name ball_to_bowl --task "Pick up the ball and place it in the bowl" --episodes 20
# 같은 데이터셋에 10개 더
bash scripts/record.sh --name ball_to_bowl --task "Pick up the ball and place it in the bowl" --episodes 10 --resume
# 녹화 옵션: --episode-time 30 --reset-time 10 --display --push(끝나면 업로드) --private

bash scripts/replay.sh --dataset ball_to_bowl --episode 0          # follower 로 다시 재생
bash scripts/hub.sh upload-dataset ball_to_bowl [--private]        # 허브에 올리기
bash scripts/hub.sh download-dataset <사용자>/<데이터셋> [--revision <commit>]   # 허브에서 받기 → data/hub/
bash scripts/hub.sh list                                           # 로컬 데이터셋·모델 목록
```

- **녹화 중 키**: 터미널이 포커스된 상태에서 누른다.
  - **n**(또는 →) = 이번 에피소드 끝내고 다음
  - **r**(또는 ←) = 다시
  - **q**(또는 ESC) = 종료
  - 터미널에 입력 모니터링 권한이 없으면 화살표·ESC 는 안 먹고 n/r/q 만 된다(LeRobot 이 자동 전환).
- 이름에 `/` 가 없으면 `HF_USER` 가 앞에 붙는다. `HF_USER` 가 비어 있으면 로그인 계정을 쓴다.
- 녹화 기본값(fps 30, 에피소드 30초, 정리 10초)은 `config/so101.env` 의 `SO101_RECORD_*` 다.
- 녹화·추론·텔레옵·학습 중에는 맥이 잠자기에 들어가지 않는다(`caffeinate`).

## 학습

```bash
bash scripts/train.sh --dataset ball_to_bowl --job act_ball                  # ACT, 100k step, batch 8 (장치 자동: mps)
bash scripts/train.sh --dataset ball_to_bowl --job act_ball --push act_ball  # 끝나면 허브 업로드
bash scripts/train.sh --job act_ball --resume                                # 끊긴 학습 이어서
bash scripts/train.sh --dataset ball_to_bowl --job act_ft --from models/<모델>/checkpoints/100000/pretrained_model   # fine-tune
bash scripts/train.sh ... -- --policy.chunk_size=50 --num_workers=4          # lerobot-train 인자 직접 추가

bash scripts/hub.sh upload-model act_ball <HF_USER>/act_ball [--private]     # 학습 결과(last) 업로드
bash scripts/hub.sh download-model <사용자>/<모델> --step 100000             # 모델 받기 → models/
```

- 결과는 `outputs/train/<job>/checkpoints/<step>/pretrained_model` 에 저장된다. 마지막은 `checkpoints/last`.
- **맥 학습 속도**
  - Apple GPU(MPS)는 느리다. M4 MacBook Air 기준 ACT batch 8 이 약 1.35 s/step 이다.
  - 그래서 10만 스텝 학습은 NVIDIA GPU PC 를 권장한다. 맥은 짧은 시험이나 fine-tune 에 쓴다.
- `download-model` 은 optimizer 상태를 받지 않는다. 이어서 학습할 거면 `--with-optimizer` 를 붙인다.

## 추론 (로봇에서 정책 실행)

```bash
# 로봇 없이 먼저 점검: 데이터셋 에피소드를 넣어 예측 action 을 정답과 비교 + 추론 시간
python scripts/check_policy.py --policy act_ball --dataset ball_to_bowl

# 로봇에서 실행 (Ctrl+C 로 종료 → 팔이 시작 자세로 천천히 돌아간다)
bash scripts/rollout.sh --policy act_ball                         # 학습한 모델 (outputs/train/act_ball)
bash scripts/rollout.sh --policy <모델 폴더 이름> --step 100000   # 받은 모델 (models/...)
bash scripts/rollout.sh --policy <사용자>/<모델> --step 100000    # 허브 repo → models/ 로 받은 뒤 실행
```

| 옵션 | 뜻 |
|---|---|
| `--n-action-steps 20` | ACT 는 한 번에 100개(chunk)를 예측한다. 그중 N 개를 실행한 뒤 다시 추론한다(기본 100) |
| `--ensemble [0.01]` | 매 프레임 추론 + 겹치는 예측 가중 평균. 부드럽지만 맥에서는 추론이 무거워진다(M4 MPS 약 66 ms/프레임) |
| `--duration 60` | 60초 뒤 종료(기본 0 = 무제한) |
| `--task "..."` | 작업 문장. 비우면 학습 데이터셋에서 찾는다(ACT 는 무시) |
| `--record NAME --episodes 10` | 실행을 데이터셋 `<HF_USER>/rollout_NAME` 으로 기록 |
| `--display` | Rerun 창에 카메라·관절값·action 표시 |
| `--cpu` | MPS 대신 CPU |
| `--check` | 로봇을 열지 않고 해석된 설정만 출력 |

## 스크립트

| 스크립트 | 하는 일 |
|---|---|
| `install.sh` | 설치(Miniforge·conda 환경·LeRobot·패키지) |
| `setup_local.sh` | 이 PC 값(계정·팔 포트·카메라 번호) 저장 → `config/so101.local.env` |
| `find_arms.py` | 팔 포트 찾기 + 모터 전압으로 follower/leader 구분(읽기 전용) |
| `migrate.sh` | 보정·이 PC 설정을 다른 맥으로 옮기기 |
| `activate.sh` | (source) conda 환경 + 설정 |
| `check_env.py` / `check_devices.sh` | 소프트웨어·GPU 점검 / 포트·카메라·보정 점검 |
| `cameras.py` | 카메라 번호·사진·실시간 창·학습 화면 겹치기 |
| `calibrate.sh` / `setup_motors.sh` | 보정 / 모터 ID 설정 |
| `teleop.sh` | leader → follower |
| `record.sh` / `replay.sh` | 데이터 녹화 / 재생 |
| `hub.sh` | 로그인, 데이터셋·모델 받기/올리기, 로컬 목록 |
| `train.sh` | 학습(새로, 이어서, fine-tune) |
| `check_policy.py` | 로봇 없이 정책 점검 |
| `rollout.sh` | 로봇에서 정책 실행(+ 기록) |

## 문제 해결

| 증상 | 해결 |
|---|---|
| `conda: command not found` | `source ~/so101-ws_for-mac/scripts/activate.sh` (conda init 없이 동작) |
| `설정 비어 있음` / `설정되지 않았다` | `bash scripts/setup_local.sh` (팔·카메라 연결 후) |
| 팔 포트를 못 찾음 | USB·전원 확인 → `ls /dev/cu.usbmodem*` → `bash scripts/setup_local.sh --redetect` |
| follower/leader 구분 실패 | 두 팔 전원이 모두 켜졌는지 확인. 안 되면 `lerobot-find-port` → `--follower`/`--leader` 로 지정 |
| front/wrist 화면이 바뀜 | 카메라 번호가 바뀐 것. `python scripts/cameras.py snap --all` → `setup_local.sh --front N --wrist M` |
| 카메라가 하나도 안 열림 | 시스템 설정 → 개인정보 보호 및 보안 → 카메라에서 터미널·VS Code 허용 |
| `Failed to open OpenCVCamera` | 다른 프로그램(카메라 창·화상회의)이 카메라를 쓰는 중 |
| 녹화 중 화살표 키가 안 먹음 | 터미널에서 n / r / q 를 쓴다 |
| `bash 4 이상이 필요하다` | `bash scripts/install.sh` 를 다시 실행(conda 환경에 bash 5 설치) |
| `Hugging Face 사용자 이름을 모른다` | `bash scripts/hub.sh login` → `bash scripts/setup_local.sh` |
| `Mismatch between calibration values ...` | 모터에 저장된 값과 보정 파일이 다르다(다른 PC에서 다시 보정한 경우 등). Enter 를 누르면 파일 값을 모터에 쓴다. 의심되면 다시 보정 |
| `Record loop is running slower (29.8 Hz)` | 한 바퀴가 33.3 ms 를 조금 넘은 것. 가끔이면 무시 |
| 모델 동작이 조금씩 빗나감 | `cameras.py live --overlay <학습 데이터셋>` 으로 카메라 위치를 학습 때와 맞춘다. 보정 차이도 의심 |
| 시작할 때 `objc[...]: Class AVFFrameReceiver is implemented in both ...` | FFmpeg 라이브러리가 여러 패키지에 들어 있어 나오는 macOS 경고. 동작에는 영향이 없었다 |

## 참고

- 원본: [so-arm101_ws](https://github.com/<user>/so-arm101_ws)(Ubuntu 24.04 용)를 macOS 용으로 옮겼다.
  - macOS 분기: 설치·포트·카메라 번호·MPS·zsh·bash 5·caffeinate
  - 추가: PC 값 자동 설정(`setup_local.sh`)
- LeRobot 0.6.1 로 만든 데이터셋(v3.0)·ACT 모델은 0.7.1 에서 그대로 로드·추론된다.
- LeRobot 0.7 에서 바뀐 점
  - Feetech 모터 드라이버가 rustypot 으로 바뀌었다(보정 파일 형식은 같음).
  - 학습 로그 도구가 wandb 에서 trackio 로 바뀌었다.
  - `lerobot-record` 는 이름 뒤에 날짜를 붙인다(`record.sh` 는 이름 그대로 저장).
  - 허브 데이터셋은 `data/hub/` 리비전 캐시에 저장된다.
