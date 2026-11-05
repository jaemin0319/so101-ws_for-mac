# 출처·고정 버전·재사용 범위·라이선스

## 고정 버전

| 대상 | 버전 | 확인 |
|---|---|---|
| LeRobot | 태그 `v0.6.1` = `7e241bd630a3719a56157a497ce5d08f244784f1` (lightweight 태그, 커밋 2026-08-03T14:05:01Z) | `git ls-remote`, `gh api .../git/refs/tags/v0.6.1`, `external/lerobot`에서 `rev-parse` |
| LeRobot 설치 산출물 | PyPI `lerobot-0.6.1-py3-none-any.whl` sha256 `1894516040c65f80a45bd9741f8174aae90ed5d93da0627ab4f1a85fd8d75e90` (업로드 2026-08-03T14:19:54Z) | 아래 "LeRobot 설치 방식" |
| SO-ARM100(하드웨어) | `a758567c3978dfeefe282ede0500085a48fe8f78` (2026-10-06) | 참고 전용 |
| uv | 0.12.23, `uv-x86_64-unknown-linux-gnu.tar.gz` sha256 `9167d72b3319674b6303c4cbe071854bba13ebdf3d76b1a7cbdc175471fb66d6` | 공식 `.sha256` 자산과 GitHub digest 일치 |
| Python | 3.12 (Ubuntu 24.04 시스템) | `requires-python = ">=3.12"`(v0.6.1 pyproject) |

## 고정 SHA permalink

