# 에이전트 지시 (Claude Code / Codex 공통)

사용자가 이 저장소 링크와 함께 **"이 레포대로 세팅해줘"**(또는 "설치해줘")라고 하면 아래 순서대로 한다.
목표는 사용자의 맥에서 SO-101 텔레옵·녹화·학습·추론을 바로 할 수 있는 상태다.
저장소에는 특정 사람의 값(Hugging Face 계정, 팔 포트, 카메라 번호, 보정 파일)이 없다. **이 PC 값은 `scripts/setup_local.sh` 로 찾아 채운다.**
사용자에게는 사용자의 언어로, 짧게 진행 상황을 알린다.

## 세팅 순서 (macOS, Apple Silicon)

1. **확인**: `uname -m` = `arm64`, `sw_vers -productVersion` ≥ 14. `git` 이 없으면 사용자에게 `xcode-select --install` 을 직접 실행해 달라고 한다.
2. **받기**
   ```bash
   git clone <사용자가 준 저장소 주소> ~/so101-ws_for-mac
   ```
   이미 `~/so101-ws_for-mac` 이 있으면 `git -C ~/so101-ws_for-mac pull` 만 한다.
3. **설치**: 인터넷이 필요하다. 2~10분이 걸리므로 타임아웃을 15분 이상으로 잡거나 백그라운드로 실행한다.
   ```bash
   bash ~/so101-ws_for-mac/scripts/install.sh
   ```
   - 마지막에 `lerobot 0.7.1 | torch 2.15.0 | ... | MPS 사용 가능: True` 가 나오면 성공이다.
   - conda 가 없으면 Miniforge 를 `~/miniforge3` 에 설치한다(고정 버전, sha256 확인, `conda init` 안 함).
4. **이 PC 값 자동 설정**
   ```bash
   cd ~/so101-ws_for-mac && bash scripts/setup_local.sh
   ```
   출력 끝의 **"남은 일"** 을 하나씩 처리한다.
   - **Hugging Face 로그인**
     - 토큰은 사용자가 직접 입력한다. 사용자에게 터미널에서 `bash scripts/hub.sh login` 을 실행해 달라고 한다.
     - 에이전트는 토큰을 받거나 입력하거나 출력하지 않는다.
     - 로그인 뒤 `setup_local.sh` 를 다시 실행하면 계정 이름이 저장된다.
     - 로그인 전에도 텔레옵·로컬 녹화는 된다. 이름을 붙일 때만 필요하다.
   - **팔 포트**
     - 두 팔의 USB 와 전원을 연결해 달라고 하고 `setup_local.sh` 를 다시 실행한다. 전원은 follower 12V, leader 5V다.
     - 자동 구분은 모터 전압만 읽는 읽기 전용 동작이라 에이전트가 실행해도 된다.
     - 그래도 구분되지 않으면 사용자가 직접 `lerobot-find-port` 를 실행한다(안내에 따라 케이블 하나를 뽑았다 꽂음). 결과를 `--follower <포트> --leader <포트>` 로 저장한다.
   - **카메라 번호**
     1. 외부 카메라 2대를 연결한 상태에서 사진을 찍는다.
        ```bash
        source scripts/activate.sh && python scripts/cameras.py snap --all
        ```
     2. `outputs/cameras/index<N>_*.jpg` 사진을 직접 열어 보고 번호를 가린다.
        - 작업면을 위에서 내려다보는 화면 = **front**
        - 그리퍼가 가까이 보이는 화면 = **wrist**
        - 사용자 얼굴·방이 보이면 맥 내장 카메라(쓰지 않음)
     3. 판단한 내용을 사용자에게 보여 주고 확인받은 뒤 저장한다: `bash scripts/setup_local.sh --front <번호> --wrist <번호>`
     - `snap` 사진은 front 를 180° 돌린 화면이다(`SO101_CAM_FRONT_ROTATION=180`). 방향을 바꾸는 일은 학습 데이터와 맞아야 하므로 사용자와 상의한다.
     - 카메라가 하나도 안 열리면 macOS 카메라 권한 문제다. 사용자에게 시스템 설정 → 개인정보 보호 및 보안 → 카메라에서 터미널(또는 VS Code)을 허용해 달라고 한다.
   - **보정**
     - 보정 파일이 없으면 사용자가 직접 보정한다(팔을 손으로 움직이는 대화형 작업): `bash scripts/calibrate.sh follower`, `bash scripts/calibrate.sh leader`
     - 다른 맥에서 같은 팔을 쓰던 묶음 파일(`so101_local_bundle_*.tar.gz`)이 있으면 대신 `bash scripts/migrate.sh import <파일>` 을 실행하고 `setup_local.sh` 를 다시 실행한다.
