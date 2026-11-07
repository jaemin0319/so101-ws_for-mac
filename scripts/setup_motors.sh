#!/usr/bin/env bash
# 모터 ID·통신 속도 설정 (lerobot-setup-motors). 새 팔을 조립하거나 모터를 교체했을 때만 한다.
# 이미 조립·설정된 팔(ID 1~6)이면 필요 없다.
#
#   bash scripts/setup_motors.sh follower
#   bash scripts/setup_motors.sh leader
#   [--dry-run]
#
# lerobot 안내에 따라 gripper(6) → wrist_roll(5) → ... → shoulder_pan(1) 순서로
# 모터를 하나씩만 보드에 연결하고 Enter 를 누른다.
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

which="${1:-}"; shift || true
# --dry-run / --check 는 _common.sh 가 처리

case "$which" in
    follower) so101_check_path "$SO101_FOLLOWER_PORT" "follower 포트"
              so101_run lerobot-setup-motors --robot.type="$SO101_ROBOT_TYPE" --robot.port="$SO101_FOLLOWER_PORT" ;;
    leader)   so101_check_path "$SO101_LEADER_PORT" "leader 포트"
              so101_run lerobot-setup-motors --teleop.type="$SO101_TELEOP_TYPE" --teleop.port="$SO101_LEADER_PORT" ;;
    *) so101_usage; exit 1 ;;
esac
