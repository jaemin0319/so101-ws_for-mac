# Claude Code 실행 요청 — macOS SO-101 설치·초기 세팅·텔레옵·데이터셋 생성

첨부 계획서 `so101_macos_plan.md`를 바탕으로 **지금부터 구현·설치·무로봇 검증·매뉴얼·결과 보고까지 진행해줘.** Plan 작성만 하고 종료하지 않는다.

## 1. 확정 목표와 우선순위

- 실제 작업 PC: MacBook Air M4, native macOS arm64.
- **작업공간: `~/so101-ws_for-mac`**. 내가 이미 만든 폴더를 사용한다. 실제 디렉터리인지, 권한과 남은 공간을 먼저 확인한다.
- 기존 프로젝트: https://github.com/user/so101-ws
- 작업 범위: **초기 세팅(USB 포트·모터 ID·캘리브레이션) / 텔레옵 / 로컬 데이터셋 생성**의 세 단계.
- 공식 LeRobot과 기존 Ubuntu 코드를 적극적으로 재사용한다. ROS·Ubuntu·VM·Docker는 설치하지 않는다.
- 코드·의존성·가상환경·공식 참조 소스·캐시·보정·로그·데이터·문서를 이 작업공간에서 관리한다.
- **이 요청이 첨부 계획의 경로·폴더 구조·녹화 범위보다 우선한다.** `~/so101_ws`는 만들지 않고, 별도 작업공간이나 그 경로로의 링크도 만들지 않는다.
- 기존 Linux 기능은 보존한다. GitHub commit·push·저장소 공개 범위 변경, Hub 업로드, 학습·추론은 이번에 실행하지 않는다.

소프트웨어 구현과 설치·검증은 이번 요청으로 승인한다. 자동으로 실제 모터 ID 설정·보정·추종·실로봇 녹화를 시작하지 않는다. 실기 조건은 8절을 따른다. 로봇이 없거나 아직 현장 준비를 확인하지 못했어도 **세 단계의 구현과 가능한 소프트웨어 검증을 모두 완료**하고, 실기만 `NOT VERIFIED`로 보고한다.

## 2. 기존 폴더와 Git을 보존하며 시작

1. 현재 VS Code 폴더, `~/so101-ws_for-mac`, 계획서, 추적·미추적 파일, `.git` 유무·HEAD·remote·브랜치·변경 사항을 조사한다. 계획 당시 15:25경 생긴 `.git`은 **커밋 없음 / main / remote 없음**이었다. 현재 상태를 다시 확인한다.
2. 기존 계획서와 내가 넣어 둔 파일을 보존한다. `~/so101-ws_for-mac` 안에 다른 `so101-ws/`를 중첩 clone하지 않는다. **작업공간 루트가 프로젝트 루트이자 Git 작업 트리**가 되게 한다.
3. 기존 `.git`이 커밋 없는 저장소라면 이를 재사용해 올바른 origin을 연결하고 fetch한 뒤, 원격 main을 기준으로 충돌 없는 작업 브랜치를 준비한다. 기존 파일과 원격 파일이 충돌하면 내용을 비교하고 작업공간의 Git 제외 백업에 보존한 다음 처리한다. `reset --hard`, `clean -fd`, 강제 checkout, `.git` 삭제로 해결하지 않는다.
4. 이미 같은 프로젝트의 정상 저장소라면 기존 변경을 보존하며 활용한다. 다른 저장소의 이력·remote·작업물이 있다면 이를 덮어쓰지 않는다. 복구 불가능한 조치가 필요한 경우에만 구체적으로 보고하고, 독립적으로 진행 가능한 조사는 계속한다.
5. 가져온 원격 SHA와 시작 상태를 기록한다. 조사 당시 SHA는 `ae8bb236f22beb7afad999505ed2e4b79c063055`지만 최신 원격을 실제 확인한다.
6. `AGENTS.md`, README, 기존 문서·설치기·CLI·lock·검증 도구를 읽는다. 이 요청으로 승인한 **macOS 설치·로컬 데이터셋 생성 지원**에 맞춰 AGENTS 범위를 최소 수정한다. 학습·추론·외부 업로드·시스템 변경 제한은 유지한다.
7. 원본 계획을 보존해 `docs/so101_macos_plan.original.md`에 둔다. 작업 경로·폴더·녹화 범위를 반영한 계획은 `docs/so101_macos_plan.md`로 갱신하고, 이 실행 요청도 `docs/so101_macos_execution_request.md`에 보관한다. 이미 같은 파일이 있으면 비교·보존 후 갱신한다.

## 3. 적용할 파일 구조

