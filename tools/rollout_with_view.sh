#!/bin/bash
# lerobot-rollout을 실행하면서, 정책이 받는 카메라 영상을 별도 창(위 front / 아래 wrist)으로 본다. macOS 전용.
#
#   ./tools/rollout_with_view.sh <lerobot-rollout 인자 그대로...>
#   예) ./tools/rollout_with_view.sh --strategy.type=base --policy.path=... --device=mps --robot.type=so101_follower ...
#   ./tools/rollout_with_view.sh --timing <인자...>    제어 루프 단계별 시간 계측(카메라·모터·전처리·추론·앙상블·전송) → logs/rollout-timing-*.json
#   ./tools/rollout_with_view.sh --timing=light ...    추가 동기화 없이 틱·관측·추론 전체·전송만 계측(전체 루프 성능용)
#   ./tools/rollout_with_view.sh --no-mirror <인자...> 영상 내보내기·창 모두 끔(계측 비교용, 공식 rollout과 같은 부하)
#   ./tools/rollout_with_view.sh --backend=coreml ... --device=cpu   ACT 추론을 Core ML GPU FP32로(같은 가중치, 먼저
#       .venv/bin/python tools/act_coreml_export.py --checkpoint <pretrained_model> 로 한 번 변환). 기본 --backend=mps(공식 그대로)
#   (래퍼 옵션 --no-view·--timing·--no-mirror·--backend는 lerobot-rollout 인자보다 앞에, 순서 무관)
#   ./tools/rollout_with_view.sh --no-view <인자...>   창은 띄우지 않고 영상만 내보냄. 다른 터미널에서 창만 띄운다:
#       swift tools/camera_view_dual.swift --mirror .tmp/live      (저장소 폴더에서)
#
# 카메라를 두 번 열지 않는다. 공식 lerobot-rollout 프로세스가 이미 읽은 프레임을 scripts/so101_camera_mirror.py가
# .tmp/live/<카메라 이름>.jpg로 1초에 약 10장 내보내고, 창(tools/camera_view_dual.swift --mirror)은 그 파일만 읽는다.
# (다른 프로그램이 같은 카메라를 열면 rollout의 카메라 프레임 크기가 바뀌어 읽기가 멈춘다 — 2026-10-14 실측)
# 공식 코드는 수정하지 않는다. scripts/so101_launch.py(부모 사망 감시)로 실행하고, 실행 중 유휴 절전을 막는다(caffeinate).
# Ctrl+C는 rollout에 그대로 전달된다(공식 종료: 시작 자세로 복귀 후 토크 해제). 창은 rollout이 끝나면 닫힌다.
# 창의 q/Esc는 창만 닫는다(rollout은 계속).
set -euo pipefail
WS="$(cd "$(dirname "$0")/.." && pwd -P)"
[ "$(uname -s)" = Darwin ] || { echo "macOS 전용입니다."; exit 1; }
VIEW=1
MIRROR=1
TIMING=""
TIMING_MODE=detail
BACKEND=""
while [ $# -gt 0 ]; do
  case "$1" in
    --no-view) VIEW=0; shift ;;
    --timing|--timing=detail) TIMING="$WS/logs"; TIMING_MODE=detail; shift ;;
    --timing=light) TIMING="$WS/logs"; TIMING_MODE=light; shift ;;
    --timing=*) echo "알 수 없는 계측 모드: $1 (--timing, --timing=light, --timing=detail)"; exit 2 ;;
    --no-mirror) MIRROR=0; VIEW=0; shift ;;
    --backend=mps|--backend=torch) BACKEND=""; shift ;;
    --backend=coreml) BACKEND=coreml; shift ;;
    --backend=*) echo "알 수 없는 backend: $1 (--backend=mps 또는 --backend=coreml)"; exit 2 ;;
    *) break ;;
  esac
