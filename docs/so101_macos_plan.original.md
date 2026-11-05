# SO-101 macOS(Apple Silicon) 지원 계획 — `so101_macos_plan.md`

> 작성: 2026-10-09, Plan 모드(조사만 수행). 설치·구현·포트 개방·모터 쓰기·commit/push는 하지 않았다.
> **파일 위치**: 로컬에 `~/so101_ws` 저장소가 없어 요청서 규칙대로 현재 VS Code 작업 폴더(`~/so101-ws_for-mac/so101_macos_plan.md`)에 작성했다. 구현 0단계에서 clone한 뒤 `~/so101_ws/docs/so101_macos_plan.md`로 복사한다. 같은 이름의 파일은 원격 저장소에 없음을 확인했다.
> 참고: 이 작업 폴더에는 조사 중(15:25경) 커밋 없는 `.git`(브랜치 `main`, remote 없음)이 생겼다. 이 작업에서 만든 것이 아니며 손대지 않았다.

---

## 0. Context(왜 하는가)

Ubuntu 24.04 x86_64용으로 만든 `user/so101-ws`는 Linux 전용이다. 설치기가 `uname`을 Linux·x86_64로 강제하고, lock이 linux x86_64 전용이며 `+cpu` torch를 요구한다. 래퍼도 `/sys`·`/proc`·`/dev/serial`·`dialout`·`prctl`에 의존한다. 목표는 MacBook Air M4(native arm64)에 리더·팔로워를 USB로 직접 연결해 **같은 운용 흐름**을 쓰는 것이다. 흐름은 설치 → doctor → 포트 → probe → (필요 시) ID 설정 → 보정 → 추종 → 종료·재실행이다. 방법은 같은 저장소에 macOS 지원을 **추가**하는 것이다. Linux 설치기와 lock은 바이트 단위로 그대로 둔다.

---

## 1. 조사한 실제 환경·저장소·읽은 파일

### 1.1 맥 환경(읽기 전용 확인, 2026-10-09)

| 항목 | 값 |
|---|---|
| 호스트 | `user-MacBookAir.local` |
| macOS | 26.5.2 (25F84), Darwin 25.5.0 |
| CPU / 커널 아키텍처 | Apple M4, `uname -m`=arm64, `arch`=arm64 |
| Rosetta 실행 여부 | `sysctl.proc_translated`=0 → 셸은 native arm64 |
| 기본 셸 | `/bin/zsh`. 스크립트용 `/bin/bash` = **GNU bash 3.2.57** |
| Python | python.org 프레임워크 3.10.11(PATH 첫째)·3.11·3.14. **3.12 없음** |
| uv / Homebrew / conda / pyenv / ffmpeg / gh | 모두 **없음** |
| git | 2.50.1 (Apple Git-155). Xcode CLT 설치됨 |
| BSD 도구 | `/sbin/sha256sum`(`-c --quiet` 동작 확인), `shasum`, `readlink -f`(동작 확인), `lsof`, `ioreg`, `system_profiler`, bsdtar |
| 기존 설치기 문법 | `/bin/bash -n scripts/install.sh`, `scripts/so101` 통과(bash 3.2) |
| Python stdlib(3.10에서 확인) | `fcntl.F_GETPATH`, `select.kqueue` 있음 |
| 시리얼 장치 | `/dev/{tty,cu}.Bluetooth-Incoming-Port`, `.Buds3Pro`, `.debug-console`뿐(보드 미연결). `cu.*` 권한 `crw-rw-rw- root:wheel` |
| 환경 누출 | `PIP_*`·`UV_*`·`PYTHON*`·`DYLD_*`·`CONDA*`·`HF_*` 없음. `~/.config/uv`·`/etc/uv` 없음 |
| SIP | enabled |
| **디스크** | `/System/Volumes/Data` 228 GiB 중 **여유 약 12 GiB(94%)**. 설치(약 2.5 GB 예상)는 가능하다. 별도 clone 검증과 녹화는 용량 관리가 필요하다 |
| 작업 폴더 | `~/so101-ws_for-mac`(비어 있음, git 아님). `~/so101_ws` **없음** |

### 1.2 조사한 저장소

- `https://github.com/user/so101-ws` `main` HEAD **`ae8bb236f22beb7afad999505ed2e4b79c063055`**(2026-10-08 16:48 +0900). 세션 scratchpad에 clone해 읽었다(작업공간에는 아무것도 만들지 않음). 로컬에는 기존 작업물과 미푸시 변경이 없다.
- 공식 LeRobot `7e241bd630a3719a56157a497ce5d08f244784f1`(v0.6.1)을 scratchpad에 shallow checkout했다(LFS 미사용).
- 읽은 파일: `AGENTS.md`, `README.md`, `docs/{CURRENT_STATE,REPRODUCE,HARDWARE,REFERENCES}.md`, `scripts/install.sh`, `scripts/so101`, `scripts/so101.py`(1284줄 전체), `tools/lock_tools.py`, `tools/verify_offline.py`(검사 58개 집계 확인), `lock/{lerobot.env,pyproject.toml,uv.lock}`, `configs/robot.example.yaml`, `.gitignore`.
  - 공식 쪽: `pyproject.toml`, `uv.lock`(darwin torch 항목), `scripts/lerobot_find_port.py`, record·teleoperate·calibrate·setup_motors, `so_follower`·`so_leader`, `motors_bus.py`, `cameras/opencv`, `utils/keyboard_input.py`, `configs/{dataset,video}.py`, docs(`so101`·`installation`·`cameras`·`il_robots`·`streaming_video_encoding`).
- 원격과 로컬 기준값 대조: 요청서 표의 값(v0.6.1/SHA, uv 0.12.23, torch 2.11.0+cpu, `[feetech]`, Python 3.12, 검사 58/58)은 **실제 저장소와 일치**한다.
  - lock 패키지는 프로젝트 자신(`so101-env`)을 빼면 46개, 포함하면 47항목이다.

---

## 2. 목표·범위·미확인 항목

- **1차(이번 구현 대상)**: native macOS arm64에서 다음을 한다. 이 맥에서 실제로 확인한 것만 완료로 적는다.
  1. 고정 설치
  2. doctor
  3. 포트 식별·저장(`setup_robot.sh`)
  4. probe
  5. 필요 시 setup-motors
  6. 공식 보정
  7. 30초·3분 추종
  8. 종료·재실행
