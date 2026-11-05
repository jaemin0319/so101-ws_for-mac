#!/usr/bin/env python3
"""rollout 제어 루프 단계별 시간 계측 — 공식 lerobot-rollout 프로세스 안에서 각 단계를 감싸 시간만 잰다.

scripts/so101_launch.py가 환경변수 SO101_ROLLOUT_TIMING=<폴더>일 때 공식 console script 실행 직전에 install()을 호출한다.
공식 LeRobot 파일은 수정하지 않는다. 동작(입력·출력 값)은 바꾸지 않고 시간과 횟수만 기록한다.

한 틱(BaseStrategy.run의 루프 1회)에서 재는 단계:
  obs           ThreadSafeRobot.get_observation 전체 = obs_motor(모터 Present_Position 읽기) + obs_camera(read_latest 2대)
  to_tensor     prepare_observation_for_inference(numpy → torch, 이미지 /255·CHW, 장치로 이동)
  preprocessor  정책 전처리 파이프라인(정규화 등)
  model         ACTPolicy.predict_action_chunk(MPS: 끝에서 synchronize해 GPU 시간을 이 단계에 귀속)
  ensemble      ACTTemporalEnsembler.update(동일하게 synchronize)
  postprocessor 정책 후처리(역정규화, CPU로 복사)
  engine        SyncInferenceEngine.get_action 전체(위 4단계 + 기타)
  send          ThreadSafeRobot.send_action 전체 = send_motor_read(max_relative_target용 현재 위치 읽기) + send_motor_write
  tick          연속한 두 틱 시작 사이 간격(실제 제어 주기)
max_relative_target으로 목표가 잘린 틱 수(clip)도 센다.
MPS synchronize는 결과를 CPU로 가져오는 후처리 단계에서 어차피 기다리는 시간을 앞 단계로 옮겨 재는 것이라, 틱 전체 시간은 거의 같다.
모드(SO101_ROLLOUT_TIMING_MODE): detail(기본, 위 전부 + 동기화) / light(추가 동기화 없이 tick·obs·engine·send와 모터·카메라만 —
engine은 후처리의 CPU 복사가 끝난 시점까지라 실제 계산 시간이다. 전체 루프 성능은 light로, 병목 귀속은 detail로 잰다).
결과: <폴더>/rollout-timing-<시각>.json(요약) + .csv(틱별). 처음 30틱(약 1초)은 워밍업으로 요약에서 따로 표시한다.
"""
from __future__ import annotations

import atexit
import csv
import json
import os
import sys
import threading
import time
from pathlib import Path

STAGES = ("tick", "obs", "obs_motor", "obs_camera", "to_tensor", "preprocessor", "model", "ensemble", "postprocessor",
          "engine", "send", "send_motor_read", "send_motor_write")
WARMUP_TICKS = 30
_state: dict = {"installed": False, "ticks": [], "cur": None, "phase": None, "in_run": False, "written": False,
                "meta": {}, "out": None}
_lock = threading.Lock()


def _now() -> float:
    return time.perf_counter()


def _add(stage: str, dt: float) -> None:
    cur = _state["cur"]
    if cur is not None and _state["in_run"]:
        cur[stage] = cur.get(stage, 0.0) + dt * 1000.0


def _sync(device_type: str | None) -> None:
    try:
        import torch

        if device_type == "mps":
            torch.mps.synchronize()
        elif device_type == "cuda":
            torch.cuda.synchronize()
    except Exception:  # noqa: BLE001
        pass


def _arg_value(name: str) -> str | None:
    for a in sys.argv:
        if a.startswith(f"--{name}="):
            return a.split("=", 1)[1]
    return None


def summarize(ticks: list[dict], fps: float | None, skip: int = WARMUP_TICKS) -> dict:
    import numpy as np

    body = ticks[skip:] if len(ticks) > skip + 10 else ticks
    out: dict = {"ticks_total": len(ticks), "ticks_summarized": len(body), "warmup_ticks_excluded": len(ticks) - len(body)}
    for s in STAGES:
        v = np.array([t[s] for t in body if s in t], dtype=float)
        if len(v):
            out[s] = {"mean": round(float(v.mean()), 2), "p50": round(float(np.percentile(v, 50)), 2),
                      "p95": round(float(np.percentile(v, 95)), 2), "max": round(float(v.max()), 2), "n": int(len(v))}
    if "tick" in out and out["tick"]["mean"] > 0:
        tk = np.array([t["tick"] for t in body if "tick" in t])
        out["hz_mean"] = round(1000.0 / float(tk.mean()), 2)
        if fps:
            out["target_hz"] = fps
            out["overrun_ratio"] = round(float((tk > 1000.0 / fps + 1.0).mean()), 3)
    clip = [t.get("clip") for t in body if "clip" in t]
    if clip:
        out["clip_ratio"] = round(sum(1 for c in clip if c) / len(clip), 3)
    if len(ticks) > len(body):
        w = [t.get("tick") for t in ticks[:len(ticks) - len(body)] if "tick" in t]
        out["warmup_tick_ms"] = [round(x, 1) for x in w[:10]]
    return out


