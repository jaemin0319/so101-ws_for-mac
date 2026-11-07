#!/usr/bin/env bash
# 시연 데이터 녹화 (lerobot-record). leader 로 follower 를 움직이며 front/wrist 카메라 + 관절값을 저장한다.
# 저장 위치: data/<HF_USER>/<NAME>  (repo_id = <HF_USER>/<NAME>)
#
#   bash scripts/record.sh --name <NAME> --task "<작업 설명>" [옵션] [-- lerobot-record 추가 인자...]
#
# 옵션
#   --name NAME           데이터셋 이름(필수). '/' 를 넣으면 그대로 repo_id 로 쓴다
#   --task TEXT           작업 설명(필수). 예: "Pick up the ball and place it in the bowl"
#   --episodes N          이번에 녹화할 에피소드 수 (기본 10)
#   --episode-time S      에피소드 길이(초). 기본 SO101_RECORD_EPISODE_TIME_S
#   --reset-time S        에피소드 사이 정리 시간(초). 기본 SO101_RECORD_RESET_TIME_S
#   --resume              이미 있는 데이터셋에 에피소드를 더 녹화(--episodes 는 "추가할" 개수)
#   --push                끝나면 허브에 업로드(로그인 필요). 기본은 로컬에만 저장
#   --private             --push 와 함께: 비공개 repo
#   --display             Rerun 창에 카메라·관절값 표시
#   --dry-run             명령만 출력
#
# 녹화 중 키: → 또는 n = 이번 에피소드 끝내고 다음 / ← 또는 r = 이번 에피소드 다시 / ESC 또는 q = 종료
#            (터미널이 포커스된 상태에서 누른다)
#
# 예
#   bash scripts/record.sh --name ball_to_bowl_v2 --task "Pick up the ball and place it in the bowl" --episodes 20
#   bash scripts/record.sh --name ball_to_bowl_v2 --task "Pick up the ball and place it in the bowl" --episodes 10 --resume
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

usage() { so101_usage; exit "${1:-0}"; }

name=""; task=""; episodes=10; ep_time="$SO101_RECORD_EPISODE_TIME_S"; reset_time="$SO101_RECORD_RESET_TIME_S"
resume=0; push=0; private=0; display=0; extra=()
while [ $# -gt 0 ]; do
    case "$1" in
        --name) name="$2"; shift 2 ;;
        --task) task="$2"; shift 2 ;;
        --episodes) episodes="$2"; shift 2 ;;
        --episode-time) ep_time="$2"; shift 2 ;;
        --reset-time) reset_time="$2"; shift 2 ;;
        --resume) resume=1; shift ;;
        --push) push=1; shift ;;
        --private) private=1; shift ;;
        --display) display=1; shift ;;
        --check|--dry-run) shift ;;  # _common.sh 가 처리
        -h|--help) usage 0 ;;
        --) shift; extra=("$@"); break ;;
        *) so101_die "알 수 없는 옵션: $1 (lerobot 인자는 -- 뒤에)" ;;
    esac
done
[ -n "$name" ] || so101_die "--name 이 필요하다"
[ -n "$task" ] || so101_die "--task 가 필요하다(학습·추론 때 같은 문장을 쓴다)"
repo="$(so101_repo_id "$name")"
root="$HF_LEROBOT_HOME/$repo"

case "${repo##*/}" in eval_*|rollout_*) so101_die "eval_/rollout_ 로 시작하는 이름은 정책 실행 기록용이다(scripts/rollout.sh --record)";; esac
if [ $resume = 1 ]; then
    [ -f "$root/meta/info.json" ] || [ "$SO101_DRY_RUN" = "1" ] || so101_die "이어서 녹화할 데이터셋이 없다: $root"
else
    if [ -e "$root" ] && [ "$SO101_DRY_RUN" != "1" ]; then
        so101_die "이미 있는 데이터셋: $root
  - 에피소드 추가: 같은 명령에 --resume 을 붙인다
  - 새로 녹화: 다른 --name 을 쓰거나 폴더를 지운다"
    fi
fi
if [ $push = 1 ] && [ "$SO101_DRY_RUN" != "1" ]; then
    u="$(so101_hf_whoami)"
    [ -n "$u" ] || so101_die "--push 에는 Hugging Face 로그인이 필요하다: bash scripts/hub.sh login"
    [ "${repo%%/*}" = "$u" ] || so101_warn "repo 소유자(${repo%%/*})와 로그인 사용자($u)가 다르다"
fi

so101_check_path "$SO101_FOLLOWER_PORT" "follower 포트"
so101_check_path "$SO101_LEADER_PORT" "leader 포트"
so101_check_cameras front wrist

cmd=(lerobot-record
    --robot.type="$SO101_ROBOT_TYPE" --robot.port="$SO101_FOLLOWER_PORT" --robot.id="$SO101_FOLLOWER_ID"
    --robot.cameras="$(so101_cameras front wrist)"
    --teleop.type="$SO101_TELEOP_TYPE" --teleop.port="$SO101_LEADER_PORT" --teleop.id="$SO101_LEADER_ID"
    --dataset.repo_id="$repo"
    --dataset.root="$root"
    --dataset.no_stamp=true
    --dataset.single_task="$task"
    --dataset.fps="$SO101_RECORD_FPS"
    --dataset.num_episodes="$episodes"
    --dataset.episode_time_s="$ep_time"
    --dataset.reset_time_s="$reset_time"
    --dataset.streaming_encoding=true
    --dataset.encoder_threads=2
)
if [ $push = 1 ]; then
    cmd+=(--dataset.push_to_hub=true)
    [ $private = 1 ] && cmd+=(--dataset.private=true)
else
    cmd+=(--dataset.push_to_hub=false)
fi
[ $resume = 1 ] && cmd+=(--resume=true)
[ $display = 1 ] && cmd+=(--display_data=true)
cmd+=("${extra[@]}")

so101_log "데이터셋: $repo → $root"
so101_run "${cmd[@]}"
[ "$SO101_DRY_RUN" = "1" ] && exit 0
so101_log "완료. 확인: bash scripts/hub.sh list | 재생: bash scripts/replay.sh --dataset $repo --episode 0"
so101_log "     학습: bash scripts/train.sh --dataset $repo --job act_${repo##*/}"
[ $push = 0 ] && so101_log "     업로드: bash scripts/hub.sh upload-dataset $repo"
exit 0