- **필수 아님**: ROS·Ubuntu·VM·Docker·CUDA·MPS·Homebrew·conda.
- **2단계(선택, 별도 승인)**: 카메라 + `lerobot-record` 로컬 녹화 → 연구실 NVIDIA PC로 이관. 10절에서 조사·계획만 한다.
- **범위 밖**: 학습·추론, Hub 업로드, 자체 모터 드라이버·보정·추종 루프·녹화기.

**미확인(현장·구현 시 확인)**

| 항목 | 필요한 정보 | 확인 시점 |
|---|---|---|
| 통신 보드 모델·USB 칩 | 보드 인쇄, `scripts/so101 ports`의 VID:PID·serial·location | 3단계(USB만 연결) |
| 맥에서의 장치 노드 이름 | `/dev/cu.usbmodem*`(CDC-ACM, 예: CH343) / `cu.usbserial-*`(CH340 내장 드라이버) / `cu.wchusbserial*`(WCH 드라이버) 중 무엇인지 | 3단계 |
| USB만으로 보드 포트가 열거되는지 | 서보 전원 없이 보이는지 | 3단계 |
| USB-C 허브·어댑터 | M4 Air는 USB-C 2포트. 허브 모델·전원 공급 여부 | 3단계 전 |
| 보드별 serial 고유 여부 | 두 보드의 `serial_number`가 다른지(같거나 없으면 이름이 location 기반일 수 있음) | 3단계 |
| 모터 라벨 전압·어댑터 정격·극성·배선 | `docs/HARDWARE.md` 2절 | 4단계(전원 전) |
| 판매자 ID 설정·보정 여부 | probe 결과 | 5단계 |
| 카메라 모델 | 미지정 | 2단계 착수 전 |
| uv 0.12.23이 아는 최신 Python 3.12 패치 | `uv python list 3.12 --only-downloads` | 구현 1단계 |
| `uv python install --no-bin`·`UV_PYTHON_BIN_DIR` 지원 | `uv python install --help` | 구현 1단계 |
| uv 맥 아카이브 최상위 폴더 이름 | `tar -tzf`(cargo-dist 관례상 `uv-aarch64-apple-darwin/`, 미검증) | 구현 1단계 |
| pyserial 3.5 macOS `comports()`가 `cu.*`만 반환하는지 | venv의 `serial/tools/list_ports_osx.py`(`IOCalloutDevice`) | 구현 2단계 |
| pty·EIO·SIGHUP의 macOS 동작(가짜 서보 시험) | `verify_offline` 실측 | 구현 4단계 |

---

## 3. 레퍼런스·고정 버전·재사용

| 대상 | 고정값 | 근거 |
|---|---|---|
| LeRobot | v0.6.1 = `7e241bd6…`. PyPI `lerobot-0.6.1-py3-none-any.whl` sha256 `1894516040c65f80a45bd9741f8174aae90ed5d93da0627ab4f1a85fd8d75e90` | PyPI JSON, 기존 REFERENCES와 일치 |
| uv | 0.12.23(릴리스 2026-10-03). **`uv-aarch64-apple-darwin.tar.gz` sha256 `50487ae565ccd96e499056b4674d438f4c53170202617b4c759defe0c6a1b544`**(17,044,217 B) | `.sha256` 사이드카·`sha256.sum`·`dist-manifest.json`·GitHub digest 4곳 일치. Linux 자산 sha256도 기존 값과 일치(교차 확인) |
| torch | 2.11.0, `torch-2.11.0-cp312-cp312-macosx_11_0_arm64.whl`, **PyPI** sha256 `4b5866312ee6e52ea625cd211dcb97d6a2cdc1131a5f15cc0d87eec948f6dd34` | PyPI JSON. 공식 `uv.lock` 6559행의 darwin 항목과 같은 해시 |
| torchvision | 0.26.0, `…-cp312-cp312-macosx_11_0_arm64.whl` sha256 `c409e1c3fdebec7a3834465086dbda8bf7680eff79abf7fd2f10c6b59520a7a4` | PyPI = CPU 인덱스 = 공식 lock 6679행 |
| Python | 3.12.x(uv managed, python-build-standalone). 패치는 구현 1단계에서 확정 | 공식 `requires-python >=3.12` |
| SO-ARM100 | `a758567c…`(참고 전용, 기존과 같음) | — |

- 문서 URL은 요청서의 공식 6개와 `https://docs.astral.sh/uv/`(environment, python-versions, resolution, sync, pytorch guide)를 쓴다.
- 고정 SHA permalink는 기존 `docs/REFERENCES.md` 목록을 그대로 쓴다.

**재사용할 원본과 최소 수정 이유**

| 기능 | 원본 | 우리 쪽 |
|---|---|---|
| 포트 찾기 | `lerobot-find-port`(macOS: `/dev/tty*` glob 후 USB 분리 전후 비교, `lerobot_find_port.py` L39-41) | 그대로 실행한다. `setup_robot.sh`는 pyserial `list_ports.comports()`(공식이 Windows에서 쓰는 같은 API)로 **연결** 전후를 비교한다 |
| ID 설정·보정·추종 | `lerobot-setup-motors`·`lerobot-calibrate`·`lerobot-teleoperate` | 수정 없이 인자만 만든다(기존과 같음) |
| 읽기·토크 해제 | `FeetechMotorsBus` API | 기존 `probe_arm`·`disable_torque_one` 그대로 |
| 보정 경로 | `HF_LEROBOT_CALIBRATION/{robots/so_follower,teleoperators/so_leader}/<id>.json` | 기존 그대로 |
| 녹화(2단계) | `lerobot-record`, `lerobot-find-cameras`, `LeRobotDataset` | 래퍼만 붙인다 |

- 공식 코드는 복사하지 않는다(라이선스 Apache-2.0, 기존 REFERENCES 표 유지).
- 2단계에서 예제를 가져오면 URL·SHA·원본 경로·라이선스 헤더·범위·수정 이유를 `docs/REFERENCES.md`에 적는다.
- 서드파티 자료는 쓰지 않았다.

---

## 4. Ubuntu 대비 macOS 차이

