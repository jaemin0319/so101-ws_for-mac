# shellcheck shell=bash
# 사용법(새 터미널마다):  source ~/so101-ws_for-mac/scripts/activate.sh   (bash, macOS 기본 셸 zsh 모두)
#   - conda 환경(config/so101.env 의 SO101_ENV_NAME)을 켜고
#   - config/so101.env 의 값을 환경 변수로 불러온다(HF_LEROBOT_HOME, HF_LEROBOT_CALIBRATION 포함).
# scripts/*.sh 는 이 파일을 알아서 불러오므로, 스크립트만 쓸 때는 따로 source 하지 않아도 된다.

if [ -n "${ZSH_VERSION:-}" ]; then
    eval '_so101_self="${(%):-%x}"'   # zsh: source 된 파일 경로
    _so101_shell=zsh
    case "${ZSH_EVAL_CONTEXT:-}" in *:file*) ;; *)
        echo "실행이 아니라 source 해야 한다: source $_so101_self" >&2; exit 1 ;; esac
elif [ -n "${BASH_VERSION:-}" ]; then
    _so101_self="${BASH_SOURCE[0]}"
    _so101_shell=bash
    if [ "${BASH_SOURCE[0]}" = "$0" ]; then
        echo "실행이 아니라 source 해야 한다: source ${BASH_SOURCE[0]}" >&2
        exit 1
    fi
else
    echo "activate.sh 는 bash 또는 zsh 에서 source 해야 한다: source ~/so101-ws_for-mac/scripts/activate.sh" >&2
    return 1 2>/dev/null || exit 1
fi

SO101_WS="$(cd "$(dirname "$_so101_self")/.." && pwd)"
export SO101_WS

# ---- 설정 불러오기: 기본값(config/so101.env) → 이 PC 값(config/so101.local.env, setup_local.sh 가 만듦) ----
set -a
# shellcheck source=../config/so101.env
. "$SO101_WS/config/so101.env"
if [ -f "$SO101_WS/config/so101.local.env" ]; then
    # shellcheck source=/dev/null
    . "$SO101_WS/config/so101.local.env"
fi
set +a

# ---- conda 환경 켜기 ----
if [ "${CONDA_DEFAULT_ENV:-}" != "$SO101_ENV_NAME" ]; then
    if ! command -v conda >/dev/null 2>&1 || ! type conda 2>/dev/null | grep -q function; then
        _so101_conda=""
        for _c in "${CONDA_EXE:-}" "$HOME/miniforge3/bin/conda" "$HOME/miniconda3/bin/conda" "$HOME/anaconda3/bin/conda"; do
            if [ -n "$_c" ] && [ -x "$_c" ]; then _so101_conda="$_c"; break; fi
        done
        if [ -z "$_so101_conda" ]; then
            echo "[activate] conda 를 찾지 못했다. Miniforge 를 설치하거나 CONDA_EXE 를 지정한다." >&2
            return 1
        fi
        eval "$("$_so101_conda" "shell.$_so101_shell" hook)"
        unset _so101_conda _c
    fi
    if ! conda activate "$SO101_ENV_NAME" 2>/dev/null; then
        echo "[activate] conda 환경 '$SO101_ENV_NAME' 이 없다. 먼저 설치: bash $SO101_WS/scripts/install.sh" >&2
        return 1
    fi
fi
unset _so101_self _so101_shell

if [ "${SO101_QUIET:-0}" != "1" ]; then
    echo "[so101-ws] conda env=$CONDA_DEFAULT_ENV  python=$(python -c 'import sys;print(sys.version.split()[0])')"
    echo "  workspace      : $SO101_WS"
    [ -f "$SO101_WS/config/so101.local.env" ] || echo "  (config/so101.local.env 없음 → bash scripts/setup_local.sh)"
    echo "  HF_USER        : ${HF_USER:-(비어 있음: 로그인 계정 사용)}"
    echo "  follower port  : $SO101_FOLLOWER_PORT (id=$SO101_FOLLOWER_ID)"
    echo "  leader port    : $SO101_LEADER_PORT (id=$SO101_LEADER_ID)"
    echo "  front camera   : $SO101_CAM_FRONT (rot=$SO101_CAM_FRONT_ROTATION)"
    echo "  wrist camera   : $SO101_CAM_WRIST (rot=$SO101_CAM_WRIST_ROTATION)"
    echo "  datasets       : $HF_LEROBOT_HOME"
    echo "  calibration    : $HF_LEROBOT_CALIBRATION"
fi
