#!/usr/bin/env python
"""카메라 확인 도구. config/so101.env 의 설정(by-path 경로, 640x480 30fps MJPG, front 180도 회전)을
lerobot OpenCVCamera 로 그대로 열어서, 녹화·추론 때와 같은 화면을 본다.

  python scripts/cameras.py list               # 연결된 카메라(by-path)와 front/wrist 대응
  python scripts/cameras.py snap               # front, wrist 한 장씩 → outputs/cameras/*.jpg
  python scripts/cameras.py snap --all         # 연결된 모든 카메라 한 장씩(어느 경로가 front/wrist 인지 찾을 때)
  python scripts/cameras.py live               # 실시간 창(front | wrist). s = 저장, o = 겹치기 켜고 끄기, q = 종료
  python scripts/cameras.py live --overlay <HF_USER>/<학습 데이터셋>
        # 학습 데이터셋의 front 첫 프레임을 반투명으로 겹쳐서 카메라 위치를 학습 때와 맞춘다(이미지 파일 경로도 가능)

카메라는 한 프로그램만 열 수 있다. teleop/record/rollout 실행 전에 이 창을 닫는다.

macOS: /dev/v4l 이 없어 config 의 카메라 값은 OpenCV(AVFoundation) 번호(0, 1, ...)다. list 는 번호를 하나씩 열어 보고,
       snap --all 은 열린 번호마다 한 장씩 찍는다(어느 번호가 front/wrist 인지 사진으로 확인). fourcc 는 지정하지 않는다.
"""

import argparse
import os
import platform
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from lerobot.cameras.configs import Cv2Rotation
from lerobot.cameras.opencv import OpenCVCamera, OpenCVCameraConfig

IS_MAC = platform.system() == "Darwin"
WS = Path(os.environ.get("SO101_WS", Path(__file__).resolve().parents[1]))
OUT = Path(os.environ.get("SO101_OUTPUT_DIR", WS / "outputs")) / "cameras"


def env(name: str) -> str:
    v = os.environ.get(name)
    if v is None:
        sys.exit(f"[오류] 환경 변수 {name} 가 없다. 먼저: source {WS}/scripts/activate.sh")
    return v


def configured() -> dict[str, dict]:
    return {
        "front": {"path": env("SO101_CAM_FRONT"), "rotation": int(env("SO101_CAM_FRONT_ROTATION"))},
        "wrist": {"path": env("SO101_CAM_WRIST"), "rotation": int(env("SO101_CAM_WRIST_ROTATION"))},
    }


def cam_exists(path: str) -> bool:
    """숫자(카메라 번호, macOS)는 파일이 없으므로 있다고 본다. 경로는 실제로 있는지 확인."""
    return path.isdigit() or os.path.exists(path)


def make_cam(path: str, rotation: int = 0) -> OpenCVCamera:
    cfg = OpenCVCameraConfig(
        index_or_path=int(path) if path.isdigit() else Path(path),
        width=int(env("SO101_CAM_WIDTH")),
        height=int(env("SO101_CAM_HEIGHT")),
        fps=int(env("SO101_CAM_FPS")),
        fourcc=os.environ.get("SO101_CAM_FOURCC") or None,   # 비우면 지정 안 함(macOS)
        rotation=Cv2Rotation(rotation),
    )
    return OpenCVCamera(cfg)


def list_mac_indices(max_index: int = 8) -> list[str]:
    """macOS: OpenCV(AVFoundation) 카메라 번호 중 실제로 열리는 것."""
    import cv2

    found = []
    for i in range(max_index):  # AVFoundation 번호는 0 부터 연속 → 처음 실패한 번호에서 멈춘다(경고 줄이기)
        cap = cv2.VideoCapture(i, cv2.CAP_AVFOUNDATION)
        try:
            ok = cap.isOpened() and cap.read()[0]
        finally:
            cap.release()
        if not ok:
            break
        found.append(str(i))
    return found


