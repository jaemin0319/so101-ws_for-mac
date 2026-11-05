# macOS 설정 보고서 — SO-101 (설치·초기 세팅·텔레옵·로컬 데이터셋)

작성 2026-10-09 16:40 +0900, 실기 결과 반영 2026-10-10(근거: `logs/runs.jsonl`, `logs/*.log`). 이 맥에서 **실제로 실행해 확인한 것만** 완료로 적었다.

## 0. 상태 요약

| 구분 | 상태 | 근거 |
|---|---|---|
| 설치·CLI | **`SOFTWARE_PREPARED` (macOS arm64)** | 고정 설치, doctor FAIL 0, 공식 CLI help 정상, 재실행·복구·별도 snapshot 재설치 통과 |
| 모터 제어 소프트웨어 | **준비 완료(무로봇 검증)** | `tools/verify_offline.py` 116/116 PASS: 가짜 서보 pty 선로 수준 검증, 신호·고아 방지, 포트 마법사 |
| 데이터셋 소프트웨어 | **준비 완료(합성 데이터 검증)** | `tools/verify_dataset.py` 15/15 PASS. **합성 데이터이며 실로봇 수집이 아니다** |
| 실제 USB(보드 포트 식별) | **확인함**(2026-10-09 17:05) | `ports.sh`로 양팔 지정. 1a86:55d3, 서보 전원 없이 USB만으로 열거, 보드 serial 고유 |
| 실기(모터 응답·보정·추종·종료·재실행) | **부분 확인**(2026-10-09) | 양팔 probe 6/6, 보정 match, 30초 추종 60 Hz, 119초·157초 추종, 종료 후 양팔 토크 해제 성공, 재실행. **3분(180초) 연속 추종은 미달(최장 157초) → `NOT VERIFIED`**. 모터 ID 설정은 불필요해서 실행하지 않음 |
| 실카메라 프레임 읽기 | `NOT VERIFIED` | 카메라 모델 미지정. 카메라 권한 창이 뜨지 않도록 자동으로 열지 않았다(내장 "MacBook Air 카메라"는 이름 목록에서만 확인) |
| 실제 녹화 | `NOT VERIFIED` | 로봇·카메라 필요 |
| Linux 기능 보존 | 정적 확인: 보호 파일 4개 바이트 불변 / **Linux 실행은 `NOT VERIFIED`** | 4절 |
| GitHub | `PUSH_PENDING`: 브랜치 `macos-support`에 커밋 완료, push는 GitHub 인증 대기(main 대상 PR 예정, 자동 병합 안 함) | 2026-10-10 |

## 1. 환경·작업공간·Git

| 항목 | 값 |
|---|---|
| 날짜 | 2026-10-09 |
| 호스트 | `user-MacBookAir.local` (MacBook Air, Apple M4) |
| macOS | 26.5.2 (25F84), Darwin 25.5.0 |
| 아키텍처 | CPU arm64. 셸 `arch`=arm64, `sysctl.proc_translated`=0(Rosetta 아님). 설치된 Python `platform.machine()`=arm64 |
| 셸 | 기본 zsh. 스크립트는 `/bin/bash` 3.2.57 |
| 작업공간 | `~/so101-ws_for-mac` = 프로젝트 루트 = Git 작업 트리(중첩 clone 없음, `~/so101_ws` 미생성) |
| 원격 | https://github.com/user/so101-ws `main` = **`ae8bb236f22beb7afad999505ed2e4b79c063055`**(시작 시 실제 fetch) |
| Git 시작 상태 | 커밋 없는 `.git`(브랜치 `main`, remote 없음), 미추적 `.DS_Store`만 있음 |
| 원격 연결 방식 | `git remote add origin`은 권한 분류기가 거부했다. 대신 URL로 직접 fetch해 `refs/remotes/upstream-fetch/main`을 만들었다. remote 설정은 변경하지 않았다 |
| Git 상태(2026-10-09 작성 시점) | 브랜치 `macos-support`(= `ae8bb23` 기준, **커밋 없음**). 수정 12개, 새 파일·폴더 19항목(파일 31개, 이 보고서 포함). 기존 `main`은 커밋 없는 상태 그대로 |
| 디스크(`/System/Volumes/Data`) | 시작 여유 약 12–14 GiB → 끝 38 GiB(세션 중 사용자 쪽에서 공간이 늘었음) |

