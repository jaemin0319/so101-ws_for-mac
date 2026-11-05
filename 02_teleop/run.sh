#!/bin/bash
# 공식 lerobot-teleoperate 리더→팔로워 추종(사전 점검·현장 확인·종료 후 양팔 토크 해제 재시도·기록).
#   ./02_teleop/run.sh --dry-run          공식 명령·인자 파싱만(포트를 열지 않음)
#   ./02_teleop/run.sh --time-s 30        짧은 첫 시험(시간 상한)
#   ./02_teleop/run.sh                    시간 상한 없음(설정 teleop.time_s), 종료는 Ctrl+C
# 종료: 리더를 쉬는 자세로 → 팔로워를 받침 → Ctrl+C. 응답이 없으면 팔로워 전원 차단.
set -euo pipefail
S="${BASH_SOURCE[0]}"; while [ -L "$S" ]; do D="$(cd "$(dirname "$S")" && pwd -P)"; S="$(readlink "$S")"; case "$S" in /*) ;; *) S="$D/$S" ;; esac; done
ROOT="$(cd "$(dirname "$S")/.." && pwd -P)"
. "$ROOT/scripts/entry_common.sh"
case "${1:-}" in -h|--help) sed -n '2,6p' "$S"; exit 0 ;; esac
run_so101 teleop "$@"
