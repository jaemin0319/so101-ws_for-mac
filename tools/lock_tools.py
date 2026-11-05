#!/usr/bin/env python3
"""유지보수용 lock 도구 (표준 라이브러리만 사용, Python 3.11+).

  constraints <official uv.lock> <out.txt>
      공식 LeRobot uv.lock에서 패키지별 버전을 resolver 입력 *제약*으로 뽑는다.
      - 한 패키지에 버전이 하나만 잠긴 경우만 `name==version`으로 쓴다(여러 버전이면 제외하고 주석으로 남김).
      - torch/torchvision의 로컬 꼬리표(+cu128)는 떼어 같은 공개 버전의 CPU 휠을 resolver가 고르게 한다.
      - nvidia-*/triton 같은 CUDA 전용 패키지는 제약에서 빼는 것이 아니라, CPU 휠이 요구하지 않으면 resolver가
        애초에 고르지 않는다. 제약은 "고르게 된다면 이 버전" 의미일 뿐이다.
      최종 lock(lock/uv.lock)은 이 제약을 받은 uv resolver가 만든다. 이 파일을 lock으로 쓰지 않는다.

  diff <official uv.lock> <our uv.lock> [--md]
      두 lock의 패키지/버전 차이를 출력한다(실제 비교 근거를 REFERENCES.md에 남기기 위함).

  check-macos <our macOS uv.lock>
      macOS arm64 lock 점검: 모든 파일의 sha256, PyPI 외 소스(경로·git·editable) 없음,
      휠 없는 패키지는 feetech-servo-sdk뿐, 휠이 있는 패키지는 cp312 macOS arm64에 설치 가능한 휠이 있음.

  hashes <official uv.lock> <our macOS uv.lock> [--md]
      공통 패키지(같은 이름·버전)의 cp312 macOS arm64 설치 대상 휠 sha256을 공식 lock과 비교한다.
"""
from __future__ import annotations

import re
import sys
import tomllib
from collections import defaultdict
from pathlib import Path

LOCAL_TAG_STRIP = {"torch", "torchvision"}


def load_versions(lock_path: Path) -> dict[str, list[str]]:
    data = tomllib.loads(lock_path.read_text())
    versions: dict[str, list[str]] = defaultdict(list)
    for pkg in data.get("package", []):
        name = pkg["name"]
        if "version" in pkg:
            versions[name].append(pkg["version"])
    return versions


def cmd_constraints(official: Path, out: Path) -> None:
    versions = load_versions(official)
    lines = [
        "# 공식 LeRobot uv.lock에서 생성한 resolver 입력 제약(tools/lock_tools.py constraints).",
        "# 최종 lock이 아니다. lock/uv.lock은 uv resolver가 이 제약과 lock/pyproject.toml로 만든다.",
    ]
    skipped = []
    for name in sorted(versions):
        vs = sorted(set(versions[name]))
        if name in LOCAL_TAG_STRIP:
            vs = sorted({v.split("+", 1)[0] for v in vs})
        if name == "lerobot":
            continue
        if len(vs) != 1:
            skipped.append(f"{name} ({', '.join(vs)})")
            continue
        lines.append(f"{name}=={vs[0]}")
    if skipped:
        lines.append("# 공식 lock에 여러 버전이 있어 제약에서 제외: " + "; ".join(skipped))
    out.write_text("\n".join(lines) + "\n")
    print(f"{out}: {len(lines) - 2} constraints, {len(skipped)} skipped")


def cmd_diff(official: Path, ours: Path, md: bool) -> None:
    off = load_versions(official)
    our = load_versions(ours)
    rows = []
    for name in sorted(n for n in set(our) if not n.startswith("so101-env")):  # 가상 프로젝트(so101-env, so101-env-macos) 제외
        o = sorted(set(off.get(name, [])))
        u = sorted(set(our[name]))
        if not o:
            rows.append((name, "-", ", ".join(u), "공식 lock에 없음"))
        elif u != o and not set(u) <= set(o):
            rows.append((name, ", ".join(o), ", ".join(u), "버전 다름"))
    if md:
        print("| 패키지 | 공식 uv.lock | lock/uv.lock | 차이 |")
        print("|---|---|---|---|")
        for r in rows:
            print("| " + " | ".join(r) + " |")
        if not rows:
            print("| (없음) | | | |")
    else:
        for r in rows:
            print("\t".join(r))
    print(f"\n# 우리 lock 패키지 수: {len([n for n in our if not n.startswith('so101-env')])}, 차이 항목: {len(rows)}", file=sys.stderr)


# ---- macOS arm64 lock 점검 --------------------------------------------------------------------
MAC_SDIST_ONLY_OK = {"feetech-servo-sdk"}
_WHEEL_RE = re.compile(r"^(?P<name>[^-]+)-(?P<ver>[^-]+)(-\d[^-]*)?-(?P<py>[^-]+)-(?P<abi>[^-]+)-(?P<plat>[^-]+)\.whl$")


def mac_arm64_cp312_ok(filename: str) -> bool:
    """휠 파일명 태그가 CPython 3.12 + macOS arm64(또는 universal2/any)에 설치 가능한지(보수적으로) 판정한다."""
    m = _WHEEL_RE.match(filename)
    if not m:
        return False
    pys, abis, plats = m["py"].split("."), m["abi"].split("."), m["plat"].split(".")
    # pip의 cp312 호환 태그: cp312, abi3(cp3X, X<=12), 순수 Python py3·py3X(X<=12).
    py_ok = any(t in ("py3", "cp312") or (t.startswith("py3") and t[3:].isdigit() and int(t[3:]) <= 12)
                or (t.startswith("cp3") and "abi3" in abis and t[3:].isdigit() and int(t[3:]) <= 12)
                for t in pys)
    abi_ok = any(a in ("none", "abi3", "cp312") for a in abis)
    plat_ok = False
    for pl in plats:
        if pl == "any":
            plat_ok = True
        pm = re.match(r"^macosx_(\d+)_(\d+)_(arm64|universal2)$", pl)
        if pm and int(pm.group(1)) <= 13:  # 설치기 최소 macOS 13 기준(platform.env MACOS_MIN)
            plat_ok = True
    return py_ok and abi_ok and plat_ok


