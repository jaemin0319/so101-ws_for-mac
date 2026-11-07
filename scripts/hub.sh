#!/usr/bin/env bash
# Hugging Face 데이터셋·모델 받기/올리기와 로컬 목록.
#
#   bash scripts/hub.sh login                                   # hf auth login (한 번만)
#   bash scripts/hub.sh whoami
#   bash scripts/hub.sh list                                    # 로컬 데이터셋·모델·학습 결과 목록
#
#   bash scripts/hub.sh download-dataset <repo_id> [--revision REV]
#       → data/hub/ (LeRobot 스냅샷 캐시. 이후 --dataset.repo_id=<repo_id> 만으로 찾는다)
#   bash scripts/hub.sh download-model <repo_id> [--revision REV] [--name DIR] [--step 100000] [--with-optimizer]
#       → models/<DIR>    (기본 DIR = repo 이름. optimizer 상태(training_state)는 기본으로 받지 않는다)
#
#   bash scripts/hub.sh upload-dataset <repo_id> [--private]    # data/<repo_id> 를 허브에 올림(v3.0 태그 포함)
#   bash scripts/hub.sh upload-model <경로|job_name> <repo_id> [--private]
#       경로: pretrained_model 폴더, 또는 outputs/train/<job> (→ checkpoints/last/pretrained_model)
#
# repo_id 에 '/' 가 없으면 config 의 HF_USER 를 앞에 붙인다(예: my_data → <HF_USER>/my_data). HF_USER 가 비어 있으면 로그인 계정.
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

usage() { so101_usage; exit "${1:-0}"; }

cmd="${1:-}"; [ -z "$cmd" ] && usage 1; shift

case "$cmd" in
-h|--help|help) usage 0 ;;

login)
    so101_run hf auth login
    ;;

whoami)
    u="$(so101_hf_whoami)"
    if [ -z "$u" ]; then echo "로그인 안 됨 → bash scripts/hub.sh login"; exit 1; fi
    echo "로그인 사용자: $u"
    [ "$u" != "$HF_USER" ] && so101_warn "config 의 HF_USER($HF_USER) 와 다르다. 업로드할 repo_id 를 확인한다."
    ;;

list)
    echo "== 데이터셋 (녹화: data/<user>/<name>, 허브에서 받은 것: data/hub/)"
    python - <<'PY'
import json, os, pathlib
root = pathlib.Path(os.environ["HF_LEROBOT_HOME"])
rows = []
for info in sorted(root.glob("*/*/meta/info.json")):
    d = info.parent.parent
    if d.relative_to(root).parts[0] in ("hub", "calibration"):
        continue
    rows.append(("local", str(d.relative_to(root)), info))
for info in sorted(root.glob("hub/datasets--*/snapshots/*/meta/info.json")):
    snap = info.parent.parent
    repo = snap.parent.parent.name.removeprefix("datasets--").replace("--", "/")
    rows.append(("hub", f"{repo} @ {snap.name[:8]}", info))
for kind, name, info in rows:
    j = json.loads(info.read_text())
    cams = [k.split(".")[-1] for k, v in j["features"].items() if v.get("dtype") == "video"]
    print(f"  [{kind:5}] {name}  episodes={j.get('total_episodes')} frames={j.get('total_frames')} fps={j.get('fps')} cams={cams}")
if not rows:
    print("  (없음)")
PY
    echo "== 모델 / 체크포인트 (config.json + model.safetensors 가 있는 폴더 = --policy.path 로 쓸 수 있음)"
    found=0
    for base in "$SO101_MODEL_DIR" "$SO101_OUTPUT_DIR/train"; do
        [ -d "$base" ] || continue
        while IFS= read -r f; do
            d="$(dirname "$f")"; [ -f "$d/config.json" ] || continue
            echo "  ${d#"$SO101_WS"/}"; found=1
        done < <(find "$base" -name model.safetensors -not -path "*/training_state/*" 2>/dev/null | sort)
    done
    [ $found = 0 ] && echo "  (없음)"
    ;;

download-dataset)
    [ $# -ge 1 ] || usage 1
    repo="$(so101_repo_id "$1")"; shift
    rev=""
    while [ $# -gt 0 ]; do
        case "$1" in --revision) rev="$2"; shift 2 ;; *) so101_die "알 수 없는 옵션: $1" ;; esac
    done
    # LeRobot 0.7 방식: 리비전 단위 스냅샷 캐시(data/hub/datasets--<user>--<name>/snapshots/<commit>)에 받는다.
    # (hf download --local-dir 로 받은 폴더는 LeRobot 이 legacy mirror 로 보고 무시하고 다시 받는다.)
    so101_log "다운로드: $repo ${rev:+(revision $rev)} → $HF_LEROBOT_HOME/hub"
    [ "$SO101_DRY_RUN" = "1" ] && exit 0
    python - "$repo" "$rev" <<'PY'