사용자용 실행 파일은 다음 경로로 제공한다. 기능을 구현하는 공통 코드는 기존 `scripts/so101`·`scripts/so101.py`와 필요한 작은 헬퍼에서 공유한다. 단계별 스크립트마다 모터 드라이버나 종료 로직을 복제하지 않는다.

| 경로 | 필수 역할 |
|---|---|
| `01_setup/install.sh` | macOS 설치 진입점. 기존 옵션 전달, 재실행·복구 지원 |
| `01_setup/doctor.sh` | 소프트웨어 점검, 필요 시 hardware scope 인자 전달 |
| `01_setup/ports.sh` | 리더·팔로워 USB 포트 식별·로컬 설정 저장. 자동화는 포트 설정까지만 |
| `01_setup/probe.sh` | 지정 역할의 모터 읽기 전용 확인 |
| `01_setup/motors.sh` | 지정 역할의 공식 모터 ID·baud 설정 |
| `01_setup/calibrate.sh` | 지정 역할의 공식 보정 |
| `02_teleop/run.sh` | 공통 설정으로 공식 리더·팔로워 추종 실행 |
| `03_dataset/cameras.sh` | 공식 도구 기반 카메라 탐색·선택·설정 확인 |
| `03_dataset/record.sh` | 공식 `lerobot-record` 기반 로컬 데이터셋 생성 |
| `03_dataset/inspect.sh` | 공식 LeRobotDataset으로 데이터셋을 다시 열고 검사 |
| `configs/` | robot·camera·recording 설정 예시와 Git 제외 로컬 설정 |
| `calibration/` | 공식 형식의 리더·팔로워 보정 파일 |
| `datasets/` | 데이터셋별 공식 `meta/`·`data/`·`videos/` 구조 |
| `scripts/` | 기존 공통 CLI, macOS 설치기, 작은 플랫폼·종료·녹화 헬퍼 |
| `lock/macos-arm64/` | 맥 전용 의존성 정의·해시 lock·플랫폼 고정값 |
| `external/lerobot/` | 고정 SHA의 공식 참조 소스. 원본 수정 금지 |
| `tools/` | 기존 무로봇 검증 및 필요한 녹화·데이터 검증 도구 |
| `docs/` | 계획·레퍼런스·단계별 사용 매뉴얼·CURRENT_STATE·결과 보고 |
| `logs/` | 설치·통신·추종·녹화 실행 기록 |

환경·도구·캐시·임시 파일은 `.venv/`, `.tools/`, `.cache/`, `.tmp/`에 모은다. 디렉터리는 실제 필요할 때 만든다. 학습 출력 폴더는 이번에 불필요하다.

기존 `scripts/install_macos.sh` 설계와 `scripts/setup_robot.sh` 설계를 재사용하되, 사용자 안내는 `01_setup/` 진입점으로 통일한다. 기존 Linux 명령과 경로는 유지한다.

공통 규칙:

- 어느 현재 디렉터리에서 호출해도 **스크립트 위치 기준으로 프로젝트 루트**를 찾는다. 코드와 lock에 `/Users/user`을 하드코딩하지 않는다. 이번 설치 대상만 위 절대경로로 고정한다.
- 파일 실행 권한과 `--help`를 제공한다. venv 활성화나 VS Code Python 선택이 달라도 지정된 프로젝트 Python을 사용한다.
- 역할 인자가 필요한 명령에 `leader` 또는 `follower`를 받는다. 잘못된 인자나 누락을 친절하게 안내하고 임의로 역할을 선택하지 않는다.
- `--dry-run`은 공식 명령·설정·인자만 검사하고 **포트·카메라를 열거나 장치를 생성·구동하지 않는다.**
- 스크립트별 README 또는 연결된 짧은 단계 매뉴얼을 둔다. 실패 메시지는 다음 조치를 알려준다.

## 4. 고정 설치와 레퍼런스 재사용

첨부 계획의 macOS 조사 결과를 출발점으로 사용하되, 다운로드 파일과 실제 환경으로 재확인한다.

