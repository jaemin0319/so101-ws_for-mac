#!/usr/bin/env python3
"""ACT 체크포인트 → Core ML(GPU, FP32) 변환본 만들기(한 번만). 로봇·카메라를 쓰지 않는다.

  .venv/bin/python tools/act_coreml_export.py --checkpoint .cache/models/<모델>/checkpoints/<step>/pretrained_model [--force]

결과: .cache/coreml/<키>/{model.mlmodelc, manifest.json, probes.npz}
  키 = sha256(model.safetensors) + sha256(config.json) + 입력 shape + coremltools·torch 버전 + 변환 설정(scripts/so101_act_coreml.py)
  - FP32 명시(compute_precision=FLOAT32; mlprogram 기본은 FP16), compute_units=CPU_AND_GPU, convert_to=mlprogram, macOS15 대상
  - 정규화된 입력 → 정규화된 동작 묶음(공식 ACT.forward). 전처리·앙상블·후처리는 변환하지 않는다(rollout 공식 경로 그대로).
  - 검증 입력 4개(고정 seed)와 PyTorch CPU 참조 출력을 probes.npz에 저장하고, 변환본과의 최대 차이를 manifest에 기록한다.
    허용치(scripts/so101_act_coreml.PROBE_TOL)를 넘으면 실패로 끝낸다.
  - 연산 배치(MLComputePlan: GPU/CPU 연산 수)를 manifest에 기록한다.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WS / "scripts"))
import so101_act_coreml as C  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="ACT 체크포인트를 Core ML GPU FP32로 변환")
    ap.add_argument("--checkpoint", required=True, help="pretrained_model 폴더(model.safetensors·config.json)")
    ap.add_argument("--cache-root", default=str(C.CACHE_ROOT))
    ap.add_argument("--force", action="store_true", help="같은 키 변환본이 있어도 다시 만든다")
    a = ap.parse_args()

    import numpy as np
    import torch
    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.policies.act.modeling_act import ACTPolicy

    ct = C._import_ct()
    ckpt = Path(a.checkpoint).expanduser().resolve()
    cfg = PreTrainedConfig.from_pretrained(ckpt)
    if cfg.type != "act":
        print(f"[FAIL] ACT 체크포인트가 아님: type={cfg.type}")
        return 1
    cfg.device = "cpu"
    policy = ACTPolicy.from_pretrained(ckpt, config=cfg).to("cpu").eval()
    key = C.cache_key(ckpt, cfg, ct.__version__, torch.__version__)
    d = Path(a.cache_root) / key
    if (d / "manifest.json").is_file() and not a.force:
        print(f"이미 있음: {d} (다시 만들려면 --force)")
        return 0
    shapes = C.input_shapes(cfg)
    order = ["observation.state", *cfg.image_features]
    names = [C.INPUT_NAMES[0]] + [f"img{i}_{k.split('.')[-1]}" for i, k in enumerate(cfg.image_features)]
    model = C.wrap_model(policy.model, len(order) - 1)
    ex = [torch.zeros(shapes[k]) for k in order]
    tmp = d.with_name(d.name + ".partial")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    t0 = time.time()
    with torch.no_grad():
        traced = torch.jit.trace(model, tuple(ex))
    mlm = ct.convert(traced, inputs=[ct.TensorType(name=n, shape=x.shape) for n, x in zip(names, ex)],
                     compute_units=ct.ComputeUnit.CPU_AND_GPU, compute_precision=ct.precision.FLOAT32,
                     minimum_deployment_target=ct.target.macOS15, convert_to="mlprogram")
    convert_s = time.time() - t0
    out_name = list(mlm.get_spec().description.output)[0].name
    shutil.copytree(mlm.get_compiled_model_path(), tmp / "model.mlmodelc")
    # 검증 입력(정규화 단위, 고정 seed)과 PyTorch CPU 참조
    g = np.random.default_rng(1234)
    probes, worst = {}, 0.0
    cm = ct.models.CompiledMLModel(str(tmp / "model.mlmodelc"), compute_units=ct.ComputeUnit.CPU_AND_GPU)
    n_probe = 4
    for i in range(n_probe):
        xs = [(g.standard_normal(shapes[k]) * (1.0 if k == "observation.state" else 1.5)).astype(np.float32) for k in order]
        with torch.no_grad():
            ref = model(*[torch.from_numpy(x) for x in xs]).float().numpy()
        y = np.asarray(cm.predict({n: x for n, x in zip(names, xs)})[out_name], dtype=np.float32)
        worst = max(worst, float(np.abs(y - ref).max()))
        for j, x in enumerate(xs):
            probes[f"in{j}_{i}"] = x
        probes[f"ref_{i}"] = ref
    np.savez_compressed(tmp / "probes.npz", **probes)
    op_devices: dict | str = {}
    try:
        from coremltools.models.compute_plan import MLComputePlan

        cp = MLComputePlan.load_from_path(path=str(tmp / "model.mlmodelc"), compute_units=ct.ComputeUnit.CPU_AND_GPU)
        for op in cp.model_structure.program.functions["main"].block.operations:
            u = cp.get_compute_device_usage_for_mlprogram_operation(op)
            if u:
                n = type(u.preferred_compute_device).__name__
                op_devices[n] = op_devices.get(n, 0) + 1
    except Exception as e:  # noqa: BLE001
        op_devices = f"확인 실패 {type(e).__name__}"
    man = {"key": key, "convert_tag": C.CONVERT_TAG, "checkpoint": str(ckpt), "model_sha256": C._sha256(ckpt / "model.safetensors"),
           "config_sha256": C._sha256(ckpt / "config.json"), "coremltools": ct.__version__, "torch": torch.__version__,
           "input_order": order, "input_names": names, "input_shapes": [shapes[k] for k in order], "output_name": out_name,
           "chunk_size": cfg.chunk_size, "precision": "FLOAT32", "compute_units": "CPU_AND_GPU", "deployment_target": "macOS15",
           "op_devices": op_devices, "n_probes": n_probe, "probe_max_abs_vs_torch_cpu": worst, "tol": C.PROBE_TOL,
           "convert_s": round(convert_s, 1), "created": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    (tmp / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1))
    if worst > C.PROBE_TOL:
        print(f"[FAIL] 변환본이 PyTorch와 다름: 정규화 단위 최대 |Δ| {worst:.2e} > 허용 {C.PROBE_TOL:.0e}. 저장하지 않음({tmp})")
        return 1
    shutil.rmtree(d, ignore_errors=True)
    tmp.rename(d)
    print(f"[OK] Core ML 변환본: {d}\n     연산 배치 {op_devices}, 검증 |Δ| {worst:.2e}(허용 {C.PROBE_TOL:.0e}), 변환 {convert_s:.1f}s")
    if isinstance(op_devices, dict) and any(k != "MLGPUComputeDevice" for k in op_devices):
        print("[WARN] 일부 연산이 GPU가 아닌 장치에 배치됨. 지연 측정으로 확인하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
