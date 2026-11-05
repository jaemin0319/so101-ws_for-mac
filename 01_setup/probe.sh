#!/bin/bash
# 모터 읽기 전용 확인(공식 FeetechMotorsBus ping/read). 모터에 쓰지 않는다. 해당 팔의 전원이 켜져 있어야 한다.
#   ./01_setup/probe.sh follower|leader|both
#   ./01_setup/probe.sh follower --scan   응답이 없을 때만: 공식 scan_port(호스트 baud만 바꿔 broadcast ping)
set -euo pipefail
S="${BASH_SOURCE[0]}"; while [ -L "$S" ]; do D="$(cd "$(dirname "$S")" && pwd -P)"; S="$(readlink "$S")"; case "$S" in /*) ;; *) S="$D/$S" ;; esac; done
ROOT="$(cd "$(dirname "$S")/.." && pwd -P)"
. "$ROOT/scripts/entry_common.sh"
case "${1:-}" in -h|--help) sed -n '2,4p' "$S"; exit 0 ;; esac
need_role "${1:-}" follower leader both
role="$1"; shift
for a in "$@"; do case "$a" in --scan) ;; *) die "알 수 없는 옵션: $a" ;; esac; done
run_so101 probe "$role" "$@"