## 2. 설치 구성(실제 버전)

| 항목 | 값 |
|---|---|
| uv | 0.12.23 `uv-aarch64-apple-darwin.tar.gz`. sha256 `50487ae565ccd96e499056b4674d438f4c53170202617b4c759defe0c6a1b544` = 공식 `.sha256` = 내려받은 바이트 |
| Python | CPython 3.12.15(uv managed). 위치 `.tools/python/cpython-3.12.15-macos-aarch64-none`. `--no-bin`이라 `~/.local/bin`에 쓰지 않았다 |
| LeRobot | 0.6.1, PyPI 휠 sha256 `18945160…`. 설치 파일 **504개 = 고정 SHA `7e241bd6` 소스(바이트 비교)** |
| torch / torchvision | 2.11.0 / 0.26.0(PyPI macOS arm64, `+` 태그 없음). GPU/MPS 미사용 |
| extras | `lerobot[feetech,dataset]`(pynput·rerun·학습 패키지 없음) |
| 영상 | av 15.1.0(FFmpeg 내장, libavcodec 61). torchcodec 0.11.1은 설치되지만 외부 FFmpeg가 없어 **로드되지 않는다** → 공식 코드가 pyav 디코더로 대체(실측) |
| 기타 | datasets 4.8.5, pandas 2.3.3, pyarrow 25.0.0, opencv-python-headless 4.13.0.92, numpy 2.2.6, feetech-servo-sdk 1.0.0(sdist 빌드), pyserial 3.5 |
| lock | `lock/macos-arm64/uv.lock` sha256 `54e73e1de9f3b0b81aa04a14258020081baadd18a08d3e0e96b32bd1f6e753e0`, 패키지 **67개**(가상 프로젝트 제외) |
| 공식 lock 대비 | 버전 차이 **0**, 공통 패키지 macOS arm64 휠 해시 **66/66 일치**. lerobot은 공식 lock에서 editable 프로젝트라 비교하지 않음 |
| Linux lock 대비 | 공통 46개는 같고 맥에만 21개가 더 있다(dataset extra와 그 의존성). Linux에만 있는 패키지 0. 공통 46개 중 차이는 torch·torchvision 표기(`+cpu`)뿐 |
| lock 생성 기준 | Linux와 같은 `exclude-newer=2026-08-03T14:05:01Z`(lerobot만 14:30:00Z), `fsspec==2026.2.0`, 빌드 제약 `setuptools==81.0.0`. 같은 입력으로 두 번 해결해 같은 hash가 나왔다. 해시·lock을 손으로 고치지 않았다 |
| 실사용 공간 | `.venv` 1.0 GB, `.cache/uv` 979 MB, `.tools` 106 MB(uv + Python 72 MB), `external` 31 MB ≈ 2.1 GB |

## 3. 파일 구조·역할·재사용

