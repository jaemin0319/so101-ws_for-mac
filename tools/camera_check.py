#!/usr/bin/env python3
"""녹화용 카메라 동시 점검(로봇·모터 없음, 녹화하지 않음).

  .venv/bin/python tools/camera_check.py                 # configs/cameras.local.yaml의 모든 카메라, 60초 동시 캡처
  .venv/bin/python tools/camera_check.py --seconds 10

- 프로젝트 설정 로더(scripts/so101_dataset.load_cameras)와 공식 lerobot OpenCVCamera(connect·백그라운드 읽기·
  RGB 변환·회전)를 그대로 쓴다. 녹화(lerobot-record)와 같은 카메라 경로다.
- 새 프레임 수는 공식 백그라운드 스레드의 하드웨어 읽기(_read_from_hardware) 지점에서 센다. 직전 프레임과 내용
  해시가 같으면 '중복'으로 따로 센다. 최신 프레임을 반복해서 읽은 횟수(read_latest)는 새 프레임으로 세지 않는다.
- 동시에 30 Hz 소비 루프(녹화 루프처럼 카메라마다 async_read)를 돌려 시간 초과 수를 센다.
- 결과: logs/camera-check-<시각>.json, 카메라별 원본(회전 전)·처리 후(회전·RGB 후) 프레임 PNG를 logs/camera-check-<시각>/에 저장.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import threading
import time
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WS / "scripts"))


class WarnCounter(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.msgs: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.msgs.append(record.getMessage()[:200])


def pct(v: list[float], q: float) -> float | None:
    if not v:
        return None
    s = sorted(v)
    return s[min(len(s) - 1, int(len(s) * q))]


def main() -> int:
    ap = argparse.ArgumentParser(description="녹화용 카메라 동시 점검(녹화 없음)")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--cameras", type=Path, default=WS / "configs" / "cameras.local.yaml")
    a = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)

    import cv2

    import so101_dataset as D
    from lerobot.cameras.opencv import OpenCVCamera, OpenCVCameraConfig

    cams_cfg, errs = D.load_cameras(a.cameras)
    if errs or not cams_cfg:
        print("[FAIL] 카메라 설정:", errs or "카메라 없음")
        return 1
    wc = WarnCounter()
    logging.getLogger().addHandler(wc)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = WS / "logs" / f"camera-check-{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    cams, stats = {}, {}
    for name, c in cams_cfg.items():
        cfg = OpenCVCameraConfig(**{k: v for k, v in c.items() if k != "type"})
        cam = OpenCVCamera(cfg)
        st = {"t": [], "dup": 0, "err": 0, "last_hash": None, "raw": None, "lock": threading.Lock()}
        orig = cam._read_from_hardware

        def wrapped(orig=orig, st=st):
            try:
                f = orig()
            except Exception:
                st["err"] += 1
                raise
            h = hashlib.blake2b(f[::4, ::4].tobytes(), digest_size=8).digest()
            now = time.perf_counter()
            with st["lock"]:
                if h == st["last_hash"]:
                    st["dup"] += 1
                else:
                    st["t"].append(now)
                    st["last_hash"] = h
                st["raw"] = f
            return f

        cam._read_from_hardware = wrapped  # 계측용(공식 읽기 함수를 그대로 호출)
        cams[name], stats[name] = cam, st

    res: dict = {"ts": ts, "seconds": a.seconds, "config": cams_cfg, "cameras": {}}
    try:
        for name, cam in cams.items():
            t0 = time.perf_counter()
            cam.connect()
            print(f"[연결] {name}: index {cams_cfg[name]['index_or_path']} ({time.perf_counter() - t0:.1f}s), "
                  f"백엔드 {cam.videocapture.getBackendName()}, "
                  f"드라이버 보고 {cam.videocapture.get(cv2.CAP_PROP_FRAME_WIDTH):.0f}x{cam.videocapture.get(cv2.CAP_PROP_FRAME_HEIGHT):.0f} "
                  f"@{cam.videocapture.get(cv2.CAP_PROP_FPS):.2f}, FOURCC 읽기값 {int(cam.videocapture.get(cv2.CAP_PROP_FOURCC))}")
        # 워밍업 이후부터 측정
        for st in stats.values():
            with st["lock"]:
                st["t"].clear()
                st["dup"] = 0
                st["err"] = 0
        timeouts = {n: 0 for n in cams}
        shapes = {n: set() for n in cams}
        last_proc = {}
        t_start = time.perf_counter()
        next_t = t_start
        print(f"[측정] {a.seconds:g}초 동시 캡처 + 30 Hz 소비 루프...")
        while time.perf_counter() - t_start < a.seconds:
            for n, cam in cams.items():
                try:
                    f = cam.async_read(timeout_ms=200)
                    shapes[n].add(tuple(f.shape))
                    last_proc[n] = f
                except TimeoutError:
                    timeouts[n] += 1
            next_t += 1 / 30
            time.sleep(max(0.0, next_t - time.perf_counter()))
        t_end = time.perf_counter()
        for n, cam in cams.items():
            st = stats[n]
            with st["lock"]:
                t = [x for x in st["t"] if t_start <= x <= t_end]
                raw = st["raw"]
            gaps = [(b - x) * 1000 for x, b in zip(t, t[1:])]
            r = {
                "index_or_path": cams_cfg[n]["index_or_path"],
                "new_frames": len(t),
                "new_fps": round(len(t) / (t_end - t_start), 2),
                "duplicate_reads": st["dup"],
                "read_errors": st["err"],
                "gap_ms_median": round(pct(gaps, 0.5), 2) if gaps else None,
                "gap_ms_p95": round(pct(gaps, 0.95), 2) if gaps else None,
                "gap_ms_max": round(max(gaps), 2) if gaps else None,
                "gaps_over_50ms": sum(g > 50 for g in gaps),  # 1.5프레임 이상 = 프레임을 건너뛴 구간
                "stalls_over_100ms": sum(g > 100 for g in gaps),
                "consumer_timeouts_200ms": timeouts[n],
                "raw_shape": list(raw.shape) if raw is not None else None,
                "processed_shapes": sorted(list(s) for s in shapes[n]),
            }
            if raw is not None:
                cv2.imwrite(str(out_dir / f"{n}_raw.png"), raw)  # OpenCV 원본(BGR, 회전 전)
            if n in last_proc:
                cv2.imwrite(str(out_dir / f"{n}_processed.png"), cv2.cvtColor(last_proc[n], cv2.COLOR_RGB2BGR))  # 공식 처리 후(RGB·회전)
            res["cameras"][n] = r
            ok = r["read_errors"] == 0 and r["stalls_over_100ms"] == 0 and r["consumer_timeouts_200ms"] == 0 and r["new_fps"] >= 28.5
            print(f"[{'OK' if ok else 'CHECK'}] {n}: 새 프레임 {r['new_frames']}개 = {r['new_fps']} fps, 간격 중앙값 {r['gap_ms_median']} ms · "
                  f"p95 {r['gap_ms_p95']} · 최대 {r['gap_ms_max']} ms, 50ms 초과 {r['gaps_over_50ms']}, 100ms 초과 멈춤 {r['stalls_over_100ms']}, 중복 {r['duplicate_reads']}, "
                  f"읽기 오류 {r['read_errors']}, 소비 시간초과 {r['consumer_timeouts_200ms']}, 원본 {r['raw_shape']} → 처리 후 {r['processed_shapes']}")
    finally:
        for cam in cams.values():
            if cam.is_connected:
                cam.disconnect()
    res["warnings"] = wc.msgs
    jp = WS / "logs" / f"camera-check-{ts}.json"
    jp.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    print(f"경고 {len(wc.msgs)}건" + (": " + " | ".join(wc.msgs[:3]) if wc.msgs else ""))
    print(f"기록: {jp}\n프레임: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
