# 카메라 설정 보고서 — ACT 데이터 수집용 (macOS)

2026-10-11, MacBook Air M4(macOS 26.5.2), LeRobot v0.6.1(설치본), OpenCV 4.13.0.92(AVFoundation 백엔드).

- 카메라만 다뤘다. 모터 포트·보정·텔레옵·로봇 녹화는 실행하지 않았다.
- 카메라 위치·각도·초점·노출·화이트밸런스는 바꾸지 않았다.
- 패키지·lock은 변경하지 않았고 commit·push도 하지 않았다.

## 1. 장치와 매핑

| 프로젝트 이름 | 역할 | 모델(USB 장치 기술자가 보고한 값) | USB 위치 · AVFoundation uniqueID | OpenCV index(2026-10-11) |
|---|---|---|---|---|
| `front` | 외부 카메라(작업면 약 50cm 위, 팔로워 옆) | Innomaker-U20CAM-720P, VID:PID 0c45:6367, bcdDevice 1.00, USB 2.0 High-Speed | 1-1.4 · `0x11400000c456367` | **1** |
| `wrist` | 손목 카메라(그리퍼 바로 위) | 위와 같음 | 1-1.1 · `0x11100000c456367` | **0** |

- **모델**: 판매 사진의 U20CAM-720P와 같은 이름을 **장치가 USB 기술자로 보고**한다. VID 0x0c45는 Sonix(Microdia) 칩 공급사다.
- **구분 방법**: 두 카메라는 이름과 USB serial(`SN0001`)까지 같다. 그래서 **USB 위치로만 구분**된다.
- **매핑 확인 방법**: uniqueID로 연 화면과 OpenCV index로 연 화면을 비교했다(상관계수 0.997 / 0.978). 사진을 눈으로도 확인했다.
  - `front` = 작업면 전체와 팔
  - `wrist` = 그리퍼 끝
- **번호가 바뀔 수 있음**: 카메라 번호는 API마다 순서가 달랐다.

  | API | 순서 |
  |---|---|
  | OpenCV | 0=wrist, 1=front, 2=내장 카메라 |
  | Swift(`devices(for:)`) | 0=wrist, 1=내장 카메라, 2=front |
  | PyAV(FFmpeg) | 연결할 때마다 바뀌었음 |

  재연결·재부팅 후에는 **세션마다 확인 사진으로 매핑을 다시 확인**한다(5절).

## 2. 변경 전/후 설정

| 항목 | 변경 전 | 변경 후(`configs/cameras.local.yaml`) |
|---|---|---|
| 카메라 설정 파일 | 없음(견본 `cameras.example.yaml`: `front` 1대, index null, 640×480@30) | 새로 만듦. 기존 로컬 파일이 없어 백업 대상 없음 |
| `front` | 미설정. 장치 활성 형식 `420v` 1280×720(드라이버 보고) | index 1, **640×480, fps 30**, `rotation: 180`(거꾸로 장착, 공식 Cv2Rotation) |
| `wrist` | 미설정. 장치 활성 형식 `420v` 1280×720(드라이버 보고) | index 0, **640×480, fps 30**, 회전 없음 |
| `fourcc` | 없음 | **넣지 않음**(3절: macOS에서 적용 불가) |
| 색 변환 | 공식 기본 RGB | 그대로(공식 `color_mode` RGB, BGR→RGB 변환 경로) |
| 녹화 FPS | 녹화 설정 파일 없음(견본 fps 30) | `configs/recording.local.yaml` 새로 만듦: **fps 30**. name·task는 null(녹화 전에 채움) |
| MP4 저장 코덱 | 공식 기본 `libsvtav1` | 그대로 `libsvtav1`(USB 입력 형식과는 별개) |
| 텔레옵 주기 | 60 Hz(`robot.local.yaml`) | 그대로 |

## 3. 입력 형식(USB)

**드라이버(AVFoundation)가 보고하는 형식**: 두 카메라가 같다(`swift tools/camera_view_dual.swift --formats`).