- LeRobot: `v0.6.1`, SHA `7e241bd630a3719a56157a497ce5d08f244784f1`을 유지한다. 공식 모터 통신·보정·추종·녹화·데이터 포맷을 그대로 사용한다.
- uv: 0.12.23, 공식 `uv-aarch64-apple-darwin.tar.gz`. 계획의 SHA256 `50487ae565ccd96e499056b4674d438f4c53170202617b4c759defe0c6a1b544`와 공식 출처 및 다운로드 바이트를 대조한다. 다르면 실행하지 않고 원인을 조사한다.
- Python: uv managed **정확한 3.12 패치 버전**을 확정·고정하고 작업공간 `.tools/python`에 설치한다. `--no-bin` 또는 해당 버전에서 지원하는 로컬 bin 경로를 사용한다. 기존 python.org Python·셸 초기화·사용자 전역 PATH를 바꾸지 않는다.
- torch 2.11.0·torchvision 0.26.0: macOS arm64 PyPI 배포본을 사용한다. Linux CPU 인덱스와 `+cpu` 요구를 맥에 강제하지 않는다. 텔레옵·녹화에 GPU/MPS를 요구하지 않는다.
- **데이터셋 생성이 이번 구현 범위에 포함됐으므로 `[feetech]`만으로 종료하지 않는다.** 고정 버전의 extras·실제 import를 조사해 `[feetech,dataset]` 등 필요한 최소 구성을 확정한다. `[all]`, training·policy 대형 패키지는 넣지 않는다.
- 기본 권장안은 **macOS 통합 lock 하나와 `.venv` 하나**로 세 단계를 지원하는 것이다. 기본 extras와 녹화 extras를 나눠야 할 실제 이유가 있으면 한 프로젝트의 optional extras로 정리하고, 활성 extras를 설치·doctor·lock 검사에 일관되게 반영한다. 별도 venv 두 개를 기본으로 만들지 않는다.
- 최초에만 실제 resolver로 macOS lock을 생성한다. 이후 설치는 `--locked`로 고정한다. 최초 생성에 필요한 제약·기준 시각·예외를 기록한다.
- 공식 lock의 macOS 해당 패키지와 가능한 버전·wheel 해시를 비교한다. 차이가 생기면 요구한 녹화 extras나 실제 호환성에 근거해 설명한다. 비교할 공통 패키지와 추가·제외 패키지를 구분한다. **차이 0을 만들려고 해시나 lock을 수동 조작하지 않는다.**
- 공식 PyPI 휠의 패키지 소스를 고정 SHA와 비교하는 doctor 검사를 재사용한다. 파일 수는 실측한다.
- 설치·캐시 파일은 분리하고 정상 재실행·누락 복구·손상 진단·repair를 구현한다. managed Python 손상과 venv 손상을 구분해 복구한다.
- macOS bash 3.2·BSD 도구 호환성을 확인한다. `readlink -f` 등이 이 맥에서 동작하더라도 더 넓은 버전 호환성을 근거 없이 주장하지 않는다.
- 시스템 Python·Homebrew·conda·보안 설정·드라이버·셸 초기화 파일을 자동 변경하지 않는다. 다른 프로젝트의 캐시나 파일을 지우지 않는다.

영상 의존성은 실제 **인코딩 + 재열기·디코딩**까지 확인한다. PyAV backend로 충분하면 공식 설정으로 선택하고 검증 도구와 연구실 이관 안내에도 같은 backend를 쓴다. torchcodec가 필수로 import되는지, 외부 FFmpeg가 필요한지는 고정 버전 코드와 실행으로 판정한다. "av import 성공"이나 `ffmpeg --version`만으로 녹화 준비 완료라고 하지 않는다. 코덱을 사용할 수 없으면 해당 버전이 지원하는 다른 코덱으로 시험하고 변경 근거를 적는다.

디스크는 다시 측정한다. 계획의 약 12 GiB를 현재 값으로 간주하지 않는다. 설치·캐시·managed Python·별도 재현본·영상 시험에 필요한 peak 용량을 추정하고 순차적으로 검사한다. 시험 규모를 작게 시작하며, 공간 부족이면 사용자의 파일을 정리하지 말고 생성한 임시 시험 파일만 정리한다. 짧은 녹화에도 외장 저장소가 반드시 필요하다고 미리 단정하지 않는다.

## 5. 초기 세팅 구현

### 5.1 USB 포트 지정 — 자동화는 여기까지

`01_setup/ports.sh`는 아래 흐름만 실행한다.

1. 모터 외부 전원 OFF, 양팔 USB 분리 안내 → Enter.
2. 리더 USB 연결 안내 → Enter → 읽기 전용 장치 열거 차이로 식별.
3. 팔로워 USB 연결 안내 → Enter → 차이로 식별.
4. 역할별 포트·USB 정보·물리 팔 장치 ID를 표시하고 사용자가 확인하면 설정 저장.
5. 전원 확인·probe·필요한 모터 설정·보정·실행 명령을 출력하고 종료.

