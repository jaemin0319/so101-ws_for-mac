# CURRENT_STATE

> **이 저장소(so101-ws_for-mac)로 옮김(2026-11-05)**: 원래 맥 작업공간(연구 저장소 `so101-ws`, 브랜치 `macos-support`, 커밋 `757b252` + 커밋 전 변경)을 그대로 옮긴 것이다. 모델·데이터셋·보정·개인 설정·토큰·로그는 넣지 않았고, 개인 이름·경로는 `user`로 일반화했다. 아래 기록은 원래 맥에서의 결과다. 새 맥에서는 README 2~5절로 설치·확인한다.

## 요약

| 구분 | 상태 |
|---|---|
| 소프트웨어(연구실) | **`SOFTWARE_PREPARED`** — 고정 설치·비구동 검사·별도 clone 재설치(별도 venv·별도 캐시) 통과 |
| 실기 | `NOT VERIFIED` — 연구실 PC에 로봇 미연결 |
| 친구 PC 재현 | `NOT VERIFIED` |
| Ubuntu 22.04 / ROS 2 Humble | 지원 검증 전(검증 환경은 Ubuntu 24.04 x86_64뿐). 22.04 기본 Python은 3.10이라 `python3.12`가 없으면 설치기가 중단된다 |
| GitHub | **`PUSHED`** — https://github.com/user/so101-ws (public, 2026-10-08 사용자 요청으로 private→public 전환), 브랜치 `main`. 2026-10-08 업로드 후 원격 HEAD = 로컬 HEAD 확인(`e4a27a6`, 파일 16개) |
| **소프트웨어(macOS arm64, user-MacBookAir.local)** | **`SOFTWARE_PREPARED`** (2026-10-09). 고정 설치, doctor FAIL 0·WARN 1, `verify_offline` 116/116, `verify_dataset` 15/15(합성), 재실행·복구·소스 snapshot 재설치 통과 → [macos_setup_report.md](macos_setup_report.md) |
| 실기(macOS) | 부분 확인: USB 식별·probe 6/6·보정 match(2026-10-12 재보정)·30초 추종 60 Hz·재실행·종료 후 양팔 토크 해제 확인. **3분 연속 추종 충족**(2026-10-12 루프 구간 858.88초, 이전 최장은 157초). 관절 방향 관찰·전압 확인표 미기록, 실로봇 녹화 미실행 → `HARDWARE_VERIFIED` 아님 |
| 데이터셋(macOS) | 합성 데이터 검증 통과 / 2026-10-13 **실로봇 시험 녹화 2회**(각 20초·600프레임, 카메라 2대): 두 번 모두 녹화·finalize·종료 정리·저장본 무결성 PASS(inspect FAIL 0), 녹화 파이프라인 실측 정상. **수집 품질 보완 필요**: 1차 task 불일치, 2차 시작 2.5~4초 사람 손 개입. 학습 데이터 아님. 연구실 PC 읽기 NOT VERIFIED → [trial_recording_verification_report_20261013.md](trial_recording_verification_report_20261013.md) / **본 데이터셋 `so101_tape_to_box` 50에피소드 수집·검사 FAIL 0, Hub 공개 업로드·재다운로드 검증 완료(2026-10-13)** |
| Linux 보존(macOS 작업 후) | `scripts/install.sh`·`lock/lerobot.env`·`lock/pyproject.toml`·`lock/uv.lock` 바이트 불변(시작 sha256과 같음). 공통 래퍼 변경의 Linux 실행 확인은 `NOT VERIFIED` |
| GitHub(macOS 작업) | **`PUSH_PENDING`** — 2026-10-10 브랜치 `macos-support`에 커밋 6개(기준 `ae8bb23`, main 변경 없음). 이 PC에서 GitHub 인증 정보가 없어 push가 막힘(`could not read Username`). 사용자가 인증 후 `git push -u origin macos-support` → main 대상 PR(자동 병합 안 함) |

## 기준 버전과 설치 방식

- LeRobot 태그 `v0.6.1` = `7e241bd630a3719a56157a497ce5d08f244784f1`. 원본 참조와 검증용으로 `external/lerobot/`(Git 제외)에 받는다.
- 설치는 PyPI `lerobot-0.6.1` 휠(해시 고정)로 한다.
  - 이유: path·git 설치 시 원본 `tool.uv.sources`(torch=cu128)가 CPU 인덱스와 충돌하기 때문이다.
  - 동일성: 휠 파일 504개 = 고정 SHA `src/lerobot`(sha256)이다. doctor가 매번 다시 비교한다.
- 의존성: `lock/pyproject.toml`과 `lock/uv.lock`(46개, 해시 포함), `uv sync --locked`. Python 3.12, uv 0.12.23, torch 2.11.0+cpu, torchvision 0.26.0+cpu, extras `[feetech]`.

## 명령 요약 (각각 별도로 실행)

