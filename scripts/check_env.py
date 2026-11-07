#!/usr/bin/env python
"""소프트웨어 환경 점검: LeRobot·PyTorch·CUDA(macOS 는 MPS)·영상 코덱·모터/카메라 라이브러리.

  python scripts/check_env.py            # GPU 연산까지 확인
  python scripts/check_env.py --no-gpu   # GPU 없이
"""

import argparse
import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

results = []


def check(name, fn):
    try:
        msg = fn()
        results.append(("PASS", name, msg or ""))
    except Exception as e:  # noqa: BLE001
        results.append(("FAIL", name, f"{type(e).__name__}: {e}"[:300]))


def ver(mod, dist=None):
    def _v():
        m = importlib.import_module(mod)
        v = getattr(m, "__version__", None)
        if v is None:
            from importlib.metadata import version

            v = version(dist or mod)
        return str(v)

    return _v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-gpu", action="store_true")
    args = ap.parse_args()

    check("python", lambda: sys.version.split()[0] + f" ({sys.executable})")
    check("conda env", lambda: os.environ.get("CONDA_DEFAULT_ENV") or (_ for _ in ()).throw(RuntimeError("conda 환경 아님")))

    def lerobot_src():
        import lerobot

        p = Path(lerobot.__file__).resolve()
        ws = Path(os.environ.get("SO101_WS", Path(__file__).resolve().parents[1]))
        if ws / "lerobot" not in p.parents:
            raise RuntimeError(f"작업 공간의 lerobot 이 아님: {p}")
        commit = subprocess.run(["git", "-C", str(ws / "lerobot"), "rev-parse", "--short", "HEAD"],
                                capture_output=True, text=True).stdout.strip()
        return f"{lerobot.__version__} editable @ {commit} ({p.parent})"

    check("lerobot", lerobot_src)
    for m in ["torch", "torchvision", "torchcodec", "av", "cv2", "numpy", "datasets", "huggingface_hub",
              "rustypot", "serial", "rerun", "accelerate", "transformers", "diffusers"]:
        check(m, ver(m))
    check("tkinter (cameras.py live)", lambda: str(importlib.import_module("tkinter").TkVersion))
    check("ffmpeg (conda)", lambda: subprocess.run([shutil.which("ffmpeg"), "-version"], capture_output=True,
                                                   text=True).stdout.split("\n")[0])

    def env_vars():
        need = ["SO101_WS", "HF_LEROBOT_HOME", "HF_LEROBOT_CALIBRATION"]
        miss = [k for k in need if not os.environ.get(k)]
        if miss:
            raise RuntimeError(f"{miss} 없음 → source scripts/activate.sh")
        from lerobot.utils.constants import HF_LEROBOT_CALIBRATION, HF_LEROBOT_HOME

        local = [k for k in ("SO101_FOLLOWER_PORT", "SO101_LEADER_PORT", "SO101_CAM_FRONT", "SO101_CAM_WRIST") if not os.environ.get(k)]
        note = f" | 이 PC 장치 값 미설정 {local} → bash scripts/setup_local.sh" if local else ""
        return f"HF_LEROBOT_HOME={HF_LEROBOT_HOME}, CALIBRATION={HF_LEROBOT_CALIBRATION}{note}"

    check("workspace env", env_vars)

    def registry():
        from lerobot.cameras.opencv import OpenCVCameraConfig  # noqa: F401
        from lerobot.robots import RobotConfig
        from lerobot.robots.so_follower import SOFollowerRobotConfig  # noqa: F401
        from lerobot.teleoperators import TeleoperatorConfig
        from lerobot.teleoperators.so_leader import SOLeaderTeleopConfig  # noqa: F401

        r = RobotConfig.get_known_choices()
        t = TeleoperatorConfig.get_known_choices()
        assert "so101_follower" in r and "so101_leader" in t
        return "so101_follower, so101_leader, opencv camera"

    check("lerobot hardware", registry)

    def video_encode():
        import av

        codecs = av.codecs_available
        assert "libsvtav1" in codecs, "libsvtav1 인코더 없음"
        return f"PyAV libsvtav1 OK, h264_nvenc={'h264_nvenc' in codecs}"

    check("video encode", video_encode)

    if not args.no_gpu:
        def gpu():
            import torch
            import torchvision

            if not torch.cuda.is_available() and torch.backends.mps.is_available():  # macOS Apple Silicon
                a = torch.randn(1024, 1024, device="mps")
                assert torch.isfinite(a @ a).all()
                m = torchvision.models.resnet18().to("mps").eval()
                with torch.no_grad():
                    m(torch.randn(1, 3, 224, 224, device="mps"))
                torch.mps.synchronize()
                import platform
                return f"Apple GPU (MPS), macOS {platform.mac_ver()[0]}, matmul+resnet18 OK"
            assert torch.cuda.is_available(), "torch.cuda.is_available() == False"
            name = torch.cuda.get_device_name(0)
            cap = torch.cuda.get_device_capability(0)
            a = torch.randn(1024, 1024, device="cuda")
            assert torch.isfinite(a @ a).all()
            m = torchvision.models.resnet18().cuda().eval()
            with torch.no_grad():
                m(torch.randn(1, 3, 224, 224, device="cuda"))
            free, total = torch.cuda.mem_get_info()
            return f"{name} sm_{cap[0]}{cap[1]}, CUDA {torch.version.cuda}, {total / 2**30:.1f} GB, matmul+resnet18 OK"

        check("GPU", gpu)

    w = max(len(n) for _, n, _ in results)
    for s, n, m in results:
        color = "\033[32m" if s == "PASS" else "\033[31m"
        print(f"  {color}{s}\033[0m {n:<{w}}  {m}")
    fails = sum(1 for s, _, _ in results if s == "FAIL")
    print(f"\nPASS {len(results) - fails}, FAIL {fails}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
