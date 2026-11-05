#!/usr/bin/env python3
"""카메라 영상 내보내기(미러) — 공식 lerobot 프로세스가 이미 읽은 프레임을 JPEG 파일로 내보낸다.

scripts/so101_launch.py가 환경변수 SO101_CAMERA_MIRROR=<폴더>일 때, 공식 console script를 실행하기 직전에 install()을 호출한다.
카메라를 두 번 열지 않는다. macOS에서 다른 프로그램이 같은 카메라를 열면 장치 형식이 바뀌어 공식 OpenCVCamera의 프레임 크기가
달라지고 읽기가 멈추기 때문이다(2026-10-14 실측, docs/camera_setup_report.md). 공식 LeRobot 파일은 수정하지 않는다.
  - lerobot.cameras(.utils).make_cameras_from_configs: 만든 카메라에 설정 키 이름(front·wrist 등)을 붙인다.
  - OpenCVCamera.connect/disconnect: 연결 뒤 내보내기 스레드를 시작하고, 연결을 끊기 전에 멈춘다.
내보내기 스레드는 공식 읽기 스레드가 저장한 latest_frame(회전까지 적용된 RGB, 정책이 받는 것과 같은 영상)을 참조만 하고,
SO101_CAMERA_MIRROR_HZ(기본 10)Hz로 <폴더>/<이름>.jpg에 원자적으로(임시 파일 → os.replace) 쓴다.
내보내기에서 어떤 오류가 나도 공식 동작에는 영향을 주지 않는다(경고 한 줄 후 그 카메라만 내보내기 중단).
보기: swift tools/camera_view_dual.swift --mirror <폴더>  (tools/rollout_with_view.sh가 함께 띄운다)
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

_state = {"installed": False}


def _warn(msg: str) -> None:
    try:
        print(f"[so101-mirror] {msg}", flush=True)
    except OSError:
        pass


def mirror_loop(cam, name: str, out_dir: Path, hz: float, stop: threading.Event, quality: int = 80) -> int:
    """cam.latest_frame(RGB)을 hz 이하로 <out_dir>/<name>.jpg에 쓴다. 쓴 장 수를 반환한다."""
    import cv2

    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"{name}.jpg"
    tmp = out_dir / f".{name}.jpg.tmp"
    period = 1.0 / max(hz, 0.1)
    last_ts = None
    n = 0
    while not stop.wait(period):
        try:
            with cam.frame_lock:  # 공식 읽기 스레드는 배열을 새로 만들어 바꿔 끼우므로 참조만 가져온다
                frame, ts = cam.latest_frame, cam.latest_timestamp
            if frame is None or ts == last_ts:
                continue
            last_ts = ts
            ok, buf = cv2.imencode(".jpg", cv2.cvtColor(frame, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, quality])
            if not ok:
                continue
            tmp.write_bytes(buf.tobytes())
            os.replace(tmp, dst)
            n += 1
        except Exception as e:  # noqa: BLE001 — 내보내기 실패가 공식 동작을 막지 않게 한다
            _warn(f"{name} 내보내기 중단: {type(e).__name__}: {e}")
            break
    return n


def install(out_dir: str | os.PathLike | None = None, hz: float | None = None) -> None:
    if _state["installed"]:
        return
    out = Path(out_dir or os.environ["SO101_CAMERA_MIRROR"])
    rate = float(hz if hz is not None else os.environ.get("SO101_CAMERA_MIRROR_HZ", "10"))
    import lerobot.cameras as C
    import lerobot.cameras.utils as CU
    from lerobot.cameras.opencv.camera_opencv import OpenCVCamera

    orig_make = CU.make_cameras_from_configs

    def make_cameras_from_configs(camera_configs):
        cams = orig_make(camera_configs)
        for key, cam in cams.items():
            try:
                cam._so101_mirror_name = str(key)
            except Exception:  # noqa: BLE001
                pass
        return cams

    # 로봇 모듈은 'from lerobot.cameras import make_cameras_from_configs'로 가져오므로, 그 모듈들이 import되기 전에 바꾼다.
    CU.make_cameras_from_configs = make_cameras_from_configs
    C.make_cameras_from_configs = make_cameras_from_configs

    orig_connect, orig_disconnect = OpenCVCamera.connect, OpenCVCamera.disconnect

    def connect(self, *args, **kw):
        result = orig_connect(self, *args, **kw)
        try:
            name = getattr(self, "_so101_mirror_name", None) or f"cam{self.index_or_path}"
            stop = threading.Event()
            th = threading.Thread(target=mirror_loop, args=(self, name, out, rate, stop), name=f"so101-mirror-{name}", daemon=True)
            self._so101_mirror = (stop, th)
            th.start()
        except Exception as e:  # noqa: BLE001
            _warn(f"내보내기 시작 실패: {type(e).__name__}: {e}")
        return result

    def disconnect(self, *args, **kw):
        m = getattr(self, "_so101_mirror", None)
        if m:
            m[0].set()
            m[1].join(timeout=1.0)
            self._so101_mirror = None
        return orig_disconnect(self, *args, **kw)

    OpenCVCamera.connect, OpenCVCamera.disconnect = connect, disconnect
    _state["installed"] = True
    _warn(f"카메라 영상 내보내기: {out} ({rate:g} Hz, 카메라를 추가로 열지 않음)")