```bash
scripts/install.sh                       # 설치·재사용·부분 설치 복구
scripts/install.sh --repair              # 파일 손상 의심 시 캐시 없이 재설치
scripts/so101 doctor                     # 소프트웨어 점검(로봇 불필요)
scripts/so101 doctor --scope hardware    # 포트·권한·점유·설정·보정 파일(포트를 열지 않음)
scripts/so101 ports                      # USB 시리얼 장치 목록(읽기 전용)
scripts/so101 find-port                  # 공식 lerobot-find-port
scripts/so101 probe follower             # 모터 읽기 전용 확인
scripts/so101 probe leader
scripts/so101 setup-motors follower      # ID 누락·충돌이 확인된 경우에만
scripts/so101 setup-motors leader        # ID 누락·충돌이 확인된 경우에만
scripts/so101 calibrate follower         # 공식 보정(팔 받치기)
scripts/so101 calibrate leader
scripts/so101 teleop --dry-run           # 공식 명령·인자 파싱만 확인
scripts/so101 teleop --time-s 30         # 공식 추종(짧은 첫 시험)
```

종료: 리더를 쉬는 자세로 → 팔로워를 받침 → `Ctrl+C`. 래퍼가 양팔 토크 해제를 독립적으로 재시도하고 결과를 기록한다(실패 시 종료 코드 3). 응답이 없으면 팔로워 전원을 차단한다.

## 연구실 PC 환경 (2026-10-08 확인)

- 호스트 `user-PC`, 사용자 `user`, Ubuntu 24.04.5 x86_64, 커널 6.8.0-139, 시스템 Python 3.12.3
- `/`(홈 포함) 여유 약 0.5 GB(99%). 그래서 작업공간을 별도 파일시스템에 둔다.
  - `/mnt/isaac` = `/dev/nvme0n1p6` ext4, 실제 마운트(`findmnt`), 여유 약 25 GB
  - 작업공간 `/mnt/isaac/so101_ws`, 진입 경로 `~/so101_ws`는 심볼릭 링크
- `~/.bashrc`가 ROS Jazzy를 source해서 `PYTHONPATH`·`LD_LIBRARY_PATH`가 설정되어 있다. 래퍼와 설치기가 제거하고 실행한다(doctor로 확인).
- 시리얼: `/dev/serial` 없음, ttyACM/ttyUSB 없음(로봇 미연결). 계정이 `dialout` 그룹이 아니다.
- brltty 설치, ModemManager active. 실제 간섭은 관찰되지 않았다(로봇 미연결).

## 커밋

- `b549589`: 검증용 커밋(설치기·래퍼·문서)
- `fa45b20`: clone 검증에서 발견한 stamp 경고 순서 수정
- `68767d5`: SOFTWARE_PREPARED와 clone 재설치 결과 기록
- `e4a27a6`: GitHub 업로드용 문서 정리(첫 push 시점의 HEAD)
- 이후: 업로드 상태(PUSHED) 기록
- 브랜치 `main`, remote `origin` = https://github.com/user/so101-ws.git (`gh repo create --private --source . --remote origin --push`로 생성 후 public 전환)

## 진행 기록

1. 작업공간 생성: `mkdir /mnt/isaac/so101_ws`, `ln -s /mnt/isaac/so101_ws ~/so101_ws`, `git init -b main`(저장소 로컬 user = user noreply, 기존 저장소 관례).
2. 공식 확인
   - 태그 v0.6.1 → `7e241bd6…`(lightweight).
   - 라이선스 원문 확인: LeRobot·SO-ARM100은 Apache-2.0, feetech-servo-sdk는 Unlicense.
   - 공식 코드 경로 확인: connect·calibrate·disconnect·handshake·max_relative_target.
3. uv 0.12.23: GitHub 릴리스 자산과 공식 `.sha256` 일치를 확인하고 `.tools/uv`에 설치. 모든 다운로드·캐시·TMPDIR은 처음부터 작업공간 안(`.cache/`, `.tmp/`)이다.
4. lock 작성 과정
   - path·git 소스로 lerobot을 설치하면 원본의 `tool.uv.sources`(torch=cu128)가 적용되어 CPU 인덱스와 충돌했다(실측). 원본을 수정하지 않기 위해 PyPI lerobot 0.6.1 휠을 쓰기로 했다.
   - 휠의 504개 파일이 고정 SHA 소스와 같음을 확인했다.
   - 제약 없이 해결하면 공식 lock보다 새 버전 13개가 섞였다. `exclude-newer`(커밋 시각)와 `fsspec==2026.2.0` 제약을 주어 다시 해결했다.
   - 결과: 공식 lock과 다른 항목은 torch·torchvision의 CPU 변형뿐이다(docs/REFERENCES.md 표).
5. 설치: `scripts/install.sh`
   - 1차 시도에서 `UV_NO_CONFIG=1`이 `[tool.uv]` 설정을 무시해 `--locked` 오류가 났다. 이 변수를 제거했다.
6. 재실행·복구 검증
   - 정상 재실행: 모든 단계를 재사용했다.
   - lerobot·pyserial 제거(부분 설치) 후 재실행: doctor FAIL(stamp가 있어도 실제 상태로 판정) → `uv sync`로 2개 복구 → OK.
   - 설치된 lerobot 파일 1개를 변조: 일반 재실행은 doctor의 바이트 비교 FAIL로 중단했다. 여기서 uv 기본 하드링크 모드 때문에 **캐시까지 오염**되는 것을 발견했다.
   - 대응: `UV_LINK_MODE=copy`, `--repair = --reinstall --no-cache`로 바꾸고 오염된 캐시 항목을 정리했다(`uv cache clean lerobot`). `--repair`로 복구 → OK.
7. 비구동 검증: 아래 표.

## 비구동 검증 결과 (연구실, 2026-10-08)