| 영역 | Ubuntu(기존) | macOS arm64(계획) | 차이 성격 |
|---|---|---|---|
| Python | 시스템 `python3.12`, `UV_PYTHON_DOWNLOADS=never`, `only-system` | uv managed CPython 3.12.N(정확한 패치 고정)을 **작업공간 `.tools/python`**에 둔다. 설치 단계에서만 다운로드하고(uv 내장 해시로 검증) 이후는 `never` + `only-managed`. `--no-bin`으로 `~/.local/bin`에 쓰지 않는다 | 배포 방식 |
| uv | `uv-x86_64-unknown-linux-gnu.tar.gz` `9167d72b…` | `uv-aarch64-apple-darwin.tar.gz` `50487ae5…`, 같은 버전 0.12.23 | 플랫폼 빌드 |
| torch | `2.11.0+cpu`(download.pytorch.org/whl/cpu) | `2.11.0`(PyPI). macOS 빌드에는 CUDA 변형이 없어 `+cpu` 로컬 태그 자체가 없다. **CPU 인덱스의 맥 휠은 PyPI와 sha256이 다르므로**(`43b35116…` vs `4b586631…`) 인덱스를 쓰지 않는다 | 플랫폼 빌드 |
| lock | `lock/pyproject.toml` + `lock/uv.lock`(linux x86_64, 46개) | `lock/macos-arm64/pyproject.toml` + `uv.lock`(darwin arm64 전용). 같은 `exclude-newer`·`fsspec` 제약·`setuptools==81.0.0` 빌드 제약을 쓴다. 공식 `uv.lock`의 darwin 해석과 **버전·휠 해시가 같아야 한다**(검증 항목) | 별도 파일 |
| 포트 | `/dev/serial/by-id`·`by-path`, `/sys` VID:PID | `/dev/cu.*`(pyserial `comports()`: VID·PID·serial_number·location). `tty.X`↔`cu.X`는 같은 장치로 정규화한다. by-id가 없으므로 USB 지문(VID/PID/serial/location)을 설정에 기록해 매번 대조한다 | 장치 모델 |
| 권한 | `dialout` 그룹 | 보통 `cu.*`가 `0666 root:wheel`이라 그룹 작업이 없다. 실패하면 진단만 하고 `chmod`는 금지 | 권한 모델 |
| 점유 확인 | `/proc/*/fd` | `lsof -F p -- <cu> <tty>`(같은 사용자 프로세스만 보임) | 구현 |
| 간섭 서비스 | brltty·ModemManager(dpkg 검사) | 해당 없음(검사 경로가 없어 자동 생략) | — |
| 신호·고아 방지 | `prctl(PR_SET_PDEATHSIG)` | 없음. 자식 런처가 **kqueue `NOTE_EXIT`로 래퍼 PID를 감시**하다가 래퍼가 죽으면 자기에게 SIGINT를 보낸다. Ctrl+C·SIGTERM·SIGHUP 전달은 기존 코드 그대로 | 구현 |
| 절전 | 해당 없음 | 추종·보정 중 `caffeinate -i -w <래퍼 PID>`로 유휴 절전을 막는다. **덮개 닫기 절전은 막지 못한다** → 매뉴얼 경고 | 운용 |
| 라이브러리 경로 격리 | `LD_LIBRARY_PATH` 제거 | `DYLD_LIBRARY_PATH`·`DYLD_FALLBACK_LIBRARY_PATH`·`DYLD_INSERT_LIBRARIES`도 제거 | 구현 |
| 영상(2단계) | 범위 밖 | PyAV 15.x(FFmpeg 내장, 휠 최소 macOS 13). torchcodec 0.11(darwin arm64 marker)은 **별도 FFmpeg 4–8이 필요**하다. 인코딩은 pyav 전용, 기본 `libsvtav1`, `h264_videotoolbox`도 가능 | 10절 |
| 키보드(2단계 녹화만) | — | pynput은 손쉬운 사용/입력 모니터링 권한이 필요하다. 권한이 없으면 공식 코드가 TTY 키 입력으로 대체한다 | 10절 |

---

## 5. 권장 구조와 파일 목록

**원칙**
- Linux 설치기·lock·설정 형식·명령은 그대로 둔다.
- 공통 CLI(`scripts/so101` + `so101.py`)를 공유하고, 플랫폼 차이는 작은 헬퍼 함수에서 `IS_MAC = sys.platform == "darwin"`으로 나눈다.
- 모터 제어 코드는 복제하지 않는다.

### 5.1 추가

| 파일 | 내용 |
|---|---|
| `scripts/install_macos.sh` | 맥 설치 진입점이다(bash 3.2·BSD 도구 호환). 구조·옵션(`--repair`, `--reset-venv`, `--relock`)·단계·`die` 메시지는 `install.sh`와 같은 흐름이다. 차이: Darwin/arm64/비Rosetta/macOS≥13 확인, uv 맥 자산, managed Python 설치, `lock/macos-arm64` 사용, `/Users/` 경로 검사 |
| `lock/macos-arm64/platform.env` | 맥 전용 KEY=VALUE: `UV_ASSET`, `UV_SHA256`, `PYTHON_VERSION=3.12.N`. 공통값(LEROBOT_*·UV_VERSION·PYTHON_MINOR)은 기존 `lock/lerobot.env`에서 읽는다 |
| `lock/macos-arm64/pyproject.toml` | `lerobot[feetech]==0.6.1`, torch, torchvision. `environments = ["sys_platform == 'darwin' and platform_machine == 'arm64'"]`. 인덱스·`tool.uv.sources` 없음(PyPI). `exclude-newer`·`exclude-newer-package`·`constraint-dependencies`·`build-constraint-dependencies`는 Linux와 같다 |
| `lock/macos-arm64/uv.lock` | 이 맥에서 `--relock`으로 1회 생성한다(해시 포함). 이후에는 `uv sync --locked`만 쓴다 |
| `scripts/so101_launch.py` | macOS 전용 자식 런처(약 40줄). 래퍼 PID를 kqueue로 감시하는 스레드를 띄운 뒤 공식 console script를 `runpy.run_path(..., run_name="__main__")`로 같은 프로세스에서 실행한다. SIGHUP을 무시하고, 시작 시 부모가 이미 바뀌었으면 SIGINT를 보낸다(기존 `_child_preexec`와 같은 의미) |
| `scripts/setup_robot.sh` | 초기 포트 설정 진입점(1~3단계만). 얇은 bash로 `scripts/so101 assign-ports`를 호출한다. Linux에서는 README 4절 안내만 출력하고 종료한다 |
| `docs/so101_macos_plan.md` | 이 계획서 |
| `docs/macos_setup_report.md` | 구현 결과 보고서(11절 양식) |

