#!/bin/bash
# 공식 lerobot-calibrate: 보정 파일이 없거나 모터 레지스터와 다를 때 실행한다(사람이 직접, 팔로워는 받친 채로).
#   ./01_setup/calibrate.sh follower|leader [--dry-run]
# 보정 파일: calibration/robots/so_follower/<id>.json, calibration/teleoperators/so_leader/<id>.json
set -euo pipefail
S="${BASH_SOURCE[0]}"; while [ -L "$S" ]; do D="$(cd "$(dirname "$S")" && pwd -P)"; S="$(readlink "$S")"; case "$S" in /*) ;; *) S="$D/$S" ;; esac; done
ROOT="$(cd "$(dirname "$S")/.." && pwd -P)"
. "$ROOT/scripts/entry_common.sh"
case "${1:-}" in -h|--help) sed -n '2,4p' "$S"; exit 0 ;; esac
need_role "${1:-}" follower leader
role="$1"; shift
for a in "$@"; do case "$a" in --dry-run) ;; *) die "알 수 없는 옵션: $a" ;; esac; done
run_so101 calibrate "$role" "$@"