| 검사 | 결과 |
|---|---|
| `scripts/so101 doctor`(software) | FAIL 0 / WARN 0 |
| 내용 | Python 3.12.3 venv, ROS·user site 격리, `uv sync --locked --check` 일치, `uv pip check` OK, lerobot 0.6.1, torch 2.11.0+cpu / torchvision 0.26.0+cpu, CUDA 패키지 없음, 설치 파일 504개 = 고정 SHA 소스, 공식 모듈 import 9/9, `lerobot-teleoperate/calibrate/setup-motors --help` exit 0, 공식 모터 맵 = 래퍼 상수, `max_relative_target` float·dict 공식 파싱 OK |
| `scripts/so101 doctor --scope hardware`(설정 없음) | FAIL "설정 파일이 없습니다 → cp …" (의도한 진단) |
| `teleop/calibrate --dry-run`(예시 설정, port null) | 공식 명령 표시, 실행 시 거부 안내 |
| `tools/verify_offline.py` | **58/58 PASS**(가짜 서보 버스 pty) |

`verify_offline` 주요 항목:
- **probe**: 정상·ID 무응답·펌웨어 차이·보정 불일치·장치 무응답·없는 포트·읽기 중 Ctrl+C·객체 소멸 모든 경우에 선로 수준 쓰기 0건, 포트 닫힘. 관절별 진단과 보정 필드 비교가 맞게 나온다.
- **독립 cleanup**
  - leader 포트 실패여도 follower는 성공한다.
  - 쓰기는 ID 1~6의 Torque_Enable(40)=0, Lock(55)=0뿐이고 목표 위치 쓰기는 없다.
  - 모터 하나가 무응답이면 그 모터만 실패로 기록한다.
  - 멈춘 팔은 1.5초 한도에 '확인 불가'로 기록한다.
- **실행기**
  - 자식 대화형 입력이 유지되고 프롬프트도 중계된다.
  - Ctrl+C에서 SIGINT는 1회만 간다(중복 없음).
  - SIGTERM과 SIGHUP(pty 닫힘)은 SIGINT로 전달되고, 자식은 SIGHUP을 무시한다.
  - 부모를 SIGKILL하면 PDEATHSIG로 자식이 정리 후 종료한다(고아 방지).
  - SIGINT를 무시하는 자식은 SIGTERM으로 단계적으로 종료한다.
  - 루프 구간과 Hz를 기록하고, after_exit 결과도 기록한다.
- **dry-run**: /dev open 0건(audit hook), 공식 Robot/Teleoperator 객체 생성 0건, 없는 포트에서도 명령을 표시한다.
- **설정·hardware doctor**: 문자열 time_s, bool fps, 관절 dict 키 누락을 거부한다. 같은 실제 장치를 가리키는 서로 다른 링크, port null, 없는 포트, 권한 없음(테스트 pty chmod 000), 다른 프로세스의 점유를 각각 진단하고, 포트는 열지 않는다.
- **teleop 사전 점검**: 보정 파일 없음·불일치면 공식 명령을 실행하지 않고 모터 쓰기도 0건이다. 조건을 충족하면 공식 인자로 실행한다.

## 별도 clone 재설치 검증 (2026-10-08)

| 회차 | 대상 커밋 | 결과 |
|---|---|---|
| 1 | `b549589` → `/mnt/isaac/so101_verify_20261008_153641` | uv·LeRobot 소스·패키지를 새 캐시로 받아 설치 42초, doctor FAIL 0. WARN 1(설치기가 doctor 뒤에 stamp를 쓰는 순서 문제) → `fa45b20`에서 수정 |
| 2 | `fa45b20` → `/mnt/isaac/so101_verify_20261008_153907` | 설치 43초. doctor FAIL 0 / WARN 0, exit 0. 재실행 시 전 단계 재사용. `verify_offline` 58/58 PASS. 설치 후 clone의 `git status` 깨끗함 |

두 환경(연구실 작업공간 vs 회차 2 clone) 비교 결과:
- Python 3.12.3, torch 2.11.0+cpu, torchvision 0.26.0+cpu, `torch.version.cuda=None`이 같다.
- 배포본 46개 모두 **버전과 설치 파일 내용 해시가 같다**(RECORD 기준, 경로 메타데이터 제외). sdist에서 빌드한 feetech-servo-sdk도 같다.
- `lerobot-teleoperate --help` 출력이 같다(작업공간 경로 치환 후).
- stamp(SHA, uv.lock·pyproject sha256, uv, Python)가 같다.

임시 clone은 검증 후 정리했다. 결과 파일은 연구실 작업공간 `.tmp/verify_results/`에 있다(Git 제외).

### 실측 디스크 사용량

- 새로 설치할 때: `.venv` 1.2 GB + `.cache/uv` 1.1 GB + `external/` 33 MB + `.tools/` 47 MB ≈ 2.4 GB
- 연구실 작업공간: 2.6 GB(초기 하드링크 캐시 포함)
- 설치기 사전 점검 기준은 여유 3,000 MB다.

## 미검증·한계

- 실기 전부(`NOT VERIFIED`): 실제 보드 VID:PID·by-id 고유성, 모터 응답, 보정, 추종, 실제 루프 Hz, 3분 추종, 종료·재실행.
- 가짜 서보 버스는 프로토콜 응답 시험용이다. 실제 모터의 타이밍·전기적 동작을 검증하지 않는다.
- `feetech-servo-sdk`는 sdist 빌드다. 빌드 산출물 해시는 고정되지 않는다(REFERENCES 참조).
- 통신 단절·SSH 단절에서 소프트웨어 토크 해제가 전달된다는 보장은 없다.