### 5.2 수정(최소)

| 파일 | 변경 | Linux 영향 |
|---|---|---|
| `scripts/so101.py` | `IS_MAC`, `LOCK_DIR`(mac=`lock/macos-arm64`), `read_lock_env`가 맥에서 `platform.env`를 병합 / `doctor_software`의 lock 경로·torch 판정(맥: lock의 정확한 버전, `+` 태그 없음)·arm64·비Rosetta·macOS 버전·DYLD 격리 / `serial_devices`·`usb_info`·`port_users`·`check_port`를 맥에서 comports·lsof로 처리 / 새 `canonical_port()`(tty↔cu) / `cmd_ports` 맥 출력 / 선택 키 `usb` 지문 검증 / 새 서브커맨드 `assign-ports` / `run_official`이 맥에서 런처와 `caffeinate`를 사용 | Linux 분기는 기존 코드 경로를 그대로 탄다. 추가되는 것은 선택 키 `usb`(없으면 기존과 같음)와 `assign-ports` 서브커맨드다 |
| `scripts/so101` | `env -u DYLD_LIBRARY_PATH -u DYLD_FALLBACK_LIBRARY_PATH -u DYLD_INSERT_LIBRARIES` 추가 | Linux에서는 원래 없는 변수라 영향 없음 |
| `tools/verify_offline.py` | `open_fds_to`: 맥에서 `/dev/fd` + `fcntl.F_GETPATH` / 부모 SIGKILL 시험이 맥에서는 런처 경로를 검증 / 맥 전용 신규 시험 추가(8.1). 재실행 격리 env에 DYLD 추가 | Linux 시험 58개의 판정 로직은 같다 |
| `tools/lock_tools.py` | `hashes <official> <ours> --marker darwin-arm64`: 공통 패키지의 darwin arm64 휠 해시를 공식 lock과 비교 | 새 서브커맨드만 추가 |
| `configs/robot.example.yaml` | 맥 port 예(`/dev/cu.usbmodem…`)와 선택 키 `usb:` 주석 | 주석과 선택 키만 |
| `.gitignore` | `configs/*.local.yaml.bak-*`, `.DS_Store`, (2단계) `data/`, `outputs/` | 무관 |
| `AGENTS.md` | 아래 5.3의 최소 변경 | 규칙 추가뿐 |
| `README.md`, `docs/REPRODUCE.md`, `docs/HARDWARE.md`, `docs/REFERENCES.md`, `docs/CURRENT_STATE.md` | macOS 절 추가(설치·포트·권한·절전), 맥 고정값·lock 비교표, 상태 행 | Linux 절은 그대로 |

**바이트 단위로 바꾸지 않는 파일**: `scripts/install.sh`, `lock/lerobot.env`, `lock/pyproject.toml`, `lock/uv.lock`. 구현 후 `git diff --stat`으로 증명한다.

### 5.3 `AGENTS.md` 최소 변경안

- **범위**: "Ubuntu 24.04 x86_64 + **macOS arm64(Apple Silicon, native)**". 카메라·데이터셋 범위 밖 규칙은 **유지**한다(2단계 착수 전에 별도 변경).
- **시스템**: 기존 문장에 다음을 추가한다.
  - "Homebrew·conda·python.org Python·셸 초기화 파일(`~/.zshrc`, `~/.zprofile` 등)을 변경하지 않는다."
  - "uv managed Python은 작업공간 `.tools/python`에만 설치(`--no-bin`)."
  - "macOS 드라이버 설치·보안 설정 변경은 안내만 한다."
- **작업 순서**: 맥은 1번이 `scripts/install_macos.sh`, 3번이 `scripts/setup_robot.sh`.
- **검증 도구**: 맥에서도 `tools/verify_offline.py`를 실행한다. 집계를 플랫폼별로 기록한다.
- **상태 기록**: 기존 라벨을 그대로 쓰고 "플랫폼(호스트)" 열을 필수로 한다. 예: `SOFTWARE_PREPARED (macOS arm64, <host>)`.

---

## 6. 구현 순서·성공 기준·실패 시 진단

각 단계는 사람이 개입하지 않는 소프트웨어 작업이다. 포트 개방이나 모터 쓰기는 하지 않는다. 실기는 8.3절 조건을 따른다.