def video_name(dev: Path) -> str:
    try:
        return (Path("/sys/class/video4linux") / dev.resolve().name / "name").read_text().strip()
    except OSError:
        return "?"


def list_by_path() -> list[Path]:
    d = Path("/dev/v4l/by-path")
    if not d.is_dir():
        return []
    # usbv2 는 같은 장치의 중복 링크라 뺀다. video-index0 만 실제 영상 스트림.
    return sorted(p for p in d.iterdir() if p.name.endswith("video-index0") and "-usbv2-" not in p.name)


def cmd_list_mac() -> None:
    import subprocess

    cfg = configured()
    names = subprocess.run(["system_profiler", "SPCameraDataType"], capture_output=True, text=True).stdout
    names = [ln.strip().rstrip(":") for ln in names.splitlines() if ln.startswith("    ") and not ln.startswith("     ") and ln.strip().endswith(":")]
    print("연결된 카메라 이름(system_profiler, 번호 순서와 같지 않을 수 있음):")
    for n in names or ["(없음)"]:
        print(f"  {n}")
    rev = {v["path"]: k for k, v in cfg.items()}
    idx = list_mac_indices()
    print("\n열리는 OpenCV 카메라 번호:")
    for i in idx or []:
        print(f"  {i}  {('= ' + rev[i]) if i in rev else ''}")
    if not idx:
        print("  (없음 — 터미널에 카메라 권한이 있는지: 시스템 설정 → 개인정보 보호 및 보안 → 카메라)")
    print("\nconfig/so101.env 설정:")
    for k, v in cfg.items():
        ok = "OK" if v["path"] in idx else "열리지 않음(연결 확인 또는 번호 수정)"
        print(f"  {k:5}: 번호 {v['path']} rot={v['rotation']}  [{ok}]")
    print("\n번호는 재연결·재부팅 뒤 바뀔 수 있다. 어느 번호가 front/wrist 인지: python scripts/cameras.py snap --all")


def cmd_list(_args) -> None:
    if IS_MAC:
        cmd_list_mac()
        return
    cfg = configured()
    rev = {}
    for k, v in cfg.items():
        rev[os.path.realpath(v["path"]) if os.path.exists(v["path"]) else v["path"]] = k
    paths = list_by_path()
    print("연결된 카메라 (/dev/v4l/by-path, video-index0):")
    if not paths:
        print("  (없음)")
    for p in paths:
        role = rev.get(os.path.realpath(p), "")
        print(f"  {p}  -> {p.resolve()}  [{video_name(p)}] {('= ' + role) if role else ''}")
    print("\nconfig/so101.env 설정:")
    for k, v in cfg.items():
        ok = "OK" if os.path.exists(v["path"]) else "없음(연결 확인 또는 경로 수정)"
        print(f"  {k:5}: {v['path']} rot={v['rotation']}  [{ok}]")


def grab(cam: OpenCVCamera, n_warm: int = 5) -> np.ndarray:
    frame = None
    for _ in range(n_warm):
        frame = cam.read()
    return frame


def cmd_snap(args) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.all and IS_MAC:
        targets = {f"index{i}": {"path": i, "rotation": 0} for i in list_mac_indices()}
    elif args.all:
        targets = {p.name.replace(":", "_"): {"path": str(p), "rotation": 0} for p in list_by_path()}
    else:
        targets = configured()
    if not targets:
        sys.exit("[오류] 카메라가 없다")
    for name, t in targets.items():
        try:
            cam = make_cam(t["path"], t["rotation"])
            cam.connect()
            img = grab(cam)
            cam.disconnect()
        except Exception as e:  # noqa: BLE001
            print(f"[실패] {name}: {t['path']}: {e}")
            continue
        out = OUT / f"{name}_{ts}.jpg"
        Image.fromarray(img).save(out, quality=92)
        print(f"[저장] {name}: {img.shape[1]}x{img.shape[0]} → {out}")