- pyserial `comports()`와 macOS USB 정보 조회를 우선 사용하며, 시리얼 포트를 열지 않는다.
- `/dev/tty.*`와 `/dev/cu.*` 별칭은 같은 보드로 묶는다. 단순 `realpath`가 두 노드를 같은 장치로 합쳐준다고 가정하지 않는다.
- Bluetooth·debug-console 등 비USB 항목을 로봇 후보에서 제외한다.
- 후보 0개는 재시도·취소, 여러 개는 사용자 선택이다. 발견 순서로 역할을 추측하지 않는다.
- 동일 보드에 두 역할을 지정하지 않는다. 빈 serial이나 같은 제조사 정보만으로 **서로 다른 물리 USB 위치의 보드까지 같은 보드로 오판하지 않는다.**
- 고유 serial이 있으면 이를 주 식별자로 쓰고 USB 위치 변화는 별도로 안내한다. serial이 없거나 중복이면 location·동일 허브 단자와 재식별 절차를 사용한다. 정보가 부족하면 자동 실행을 거부하고 재확인을 안내한다.
- 기존 장치 ID·다른 설정·주석을 보존한다. 저장 전 변경 내용을 확인하고 백업·재파싱·동일 디렉터리 임시 파일·원자적 교체를 한다. 취소·예외 시 원본을 유지한다.
- 파일이 없으면 예시에서 새로 만든다. 예시의 임의 장치 ID를 실제 팔 ID로 조용히 확정하지 않는다.
- macOS `lsof` 점유 진단은 tty/cu 별칭을 모두 고려한다. 열람 권한·검사 실패는 "점유 없음"으로 처리하지 않는다.
- USB만으로 해당 보드가 열거되는지 실제 연결 전에는 `NOT VERIFIED`로 둔다.

### 5.2 모터 ID와 보정

`01_setup/probe.sh`, `motors.sh`, `calibrate.sh`는 기존 공통 래퍼와 공식 API/CLI를 사용한다.

- probe는 모델·ID·위치·보정 상태 등을 읽으며 모터 쓰기 0건을 유지한다.
- 통신 실패는 전원 → 케이블 → 보드 모드 → 포트 → baud 순으로 진단한다. 무조건 초기화·펌웨어 갱신·재설정하지 않는다.
- 이미 올바르게 설정된 모터의 ID·baud는 다시 쓰지 않는다.
- 모터 ID는 베이스부터 `1~6`: shoulder_pan / shoulder_lift / elbow_flex / wrist_flex / wrist_roll / gripper.
- ID 설정은 역할별 공식 프롬프트 순서로 모터 한 개만 연결한다. **해당 모터에서 다른 모터로 이어지는 연결도 분리**해 버스에 한 개만 남긴다. 조립 후 설정도 가능하며 케이블 교체 전에 모터 전원을 끈다.
- 장치 ID 문자열은 물리 팔을 구분하는 보정 파일 이름이며 모터 ID와 다르다. 다른 팔의 보정 파일을 복사하지 않는다.
- 보정 파일이 없거나 실제 모터 레지스터와 불일치할 때 공식 보정을 한다. 기존 파일 재사용·재보정 선택과 가운데 자세·가동 범위 기록은 고정 버전 프롬프트 기준으로 안내한다.
- `calibration/robots/so_follower/<id>.json`, `calibration/teleoperators/so_leader/<id>.json` 구조를 유지하고 모든 단계가 이를 공유한다.

## 6. 텔레옵·종료 처리

`02_teleop/run.sh`는 공통 설정과 공식 `lerobot-teleoperate`를 사용한다.

- 포트·역할·모터 응답·보정 파일과 실제 레지스터·시작 자세를 검사한다. 불일치한 채로 추종을 시작하거나 자동 재보정하지 않는다.
- `--dry-run`, `--time-s 30`, 정상 종료·재실행을 지원한다. 실측 루프 Hz·루프 구간·공식 출력·종료와 토크 해제 결과를 기록한다.
- 양팔 추가 토크 해제는 각각 독립적으로 수행한다. 한쪽 실패 때문에 다른 팔 처리를 생략하지 않는다. 기존 cleanup 쓰기 범위를 불필요하게 넓히지 않는다.
- Ctrl+C·SIGTERM·SIGHUP·시간 제한·자식 무응답을 처리한다. 부모 강제 종료 감시가 필요한 맥에서 계획의 kqueue 런처를 사용할 수 있지만 **방법을 먼저 검증한 다음 채택**한다.
- 런처를 쓰면 공식 CLI의 `argv`, console entry point, 종료 코드·신호·traceback을 보존한다. `runpy` 시작 전후 SIGINT 핸들러·부모 종료 race·PID 재사용·감시 등록 실패·stderr 종료·SIGINT 중복을 실제 가짜 프로세스/가짜 서보로 확인한다. 부모 정상 종료와 무응답 자식 escalation 경로도 확인한다.
- 모든 프로세스가 SIGKILL되거나 USB가 끊기면 토크 해제 전달을 보장할 수 없음을 간단히 설명한다. 고아 방지가 검증되지 않았는데 성공으로 표시하지 않는다.
- `caffeinate`는 팔을 사용하는 공식 실행 프로세스에 맞춰 유지하고, 실행 실패·취소·시간 제한·정상 종료 때도 종료한다. 입력 대기와 실행 단계의 수명을 확인한다. 덮개 닫기 절전은 방지한다고 주장하지 않는다.
- 매뉴얼에 쉬는 자세 → 팔로워 받치기 → Ctrl+C → 토크 해제 확인, 실패 시 받친 상태에서 전원 차단을 넣는다.