def _write() -> None:
    with _lock:
        if _state["written"] or not _state["ticks"]:
            return
        _state["written"] = True
    out_dir = Path(_state["out"])
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    fps = float(_arg_value("fps")) if _arg_value("fps") else None
    summ = summarize(_state["ticks"], fps)
    meta = dict(_state["meta"], fps=fps, policy_path=_arg_value("policy.path"),
                n_action_steps=_arg_value("policy.n_action_steps"), temporal_ensemble_coeff=_arg_value("policy.temporal_ensemble_coeff"),
                device=_arg_value("device"), argv=sys.argv[1:])
    jp = out_dir / f"rollout-timing-{stamp}.json"
    jp.write_text(json.dumps({"meta": meta, "summary": summ}, ensure_ascii=False, indent=1))
    cp = out_dir / f"rollout-timing-{stamp}.csv"
    with cp.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["i", *STAGES, "clip"])
        for i, t in enumerate(_state["ticks"]):
            w.writerow([i, *[round(t[s], 3) if s in t else "" for s in STAGES], int(bool(t.get("clip")))])
    print_summary(summ, jp)


def print_summary(summ: dict, path: Path | None = None) -> None:
    def g(s, k="mean"):
        return summ.get(s, {}).get(k, float("nan"))
    lines = [f"\n[so101-timing] 제어 루프 계측 (워밍업 {summ.get('warmup_ticks_excluded', 0)}틱 제외, {summ.get('ticks_summarized', 0)}틱)",
             f"  실제 주기: 평균 {g('tick'):.1f} ms → {summ.get('hz_mean', float('nan'))} Hz (목표 {summ.get('target_hz')} Hz), "
             f"p95 {g('tick', 'p95'):.1f} ms, 주기 초과 {summ.get('overrun_ratio', float('nan')) * 100:.0f}%"]
    for s, label in (("obs", "관측 전체"), ("obs_motor", " ├ 모터 읽기"), ("obs_camera", " └ 카메라 read_latest"),
                     ("to_tensor", "텐서 변환·장치 이동"), ("preprocessor", "전처리(정규화)"), ("model", "모델 추론"),
                     ("ensemble", "앙상블"), ("postprocessor", "후처리"), ("engine", "추론 엔진 전체"),
                     ("send", "명령 전송 전체"), ("send_motor_read", " ├ 제한용 위치 읽기"), ("send_motor_write", " └ 목표 쓰기")):
        if s in summ:
            lines.append(f"  {label:<18} 평균 {g(s):7.2f}  p95 {g(s, 'p95'):7.2f}  최대 {g(s, 'max'):7.2f} ms")
    if "clip_ratio" in summ:
        lines.append(f"  max_relative_target로 잘린 틱: {summ['clip_ratio'] * 100:.1f}%")
    if path:
        lines.append(f"  기록: {path} (+ .csv 틱별)")
    print("\n".join(lines), flush=True)