5. **확인**
   - `bash scripts/check_devices.sh`: FAIL 0이어야 한다.
   - `source scripts/activate.sh && python scripts/check_env.py`: FAIL 0이어야 한다.
6. **사용자에게 알려 줄 것**
   - 새 터미널마다 `source ~/so101-ws_for-mac/scripts/activate.sh` (zsh 그대로 가능)
   - 텔레옵: `bash scripts/teleop.sh`
   - 녹화·학습·추론: README.md
   - 남은 일이 있으면(로그인·보정 등) 무엇을 직접 해야 하는지

## 안전 규칙

- **모터를 움직이거나 모터에 쓰는 명령은 에이전트가 실행하지 않는다.**
  - 해당: `teleop.sh`, `record.sh`, `replay.sh`, `rollout.sh`, `calibrate.sh`, `setup_motors.sh`
  - 사용자가 팔 옆에서 직접 실행하도록 명령만 알려 준다. Enter·키 입력이 필요한 대화형 명령이기도 하다.
  - 같은 스크립트라도 `--check`·`--dry-run` 은 장치를 열지 않으므로 실행해도 된다.
- **에이전트가 실행해도 되는 것**
  - 읽기 전용: `setup_local.sh`(모터 전압 읽기), `find_arms.py`, `check_devices.sh`, `check_env.py`, `hub.sh list`
  - 카메라만 여는 것: `cameras.py list`·`snap`
- 전원이 켜진 팔의 USB·모터 케이블을 뽑으라고 하지 않는다(`lerobot-find-port` 는 사용자가 안내를 보며 직접).
- 모터 통신이 안 된다고 펌웨어·EEPROM 초기화나 `setup_motors.sh` 를 하지 않는다. 확인 순서: 전원 → 케이블 → 포트 → 설정.

## 하지 않는 것

- `~/.zshrc`·`~/.bashrc`, 시스템 Python, Homebrew 패키지를 건드리지 않는다.
- `lerobot/` 소스를 다른 커밋으로 바꾸지 않는다(검증한 커밋으로 고정).
- 토큰·비밀번호를 묻거나 출력하거나 파일에 쓰지 않는다.
- 설치가 실패하면 패키지를 임의로 다른 버전으로 바꾸지 않는다. 오류 메시지와 함께 사용자에게 알린다.
- `config/so101.env`(공용 기본값)는 사용자가 요청할 때만 고친다. PC별 값은 `setup_local.sh` 로 `config/so101.local.env` 에 쓴다.
- 다른 사람·다른 팔의 보정 파일을 복사하지 않는다.

## 작업 공간 규칙 (세팅 이후)

- 모든 작업은 `scripts/*.sh` 로 한다. `--dry-run` 은 명령만 출력하고, `--check` 는 장치 없이 LeRobot 설정을 해석한다.
- 장치·계정 값의 위치
  - 공용 기본값: `config/so101.env`
  - 이 PC 값: `config/so101.local.env`
  - 스크립트에 값을 직접 쓰지 않는다.
- 저장 위치(모두 git 제외)
  - 데이터셋: `data/`
  - 받은 모델: `models/`
  - 학습 결과: `outputs/train/<job>/`
  - 보정: `calibration/`

## Ubuntu

`install.sh` 는 Ubuntu 24.04 x86_64 도 감지한다(원본 so-arm101_ws 동작). 이 저장소에서 검증한 것은 macOS 다.
Ubuntu 에서는 시리얼 포트 권한이 필요하다. 사용자가 직접 `sudo usermod -aG dialout $USER` 를 실행하고 재로그인한다.