| # | 작업 | 성공 기준 | 실패 시 |
|---|---|---|---|
| 0 | `git clone https://github.com/user/so101-ws.git ~/so101_ws`. `git status`가 깨끗한지 확인하고, 이 계획을 `docs/so101_macos_plan.md`로 복사한다 | HEAD=`ae8bb23`(또는 그 이후 원격 HEAD, 기록) | 기존 폴더가 있으면 덮어쓰지 않고 멈춰서 보고한다 |
| 1 | uv·Python 준비: `install_macos.sh`의 0~1단계(사전 점검, uv 다운로드 → `sha256sum -c`, `tar -tzf`로 구조 확인 → `.tools/uv`)와 managed Python 설치(`UV_PYTHON_INSTALL_DIR=$WS/.tools/python`, `--no-bin`, 정확한 `3.12.N`). `PYTHON_VERSION` 확정 | `.tools/uv/uv --version`=0.12.23, `.tools/python/.../python3.12 -c 'import platform;print(platform.machine())'`=arm64. `~/.local/bin`·셸 rc 변경 없음(전후 `ls`·mtime 비교) | 체크섬 불일치면 파일을 쓰지 않는다. `--no-bin`을 지원하지 않으면 `UV_PYTHON_BIN_DIR=$WS/.tools/python-bin`. 네트워크 문제면 재실행 |
| 2 | macOS lock 최초 생성: `install_macos.sh --relock` | `uv lock` 성공. 해시 없는 항목 0, 로컬 경로 0, sdist 전용은 `{feetech-servo-sdk}`뿐. `lock_tools diff`에서 공식 lock과 버전 차이 0(예상, 실측으로 판정). `lock_tools hashes`에서 darwin 휠 해시 차이 0. 패키지 수는 실측해 기록(46으로 가정하지 않음) | 차이가 나면 exclude-newer·제약을 Linux와 같게 맞췄는지 확인한다. 원인을 REFERENCES에 기록하고 임의로 고치지 않는다 |
| 3 | 고정 설치: `install_macos.sh`(일반) | `uv sync --locked` 성공, `--check` 일치, `uv pip check` OK, stamp 기록. venv의 pyserial `list_ports_osx.py`가 `IOCalloutDevice`를 쓰는지 확인 | 다운로드 실패면 재실행(캐시 재사용). 손상이 의심되면 `--repair` |
| 4 | `so101.py` 플랫폼 헬퍼, `so101_launch.py`, `scripts/so101` DYLD 격리, `doctor` 맥 판정 구현 | `scripts/so101 doctor` FAIL 0. WARN은 원인·영향·조치를 기록한다 | doctor 항목별 메시지를 따른다 |
| 5 | `ports`·`assign-ports`·`setup_robot.sh`·`usb` 지문 검증 구현 | 보드 없이 `ports`가 Bluetooth 등 비USB 장치를 USB 후보로 세지 않는다(VID 없음 → 제외/표시). `assign-ports`는 모의 comports로 시험 통과 | — |
| 6 | `verify_offline.py` 맥 대응과 신규 시험 | 실제 총수·PASS·FAIL·SKIP 기록. SKIP은 PASS로 세지 않는다 | 실패 시험은 원인(맥 pty 동작 등)과 함께 기록. 판정 기준을 느슨하게 바꾸지 않는다 |
| 7 | 재실행·복구 검증(8.1) | 정상 재실행은 전 단계 재사용. 부분 삭제 → 복구, 변조 → doctor FAIL → `--repair` 복구. 캐시 오염 없음 | — |
| 8 | 별도 복사본 재현(8.1) | 별도 경로·별도 캐시에서 설치 시간 기록, doctor FAIL 0, 배포본 버전·RECORD 해시 동일 | 용량 부족이면 검증 후 즉시 정리 |
| 9 | 문서·`AGENTS.md`·`CURRENT_STATE.md`·`macos_setup_report.md` 작성, Linux 보존 정적 검토 | 5.2의 "바꾸지 않는 파일" diff 0. 보고서에 실측만 기록 | — |
| 10 | (현장 조건 충족 후) 8.2~8.3 실기 | 8.3 기준 | HARDWARE.md 4절 진단 순서 |

commit·push는 하지 않는다. 검토 후 별도 요청으로 진행한다.

### 6.1 `install_macos.sh` 핵심(초안)

```bash
set -euo pipefail          # bash 3.2: 빈 배열 "${a[@]}" 금지, mapfile·${v,,} 미사용
WS="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd -P)"
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV CONDA_PREFIX DYLD_LIBRARY_PATH DYLD_FALLBACK_LIBRARY_PATH DYLD_INSERT_LIBRARIES || true
export PYTHONNOUSERSITE=1 TMPDIR="$WS/.tmp" UV_CACHE_DIR="${SO101_UV_CACHE_DIR:-$WS/.cache/uv}"
export UV_PYTHON_INSTALL_DIR="$WS/.tools/python" UV_PYTHON_BIN_DIR="$WS/.tools/python-bin"
export UV_PYTHON_PREFERENCE=only-managed UV_PROJECT_ENVIRONMENT="$WS/.venv" UV_LINK_MODE=copy GIT_LFS_SKIP_SMUDGE=1
# 사전 점검: uname -s=Darwin, uname -m=arm64, sysctl -n sysctl.proc_translated=0, sw_vers -productVersion ≥ 13
# uv: curl → sha256sum -c(없으면 shasum -a 256 -c) → tar -tzf 확인 → .tools/uv
# Python: UV_PYTHON_DOWNLOADS=manual "$UV" python install --no-bin "$PYTHON_VERSION"
#         이후 export UV_PYTHON_DOWNLOADS=never;  PYSYS="$("$UV" python find --managed-python "$PYTHON_VERSION")"
# external/lerobot checkout, venv, sync --locked, doctor, stamp: install.sh 4~6단계와 같은 로직(경로만 lock/macos-arm64)
```

- curl로 받은 파일에는 quarantine 속성이 붙지 않아 Gatekeeper 문제는 예상되지 않는다. 실행 실패 시 `xattr -l`로 진단만 한다.

### 6.2 macOS 신호·종료 처리와 한계

| 상황 | 동작 | 근거·한계 |
|---|---|---|
| Ctrl+C | 같은 프로세스 그룹이라 공식 자식이 직접 SIGINT를 받고, 래퍼는 기록만 한다 → 공식 `finally` disconnect → 래퍼 독립 토크 해제 | 기존과 같다(POSIX) |
| SIGTERM | 래퍼가 SIGINT 1회 전달 → 20초 후 SIGTERM → 5초 후 SIGKILL | 기존과 같다 |
| VS Code 터미널 탭 닫기 / 창 종료 | pty가 닫혀 전경 그룹에 SIGHUP. 자식은 무시하고 래퍼가 SIGINT를 전달한다 | 실측 항목(8.1). VS Code가 셸 트리를 SIGKILL하면 래퍼가 즉시 죽고, 다음 줄로 넘어간다 |
| 래퍼 SIGKILL·크래시 | 런처 스레드가 kqueue `NOTE_EXIT`를 받아 자기에게 SIGINT를 보내고, 공식 정리 경로를 탄다 | 프로세스 그룹 전체가 SIGKILL되면 어떤 소프트웨어 정리도 실행되지 않는다. **최종 수단은 팔로워 전원 차단** |
| 맥 절전·덮개 닫기 | `caffeinate -i`가 유휴 절전만 막는다. 덮개를 닫으면 프로세스와 USB가 멈추고 팔로워는 마지막 목표에서 토크를 유지할 수 있다 | 매뉴얼에 "덮개를 닫지 않음, 전원 어댑터 연결" 체크리스트 추가 |
| 통신 단절(USB 분리·허브 리셋) | 공식 루프 예외 → disconnect 시도 실패 → 래퍼 정리 실패 기록(종료 코드 3) | 토크 해제 보장 없음 → 전원 차단 |
| VS Code 백그라운드(App Nap 등) | 실제 루프 Hz로 판정 | 3분 시험에서 VS Code를 전경/후경으로 두고 Hz를 비교 기록 |

---

## 7. 버전·wheel·extras 호환성(실측 조사 결과)

