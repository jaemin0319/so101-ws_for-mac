#!/bin/bash
# USB 포트 지정(macOS): 모터 전원 OFF·USB 모두 분리 → 리더 연결 → 팔로워 연결 순서로 안내하고,
# 장치 목록 차이로 포트를 찾아 configs/robot.local.yaml에 저장한다(확인·백업·원자적 저장). 포트를 열지 않는다.
#   ./01_setup/ports.sh              포트 지정 마법사
#   ./01_setup/ports.sh --list       현재 USB 시리얼 장치와 설정 매핑·USB 지문 대조(읽기 전용)
#   ./01_setup/ports.sh --find-port  공식 lerobot-find-port(USB를 뽑는 방식, 보조)
# 이 스크립트는 probe·모터 설정·보정·추종을 실행하지 않는다. 끝에 다음 명령을 출력한다.
set -euo pipefail
S="${BASH_SOURCE[0]}"; while [ -L "$S" ]; do D="$(cd "$(dirname "$S")" && pwd -P)"; S="$(readlink "$S")"; case "$S" in /*) ;; *) S="$D/$S" ;; esac; done
ROOT="$(cd "$(dirname "$S")/.." && pwd -P)"
. "$ROOT/scripts/entry_common.sh"
case "${1:-}" in
  -h|--help) sed -n '2,8p' "$S"; exit 0 ;;
  --list) run_so101 ports ;;
  --find-port) run_so101 find-port ;;
  '') run_so101 assign-ports ;;
  *) die "알 수 없는 옵션: $1 (--list, --find-port, --help)" ;;
esac