| 경로 | 역할 |
|---|---|
| `01_setup/{install,doctor,ports,probe,motors,calibrate}.sh` | 사용자 진입점(얇음, `--help`, 역할 인자 검증, 위치 기준 루트) |
| `02_teleop/run.sh` | 추종 진입점 |
| `03_dataset/{cameras,record,inspect}.sh` | 데이터셋 진입점 |
| `scripts/entry_common.sh` | 진입점 공통: 루트·역할 검사·`SO101_CONFIG` |
| `scripts/install_macos.sh` | 맥 설치기. `--repair`·`--reset-venv`·`--relock`, managed Python 손상 시 자동 재설치 |
| `scripts/so101`, `scripts/so101.py` | **공통 CLI(Linux와 공유)**. 맥 분기 함수: `canonical_port`·`mac_usb_ports`·`mac_port_users`·`check_usb_fingerprint`·`cmd_ports_mac`·`cmd_assign_ports`·`doctor_macos_platform`. 공용 함수: `arm_session_precheck`(teleop·record), `cmd_record`·`cmd_cameras`·`cmd_inspect` |
| `scripts/so101_launch.py` | macOS 자식 런처(kqueue 부모 사망 감시, Linux `prctl` 대체) |
| `scripts/so101_dataset.py` | 녹화·카메라 설정, 공식 `lerobot-record` 인자, doctor 데이터셋 점검, inspect |
| `lock/macos-arm64/` | `platform.env`, `pyproject.toml`, `uv.lock` |
| `configs/{robot,cameras,recording}.example.yaml` | 설정 예시(`*.local.yaml`은 Git 제외) |
| `tools/verify_offline.py` | 무로봇 검증(공통 58 + 맥 전용 58) |
| `tools/verify_dataset.py` | 합성 데이터셋 검증 |
| `tools/compare_envs.py` | 두 설치 환경 비교 |
| `tools/lock_tools.py` | lock 도구. `check-macos`·`hashes` 추가 |
| `docs/` | `SETUP.md`·`TELEOP.md`·`DATASET.md`(매뉴얼), 이 보고서, `so101_macos_plan.md`(실행 반영판)·`.original.md`·`so101_macos_execution_request.md` |
| `calibration/`, `datasets/`, `logs/` | 실행 시 생성(Git 제외). `datasets/<name>/` = 공식 v3 `meta/`·`data/`·`videos/` |

- **공식 코드 재사용**: 모터 통신·ID 설정·보정·추종·녹화·카메라·데이터 포맷은 모두 공식 CLI/API를 호출한다. 공식 코드를 복사하거나 수정한 곳은 없다(`external/lerobot` 수정 없음, doctor가 확인).
- **계획에서 바꾼 것**: [so101_macos_plan.md](so101_macos_plan.md) 맨 위 표에 정리했다.
  - 작업공간·진입점 구조·녹화 범위·extras는 실행 요청을 따랐다.
  - 런처는 검증한 뒤 채택했다.
  - 녹화 래퍼가 `video_encoding_batch_size=1`을 고정한다.
  - USB 지문에 serial/위치 기준을 기록한다.

## 4. Linux 기능 보존

- **바이트 불변**: 시작 기준 sha256과 같다(`.tmp/baseline/tracked_sha256.txt`와 비교). `git diff`도 없다.

| 파일 | sha256 |
|---|---|
| `scripts/install.sh` | `a365cf4b…` |
| `lock/lerobot.env` | `6c46839f…` |
| `lock/pyproject.toml` | `5412801e…` |
| `lock/uv.lock` | `49bfdcbc…` |

- **정적 검토**(`scripts/so101.py` Linux 경로)
  - 맥 코드는 `IS_MAC` 분기 안에 있다.
  - Linux에서는 `LOCK_DIR=lock/`, git 명령, 포트 realpath, `/proc` 점유 확인, `+cpu` 판정, `prctl`, 출력 문구가 기존과 같다.
  - 추가된 것은 다음 두 가지다.
    - 선택 설정 키 `usb`: 없으면 기존과 같다. Linux에서는 대조하지 않는다.
    - 새 서브커맨드: `assign-ports`·`record`·`cameras`는 Linux에서 안내만 하고 종료(2)한다. `inspect`는 dataset extra가 필요하다.
  - teleop 사전 점검 순서(파일·포트·인자 파싱 → 모터 읽기)는 기존과 같게 유지했다.
  - `scripts/so101`은 `DYLD_*` 변수 제거만 추가했다. Linux에는 원래 없는 변수다.
- **실행**: 이 맥에서만 실행했다. 공통 58개 시험은 맥에서 모두 통과했다. **Ubuntu에서의 실제 실행은 `NOT VERIFIED`**다. 연구실 PC에서 `scripts/install.sh` → `scripts/so101 doctor` → `tools/verify_offline.py`(58/58 기대)를 실행하고 결과를 적어야 한다.

