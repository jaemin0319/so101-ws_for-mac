#!/bin/bash
# 이전 맥의 로컬 상태(보정 파일·로컬 설정)를 파일 하나로 묶어 새 맥으로 옮긴다. Git에는 올리지 않는다.
#
#   ./tools/migrate_local.sh export [출력.tar.gz]     # 이전 맥: 기본 ~/Downloads/so101_local_bundle_<날짜>.tar.gz
#   SO101_WS=<예전 작업 폴더> ./tools/migrate_local.sh export   # 이 도구가 없는 예전 폴더에서 꺼낼 때
#   ./tools/migrate_local.sh import <묶음.tar.gz>      # 새 맥: 저장소 폴더에 풀기(있는 파일은 덮어쓰지 않음)
#   ./tools/migrate_local.sh import <묶음.tar.gz> --force   # 다른 파일이 있으면 <파일>.bak-<시각>으로 백업 후 교체
#
# 포함: calibration/ (팔별 보정 JSON), configs/*.local.yaml (포트·팔 id·카메라·녹화 설정)
# 제외: 모델·데이터셋·로그·Hugging Face 토큰·.venv·.cache (토큰은 새 맥에서 직접 로그인)
# 보정 파일은 "같은 물리 팔"에서만 유효하다. 옮긴 뒤 ./01_setup/probe.sh both 로 'match'를 확인한다.
set -euo pipefail
S="${BASH_SOURCE[0]}"; while [ -L "$S" ]; do D="$(cd "$(dirname "$S")" && pwd -P)"; S="$(readlink "$S")"; case "$S" in /*) ;; *) S="$D/$S" ;; esac; done
# SO101_WS=<폴더>: 이 도구가 없는 예전 작업 폴더(예: 원래 so101-ws clone)에서 export할 때 그 폴더를 지정
WS="${SO101_WS:-$(cd "$(dirname "$S")/.." && pwd -P)}"
[ -d "$WS" ] || { echo "작업 폴더가 없습니다: $WS"; exit 2; }
usage() { awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$S"; }
cmd="${1:-}"
case "$cmd" in -h|--help|"") usage; [ -n "$cmd" ] && exit 0 || exit 2 ;; esac

if [ "$cmd" = export ]; then
  out="${2:-$HOME/Downloads/so101_local_bundle_$(date +%Y%m%d_%H%M%S).tar.gz}"
  cd "$WS"
  files=()
  [ -d calibration ] && while IFS= read -r f; do files+=("$f"); done < <(find calibration -type f -name '*.json' | sort)
  for f in configs/*.local.yaml; do [ -f "$f" ] && files+=("$f"); done
  [ ${#files[@]} -gt 0 ] || { echo "옮길 로컬 파일이 없습니다(calibration/, configs/*.local.yaml)."; exit 1; }
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
  for f in "${files[@]}"; do mkdir -p "$tmp/$(dirname "$f")"; cp -p "$f" "$tmp/$f"; done
  (cd "$tmp" && shasum -a 256 "${files[@]}" > MANIFEST.sha256)
  { echo "created=$(date '+%Y-%m-%dT%H:%M:%S%z')"; echo "files=${#files[@]}"; } > "$tmp/BUNDLE_INFO.txt"
  mkdir -p "$(dirname "$out")"
  tar -czf "$out" -C "$tmp" BUNDLE_INFO.txt MANIFEST.sha256 "${files[@]}"
  echo "[OK] 묶음: $out"
  printf '  %s\n' "${files[@]}"
  echo "새 맥에서: ./tools/migrate_local.sh import <이 파일>   (AirDrop·USB 등으로 옮기기. 토큰은 들어 있지 않음)"
  exit 0
fi

if [ "$cmd" = import ]; then
  src="${2:-}"; force="${3:-}"
  [ -f "$src" ] || { echo "묶음 파일이 없습니다: ${src:-<경로 필요>}"; exit 2; }
  [ -z "$force" ] || [ "$force" = --force ] || { echo "알 수 없는 옵션: $force"; exit 2; }
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
  tar -xzf "$src" -C "$tmp"
  [ -f "$tmp/MANIFEST.sha256" ] || { echo "MANIFEST.sha256이 없는 묶음입니다(export로 만든 파일인지 확인)."; exit 1; }
  (cd "$tmp" && shasum -a 256 -c --quiet MANIFEST.sha256) || { echo "[FAIL] 묶음 무결성 확인 실패"; exit 1; }
  list=()
  while IFS= read -r line; do list+=("${line#*  }"); done < "$tmp/MANIFEST.sha256"
  for f in "${list[@]}"; do
    case "$f" in calibration/*.json|configs/*.local.yaml) ;; *) echo "[FAIL] 예상 밖 경로가 들어 있음: $f"; exit 1 ;; esac
  done
  conflicts=()
  for f in "${list[@]}"; do
    if [ -f "$WS/$f" ] && ! cmp -s "$tmp/$f" "$WS/$f"; then conflicts+=("$f"); fi
  done
  if [ ${#conflicts[@]} -gt 0 ] && [ "$force" != --force ]; then
    echo "[중단] 내용이 다른 파일이 이미 있습니다(덮어쓰지 않음):"; printf '  %s\n' "${conflicts[@]}"
    echo "확인 후 교체하려면: ./tools/migrate_local.sh import \"$src\" --force   (기존 파일은 .bak-<시각>으로 백업)"
    exit 1
  fi
  ts="$(date +%Y%m%d_%H%M%S)"
  for f in "${list[@]}"; do
    mkdir -p "$WS/$(dirname "$f")"
    if [ -f "$WS/$f" ] && ! cmp -s "$tmp/$f" "$WS/$f"; then cp -p "$WS/$f" "$WS/$f.bak-$ts"; echo "  백업: $f.bak-$ts"; fi
    cp -p "$tmp/$f" "$WS/$f"; echo "  가져옴: $f"
  done
  echo "[OK] 로컬 상태를 가져왔습니다. 다음:"
  echo "  1) USB를 꽂고 ./01_setup/ports.sh  (포트 이름이 이 맥에서 다를 수 있음, 기존 id는 유지됨)"
  echo "  2) ./03_dataset/cameras.sh          (카메라 번호는 맥·허브마다 다름 → configs/cameras.local.yaml 확인)"
  echo "  3) ./01_setup/probe.sh both         (양팔 '보정 파일 상태: match'면 그대로 사용, mismatch면 ./01_setup/calibrate.sh)"
  exit 0
fi
echo "알 수 없는 명령: $cmd (export | import)"; exit 2
