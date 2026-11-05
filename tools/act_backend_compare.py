#!/usr/bin/env python3
"""ACT 추론 backend 비교 검증(로봇·카메라 없음) — PyTorch-MPS 기준 대비 Core ML GPU FP32·PyTorch CPU.

docs/ACT_INFERENCE_OPTIMIZATION_PLAN.md 7.1(수치)·7.2(지연)의 오프라인 검증 도구다. 공식 코드는 수정하지 않는다.
녹화 데이터셋(Hub)의 실제 프레임·관절을 공식 SyncInferenceEngine(텐서 변환 → 전처리 → select_action(chunk 예측 →
ACTTemporalEnsembler) → 후처리)에 넣는다. backend별로 ACTPolicy.predict_action_chunk만 바꾼다(Core ML은 같은 가중치를 FP32로 변환).

  numeric  여러 에피소드를 backend마다 같은 순서로 실행해 4단계를 비교한다.
           ① chunk(정규화) ② 앙상블 출력(정규화) ③ 역정규화 목표(관절 °, gripper 0~100) ④ 기록된 관측 위치 기준
           ensure_safe_goal_position 적용 명령. 기준 편차: MPS 대 MPS 반복, MPS 대 CPU.
           reset 검사: 에피소드 A → B → reset → A가 처음 A와 같은지.
  latency  한 backend로 N초 연속 추론(추가 동기화 없음: 후처리의 CPU 복사가 끝난 시점까지를 틱 계산으로 잼).
           분당 p50·p95·p99, RSS·스왑, 발열 경고 기록을 남긴다.

Core ML 경로는 배포 코드 그대로다: tools/act_coreml_export.py(변환) + scripts/so101_act_coreml.attach(시작 검증·교체).
coremltools는 lock/macos-arm64에 고정돼 있다(9.0). 사용 예:
  .venv/bin/python tools/act_backend_compare.py numeric --episodes 0,15,35,55,75,95
  .venv/bin/python tools/act_backend_compare.py latency --backend coreml --seconds 600
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import subprocess
import sys
import time
import warnings
from copy import copy
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
DEFAULT_CKPT = WS / ".cache/models/act_so101_ball_to_bowl_v1/checkpoints/100000/pretrained_model"
REPO = ""  # --dataset-repo로 지정(예: <HF 사용자>/so101_ball_to_bowl_v1)
TASK = "Pick up the ball and place it in the bowl"
MAX_REL = {"shoulder_pan": 15.0, "shoulder_lift": 35.0, "elbow_flex": 30.0, "wrist_flex": 20.0, "wrist_roll": 10.0, "gripper": 25.0}
OUT = WS / ".tmp" / "act_eval"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def import_coremltools():
    warnings.filterwarnings("ignore")
    import logging

    logging.getLogger("coremltools").setLevel(logging.ERROR)
    import coremltools as ct

    return ct


# ---------------------------------------------------------------------------------------------
# 정책·엔진 구성(공식 객체)
# ---------------------------------------------------------------------------------------------
def build(ckpt: Path, device: str, n_action_steps: int = 1, coeff: float = 0.01):
    import torch
    from lerobot.cameras.configs import Cv2Rotation
    from lerobot.cameras.opencv import OpenCVCameraConfig
    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies.factory import make_pre_post_processors
    from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig
    from lerobot.rollout.inference.sync import SyncInferenceEngine
    from lerobot.utils.feature_utils import combine_feature_dicts, hw_to_dataset_features

    robot = SO101Follower(SO101FollowerConfig(port="/dev/null-not-opened", id="so101_follower", cameras={
        "front": OpenCVCameraConfig(index_or_path=1, width=640, height=480, fps=30, rotation=Cv2Rotation.ROTATE_180),
        "wrist": OpenCVCameraConfig(index_or_path=0, width=640, height=480, fps=30)}))  # 연결하지 않음(특징 정의만)
    feats = combine_feature_dicts(hw_to_dataset_features(robot.action_features, "action"),
                                  hw_to_dataset_features(robot.observation_features, "observation"))
    keys = list(robot.action_features)
    cfg = PreTrainedConfig.from_pretrained(ckpt)
    cfg.device, cfg.n_action_steps, cfg.temporal_ensemble_coeff = device, n_action_steps, coeff
    policy = ACTPolicy.from_pretrained(ckpt, config=cfg).to(torch.device(device)).eval()
    pre, post = make_pre_post_processors(policy_cfg=cfg, pretrained_path=ckpt, preprocessor_overrides={"device_processor": {"device": device}})
    eng = SyncInferenceEngine(policy=policy, preprocessor=pre, postprocessor=post, dataset_features=feats, ordered_action_keys=keys,
                              task=TASK, device=device, robot_type=robot.robot_type)
    return policy, eng, feats, keys


def official_coreml(policy, ckpt: Path, cache_root: Path) -> dict:
    """배포 코드 그대로: tools/act_coreml_export.py로 변환(있으면 재사용) → scripts/so101_act_coreml.attach(시작 검증 포함)."""
    r = subprocess.run([sys.executable, str(WS / "tools" / "act_coreml_export.py"), "--checkpoint", str(ckpt), "--cache-root", str(cache_root)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Core ML 변환 실패: {r.stdout[-400:]} {r.stderr[-400:]}")
    sys.path.insert(0, str(WS / "scripts"))
    import so101_act_coreml as C

    info = C.attach(policy, ckpt, cache_root)
    policy.predict_action_chunk = policy._so101_coreml  # 도구 안에서는 클래스 대신 인스턴스에 연결
    return info


# ---------------------------------------------------------------------------------------------
# 데이터
# ---------------------------------------------------------------------------------------------
def load_episodes(eps: list[int]):
    """Hub 데이터셋에서 해당 에피소드만 받아 (state, front uint8 HWC, wrist uint8 HWC) 생성기를 돌려준다."""
    import numpy as np
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    root = OUT / "ds" / REPO.split("/")[1]
    ds = LeRobotDataset(REPO, root=root, episodes=eps, video_backend="pyav")
    meta = ds.meta.episodes
    spans = {}
    for i in range(len(meta)):
        e = int(meta[i]["episode_index"])
        if e in eps:
            spans[e] = (int(meta[i]["dataset_from_index"]), int(meta[i]["dataset_to_index"]))
    # LeRobotDataset(episodes=...)는 선택된 에피소드만 순서대로 담는다 → 에피소드별 로컬 범위를 다시 구한다
    local, off = {}, 0
    for e in sorted(spans):
        n = spans[e][1] - spans[e][0]
        local[e] = (off, off + n)
        off += n

    def frames(e, limit=None):
        a, b = local[e]
        if limit:
            b = min(b, a + limit)
        for i in range(a, b):
            it = ds[i]
            if i == a:
                assert int(it["episode_index"]) == e, f"에피소드 매핑 오류: 기대 {e}, 실제 {int(it['episode_index'])}"
            yield (it["observation.state"].numpy().astype(np.float32),
                   (it["observation.images.front"].permute(1, 2, 0).numpy() * 255).round().astype(np.uint8),
                   (it["observation.images.wrist"].permute(1, 2, 0).numpy() * 255).round().astype(np.uint8))
    return frames, {e: local[e][1] - local[e][0] for e in local}


# ---------------------------------------------------------------------------------------------
# 수치 비교
# ---------------------------------------------------------------------------------------------
def run_backend(name, policy, eng, feats, keys, seq):
    """seq: [(tag, frames iterator 생성 함수)]. 각 tag 시작 때 엔진 reset(공식 BaseStrategy 시작과 같음)."""
    import numpy as np
    from lerobot.robots.utils import ensure_safe_goal_position
    from lerobot.utils.feature_utils import build_dataset_frame

    rec: dict = {}
    cap: dict = {}
    orig_pac = policy.predict_action_chunk

    def pac(batch):
        c = orig_pac(batch)
        cap["chunk"] = c.detach().float().cpu().numpy()[0].copy()
        return c
    policy.predict_action_chunk = pac
    ens = policy.temporal_ensembler
    orig_upd = ens.update

    def upd(actions):
        a = orig_upd(actions)
        cap["ens"] = a.detach().float().cpu().numpy()[0].copy()
        return a
    ens.update = upd
    t0 = time.time()
    for tag, gen in seq:
        eng.reset()
        ch, en, cm_, cl = [], [], [], []
        for st, fr, wr in gen():
            obs = dict(zip(keys, st.tolist()))
            obs["front"], obs["wrist"] = fr, wr
            a = eng.get_action(build_dataset_frame(feats, obs, prefix="observation"))
            cmd = a.numpy().astype(np.float32)
            goal_present = {k.removesuffix(".pos"): (float(cmd[j]), float(st[j])) for j, k in enumerate(keys)}
            safe = ensure_safe_goal_position(goal_present, MAX_REL)
            ch.append(cap["chunk"]); en.append(cap["ens"]); cm_.append(cmd)
            cl.append(np.array([safe[k.removesuffix(".pos")] for k in keys], dtype=np.float32))
        rec[tag] = {"chunk": np.stack(ch), "ens": np.stack(en), "cmd": np.stack(cm_), "clip": np.stack(cl)}
    policy.predict_action_chunk = orig_pac
    ens.update = orig_upd
    log(f"{name}: {sum(len(v['cmd']) for v in rec.values())}틱 {time.time() - t0:.0f}s")
    return rec


def diff_stats(a: dict, b: dict, tags: list[str]) -> dict:
    import numpy as np

    out = {}
    for stage, unit in (("chunk", "정규화"), ("ens", "정규화"), ("cmd", "관절°/gripper"), ("clip", "관절°/gripper")):
        d = np.concatenate([np.abs(a[t][stage].astype(np.float64) - b[t][stage].astype(np.float64)).reshape(-1, 6) for t in tags])
        first = np.concatenate([np.abs(a[t][stage][:1].astype(np.float64) - b[t][stage][:1].astype(np.float64)).reshape(-1, 6) for t in tags])
        late = [np.abs(a[t][stage][100:].astype(np.float64) - b[t][stage][100:].astype(np.float64)).reshape(-1, 6) for t in tags
                if len(a[t][stage]) > 100]
        late = np.concatenate(late) if late else np.zeros((1, 6))
        out[stage] = {"unit": unit, "max": float(d.max()), "mean": float(d.mean()), "p99": float(np.percentile(d, 99)),
                      "per_joint_max": [float(x) for x in d.max(0)], "first_tick_max": float(first.max()),
                      "after_100_ticks_max": float(late.max()), "exact_equal_ratio": float((d == 0).mean())}
    return out


def cmd_numeric(a) -> int:
    import logging

    import numpy as np
    import torch

    logging.getLogger().setLevel(logging.ERROR)  # 제한 적용 경고(공식 ensure_safe_goal_position)가 매 틱 출력되는 것을 끔. 비율은 따로 기록

    eps = [int(x) for x in a.episodes.split(",")]
    frames, lens = load_episodes(eps)
    log(f"에피소드 길이: {lens}")
    lim = a.limit or None
    tags = [f"ep{e}" for e in eps]
    seq = [(f"ep{e}", (lambda e=e: frames(e, lim))) for e in eps]
    # reset 검사용: A → B → reset → A
    A, B = eps[0], eps[1]
    seq_reset = [(f"A_ep{A}", lambda: frames(A, 150)), (f"B_ep{B}", lambda: frames(B, 150)), (f"A2_ep{A}", lambda: frames(A, 150))]
    ct = import_coremltools()
    ckpt = Path(a.checkpoint)
    res: dict = {"checkpoint": str(ckpt), "episodes": lens, "limit_per_episode": lim, "torch": torch.__version__,
                 "coremltools": ct.__version__, "max_relative_target": MAX_REL, "ensemble_coeff": 0.01, "n_action_steps": 1}
    runs: dict = {}
    for name, dev in (("mps", "mps"), ("mps_repeat", "mps"), ("coreml", "cpu"), ("cpu", "cpu")):
        policy, eng, feats, keys = build(ckpt, dev)
        if name == "coreml":
            res["coreml_model"] = official_coreml(policy, ckpt, Path(a.cache_root))
        s = seq if name != "cpu" else seq[:2]  # CPU는 느려서 기준 편차용으로 2개만
        runs[name] = run_backend(name, policy, eng, feats, keys, s)
        if name == "coreml":
            runs["coreml_reset"] = run_backend("coreml_reset", policy, eng, feats, keys, seq_reset)
        if name == "mps":
            runs["mps_reset"] = run_backend("mps_reset", policy, eng, feats, keys, seq_reset)
        del policy, eng
        if dev == "mps":
            torch.mps.empty_cache()
    res["coreml_vs_mps"] = diff_stats(runs["coreml"], runs["mps"], tags)
    res["mps_vs_mps_repeat"] = diff_stats(runs["mps_repeat"], runs["mps"], tags)
    res["cpu_vs_mps"] = diff_stats(runs["cpu"], runs["mps"], tags[:2])
    res["coreml_vs_cpu"] = diff_stats(runs["coreml"], runs["cpu"], tags[:2])
    for b in ("mps", "coreml"):
        r = runs[f"{b}_reset"]
        res[f"reset_{b}"] = {"A_after_B_and_reset_equals_fresh_A": bool(all(np.array_equal(r[f"A_ep{A}"][s], r[f"A2_ep{A}"][s]) for s in ("chunk", "ens", "cmd"))),
                             "max_abs": float(max(np.abs(r[f"A_ep{A}"][s] - r[f"A2_ep{A}"][s]).max() for s in ("chunk", "ens", "cmd")))}
    # '차이 0' 재확인: 서로 다른 배열인지, 값 예시
    t0 = tags[0]
    k = min(50, len(runs["mps"][t0]["cmd"]) - 1)
    res["sanity"] = {"same_object": runs["coreml"][t0]["cmd"] is runs["mps"][t0]["cmd"], "dtype": str(runs["coreml"][t0]["cmd"].dtype),
                     "tick": k, "coreml_cmd": runs["coreml"][t0]["cmd"][k].tolist(), "mps_cmd": runs["mps"][t0]["cmd"][k].tolist(),
                     "clip_changed_ratio_mps": float(np.mean([np.any(np.abs(runs["mps"][t]["clip"] - runs["mps"][t]["cmd"]) > 1e-6, axis=1).mean() for t in tags]))}
    a_out = Path(a.out)
    a_out.mkdir(parents=True, exist_ok=True)
    (a_out / "numeric.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    np.savez_compressed(a_out / "numeric_arrays.npz", **{f"{n}__{t}__{s}": v[t][s] for n, v in runs.items() for t in v for s in v[t]})
    log(f"저장: {a_out / 'numeric.json'}")
    print(json.dumps({k: res[k] for k in ("coreml_vs_mps", "mps_vs_mps_repeat", "cpu_vs_mps", "reset_mps", "reset_coreml", "sanity")},
                     ensure_ascii=False)[:3000])
    return 0


# ---------------------------------------------------------------------------------------------
# 지연(지속)
# ---------------------------------------------------------------------------------------------
def swap_used_mb() -> float:
    try:
        s = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True).stdout
        return float(s.split("used = ")[1].split("M")[0])
    except Exception:  # noqa: BLE001
        return float("nan")


def therm() -> str:
    try:
        return subprocess.run(["pmset", "-g", "therm"], capture_output=True, text=True).stdout.strip().replace("\n", " | ")
    except Exception:  # noqa: BLE001
        return "?"


def cmd_latency(a) -> int:
    import numpy as np
    from lerobot.utils.feature_utils import build_dataset_frame

    frames, lens = load_episodes([a.episode])
    buf = list(frames(a.episode, 150))
    dev = "mps" if a.backend == "mps" else "cpu"
    policy, eng, feats, keys = build(Path(a.checkpoint), dev)
    info = {}
    if a.backend == "coreml":
        info = official_coreml(policy, Path(a.checkpoint), Path(a.cache_root))
    eng.reset()
    period = 1 / 30
    t_start = time.perf_counter()
    per_min: list[dict] = []
    cur: list[float] = []
    mark = t_start
    i = 0
    batt = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout.splitlines()[0]
    meta = {"backend": a.backend, "device": dev, "seconds": a.seconds, "power": batt, "therm_start": therm(), "swap_start_mb": swap_used_mb(),
            "coreml": info, "note": "틱 계산 = 텐서 변환~후처리(CPU 복사 완료)까지, 단계별 동기화 없음. 30Hz 간격 유지(남으면 sleep)."}
    warm = []
    while time.perf_counter() - t_start < a.seconds:
        st, fr, wr = buf[i % len(buf)]
        obs = dict(zip(keys, st.tolist()))
        obs["front"], obs["wrist"] = fr, wr
        t0 = time.perf_counter()
        eng.get_action(build_dataset_frame(feats, obs, prefix="observation"))
        dt = (time.perf_counter() - t0) * 1000
        (warm if i < 20 else cur).append(dt)
        i += 1
        rest = period - (time.perf_counter() - t0)
        if rest > 0:
            time.sleep(rest)
        if time.perf_counter() - mark >= 60 or time.perf_counter() - t_start >= a.seconds:
            if cur:
                v = np.array(cur)
                per_min.append({"minute": len(per_min) + 1, "n": len(v), "mean": round(float(v.mean()), 2), "p50": round(float(np.percentile(v, 50)), 2),
                                "p95": round(float(np.percentile(v, 95)), 2), "p99": round(float(np.percentile(v, 99)), 2),
                                "max": round(float(v.max()), 2), "rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6, 1),
                                "swap_mb": swap_used_mb()})
                log(f"{a.backend} {per_min[-1]}")
            cur, mark = [], time.perf_counter()
    meta.update(therm_end=therm(), swap_end_mb=swap_used_mb(), warmup_first_ms=[round(x, 1) for x in warm[:10]], ticks=i)
    allv = per_min
    if allv:
        meta["first_min_p95"], meta["last_min_p95"] = allv[0]["p95"], allv[-1]["p95"]
        meta["p95_drift_pct"] = round((allv[-1]["p95"] / allv[0]["p95"] - 1) * 100, 1)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"latency_{a.backend}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    p.write_text(json.dumps({"meta": meta, "per_minute": per_min}, ensure_ascii=False, indent=1))
    log(f"저장: {p}")
    print(json.dumps({"meta": {k: meta[k] for k in meta if k != 'coreml'}, "per_minute": per_min}, ensure_ascii=False))
    return 0


def cmd_ab(a) -> int:
    """같은 프로세스에서 MPS와 Core ML을 block초씩 번갈아 실행(같은 발열·메모리 상태에서 짝 비교)."""
    import numpy as np
    from lerobot.utils.feature_utils import build_dataset_frame

    frames, _ = load_episodes([a.episode])
    buf = list(frames(a.episode, 150))
    pm, em, feats, keys = build(Path(a.checkpoint), "mps")
    pc, ec, _, _ = build(Path(a.checkpoint), "cpu")
    info = official_coreml(pc, Path(a.checkpoint), Path(a.cache_root))
    engines = {"mps": em, "coreml": ec}
    for e in engines.values():
        e.reset()
    period = 1 / 30
    blocks = []
    i = 0
    meta = {"block_s": a.block, "rounds": a.rounds, "power": subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout.splitlines()[0],
            "therm_start": therm(), "swap_start_mb": swap_used_mb(), "coreml": info}
    for r in range(a.rounds):
        for name in (("mps", "coreml") if r % 2 == 0 else ("coreml", "mps")):
            eng = engines[name]
            v = []
            t_end = time.perf_counter() + a.block
            k = 0
            while time.perf_counter() < t_end:
                st, fr, wr = buf[i % len(buf)]
                obs = dict(zip(keys, st.tolist()))
                obs["front"], obs["wrist"] = fr, wr
                t0 = time.perf_counter()
                eng.get_action(build_dataset_frame(feats, obs, prefix="observation"))
                dt = (time.perf_counter() - t0) * 1000
                if k >= 10:  # 블록 전환 직후 10틱 제외
                    v.append(dt)
                k += 1
                i += 1
                rest = period - (time.perf_counter() - t0)
                if rest > 0:
                    time.sleep(rest)
            v = np.array(v)
            b = {"round": r + 1, "backend": name, "n": len(v), "mean": round(float(v.mean()), 2), "p50": round(float(np.percentile(v, 50)), 2),
                 "p95": round(float(np.percentile(v, 95)), 2), "p99": round(float(np.percentile(v, 99)), 2), "swap_mb": swap_used_mb()}
            blocks.append(b)
            log(f"ab {b}")
    meta.update(therm_end=therm(), swap_end_mb=swap_used_mb())
    summ = {}
    for name in ("mps", "coreml"):
        bs = [b for b in blocks if b["backend"] == name]
        summ[name] = {k: round(float(np.median([b[k] for b in bs])), 2) for k in ("mean", "p50", "p95", "p99")}
    summ["coreml_over_mps_p50"] = round(summ["coreml"]["p50"] / summ["mps"]["p50"], 3)
    summ["coreml_over_mps_p95"] = round(summ["coreml"]["p95"] / summ["mps"]["p95"], 3)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pth = out / f"ab_{time.strftime('%Y%m%d_%H%M%S')}.json"
    pth.write_text(json.dumps({"meta": meta, "blocks": blocks, "summary_median_of_blocks": summ}, ensure_ascii=False, indent=1))
    log(f"저장: {pth}")
    print(json.dumps(summ, ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("numeric")
    p.add_argument("--episodes", default="0,15,35,55,75,95")
    p.add_argument("--limit", type=int, default=0, help="에피소드당 최대 틱(0=전체)")
    p = sub.add_parser("latency")
    p.add_argument("--backend", choices=("mps", "coreml"), required=True)
    p.add_argument("--seconds", type=float, default=600)
    p.add_argument("--episode", type=int, default=35)
    p = sub.add_parser("ab")
    p.add_argument("--block", type=float, default=60)
    p.add_argument("--rounds", type=int, default=4)
    p.add_argument("--episode", type=int, default=35)
    for p in sub.choices.values():
        p.add_argument("--checkpoint", default=str(DEFAULT_CKPT))
        p.add_argument("--dataset-repo", required=True, help="입력 프레임을 받을 Hugging Face 데이터셋 repo_id(예: user/so101_ball_to_bowl_v1)")
        p.add_argument("--cache-root", default=str(WS / ".cache" / "coreml"), help="Core ML 변환본 위치(배포와 같은 기본값)")
        p.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    global REPO
    REPO = a.dataset_repo
    os.chdir(WS)
    return {"numeric": cmd_numeric, "latency": cmd_latency, "ab": cmd_ab}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