| 형식 | 320×240 | 640×480 | 800×600 | 1280×720 |
|---|---|---|---|---|
| `yuvs`(YUY2 4:2:2) | 30 | **30** | 20 | 10 |
| `420v`(NV12) | 30 | **30** | 30 | 30 |

- **`dmb1`(Motion-JPEG)은 목록에 없다.**
  - `420v`가 고해상도에서도 30 fps인데 `yuvs`는 10–20 fps뿐이다. 그래서 `420v`는 카메라의 압축(MJPEG) 스트림을 macOS가 풀어서 내주는 형식으로 **추정**된다.
  - 장치 기술자의 UVC 형식 목록을 직접 읽지는 못했으므로 **추정**이다.
- **MJPEG 우선 적용: 확인 불가**
  - 공식 `fourcc: MJPG`·`YUY2`를 지정해도 OpenCV(AVFoundation)는 `set` 실패(success=False)를 반환한다. 읽기값도 `0`이다. LeRobot은 경고만 남기고 기본 형식으로 진행했다.
  - 이 경로에는 USB 입력 형식을 고르거나 읽는 방법이 없다.
  - 그래서 MJPEG 적용 성공으로 보지 않는다. 실제 640×480 연결에 쓰인 USB 형식(YUY2인지 압축인지)도 **확인 불가**다.
- **YUY2 640×480@30**: 장치가 보고하는 형식 목록에 있다. 실제로 사용 중인지는 확인 불가.
- **화면 비율**: 640×480 요청 시 카메라는 4:3 모드로 바뀐다. 1280×720보다 화각이 좁고, 늘어나거나 찌그러지지 않았다(사진 육안 확인).

## 4. 실측(공식 OpenCVCamera, 두 카메라 동시 60초)

`tools/camera_check.py` 기준이다.
- **새 프레임 세는 방법**: 공식 백그라운드 스레드의 하드웨어 읽기 지점에서 센다. 직전 프레임과 내용 해시가 같으면 중복으로 따로 센다.
- **녹화와 같은 조건**: 동시에 30 Hz 소비 루프(`async_read`)를 돌렸다.

| 구분 | `front` | `wrist` |
|---|---|---|
| 설정값 | 640×480, 30 fps | 640×480, 30 fps |
| 드라이버 보고값(OpenCV get) | 640×480, 30.00 fps, FOURCC 0 | 640×480, 30.00 fps, FOURCC 0 |
| 실제 수신 프레임(원본 → 처리 후) | 480×640×3 → 480×640×3(180° 회전·RGB) | 480×640×3 → 480×640×3(RGB) |
| **새 프레임 수신 FPS(동시)** | **30.15**(1809장/60초) | **30.15**(1809장/60초) |
| 간격 중앙값 / p95 / 최대 | 33.0 / 34.7 / 76.5 ms | 33.0 / 34.8 / 77.9 ms |
| 50 ms 초과 간격 / 100 ms 초과 멈춤 | 11 / 0 | 11 / 0 |
| 중복 프레임 / 읽기 오류 / 소비 시간초과(200 ms) | 0 / 0 / 0 | 0 / 0 / 0 |

- 같은 측정을 한 번 더 했을 때(앞선 60초): 30.13 / 30.16 fps, 최대 간격 91 / 94 ms, 그 외 오류 0.
- **50 ms 초과 간격 11회의 해석**
  - 평균은 30.15 fps를 유지했다. 그래서 대부분은 프레임이 늦게 왔다가 몰아서 도착한 **전달 지연**으로 보인다.
  - 카메라가 찍은 시각(타임스탬프)이 없어서, 실제로 빠진 프레임이 없는지는 **확인 불가**다.
