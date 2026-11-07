#!/usr/bin/env bash
# 학습했거나 허브에서 받은 정책으로 follower 를 움직인다 (lerobot-rollout). Ctrl+C 로 종료.
#
#   bash scripts/rollout.sh --policy <모델> [옵션] [-- lerobot-rollout 추가 인자...]
#
# --policy 에 줄 수 있는 것
#   - outputs/train/<job> 또는 job 이름만   → checkpoints/last/pretrained_model
#   - models/<이름> 또는 이름만               → 그 안의 pretrained_model (여럿이면 가장 큰 step, --step 으로 선택)
#   - pretrained_model 폴더 경로
#   - 허브 repo_id (예: <HF_USER>/my_policy) → 허브 캐시로 받아서 실행
#
# 옵션
#   --step N              체크포인트 선택(예 100000, 020000)
#   --task TEXT           작업 문장. 비우면 학습 데이터셋의 첫 작업 문장을 찾아 쓴다(ACT 는 무시, SmolVLA 등은 필요)
#   --duration S          S 초 뒤 종료(기본 0 = 무제한)
#   --n-action-steps N    ACT 등: 한 번 추론한 chunk 중 N 개 실행 후 다시 추론(작을수록 반응 빠름)
#   --ensemble [C]        ACT temporal ensembling: 매 프레임 추론 후 가중 평균(계수 기본 0.01)
#   --record NAME         실행을 데이터셋으로 기록(<HF_USER>/rollout_<NAME>, episodic 전략)
#     --episodes N          기록할 에피소드 수(기본 10)
#     --episode-time S      에피소드 길이(기본 SO101_RECORD_EPISODE_TIME_S)
#     --reset-time S        에피소드 사이 정리 시간(기본 SO101_RECORD_RESET_TIME_S)
#     --push                끝나면 허브 업로드
#   --display             Rerun 창에 카메라·관절값·action 표시
#   --cpu                 GPU(CUDA/MPS) 대신 CPU
#   --check               로봇·카메라를 열지 않고 lerobot 이 해석한 설정만 출력
#   --dry-run             명령만 출력
#
# 예
#   bash scripts/rollout.sh --policy act_ball_to_bowl_v1 --step 100000
#   bash scripts/rollout.sh --policy models/act_so101_ball_to_bowl_v1 --ensemble
#   bash scripts/rollout.sh --policy my_act_job --n-action-steps 20 --duration 60
#   bash scripts/rollout.sh --policy my_act_job --record my_act_eval --episodes 10
# 멈추면 팔이 시작 자세로 천천히 돌아간다.
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

usage() { so101_usage; exit "${1:-0}"; }

policy=""; step=""; task=""; duration=0; nas=""; ens=""; record=""; episodes=10
ep_time="$SO101_RECORD_EPISODE_TIME_S"; reset_time="$SO101_RECORD_RESET_TIME_S"; push=0; display=0; device=""
extra=()
while [ $# -gt 0 ]; do
    case "$1" in
        --policy) policy="$2"; shift 2 ;;
        --step) step="$2"; shift 2 ;;
        --task) task="$2"; shift 2 ;;
        --duration) duration="$2"; shift 2 ;;
        --n-action-steps) nas="$2"; shift 2 ;;
        --ensemble)
            if [[ "${2:-}" =~ ^[0-9]*\.?[0-9]+$ ]]; then ens="$2"; shift 2; else ens="0.01"; shift; fi ;;
        --record) record="$2"; shift 2 ;;
        --episodes) episodes="$2"; shift 2 ;;
        --episode-time) ep_time="$2"; shift 2 ;;
        --reset-time) reset_time="$2"; shift 2 ;;
        --push) push=1; shift ;;
        --display) display=1; shift ;;
        --cpu) device="cpu"; shift ;;
        --check|--dry-run) shift ;;
        -h|--help) usage 0 ;;
        --) shift; extra=("$@"); break ;;
        *) so101_die "알 수 없는 옵션: $1 (lerobot 인자는 -- 뒤에)" ;;
    esac
done
[ -n "$policy" ] || so101_die "--policy 가 필요하다 (bash scripts/hub.sh list 로 목록 확인)"
[ -n "$nas" ] && [ -n "$ens" ] && so101_die "--n-action-steps 와 --ensemble 은 함께 쓸 수 없다"