import sys
from lerobot.datasets import LeRobotDataset
repo, rev = sys.argv[1], sys.argv[2] or None
ds = LeRobotDataset(repo, revision=rev)
m = ds.meta
print(f"[완료] {ds.root}")
print(f"  codebase={m.info.codebase_version} robot={m.robot_type} episodes={m.total_episodes} frames={m.total_frames} fps={m.fps}")
print(f"  tasks={list(m.tasks.index) if hasattr(m.tasks, 'index') else m.tasks}")
for k, v in m.features.items():
    print(f"  - {k}: {v['dtype']} {v['shape']}")
PY
    echo "학습:  bash scripts/train.sh --dataset $repo --job <이름>"
    ;;

download-model)
    [ $# -ge 1 ] || usage 1
    repo="$(so101_repo_id "$1")"; shift
    rev=""; name="${repo##*/}"; step=""; with_opt=0
    while [ $# -gt 0 ]; do
        case "$1" in
            --revision) rev="$2"; shift 2 ;;
            --name) name="$2"; shift 2 ;;
            --step) step="$2"; shift 2 ;;
            --with-optimizer) with_opt=1; shift ;;
            *) so101_die "알 수 없는 옵션: $1" ;;
        esac
    done
    dest="$SO101_MODEL_DIR/$name"
    args=(hf download "$repo" --local-dir "$dest")
    [ -n "$rev" ] && args+=(--revision "$rev")
    [ -n "$step" ] && args+=(--include "checkpoints/$step/*" --include "README.md")
    [ $with_opt = 0 ] && args+=(--exclude "*/training_state/*")
    so101_run "${args[@]}"
    [ "$SO101_DRY_RUN" = "1" ] && exit 0
    echo "[완료] $dest"
    echo "추론에 쓸 수 있는 폴더(--policy.path):"
    find "$dest" -name model.safetensors -not -path "*/training_state/*" -exec dirname {} \; | sed 's/^/  /' | sort   # -printf 는 macOS find 에 없음
    echo "실행 예:  bash scripts/rollout.sh --policy <위 폴더> --task \"...\""
    ;;

upload-dataset)
    [ $# -ge 1 ] || usage 1
    repo="$(so101_repo_id "$1")"; shift
    private="None"
    while [ $# -gt 0 ]; do
        case "$1" in --private) private="True"; shift ;; *) so101_die "알 수 없는 옵션: $1" ;; esac
    done
    [ -f "$HF_LEROBOT_HOME/$repo/meta/info.json" ] || so101_die "로컬 데이터셋이 없다: $HF_LEROBOT_HOME/$repo  (bash scripts/hub.sh list)"
    [ -n "$(so101_hf_whoami)" ] || so101_die "Hugging Face 로그인이 필요하다: bash scripts/hub.sh login"
    so101_log "업로드: $HF_LEROBOT_HOME/$repo → https://huggingface.co/datasets/$repo"
    [ "$SO101_DRY_RUN" = "1" ] && exit 0
    python - "$repo" "$private" <<'PY'
import sys
from lerobot.datasets import LeRobotDataset
repo, private = sys.argv[1], {"True": True, "None": None}[sys.argv[2]]
ds = LeRobotDataset(repo)
ds.push_to_hub(private=private)
print(f"[완료] https://huggingface.co/datasets/{repo}")
PY
    ;;

upload-model)
    [ $# -ge 2 ] || usage 1
    src="$1"; repo="$(so101_repo_id "$2")"; shift 2
    private=0
    while [ $# -gt 0 ]; do
        case "$1" in --private) private=1; shift ;; *) so101_die "알 수 없는 옵션: $1" ;; esac
    done
    # job 이름 → outputs/train/<job>
    [ ! -e "$src" ] && [ -d "$SO101_OUTPUT_DIR/train/$src" ] && src="$SO101_OUTPUT_DIR/train/$src"
    [ -d "$src/checkpoints/last/pretrained_model" ] && src="$src/checkpoints/last/pretrained_model"
    [ -f "$src/model.safetensors" ] && [ -f "$src/config.json" ] || so101_die "pretrained_model 폴더가 아니다: $src"
    [ -n "$(so101_hf_whoami)" ] || so101_die "Hugging Face 로그인이 필요하다: bash scripts/hub.sh login"
    args=(hf upload "$repo" "$src" .)
    [ $private = 1 ] && args+=(--private)
    so101_run "${args[@]}"
    echo "[완료] https://huggingface.co/$repo"
    ;;

*) so101_warn "알 수 없는 명령: $cmd"; usage 1 ;;
esac
