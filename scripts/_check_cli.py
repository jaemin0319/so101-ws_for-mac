#!/usr/bin/env python
"""lerobot CLI 인자를 장치를 열지 않고 해석만 한다 (scripts/*.sh --check 가 사용).

  python scripts/_check_cli.py lerobot-rollout --robot.type=so101_follower ...

lerobot 이 실제로 쓸 설정(로봇·카메라·정책·데이터셋)을 출력하고, 인자 오류가 있으면 여기서 실패한다.
"""

import dataclasses
import importlib
import inspect
import json
import sys
from enum import Enum
from pathlib import Path


def to_plain(obj, depth=0):
    if depth > 6:
        return "..."
    if dataclasses.is_dataclass(obj):
        out = {}
        try:
            out["type"] = obj.type  # draccus ChoiceRegistry
        except Exception:
            pass
        for f in dataclasses.fields(obj):
            out[f.name] = to_plain(getattr(obj, f.name), depth + 1)
        return out
    if isinstance(obj, dict):
        return {str(k): to_plain(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_plain(v, depth + 1) for v in obj]
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return repr(obj)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    prog, cli_args = sys.argv[1], sys.argv[2:]
    mod = importlib.import_module("lerobot.scripts." + prog.replace("-", "_"))
    # @parser.wrap() 으로 감싼 진입 함수(이름 = 명령 이름, 예: lerobot-train → train)의 config 클래스
    want = prog.removeprefix("lerobot-").replace("-", "_")
    candidates = []
    for obj in vars(mod).values():
        inner = getattr(obj, "__wrapped__", None)
        if callable(inner) and getattr(obj, "__module__", "") == mod.__name__:
            spec = inspect.getfullargspec(inner)
            if spec.args and spec.args[0] in spec.annotations:
                candidates.append((inner.__name__, spec.annotations[spec.args[0]]))
    entry = next((c for n, c in candidates if n == want), candidates[0][1] if len(candidates) == 1 else None)
    if entry is None:
        print(f"[check] {prog}: 해석 점검을 지원하지 않는다(그대로 실행하면 된다)")
        return

    from lerobot.configs import parser

    def _echo(cfg):
        return cfg

    _echo.__annotations__ = {"cfg": entry}
    sys.argv = [prog, *cli_args]
    cfg = parser.wrap()(_echo)()

    plain = to_plain(cfg)
    keep = ["robot", "teleop", "policy", "dataset", "strategy", "inference", "task", "duration", "fps", "device",
            "display_data", "resume", "episode", "repo_id"]
    shown = {k: plain[k] for k in keep if isinstance(plain, dict) and k in plain}
    if "policy" in shown and isinstance(shown["policy"], dict):
        p = shown["policy"]
        shown["policy"] = {k: p.get(k) for k in ("type", "pretrained_path", "device", "chunk_size", "n_action_steps",
                                                  "temporal_ensemble_coeff", "input_features", "output_features")
                           if k in p}
    # so100_/so101_ 은 같은 클래스의 별칭이라 역조회하면 so100_ 으로 보인다 → CLI 에 준 이름으로 표시
    for key in ("robot", "teleop"):
        given = next((a.split("=", 1)[1] for a in cli_args if a.startswith(f"--{key}.type=")), None)
        if given and isinstance(shown.get(key), dict):
            shown[key]["type"] = given
    print(f"[check] {prog}: 인자 해석 OK ({entry.__name__})")
    print(json.dumps(shown, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
