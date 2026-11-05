#!/bin/bash
# 공식 LeRobotDataset으로 데이터셋을 다시 열어 검사(모터·카메라를 열지 않음).
#   ./03_dataset/inspect.sh datasets/<이름>                    형식·에피소드·프레임·timestamp·영상 디코드·NaN·task 검사
#   ./03_dataset/inspect.sh datasets/<이름> --write-manifest   + 이관용 sha256 목록·manifest(datasets/<이름>.sha256, .so101.json)
#   ./03_dataset/inspect.sh datasets/<이름> --no-decode        영상 디코드 생략(빠름)
#   ./03_dataset/inspect.sh datasets/<이름> --episodes 50-59   에피소드별 검사를 그 범위만(데이터셋 수준 검사는 전체)
set -euo pipefail
S="${BASH_SOURCE[0]}"; while [ -L "$S" ]; do D="$(cd "$(dirname "$S")" && pwd -P)"; S="$(readlink "$S")"; case "$S" in /*) ;; *) S="$D/$S" ;; esac; done
ROOT="$(cd "$(dirname "$S")/.." && pwd -P)"
. "$ROOT/scripts/entry_common.sh"
case "${1:-}" in -h|--help|'') sed -n '2,5p' "$S"; [ -n "${1:-}" ] && exit 0 || exit 2 ;; esac
run_so101 inspect "$@"