## 5. 실행한 명령과 결과

| 명령 | 결과 |
|---|---|
| `scripts/install_macos.sh --relock`(1회차) | FAIL: `uv python find --managed-python`이 `UV_PYTHON_PREFERENCE`와 충돌 → 플래그 제거 |
| `--relock`(2회차) | FAIL: lock 점검이 `py312-none-any` 휠을 잘못 거부 → 태그 규칙 수정 |
| `--relock`(3회차) | lock·설치 성공(67개). 마지막 doctor FAIL 2는 아직 맥 판정이 없던 래퍼 때문(구현 전) |
| `uv python find`가 `.venv`를 찾는 문제 | `--system`으로 수정해 managed 기반 인터프리터를 쓰게 함 |
| `./01_setup/install.sh`(정상 재실행) | exit 0, **9초**, uv·Python·LeRobot·패키지 모두 재사용 |
| `./01_setup/doctor.sh` | exit 2, **FAIL 0 / WARN 1** |
| `./01_setup/doctor.sh --hardware` | exit 1, FAIL 1 = "설정 파일이 없습니다"(`robot.local.yaml` 없음 → `ports.sh` 안내). 의도한 진단 |
| 모든 진입점 `--help`(다른 현재 디렉터리 `/tmp`에서) | 10개 모두 exit 0. 역할 누락·오류는 exit 2와 안내 |
| `02_teleop/run.sh --dry-run`, `03_dataset/record.sh --dry-run`, `03_dataset/cameras.sh --dry-run`(예시 설정, `/tmp`에서) | 공식 명령·인자 파싱 표시. 장치를 열지 않음 |
| `.venv/bin/python tools/verify_offline.py` | **116/116 PASS, FAIL 0, SKIP 0**(공통 58/58 + macOS 전용 58/58) |
| `.venv/bin/python tools/verify_dataset.py` | **15/15 PASS**(합성) |

**doctor WARN 1개**: "cv2와 av가 같은 FFmpeg 장치 라이브러리를 각각 포함(libavdevice.61.3.100.dylib): objc 중복 클래스 경고"
- 원인: 공식 의존성 휠 두 개가 FFmpeg를 각각 번들한다.
- 영향: LeRobot은 카메라를 OpenCV(AVFoundation)로 열고, PyAV는 인코딩에만 쓴다. 중복 클래스(AVFFrameReceiver)를 쓰는 경로가 아니다. 합성 인코딩·디코딩도 정상이었다. 다만 **실카메라 녹화로는 확인 전**이다.
- 조치: 실카메라 시험·녹화에서 충돌이나 프레임 오류가 없는지 확인한다. 의존성은 바꾸지 않았다.

## 6. 무로봇 검증 상세(`tools/verify_offline.py`, 116개)

**공통 58개**(Linux와 같은 시험·같은 판정)
- probe: 모든 경로에서 선로 수준 쓰기 0건, 포트 닫힘.
- 독립 cleanup: 쓰기는 Torque_Enable=0·Lock=0뿐이다. 한쪽 실패·지연이 다른 쪽을 막지 않는다.
- 실행기: 입력 중계, Ctrl+C 때 SIGINT 1회, SIGTERM·SIGHUP 전달, **부모 SIGKILL → 런처(kqueue)로 자식 정리**, 무응답 자식 단계 종료.
- dry-run: `/dev` open 0건·객체 생성 0건.
- 설정·hardware doctor: 같은 장치, null, 없는 포트, 권한, **lsof 점유**.
- teleop 거부.

**맥 시험 도구에 바꾼 점**(판정 기준은 같음)
- `/proc/self/fd` 대신 `/dev/fd` + `F_GETPATH`를 쓴다.
- 가짜 장치를 USB 목록에 등록한다.
- pty에서만 `IOSSIOSPEED`(비표준 baud) ioctl ENOTTY를 무시하는 shim을 쓴다. macOS pty가 이 ioctl을 지원하지 않음을 실측했다. 실제 장치 경로에는 적용하지 않는다.
- pty master EOF를 기다리도록 처리했다.

