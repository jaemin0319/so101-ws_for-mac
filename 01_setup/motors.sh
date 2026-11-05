#!/bin/bash
# 공식 lerobot-setup-motors: 모터 ID(1~6)·baud를 EEPROM에 쓴다. probe에서 ID 누락·충돌이 확인된 팔만 실행한다.
#   ./01_setup/motors.sh follower|leader [--dry-run]
# 공식 프롬프트 순서(gripper부터)대로 모터 '하나만' 버스에 연결한다(그 모터에서 다음 모터로 가는 케이블도 분리).
# 케이블을 바꾸기 전에는 반드시 모터 전원을 끈다. 사람이 터미널에서 직접 실행한다.
set -euo pipefail
S="${BASH_SOURCE[0]}"; while [ -L "$S" ]; do D="$(cd "$(dirname "$S")" && pwd -P)"; S="$(readlink "$S")"; case "$S" in /*) ;; *) S="$D/$S" ;; esac; done
ROOT="$(cd "$(dirname "$S")/.." && pwd -P)"
. "$ROOT/scripts/entry_common.sh"
case "${1:-}" in -h|--help) sed -n '2,5p' "$S"; exit 0 ;; esac
need_role "${1:-}" follower leader
role="$1"; shift
for a in "$@"; do case "$a" in --dry-run) ;; *) die "알 수 없는 옵션: $a" ;; esac; done
run_so101 setup-motors "$role" "$@"
