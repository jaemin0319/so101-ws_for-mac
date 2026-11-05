#!/usr/bin/env python3
"""데이터셋 소프트웨어 검증(로봇·카메라 없음, 검증 전용 도구).

공식 LeRobotDataset API(create → add_frame → save_episode → finalize)와 실제 PyAV 인코더로 **합성(SYNTHETIC) 시험 데이터셋**을
만들고, 공식 API로 다시 열어 scripts/so101_dataset.py inspect로 검사한다. 일부러 손상시킨 사본(영상 삭제·timestamp 역전·NaN·
관절 이름 변경·행 누락·task 누락)은 검사가 FAIL로 잡아내는지 확인한다. 합성 데이터는 실로봇 수집 성공으로 세지 않는다.

실행:  .venv/bin/python tools/verify_dataset.py      (결과: .tmp/verify_dataset/result.json)
특징 정의는 공식 SO101Follower(연결 없음)+hw_to_dataset_features로 lerobot-record와 같은 방식으로 만든다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
IS_MAC = sys.platform == "darwin"
_LEAK = ("PYTHONPATH", "PYTHONHOME", "LD_LIBRARY_PATH") + (
    ("DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES") if IS_MAC else ())
if any(os.environ.get(k) for k in _LEAK) or os.environ.get("PYTHONNOUSERSITE") != "1":
    env = {k: v for k, v in os.environ.items() if k not in _LEAK}
    env.update(PYTHONNOUSERSITE="1", SO101_WS=str(WS), HF_HOME=str(WS / ".cache/huggingface"), HF_HUB_OFFLINE="1",
               TMPDIR=str(WS / ".tmp"))
    os.execve(sys.executable, [sys.executable, *sys.argv], env)

sys.path.insert(0, str(WS / "scripts"))
OUT = WS / ".tmp" / "verify_dataset"
RESULTS: list[dict] = []
FPS, W, H, FRAMES = 30, 160, 120, 45  # 작은 시험: 2 에피소드 × 45프레임(1.5초), 카메라 1대 160×120


def check(name: str, cond: bool, detail: str = "") -> bool:
    RESULTS.append({"test": name, "pass": bool(cond), "detail": detail})
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""), flush=True)
    return cond


def make_dataset(name: str, vcodec: str) -> tuple[Path, float]:
    """공식 API로 합성 데이터셋을 만든다(카메라·모터 대신 합성 이미지·관절 값)."""
    import numpy as np

    import so101_dataset as D
    from lerobot.configs.video import RGBEncoderConfig
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    cams = {"front": {"type": "opencv", "index_or_path": 0, "width": W, "height": H, "fps": FPS}}
    feats = D.expected_features(cams, True)
    root = OUT / name
    t0 = time.time()
    ds = LeRobotDataset.create(f"local/{name}", FPS, features=feats, root=root, robot_type="so_follower", use_videos=True,
                               image_writer_threads=4, rgb_encoder=RGBEncoderConfig(vcodec=vcodec), video_backend="pyav")
    state_names = feats["observation.state"]["names"]
    for ep in range(2):
        for i in range(FRAMES):
            t = i / FPS
            q = np.array([10 * np.sin(t + k) for k in range(5)] + [50 + 40 * np.sin(t)], dtype=np.float32)
            img = np.zeros((H, W, 3), dtype=np.uint8)
            img[:, :, 0] = (np.arange(W)[None, :] + 4 * i) % 256
            img[:, :, 1] = (np.arange(H)[:, None] * 2) % 256
            img[:, :, 2] = 80 * ep
            ds.add_frame({"observation.state": q, "action": q + 0.5, "observation.images.front": img,
                          "task": f"SYNTHETIC test data (no robot), episode group {ep}"})
        ds.save_episode()
    ds.finalize()
    assert len(state_names) == 6
    return root, time.time() - t0


def run_inspect(root: Path, episodes: set[int] | None = None) -> dict:
    import io
    import contextlib

    import so101_dataset as D

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        res = D.inspect_dataset(root, decode=True, episodes=episodes)
    res["_stdout"] = buf.getvalue()
    return res


def fails_text(res: dict) -> str:
    return " | ".join(f"{t}: {d}"[:160] for s, t, d in res["items"] if s == "FAIL")


def rewrite_parquet(path: Path, fn) -> None:
    import pyarrow.parquet as pq

    t = pq.read_table(path)
    t2 = fn(t)
    pq.write_table(t2.replace_schema_metadata(t.schema.metadata), path)


def main() -> int:
    import numpy as np

    if OUT.is_dir():
        shutil.rmtree(OUT)  # 이 도구 전용 임시 폴더만 비운다
    OUT.mkdir(parents=True)

    # 1) 공식 기본 코덱(libsvtav1)으로 생성·종료·재열기·검사
    root, dt = make_dataset("SYNTHETIC_TEST_so101_av1", "libsvtav1")
    info = json.loads((root / "meta" / "info.json").read_text())
    check("합성 데이터셋 생성(공식 create/add_frame/save_episode/finalize, libsvtav1)",
          info.get("total_episodes") == 2 and info.get("total_frames") == 2 * FRAMES,
          f"{dt:.1f}s, episodes {info.get('total_episodes')}, frames {info.get('total_frames')}")
    tree = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
    leftover = [t for t in tree if t.startswith("images/")]
    check("공식 v3 폴더 구조(meta/·data/·videos/), 인코딩 후 임시 PNG 없음", any(t.startswith("meta/") for t in tree)
          and any(t.startswith("data/") for t in tree) and any(t.startswith("videos/") for t in tree) and not leftover,
          ", ".join(tree)[:300])
    mp4s = [p for p in root.rglob("*.mp4")]
    import av

    codec = None
    if mp4s:
        with av.open(str(mp4s[0])) as c:
            codec = c.streams.video[0].codec_context.name
    check("영상 실제 인코딩(MP4 코덱 확인)", codec in ("libdav1d", "av1", "libaom-av1", "libsvtav1"), f"{[p.name for p in mp4s]} codec={codec}")
    res = run_inspect(root)
    check("inspect: 정상 합성 데이터셋 FAIL 0", res["fail"] == 0, fails_text(res) or f"WARN {res['warn']}")
    eps = res.get("episodes", [])
    check("inspect: 에피소드별 디코드 프레임 수 = length(공유 MP4 offset 기준)",
          len(eps) == 2 and all(e.get("observation.images.front_decoded") == e["length"] == FRAMES for e in eps), json.dumps(eps)[:200])

    # 2) 공식 기본 디코더 경로(video_backend 미지정): torchcodec 로드 불가 시 pyav 대체로 읽히는지
    import logging

    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    logging.getLogger("lerobot.utils.import_utils").setLevel(logging.CRITICAL)
    try:
        ds = LeRobotDataset(f"local/{root.name}", root=root)
        item = ds[len(ds) - 1]
        check("공식 기본 디코더 경로로 재열기·마지막 프레임 디코드", tuple(item["observation.images.front"].shape) == (3, H, W),
              f"backend={ds._video_backend}, shape={tuple(item['observation.images.front'].shape)}")
    except Exception as e:  # noqa: BLE001
        check("공식 기본 디코더 경로로 재열기·마지막 프레임 디코드", False, f"{type(e).__name__}: {e}")

    # 3) 맥 하드웨어 인코더(h264_videotoolbox)도 같은 경로로 생성·검사(대안 코덱)
    if IS_MAC:
        try:
            root_h, dt_h = make_dataset("SYNTHETIC_TEST_so101_h264vt", "h264_videotoolbox")
            r2 = run_inspect(root_h)
            check("대안 코덱 h264_videotoolbox 생성·검사 FAIL 0", r2["fail"] == 0, f"{dt_h:.1f}s " + (fails_text(r2) or ""))
        except Exception as e:  # noqa: BLE001
            check("대안 코덱 h264_videotoolbox 생성·검사 FAIL 0", False, f"{type(e).__name__}: {e}")

    # 4) 손상 사본: 검사가 FAIL로 잡아내는지
    def corrupt(tag: str, fn) -> dict:
        dst = OUT / f"CORRUPT_{tag}"
        shutil.copytree(root, dst)
        fn(dst)
        return run_inspect(dst)

    data_pq = lambda r: sorted((r / "data").rglob("*.parquet"))[0]  # noqa: E731

    r = corrupt("video_missing", lambda d: [p.unlink() for p in d.rglob("*.mp4")])
    check("손상 탐지: 영상 파일 삭제 → FAIL(누락 파일로 보고)", r["fail"] > 0 and ".mp4" in fails_text(r), fails_text(r)[:200])

    def ts_reverse(d: Path) -> None:
        import pyarrow as pa

        def fn(t):
            ts = t["timestamp"].to_numpy().copy()
            ts[5], ts[6] = ts[6], ts[5]
            return t.set_column(t.schema.get_field_index("timestamp"), "timestamp", pa.array(ts, type=t.schema.field("timestamp").type))
        rewrite_parquet(data_pq(d), fn)
    r = corrupt("timestamp", ts_reverse)
    check("손상 탐지: 에피소드 안 timestamp 역전 → FAIL", r["fail"] > 0 and "timestamp" in fails_text(r), fails_text(r)[:200])
    # 범위 검사(녹화 후 자동 검사가 이번에 저장된 에피소드만 볼 때와 같은 경로): 손상은 episode 0에만 있다
    r1 = run_inspect(OUT / "CORRUPT_timestamp", episodes={1})
    check("범위 검사: episodes={1}이면 episode 0(손상)은 에피소드별 검사에서 제외 → FAIL 0, 1개만 검사",
          r1["fail"] == 0 and [e["episode_index"] for e in r1.get("episodes", [])] == [1]
          and r1.get("checked_episodes") == [1], fails_text(r1) or json.dumps(r1.get("episodes"))[:200])
    r0 = run_inspect(OUT / "CORRUPT_timestamp", episodes={0})
    check("범위 검사: episodes={0}이면 손상 탐지 → FAIL", r0["fail"] > 0 and "timestamp" in fails_text(r0), fails_text(r0)[:200])
    rx = run_inspect(root, episodes={7})
    check("범위 검사: 없는 에피소드 지정 → FAIL", rx["fail"] > 0 and "없음" in fails_text(rx), fails_text(rx)[:200])

    def nan_action(d: Path) -> None:
        import pyarrow as pa

        def fn(t):
            col = t["action"].to_pylist()
            col[3][2] = float("nan")
            return t.set_column(t.schema.get_field_index("action"), "action", pa.array(col, type=t.schema.field("action").type))
        rewrite_parquet(data_pq(d), fn)
    r = corrupt("nan", nan_action)
    check("손상 탐지: action NaN → FAIL", r["fail"] > 0 and "NaN" in fails_text(r), fails_text(r)[:200])

    def swap_names(d: Path) -> None:
        p = d / "meta" / "info.json"
        info = json.loads(p.read_text())
        n = info["features"]["observation.state"]["names"]
        n[0], n[1] = n[1], n[0]
        p.write_text(json.dumps(info, indent=4))
    r = corrupt("names", swap_names)
    check("손상 탐지: 관절 이름 순서 변경(형태는 6 그대로) → FAIL", r["fail"] > 0 and "observation.state" in fails_text(r), fails_text(r)[:200])

    def drop_rows(d: Path) -> None:
        rewrite_parquet(data_pq(d), lambda t: t.slice(0, t.num_rows - 3))
    r = corrupt("rows", drop_rows)
    check("손상 탐지: 마지막 에피소드 행 3개 누락 → FAIL", r["fail"] > 0, fails_text(r)[:200])

    def bad_task(d: Path) -> None:
        import pyarrow as pa

        def fn(t):
            ti = t["task_index"].to_numpy().copy()
            ti[:] = 99
            return t.set_column(t.schema.get_field_index("task_index"), "task_index", pa.array(ti, type=t.schema.field("task_index").type))
        rewrite_parquet(data_pq(d), fn)
    r = corrupt("task", bad_task)
    check("손상 탐지: 없는 task_index → FAIL", r["fail"] > 0 and "task" in fails_text(r), fails_text(r)[:200])

    # 4b) 이어 녹화(--resume) 후 자동 검사 범위: 녹화 전후 total_episodes 차이 = 이번에 저장된 에피소드
    import so101_dataset as D

    res_root = OUT / "RESUME_so101"
    shutil.copytree(root, res_root)
    before = D.episode_count(res_root)
    ds_r = LeRobotDataset.resume(f"local/{res_root.name}", root=res_root, image_writer_threads=4,
                                 rgb_encoder=__import__("lerobot.configs.video", fromlist=["RGBEncoderConfig"]).RGBEncoderConfig(vcodec="libsvtav1"))
    for i in range(FRAMES):
        t = i / FPS
        q = np.array([5 * np.cos(t + k) for k in range(5)] + [30 + 20 * np.cos(t)], dtype=np.float32)
        img = np.full((H, W, 3), (i * 5) % 256, dtype=np.uint8)
        ds_r.add_frame({"observation.state": q, "action": q, "observation.images.front": img,
                        "task": "SYNTHETIC test data (no robot), episode group 0"})
    ds_r.save_episode()
    ds_r.finalize()
    new = set(range(before, D.episode_count(res_root)))
    rr = run_inspect(res_root, episodes=new)
    check("이어 녹화 후 범위 검사: 새 에피소드 {2}만 디코드 검사, 데이터셋 수준 FAIL 0",
          before == 2 and new == {2} and rr["fail"] == 0 and [e["episode_index"] for e in rr.get("episodes", [])] == [2]
          and rr["episodes"][0].get("observation.images.front_decoded") == FRAMES,
          f"before={before}, new={sorted(new)}, " + (fails_text(rr) or json.dumps(rr.get("episodes"))[:160]))

    # 5) 래퍼 진입점(03_dataset/inspect.sh) + 이관용 체크섬·manifest
    p = subprocess.run([str(WS / "03_dataset" / "inspect.sh"), str(root), "--write-manifest"], capture_output=True, text=True, cwd="/")
    cs = root.parent / f"{root.name}.sha256"
    v = subprocess.run(["shasum", "-a", "256", "-c", "--quiet", cs.name], capture_output=True, text=True, cwd=root.parent) if cs.is_file() else None
    check("inspect.sh --write-manifest: exit 0(또는 WARN 2) + sha256 목록 검증 통과",
          p.returncode in (0, 2) and v is not None and v.returncode == 0 and (root.parent / f"{root.name}.so101.json").is_file(),
          f"inspect rc={p.returncode}, shasum rc={v.returncode if v else None}, files={sum(1 for _ in open(cs)) if cs.is_file() else 0}")
    # 이관 시뮬레이션: 다른 경로로 복사 → 체크섬 검증 → 공식 API로 열기
    dst_parent = OUT / "copied_to_lab"
    dst_parent.mkdir()
    shutil.copytree(root, dst_parent / root.name)
    shutil.copy2(cs, dst_parent / cs.name)
    v2 = subprocess.run(["shasum", "-a", "256", "-c", "--quiet", cs.name], capture_output=True, text=True, cwd=dst_parent)
    r3 = run_inspect(dst_parent / root.name)
    check("이관 시뮬레이션: 복사본 체크섬 검증 + 공식 API 재검사 FAIL 0", v2.returncode == 0 and r3["fail"] == 0,
          f"shasum rc={v2.returncode}, inspect fail={r3['fail']}")

    n_fail = sum(1 for x in RESULTS if not x["pass"])
    (OUT / "result.json").write_text(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "synthetic": True,
                                                 "results": RESULTS}, ensure_ascii=False, indent=1))
    print(f"\n합계 PASS {len(RESULTS) - n_fail} / {len(RESULTS)}, FAIL {n_fail}  (합성 데이터: 실로봇 수집 아님)")
    _ = np
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
