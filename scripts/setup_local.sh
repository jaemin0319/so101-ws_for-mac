#!/usr/bin/env bash
# 이 PC 에 맞는 값을 찾아 config/so101.local.env 에 저장한다(Git 에 올라가지 않음). 여러 번 실행해도 안전하다.
#
#   bash scripts/setup_local.sh                      # 자동: Hugging Face 계정, 팔 포트(모터 전압으로 follower/leader 구분)
#   bash scripts/setup_local.sh --front 1 --wrist 0  # 카메라 번호 저장(python scripts/cameras.py snap --all 사진으로 확인)
#   bash scripts/setup_local.sh --follower /dev/cu.usbmodemXXXX --leader /dev/cu.usbmodemYYYY   # 포트 직접 지정
#   bash scripts/setup_local.sh --hf-user NAME       # Hugging Face 사용자 직접 지정
#   bash scripts/setup_local.sh --redetect           # 이미 저장된 포트도 다시 찾기
#   bash scripts/setup_local.sh --show               # 저장하지 않고 현재 값만 보기
#
# 팔 포트 자동 찾기는 읽기 전용이다(모터 전압 레지스터만 읽음, 모터가 움직이지 않음). 두 팔의 USB 와 전원이 연결돼 있어야 한다.
# 카메라는 두 대가 같은 모델이면 자동으로 구분할 수 없어 사진으로 확인해 번호를 정한다.
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

LOCAL="$SO101_WS/config/so101.local.env"
o_hf=""; o_fol=""; o_lead=""; o_front=""; o_wrist=""; redetect=0; show=0
while [ $# -gt 0 ]; do
    case "$1" in
        --hf-user) o_hf="$2"; shift 2 ;;
        --follower) o_fol="$2"; shift 2 ;;
        --leader) o_lead="$2"; shift 2 ;;
        --front) o_front="$2"; shift 2 ;;
        --wrist) o_wrist="$2"; shift 2 ;;
        --redetect) redetect=1; shift ;;
        --show) show=1; shift ;;
        --check|--dry-run) show=1; shift ;;
        -h|--help) so101_usage; exit 0 ;;
        *) so101_die "알 수 없는 옵션: $1 (--help)" ;;
    esac
done

hf="${o_hf:-${HF_USER:-}}"
fol="${o_fol:-${SO101_FOLLOWER_PORT:-}}"
lead="${o_lead:-${SO101_LEADER_PORT:-}}"
front="${o_front:-${SO101_CAM_FRONT:-}}"
wrist="${o_wrist:-${SO101_CAM_WRIST:-}}"
fourcc="${SO101_CAM_FOURCC:-}"
[ "$(uname -s)" = "Darwin" ] || fourcc="${fourcc:-MJPG}"   # Linux: 카메라 2대가 USB 2.0 허브를 같이 쓰면 MJPG 필요

# ---- Hugging Face 계정 ----
if [ -z "$hf" ]; then
    hf="$(so101_hf_whoami)"
    [ -n "$hf" ] && so101_log "Hugging Face 로그인 계정: $hf"
fi

# ---- 팔 포트 ----
port_ok() { [ -n "$1" ] && [ -e "$1" ]; }
if [ -z "$o_fol$o_lead" ] && { [ $redetect = 1 ] || ! port_ok "$fol" || ! port_ok "$lead"; }; then
    so101_log "팔 포트 찾기(읽기 전용, 모터 전압으로 follower/leader 구분)"
    json="$(python "$_SO101_SCRIPTS/find_arms.py" --json 2> >(sed 's/^/  /' >&2) | tail -1)"
    f2="$(printf '%s' "$json" | python -c 'import json,sys; d=json.loads(sys.stdin.read() or "{}"); print(d.get("follower") or "")' 2>/dev/null || true)"
    l2="$(printf '%s' "$json" | python -c 'import json,sys; d=json.loads(sys.stdin.read() or "{}"); print(d.get("leader") or "")' 2>/dev/null || true)"
    [ -n "$f2" ] && fol="$f2"
    [ -n "$l2" ] && lead="$l2"