def install(out_dir: str | os.PathLike | None = None, mode: str | None = None) -> None:
    if _state["installed"]:
        return
    _state["out"] = str(out_dir or os.environ["SO101_ROLLOUT_TIMING"])
    mode = (mode or os.environ.get("SO101_ROLLOUT_TIMING_MODE") or "detail").strip().lower()
    if mode not in ("detail", "light"):
        raise ValueError(f"SO101_ROLLOUT_TIMING_MODE는 detail 또는 light: {mode!r}")
    _state["meta"]["timing_mode"] = mode
    import lerobot.robots.so_follower.so_follower as SF
    import lerobot.rollout.inference.sync as SY
    from lerobot.cameras.opencv.camera_opencv import OpenCVCamera
    from lerobot.motors.motors_bus import SerialMotorsBus
    from lerobot.policies.act.modeling_act import ACTPolicy, ACTTemporalEnsembler
    from lerobot.rollout.robot_wrapper import ThreadSafeRobot
    from lerobot.rollout.strategies.base import BaseStrategy

    def timed(stage, fn, sync_dev=None, phase=None):
        def wrapper(*a, **kw):
            prev = _state["phase"]
            if phase:
                _state["phase"] = phase
            t0 = _now()
            try:
                r = fn(*a, **kw)
                if sync_dev is not None:
                    _sync(sync_dev(a, r))
                return r
            finally:
                _add(stage, _now() - t0)
                _state["phase"] = prev
        wrapper.__wrapped__ = fn
        return wrapper

    # 틱 경계: get_observation 시작 = 새 틱
    orig_get_obs = ThreadSafeRobot.get_observation

    def get_observation(self, *a, **kw):
        t = _now()
        if _state["in_run"]:
            cur = _state["cur"]
            if cur is not None:
                cur["tick"] = (t - cur["_t0"]) * 1000.0
                _state["ticks"].append({k: v for k, v in cur.items() if not k.startswith("_")})
            _state["cur"] = {"_t0": t}
        return timed("obs", orig_get_obs, phase="obs")(self, *a, **kw)

    ThreadSafeRobot.get_observation = get_observation
    ThreadSafeRobot.send_action = timed("send", ThreadSafeRobot.send_action, phase="send")

    orig_sync_read, orig_sync_write = SerialMotorsBus.sync_read, SerialMotorsBus.sync_write

    def sync_read(self, *a, **kw):
        t0 = _now()
        try:
            return orig_sync_read(self, *a, **kw)
        finally:
            _add("send_motor_read" if _state["phase"] == "send" else "obs_motor", _now() - t0)

    def sync_write(self, *a, **kw):
        t0 = _now()
        try:
            return orig_sync_write(self, *a, **kw)
        finally:
            if _state["phase"] == "send":
                _add("send_motor_write", _now() - t0)

    SerialMotorsBus.sync_read, SerialMotorsBus.sync_write = sync_read, sync_write
    OpenCVCamera.read_latest = timed("obs_camera", OpenCVCamera.read_latest)

    SY.SyncInferenceEngine.get_action = timed("engine", SY.SyncInferenceEngine.get_action)
    if mode == "light":
        _install_tail(SF, BaseStrategy)
        print(f"[so101-timing] 제어 루프 계측 켜짐(light: 추가 동기화 없음) → {_state['out']}", flush=True)
        return
    # 추론 엔진: 공식 sync.py가 이름으로 가져온 함수와 엔진 안의 전·후처리 객체를 감싼다
    SY.prepare_observation_for_inference = timed("to_tensor", SY.prepare_observation_for_inference)

    class _Timed:
        def __init__(self, inner, stage):
            self._inner, self._stage = inner, stage

        def __call__(self, *a, **kw):
            t0 = _now()
            try:
                return self._inner(*a, **kw)
            finally:
                _add(self._stage, _now() - t0)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    orig_engine_init = SY.SyncInferenceEngine.__init__

    def engine_init(self, *a, **kw):
        orig_engine_init(self, *a, **kw)
        self._preprocessor = _Timed(self._preprocessor, "preprocessor")
        self._postprocessor = _Timed(self._postprocessor, "postprocessor")
        _state["meta"]["engine_device"] = str(self._device)

    SY.SyncInferenceEngine.__init__ = engine_init

    def dev_of_result(a, r):
        try:
            return r.device.type
        except Exception:  # noqa: BLE001
            return None

    ACTPolicy.predict_action_chunk = timed("model", ACTPolicy.predict_action_chunk, sync_dev=dev_of_result)
    ACTTemporalEnsembler.update = timed("ensemble", ACTTemporalEnsembler.update, sync_dev=dev_of_result)
    _install_tail(SF, BaseStrategy)
    print(f"[so101-timing] 제어 루프 단계별 계측 켜짐(detail) → {_state['out']}", flush=True)


def _install_tail(SF, BaseStrategy) -> None:
    """두 모드 공통: 제한 비율, 실행 구간 표시, 종료 시 기록."""
    orig_ensure = SF.ensure_safe_goal_position

    def ensure_safe_goal_position(goal_present_pos, max_relative_target):
        safe = orig_ensure(goal_present_pos, max_relative_target)
        cur = _state["cur"]
        if cur is not None and _state["in_run"]:
            cur["clip"] = cur.get("clip", False) or any(abs(float(safe[k]) - float(g)) > 1e-6 for k, (g, _) in goal_present_pos.items())
        return safe

    SF.ensure_safe_goal_position = ensure_safe_goal_position

    orig_run = BaseStrategy.run

    def run(self, ctx, *a, **kw):
        _state["in_run"] = True
        try:
            return orig_run(self, ctx, *a, **kw)
        finally:
            _state["in_run"] = False
            _write()  # 시작 자세 복귀(teardown) 전에 기록

    BaseStrategy.run = run
    atexit.register(_write)
    _state["installed"] = True
