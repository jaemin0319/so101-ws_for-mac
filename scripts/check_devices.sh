#!/usr/bin/env bash
# 장치 점검(장치를 열지 않음): 시리얼 포트·카메라 목록, 권한, config/so101.env 경로가 실제로 있는지.
#   bash scripts/check_devices.sh
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
set +e

ok()   { printf '  \033[32mOK\033[0m   %s\n' "$*"; }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$*"; fails=$((fails+1)); }
fails=0

IS_MAC=0; [ "$(uname -s)" = "Darwin" ] && IS_MAC=1

if [ $IS_MAC = 1 ]; then
    # macOS: dialout 그룹이 없다(사용자가 /dev/cu.* 를 바로 연다). 카메라는 OpenCV 번호로 쓴다.
    echo "== 시리얼 포트 (/dev/cu.usbmodem*, 이름 = 보드 시리얼 번호 + 1)"
    found=0
    for p in /dev/cu.usbmodem*; do [ -e "$p" ] || continue; echo "  $p"; found=1; done
    [ $found = 0 ] && echo "  (없음 — 팔 USB 가 연결되지 않음)"

    echo "== 카메라 (system_profiler, OpenCV 번호는 python scripts/cameras.py list)"
    cams="$(system_profiler SPCameraDataType 2>/dev/null | sed -n 's/^    \([^ ].*\):$/\1/p')"
    if [ -n "$cams" ]; then printf '%s\n' "$cams" | sed 's/^/  /'; else echo "  (없음)"; fi
else
    echo "== 사용자 그룹 (시리얼 포트 접근에 dialout 필요)"
    if id -nG | tr ' ' '\n' | grep -qx dialout; then ok "$(id -un) ∈ dialout"
    else bad "$(id -un) 이 dialout 그룹이 아니다 → sudo usermod -aG dialout $(id -un) 후 재로그인"; fi

    echo "== 시리얼 포트 (/dev/serial/by-id)"
    if ls /dev/serial/by-id/ >/dev/null 2>&1; then
        for p in /dev/serial/by-id/*; do echo "  $p -> $(readlink -f "$p")"; done
    else
        echo "  (없음 — 팔 USB 가 연결되지 않음)"
    fi

    echo "== 카메라 (/dev/v4l/by-path, video-index0)"
    found=0
    for p in /dev/v4l/by-path/*video-index0; do
        [ -e "$p" ] || continue
        case "$p" in *-usbv2-*) continue ;; esac
        dev="$(readlink -f "$p")"; name="$(cat "/sys/class/video4linux/$(basename "$dev")/name" 2>/dev/null)"
        echo "  $p -> $dev [$name]"; found=1
    done
    [ $found = 0 ] && echo "  (없음)"
fi

echo "== 설정한 장치 (config/so101.env + so101.local.env)"
chk() {
    local label="$1" path="$2"
    if [ -z "$path" ]; then bad "$label: 설정 안 됨 → bash scripts/setup_local.sh"; return; fi
    case "$path" in ''|*[!0-9]*) ;; *)   # 숫자 = OpenCV 카메라 번호(macOS): 장치 파일이 없다
        ok "$label: 카메라 번호 $path (맞는 카메라인지: python scripts/cameras.py snap)"; return ;; esac
    if [ -e "$path" ]; then
        if [ -r "$path" ] && [ -w "$path" ]; then ok "$label: $path"
        else bad "$label: $path (권한 없음: $(stat -c '%A %U:%G' "$(readlink -f "$path")" 2>/dev/null || stat -f '%Sp %Su:%Sg' "$path"))"; fi
    else bad "$label: $path (없음)"; fi
}
chk "follower" "$SO101_FOLLOWER_PORT"
chk "leader  " "$SO101_LEADER_PORT"
chk "front   " "$SO101_CAM_FRONT"
chk "wrist   " "$SO101_CAM_WRIST"

echo "== 보정 파일"
for f in "$HF_LEROBOT_CALIBRATION/robots/so_follower/$SO101_FOLLOWER_ID.json" \
         "$HF_LEROBOT_CALIBRATION/teleoperators/so_leader/$SO101_LEADER_ID.json"; do
    [ -f "$f" ] && ok "${f#"$SO101_WS"/}" || bad "${f#"$SO101_WS"/} 없음 → bash scripts/calibrate.sh"
done

echo "== 카메라를 쓰고 있는 프로세스"
if [ $IS_MAC = 1 ]; then
    echo "  (macOS: 확인 생략. 카메라를 연 다른 프로그램(카메라 창, 화상회의 등)을 닫는다)"
elif command -v fuser >/dev/null; then
    users="$(fuser /dev/video* 2>/dev/null)"
    [ -n "$users" ] && fuser -v /dev/video* 2>&1 | sed 's/^/  /' || echo "  (없음)"
fi

echo
[ $fails = 0 ] && echo "모두 OK" || echo "FAIL $fails 개 — 장치를 연결/전원 확인 후 다시 실행"
exit $fails