done
[ $# -gt 0 ] || { sed -n '2,13p' "$0"; exit 2; }
if [ "$BACKEND" = coreml ]; then
  for x in "$@"; do
    case "$x" in --device=cpu) ;; --device=*) echo "--backend=coreml은 --device=cpu와 함께 씁니다(현재 $x)."; exit 2 ;; esac
  done
  case " $* " in *" --device=cpu "*) ;; *) echo "--backend=coreml은 --device=cpu를 명시해야 합니다."; exit 2 ;; esac
  # 공식 rollout은 --device(실행 장치)와 정책 설정의 policy.device를 따로 둔다. 정책 로드 시점에도 CPU이도록 맞춘다.
  case " $* " in
    *" --policy.device=cpu "*) ;;
    *" --policy.device="*) echo "--backend=coreml은 --policy.device=cpu여야 합니다(생략하면 자동으로 넣음)."; exit 2 ;;
    *) set -- "$@" --policy.device=cpu ;;
  esac
fi
LIVE="$WS/.tmp/live"
VIEW_BIN="$WS/.tmp/bin/camera_view_dual"
mkdir -p "$LIVE" "$WS/.tmp/bin"
rm -f "$LIVE"/*.jpg "$LIVE"/.*.jpg.tmp
VPID=""
if [ "$VIEW" = 1 ]; then
  if [ ! -x "$VIEW_BIN" ] || [ "$WS/tools/camera_view_dual.swift" -nt "$VIEW_BIN" ]; then
    echo "미리보기 창 빌드 중(처음 한 번, 수십 초)..."
    xcrun swiftc -O "$WS/tools/camera_view_dual.swift" -o "$VIEW_BIN"
  fi
  # 창과 caffeinate는 Ctrl+C를 무시한다(rollout이 시작 자세로 돌아가는 동안에도 계속 보이도록). rollout이 끝나면 정리한다.
  ( trap '' INT; exec "$VIEW_BIN" --mirror "$LIVE" ) > "$LIVE/viewer.log" 2>&1 &
  VPID=$!
fi
( trap '' INT; exec caffeinate -i -w $$ ) &
CPID=$!
cleanup() { kill $VPID "$CPID" 2>/dev/null || true; }
trap cleanup EXIT
trap 'true' INT   # 무시(SIG_IGN)가 아니라 빈 처리기: 자식(rollout)은 기본 SIGINT를 그대로 받는다
if [ "$VIEW" = 1 ]; then
  echo "카메라 창: 위 front / 아래 wrist (영상은 rollout이 카메라를 연 뒤 나타남). 종료는 Ctrl+C."
elif [ "$MIRROR" = 0 ]; then
  echo "영상 내보내기·창 없이 실행(--no-mirror)."
else
  echo "창 없이 실행(영상은 $LIVE 로 내보냄). 다른 터미널에서 창 띄우기:"
  echo "  swift $WS/tools/camera_view_dual.swift --mirror $LIVE"
fi
set +e
env -u PYTHONPATH -u PYTHONHOME -u LD_LIBRARY_PATH -u DYLD_LIBRARY_PATH -u DYLD_FALLBACK_LIBRARY_PATH -u DYLD_INSERT_LIBRARIES \
  HF_HOME="$WS/.cache/huggingface" HF_HUB_OFFLINE=1 HF_LEROBOT_CALIBRATION="$WS/calibration" TORCH_HOME="$WS/.cache/torch" \
  PYTHONNOUSERSITE=1 PYTHONUNBUFFERED=1 SO101_CAMERA_MIRROR="$([ "$MIRROR" = 1 ] && echo "$LIVE")" SO101_ROLLOUT_TIMING="$TIMING" SO101_ROLLOUT_TIMING_MODE="$TIMING_MODE" SO101_ACT_BACKEND="$BACKEND" \
  "$WS/.venv/bin/python" "$WS/scripts/so101_launch.py" $$ -- "${SO101_ROLLOUT_BIN:-$WS/.venv/bin/lerobot-rollout}" "$@"
rc=$?
set -e
echo "rollout 종료 코드: $rc"
exit $rc
