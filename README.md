# so101-ws_for-mac — SO-101 로봇팔 맥북 작업 환경

SO-ARM101(SO-101) 리더·팔로워 로봇팔을 **Apple Silicon 맥북**에서 쓰기 위한 작업 환경이다.
명령 몇 개로 어느 맥북에서나 같은 환경을 만들 수 있다.

- **초기 세팅**: 고정 버전 설치, USB 포트 지정, 모터 확인·ID 설정, 보정
- **텔레옵**: 리더 → 팔로워 추종
- **데이터셋 녹화**: 카메라 2대 + 관절을 공식 LeRobotDataset으로 저장, 스페이스바 진행, 녹화 중 카메라 창
- **모델 실행(rollout)**: 학습된 ACT 모델로 팔로워 구동. MPS(기본) 또는 Core ML GPU(선택, 약 30% 빠름), 실행 중 카메라 창·단계별 시간 계측

모터 통신·보정·추종·녹화·데이터 형식·정책 실행은 **공식 [LeRobot](https://github.com/huggingface/lerobot) v0.6.1**(`7e241bd6`)을 그대로 쓴다. 이 저장소에는 공식 코드를 감싸는 것들만 있다: 설치기, 실행 스크립트, 안전 점검, 기록·검증 도구, 문서.

> **들어 있지 않은 것**
> - 모델 가중치, 데이터셋, 보정 파일, 개인 설정, Hugging Face 토큰
> - 가상환경(`.venv`): 설치기가 새로 만든다.
> - 데이터·모델은 Hugging Face에서 받는다(6·7절). 이전 맥의 보정·설정은 묶음 파일로 옮긴다(3절).

---

## 1. 준비물

| 항목 | 조건 |
|---|---|
| 맥 | Apple Silicon(M1 이상), **macOS 13 이상**. Intel 맥·Rosetta 터미널은 지원하지 않음 |
| 개발 도구 | Xcode Command Line Tools(`git`, `swift`): 없으면 `xcode-select --install` |
| 디스크 | 여유 약 6 GB(설치물 약 3 GB + 캐시) |
| 네트워크 | 처음 설치할 때만 필요(uv·Python·패키지·LeRobot 원본을 고정 버전·해시로 받음) |
| 로봇 | SO-101 리더·팔로워, 모터 보드 2개(USB), 각 팔 전원 어댑터. 녹화·모델 실행에는 USB 카메라 2대(front·wrist) |

설치기는 Homebrew·conda·시스템 Python·셸 설정(`~/.zshrc`)을 **바꾸지 않는다**. 모든 것이 이 폴더 안(`.tools/`, `.venv/`, `.cache/`)에 설치된다.

## 2. 설치(처음 한 번, 약 5~10분)

```bash
git clone https://github.com/<user>/so101-ws_for-mac.git ~/so101-ws_for-mac
cd ~/so101-ws_for-mac
./01_setup/install.sh        # uv·Python 3.12.15·LeRobot 0.6.1·torch 2.11.0 등을 고정 버전으로 설치
./01_setup/doctor.sh         # 소프트웨어 점검: FAIL 0이면 정상(WARN은 안내만)
```

- `<user>`는 이 저장소를 올린 GitHub 계정이다. 비공개 저장소라면 접근 권한이 있는 계정으로 로그인해야 clone할 수 있다.
- 다른 폴더에 clone해도 된다. 스크립트는 경로를 하드코딩하지 않는다.
- 설치기를 다시 실행해도 안전하다(이미 맞으면 재사용). 꼬였다고 의심되면 `./01_setup/install.sh --repair`를 실행한다.
- 이 README의 명령은 **저장소 폴더 안**에서 실행한다고 가정한다.

## 3. 이전 맥에서 옮겨 오는 경우(같은 로봇팔)

보정 파일과 로컬 설정(포트·팔 이름·카메라·녹화 조건)은 Git에 없다. 묶음 파일 하나로 옮긴다.

```bash
# 이전 맥(기존 작업 폴더에서): ~/Downloads/so101_local_bundle_<날짜>.tar.gz 생성
./tools/migrate_local.sh export
# AirDrop·USB 등으로 새 맥에 옮긴 뒤, 새 맥의 저장소 폴더에서:
./tools/migrate_local.sh import ~/Downloads/so101_local_bundle_<날짜>.tar.gz
```

- **묶음에 들어가는 것**: `calibration/*.json`, `configs/*.local.yaml`
- **들어가지 않는 것**: 모델, 데이터셋, 로그, 토큰
- import는 기존 파일을 덮어쓰지 않는다. 바꾸려면 `--force`를 붙인다. 그러면 기존 파일을 백업한 뒤 교체한다.
- 가져온 뒤 확인할 것:
  - 포트 이름: `./01_setup/ports.sh`
  - 카메라 번호(맥·허브마다 다름): `./03_dataset/cameras.sh`
  - 보정 일치: `./01_setup/probe.sh both`

이전 맥이 없거나 새 로봇이면 4절부터 하면 된다.

## 4. 로봇 첫 세팅(새 로봇 또는 보정이 없을 때)

```bash
./01_setup/ports.sh                 # USB 연결 전후 비교로 리더·팔로워 포트를 찾아 configs/robot.local.yaml에 저장
./01_setup/doctor.sh --hardware     # 포트·권한 점검(보정 전이면 '보정 파일 없음' WARN은 정상)
./01_setup/probe.sh follower        # 읽기 전용: 모터 6/6 응답·모델·펌웨어·보정 상태
./01_setup/probe.sh leader
./01_setup/motors.sh follower       # (6/6이 아니고 ID가 비어 있을 때만) 공식 setup-motors: 모터를 하나씩 연결
./01_setup/calibrate.sh follower    # 공식 보정(팔로워는 손으로 받친 채로)
./01_setup/calibrate.sh leader
./01_setup/probe.sh both            # 양팔 '보정 파일 상태: match' 확인
```

- **보정 순서**
  1. 기존 파일을 쓸지 묻는 프롬프트가 나오면 **`c` + Enter**를 누른다(그냥 Enter는 예전 파일을 그대로 씀).
  2. 모든 관절을 가동 범위 **가운데**에 두고 Enter를 누른다.
  3. wrist_roll을 뺀 관절을 양쪽 끝까지 천천히 움직이고 Enter를 누른다.
- 모터를 움직이거나 모터에 쓰는 명령(`motors`, `calibrate`, `run`, `record`, rollout)은 **사람이 로봇 옆에서 직접** 실행한다.

## 5. 텔레옵(리더 → 팔로워)

```bash
./02_teleop/run.sh --dry-run       # 명령·설정만 확인(포트를 열지 않음)
./02_teleop/run.sh --time-s 30     # 30초 시험
./02_teleop/run.sh                 # 시간 제한 없음. 시작 자세 확인 후 Enter
```

**종료 순서**
1. 리더를 쉬는 자세로 둔다.
2. 팔로워를 받친다.
3. `Ctrl+C`를 누른다.

종료 요약에 양팔 토크 해제 '성공'이 나오는지 본다. 응답이 없으면 팔로워 전원을 뽑는다.

## 6. 카메라·데이터셋 녹화

```bash
./03_dataset/cameras.sh                                   # 카메라 번호 확인 → configs/cameras.local.yaml (front·wrist 640×480 30fps)
./03_dataset/record.sh --name <이름> --task "<작업 문장>" --episodes 10 --view   # 새 데이터셋, 카메라 창과 함께
./03_dataset/record.sh --resume --name <이름> --task "<같은 문장>" --episodes 10 --view   # 이어서 10개 추가
./03_dataset/inspect.sh datasets/<이름>                    # 검사(녹화 후에는 이번에 저장한 에피소드만 자동 검사)
```

- **스페이스바 진행**(`configs/recording.local.yaml`의 `manual_advance: true`)
  1. 스페이스 → 녹화 시작
  2. 스페이스 → 저장, `r` → 버림
  3. 환경 재설정 후 스페이스 → 다음 녹화
  4. `q` → 종료
- **카메라 창**: `--view`는 녹화 프로세스가 읽은 영상을 보여 준다(카메라를 다시 열지 않음). `--mirror`는 다른 터미널에서 `swift tools/camera_view_dual.swift --mirror .tmp/live --no-focus`로 띄울 때 쓴다.
- 녹화 중에 `--mirror` 없이 카메라 앱·창을 열면 녹화 카메라가 멈춘다.

**Hugging Face 업로드·다운로드**
- 먼저 `.venv/bin/hf auth login`으로 로그인한다. 토큰은 작업 폴더 `.cache/huggingface/`에만 저장되며 Git에 올라가지 않는다.
- 업로드 절차는 [docs/DATASET.md](docs/DATASET.md)에 있다.

## 7. 모델 실행(rollout)

**모델 받기**(예: ACT 체크포인트, `<HF 사용자>/<모델 repo>`):
```bash
.venv/bin/hf download <HF 사용자>/<모델 repo> --include "checkpoints/100000/pretrained_model/*" \
  --local-dir .cache/models/<모델 repo>
```

**실행**: 포트·카메라 번호·task 문장은 본인 값으로 바꾼다. 포트는 `configs/robot.local.yaml`에 있다. task는 녹화 때 쓴 문장과 같아야 한다.
```bash
./tools/rollout_with_view.sh --no-view \
--strategy.type=base \
--policy.path="$PWD/.cache/models/<모델 repo>/checkpoints/100000/pretrained_model" \
--policy.n_action_steps=1 \
--policy.temporal_ensemble_coeff=0.01 \
--device=mps \
--robot.type=so101_follower \
--robot.port=/dev/cu.usbmodem<팔로워> \
--robot.id=so101_follower \
--robot.disable_torque_on_disconnect=true \
'--robot.max_relative_target={"shoulder_pan":15.0,"shoulder_lift":35.0,"elbow_flex":30.0,"wrist_flex":20.0,"wrist_roll":10.0,"gripper":25.0}' \
'--robot.cameras={"front":{"type":"opencv","index_or_path":1,"width":640,"height":480,"fps":30,"rotation":180},"wrist":{"type":"opencv","index_or_path":0,"width":640,"height":480,"fps":30}}' \
'--task=<녹화 때 쓴 작업 문장>' \
--fps=30 --play_sounds=false
```

- **정책 설정 줄**
  - `--policy.n_action_steps=1`, `--policy.temporal_ensemble_coeff=0.01`: 매 스텝 추론 + 시간 앙상블.
  - 이 두 줄을 빼면 모델 기본값(100스텝 묶음)으로 돈다.
- **Core ML(선택, 같은 가중치·같은 결과, 추론 약 30% 빠름)**
  1. 처음 한 번 `.venv/bin/python tools/act_coreml_export.py --checkpoint <pretrained_model 경로>`로 변환한다.
  2. 첫 줄에 `--backend=coreml`을 넣고, `--device=mps`를 `--device=cpu`로 바꾼다.
- **래퍼 옵션**(첫 줄): `--no-view`(창 없이, 다른 터미널에서 `swift tools/camera_view_dual.swift --mirror .tmp/live`), `--timing` / `--timing=light`(단계별 시간 → `logs/rollout-timing-*.json`), `--no-mirror`
- 시작 확인 없이 바로 움직인다. 팔로워를 받칠 수 있게 두고, 이상하면 `Ctrl+C` 또는 전원 차단을 한다.
- 실행 중에는 `swift tools/camera_view_dual.swift`(`--mirror` 없이)를 띄우지 않는다. 카메라를 다시 열면 rollout 입력이 멈춘다.

## 8. 자주 겪는 문제

| 증상 | 원인·조치 |
|---|---|
| probe에서 모터 **0/6** | 거의 항상 모터 전원(어댑터·멀티탭·DC 잭)이 원인이다. 보드 점퍼(`B`)·3핀 케이블도 확인한다. 펌웨어 초기화는 하지 않는다 |
| 보정 파일 **mismatch** | 다른 컴퓨터에서 다시 보정했거나 다른 팔의 파일이다. 그 컴퓨터의 파일을 가져오거나 `./01_setup/calibrate.sh`로 다시 보정한다(`c` 입력) |
| 카메라 열기 실패·번호가 바뀜 | 허브를 다시 꽂으면 번호가 바뀐다. `./03_dataset/cameras.sh`로 확인하고 설정·명령의 `index_or_path`를 고친다 |
| 명령이 중간에 끊김(zsh) | 줄 끝 `\` 뒤에 공백이 있거나, 명령 안에 `#` 주석이 들어간 경우다 |
| `Record loop is running slower` 경고 | 구간이 바뀔 때 한두 번 나오는 것은 정상이다. 계속 나오면 다른 앱을 닫는다. rollout은 맥에서 30 Hz가 어렵다(약 13~19 Hz, docs의 성능 보고서 참고) |
| 카메라 권한 창 | 시스템 설정 → 개인정보 보호 및 보안 → 카메라에서 터미널/VS Code를 허용한다 |

## 9. 폴더와 문서

| 경로 | 내용 |
|---|---|
| `01_setup/`, `02_teleop/`, `03_dataset/` | 단계별 실행 스크립트(공통 CLI `scripts/so101` 호출, 모두 `--help` 지원) |
| `scripts/` | 설치기(`install_macos.sh`), 공통 래퍼(`so101.py`), 런처·훅(녹화 스페이스바·카메라 미러·rollout 계측·Core ML) |
| `tools/` | rollout 래퍼, 카메라 창(Swift), Core ML 변환·비교, 로컬 상태 이관, 오프라인 검증(`verify_offline.py`, `verify_dataset.py`) |
| `configs/*.example.yaml` | 설정 견본. 실제 값은 `*.local.yaml`(Git 제외, 스크립트가 만들거나 묶음으로 가져옴) |
| `lock/macos-arm64/` | macOS 고정 의존성(uv.lock, 해시 포함). `lock/`의 나머지는 Ubuntu용 |
| 매뉴얼 | [docs/SETUP.md](docs/SETUP.md) · [docs/TELEOP.md](docs/TELEOP.md) · [docs/DATASET.md](docs/DATASET.md) · [docs/HARDWARE.md](docs/HARDWARE.md) · [docs/PROJECT_MAP.md](docs/PROJECT_MAP.md) |
| 성능·검증 기록 | [docs/ACT_INFERENCE_OPTIMIZATION_REPORT.md](docs/ACT_INFERENCE_OPTIMIZATION_REPORT.md), [docs/CURRENT_STATE.md](docs/CURRENT_STATE.md) 등. 원래 맥에서의 기록이며 경로·이름은 `user`로 일반화했다 |
| 작업 규칙 | [AGENTS.md](AGENTS.md)(AI 에이전트·작업자용 안전 규칙) |

**로봇 없이 소프트웨어 검증**
- `.venv/bin/python tools/verify_offline.py`: 가짜 서보로 래퍼·훅·안전 동작을 시험한다.
- `.venv/bin/python tools/verify_dataset.py`: 합성 데이터셋을 만들어 검사한다.

## 10. 고정 버전

| 항목 | 값 |
|---|---|
| uv | 0.12.23 (공식 sha256 검증) |
| Python | 3.12.15 (uv 관리, 작업 폴더 `.tools/python`에만 설치) |
| LeRobot | 0.6.1 `lerobot[feetech,dataset]` (원본 커밋 `7e241bd630a3719a56157a497ce5d08f244784f1`) |
| PyTorch | torch 2.11.0, torchvision 0.26.0 (PyPI macOS arm64, MPS) |
| Core ML | coremltools 9.0 (선택 backend용) |
| 잠금 | `lock/macos-arm64/uv.lock` 71개 패키지. 공식 LeRobot lock과 공통 67개는 버전·해시가 같다 |

라이선스: 공식 LeRobot·SO-ARM100은 Apache-2.0이다([docs/REFERENCES.md](docs/REFERENCES.md)).