| 패키지(Linux lock 버전) | macOS arm64 cp312 배포 | 최소 macOS | 상태 |
|---|---|---|---|
| torch 2.11.0 | `macosx_11_0_arm64`(PyPI) | 11 | 확인 |
| torchvision 0.26.0 | `macosx_11_0_arm64` | 11 | 확인 |
| opencv-python-headless 4.13.0.92(core) | `cp37-abi3-macosx_13_0_arm64` | **13** | 확인(최신 허용 버전 기준). 고정 시점 버전은 lock 생성 때 재확인 |
| numpy 2.2.6 | `macosx_11_0`/`14_0_arm64` | 11 | 확인 |
| pillow 12.3.0, pyyaml 6.0.3, safetensors 0.8.0, hf-xet, cmake 4.1.3(universal2) | arm64/universal2 휠 있음 | ≤11 | 확인(hf-xet는 exclude-newer로 1.5.2 예상, lock 시 확인) |
| feetech-servo-sdk 1.0.0 | **sdist만**. 순수 Python, 의존성 없음 | — | Linux와 같은 방식으로 빌드한다(컴파일러 불필요 예상) |
| pyserial 3.5, deepdiff 8.6.2, orderly-set 등 | `py3-none-any` | — | 확인 |
| lerobot 0.6.1 | `py3-none-any` | — | 확인 |

- **extras**: `[feetech]` = `feetech-servo-sdk`, `pyserial`, `deepdiff`뿐이다(고정 pyproject L161-170). `av`·`torchcodec`·`pynput`·`rerun-sdk`는 1차에 들어오지 않는다.
- `[all]`·`[dataset]`·`[hardware]`·NVIDIA 의존성은 넣지 않는다.
- macOS 최소 요구는 **13**(opencv)으로 정해 설치기에서 검사한다. 이 맥은 26.5.2다.
- **설치본 동일성 검사**: 그대로 재사용한다. doctor는 이미 `dist.files`에서 파일 수를 동적으로 센다. 문서의 "504"는 "설치 배포본 기준 N개(doctor 출력)"로 바꾸고 맥 실측값을 기록한다.

---

## 8. 검증 계획

### 8.1 무로봇 소프트웨어(이 맥, 구현 직후)

**기존 시험(58개, 맥에서 같은 판정 기준)**
- probe 쓰기 0건, dry-run `/dev` open 0건과 객체 생성 0건, 독립 cleanup, 실행기(Ctrl+C·SIGTERM·SIGHUP·**부모 SIGKILL = 맥은 런처**·무응답 자식 단계 종료), 설정·hardware doctor(같은 장치 링크, null, 없는 포트, 권한 chmod 000, 점유 = 맥은 lsof), teleop 거부.

**맥 추가 시험(예정)**
1. `canonical_port`: `/dev/tty.X`와 `/dev/cu.X`는 같은 장치로 판정, 서로 다른 장치는 다르게 판정
2. `ports`: 모의 comports에서 tty/cu 이중 계산 0, VID 없는 Bluetooth·debug-console 제외
3. `usb` 지문 불일치(serial·location 변경) → hardware doctor·teleop 사전 점검 FAIL
4. `assign-ports`(모의 comports + 스크립트 입력)
   - 정상 저장
   - 후보 여러 개 → 선택
   - 같은 장치 → 거부
   - Ctrl+C·`no` → 파일 바이트 불변
   - 저장 전 예외 → 원본 보존(원자적 교체)
   - 백업 생성
   - 기존 id·`max_relative_target`·주석 보존
   - **포트 open 0건(audit hook)**
5. `caffeinate`가 래퍼 종료와 함께 끝남
6. 런처: 시작 시 부모가 이미 종료된 경우 즉시 SIGINT

**설치 재현**
- 정상 재실행(전 단계 재사용).
- 부분 설치 복구(`lerobot`·`pyserial` 제거).
- 설치 파일 1개 변조 → doctor FAIL → `--repair` → OK, 캐시 무오염.
- `.tools/python` 손상 시 `--reset-venv`와 Python 재설치.

**별도 복사본**
- commit 없이 진행한다. `git ls-files -co --exclude-standard`로 추적·신규 파일만 scratch 경로에 복사한다.
- `SO101_UV_CACHE_DIR`을 새 경로로 두고 설치한다.
- 본 작업공간과 배포본 버전·RECORD 해시·`--help` 출력·stamp를 비교한다.
- 실제 `git clone` 재현은 사용자가 commit을 승인한 뒤 한다.

**Linux 보존**
- 정적 검토: 바꾸지 않는 4개 파일의 diff 0, `so101.py`의 Linux 분기 diff 검토.
- **Linux 실제 실행은 `NOT VERIFIED`**. 연구실 PC에서 `tools/verify_offline.py`(≥58 PASS 기대)와 `doctor`를 실행할 때까지 구분해 적는다.

**판정**: 실제 총수와 PASS·FAIL·SKIP 개수, 그리고 사유를 적는다. 기존 58/58을 옮겨 적지 않는다.

### 8.2 실제 USB(서보 전원 OFF)

- `setup_robot.sh`로 리더·팔로워 식별. 두 장치가 서로 다른지, tty/cu가 한 개로 세어지는지 확인한다.
- `ports`의 VID:PID·serial·location을 확인한다.
- 같은 USB 단자/허브에서 재연결해 이름이 유지되는지 확인한다. 바뀌면 재식별 절차를 검증한다.
- `doctor --scope hardware` FAIL 0(보정 파일 없음 WARN만).

### 8.3 실제 모터·실기 추종(현장 조건 충족 후에만)

- **시작 조건**: 기존 AGENTS 실기 조건 1~4를 모두 충족해야 한다.
  - 작업자가 로봇 옆에 있고 팔을 받칠 수 있으며 전원을 끊을 수 있다.
  - HARDWARE.md 확인표를 작성했다.
  - hardware doctor FAIL 0.
  - 사람이 직접 터미널에서 대화형으로 실행한다.
- **맥 체크리스트 추가**: 전원 어댑터 연결, 덮개 열림, 허브 고정.
- **순서**: probe 양팔(6/6 응답·모델·펌웨어) → (필요 시) setup-motors → calibrate follower·leader(보정 파일 검증 OK, `probe both` match) → `teleop --dry-run` → `--time-s 30` → `--time-s 240`(180초에 수동 종료) → 동일 명령 재실행.
- **기록**: `runs.jsonl`의 `teleop_loop.loop_span_s`(3분 판정), `hz_median`, `loop_ms_p95`, `exit_code`, `cleanup.*.status`. 관찰은 "관찰 기반"으로 적는다.
- **현장 정보**: 7절과 2절 미확인 표의 항목.

