#!/usr/bin/env python3
"""두 설치 환경(.venv)의 배포본·설치 파일 내용 비교(재현 검증용, 표준 라이브러리만 사용).

  python tools/compare_envs.py <A의 site-packages> <B의 site-packages> [--json out.json]

- 각 *.dist-info의 이름·버전을 비교한다.
- RECORD에 적힌 설치 파일을 직접 sha256으로 비교한다(RECORD의 해시 값 대신 실제 바이트).
- 경로가 들어가 설치 위치마다 달라지는 것은 '예상 차이'로 따로 센다: RECORD, direct_url.json,
  INSTALLER, REQUESTED, *.pyc, 그리고 site-packages 밖(bin/ console script shebang).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

EXPECTED_NAMES = {"RECORD", "direct_url.json", "INSTALLER", "REQUESTED", "uv_cache.json", "uv_build.json"}


def dists(site: Path) -> dict[str, tuple[str, Path]]:
    out = {}
    for d in site.glob("*.dist-info"):
        meta = (d / "METADATA").read_text(errors="replace")
        name = next((ln.split(":", 1)[1].strip() for ln in meta.splitlines() if ln.startswith("Name:")), d.name)
        ver = next((ln.split(":", 1)[1].strip() for ln in meta.splitlines() if ln.startswith("Version:")), "?")
        out[name.lower().replace("_", "-")] = (ver, d)
    return out


def files_of(site: Path, dist_info: Path) -> dict[str, str]:
    res = {}
    rec = dist_info / "RECORD"
    if not rec.is_file():
        return res
    for line in rec.read_text().splitlines():
        rel = line.rsplit(",", 2)[0]
        if not rel:
            continue
        p = (site / rel).resolve()
        res[rel] = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "<missing>"
    return res


def main(argv: list[str]) -> int:
    a, b = Path(argv[0]), Path(argv[1])
    da, db = dists(a), dists(b)
    report = {"only_a": sorted(set(da) - set(db)), "only_b": sorted(set(db) - set(da)), "version_diff": [],
              "content_same": 0, "content_diff": [], "expected_diff": 0, "files_compared": 0}
    for name in sorted(set(da) & set(db)):
        (va, ia), (vb, ib) = da[name], db[name]
        if va != vb:
            report["version_diff"].append((name, va, vb))
            continue
        fa, fb = files_of(a, ia), files_of(b, ib)
        same = True
        for rel in sorted(set(fa) | set(fb)):
            base = rel.rsplit("/", 1)[-1]
            if base in EXPECTED_NAMES or rel.endswith(".pyc") or rel.startswith("../"):
                if fa.get(rel) != fb.get(rel):
                    report["expected_diff"] += 1
                continue
            report["files_compared"] += 1
            if fa.get(rel) != fb.get(rel):
                same = False
                report["content_diff"].append(f"{name}: {rel}")
        report["content_same"] += same
    print(f"배포본 A {len(da)}개 / B {len(db)}개, A에만 {report['only_a']}, B에만 {report['only_b']}")
    print(f"버전 다름 {report['version_diff']}")
    print(f"설치 파일 내용이 모두 같은 배포본 {report['content_same']}/{len(set(da) & set(db))}, "
          f"비교한 파일 {report['files_compared']}개, 내용 다른 파일 {len(report['content_diff'])}개 {report['content_diff'][:5]}")
    print(f"예상 차이(설치 경로가 들어가는 RECORD·direct_url·INSTALLER·*.pyc·bin/): {report['expected_diff']}개")
    if "--json" in argv:
        Path(argv[argv.index("--json") + 1]).write_text(json.dumps(report, ensure_ascii=False, indent=1))
    ok = not (report["only_a"] or report["only_b"] or report["version_diff"] or report["content_diff"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