- 코드: https://github.com/huggingface/lerobot/tree/7e241bd630a3719a56157a497ce5d08f244784f1
- 패키지 정의(extras, CLI 진입점 18개, `tool.uv.sources` torch=cu128): https://github.com/huggingface/lerobot/blob/7e241bd630a3719a56157a497ce5d08f244784f1/pyproject.toml
- 공식 잠금: https://github.com/huggingface/lerobot/blob/7e241bd630a3719a56157a497ce5d08f244784f1/uv.lock
- CLI
  - [lerobot_teleoperate.py](https://github.com/huggingface/lerobot/blob/7e241bd630a3719a56157a497ce5d08f244784f1/src/lerobot/scripts/lerobot_teleoperate.py)
  - [lerobot_calibrate.py](https://github.com/huggingface/lerobot/blob/7e241bd630a3719a56157a497ce5d08f244784f1/src/lerobot/scripts/lerobot_calibrate.py)
  - [lerobot_setup_motors.py](https://github.com/huggingface/lerobot/blob/7e241bd630a3719a56157a497ce5d08f244784f1/src/lerobot/scripts/lerobot_setup_motors.py)
  - [lerobot_find_port.py](https://github.com/huggingface/lerobot/blob/7e241bd630a3719a56157a497ce5d08f244784f1/src/lerobot/scripts/lerobot_find_port.py)
- SO-101
  - [so_follower/](https://github.com/huggingface/lerobot/tree/7e241bd630a3719a56157a497ce5d08f244784f1/src/lerobot/robots/so_follower)
  - [so_leader/](https://github.com/huggingface/lerobot/tree/7e241bd630a3719a56157a497ce5d08f244784f1/src/lerobot/teleoperators/so_leader)
  - [robots/utils.py](https://github.com/huggingface/lerobot/blob/7e241bd630a3719a56157a497ce5d08f244784f1/src/lerobot/robots/utils.py) (`ensure_safe_goal_position`)
- 버스: [motors_bus.py](https://github.com/huggingface/lerobot/blob/7e241bd630a3719a56157a497ce5d08f244784f1/src/lerobot/motors/motors_bus.py), [feetech/feetech.py](https://github.com/huggingface/lerobot/blob/7e241bd630a3719a56157a497ce5d08f244784f1/src/lerobot/motors/feetech/feetech.py)
- 문서
  - [so101.mdx](https://github.com/huggingface/lerobot/blob/7e241bd630a3719a56157a497ce5d08f244784f1/docs/source/so101.mdx)
  - [installation.mdx](https://github.com/huggingface/lerobot/blob/7e241bd630a3719a56157a497ce5d08f244784f1/docs/source/installation.mdx)
  - [il_robots.mdx](https://github.com/huggingface/lerobot/blob/7e241bd630a3719a56157a497ce5d08f244784f1/docs/source/il_robots.mdx)
- 하드웨어: https://github.com/TheRobotStudio/SO-ARM100/blob/a758567c3978dfeefe282ede0500085a48fe8f78/README.md
- 판매 제품: https://brainus.io/product_detail?PROD_CD=10001

## LeRobot 설치 방식과 근거

1. `external/lerobot`은 고정 SHA로 받는다.
   - `git clone --filter=blob:none` + `checkout --detach`. Git 추적에서 제외한다.
   - 용도: 원본 참조와 설치본 검증. 수정하지 않는다.
2. 설치는 PyPI의 lerobot 0.6.1 휠(lock에 해시 고정)로 한다. non-editable이다.
3. 동일성 근거(2026-10-08 확인):
   - 휠의 패키지 파일 **504개 전부**가 `external/lerobot/src/lerobot`의 같은 파일과 sha256이 같다.
   - 소스에만 있는 27개는 패키징 대상이 아닌 README·mdx·proto 문서다.
   - 휠 METADATA의 Requires-Dist와 18개 CLI 진입점이 고정 SHA의 `pyproject.toml`과 같다.
   - `scripts/so101 doctor`가 **설치된 파일 504개를 매번 `external/lerobot`과 바이트 비교**한다.
4. path 의존성(`external/lerobot` 직접 설치)을 쓰지 않은 이유
   - uv는 path·git 의존성의 `tool.uv.sources`도 적용한다. v0.6.1은 linux torch를 `pytorch-cu128` 인덱스로 지정해서, CPU 인덱스와 `conflicting indexes for package torch` 오류가 난다(실측).
   - 원본은 수정하지 않는다.
   - `--no-sources-package torch`는 우리 CPU 지정까지 꺼서 쓸 수 없다.

## 의존성 잠금 방식

- **정의**: `lock/pyproject.toml`
  - `lerobot[feetech]==0.6.1`, torch, torchvision
  - `[tool.uv.sources]`로 **torch·torchvision만** `https://download.pytorch.org/whl/cpu`(explicit 인덱스). 나머지는 PyPI.
  - `environments`는 linux x86_64.
- **해결 기준**
  - `exclude-newer = 2026-08-03T14:05:01Z`(고정 커밋 시각). lerobot만 휠 업로드 시각 이후(`14:30:00Z`)를 허용한다.
  - 제약 `fsspec==2026.2.0`. 공식 lock은 `datasets` 상한 때문에 이 버전을 잠갔다.
  - 이 기준으로 uv resolver가 실제로 해결한다. 공식 lock의 행을 지우거나 고쳐 만든 lock이 아니다.
- **잠금**: `lock/uv.lock`
  - 46개 패키지, 모든 휠과 sdist에 sha256이 있다.
  - 로컬 경로·editable·file URL은 없다(`--relock`이 검사).
- **설치**
  - `uv sync --locked`만 실행하고 재해결하지 않는다. lock과 정의가 어긋나면 실패한다.
  - `UV_LINK_MODE=copy`로 venv가 캐시와 파일을 공유하지 않는다.
  - 재해결은 유지보수용 `scripts/install.sh --relock`에서만 한다.
- **빌드**
  - 휠이 없는 패키지는 `feetech-servo-sdk 1.0.0` 하나다(sdist, legacy `setup.py`, sha256 `d4d3832e…e69c`).
  - 빌드 격리 환경의 setuptools는 `build-constraint-dependencies = ["setuptools==81.0.0"]`로 고정한다(공식 lock의 런타임 setuptools와 같은 버전).
  - **재현성 한계**: 빌드 결과 휠의 해시는 고정되지 않는다(소스 sdist 해시와 빌드 도구 버전만 고정).
  - 빌드 격리 환경의 setuptools 자체는 PyPI에서 받으며 그 휠 해시는 lock에 없다.
- **lock 범위 밖 기준**: 설치 기준은 SHA + `lock/pyproject.toml` + `lock/uv.lock` + Python 3.12 + uv 0.12.23 + 빌드 방식이다.
  - 시스템 `python3.12`의 패치 버전은 PC마다 다를 수 있다(연구실 3.12.3).
  - `CURRENT_STATE.md`에 기록한다.

## 공식 lock과의 차이(실제 비교)

비교 방법:
- `tools/lock_tools.py diff external/lerobot/uv.lock lock/uv.lock`
- 공식 lock을 같은 범위로 내보낸 목록과 이름 비교: `uv export --frozen --extra feetech --no-emit-project`

| 구분 | 패키지 | 공식 uv.lock (`[feetech]` 범위) | lock/uv.lock |
|---|---|---|---|
| 버전 다름 | torch | 2.11.0(비 linux), 2.11.0+cu128(linux) | 2.11.0+cpu |
| 버전 다름 | torchvision | 0.26.0, 0.26.0+cu128 | 0.26.0+cpu |
| 공식에만 | nvidia-* 15개, cuda-bindings, cuda-pathfinder, cuda-toolkit, triton | cu128 torch 의존성 | 없음(CPU 휠은 요구하지 않음) |
| 공식에만 | colorama | Windows 전용 marker | 없음(linux 전용 lock) |
| 우리에만 | lerobot 0.6.1 | 공식 lock에서는 프로젝트 자신 | PyPI 휠 |

나머지 공통 패키지 43개는 버전이 공식 lock과 같다.

## 재사용 범위(복사 없음)

| 기능 | 공식 코드 | 이 저장소에서 한 일 |
|---|---|---|
| 포트 찾기 | `lerobot-find-port` | 그대로 실행(`scripts/so101 find-port`). `ports`는 sysfs·`/dev/serial` 읽기 전용 목록 |
| 모터 ID·baud 설정 | `lerobot-setup-motors` | 인자 생성·실행 |
| 보정 | `lerobot-calibrate` | 인자 생성·실행, 보정 경로(`HF_LEROBOT_CALIBRATION`) 지정 |
| 추종 | `lerobot-teleoperate` | 인자 생성, 사전 점검, 실행, 출력 중계·기록, 종료 후 양팔 토크 해제 재시도 |
| 모터 맵·보정 파일 로드 | `SO101Follower`/`SO101Leader` 생성자 | `make_bus`가 객체를 *생성만* 하고 `bus.motors`와 `calibration`을 가져와 별도 `FeetechMotorsBus` 구성 |
| 읽기 | `FeetechMotorsBus.connect(handshake=False)`, `ping`, `read`, `sync_read`, `disconnect(disable_torque=False)`, `scan_port` | probe |
| 토크 해제 | `FeetechMotorsBus.disable_torque`(Torque_Enable=0, Lock=0), `set_timeout` | teleop 종료 후 정리 |
| 인자 파싱 확인 | `TeleoperateConfig` + draccus | dry-run/doctor |

공식 코드는 수정하지 않았다(원본 diff 없음).

## 공식 동작에서 확인한 사항 (v0.6.1 코드 기준)

- `lerobot-teleoperate`: `teleop.connect()` → `robot.connect()`이며, 두 connect 모두 `calibrate=True`가 기본이다.
  - 보정 파일이 없거나 레지스터와 다르면 대화형 보정을 시작한다. 파일이 있으면 Enter=파일을 모터에 기록, `c`=재보정이다.
  - 루프 중 `KeyboardInterrupt`는 `pass` 처리되고, `finally`에서 `teleop.disconnect()` 다음 `robot.disconnect()`를 **순서대로** 호출한다. 앞쪽이 예외를 내면 뒤쪽이 호출되지 않는다. 그래서 래퍼가 종료 후 독립 정리를 한다.
  - SIGHUP은 처리하지 않는다. 그래서 래퍼는 자식에서 SIGHUP을 무시시키고, 대신 SIGINT를 전달한다.
- 팔로워 `connect` → `configure()`: `torque_disabled()` 안에서 PID(16/0/32)·가속도(254)·gripper 토크 한도를 쓰고, 빠져나오면서 토크를 켠다.
  - 리더 `configure()`는 토크를 끈다.
- `disconnect`: 팔로워는 `disable_torque_on_disconnect=True`(기본)일 때 `disable_torque(num_retry=5)` 후 포트를 닫는다.
- `max_relative_target: float | dict[str, float] | None`(기본 None). `send_action`마다 Present_Position을 읽고 `goal = present + clip(goal - present, ±cap)`을 적용한다.
  - dict는 6개 관절 키가 정확히 같아야 하며, 아니면 ValueError가 난다.
  - draccus는 CLI의 `5`도 float 5.0으로 파싱한다(실측). 원본 계획에서 우려한 int 함정은 CLI 경로에서는 없다.
- Feetech handshake(`bus.connect(handshake=True)`): 모델 확인 ping + 펌웨어 읽기(읽기 전용). 펌웨어가 다르면 RuntimeError가 나서 공식 calibrate·teleop 연결이 실패한다.
- 기본 baud 1,000,000, 패킷 timeout 1000 ms, 프로토콜 0, `num_read_retries` 기본 2. teleop 기본 `fps=60`.
- 보정 파일 경로: `HF_LEROBOT_CALIBRATION/{robots|teleoperators}/{so_follower|so_leader}/{id}.json`. 클래스 `name`이 so101이 아니라 `so_follower`/`so_leader`다.

## 라이선스 (원문 확인)

| 대상 | 라이선스 | 근거 |
|---|---|---|
| LeRobot | Apache License 2.0 | `external/lerobot/LICENSE` 원문(“Apache License Version 2.0, January 2004”, “Copyright 2024 The Hugging Face team”), 휠 METADATA `License: Apache-2.0` |
| SO-ARM100 | Apache License 2.0 | 고정 SHA의 `LICENSE` 원문 |
| feetech-servo-sdk 1.0.0 | Unlicense(퍼블릭 도메인 선언) | sdist의 `LICENSE` 원문 |

- 이 저장소는 위 코드를 복사하지 않고, 설치와 호출만 한다.
- 문서의 공식 동작 설명은 고정 SHA 코드를 읽고 요약한 것이다.

---

# macOS arm64 추가분 (2026-10-09, 호스트 user-MacBookAir.local)

## 고정 버전(macOS)

| 대상 | 값 | 확인 |
|---|---|---|
| uv | 0.12.23 `uv-aarch64-apple-darwin.tar.gz` sha256 `50487ae565ccd96e499056b4674d438f4c53170202617b4c759defe0c6a1b544`. 아카이브 구조 `uv-aarch64-apple-darwin/{uv,uvx}` | 공식 `.sha256` 사이드카·`sha256.sum`·`dist-manifest.json`·GitHub digest 일치, 내려받은 바이트로 `sha256sum -c` 통과 |
| Python | CPython **3.12.15**, uv managed(python-build-standalone) `cpython-3.12.15-macos-aarch64-none`. 작업공간 `.tools/python`, `--no-bin` | `uv python list 3.12 --only-downloads`로 uv 0.12.23이 아는 최신 3.12 패치를 확인. 다운로드 무결성은 uv에 내장된 해시로 검증 |
| torch / torchvision | 2.11.0 / 0.26.0, PyPI `cp312-cp312-macosx_11_0_arm64` | 공식 `uv.lock`의 darwin 항목과 같은 휠 sha256. download.pytorch.org/whl/cpu의 맥 torch 휠은 PyPI와 sha256이 달라 쓰지 않음 |
| 의존성 정의 | `lock/macos-arm64/pyproject.toml` sha256 `edfaa16b…`: `lerobot[feetech,dataset]==0.6.1`, torch, torchvision, **`coremltools==9.0`**(2026-10-17 추가, ACT Core ML backend용·사용자 승인). `environments = darwin arm64`. Linux와 같은 `exclude-newer`(2026-08-03T14:05:01Z, lerobot만 14:30:00Z)·`fsspec==2026.2.0`·**`protobuf==6.32.0`**(공식 lock과 같은 버전)·빌드 제약 `setuptools==81.0.0` | — |
| lock | `lock/macos-arm64/uv.lock` sha256 `0ec978cd…`(이전 `54e73e1d…`). 패키지 71개(가상 프로젝트 제외; coremltools·protobuf·cattrs·pyaml 추가, 기존 67개 버전 변화 없음), 모든 파일 sha256, 소스 빌드는 `feetech-servo-sdk`뿐 | `tools/lock_tools.py check-macos` 통과, `scripts/install_macos.sh --relock` 후 doctor FAIL 0 |
| 플랫폼 고정값 | `lock/macos-arm64/platform.env`(UV_ASSET·UV_SHA256·PYTHON_VERSION·MACOS_MIN=13.0·LEROBOT_EXTRAS) | MACOS_MIN은 opencv·av 휠 태그 `macosx_13_0_arm64` 기준 |

## 공식 lock과의 비교(macOS)

- **방법**
  - 버전 비교: `tools/lock_tools.py diff external/lerobot/uv.lock lock/macos-arm64/uv.lock`
  - 휠 해시 비교: `tools/lock_tools.py hashes …`. 같은 이름·버전 패키지의 cp312 macOS arm64 설치 대상 휠 sha256을 비교한다.
- **결과**(2026-10-17 coremltools 추가 후)
  - 공통 패키지 버전 차이 **0**, 공통 패키지 휠 해시 **67/67 일치**(protobuf 6.32.0 포함)
  - 공식 lock에 없는 패키지 3개: `coremltools 9.0`, `cattrs 26.1.0`, `pyaml 26.7.0`(Core ML backend 전용, macOS lock에만)
  - 참고: coremltools 9.0은 실행 시 "Torch 2.11.0 has not been tested(2.7.0까지 시험)" 경고를 낸다. 그래서 변환은 `tools/act_coreml_export.py`에서 한 번만 하고 결과를 PyTorch와 대조해 저장하며, rollout 중에는 컴파일본만 로드한다(docs/ACT_INFERENCE_OPTIMIZATION_REPORT.md)
  - 이전(coremltools 추가 전): 버전 차이 0, 공통 해시 66/66 일치
  - `lerobot`은 공식 lock에서 프로젝트 자신(editable)이라 비교하지 않는다. 우리 쪽은 PyPI 휠 sha256 `18945160…`(Linux lock과 같음)이다.
- **해석**: 맥 lock은 공식 lock의 darwin arm64 해결 결과에서 `[feetech,dataset]` 범위만 해시 그대로 잘라 낸 것과 같다. 수동으로 고친 값은 없다.
- **Linux lock과의 차이**: 플랫폼 빌드 차이와 extras 차이 두 가지다.
  - 플랫폼 빌드: torch `+cpu` → 맥 PyPI 빌드.
  - extras: `dataset`이 추가되어 datasets·pandas·pyarrow·av·jsonlines·torchcodec와 그 의존성 21개가 더 들어간다.
  - 공통 46개 패키지의 버전은 torch·torchvision 표기 외에 같다.

## LeRobot 설치본 동일성(macOS)

- PyPI 휠 설치 파일 504개(doctor 실측)가 고정 SHA `src/lerobot`과 바이트 단위로 같다.
- doctor가 실행될 때마다 다시 비교한다. 파일 수는 하드코딩하지 않는다.

## 재사용 범위 추가(macOS·데이터셋)

| 기능 | 공식 코드 | 이 저장소에서 한 일 |
|---|---|---|
| 녹화 | `lerobot-record`(`lerobot/scripts/lerobot_record.py`) | 인자 생성, 사전 점검, 실행, 기록, 종료 후 양팔 토크 해제 재시도. 고정 인자: `push_to_hub=false`, `no_stamp=true`, `video_encoding_batch_size=1`, `play_sounds=false`, `display_data=false` |
| 카메라 탐색 | `lerobot-find-cameras opencv` | 그대로 실행. `cameras --test`는 공식 `OpenCVCamera`로 connect·read·disconnect만 한다 |
| 데이터셋 읽기·쓰기 | `LeRobotDataset.create/add_frame/save_episode/finalize`, `LeRobotDataset(..., video_backend="pyav")`, `LeRobotDatasetMetadata` | 합성 시험 생성(`tools/verify_dataset.py`), 검사(`so101_dataset.inspect_dataset`) |
| 특징 정의 | `SO101Follower`(연결 없음) + `hw_to_dataset_features` | resume 호환성 확인·합성 시험에 사용(lerobot-record와 같은 방식) |
| 키 입력 | `init_keyboard_listener`. pynput이 없거나 신뢰되지 않으면 `TerminalKeyListener`(n/r/q, 방향키·Esc) | pynput(`hardware` extra)을 설치하지 않아 터미널 방식을 쓴다 |
| 영상 디코드 기본값 | `get_safe_default_video_backend`. torchcodec을 로드할 수 없으면 pyav로 대체 | 그대로. 검사는 pyav를 명시 |

## macOS 전용 확인 사항(v0.6.1 코드)

- `lerobot-find-port`는 macOS에서 `/dev/tty*`를 glob한다(`lerobot_find_port.py`). `cu.*`는 나오지 않으므로 tty/cu 이중 계산이 없다.
  - 래퍼의 `ports.sh`는 pyserial `comports()`를 쓴다. pyserial 3.5 `list_ports_osx.py`가 `IOCalloutDevice`, 즉 `/dev/cu.*`만 반환하고, 비USB 항목은 `vid=None`이다.
- `lerobot-record`의 종료 순서(`finally`)는 `dataset.finalize()` → `robot.disconnect()` → `teleop.disconnect()` → (push_to_hub이면 업로드)다.
  - `num_episodes`는 이번 실행에서 녹화할 수다. resume이어도 추가 수다.
  - `--dataset.root`는 데이터셋 폴더 자체이며, 새로 만들 때 이미 있으면 안 된다(`mkdir(exist_ok=False)`).
- 저장 timestamp는 `frame_index / fps`다(`dataset_writer.add_frame`). 실제 루프 지연은 "Record loop is running slower (X Hz)" 경고로만 드러난다.
- torchcodec 0.11.1은 외부 FFmpeg 4–8 dylib가 없으면 로드되지 않는다(이 맥 실측). 인코딩은 PyAV 15.1.0 내장 FFmpeg가 맡는다.
  - 이 맥에서 쓸 수 있는 인코더: libsvtav1, libaom-av1, h264(libx264), hevc, h264_videotoolbox, hevc_videotoolbox.
- `opencv-python-headless` 4.13.0.92와 `av` 15.1.0이 각각 `libavdevice.61.3.100.dylib`를 포함한다. 둘을 함께 import하면 objc 중복 클래스 경고가 난다(doctor WARN).

## 검증 도구의 macOS 대응(시험 전용)

- macOS pty는 pyserial이 1,000,000 baud에 쓰는 `IOSSIOSPEED` ioctl을 지원하지 않는다(실측 `Errno 25 ENOTTY`).
  - `tools/verify_offline.py`는 `/dev/ttys*`(pty)에서만 이 오류를 무시하는 shim을 쓴다.
  - 실제 USB 장치 경로는 바꾸지 않는다.
- macOS에서 slave가 열려 있지 않은 pty master를 read하면 EOF(0바이트)가 돌아온다(Linux는 EIO). 가짜 서보 버스가 이 경우를 기다리도록 처리했다.

## 출처(macOS 추가)

- uv 릴리스: https://github.com/astral-sh/uv/releases/tag/0.12.23
- uv 문서: https://docs.astral.sh/uv/reference/environment/, https://docs.astral.sh/uv/concepts/python-versions/, https://docs.astral.sh/uv/concepts/resolution/, https://docs.astral.sh/uv/concepts/projects/sync/
- PyPI: https://pypi.org/project/torch/2.11.0/, https://pypi.org/project/torchvision/0.26.0/, https://pypi.org/project/lerobot/0.6.1/
- LeRobot 문서(고정 SHA 코드 우선): https://huggingface.co/docs/lerobot/so101, https://huggingface.co/docs/lerobot/installation, https://huggingface.co/docs/lerobot/v0.6.1/il_robots, https://huggingface.co/docs/lerobot/cameras, https://huggingface.co/docs/lerobot/lerobot-dataset-v3
- 공식 예제·코드를 이 저장소로 **복사하지 않았다.** 모두 설치된 공식 패키지를 호출한다. 라이선스 표는 위와 같다.