## 7. 데이터셋 생성 — 이번에 실제 구현할 필수 기능

첨부 계획의 선택 2단계를 **구현 범위에 포함**한다. 카메라·모터가 없어 실제 수집을 못 하더라도 녹화 진입점·설정·소프트웨어 검증·매뉴얼을 구현한다. 디렉터리나 빈 스크립트만 만들어 완료로 처리하지 않는다.

### 7.1 설정과 카메라

- `configs/cameras.example.yaml`, `configs/recording.example.yaml`과 Git 제외 로컬 설정을 제공한다. 기존 robot 설정을 공유한다.
- 카메라 이름, device/index, 해상도, FPS와 task, dataset name, episode time, reset time, episode count, 저장 경로를 설정할 수 있게 한다.
- `03_dataset/cameras.sh`는 공식 탐색 도구를 우선 사용하고 결과를 표시한다. 실제 사용 가능한 카메라가 있으면 로봇 없이 짧은 프레임 읽기 시험을 할 수 있다. 선택하지 않은 내장/iPhone 카메라를 자동 녹화 대상으로 확정하지 않는다.
- macOS 카메라 권한은 실제 요청이 생길 때 사용자가 OS 화면에서 허용하도록 안내한다. 권한을 자동 변경하거나 불필요하게 Accessibility 권한을 요구하지 않는다.
- 카메라 index는 재연결·연속성 카메라 때문에 달라질 수 있다. 세션별 확인을 안내한다. 해상도·요청 FPS와 실제 제공 결과를 확인한다.
- 카메라 실측 FPS와 로봇 녹화 루프 FPS·저장 timestamps의 의미를 구분한다. 목표 FPS만으로 영상 품질·시간 동기화 성공을 판단하지 않는다.

### 7.2 공식 녹화 실행

- `03_dataset/record.sh`는 공식 `lerobot-record`를 호출한다. 자체 카메라·모터 녹화 루프를 작성하지 않는다.
- 녹화 CLI가 리더·팔로워 제어를 함께 실행하므로 텔레옵 프로세스를 별도로 동시에 띄우지 않는다. 중복 점유 시 안내한다.
- 로봇·보정·시작 자세 사전 점검, 대화형 확인, 신호 전달, 토크 해제, 절전 방지·로그를 텔레옵과 공유한다. 녹화 특유의 종료·dataset finalize 처리도 확인한다.
- 기본 저장은 `~/so101-ws_for-mac/datasets/<dataset_name>/`이며 코드에서는 프로젝트 상대경로로 계산한다. 명시적 경로 옵션으로 외장 저장소를 사용할 수 있게 하되 디렉터리가 실제 존재·쓰기 가능한지 확인한다.
- 공식 `--dataset.root`, `repo_id`, `no_stamp`, resume 의미를 실제 v0.6.1 코드·help로 확인하고 서로 일관되게 적용한다. root와 실제 repo_id·session suffix를 출력·기록한다.
- **`--dataset.push_to_hub=false`를 명시적으로 적용하고 이번 래퍼에서는 업로드 활성화를 허용하지 않는다.** HF 로그인·토큰을 필수 조건으로 만들지 않는다.
- 기존 데이터가 있으면 덮어쓰거나 삭제하지 않는다. 명시적 resume 또는 새 이름을 안내한다. resume은 기존 카메라·관절 schema·FPS·task 정보와 호환되는지 검사한다. episode count가 추가 횟수인지 실제 버전 기준으로 안내한다.
- 선택한 카메라 누락·잘못된 task·0 또는 음수 설정·공간 부족·보정 불일치 시 모터 구동 전에 실패한다.
- CLI 인자와 키보드 제어는 고정 버전 기준으로 검증한다. 공식 TTY fallback을 우선 활용하고 `n/r/q`·타이머·Ctrl+C 동작을 문서화한다. `pynput` 미설치가 해당 경로에서 처리되는지 실제 시험한다.
- 기본 짧은 현장 시험 설정은 예를 들어 카메라 한 대, 640×480, 30 FPS, 20초×2개 에피소드로 제공한다. 실제 카메라가 지원하지 않으면 지원값으로 조정하고 이유를 기록한다.
- 끊김·예외·정상 종료 시 공식 finalize와 영상 인코딩의 완료 여부를 기록한다. 로봇 토크 해제까지 대용량 인코딩을 기다리는지 고정 버전의 정리 순서를 검토하고, 불필요하게 지연되는 경우 최소한의 래퍼 개선과 검증으로 처리한다.

