#!/usr/bin/env python3
"""ACT 추론 Core ML backend(선택형) — 같은 체크포인트 가중치를 Core ML GPU FP32로 실행한다.

docs/ACT_INFERENCE_OPTIMIZATION_PLAN.md 5절. 공식 LeRobot 파일은 수정하지 않는다.
바꾸는 것은 ACTPolicy.predict_action_chunk(정규화된 관측 → 정규화된 동작 묶음) 하나뿐이다. 전처리·정규화·select_action·
ACTTemporalEnsembler(계수 그대로)·reset·후처리·max_relative_target·카메라는 공식 경로 그대로다.

사용: tools/rollout_with_view.sh --backend=coreml ... --device=cpu
  1) 먼저 한 번 변환: .venv/bin/python tools/act_coreml_export.py --checkpoint <pretrained_model 경로>
     → .cache/coreml/<키>/model.mlmodelc + manifest.json(키 = 가중치·config sha256 + coremltools·torch 버전 + 변환 설정)
  2) scripts/so101_launch.py가 SO101_ACT_BACKEND=coreml이면 install()을 호출한다(모델 로드는 로봇 연결 전에 끝난다).
     ACTPolicy.from_pretrained 직후(제어 루프 밖): 장치(cpu) 확인 → 캐시 키 재계산·manifest 대조 → 컴파일본 로드 →
     워밍업 → 고정 검증 입력으로 Core ML 대 저장된 PyTorch 참조·현재 PyTorch 가중치 대조 → 통과하면 교체.
     하나라도 실패하면 예외로 시작을 거부한다(로봇 연결 전). 실행 중 오류가 나도 MPS/CPU로 조용히 대체하지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
CACHE_ROOT = WS / ".cache" / "coreml"
INPUT_NAMES = ("joint_state", "front", "wrist")  # 'state'는 Core ML 예약어라 바뀌므로 피한다
CONVERT_TAG = "fp32-cpu_and_gpu-mlprogram-macOS15"
PROBE_TOL = 1e-4  # 정규화 단위 chunk 최대 |Δ|. 실측 기준: Core ML 대 CPU 9.7e-6, CPU 대 MPS 1.2e-5(6에피소드 3,073틱)
_state = {"installed": False}


class CoreMLBackendError(RuntimeError):
    pass


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def image_keys(config) -> list[str]:
    return [k for k in config.input_features if k.startswith("observation.images.")]


def input_shapes(config) -> dict[str, list[int]]:
    """batch 1 고정 shape. 순서: 관절 상태, 이미지(설정의 image_features 순서 = 공식 forward의 카메라 순서)."""
    shp = {"observation.state": [1, *config.input_features["observation.state"].shape]}
    for k in config.image_features:
        shp[k] = [1, *config.input_features[k].shape]
    return shp


def cache_key(ckpt: Path, config, ct_version: str, torch_version: str) -> str:
    parts = [_sha256(ckpt / "model.safetensors"), _sha256(ckpt / "config.json"), json.dumps(input_shapes(config), sort_keys=True),
             ct_version, torch_version, CONVERT_TAG]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:20]


def wrap_model(model, n_images: int):
    """정규화된 (state, img1, img2, ...) → 정규화된 chunk. 공식 ACT.forward를 그대로 호출(추론 경로: VAE 잠재 0)."""
    import torch

    class Wrap(torch.nn.Module):
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, state, *imgs):
            return self.m({"observation.state": state, "observation.images": list(imgs)})[0]

    return Wrap(model).eval()


def _import_ct():
    import logging
    import warnings

    warnings.filterwarnings("ignore", module="coremltools")
    logging.getLogger("coremltools").setLevel(logging.ERROR)
    import coremltools as ct

    return ct


def attach(policy, ckpt: Path, cache_root: Path = CACHE_ROOT) -> dict:
    """정책 인스턴스에 Core ML backend를 붙인다. 실패하면 CoreMLBackendError(시작 거부)."""
    import numpy as np
    import torch

    cfg = policy.config
    dev = str(getattr(cfg, "device", "")).lower()
    if dev != "cpu":
        raise CoreMLBackendError(f"Core ML backend는 --device=cpu에서만 쓴다(현재 {dev!r}). 전·후처리·앙상블을 CPU에 두어 "
                                 "MPS 왕복을 없애기 위해서다. 명령의 --device=mps를 --device=cpu로 바꾸세요.")
    ckpt = Path(ckpt)
    if not (ckpt / "model.safetensors").is_file():
        raise CoreMLBackendError(f"체크포인트 폴더가 아님(로컬 pretrained_model 경로 필요): {ckpt}")
    try:
        ct = _import_ct()
    except ImportError as e:
        raise CoreMLBackendError(f"coremltools를 불러올 수 없음({e}). scripts/install_macos.sh로 lock을 다시 동기화하세요.") from e
    key = cache_key(ckpt, cfg, ct.__version__, torch.__version__)
    d = Path(cache_root) / key
    man_p, mlc = d / "manifest.json", d / "model.mlmodelc"
    export_cmd = f".venv/bin/python tools/act_coreml_export.py --checkpoint {ckpt}"
    if not man_p.is_file() or not mlc.is_dir():
        raise CoreMLBackendError(f"이 체크포인트·버전에 맞는 Core ML 변환본이 없음(키 {key}). 먼저 실행: {export_cmd}")
    man = json.loads(man_p.read_text())
    if man.get("key") != key or man.get("convert_tag") != CONVERT_TAG:
        raise CoreMLBackendError(f"변환본 manifest 불일치(키 {man.get('key')} ≠ {key}). 다시 변환: {export_cmd} --force")
    t0 = time.perf_counter()
    cm = ct.models.CompiledMLModel(str(mlc), compute_units=ct.ComputeUnit.CPU_AND_GPU)
    load_s = time.perf_counter() - t0
    names = man["input_names"]
    out_name = man["output_name"]
    probes = np.load(d / "probes.npz")

    def run_cm(arrs: list[np.ndarray]) -> np.ndarray:
        out = cm.predict({n: np.ascontiguousarray(a, dtype=np.float32) for n, a in zip(names, arrs)})
        return np.asarray(out[out_name], dtype=np.float32)

    n_probe = int(man["n_probes"])
    for _ in range(3):  # 워밍업(제어 루프 밖)
        run_cm([probes[f"in{j}_{0}"] for j in range(len(names))])
    worst_ref = 0.0
    for i in range(n_probe):
        y = run_cm([probes[f"in{j}_{i}"] for j in range(len(names))])
        worst_ref = max(worst_ref, float(np.abs(y - probes[f"ref_{i}"]).max()))
    # 현재 로드된 PyTorch 가중치로도 한 번 대조(캐시·체크포인트가 실제로 같은 모델인지)
    with torch.inference_mode():
        x = [torch.from_numpy(probes[f"in{j}_0"]) for j in range(len(names))]
        live = wrap_model(policy.model, len(names) - 1)(*x).float().cpu().numpy()
    worst_live = float(np.abs(run_cm([probes[f"in{j}_0"] for j in range(len(names))]) - live).max())
    if not (worst_ref <= PROBE_TOL and worst_live <= PROBE_TOL):
        raise CoreMLBackendError(f"Core ML 출력이 PyTorch와 다름(정규화 단위 최대 |Δ| 저장 참조 {worst_ref:.2e}, 현재 가중치 {worst_live:.2e}, "
                                 f"허용 {PROBE_TOL:.0e}). 시작하지 않습니다. 원인 확인 후 다시 변환: {export_cmd} --force")
    img_keys = list(cfg.image_features)

    def predict_action_chunk(batch):
        arrs = [batch["observation.state"].detach().cpu().numpy()] + [batch[k].detach().cpu().numpy() for k in img_keys]
        return torch.from_numpy(run_cm(arrs))

    policy._so101_coreml = predict_action_chunk
    info = {"backend": "coreml", "device": dev, "key": key, "load_s": round(load_s, 2), "op_devices": man.get("op_devices"),
            "probe_max_abs_vs_stored_ref": worst_ref, "probe_max_abs_vs_live_torch": worst_live, "tol": PROBE_TOL,
            "coremltools": ct.__version__, "torch": torch.__version__,
            "n_action_steps": cfg.n_action_steps, "temporal_ensemble_coeff": cfg.temporal_ensemble_coeff, "chunk_size": cfg.chunk_size}
    policy._so101_backend_info = info
    print(f"[so101-coreml] Core ML backend 켜짐: 키 {key}, 로드 {load_s:.2f}s, 연산 배치 {man.get('op_devices')}, "
          f"검증 |Δ| 저장참조 {worst_ref:.1e}·현재가중치 {worst_live:.1e} (허용 {PROBE_TOL:.0e}), 장치 {dev}, "
          f"chunk {cfg.chunk_size}, n_action_steps {cfg.n_action_steps}, 앙상블 계수 {cfg.temporal_ensemble_coeff}", flush=True)
    return info


def install(cache_root: str | os.PathLike | None = None) -> None:
    """ACTPolicy.from_pretrained 직후 attach(). predict_action_chunk는 클래스 수준에서 감싸 계측 훅(나중 설치)도 그대로 잴 수 있게 한다."""
    if _state["installed"]:
        return
    from lerobot.policies.act.modeling_act import ACTPolicy

    root = Path(cache_root or os.environ.get("SO101_COREML_CACHE") or CACHE_ROOT)
    orig_fp = ACTPolicy.from_pretrained.__func__

    def from_pretrained(cls, pretrained_name_or_path, *a, **kw):
        policy = orig_fp(cls, pretrained_name_or_path, *a, **kw)
        attach(policy, Path(pretrained_name_or_path), root)
        return policy

    ACTPolicy.from_pretrained = classmethod(from_pretrained)
    orig_pac = ACTPolicy.predict_action_chunk

    def predict_action_chunk(self, batch):
        f = getattr(self, "_so101_coreml", None)
        return f(batch) if f is not None else orig_pac(self, batch)

    ACTPolicy.predict_action_chunk = predict_action_chunk
    _state["installed"] = True
    print(f"[so101-coreml] ACT 추론 backend: Core ML GPU FP32(변환본 {root})", flush=True)


if __name__ == "__main__":
    sys.exit("직접 실행하지 않습니다. tools/act_coreml_export.py로 변환하고 rollout_with_view.sh --backend=coreml로 쓰세요.")