## 다음 행동

1. 실물 확인표 작성(docs/HARDWARE.md): 모터 라벨 전압, 어댑터 정격·극성, 보드 모델, 조립·판매자 기설정 여부
2. 실기 PC(친구 PC 또는 로봇을 연결한 연구실 PC)에서 `git clone https://github.com/user/so101-ws.git ~/so101_ws` 후 docs/REPRODUCE.md 순서 진행(public 저장소라 인증 없이 clone 가능)
   - dialout → ports → probe → 보정 → teleop 30초 → 3분 → 재실행
   - 결과를 별도 커밋으로 남긴다

---

# macOS(Apple Silicon) — 2026-10-09

## 환경

- 호스트 `user-MacBookAir.local`, MacBook Air M4, macOS 26.5.2(25F84), native arm64(`sysctl.proc_translated=0`), 기본 셸 zsh, `/bin/bash` 3.2.57
- 기존 Python: python.org 3.10/3.11/3.14가 있고 3.12는 없다. Homebrew·conda·uv·ffmpeg는 없다. 이 작업은 이들을 바꾸지 않았다.
- 작업공간 `~/so101-ws_for-mac`(프로젝트 루트 = Git 작업 트리). 원격 `main` `ae8bb236f22beb7afad999505ed2e4b79c063055`에서 브랜치 `macos-support`를 만들었다.
- 시리얼: Bluetooth·debug-console만 있다(로봇 보드 미연결). 카메라 이름 목록: "MacBook Air 카메라"(열지 않음).

## 기준 버전과 설치 방식(macOS)

| 항목 | 값 |
|---|---|
| 설치기 | `./01_setup/install.sh` → `scripts/install_macos.sh` |
| 기준 파일 | `lock/lerobot.env`(공통) + `lock/macos-arm64/{platform.env,pyproject.toml,uv.lock}` |
| uv | 0.12.23 `uv-aarch64-apple-darwin`, sha256 `50487ae5…` |
| Python | 3.12.15 uv managed(`.tools/python`, `--no-bin`) |
| 패키지 | `lerobot[feetech,dataset]==0.6.1`, torch 2.11.0·torchvision 0.26.0(PyPI macOS arm64) |
| lock | 67개, sha256 `54e73e1d…`. 공식 lock과 버전 차이 0, macOS 휠 해시 66/66 일치 |
| 설치본 동일성 | LeRobot 설치 파일 504개 = 고정 SHA 소스 |
| 영상 | av 15.1.0(인코딩). torchcodec은 외부 FFmpeg가 없어 로드되지 않으며 공식 코드가 pyav로 대체한다 |

## 명령(macOS)

```bash
./01_setup/install.sh            # --repair / --reset-venv
./01_setup/doctor.sh             # --hardware
./01_setup/ports.sh              # --list / --find-port
./01_setup/probe.sh follower|leader|both
./01_setup/motors.sh follower|leader      # 필요 시, 사람이 직접
./01_setup/calibrate.sh follower|leader   # 사람이 직접
./02_teleop/run.sh --dry-run | --time-s 30
./03_dataset/cameras.sh | --test <이름> | --dry-run
./03_dataset/record.sh --dry-run | (실행) | --resume --name <이름>
./03_dataset/inspect.sh datasets/<이름> [--write-manifest]
```

## 검증 결과(macOS, 2026-10-09)

| 검사 | 결과 |
|---|---|
| `./01_setup/doctor.sh` | FAIL 0 / WARN 1(cv2·av의 libavdevice 중복 objc 경고 — 원인·영향·조치는 보고서 5절) |
| `./01_setup/doctor.sh --hardware` | FAIL 1 = `configs/robot.local.yaml` 없음(포트 지정 전, 의도한 진단) |
| `tools/verify_offline.py` | **116/116 PASS**(공통 58/58 + macOS 전용 58/58), SKIP 0 |
| `tools/verify_dataset.py` | **15/15 PASS** — 합성 데이터(실로봇 수집 아님) |
| 재실행·누락 복구·손상 repair·Python 손상·venv 손상 | 모두 통과(보고서 7절) |
| 소스 snapshot 재설치(별도 venv·캐시·Python) | 78초, doctor FAIL 0, 설치 파일 26,329개 내용 동일 |

### 재확인(2026-10-10, GitHub 정리 전, USB·카메라·모터를 열지 않음)

| 검사 | 결과 |
|---|---|
| `./01_setup/doctor.sh` | FAIL 0 / WARN 1(cv2·av libavdevice 중복), exit 2 |
| `tools/verify_offline.py` | 116/116 PASS(공통 58/58 + macOS 전용 58/58), SKIP 0 |
| `tools/verify_dataset.py` | 15/15 PASS(합성 데이터) |
| Ubuntu 보호 파일 4개 | 시작 sha256과 같음 |

## 미검증·한계(macOS)

- 실기 전부 `NOT VERIFIED`: 보드 USB 식별, USB만으로 포트가 보이는지, 모터 응답, ID 설정, 보정, 30초·3분 추종, 실제 Hz, 종료·재실행.
- 실카메라와 실제 녹화, 연구실 PC에서 읽기는 `NOT VERIFIED`.
- 소프트웨어로 토크 해제를 보장할 수 없는 경우: 모든 프로세스가 SIGKILL되거나, USB가 끊기거나, 덮개를 닫아 절전에 들어간 경우. 최종 수단은 전원 차단이다.
- 공통 래퍼 변경의 Ubuntu 실행 확인은 `NOT VERIFIED`(정적 검토만 함).