### 7.3 저장·검사·이관

- 데이터셋 내부는 공식 LeRobotDataset의 `meta/`, `data/`, `videos/` 형식을 그대로 사용한다. episode별 폴더나 커스텀 CSV 포맷을 새로 강제하지 않는다.
- `03_dataset/inspect.sh <dataset_path>`는 실제 LeRobotDataset으로 열어서 schema·에피소드·프레임·timestamps·영상 디코딩·NaN·누락을 검사한다. **검사 자체가 모터를 연결하거나 녹화하지 않는다.**
- 관절 이름·순서·단위와 `observation.state`·`action` shape를 확인한다. 6개라는 숫자만 맞는다고 동일 의미로 판정하지 않는다.
- timestamps의 단조 증가·간격은 **각 episode 안에서** 확인한다. 에피소드마다 0부터 시작하는 것을 오류로 세지 않는다.
- v3의 공유 Parquet/MP4와 에피소드 offset 정보를 이용해 행·영상 구간을 비교한다. "MP4 하나=에피소드 하나"로 가정하지 않는다. dropped frame·중복 영상 등 판정 기준과 실제 측정 한계를 적는다.
- task가 어떤 column/metadata로 보존되는지는 고정 버전 schema로 검사한다. 무조건 원시 `task` column을 요구하지 않는다.
- 수집 환경·코드 SHA·설정 snapshot·물리 팔 ID·보정 파일 hash·카메라 설정·실측 검증 결과를 manifest/로그로 남긴다. 공식 metadata를 임의로 덮어쓰지 않으며 개인정보·토큰은 넣지 않는다.
- 데이터셋을 생성·검사한 뒤 전체 폴더와 함께 필요한 manifest를 checksum 검증하여 연구실 PC로 옮기는 절차를 `docs/DATASET.md`에 작성한다. 이 맥에서 연구실 PC에 접속·설치·학습을 시작하지 않는다.

## 8. 실행 권한과 진행 방식

**이번에 자동으로 완료할 일**: 저장소 준비, 코드·문서 구현, 프로젝트 격리 환경 설치, 소프트웨어 doctor, official CLI help·dry-run, 무로봇 검증, 가짜 장치·합성 데이터 검증, 설치 재실행·복구·재현 검증, 결과 `.md` 작성.

USB 정보 열거는 읽기 전용으로 가능하다. 실제 카메라 시험은 카메라가 있고 필요한 OS 권한을 사용자가 허용한 범위에서 가능하며 시험 결과를 구분해 기록한다.

**모터에 쓰는 명령과 실제 실로봇 녹화**는 기존 AGENTS의 현장 조건이 확인된 다음 사람이 터미널에서 대화형으로 실행하도록 한다: 실제 전압·정격·극성·배선 확인, 사용자 현장 대기·팔 받침·즉시 전원 차단 가능, hardware doctor, 필요한 사전 점검. 현재 연결 여부와 현장 준비가 확인되지 않았다면 명령과 매뉴얼을 준비하고 실기는 `NOT VERIFIED`로 둔다. 자동 `yes`·Enter 주입으로 공식 설정·보정·시작 확인을 넘기지 않는다.

진행 중 실패는 원인을 조사해 수정하고 영향받는 검증을 다시 수행한다. 하드웨어 정보나 카메라가 없다는 이유로 소프트웨어 구현·설치·검증을 중단하지 않는다. 시스템 드라이버·권한·외장 저장소처럼 사용자 조치가 필요한 부분만 남기고 나머지는 완료한다.

## 9. 검증 — 실측한 결과로 완료 판정

### A. 소프트웨어와 파일 구조

- native arm64 Python 3.12, 고정 uv·torch·torchvision·LeRobot 설치, lock sync/check·pip check.
- 최소 extras로 세 단계 CLI의 import/help/dry-run 성공. 포트·카메라 없는 software doctor는 불필요한 하드웨어 FAIL을 내지 않는다.
- 모든 단계 진입점을 작업공간 및 다른 현재 디렉터리에서 검증한다. `--help`·`--dry-run`이 실제 장치를 열지 않는지 확인한다.
- 기존 `scripts/install.sh`, `lock/lerobot.env`, `lock/pyproject.toml`, `lock/uv.lock`은 시작 기준 파일 hash와 비교해 바이트 불변을 확인한다. `git diff --stat`만으로 이를 증명하지 않는다.
- Linux 분기 보존은 정적 검토와 실제 실행을 구분한다. 맥에서만 실행했으면 Linux 실행 `NOT VERIFIED`로 적는다.