fi
if [ "$(uname -s)" = "Darwin" ]; then
    for v in "$o_front" "$o_wrist"; do
        case "$v" in ''|*[!0-9]*) [ -z "$v" ] || so101_die "macOS 카메라 값은 번호(0, 1, ...): $v" ;; esac
    done
fi
[ -n "$front" ] && [ "$front" = "$wrist" ] && so101_die "front 와 wrist 카메라가 같은 번호($front)다"

# ---- 저장 ----
if [ $show = 0 ]; then
    [ -f "$LOCAL" ] && cp "$LOCAL" "$LOCAL.bak"
    cat > "$LOCAL" <<EOF
# 이 PC 전용 설정(scripts/setup_local.sh 가 $(date '+%Y-%m-%d %H:%M') 에 저장). Git 에 올라가지 않는다.
# config/so101.env 의 같은 이름 값을 덮어쓴다. 다시 만들기: bash scripts/setup_local.sh
HF_USER=$hf
SO101_FOLLOWER_PORT=$fol
SO101_LEADER_PORT=$lead
SO101_CAM_FRONT=$front
SO101_CAM_WRIST=$wrist
SO101_CAM_FOURCC=$fourcc
EOF
    # install.sh --env-name 으로 기본과 다른 conda 환경을 쓰는 경우 유지
    base_env="$(sed -n 's/^SO101_ENV_NAME=//p' "$SO101_WS/config/so101.env")"
    [ "$SO101_ENV_NAME" = "$base_env" ] || echo "SO101_ENV_NAME=$SO101_ENV_NAME" >> "$LOCAL"
    so101_log "저장: ${LOCAL#"$SO101_WS"/}"
fi

# ---- 요약·남은 일 ----
todo=0
item() { printf '  %s: %s\n' "$1" "$2"; }
echo
echo "== 이 PC 설정"
item "HF_USER" "${hf:-(없음)}"
item "follower 포트" "${fol:-(없음)}$(port_ok "$fol" || [ -z "$fol" ] || echo '  [지금 연결 안 됨]')"
item "leader 포트" "${lead:-(없음)}$(port_ok "$lead" || [ -z "$lead" ] || echo '  [지금 연결 안 됨]')"
item "front 카메라" "${front:-(없음)}"
item "wrist 카메라" "${wrist:-(없음)}"
fcal="$HF_LEROBOT_CALIBRATION/robots/so_follower/$SO101_FOLLOWER_ID.json"
lcal="$HF_LEROBOT_CALIBRATION/teleoperators/so_leader/$SO101_LEADER_ID.json"
item "보정 파일" "follower $([ -f "$fcal" ] && echo 있음 || echo 없음), leader $([ -f "$lcal" ] && echo 있음 || echo 없음)"
echo
echo "== 남은 일"
if [ -z "$hf" ]; then todo=1; echo "  - Hugging Face 로그인(업로드·비공개 데이터용, 사용자가 직접): bash scripts/hub.sh login → 다시 bash scripts/setup_local.sh"; fi
if [ -z "$fol" ] || [ -z "$lead" ]; then todo=1
    echo "  - 팔 포트: 두 팔의 USB 와 전원(follower 12V, leader 5V)을 연결하고 다시 bash scripts/setup_local.sh"
    echo "    (자동 구분이 안 되면: lerobot-find-port 로 하나씩 찾고 --follower/--leader 로 지정)"
fi
if [ -z "$front" ] || [ -z "$wrist" ]; then todo=1
    echo "  - 카메라 번호: python scripts/cameras.py snap --all → outputs/cameras/ 사진에서 front(작업면)·wrist(그리퍼) 번호 확인"
    echo "    → bash scripts/setup_local.sh --front <번호> --wrist <번호>"
fi
if [ ! -f "$fcal" ] || [ ! -f "$lcal" ]; then todo=1
    echo "  - 보정(팔을 직접 움직이는 작업, 사용자가 실행): bash scripts/calibrate.sh follower ; bash scripts/calibrate.sh leader"
    echo "    (다른 맥에서 쓰던 같은 팔이면 그 맥의 묶음을 가져와도 된다: bash scripts/migrate.sh import <묶음 파일>)"
fi
[ $todo = 0 ] && echo "  (없음) → 확인: bash scripts/check_devices.sh  /  텔레옵: bash scripts/teleop.sh"
exit 0