# ---- 모델 경로 해석 ----
resolve_dir() {  # 폴더 → pretrained_model 폴더
    local d="$1" c
    if [ -f "$d/config.json" ] && [ -f "$d/model.safetensors" ]; then echo "$d"; return; fi
    if [ -n "$step" ]; then
        for c in "$d/checkpoints/$step/pretrained_model" "$d/checkpoints/$(printf '%06d' "$((10#$step))")/pretrained_model"; do
            [ -f "$c/config.json" ] && { echo "$c"; return; }
        done
        so101_die "체크포인트 $step 이 없다: $(ls "$d/checkpoints" 2>/dev/null | tr '\n' ' ')"
    fi
    if [ -f "$d/checkpoints/last/pretrained_model/config.json" ]; then echo "$d/checkpoints/last/pretrained_model"; return; fi
    c="$(find "$d" -path '*/pretrained_model/config.json' 2>/dev/null | sort | tail -1)"
    [ -n "$c" ] && { echo "$(dirname "$c")"; return; }
    so101_die "pretrained_model 을 찾지 못했다: $d"
}
if [ -d "$policy" ]; then
    ppath="$(resolve_dir "$(cd "$policy" && pwd)")"
elif [ -d "$SO101_OUTPUT_DIR/train/$policy" ]; then
    ppath="$(resolve_dir "$SO101_OUTPUT_DIR/train/$policy")"
elif [ -d "$SO101_MODEL_DIR/$policy" ]; then
    ppath="$(resolve_dir "$SO101_MODEL_DIR/$policy")"
elif [[ "$policy" == */* ]]; then
    # 허브 repo_id → models/<repo 이름> 으로 받은 뒤 그 폴더를 쓴다(optimizer 상태는 받지 않음)
    so101_log "허브 모델을 받는다(이미 있으면 빠진 파일만): $policy → $SO101_MODEL_DIR/${policy##*/}"
    if [ "$SO101_DRY_RUN" = "1" ] && [ "$SO101_CHECK" != "1" ]; then
        ppath="$SO101_MODEL_DIR/${policy##*/}/<pretrained_model>"
    else
        SO101_DRY_RUN=0 bash "$_SO101_SCRIPTS/hub.sh" download-model "$policy" ${step:+--step "$step"} >&2
        ppath="$(resolve_dir "$SO101_MODEL_DIR/${policy##*/}")"
    fi
else
    so101_die "모델을 찾지 못했다: $policy (bash scripts/hub.sh list)"
fi
if [ -d "$ppath" ]; then
    ptype="$(python -c "import json,sys;print(json.load(open(sys.argv[1]+'/config.json')).get('type',''))" "$ppath")"
    so101_log "정책: $ptype  $ppath"
fi

# ---- task: 비었으면 학습 데이터셋에서 찾기 ----
if [ -z "$task" ] && [ -f "$ppath/train_config.json" ]; then
    task="$(python - "$ppath/train_config.json" <<'PY' 2>/dev/null || true
import json, os, sys, pathlib
import pandas as pd
repo = json.load(open(sys.argv[1]))["dataset"]["repo_id"]
if isinstance(repo, list):
    repo = repo[0]
home = pathlib.Path(os.environ["HF_LEROBOT_HOME"])
cands = [home / repo / "meta/tasks.parquet"]
cands += sorted((home / "hub" / ("datasets--" + repo.replace("/", "--")) / "snapshots").glob("*/meta/tasks.parquet"))
for c in cands:
    if c.is_file():
        df = pd.read_parquet(c)
        print(df.index[0] if "task" not in df.columns else df["task"].iloc[0])
        break
PY
)"
    [ -n "$task" ] && so101_log "task(학습 데이터셋에서): $task"
fi
if [ -z "$task" ]; then
    case "${ptype:-}" in act|diffusion|vqbet|tdmpc|"") ;; *) so101_warn "$ptype 정책은 --task 문장이 필요할 수 있다" ;; esac
fi

if [ -z "$device" ]; then
    device="$(python -c "import torch; print('cuda' if torch.cuda.is_available() else ('mps' if torch.backends.mps.is_available() else 'cpu'))")"
fi

so101_check_path "$SO101_FOLLOWER_PORT" "follower 포트"
so101_check_cameras front wrist

cmd=(lerobot-rollout
    --policy.path="$ppath"
    --device="$device"
    --robot.type="$SO101_ROBOT_TYPE" --robot.port="$SO101_FOLLOWER_PORT" --robot.id="$SO101_FOLLOWER_ID"
    --robot.cameras="$(so101_cameras front wrist)"
    --fps="$SO101_CAM_FPS"
    --duration="$duration"
)
[ -n "$task" ] && cmd+=(--task="$task")
[ -n "$nas" ] && cmd+=(--policy.n_action_steps="$nas")
[ -n "$ens" ] && cmd+=(--policy.n_action_steps=1 --policy.temporal_ensemble_coeff="$ens")

if [ -n "$record" ]; then
    [ -n "$task" ] || so101_die "--record 에는 --task 가 필요하다"
    if [[ "$record" == */* ]]; then owner="${record%%/*}"; name="${record#*/}"; else owner="$HF_USER"; name="$record"; fi
    [[ "$name" == rollout_* ]] || name="rollout_$name"   # lerobot-rollout 규칙: 기록 데이터셋 이름은 rollout_ 로 시작
    repo="$owner/$name"
    root="$HF_LEROBOT_HOME/$repo"
    [ -e "$root" ] && [ "$SO101_DRY_RUN" != "1" ] && so101_die "이미 있는 기록 데이터셋: $root (다른 --record 이름 사용)"
    if [ $push = 1 ] && [ "$SO101_DRY_RUN" != "1" ] && [ -z "$(so101_hf_whoami)" ]; then
        so101_die "--push 에는 Hugging Face 로그인이 필요하다: bash scripts/hub.sh login"
    fi
    cmd+=(--strategy.type=episodic
        --dataset.repo_id="$repo" --dataset.root="$root" --dataset.no_stamp=true
        --dataset.single_task="$task"
        --dataset.num_episodes="$episodes" --dataset.episode_time_s="$ep_time" --dataset.reset_time_s="$reset_time"
        --dataset.push_to_hub="$([ $push = 1 ] && echo true || echo false)")
    so101_log "실행 기록: $repo → $root"
else
    cmd+=(--strategy.type=base)
fi
[ $display = 1 ] && cmd+=(--display_data=true)
cmd+=("${extra[@]}")
so101_run "${cmd[@]}"