### B. 무로봇·가짜 장치

- 기존 `tools/verify_offline.py`를 최대한 재사용하여 macOS PTY 동작에 맞게 보완한다.
- probe는 모든 성공·실패·중단 경로에서 모터 쓰기 0건, dry-run은 장치 개방 0건.
- 포트 wizard의 정상·다중 후보·동일 보드·빈/중복 serial·tty/cu·취소·저장 실패·원본 보존·다른 설정 보존.
- 보정 없음·불일치·잘못된 역할·중복 포트 상태에서 teleop·record가 실제 구동 전에 거부되는지 검사.
- 정상·Ctrl+C·SIGTERM·SIGHUP·시간 제한·부모 종료·감시 등록 실패·한쪽 cleanup 실패를 검사. 실제 선로 쓰기와 프로세스 상태로 판정한다.
- record의 업로드 false 고정, resume/new name, 잘못된 config, 영상 실패·finalize·정리 경로 검증.
- 실제 총수·PASS·FAIL·SKIP과 이유를 기록한다. 기존 58/58이나 계획상 신규 시험 수를 그대로 결과로 복사하지 않는다.

### C. 데이터셋 소프트웨어 검증

- 공식 LeRobotDataset API와 실제 영상 인코더·디코더로 **명확히 합성/테스트용이라고 표시한** 작은 데이터셋(예: 2개 episode·6관절·카메라 1대)을 생성·종료·재열기한다.
- 이를 `inspect.sh`로 검사하고 잘못된 데이터·schema·timestamp 조건은 탐지되는지 확인한다. 합성 데이터는 실로봇 수집 성공으로 세지 않는다.
- 합성 시험은 저장·읽기 소프트웨어 검증이다. 실제 `lerobot-record`의 하드웨어 세션 성공과 별도로 보고한다.
- 실제 카메라가 사용 가능하면 짧은 프레임 읽기·인코딩·재읽기 결과를 별도로 기록한다. 카메라·모터가 없으면 그 실기 항목만 `NOT VERIFIED`다.

### D. 설치 재사용·복구·별도 재현

- 정상 재실행 재사용, 안전하게 선택한 패키지 누락 후 복구, 설치 파일 변조 탐지 후 repair, 캐시 오염 여부를 확인한다. 사용자 원본과 다른 환경은 건드리지 않는다.
- commit 없이 현재 추적 파일과 **필요한 신규 구현 파일을 포함한 명시적 목록**으로 별도 소스 snapshot을 만든다. 미추적 거대 폴더를 `git ls-files --others`로 무조건 수집하지 않는다.
- 별도 경로·별도 venv·별도 cache·별도 managed Python 경로에서 재설치하고 doctor·필수 CLI·데이터 검사 smoke test를 수행한다. 원래 환경으로 몰래 fallback하지 않는지 확인한다.
- 배포본 버전과 실제 설치 파일 integrity를 비교한다. 설치 경로가 들어가는 console shebang·생성 bytecode·RECORD 등은 예상 차이를 명시하고, 의미 있는 패키지 소스 hash와 wheel hash를 비교한다.
- Git clone 검증을 하지 않았으면 **"소스 snapshot 재설치"**라고 보고한다. commit이 없는데 clone만으로 신규 기능이 복원됐다고 하지 않는다.
- 용량을 먼저 확인하고 본 작업공간을 보존하며 내가 생성한 임시 재현본만 정리한다. 수행 불가능한 검증은 이유를 남기고 완료로 표시하지 않는다.

## 10. 공식 레퍼런스와 문서

다음 공식 자료와 고정 버전 소스를 우선 사용한다. 가져온 코드·예제의 URL·버전/SHA·원본 경로·라이선스·재사용 범위·수정 이유를 `docs/REFERENCES.md`에 기록한다. 최신 문서와 v0.6.1이 다르면 고정 버전 실제 코드/CLI를 기준으로 한다.

- https://github.com/user/so101-ws
- https://github.com/huggingface/lerobot/tree/7e241bd630a3719a56157a497ce5d08f244784f1
- https://huggingface.co/docs/lerobot/so101
- https://huggingface.co/docs/lerobot/installation
- https://huggingface.co/docs/lerobot/v0.6.1/il_robots
- https://huggingface.co/docs/lerobot/cameras
- https://huggingface.co/docs/lerobot/lerobot-dataset-v3
- https://docs.astral.sh/uv/