### 8.4 선택 녹화

10절 기준. 카메라가 없으면 `NOT VERIFIED`로 둔다.

---

## 9. 초보자용 명령 초안(설치~종료)

`[초안]` 표시는 구현 후 확정한다. VS Code 터미널 하나에서 진행한다.

```bash
# --- 설치(1회) ---
git clone https://github.com/user/so101-ws.git ~/so101_ws
cd ~/so101_ws
scripts/install_macos.sh                 # [초안] 다시 실행해도 안전. 손상 의심: --repair
scripts/so101 doctor                     # 0=OK, 2=WARN만, 1=FAIL

# --- 1~3. 포트 식별·저장(모터 외부 전원 OFF, USB만) ---
scripts/setup_robot.sh                   # [초안] 안내: 두 보드 USB 모두 분리 → Enter → 리더 USB 연결 → Enter → 팔로워 USB 연결 → Enter
                                         #        → 장치 ID 확인(예: so101_leader_a / so101_follower_a) → 변경 내용 확인 'yes' → 저장(백업 생성)
scripts/so101 ports                      # 저장된 역할↔포트·VID:PID·serial 확인
scripts/so101 doctor --scope hardware    # 보정 전이면 '보정 파일 없음' WARN만 정상

# --- 4. 실물 확인(전원 넣기 전): docs/HARDWARE.md 2절 표 작성(모터 라벨 전압, 어댑터 정격·극성, 보드, 배선) ---
# --- 그다음 각 팔에 맞는 전원 연결 ---

# --- 5. 읽기 전용 모터 확인 ---
scripts/so101 probe follower
scripts/so101 probe leader               # 6/6 응답·모델 일치면 6번 건너뜀

# --- 6. (ID 누락·충돌이 확인된 팔만) 모터 ID·baud 설정 ---
scripts/so101 setup-motors follower      # gripper(6)부터 안내되는 모터 '하나만' 보드에 연결 → Enter
                                         # 케이블을 바꾸기 전에는 반드시 모터 전원 OFF.
                                         # 조립 상태에서는 각 모터의 비어 있는 커넥터나 보드→1번 케이블을 해당 모터로 옮겨 연결

# --- 7. 보정(파일 없음·불일치일 때) ---
scripts/so101 calibrate follower         # 팔 받치기. 가운데 자세 Enter → wrist_roll 제외 끝까지 움직임 → Enter
scripts/so101 calibrate leader
scripts/so101 probe both                 # '보정 파일 상태: match'

# --- 8. 추종 ---
scripts/so101 teleop --dry-run
scripts/so101 teleop --time-s 30         # 자세 차이 표 확인 → 체크리스트 'yes'
scripts/so101 teleop --time-s 240        # 3분 확인. 180초 이후 쉬는 자세 → 받침 → Ctrl+C

# --- 9. 종료 ---
# 리더를 쉬는 자세로 → 팔로워를 손으로 받침 → Ctrl+C → '종료 요약'에서 양팔 토크 해제 '성공' 확인
# 실패/확인 불가(종료 코드 3) 또는 응답 없음 → 팔로워 전원 차단 → USB·전원 확인 → scripts/so101 probe both → 같은 명령 재실행
# 포트가 사라졌거나 이름이 바뀌면(허브 재연결 등) → scripts/setup_robot.sh 다시 실행(기존 id 보존)
```

### 9.1 `setup_robot.sh`(`assign-ports`) 동작 명세

- **자동화 범위**: 1~3단계만. 포트 열기·probe·ID 설정·보정·teleop은 실행하지 않고, 다음 명령만 출력한다.
- **장치 목록**: pyserial `comports()`로 읽는다(포트를 열지 않음). `cu.*`로 정규화하고 VID가 없는 항목(Bluetooth 등)은 후보에서 뺀다.
- **식별**: 연결 전후 차이로 정한다.
  - 0개 → 케이블(데이터 지원)·허브·`system_profiler SPUSBDataType` 확인 안내 후 재시도/취소.
  - 여러 개 → 번호로 선택.
- **같은 장치 거부**: 두 역할의 정규화 경로나 (VID, PID, serial, location)이 같으면 저장하지 않는다.
- **장치 ID**: 기존 값을 기본값으로 둔다(Enter=유지). `ID_RE`로 검증하고, 두 역할이 같으면 경고한다. 모터 ID 1~6과 다른 개념임을 화면에 표시한다.
- **저장 절차**
  1. 변경 전후 diff를 보여 주고 `yes`를 받는다.
  2. `robot.local.yaml.bak-<시각>`로 백업한다.
  3. 해당 블록의 `port:`/`id:`/`usb:` 줄만 텍스트로 교체한다. 주석과 다른 값은 보존한다.
  4. 재파싱해서 바꾼 키 외에 값이 같은지 확인한다.
  5. 같은 폴더의 임시 파일에 쓰고 fsync한 뒤 `os.replace`로 교체한다.
- **보존 원칙**: 파일이 없으면 example을 바탕으로 만든다. 구조가 예상과 다르면 자동 수정하지 않고 수동 안내만 한다. 취소·오류 시 원본은 그대로다.

---

## 10. 2단계(선택): 녹화 계획 — 조사·계획만

**착수 조건**: `AGENTS.md`의 "카메라·데이터셋 범위 밖" 규칙을 바꾸는 변경안을 사용자가 명시적으로 승인한다. 이번 요청은 녹화·업로드·학습·추론 실행을 승인하지 않는다.

- **최소 구성**
  - 별도 lock `lock/macos-arm64-record/`, 또는 1차 lock에 optional extra를 더해 relock(설계 시 결정).
  - 대상: `lerobot[feetech,dataset]==0.6.1` = datasets·pandas·pyarrow·`av>=15,<16`·jsonlines·`torchcodec<0.12`(darwin arm64 marker).
  - `pynput`(`[hardware]`)은 기본 제외한다. 권한 요구를 피하기 위해서다. 공식 코드가 TTY 키(`n`/`r`/`q`)와 타이머로 대체하는지 확인한다(**확인 예정**: pynput이 미설치일 때의 경로).
