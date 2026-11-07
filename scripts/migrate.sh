#!/usr/bin/env bash
# 같은 팔을 다른 맥에서 쓸 때: 보정 파일과 이 PC 설정을 묶음 파일 하나로 옮긴다(데이터셋·모델·토큰은 넣지 않는다).
#
#   bash scripts/migrate.sh export                 # → ~/Downloads/so101_local_bundle_<날짜>.tar.gz
#   bash scripts/migrate.sh import <묶음 파일>     # 이 작업 공간에 풀기(기존 파일은 calibration/backup/ 에 백업)
#
# 묶음에 들어가는 것: calibration/robots/**.json, calibration/teleoperators/**.json, config/so101.local.env
# 가져온 뒤에는 bash scripts/setup_local.sh 를 한 번 실행한다(카메라 번호는 맥마다 다를 수 있다).
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

cmd="${1:-}"; shift || true
case "$cmd" in
export)
    out="${1:-$HOME/Downloads/so101_local_bundle_$(date +%Y%m%d_%H%M%S).tar.gz}"
    files=()
    while IFS= read -r f; do files+=("$f"); done < <(cd "$SO101_WS" && find calibration/robots calibration/teleoperators -name '*.json' 2>/dev/null | sort)
    [ -f "$SO101_WS/config/so101.local.env" ] && files+=(config/so101.local.env)
    [ ${#files[@]} -gt 0 ] || so101_die "옮길 파일이 없다(보정 파일·config/so101.local.env 없음)"
    printf '  %s\n' "${files[@]}"
    so101_run tar -czf "$out" -C "$SO101_WS" "${files[@]}"
    [ "$SO101_DRY_RUN" = "1" ] || so101_log "묶음: $out  (새 맥에서: bash scripts/migrate.sh import $out)"
    ;;
import)
    bundle="${1:-}"; [ -f "$bundle" ] || so101_die "묶음 파일이 없다: ${bundle:-(지정 안 함)}"
    while IFS= read -r f; do
        case "$f" in
            /*|*..*) so101_die "묶음에 허용하지 않는 경로가 있다: $f (풀지 않음)" ;;
            calibration/robots/*.json|calibration/teleoperators/*.json|config/so101.local.env) ;;
            */) continue ;;
            *) so101_die "묶음에 예상하지 않은 파일이 있다: $f (풀지 않음)" ;;
        esac
        if [ -f "$SO101_WS/$f" ] && [ "$SO101_DRY_RUN" != "1" ]; then
            mkdir -p "$SO101_WS/calibration/backup"
            cp "$SO101_WS/$f" "$SO101_WS/calibration/backup/$(basename "$f").$(date +%Y%m%d_%H%M%S)"
            so101_log "기존 파일 백업: $f → calibration/backup/"
        fi
    done < <(tar -tzf "$bundle")
    so101_run tar -xzf "$bundle" -C "$SO101_WS"
    [ "$SO101_DRY_RUN" = "1" ] || so101_log "가져옴. 다음: bash scripts/setup_local.sh (포트·카메라 번호 확인)"
    ;;
*) so101_usage; exit 1 ;;
esac
