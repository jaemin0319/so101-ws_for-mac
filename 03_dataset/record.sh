#!/bin/bash
# 공식 lerobot-record로 로컬 데이터셋 녹화(리더·팔로워 추종을 함께 실행하므로 02_teleop/run.sh를 동시에 띄우지 않는다).
#   ./03_dataset/record.sh --dry-run                 설정·공식 인자·경로·공간 확인(포트·카메라를 열지 않음)
#   ./03_dataset/record.sh                           configs/recording.local.yaml + cameras.local.yaml로 녹화
#   ./03_dataset/record.sh --name NAME --task "..." --episodes 2   설정 파일 값 덮어쓰기
#   ./03_dataset/record.sh --resume --name NAME      기존 데이터셋에 이어서(--episodes는 추가 수)
#   ./03_dataset/record.sh ... --view                녹화 중 카메라 창(위 front / 아래 wrist). --mirror: 내보내기만(다른 터미널에서 창)
# 저장: datasets/<name>/ (공식 meta/·data/·videos/). Hub 업로드는 하지 않는다. 키: n=다음, r=다시, q=종료.
set -euo pipefail
S="${BASH_SOURCE[0]}"; while [ -L "$S" ]; do D="$(cd "$(dirname "$S")" && pwd -P)"; S="$(readlink "$S")"; case "$S" in /*) ;; *) S="$D/$S" ;; esac; done
ROOT="$(cd "$(dirname "$S")/.." && pwd -P)"
. "$ROOT/scripts/entry_common.sh"
case "${1:-}" in -h|--help) sed -n '2,8p' "$S"; exit 0 ;; esac
run_so101 record "$@"