## 다음 행동(macOS)

1. 현장: [SETUP.md](SETUP.md) 2번(`./01_setup/ports.sh`)부터 진행
2. HARDWARE.md 확인표 → probe → (필요 시) motors → calibrate → [TELEOP.md](TELEOP.md) 30초·3분
3. 카메라 선택 → [DATASET.md](DATASET.md) 짧은 녹화(20초×2) → inspect → 연구실 PC로 이관해 체크섬·읽기 확인
4. 연구실 Ubuntu PC에서 `tools/verify_offline.py`로 Linux 회귀 확인
5. 검토 후 커밋·push(별도 요청)

## 실기 진행 기록(macOS, 2026-10-09, 사용자가 로봇 옆 터미널에서 직접 실행)

| 단계 | 결과 |
|---|---|
| USB 포트 식별(`./01_setup/ports.sh`, 17:05) | 리더 `/dev/cu.usbmodem5B901517511`(serial 5B90151751, 위치 1-1.3), 팔로워 `/dev/cu.usbmodem5B901515041`(serial 5B90151504, 위치 1-1.2). 1a86:55d3, macOS 내장 드라이버, **서보 전원 없이 USB만으로 열거됨**. `doctor --hardware` FAIL 0 |
| probe(17:09) | 양팔 6/6 응답, 모델 777(STS3215), 펌웨어 모두 3.10 → 모터 ID 설정 불필요 |
| 보정(팔로워 17:12:54, 리더 17:15:37 시작) | 공식 `lerobot-calibrate`. 각 팔의 첫 시도(17:11:56, 17:14:50)는 가동 범위 기록 중 Ctrl+C로 중단(exit -2)했고, 두 번째 시도는 exit 0으로 끝남. `probe both`(17:17) 결과 양팔 `match`. 보정 파일 sha256: 리더 `cbdc9839…`, 팔로워 `e72dff43…`(백업은 아직) |
| 재보정(2026-10-12) | 팔로워 11:15:50, 리더 11:27:05에 공식 `lerobot-calibrate`로 다시 보정(exit 0). 리더 첫 재보정(11:18)은 shoulder_lift·elbow_flex·wrist_flex 범위가 엔코더 넘어감으로 0~4095가 되어 다시 했다. 현재 파일 sha256: 리더 `97b9afec5d27…`, 팔로워 `ae844d1bc16e…`. `doctor --hardware`에서 두 보정 파일 OK. 래퍼에 넘어간 범위 검사 추가. 각 팔 최신 보정 로그만 남기고 이전 로그 삭제(사용자 요청) |
| 재보정 후 연속 추종(2026-10-12 11:32:35, 사용자 실행) | exit 0(Ctrl+C). **루프 구간 858.88초(약 14분 19초)**, 60.0 Hz, 최대 48.4 ms, 양팔 토크 해제 성공 → **3분(180초) 연속 추종 기준 충족**(현재 보정 기준) |
| 데이터셋 준비 점검(2026-10-12 11:33~11:48) | doctor --hardware FAIL 0, probe both 양팔 6/6·match, 두 카메라 동시 60초 30.12/30.15 fps(640×480, 중복·오류·100ms 초과 멈춤 0), 역할 사진 확인, record.sh --dry-run FAIL 0. **판정: 시험 녹화 가능 / 실제 녹화·검사는 NOT VERIFIED** → [dataset_readiness_report.md](dataset_readiness_report.md) |
| 시험 녹화(2026-10-13 11:29, 사용자 실행) | `./03_dataset/record.sh --name so101_trial_20261013 --task "Pick up the marker and place it in the box" --episodes 1` → exit 0, 600프레임/20.00초, 녹화 루프 지연 경고 0, 양팔 토크 해제 성공. inspect FAIL 0(영상 2개 디코드 600/600, state·action 6차원·NaN 0, timestamp 33.333 ms). 실제 옮긴 물체는 빨간 테이프 롤이라 **task 문장 불일치**(데이터 보존, 학습 제외). 공식 read_latest 구조로 움직임 구간 반복 프레임 약 1~1.5% 관찰 |
| 시험 데이터셋 삭제(2026-10-13 11:41) | 사용자 요청으로 `so101_trial_20261013`, `_b`와 수집 기록 삭제(로그는 보존) |
| 시험 녹화 2차(2026-10-13 11:34, 사용자 실행) | `--name so101_trial_20261013_b --task "Pick up the red tape roll and place it in the box" --episodes 1` → exit 0, 600프레임/20.00초, 지연 경고 0, 양팔 토크 해제 성공, inspect FAIL 0(영상 600/600, NaN 0). task 일치. 단 2.5~4초 사람 손이 테이프를 옮김(장면 개입) → 학습 데이터 아님. 다음: 물체 배치 후 `yes`, 녹화 중 손 금지로 재녹화 |
| 데이터셋 `so101_tape_to_box`(2026-10-13 11:46~12:42, 사용자 녹화) | 녹화 6세션(1+9+10+10+10+10), 모두 exit 0·양팔 토크 해제 성공, 지연 경고는 11:58 세션 1회(최저 11.2 Hz). **에피소드 50, 프레임 29,896**(ep 28·29만 547·549프레임, 나머지 600). `inspect.sh` 전체 디코드 FAIL 0 / WARN 0. task `Pick up the red tape roll and place it in the box` |
| Hub 업로드(2026-10-13, 사용자 명시 요청) | https://huggingface.co/datasets/user/so101_tape_to_box **공개(public)**. 공식 `LeRobotDataset.push_to_hub`(데이터 파일 27개만, `.DS_Store` 제외), 카드 README·`v3.0` 태그 생성. Hub에서 내려받아 공식 API로 열기 성공, 27개 파일 sha256 로컬과 일치. 토큰은 작업공간 `.cache/huggingface/`(Git 제외) |
| ACT 정책 오프라인 점검(2026-10-13, 로봇 미구동) | https://huggingface.co/user/act_so101_tape_to_box 체크포인트 `040000`의 `pretrained_model`만 `.cache/models/`(Git 제외)에 받음. 입력(state 6, front·wrist 3×480×640)이 현재 구성과 일치. 설정 device=cuda → 맥은 `--device=mps`. MPS 청크(100스텝) 추론 53 ms, CPU 103 ms, NaN 0. 학습 데이터 50에피소드 비교: 5·10초 지점 몸체 평균 오차 약 3°(가만히 13~19°), 0초 지점은 사람 시연의 시작 대기 때문에 차이. 공식 `lerobot-rollout` 인자 파싱 확인(base, mps, 관절별 max_relative_target). **실제 로봇 실행은 미실행(NOT VERIFIED)** — 사람이 로봇 옆에서 시작 |
| 녹화 스페이스바 진행 모드(2026-10-14) | `recording.local.yaml`에 `manual_advance: true`, `max_episode_time_s: 120` 추가(백업 `recording.local.yaml.bak-20261014_102305`). 준비→스페이스=시작, 녹화 중 스페이스=저장 / r=버림, 재설정 후 스페이스=다음. 공식 파일 미수정, 런처가 `scripts/so101_record_hooks.py`로 `record_loop`·키 연결만 감쌈. 무로봇 검증 125/125(스페이스바 흐름 6개 포함), 사용자 명령 dry-run FAIL 0. **실제 로봇 녹화로는 아직 확인 전** |
| 녹화 후 검사 범위 축소(2026-10-14) | 녹화 후 자동 검사가 **이번 녹화에서 저장된 에피소드만** 에피소드별 검사(영상 디코드 포함). 범위는 녹화 전후 `total_episodes` 차이. 데이터셋 수준 검사(파일 존재·특징·전체 행 수·task·stats)는 전체 유지. `inspect.sh --episodes 50-59` 추가(기본은 전체). 수집 기록에 `episodes_before`·`episodes_saved`·`inspect.episodes_checked`. 무로봇 검증 125/125, 합성 데이터셋 19/19(범위 검사·이어 녹화 후 범위 검사 4개 추가), `so101_tape_to_box --episodes 48-49` FAIL 0(약 9초). **실제 이어 녹화 후 자동 검사로는 아직 확인 전** |
| 데이터셋 `so101_tape_to_box_v2`(2026-10-14 10:30~12:34, 사용자 녹화, 스페이스바 모드) | 녹화 10세션 × 10에피소드(첫 세션은 새로 만들기, 이후 `--resume`). 모두 exit 0·양팔 토크 해제 성공, 지연 경고는 2세션에서 각 1회(최저 24.3 Hz, 21.9 Hz). **에피소드 100, 프레임 91,889**(에피소드 길이 660~1,270프레임 = 22~42초, 중앙값 901, 모두 스페이스바로 종료되어 120초 상한 도달 없음). 세션별 자동 검사 모두 FAIL 0 / WARN 0. 5번째 세션부터 **이번에 저장된 에피소드만 검사**(40~49 … 90~99)가 실제로 동작함을 확인. 전체 100개 `inspect.sh --no-decode` FAIL 0. task `Pick up the red tape roll and place it in the box`. → **스페이스바 진행 모드와 범위 검사 실로봇 확인** |
| Hub 업로드 v2(2026-10-14, 사용자 명시 요청, 공개 선택) | https://huggingface.co/datasets/user/so101_tape_to_box_v2 **공개(public)**. 공식 `LeRobotDataset.push_to_hub`(데이터 파일 43개, 1,798 MB, 약 29분), 카드 README·`v3.0` 태그 생성, `.DS_Store` 없음. Hub(`v3.0`)에서 내려받아 공식 API로 열기 성공(에피소드 100, 프레임 91,889, 마지막 프레임 디코드), 43개 파일 sha256 로컬과 일치. 검증용 사본은 삭제 |
| 로컬 정리·v2 모델 받기(2026-10-14 20:33, 사용자 요청) | 로컬 데이터셋 `so101_tape_to_box`(v1)·`so101_tape_to_box_v2`와 수집 기록(`.so101.json`), 파생 캐시(`.cache/huggingface/datasets/parquet`, Hub 데이터셋 refs) 삭제 → **원본은 Hub에만 있음**(둘 다 업로드·재다운로드 sha256 일치 확인됨). v1 모델은 `100000`만 남기고 `040000`·`060000`·`080000` 삭제. https://huggingface.co/user/act_so101_tape_to_box_v2 (커밋 `e4591cad93`)의 체크포인트 `020000`·`040000`의 `pretrained_model`만 `.cache/models/act_so101_tape_to_box_v2/`에 받음(training_state 제외, 14개 파일 크기·sha256 Hub와 일치). 이어서 `060000`도 받음(커밋 `e3f61b1ed0`, 7개 파일 sha256 일치). `080000`도 받음(커밋 `d4369fa8ee`, 7개 파일 sha256 일치, 입력·출력 형식 동일, rollout 실행 중이라 MPS 로드 시험은 생략). 2026-10-15: 사용자 요청으로 v2 `020000`·`040000`·`060000` 삭제, `100000` 받음(커밋 `27d27c232b`, 7개 파일 sha256 일치, 학습 목표 100,000 step 도달). `080000`·`100000` MPS 로드·추론(임의 입력) 출력 (1,100,6), NaN 0, 청크 추론 55 ms(080000의 155 ms는 프로세스 첫 모델 워밍업). 이어서 `120000`도 받음(Hub 커밋 `98c5834ab7`, sha256 일치, rollout 실행 중이라 MPS 로드 시험 생략). `140000`도 받음(Hub 커밋 `c41ad529d7`, sha256 일치, 실행 중이라 MPS 로드 시험 생략). 이후 사용자 요청으로 `140000` 삭제. 현재 로컬: v2 `080000`·`100000`·`120000`, v1 `100000`. 학습 설정: 데이터 `user/so101_tape_to_box_v2`, 목표 100,000 step, batch 8, chunk 100. 입력(state 6, front·wrist 3×480×640) 현재 구성과 일치. MPS 로드·추론(임의 입력) 출력 (1,100,6), NaN 0, 청크 추론 약 55 ms. **실제 로봇 실행은 NOT VERIFIED** |
| 실행 중 카메라 창 함께 보기 시험(2026-10-14, 로봇 미사용) | 공식 `OpenCVCamera`(rollout과 같은 설정: index 1 640×480 30fps 180°, index 0)로 읽는 중에 `camera_view_dual.swift`를 15초 띄움. preset을 640×480으로 맞춘 창에서도 장치 형식이 1280×720으로 바뀌어 프레임이 640×360 → 크기 불일치로 두 카메라 읽기 스레드 중단, 창을 닫아도 복구 안 됨 → **불가 판정, viewer는 원래대로 되돌리고 경고 주석만 추가**. 이후 두 카메라 640×480 약 31fps 정상 확인. rollout·record 중 영상을 보려면 같은 프로세스 안에서 프레임을 내보내는 방식이 필요(미구현) |
| 실행 중 카메라 보기(미러) 추가(2026-10-14, 로봇 미사용) | `tools/rollout_with_view.sh <lerobot-rollout 인자>`: 공식 rollout을 `so101_launch.py`(부모 사망 감시)+caffeinate로 실행하고, `scripts/so101_camera_mirror.py`가 공식 프로세스 안에서 이미 읽은 프레임(회전 적용, 정책 입력과 동일)을 `.tmp/live/front.jpg`·`wrist.jpg`로 약 10Hz 내보냄. 창은 `camera_view_dual.swift --mirror`로 파일만 읽음(카메라 추가 개방 없음). 공식 파일 미수정. 실측(실제 카메라 2대, 모터 없이 공식 `SO101Follower` 카메라 경로 20초): 미러 없음/있음 루프 26.61/26.67 Hz, read_latest p99 0.21/0.17 ms, 초과 0/0, 프로세스 CPU 10.3/11.3 s(+약 5%), JPEG 약 9 Hz·창 표시 확인, 이미지 방향 정상. Ctrl+C → 공식 종료 경로 0.6초, 창·caffeinate 정리. 공식 `lerobot-rollout --help` 통과. verify_offline 130/130(미러 시험 5개 추가). `--no-view`로 실행·창 분리(두 터미널) 가능: 다른 터미널의 `swift tools/camera_view_dual.swift --mirror .tmp/live`에서 138/121장 표시 확인. **실제 rollout과 함께 쓰는 것은 아직 확인 전** |
| 녹화 중 카메라 보기(2026-10-15, 로봇 미사용) | `record.sh --view`(창 자동) / `--mirror`(내보내기만, 다른 터미널에서 `camera_view_dual.swift --mirror .tmp/live --no-focus`). rollout과 같은 미러 방식(카메라 추가 개방 없음). 창은 `--no-focus`로 키보드 초점을 가져가지 않음(실측: 창을 띄운 뒤에도 앞 앱 유지) → 스페이스바 녹화와 함께 사용 가능. 녹화가 끝나면 창 종료. verify_offline 133/133(녹화 보기 시험 3개 추가). **실제 녹화와 함께 쓰는 것은 아직 확인 전** |
| 데이터셋 `so101_ball_to_bowl_v1`(2026-10-16, 사용자 녹화, 스페이스바 모드·`--view`) | 녹화 10세션 × 10에피소드, 모두 exit 0, 세션별 자동 검사 FAIL 0 / WARN 0. **에피소드 100, 프레임 45,467**, task `Pick up the ball and place it in the bowl`. 지연 경고는 첫 세션에서 구간 전환 순간 2회(24.6 Hz, 19.3 Hz). → `--view` 녹화 중 카메라 창 실사용 확인 |
| Hub 업로드 ball_to_bowl(2026-10-16, 사용자 명시 요청, 공개 선택) | https://huggingface.co/datasets/user/so101_ball_to_bowl_v1 **공개**. 공식 `push_to_hub`(데이터 파일 43개, 약 9분), `v3.0` 태그. Hub에서 내려받아 공식 API로 열기 성공(에피소드 100, 프레임 45,467), 43개 sha256 일치 → 사용자 요청대로 로컬 데이터셋·수집 기록·파생 캐시 삭제(원본은 Hub에만) |
| ball_to_bowl 모델 받기(2026-10-17, 사용자 요청) | https://huggingface.co/user/act_so101_ball_to_bowl_v1 (커밋 `f5d4f61d49`) 체크포인트 `020000`·`040000`·`060000`·`080000`·`100000`의 `pretrained_model`만 `.cache/models/act_so101_ball_to_bowl_v1/`에 받음(각 7개 파일 sha256 일치). 학습 데이터 `user/so101_ball_to_bowl_v1`, 100,000 step, 입력 state 6·front·wrist 3×480×640, n_action_steps 100. 다른 lerobot 실행 중이라 MPS 로드 시험 생략. **실제 로봇 실행 NOT VERIFIED** |
| rollout 30 Hz 미달 병목 분석(2026-10-17, 로봇·카메라 미연결) | 사용자 실측 12.5 Hz(n_action_steps=1, 앙상블 0.01). 녹화 프레임으로 공식 추론 단계별 측정: 계산 57.5 ms 중 **모델 추론 52.8 ms(92%)**, 백본(카메라 2대) 약 2/3. PyTorch-MPS에서 값이 같은 개선 없음(channels_last·배치·GPU 변환·fp16·torch.compile). **Core ML GPU fp32(같은 가중치, `.tmp`에서만 실험): 추론 36.1 ms, 틱 계산 37.7 ms(17.4→26.5 Hz), 출력 차이 0** — 의존성 추가라 미적용(승인 필요). 30 Hz는 계산만으로도 미달. 실기 단계별 계측 도구 `rollout_with_view.sh --timing`(+`--no-mirror`) 추가, verify_offline 137/137. 모터 입출력·실제 Hz는 **NOT VERIFIED**. 상세: [ROLLOUT_PERFORMANCE_REPORT.md](ROLLOUT_PERFORMANCE_REPORT.md) |
| ACT Core ML backend 구현(2026-10-17, 로봇 미사용) | 계획 [ACT_INFERENCE_OPTIMIZATION_PLAN.md](ACT_INFERENCE_OPTIMIZATION_PLAN.md) 승인·실행. macOS lock에 `coremltools==9.0`(+cattrs·pyaml, protobuf 6.32.0 공식 동일) 추가 — 공통 67개 해시 공식 lock과 일치, doctor FAIL 0. `tools/act_coreml_export.py`(변환, FP32·GPU) + `scripts/so101_act_coreml.py`(로봇 연결 전 시작 검증, 실패 시 거부) + `rollout_with_view.sh --backend=coreml --device=cpu`. 오프라인: 6에피소드 3,073틱 Core ML 대 MPS 명령 차이 최대 5.3e-5(CPU 대 MPS와 같은 수준), reset OK. 같은 발열 상태 교차 비교 틱 계산 p50 77.0→52.8 ms·p95 91.5→63.0 ms(−31%). **지속 부하에서 두 backend 모두 짧은 측정보다 느려짐**(MPS 57→77~100 ms). 30 Hz는 계산만으로도 미달. verify_offline 145/145, verify_dataset 19/19. **실기 성능·성공률 NOT VERIFIED**. 상세: [ACT_INFERENCE_OPTIMIZATION_REPORT.md](ACT_INFERENCE_OPTIMIZATION_REPORT.md) |
| 30초 추종(`./02_teleop/run.sh --time-s 30`, 17:18:52) | exit 0. **루프 구간 29.99s**, 루프 출력 1799줄, 루프 주기 중앙값 16.67 ms ≈ **60.0 Hz**(p95 16.67 ms, 최대 16.71 ms). 시작 자세 차이는 최대 1.97(gripper). 종료 후 양팔 토크 해제 재시도 **성공**(관절 12개 모두 ok). caffeinate 종료 확인. kqueue 런처 사용. 로그에 error/warn 0줄 |
| 추종(`--time-s 240`, 17:21:22) | 사용자 Ctrl+C로 종료, exit 0. 루프 구간 119.02s, 60.0 Hz, 최대 16.82 ms. 양팔 토크 해제 재시도 성공 |
| 연속 추종(`./02_teleop/run.sh`, 시간 상한 없음, 17:23:37) | 사용자 Ctrl+C로 종료, exit 0. **루프 구간 157.03s**(루프 출력 9414줄), 중앙값 16.67 ms ≈ 60.0 Hz, p95 16.67 ms, 최대 22.75 ms. 양팔 토크 해제 재시도 성공, caffeinate 종료, 로그 error/warn 0줄. **3분(180s) 기준에 못 미침 → 3분 추종은 `NOT VERIFIED`** |
| 재실행 | 17:18 → 17:21 → 17:23에 같은 설정으로 세 번 실행. 매번 정상 시작·종료, 양팔 토크 해제 성공 → 종료 후 재실행 동작은 확인됨 |
| 관절별 방향·대응 | 관찰 기록 대기(정량 오차 미측정) |
| 모터 라벨 전압·어댑터 정격·극성 | HARDWARE.md 확인표 미기록(사용자 확인 대기) |
