#!/usr/bin/env python
"""로봇 없이 정책(모델)을 점검한다: 데이터셋 에피소드의 관측을 넣어 예측 action 을 정답 action 과 비교.

학습한 모델이나 허브에서 받은 모델을 로봇에 올리기 전에
  - 모델·전처리기가 이 LeRobot 버전에서 로드되는지
  - 카메라/상태 이름이 데이터셋과 맞는지
  - 추론 시간(ms)이 fps 안에 드는지
  - 예측이 사람 시연(정답)과 비슷한지
를 확인한다. 로봇·카메라를 열지 않는다.

예:
  python scripts/check_policy.py \
      --policy models/act_so101_ball_to_bowl_v1/checkpoints/100000/pretrained_model \
      --dataset <HF_USER>/so101_ball_to_bowl_v1 --episode 0
  python scripts/check_policy.py --policy my_act_job --dataset my_data      # outputs/train/my_act_job, <HF_USER>/my_data
"""

import argparse
import os
import time
from pathlib import Path

import numpy as np
import torch

from lerobot.configs.policies import PreTrainedConfig
from lerobot.datasets import LeRobotDataset
from lerobot.policies import make_policy, make_pre_post_processors
from lerobot.processor import policy_output_to_transition, transition_to_policy_action


def _pick_checkpoint(d: Path) -> Path:
    if (d / "config.json").is_file() and (d / "model.safetensors").is_file():
        return d
    if (d / "checkpoints/last/pretrained_model/config.json").is_file():
        return d / "checkpoints/last/pretrained_model"
    found = sorted(d.glob("**/pretrained_model/config.json"))
    if not found:
        raise SystemExit(f"[오류] pretrained_model 을 찾지 못했다: {d}")
    return found[-1].parent  # 가장 큰 step


def resolve_policy_path(p: str) -> str:
    """rollout.sh 와 같은 규칙: 경로 → outputs/train/<job> → models/<name> → 허브 repo_id."""
    ws = Path(os.environ.get("SO101_WS", Path(__file__).resolve().parents[1]))
    out = Path(os.environ.get("SO101_OUTPUT_DIR", ws / "outputs"))
    models = Path(os.environ.get("SO101_MODEL_DIR", ws / "models"))
    for cand in (Path(p).expanduser(), out / "train" / p, models / p):
        if cand.is_dir():
            return str(_pick_checkpoint(cand.resolve()))
    if "/" in p:
        return p  # 허브 repo_id (루트에 config.json 이 있는 repo)
    raise SystemExit(f"[오류] 모델을 찾지 못했다: {p} (bash scripts/hub.sh list)")


def resolve_repo_id(r: str) -> str:
    return r if "/" in r else f"{os.environ.get('HF_USER', '')}/{r}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--policy", required=True, help="pretrained_model 폴더, outputs/train/<job>, 또는 허브 repo_id")
    ap.add_argument("--dataset", required=True, help="데이터셋 repo_id (data/<repo_id> 에 있으면 로컬 사용)")
    ap.add_argument("--episode", type=int, default=0)
    ap.add_argument("--frames", type=int, default=0, help="앞에서부터 N 프레임만(0 = 에피소드 전체)")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu"))
    ap.add_argument("--n-action-steps", type=int, default=None, help="ACT 등: 한 번 추론해서 실행할 action 수")
    ap.add_argument("--ensemble", type=float, default=None, help="ACT temporal ensembling 계수(예 0.01)")
    args = ap.parse_args()

    policy_path = resolve_policy_path(args.policy)
    cfg = PreTrainedConfig.from_pretrained(policy_path)
    cfg.pretrained_path = policy_path
    cfg.device = args.device
    if args.ensemble is not None:
        cfg.temporal_ensemble_coeff = args.ensemble
        cfg.n_action_steps = 1
    elif args.n_action_steps is not None:
        cfg.n_action_steps = args.n_action_steps

    repo_id = resolve_repo_id(args.dataset)
    ds = LeRobotDataset(repo_id, episodes=[args.episode])
    print(f"[dataset] {repo_id} root={ds.root}")
    print(f"          episode={args.episode} frames={ds.num_frames} fps={ds.fps} robot={ds.meta.robot_type}")

    # 이름 확인: 정책 입력 ↔ 데이터셋 특징
    missing = [k for k in cfg.input_features if k not in ds.features]
    if missing:
        raise SystemExit(f"[오류] 정책 입력 {missing} 이 데이터셋에 없다. 데이터셋 특징: {list(ds.features)}")

    policy = make_policy(cfg, ds_meta=ds.meta)
    policy.eval()
    pre, post = make_pre_post_processors(
        cfg,
        pretrained_path=policy_path,
        preprocessor_overrides={"device_processor": {"device": args.device}},
    )
    print(f"[policy]  type={cfg.type} device={args.device} path={policy_path}")
    print(f"          inputs={list(cfg.input_features)} outputs={list(cfg.output_features)}")
    extra = {k: getattr(cfg, k) for k in ("chunk_size", "n_action_steps", "temporal_ensemble_coeff") if hasattr(cfg, k)}
    if extra:
        print(f"          {extra}")

    policy.reset()
    n = ds.num_frames if args.frames <= 0 else min(args.frames, ds.num_frames)
    preds, gts, times = [], [], []
    for i in range(n):
        item = ds[i]
        obs = {k: v.unsqueeze(0) for k, v in item.items() if k.startswith("observation.")}
        obs["task"] = [item["task"]]
        obs["robot_type"] = ds.meta.robot_type or ""
        if args.device == "cuda":
            torch.cuda.synchronize()
        elif args.device == "mps":
            torch.mps.synchronize()
        t0 = time.perf_counter()
        with torch.inference_mode():
            batch = pre(obs)
            action = transition_to_policy_action(policy_output_to_transition(policy.select_action(batch)))
            action = post(action)
        if args.device == "cuda":
            torch.cuda.synchronize()
        elif args.device == "mps":
            torch.mps.synchronize()
        times.append((time.perf_counter() - t0) * 1000)
        preds.append(action.squeeze(0).float().cpu().numpy())
        gts.append(item["action"].float().numpy())

    preds, gts, times = np.stack(preds), np.stack(gts), np.array(times)
    names = ds.features["action"].get("names") or [f"a{i}" for i in range(gts.shape[1])]
    err = np.abs(preds - gts)
    print(f"\n[결과] {n} 프레임, task='{item['task']}'")
    print(f"  {'joint':<16}{'MAE':>8}{'max':>8}{'gt range':>12}")
    for j, name in enumerate(names):
        rng = gts[:, j].max() - gts[:, j].min()
        print(f"  {name:<16}{err[:, j].mean():8.2f}{err[:, j].max():8.2f}{rng:12.2f}")
    print(f"  전체 MAE = {err.mean():.2f} (단위: 데이터셋 action 단위, SO-101 은 관절 각도[deg], gripper 0~100)")
    budget = 1000 / ds.fps
    skip = 1 if len(times) > 1 else 0  # 첫 호출은 워밍업
    t = times[skip:]
    slow = (t > budget).sum()
    print(f"  추론 시간 ms: median={np.median(t):.1f} p95={np.percentile(t, 95):.1f} max={t.max():.1f}"
          f" (한 프레임 예산 {budget:.1f} ms, 초과 {slow}회 — chunk 정책은 몇 프레임마다 한 번만 무거움)")


if __name__ == "__main__":
    main()
