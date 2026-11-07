#!/usr/bin/env bash
# 정책 학습 (lerobot-train). 결과: outputs/train/<job>/checkpoints/<step>/pretrained_model (+ last 링크)
#
#   bash scripts/train.sh --dataset <repo_id> --job <이름> [옵션] [-- lerobot-train 추가 인자...]
#
# 옵션
#   --dataset REPO      학습 데이터셋 repo_id (로컬 녹화 data/<repo_id> 또는 허브). 필수
#   --job NAME          결과 폴더 이름 outputs/train/<NAME>. 필수
#   --policy TYPE       act(기본) | diffusion | smolvla ...  (config 의 SO101_TRAIN_POLICY)
#   --from PATH|REPO    처음부터가 아니라 이 모델에서 이어서 학습(fine-tune). --policy 대신 쓴다
#   --steps N           기본 SO101_TRAIN_STEPS
#   --batch N           기본 SO101_TRAIN_BATCH_SIZE (8GB GPU 에서 ACT 8)
#   (장치는 자동: NVIDIA → cuda, Apple Silicon → mps, 없으면 cpu)
#   --save-freq N       체크포인트 저장 간격. 기본 SO101_TRAIN_SAVE_FREQ
#   --push REPO         학습이 끝나면 모델을 허브 REPO 에 올림(로그인 필요). 기본은 올리지 않음
#   --trackio           학습 곡선 기록(보기: trackio show --project lerobot)
#   --resume            outputs/train/<job> 의 마지막 체크포인트에서 이어서(같은 --job 필요)
#   --dry-run           명령만 출력
#
# 예
#   bash scripts/train.sh --dataset ball_to_bowl_v2 --job act_ball_v2          # = <HF_USER>/ball_to_bowl_v2
#   bash scripts/train.sh --dataset my_data --job act_my --steps 50000 --push my_act_policy
#   bash scripts/train.sh --job act_my --resume
#   bash scripts/train.sh --dataset my_data --job act_my2 -- --policy.chunk_size=50 --policy.n_action_steps=50
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

usage() { so101_usage; exit "${1:-0}"; }

dataset=""; job=""; policy="$SO101_TRAIN_POLICY"; from=""; steps="$SO101_TRAIN_STEPS"
batch="$SO101_TRAIN_BATCH_SIZE"; save_freq="$SO101_TRAIN_SAVE_FREQ"; push=""; trackio=0; resume=0
extra=()
while [ $# -gt 0 ]; do
    case "$1" in
        --dataset) dataset="$(so101_repo_id "$2")"; shift 2 ;;
        --job) job="$2"; shift 2 ;;
        --policy) policy="$2"; shift 2 ;;
        --from) from="$2"; shift 2 ;;
        --steps) steps="$2"; shift 2 ;;
        --batch) batch="$2"; shift 2 ;;
        --save-freq) save_freq="$2"; shift 2 ;;
        --push) push="$(so101_repo_id "$2")"; shift 2 ;;
        --trackio) trackio=1; shift ;;
        --resume) resume=1; shift ;;
        --check|--dry-run) shift ;;  # _common.sh 가 처리
        -h|--help) usage 0 ;;
        --) shift; extra=("$@"); break ;;
        *) so101_die "알 수 없는 옵션: $1 (lerobot 인자는 -- 뒤에)" ;;
    esac
done
[ -n "$job" ] || so101_die "--job 이 필요하다"
out="$SO101_OUTPUT_DIR/train/$job"
# NVIDIA GPU → cuda, Apple Silicon → mps, 둘 다 없으면 cpu
device="$(python -c "import torch; print('cuda' if torch.cuda.is_available() else ('mps' if torch.backends.mps.is_available() else 'cpu'))")"
[ "$device" = "cpu" ] && so101_warn "GPU(CUDA/MPS)를 못 찾아 CPU 로 학습한다(매우 느림)"

if [ $resume = 1 ]; then
    cfg="$out/checkpoints/last/pretrained_model/train_config.json"
    [ -f "$cfg" ] || [ "$SO101_DRY_RUN" = "1" ] || so101_die "이어서 할 체크포인트가 없다: $cfg"
    cmd=(lerobot-train --config_path="$cfg" --resume=true)
    cmd+=("${extra[@]}")
    so101_run "${cmd[@]}"
    exit
fi

[ -n "$dataset" ] || so101_die "--dataset 이 필요하다"
if [ -e "$out" ] && [ "$SO101_DRY_RUN" != "1" ]; then
    so101_die "이미 있는 결과 폴더: $out
  - 이어서 학습: bash scripts/train.sh --job $job --resume
  - 새로 학습: 다른 --job 이름을 쓰거나 폴더를 지운다"
fi
if [ -n "$push" ] && [ -z "$(so101_hf_whoami)" ] && [ "$SO101_DRY_RUN" != "1" ]; then
    so101_die "--push 에는 Hugging Face 로그인이 필요하다: bash scripts/hub.sh login"
fi

cmd=(lerobot-train
    --dataset.repo_id="$dataset"
    --output_dir="$out"
    --job_name="$job"
    --steps="$steps"
    --batch_size="$batch"
    --save_freq="$save_freq"
)
if [ -n "$from" ]; then
    [ -d "$from/checkpoints/last/pretrained_model" ] && from="$from/checkpoints/last/pretrained_model"
    cmd+=(--policy.path="$from")
else
    cmd+=(--policy.type="$policy")
fi
cmd+=(--policy.device="$device")
if [ -n "$push" ]; then
    cmd+=(--policy.push_to_hub=true --policy.repo_id="$push")
else
    cmd+=(--policy.push_to_hub=false)
fi
[ $trackio = 1 ] && cmd+=(--trackio.enable=true)
cmd+=("${extra[@]}")

so101_log "결과 폴더: $out"
so101_run "${cmd[@]}"
[ "$SO101_DRY_RUN" = "1" ] && exit 0
so101_log "완료. 추론: bash scripts/rollout.sh --policy $out --task \"...\""
so101_log "     오프라인 점검: python scripts/check_policy.py --policy $out --dataset $dataset"