def load_overlay(src: str, size: tuple[int, int]) -> Image.Image | None:
    if not src:
        return None
    p = Path(src).expanduser()
    if p.is_file():
        img = Image.open(p).convert("RGB")
    else:
        from lerobot.datasets import LeRobotDataset

        ds = LeRobotDataset(src, episodes=[0])
        key = next(k for k in ds.meta.camera_keys if k.endswith("front"))
        t = ds[0][key]  # CHW float [0,1], 녹화 때 회전이 이미 적용된 화면
        img = Image.fromarray((t.permute(1, 2, 0).numpy() * 255).astype(np.uint8))
        print(f"[overlay] {src} episode 0 frame 0 ({key})")
    return img.resize(size)


def cmd_live(args) -> None:
    import tkinter as tk

    from PIL import ImageTk

    cfg = configured()
    cams = {}
    for name, t in cfg.items():
        try:
            c = make_cam(t["path"], t["rotation"])
            c.connect()
            cams[name] = c
            print(f"[열림] {name}: {t['path']}")
        except Exception as e:  # noqa: BLE001
            print(f"[실패] {name}: {e}")
    if not cams:
        sys.exit("[오류] 열린 카메라가 없다 (python scripts/cameras.py list)")

    w, h = int(env("SO101_CAM_WIDTH")), int(env("SO101_CAM_HEIGHT"))
    overlay = load_overlay(args.overlay, (w, h)) if args.overlay else None
    state = {"overlay": overlay is not None, "frames": {}, "t": time.time(), "n": 0, "fps": 0.0}

    root = tk.Tk()
    root.title("SO-ARM cameras  (s=저장  o=겹치기  q=종료)")
    label = tk.Label(root)
    label.pack()
    status = tk.Label(root, anchor="w", font=("monospace", 10))
    status.pack(fill="x")

    def save(_e=None):
        OUT.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        for k, f in state["frames"].items():
            out = OUT / f"{k}_{ts}.jpg"
            Image.fromarray(f).save(out, quality=92)
            print(f"[저장] {out}")

    def toggle(_e=None):
        if overlay is not None:
            state["overlay"] = not state["overlay"]

    def quit_(_e=None):
        root.quit()

    root.bind("s", save)
    root.bind("o", toggle)
    root.bind("q", quit_)
    root.bind("<Escape>", quit_)
    root.protocol("WM_DELETE_WINDOW", quit_)

    def tick():
        tiles = []
        for name, cam in cams.items():
            try:
                f = cam.async_read(timeout_ms=500)
                state["frames"][name] = f
            except Exception:  # noqa: BLE001
                f = state["frames"].get(name, np.zeros((h, w, 3), np.uint8))
            im = Image.fromarray(f)
            if name == "front" and state["overlay"] and overlay is not None:
                im = Image.blend(im, overlay, 0.5)
            tiles.append((name, im))
        canvas = Image.new("RGB", (w * len(tiles), h))
        for i, (_, im) in enumerate(tiles):
            canvas.paste(im, (i * w, 0))
        photo = ImageTk.PhotoImage(canvas)
        label.configure(image=photo)
        label.image = photo
        state["n"] += 1
        dt = time.time() - state["t"]
        if dt >= 1.0:
            state["fps"], state["n"], state["t"] = state["n"] / dt, 0, time.time()
        names = " | ".join(n for n, _ in tiles)
        ov = "  overlay=ON" if state["overlay"] else ""
        status.configure(text=f"{names}   display {state['fps']:.1f} fps{ov}")
        root.after(15, tick)

    root.after(0, tick)
    try:
        root.mainloop()
    finally:
        for c in cams.values():
            try:
                c.disconnect()
            except Exception:  # noqa: BLE001
                pass


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    s = sub.add_parser("snap")
    s.add_argument("--all", action="store_true", help="연결된 모든 카메라(회전 없이)")
    l_ = sub.add_parser("live")
    l_.add_argument("--overlay", default="", help="겹칠 이미지 파일 또는 데이터셋 repo_id")
    args = ap.parse_args()
    {"list": cmd_list, "snap": cmd_snap, "live": cmd_live}[args.cmd](args)


if __name__ == "__main__":
    main()