**macOS 전용 58개**

| 묶음 | 확인한 것 |
|---|---|
| 런처 | 종료 코드(7) 보존; 예외 traceback·exit 1; argv·`__main__`·`sys.path[0]`·SIGINT 기본 핸들러·SIGHUP 무시; 공식 console script(`lerobot-find-cameras --help`)가 직접 실행과 같은 출력; **시작 시 부모가 이미 없으면 공식 스크립트 실행 전 즉시 종료**(등록 실패 경로) |
| 실행기 추가 | 부모 SIGKILL 시 감시 방식 kqueue 확인; **폴링 대체 경로**에서도 자식 정리·종료(이번 실행의 종료 원인은 로그에 기록됨); SIGINT를 무시하는 자식도 부모 사망 후 SIGTERM/SIGKILL로 종료(고아 없음); `caffeinate -i -w <자식PID>`가 실행 중 존재하고, 정상 종료·Ctrl+C 뒤 함께 종료 |
| 포트 | tty/cu 정규화; Bluetooth·debug-console 제외·tty/cu 1개; USB 지문(serial 일치/불일치/단자만 변경/중복 serial/위치 불일치/기록 없음 strict·non-strict) |
| 포트 마법사 | 예시 기반 새 파일 저장·주석 보존; 기존 값(max_relative_target·fps) 보존·백업·id 유지; 비로봇 USB 제외; 후보 여러 개 → 번호 선택·고르지 않은 장치는 팔로워 후보에서 제외; serial 없음/중복 → 위치 기준; 정보 없음 → 거부; 같은 보드 → 취소·불변; 같은 ID 거부; Ctrl+C·`no`·원자적 교체 실패 → 원본 불변·임시 파일 없음; 예상과 다른 YAML 구조 → 거부; **모든 경로에서 `/dev` open 0건** |
| 녹화 래퍼 | dry-run 파싱 OK·업로드 false·no_stamp·batch 1 고정; dry-run `/dev` open·카메라 connect·모터 패킷·실행 0건; 설정 거부 9종(task·eval_·fps·시간·에피소드 수·push_to_hub 키·카메라 index·fps 불일치·없는 외장 폴더); `--no-cameras` 명시 때만 영상 없이; 같은 이름 덮어쓰기 거부; resume 호환/비호환/없음; 카메라 실패 → 모터 전 거부; 보정 없음 → 거부·쓰기 0; 조건 충족 시 공식 `lerobot-record`를 업로드 없이·절전 방지·양팔 정리와 함께 실행; manifest(보정 파일 hash 포함) |

**구현 중 시험이 잡아낸 문제**(수정 후 재검증)
- 마법사가 리더 단계에서 고르지 않은 장치를 팔로워 후보로 남기던 문제.
- bash 3.2에서 `$변수` 바로 뒤에 한글이 오면 변수 이름으로 해석되는 문제(`--reset-venv` 경로 실패). 변수를 `${…}`로 감쌌다.

## 7. 설치 재실행·복구·별도 재현

