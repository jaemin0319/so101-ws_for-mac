#!/usr/bin/env bash
# leader → follower 원격 조작 (lerobot-teleoperate). Ctrl+C 로 종료.
#
#   bash scripts/teleop.sh                 # 팔만
#   bash scripts/teleop.sh --display       # 카메라(front, wrist)까지 열고 Rerun 창에 관절값·영상 표시
#   bash scripts/teleop.sh --cameras       # 카메라는 열지만 화면 표시는 안 함
#   bash scripts/teleop.sh --dry-run       # 명령만 출력
#   bash scripts/teleop.sh -- --fps=30     # -- 뒤는 lerobot-teleoperate 에 그대로 전달
#
# 주의: Ctrl+C 로 멈추면 follower 토크가 꺼져 팔이 힘없이 내려온다. 손으로 받친다.
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

cams=0; display=0; extra=()
while [ $# -gt 0 ]; do
    case "$1" in
        --display) display=1; cams=1; shift ;;
        --cameras) cams=1; shift ;;
        --check|--dry-run) shift ;;  # _common.sh 가 처리
        -h|--help) so101_usage; exit 0 ;;
        --) shift; extra=("$@"); break ;;
        *) so101_die "알 수 없는 옵션: $1" ;;
    esac
done

so101_check_path "$SO101_FOLLOWER_PORT" "follower 포트"
so101_check_path "$SO101_LEADER_PORT" "leader 포트"
cmd=(lerobot-teleoperate
    --robot.type="$SO101_ROBOT_TYPE" --robot.port="$SO101_FOLLOWER_PORT" --robot.id="$SO101_FOLLOWER_ID"
    --teleop.type="$SO101_TELEOP_TYPE" --teleop.port="$SO101_LEADER_PORT" --teleop.id="$SO101_LEADER_ID")
if [ $cams = 1 ]; then
    so101_check_cameras front wrist
    cmd+=(--robot.cameras="$(so101_cameras front wrist)")
fi
[ $display = 1 ] && cmd+=(--display_data=true)
cmd+=("${extra[@]}")
so101_run "${cmd[@]}"
