#!/usr/bin/env bash
# 팔 보정 (lerobot-calibrate). 결과는 calibration/ 의 JSON 에 저장된다.
#
#   bash scripts/calibrate.sh follower      # calibration/robots/so_follower/<FOLLOWER_ID>.json
#   bash scripts/calibrate.sh leader        # calibration/teleoperators/so_leader/<LEADER_ID>.json
#   [--dry-run]
#
# 진행(lerobot 안내를 따른다):
#   1) 팔을 모든 관절의 가운데 자세로 두고 Enter  → homing offset 기록
#   2) wrist_roll 을 뺀 모든 관절을 끝에서 끝까지 천천히 움직이고 Enter → range_min/max 기록
# 덮어쓰기 전에 기존 파일을 calibration/backup/ 에 복사해 둔다.
# 이미 보정 파일이 있으면 lerobot 이 "기존 파일 사용(Enter) / 새로 보정(c)" 을 묻는다.
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

which="${1:-}"; shift || true
# --dry-run / --check 는 _common.sh 가 처리

case "$which" in
    follower)
        port="$SO101_FOLLOWER_PORT"; id="$SO101_FOLLOWER_ID"
        file="$HF_LEROBOT_CALIBRATION/robots/so_follower/$id.json"
        args=(--robot.type="$SO101_ROBOT_TYPE" --robot.port="$port" --robot.id="$id") ;;
    leader)
        port="$SO101_LEADER_PORT"; id="$SO101_LEADER_ID"
        file="$HF_LEROBOT_CALIBRATION/teleoperators/so_leader/$id.json"
        args=(--teleop.type="$SO101_TELEOP_TYPE" --teleop.port="$port" --teleop.id="$id") ;;
    *) so101_usage; exit 1 ;;
esac

so101_check_path "$port" "$which 포트"
if [ -f "$file" ] && [ "$SO101_DRY_RUN" != "1" ]; then
    mkdir -p "$HF_LEROBOT_CALIBRATION/backup"
    bak="$HF_LEROBOT_CALIBRATION/backup/${id}_$(date +%Y%m%d_%H%M%S).json"
    cp "$file" "$bak"
    so101_log "기존 보정 파일 백업: $bak"
fi
so101_run lerobot-calibrate "${args[@]}"
[ "$SO101_DRY_RUN" = "1" ] || so101_log "보정 파일: $file"
