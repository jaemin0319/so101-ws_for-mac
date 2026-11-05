#!/bin/bash
# 카메라 확인(macOS). 카메라를 처음 열 때 macOS가 이 터미널 앱의 카메라 권한을 묻는다(사용자가 허용).
#   ./03_dataset/cameras.sh                  공식 lerobot-find-cameras opencv(모든 카메라 index·지원값, 확인용 사진 logs/에 저장)
#   ./03_dataset/cameras.sh --test front     configs/cameras.local.yaml의 front를 공식 OpenCVCamera로 읽기 시험(측정 FPS·사진)
#   ./03_dataset/cameras.sh --dry-run        명령·설정만 확인(카메라를 열지 않음)
set -euo pipefail
S="${BASH_SOURCE[0]}"; while [ -L "$S" ]; do D="$(cd "$(dirname "$S")" && pwd -P)"; S="$(readlink "$S")"; case "$S" in /*) ;; *) S="$D/$S" ;; esac; done
ROOT="$(cd "$(dirname "$S")/.." && pwd -P)"
. "$ROOT/scripts/entry_common.sh"
case "${1:-}" in -h|--help) sed -n '2,5p' "$S"; exit 0 ;; esac
run_so101 cameras "$@"