- **USB 대역**: 두 카메라 모두 USB 2.0 High-Speed이고, 로봇 보드 2개와 같은 허브에 연결되어 있다. 이 조건에서 동시 30 fps를 얻었다. 로봇 통신을 함께 켠 상태는 측정하지 않았다.
- **한 대씩**(`./03_dataset/cameras.sh --test`, 5초, 프로젝트 실제 경로): `front` 30.5 fps, `wrist` 30.4 fps. 두 카메라 모두 480×640×3.
- **녹화 경로 반영**: `./03_dataset/record.sh --dry-run`(포트·카메라를 열지 않음)에서 공식 RecordConfig 파싱이 OK였다.
  - 두 카메라: index 1/0, 640×480, fps 30
  - `front`의 `rotation`: `ROTATE_180`
  - fourcc: None, 데이터셋 fps 30, 코덱 libsvtav1
- **확인용 프레임**: `logs/camera-check-20261011_182424/`
  - `front_raw.png`(회전 전 원본), `front_processed.png`(회전·RGB 후)
  - `wrist_raw.png`, `wrist_processed.png`
- 측정 기록: `logs/camera-check-20261011_182424.json`

## 5. 이후 카메라 확인 명령

```bash
cd ~/so101-ws_for-mac
swift tools/camera_view_dual.swift --list        # 카메라·uniqueID(USB 위치) 목록, 카메라를 열지 않음
swift tools/camera_view_dual.swift --formats     # 드라이버 보고 형식
swift tools/camera_view_dual.swift               # 실시간 미리보기(위 front 180°, 아래 wrist)
swift tools/camera_view_dual.swift --mirror .tmp/live  # 카메라를 열지 않고, 실행 중인 프로세스가 내보낸 영상만 표시
./tools/rollout_with_view.sh <lerobot-rollout 인자>    # rollout 실행 + 정책이 받는 영상 창(위 front / 아래 wrist)
./03_dataset/cameras.sh --test front             # 프로젝트 경로로 한 대씩 시험 + 확인 사진
./03_dataset/cameras.sh --test wrist
.venv/bin/python tools/camera_check.py           # 두 카메라 동시 60초 실측(--seconds로 변경)
```

- 녹화 전에는 `cameras.sh --test` 사진으로 index 매핑을 확인한다.
- 바뀌었으면 `configs/cameras.local.yaml`의 `index_or_path`만 고친다.
- 미리보기 창과 녹화·rollout을 동시에 켜지 않는다. 실측(2026-10-14): 공식 OpenCVCamera가 640×480으로 읽는 중에 창을 열면 장치가 1280×720으로 바뀌어 프레임이 640×360으로 들어오고 읽기 스레드가 멈췄다(창을 닫아도 복구 안 됨). 창의 preset을 640×480으로 맞춰도 같았다.
  - 실행 중에 보려면 `tools/rollout_with_view.sh`를 쓴다. 공식 프로세스 안에서 이미 읽은 프레임을 `scripts/so101_camera_mirror.py`가 `.tmp/live/*.jpg`로 약 10Hz 내보내고, 창(`--mirror`)은 파일만 읽는다.

## 6. 변경한 파일

| 파일 | 내용 | Git |
|---|---|---|
| `configs/cameras.local.yaml` | 새로 만듦(`front`·`wrist`, 640×480@30, `front` 회전 180) | 제외(로컬) |
| `configs/recording.local.yaml` | 새로 만듦(fps 30, 견본 기반) | 제외(로컬) |
| `tools/camera_check.py` | 새 파일: 두 카메라 동시 실측 | 미커밋 |
| `tools/camera_view_dual.swift` | `--formats`, `--snapshot`(uniqueID로 한 장 저장) 추가 | 미커밋 |
| `docs/camera_setup_report.md` | 이 보고서 | 미커밋 |

프로젝트 래퍼 코드(`scripts/`)와 LeRobot 설치본은 수정하지 않았다(수정이 필요한 문제가 없었음).

## 7. 확인하지 못한 항목

- 실제 USB 입력 형식(MJPEG/YUY2)과 MJPEG 강제 적용 가능 여부(macOS AVFoundation 경로에서 선택·조회 불가)
- 카메라 기준 타임스탬프로 확인하는 프레임 손실 여부
- 로봇 통신·녹화(영상 인코딩)를 함께 켠 상태에서의 카메라 FPS
- 재부팅·재연결 후 OpenCV index 유지 여부