`README.md`에 세 단계와 바로 실행할 명령을 연결한다. `docs/SETUP.md`, `docs/TELEOP.md`, `docs/DATASET.md`에는 **"무엇을 연결하세요 → 어떤 명령을 실행하세요 → 무엇이 나오면 다음으로 가세요 → 실패하면 무엇을 하세요"** 방식으로 작성한다. 터미널 하나를 기준으로 하며 내부 구현 설명을 운용 절차에 길게 섞지 않는다.

Git 제외 항목은 `.venv`, `.tools`, `.cache`, `.tmp`, `external`, 실제 `calibration`, `datasets`, 로컬 설정과 백업, 실행 로그, workspace 백업, `.DS_Store`다. 소스 코드·lock·설정 예시·검증 도구·문서는 남긴다. 내가 만든 파일을 일괄 삭제하지 않는다.

## 11. 완료 보고 — 반드시 `.md` 파일로 제공

아래 파일을 작업공간에 저장해줘.

- **`~/so101-ws_for-mac/docs/macos_setup_report.md`**: 이번 구현·설치·검증의 전체 결과.
- **`~/so101-ws_for-mac/docs/CURRENT_STATE.md`**: 이전 Ubuntu 기록을 보존하고 이번 맥 상태를 별도 추가.
- **`~/so101-ws_for-mac/docs/DATASET.md`**: 녹화·검사·resume·복사 매뉴얼과 실제 확인 범위.

결과 보고에는 다음을 포함한다.

1. 날짜·호스트·macOS·CPU/셸/Python 아키텍처·Rosetta 여부·작업공간·가져온 원격 SHA·Git 시작/끝 상태.
2. 실제 uv·Python·LeRobot·torch·torchvision·영상 의존성 버전, lock hash·패키지 수·공식 lock 차이와 이유.
3. 최종 폴더·파일 목록과 역할, 공통 코드 재사용 범위, 계획에서 변경한 내용과 근거.
4. 실행한 실제 명령·종료 코드·doctor FAIL/WARN·무로봇 검사 총수/PASS/FAIL/SKIP과 사유.
5. 설치 재실행·누락 복구·손상 repair·별도 snapshot 재설치 결과와 공간 사용량.
6. 합성 데이터 생성·재읽기·검사·영상 인코딩/디코딩 결과. 실카메라·실모터·실로봇 녹화와 구분.
7. USB·모터·보정·30초 추종·3분 추종·정상 종료·실제 녹화의 각 결과 또는 `NOT VERIFIED`.
8. Linux 바이트 보존 증거·정적 검토와 실제 Linux 미검증 범위.
9. 필요한 사용자 조치와 지금부터 실행할 **확정 명령**. 미확정 placeholder를 성공한 명령처럼 적지 않는다.

상태는 설치/CLI, 모터 제어 소프트웨어, 데이터셋 소프트웨어, 실제 USB, 실기, 실제 녹화, GitHub를 별도로 표시한다. 모터나 카메라가 없는 경우 소프트웨어 준비 완료와 실기 미검증을 동시에 정확히 표현한다.

최종 채팅에는 결과 보고 `.md`의 절대경로, 주요 상태와 실제 통과 수, 사용자가 다음에 실행할 짧은 명령 순서를 알려줘. **결과를 채팅 요약으로만 끝내지 말고 반드시 Markdown 보고서로 남겨줘.**

## 12. 구현 후 제공해야 할 기본 명령

아래 사용 흐름이 실제로 동작하도록 구현하고, 실제 지원 옵션에 맞춰 문서를 확정한다.

```bash
cd ~/so101-ws_for-mac

# 설치와 소프트웨어 점검 — 이번 작업에서 실행·검증
./01_setup/install.sh
./01_setup/doctor.sh

# 현장에서 USB 포트 지정 → 맞는 모터 전원 연결 → 읽기 전용 확인
./01_setup/ports.sh
./01_setup/probe.sh follower
./01_setup/probe.sh leader

# 필요한 팔만, 사람이 공식 프롬프트를 따라 실행
./01_setup/motors.sh follower
./01_setup/motors.sh leader
./01_setup/calibrate.sh follower
./01_setup/calibrate.sh leader

# 보정·현장 조건 확인 후 텔레옵
./02_teleop/run.sh --dry-run
./02_teleop/run.sh --time-s 30

# 카메라 선택·녹화 설정 확인 후 로컬 데이터 생성
./03_dataset/cameras.sh
./03_dataset/record.sh --dry-run
./03_dataset/record.sh
./03_dataset/inspect.sh datasets/<실제로_생성한_데이터셋_이름>
```

실제 motors/calibrate/teleop/record는 8절 조건을 충족한 현장에서 실행한다. 이번에는 소프트웨어를 끝까지 준비하고 검증하여, 사용자가 위 세 단계를 바로 진행할 수 있는 상태로 만들어줘.
