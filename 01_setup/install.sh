#!/bin/bash
# 설치 진입점. macOS arm64 → scripts/install_macos.sh, Linux → scripts/install.sh (옵션을 그대로 전달).
#   ./01_setup/install.sh              고정 버전 설치(다시 실행해도 안전: 정상 환경 재사용·누락 복구)
#   ./01_setup/install.sh --repair     캐시 없이 lock의 모든 패키지 재설치(파일 손상 의심 시)
#   ./01_setup/install.sh --reset-venv 재사용할 수 없는 .venv를 .venv.broken-<시각>으로 옮기고 새로 만듦
#   ./01_setup/install.sh --relock     [유지보수용] lock 재해결
set -euo pipefail
S="${BASH_SOURCE[0]}"; while [ -L "$S" ]; do D="$(cd "$(dirname "$S")" && pwd -P)"; S="$(readlink "$S")"; case "$S" in /*) ;; *) S="$D/$S" ;; esac; done
ROOT="$(cd "$(dirname "$S")/.." && pwd -P)"
. "$ROOT/scripts/entry_common.sh"
case "${1:-}" in -h|--help) sed -n '2,7p' "$S"; exit 0 ;; esac
case "$(uname -s)" in
  Darwin) exec "$ROOT/scripts/install_macos.sh" "$@" ;;
  Linux) exec "$ROOT/scripts/install.sh" "$@" ;;
  *) die "지원하지 않는 OS: $(uname -s)" ;;
esac
