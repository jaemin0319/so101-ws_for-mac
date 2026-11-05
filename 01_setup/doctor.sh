#!/bin/bash
# 비구동 점검(장치를 열지 않음).
#   ./01_setup/doctor.sh             소프트웨어 점검(로봇·카메라 불필요)
#   ./01_setup/doctor.sh --hardware  + 설정·포트 경로·권한·점유·USB 지문·보정 파일(포트를 열지 않음)
# 종료 코드: 0=OK, 1=FAIL, 2=WARN만
set -euo pipefail
S="${BASH_SOURCE[0]}"; while [ -L "$S" ]; do D="$(cd "$(dirname "$S")" && pwd -P)"; S="$(readlink "$S")"; case "$S" in /*) ;; *) S="$D/$S" ;; esac; done
ROOT="$(cd "$(dirname "$S")/.." && pwd -P)"
. "$ROOT/scripts/entry_common.sh"
case "${1:-}" in
  -h|--help) sed -n '2,6p' "$S"; exit 0 ;;
  --hardware) shift; run_so101 doctor --scope hardware "$@" ;;
  '') run_so101 doctor ;;
  *) die "알 수 없는 옵션: $1 (--hardware 또는 --help)" ;;
esac
