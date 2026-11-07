#!/usr/bin/env bash
# 녹화한 에피소드의 action 을 follower 로 다시 재생 (lerobot-replay). leader 는 필요 없다.
#
#   bash scripts/replay.sh --dataset <repo_id> [--episode 0] [--dry-run]
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

dataset=""; episode=0; extra=()
while [ $# -gt 0 ]; do
    case "$1" in
        --dataset) dataset="$(so101_repo_id "$2")"; shift 2 ;;
        --episode) episode="$2"; shift 2 ;;
        --check|--dry-run) shift ;;  # _common.sh 가 처리
        -h|--help) so101_usage; exit 0 ;;
        --) shift; extra=("$@"); break ;;
        *) so101_die "알 수 없는 옵션: $1" ;;
    esac
done
[ -n "$dataset" ] || so101_die "--dataset 이 필요하다"
so101_check_path "$SO101_FOLLOWER_PORT" "follower 포트"
cmd=(lerobot-replay
    --robot.type="$SO101_ROBOT_TYPE" --robot.port="$SO101_FOLLOWER_PORT" --robot.id="$SO101_FOLLOWER_ID"
    --dataset.repo_id="$dataset" --dataset.episode="$episode")
# 로컬 녹화본이면 그 폴더를 직접 쓴다(허브 조회 안 함)
[ -f "$HF_LEROBOT_HOME/$dataset/meta/info.json" ] && cmd+=(--dataset.root="$HF_LEROBOT_HOME/$dataset")
cmd+=("${extra[@]}")
so101_run "${cmd[@]}"