| 시험 | 결과 |
|---|---|
| 정상 재실행 | 9초, 전 단계 재사용 |
| 누락 복구(`uv pip uninstall lerobot pyserial`) | doctor FAIL 4 → `install.sh`가 2개를 다시 설치 → FAIL 0(11초) |
| 손상(설치된 `lerobot/__version__.py` 변조) | doctor "고정 SHA 소스와 다름" FAIL. 일반 재실행은 점검 실패로 중단하고 `--repair`를 안내한다. uv 캐시 사본 sha256은 **불변**(copy 모드). `--repair`(80초, 캐시 없이 재설치)로 복구 → 504개 일치 |
| managed Python 손상(stdlib `ssl.py` 이동) | 설치기가 감지 → `uv python install --reinstall` → 원본과 같은 `ssl.py` 복원, doctor FAIL 0(10초) |
| venv 손상(`.venv/bin/python` 삭제) | 일반 실행은 안내 후 중단. `--reset-venv`는 `.venv.broken-<시각>`으로 옮기고 새로 만듦 → doctor FAIL 0(72초). 옮긴 폴더는 이 시험이 만든 것이라 확인 후 삭제 |
| **소스 snapshot 재설치** | 커밋 없이 명시 목록 46개 파일(추적 16 + 새 파일 30, `git ls-files -o --exclude-standard`와 같음을 확인)을 scratch 경로에 복사했다. 별도 `.venv`·`.cache/uv`·`.tools/python`·`external`로 **78초**에 새로 설치(uv·Python·LeRobot을 새로 받음). doctor FAIL 0; venv의 기반 인터프리터가 snapshot 자신의 `.tools/python`임을 확인(원래 환경으로 대체되지 않음); teleop·record help·dry-run이 snapshot의 CLI를 사용; snapshot 안 `verify_dataset` 15/15 |
| 두 환경 비교(`tools/compare_envs.py`) | 배포본 67/67 같은 버전, **설치 파일 26,329개 내용 동일(차이 0)**. sdist에서 빌드한 feetech-servo-sdk 포함. 경로 의존 예상 차이(RECORD·direct_url·*.pyc·bin/) 57개. 비교 후 snapshot은 삭제 |
| Git clone 재현 | 하지 않음(커밋이 없으므로 "소스 snapshot 재설치"로 대신함) |
| 작업공간 밖 쓰기 | `~/.zshrc`·`~/.zprofile`·`~/.gitconfig`의 mtime·크기 불변. `~/.local`·`~/.cache/uv`·`~/.cache/huggingface`·`~/Library/Caches/uv`·`~/.config/uv`는 계속 없음. 차이 1건: `~/.cache/codex-runtimes`의 mtime(16:25). 이 작업은 그 경로를 쓰지 않는다(다른 앱 활동으로 판단). uv·HF 캐시는 모두 작업공간에 있다 |

## 8. 데이터셋 소프트웨어 검증(합성, `tools/verify_dataset.py` 15/15)

**만든 데이터**
- 공식 `LeRobotDataset.create/add_frame/save_episode/finalize`를 썼다.
- 특징은 공식 SO101Follower + `hw_to_dataset_features`로 만들었다.
- 2개 에피소드 × 45프레임, 카메라 1대 160×120, 30 fps, 표시 이름 `SYNTHETIC_TEST_…`.

**결과**
- **libsvtav1**(공식 기본) 인코딩: 0.4–0.8초. MP4 디코더 `libdav1d`로 확인. 구조는 공식 v3 `meta/`·`data/`·`videos/`, 임시 PNG는 남지 않았다.
- inspect FAIL 0. 에피소드별 디코드 프레임이 45 = length였다(공유 MP4 offset 기준).
- 공식 기본 디코더 경로(video_backend 미지정)로 다시 열었다: 실제 backend=pyav, 마지막 프레임 (3,120,160).
- 대안 코덱 **h264_videotoolbox**도 생성과 검사 모두 FAIL 0.
- **손상 탐지 6종 모두 FAIL로 잡음**:
  1. 영상 삭제("메타데이터가 가리키는 파일 없음")
  2. 에피소드 안 timestamp 역전
  3. action NaN
  4. 관절 이름 순서 변경(형태 6은 그대로)
  5. 행 3개 누락
  6. 없는 task_index
- `inspect.sh --write-manifest`: sha256 목록 6개 파일, `shasum -c` 통과.
- 이관 시뮬레이션(다른 경로로 복사 → 체크섬 검증 → 공식 API 재검사): FAIL 0.

**합성 시험이 확인하지 않는 것**: 실카메라 캡처, 실제 녹화 루프 타이밍, 실로봇 관절 값.

