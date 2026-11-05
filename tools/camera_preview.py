#!/usr/bin/env python3
"""카메라 실시간 미리보기(macOS, 녹화·저장 없음).

  .venv/bin/python tools/camera_preview.py                       # Innomaker 카메라, 1280x720 30fps
  .venv/bin/python tools/camera_preview.py --name "MacBook" --size 640x480
  .venv/bin/python tools/camera_preview.py --list                # AVFoundation 카메라 이름·번호 목록

- 카메라는 이름(부분 일치)으로 고른다. AVFoundation 번호를 추측하지 않는다.
- PyAV(내장 FFmpeg avfoundation 입력)로 받아 Tk 창에 표시한다. 이 프로세스는 cv2를 불러오지 않는다
  (cv2·av가 같은 libavdevice를 각각 포함해 생기는 objc 중복 클래스 충돌을 피하기 위해).
- 창 제목에 실제 해상도와 측정 FPS를 표시한다. 창을 닫거나 q/Esc를 누르면 종료한다.
- 처음 카메라를 열 때 macOS가 이 터미널 앱의 카메라 접근 허용을 묻는다(사용자가 허용).
- 참고: 여기 번호는 AVFoundation 순서다. lerobot 녹화 설정(cameras.local.yaml)의 OpenCV index는
  ./03_dataset/cameras.sh 결과(확인용 사진)로 정한다.
"""
from __future__ import annotations

import argparse
import re
import sys
import threading
import time


def list_devices() -> list[tuple[int, str]]:
    import av
    import av.logging

    av.logging.set_level(av.logging.INFO)
    with av.logging.Capture() as logs:
        try:
            av.open("", format="avfoundation", options={"list_devices": "true"})
        except Exception:  # noqa: BLE001 — 목록 출력 후 항상 오류로 끝난다(ffmpeg 동작)
            pass
    av.logging.set_level(av.logging.ERROR)
    out, video = [], False
    for _, _, msg in logs:
        m = msg.strip()
        if m.startswith("AVFoundation video devices"):
            video = True
        elif m.startswith("AVFoundation audio devices"):
            video = False
        elif video:
            g = re.match(r"\[(\d+)\]\s+(.*)", m)
            if g:
                out.append((int(g.group(1)), g.group(2).replace("\xa0", " ").strip()))
    return out


def open_camera(index: int, size: str, fps: str):
    import av
    import av.logging

    tried = []
    for sz in dict.fromkeys([size, "1280x720", "640x480"]):
        with av.logging.Capture() as logs:
            try:
                c = av.open(f"{index}:none", format="avfoundation",
                            options={"framerate": fps, "video_size": sz})
                return c, sz
            except Exception as e:  # noqa: BLE001
                tried.append(f"{sz}@{fps}: {type(e).__name__}")
        modes = [m.strip() for _, _, m in logs if "@" in m and "fps" in m]
        if modes:
            print("카메라가 지원하는 모드:", "; ".join(modes[:12]))
    sys.exit("카메라를 열지 못했습니다: " + " / ".join(tried) +
             "\n  - macOS 카메라 권한(시스템 설정 > 개인정보 보호 및 보안 > 카메라)에서 이 터미널 앱을 허용했는지 확인하세요."
             "\n  - 다른 프로그램(녹화·cameras.sh 등)이 카메라를 쓰고 있지 않은지 확인하세요.")


def main() -> int:
    ap = argparse.ArgumentParser(description="카메라 실시간 미리보기(녹화 없음)")
    ap.add_argument("--name", default="Innomaker", help="카메라 이름 일부(기본 Innomaker)")
    ap.add_argument("--size", default="1280x720")
    ap.add_argument("--fps", default="30")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)  # 로그 파일로 보낼 때도 즉시 기록

    devs = list_devices()
    if a.list or not devs:
        for i, n in devs:
            print(f"[{i}] {n}")
        return 0 if devs else 1
    match = [(i, n) for i, n in devs if a.name.lower() in n.lower()]
    if len(match) != 1:
        print(f"'{a.name}'와 일치하는 카메라가 {len(match)}개입니다. --list로 이름을 확인하세요:")
        for i, n in devs:
            print(f"  [{i}] {n}")
        return 1
    idx, name = match[0]
    container, size = open_camera(idx, a.size, a.fps)
    stream = container.streams.video[0]
    print(f"열림: [{idx}] {name}  {stream.codec_context.width}x{stream.codec_context.height} 요청 {size}@{a.fps}fps")

    import tkinter as tk

    from PIL import ImageTk

    latest = {"img": None, "n": 0, "t0": time.perf_counter(), "fps": 0.0, "err": None}
    stop = threading.Event()

    def reader() -> None:
        # avfoundation 입력은 다음 프레임이 아직 없으면 EAGAIN(BlockingIOError)을 낸다 → 잠깐 쉬고 다시 읽는다.
        while not stop.is_set():
            try:
                for packet in container.demux(stream):
                    for frame in packet.decode():
                        latest["img"] = frame.to_image()
                        latest["n"] += 1
                        el = time.perf_counter() - latest["t0"]
                        if el >= 1.0:
                            latest["fps"] = latest["n"] / el
                            latest["n"], latest["t0"] = 0, time.perf_counter()
                    if stop.is_set():
                        return
            except BlockingIOError:
                time.sleep(0.005)
            except Exception as e:  # noqa: BLE001
                latest["err"] = f"{type(e).__name__}: {e}"
                return

    th = threading.Thread(target=reader, daemon=True)
    th.start()

    root = tk.Tk()
    root.title(f"{name} — 연결 중")
    label = tk.Label(root)
    label.pack()
    holder = {}

    def close(*_):
        stop.set()
        root.destroy()

    def tick():
        if latest["err"]:
            print("카메라 읽기 오류:", latest["err"])
            close()
            return
        img = latest["img"]
        if img is not None:
            holder["photo"] = ImageTk.PhotoImage(img)
            label.configure(image=holder["photo"])
            root.title(f"{name} — {img.width}x{img.height}, 측정 {latest['fps']:.1f} fps  (q/Esc: 종료)")
        root.after(15, tick)

    root.protocol("WM_DELETE_WINDOW", close)
    root.bind("<Escape>", close)
    root.bind("q", close)
    root.lift()
    root.attributes("-topmost", True)
    root.after(500, lambda: root.attributes("-topmost", False))
    root.after(15, tick)
    root.mainloop()
    stop.set()
    th.join(timeout=2)
    container.close()
    print("미리보기 종료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