def _packages(lock_path: Path) -> list[dict]:
    return tomllib.loads(lock_path.read_text()).get("package", [])


def cmd_check_macos(ours: Path) -> int:
    data = tomllib.loads(ours.read_text())
    problems: list[str] = []
    env = data.get("supported-markers") or data.get("resolution-markers") or []
    print("supported-markers:", env)
    if not env or any("darwin" not in e or "arm64" not in e for e in env):
        problems.append(f"lock 대상 환경이 macOS arm64 전용이 아님: {env}")
    sdist_only, n = [], 0
    for p in data.get("package", []):
        src = p.get("source", {})
        if "virtual" in src or "editable" in src:  # 가상 프로젝트 자신
            continue
        n += 1
        if set(src) != {"registry"} or "pypi.org" not in src.get("registry", ""):
            problems.append(f"{p['name']}: PyPI 레지스트리 외 소스 {src}")
        wheels = p.get("wheels", [])
        files = wheels + ([p["sdist"]] if "sdist" in p else [])
        if any(not str(f.get("hash", "")).startswith("sha256:") for f in files):
            problems.append(f"{p['name']}: sha256 없는 파일")
        if not wheels:
            sdist_only.append(p["name"])
        elif not any(mac_arm64_cp312_ok(w["url"].rsplit("/", 1)[-1]) for w in wheels):
            problems.append(f"{p['name']} {p['version']}: cp312 macOS arm64 설치 가능 휠 없음")
    print(f"패키지 {n}개(가상 프로젝트 제외), 휠 없는 패키지(소스 빌드): {sorted(sdist_only)}")
    if set(sdist_only) - MAC_SDIST_ONLY_OK:
        problems.append(f"feetech-servo-sdk 외 소스 빌드 패키지: {sorted(set(sdist_only) - MAC_SDIST_ONLY_OK)}")
    text = ours.read_text()
    for pat in ("file://", "/Users/", "/home/", "/mnt/", "editable = ", "directory = ", "path = "):
        if pat in text:
            problems.append(f"lock에 로컬 경로 흔적 '{pat}'")
    for pr in problems:
        print("[FAIL]", pr)
    print("[OK] macOS lock 점검 통과" if not problems else f"[FAIL] 문제 {len(problems)}건")
    return 1 if problems else 0


def _mac_wheels(p: dict) -> dict[str, str]:
    return {w["url"].rsplit("/", 1)[-1]: w["hash"] for w in p.get("wheels", []) if mac_arm64_cp312_ok(w["url"].rsplit("/", 1)[-1])}


def cmd_hashes(official: Path, ours: Path, md: bool) -> int:
    off: dict[tuple[str, str], dict] = {(p["name"], p.get("version", "")): p for p in _packages(official)}
    rows, same, mism, absent = [], 0, 0, 0
    for p in _packages(ours):
        src = p.get("source", {})
        if "virtual" in src or "editable" in src:
            continue
        key = (p["name"], p.get("version", ""))
        mine = _mac_wheels(p)
        o = off.get(key)
        if o is None:
            absent += 1
            rows.append((p["name"], p["version"], "공식 lock에 같은 버전 없음", ""))
            continue
        if "editable" in o.get("source", {}):  # 공식 lock에서는 lerobot이 프로젝트 자신(편집 설치)이라 휠 해시가 없다
            rows.append((p["name"], p["version"], "공식 lock에서는 프로젝트 자신(editable) — 비교 대상 아님",
                         "PyPI 휠 " + ", ".join(f"{f} {h}" for f, h in mine.items())))
            continue
        theirs = _mac_wheels(o)
        if not mine and not p.get("wheels"):  # sdist 전용
            sd_ok = p.get("sdist", {}).get("hash") == o.get("sdist", {}).get("hash")
            same += sd_ok
            mism += not sd_ok
            if not sd_ok:
                rows.append((p["name"], p["version"], "sdist 해시 다름", ""))
            continue
        diff = {f for f in set(mine) | set(theirs) if mine.get(f) != theirs.get(f)}
        if diff:
            mism += 1
            rows.append((p["name"], p["version"], "macOS arm64 휠 해시/목록 다름", ", ".join(sorted(diff))[:200]))
        else:
            same += 1
    if md:
        print("| 패키지 | 버전 | 결과 | 상세 |")
        print("|---|---|---|---|")
        for r in rows:
            print("| " + " | ".join(r) + " |")
        if not rows:
            print("| (차이 없음) | | | |")
    else:
        for r in rows:
            print("\t".join(r))
    print(f"# 공통 패키지 해시 일치 {same}, 다름 {mism}, 공식 lock에 같은 버전 없음 {absent}", file=sys.stderr)
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[0] == "constraints":
        cmd_constraints(Path(argv[1]), Path(argv[2]))
        return 0
    if len(argv) >= 3 and argv[0] == "diff":
        cmd_diff(Path(argv[1]), Path(argv[2]), "--md" in argv[3:])
        return 0
    if len(argv) >= 2 and argv[0] == "check-macos":
        return cmd_check_macos(Path(argv[1]))
    if len(argv) >= 3 and argv[0] == "hashes":
        return cmd_hashes(Path(argv[1]), Path(argv[2]), "--md" in argv[3:])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