## 9. 실기·현장 항목(2026-10-09, 사용자가 로봇 옆 터미널에서 직접 실행)

근거: `logs/runs.jsonl`과 명령별 로그(`logs/teleop-*.log`, `logs/calibrate-*.log`).

| 항목 | 결과 |
|---|---|
| 보드 USB 식별(`ports.sh`, 17:05) | 확인. 리더 `/dev/cu.usbmodem5B901517511`(serial 5B90151751), 팔로워 `/dev/cu.usbmodem5B901515041`(serial 5B90151504). 1a86:55d3, macOS 내장 드라이버 |
| USB만으로 포트 열거 | 확인(서보 전원 없이 보임) |
| 양팔 모터 통신(probe, 17:09) | 확인. 양팔 6/6 응답, 모델 777(STS3215), 펌웨어 전부 3.10 |
| 모터 ID 설정 | 불필요(ID 1~6이 모두 응답) → 실행하지 않음 |
| 보정 | 확인. 각 팔 첫 시도는 가동 범위 기록 중 Ctrl+C로 중단(exit -2), 두 번째 시도 exit 0. `probe both`(17:17) 양팔 `match` |
| 30초 추종(17:18) | 확인. 루프 구간 29.99s, 60.0 Hz(최대 16.71 ms), exit 0, 양팔 토크 해제 성공 |
| 추종 `--time-s 240`(17:21) | Ctrl+C로 종료. 루프 구간 119.02s, 60.0 Hz(최대 16.82 ms), 양팔 토크 해제 성공 |
| 시간 상한 없는 추종(17:23) | Ctrl+C로 종료. 루프 구간 157.03s, 60.0 Hz(최대 22.75 ms), 양팔 토크 해제 성공 |
| **3분(180초) 연속 추종** | **NOT VERIFIED**(최장 157.03s) |
| 정상 종료·재실행 | 확인(같은 설정으로 세 번 연속 실행, 모두 exit 0) |
| 관절별 방향·대응 관찰, 모터 라벨 전압·어댑터 정격 기록 | 미기록 |
| 실카메라 읽기·실제 녹화·연구실 PC로 옮겨 읽기 | NOT VERIFIED |

## 10. 사용자 조치와 다음 명령(확정)

**현장에서 사람이 할 일**
- 보드·허브 준비
- HARDWARE.md 확인표 작성
- 카메라 선택
- 처음 카메라를 열 때 macOS 권한 허용

```bash
cd ~/so101-ws_for-mac
./01_setup/doctor.sh                     # 지금 상태: FAIL 0, WARN 1
./01_setup/ports.sh                      # 모터 전원 OFF, USB만: 리더 → 팔로워 순서
./01_setup/doctor.sh --hardware
# docs/HARDWARE.md 2절 확인 후 각 팔에 맞는 전원 연결
./01_setup/probe.sh follower
./01_setup/probe.sh leader
./01_setup/motors.sh follower            # probe에서 ID 누락·충돌이 있을 때만(leader도 같음)
./01_setup/calibrate.sh follower
./01_setup/calibrate.sh leader
./02_teleop/run.sh --dry-run
./02_teleop/run.sh --time-s 30
cp configs/cameras.example.yaml configs/cameras.local.yaml
cp configs/recording.example.yaml configs/recording.local.yaml
./03_dataset/cameras.sh                  # 결과로 cameras.local.yaml의 index_or_path 등 작성
./03_dataset/cameras.sh --test front
./03_dataset/record.sh --dry-run         # recording.local.yaml의 name·task 작성 후
./03_dataset/record.sh
./03_dataset/inspect.sh datasets/<recording.local.yaml의 name>
```

- 커밋·push는 이 보고서를 검토한 뒤 별도로 요청받아 진행한다.
- 커밋에서 제외되는 것: `.venv/`·`.tools/`·`.cache/`·`.tmp/`·`external/`·`calibration/`·`datasets/`·`logs/`·`configs/*.local.yaml*`·`.DS_Store`(`.gitignore` 반영).