- **FFmpeg**
  - 인코딩은 PyAV 내장 FFmpeg로 충분하다(공식 encoder = pyav 전용).
  - 디코딩 기본값은 torchcodec이고 시스템 FFmpeg 4–8이 필요하다. Homebrew 설치는 시스템 변경이라 기본 계획에 넣지 않는다.
  - 검증 읽기는 `video_backend="pyav"`로 한다.
- **카메라**
  - 모델 미지정. 일반 UVC 기준으로 `lerobot-find-cameras opencv`를 쓴다(AVFoundation, index 0~59 탐색, 테스트 프레임 저장).
  - 이름은 `system_profiler SPCameraDataType`(읽기 전용)으로 대조한다.
  - 내장 카메라·iPhone 연속성 카메라 때문에 index가 바뀔 수 있다. 세션마다 재확인한다.
  - macOS **카메라 권한**은 처음 접근할 때 VS Code/터미널 앱에 묻는다(사용자가 허용, Plan 단계에서는 설정 안 함).
  - FPS 검사가 엄격하다(±0.1%). find-cameras가 보고한 값을 쓴다.
- **명령 초안**: `[초안]`, 인자는 고정 버전 `configs/dataset.py`·`lerobot_record.py`에서 확인한 이름이다.

  ```bash
  .venv/bin/lerobot-record \
    --robot.type=so101_follower --robot.port=<cu> --robot.id=<id> \
    --robot.cameras="{front: {type: opencv, index_or_path: <N>, width: 640, height: 480, fps: 30}}" \
    --teleop.type=so101_leader --teleop.port=<cu> --teleop.id=<id> \
    --dataset.repo_id=local/so101_trial --dataset.root=$HOME/so101_ws/data/so101_trial_<날짜> \
    --dataset.single_task="<작업 설명>" --dataset.fps=30 --dataset.num_episodes=2 \
    --dataset.episode_time_s=20 --dataset.reset_time_s=10 \
    --dataset.push_to_hub=false --play_sounds=false --display_data=false
  ```

  - `push_to_hub` 기본값이 **True**이므로 반드시 false로 둔다.
  - `repo_id`에 시각 접미사가 붙는다(`--dataset.no_stamp`).
  - 코덱 기본값은 `libsvtav1`이고 `h264_videotoolbox`는 비교 옵션이다.
  - 실행은 래퍼 `scripts/so101 record`(2단계에서 추가)로 하고 사전 점검·토크 정리를 공유한다.
- **검증 기준**
  - `LeRobotDataset(repo_id, root=…)`로 다시 연다.
  - 에피소드 수 = 2.
  - 에피소드별 프레임 수 ≈ fps×episode_time_s(허용 오차 기록).
  - timestamp가 단조 증가하고 간격이 1/fps±허용치.
  - 영상 디코드 프레임 수 = 표 행 수.
  - `observation.state`·`action`이 6차원이고 NaN 0.
  - `task`·`episode_index`가 있다.
  - 공식 `check_timestamps_sync` 재사용(확인 예정).
- **저장·용량**
  - 기본 로컬 `data/`(Git 제외), Hub 업로드 끔, 토큰 사용 없음.
  - 이 맥의 여유는 약 12 GiB다. 시험 전에 해상도·시간으로 용량을 추정하고 외장 저장소를 검토한다.
- **연구실 PC 이관**
  1. 데이터셋 폴더를 `tar`로 묶는다.
  2. `shasum -a 256` 매니페스트를 만든다.
  3. 외장 SSD 또는 `scp`로 옮긴다.
  4. 연구실 PC에서 매니페스트를 검증한다.
  5. 같은 LeRobot v0.6.1 + `[dataset]` 환경에서 같은 검증 스크립트로 읽는다. 연구실 PC의 dataset 환경 구성은 별도 작업이다.

---

## 11. 구현 후 기록 양식

### 11.1 `docs/macos_setup_report.md`

```markdown
# macOS 설정 보고서
- 날짜: YYYY-MM-DD / 호스트: <host> / macOS: <sw_vers> / 아키텍처: arm64(proc_translated=0)
- 저장소 커밋: <sha>(+ 미커밋 변경 목록) / LeRobot: v0.6.1 7e241bd6 / uv: 0.12.23 / Python: 3.12.N(managed)
- torch / torchvision: <실제 버전> / lock: lock/macos-arm64/uv.lock sha256=<…>, 패키지 수=<실측>
- 공식 lock 대비: 버전 차이 <n>, darwin 휠 해시 차이 <n>
| 단계 | 실행 명령 | 결과(종료 코드·FAIL/WARN) | 소요 |
- doctor(software): FAIL x / WARN y (WARN별 원인·영향·조치)
- verify_offline: 총 N, PASS a, FAIL b, SKIP c (사유) — 기존 Linux 58과 별개
- 재실행 / 부분 복구 / repair / 별도 복사본: 결과
- 디스크: .venv / .cache/uv / .tools / external 실측
- 변경 파일: <git status/diff --stat>, 바꾸지 않은 파일 diff 0 확인
- Linux 보존: 정적 검토 결과 / 실제 실행 NOT VERIFIED(또는 결과)
- 실기: USB / 모터 / 보정 / 30초 / 3분(loop_span_s, hz_median, p95) / 종료·재실행 — 각 결과 또는 NOT VERIFIED
- 미검증: … / 다음 명령: …
```

### 11.2 `docs/CURRENT_STATE.md`

요약 표에 행을 추가한다:
- `소프트웨어(macOS arm64, <host>) | SOFTWARE_PREPARED 또는 SOFTWARE_PARTIAL — 근거 한 줄`
- `실기(macOS) | NOT VERIFIED 또는 HARDWARE_VERIFIED`

"맥북 환경(날짜 확인)" 절에 1.1절 표의 실측값을 적는다. 상세는 `macos_setup_report.md`로 링크한다.

---

## 12. 구현 전 꼭 필요한 확인(요약)

1. 보드의 USB 칩과 맥에서 보이는 장치 이름(드라이버 필요 여부), USB-C 허브 유무 → 실물 연결 시
2. 두 보드의 serial 고유 여부 → 3단계
3. 모터 전압·어댑터 정격·극성 → 전원 전
4. 디스크 여유 12 GiB → 설치·검증은 가능하다. 녹화 전에 정리나 외장 저장소가 필요하다
