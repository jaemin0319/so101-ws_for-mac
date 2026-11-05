#!/bin/bash
# SO-101 macOS arm64(Apple Silicon) 환경 설치기. Linux는 scripts/install.sh를 쓴다(이 파일과 무관).
#   scripts/install_macos.sh            고정 버전 설치. 다시 실행하면 정상 환경을 재사용하고 누락·부분 설치를 복구한다.
#   scripts/install_macos.sh --repair   lock에 있는 모든 패키지를 캐시 없이 다시 받아 설치한다(파일 손상 의심 시).
#   scripts/install_macos.sh --reset-venv
#                                       재사용할 수 없는 .venv를 .venv.broken-<시각>으로 옮기고 새로 만든다(삭제하지 않음).
#   scripts/install_macos.sh --relock   [유지보수용] lock/macos-arm64/pyproject.toml로 uv.lock을 다시 해결하고 점검한 뒤 설치한다.
#
# 설치 기준: lock/lerobot.env(공통) + lock/macos-arm64/{platform.env,pyproject.toml,uv.lock}.
# 일반 설치는 `uv sync --locked`만 실행하며 lock을 재해결하지 않는다.
# 모든 다운로드·캐시·임시 파일·Python은 작업공간 안(.cache/, .tmp/, .tools/)에 둔다. 셸 설정·시스템 Python·Homebrew를 바꾸지 않는다.
# macOS 기본 /bin/bash 3.2와 BSD 도구로 동작하도록 작성했다(mapfile·${v,,}·GNU 전용 옵션 미사용).
set -euo pipefail

# 스크립트 위치 기준 작업공간(readlink -f에 의존하지 않고 심볼릭 링크를 따라간다).
resolve_script() {
  local p="$1" d
  while [[ -L "$p" ]]; do
    d="$(cd "$(dirname "$p")" && pwd -P)"
    p="$(readlink "$p")"
    [[ "$p" == /* ]] || p="$d/$p"
  done
  printf '%s' "$p"
}
SELF="$(resolve_script "${BASH_SOURCE[0]}")"
WS="$(cd "$(dirname "$SELF")/.." && pwd -P)"
cd "$WS"
LOCKDIR="$WS/lock/macos-arm64"

# ---- 실행 환경 격리(첫 다운로드 전에 적용) ----
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV CONDA_PREFIX DYLD_LIBRARY_PATH DYLD_FALLBACK_LIBRARY_PATH DYLD_INSERT_LIBRARIES || true
export PYTHONNOUSERSITE=1
export TMPDIR="$WS/.tmp"
export UV_CACHE_DIR="${SO101_UV_CACHE_DIR:-$WS/.cache/uv}"
export UV_PYTHON_INSTALL_DIR="$WS/.tools/python"
export UV_PYTHON_BIN_DIR="$WS/.tools/python-bin"   # --no-bin과 함께: 사용자 ~/.local/bin에 쓰지 않음
export UV_PYTHON_PREFERENCE=only-managed
export UV_PYTHON_DOWNLOADS=never                     # Python 설치 단계에서만 manual로 바꾼다
export UV_PROJECT_ENVIRONMENT="$WS/.venv"
# venv 파일을 캐시와 하드링크/클론으로 공유하지 않는다(설치본 손상이 캐시로 번지지 않게).
export UV_LINK_MODE=copy
export GIT_LFS_SKIP_SMUDGE=1
export HF_HOME="$WS/.cache/huggingface"
mkdir -p "$TMPDIR" "$UV_CACHE_DIR" "$WS/logs"
# 사용자 전역 git 설정에 git-lfs 필터가 required로 있어도(git-lfs 미설치) external/lerobot 작업이 실패하지 않게,
# 이 저장소 작업에만 필터를 끈다(~/.gitconfig는 수정하지 않음). LFS 파일은 포인터로 남으며 설치·검증에 쓰지 않는다.
GITX=(git -c filter.lfs.process= -c filter.lfs.smudge=cat -c filter.lfs.clean=cat -c filter.lfs.required=false)

MODE=install
RESET_VENV=0
for a in "$@"; do
  case "$a" in
    --repair) MODE=repair ;;
    --reset-venv) RESET_VENV=1 ;;
    --relock) MODE=relock ;;
    -h|--help) sed -n '2,13p' "$SELF"; exit 0 ;;
    *) echo "알 수 없는 옵션: $a  (scripts/install_macos.sh --help)" >&2; exit 2 ;;
  esac
done

log() { printf '[install-macos] %s\n' "$*"; }
die() { printf '[install-macos][FAIL] %s\n' "$*" >&2; exit 1; }

# KEY=VALUE만 읽는다(source하지 않음).
envget() {
  local f="$1" k="$2" v
  v="$(grep -E "^$k=" "$f" | tail -n1 | cut -d= -f2-)"
  [[ -n "$v" ]] || die "${f}에 $k 값이 없습니다."
  printf '%s' "$v"
}
LEROBOT_REPO="$(envget lock/lerobot.env LEROBOT_REPO)"
LEROBOT_SHA="$(envget lock/lerobot.env LEROBOT_SHA)"
LEROBOT_TAG="$(envget lock/lerobot.env LEROBOT_TAG)"
PYTHON_MINOR="$(envget lock/lerobot.env PYTHON_MINOR)"
UV_VERSION="$(envget lock/lerobot.env UV_VERSION)"
UV_ASSET="$(envget "$LOCKDIR/platform.env" UV_ASSET)"
UV_SHA256="$(envget "$LOCKDIR/platform.env" UV_SHA256)"
PYTHON_VERSION="$(envget "$LOCKDIR/platform.env" PYTHON_VERSION)"
MACOS_MIN="$(envget "$LOCKDIR/platform.env" MACOS_MIN)"
UV="$WS/.tools/uv/uv"
[[ "$PYTHON_VERSION" == "$PYTHON_MINOR".* ]] || die "PYTHON_VERSION($PYTHON_VERSION)이 PYTHON_MINOR($PYTHON_MINOR)와 맞지 않습니다."

# 설치 중 필요한 최소 여유 공간(MB). 실측(docs/macos_setup_report.md)에 여유를 더한 값.
REQUIRED_FREE_MB="${SO101_REQUIRED_FREE_MB:-4000}"

# ---- 0. 사전 점검 ----
log "작업공간: $WS"
[[ "$(uname -s)" == Darwin ]] || die "macOS 전용 설치기입니다. Linux는 scripts/install.sh를 쓰세요."
[[ "$(uname -m)" == arm64 ]] || die "Apple Silicon(arm64) 전용입니다(현재 $(uname -m))."
if [[ "$(sysctl -n sysctl.proc_translated 2>/dev/null || echo 0)" == 1 ]]; then
  die "Rosetta(x86_64 번역)로 실행 중입니다. native arm64 터미널에서 실행하세요."
fi
macv="$(sw_vers -productVersion)"
ver_ge() {  # $1 >= $2 (점 구분 숫자)
  local IFS=.
  local a=($1) b=($2) i
  for i in 0 1 2; do
    local x="${a[$i]:-0}" y="${b[$i]:-0}"
    if (( x > y )); then return 0; fi
    if (( x < y )); then return 1; fi
  done
  return 0
}
ver_ge "$macv" "$MACOS_MIN" || die "macOS $MACOS_MIN 이상이 필요합니다(현재 $macv)."
log "macOS $macv arm64(native)"
for f in "${XDG_CONFIG_HOME:-$HOME/.config}/uv/uv.toml" /etc/uv/uv.toml; do
  [[ -e "$f" ]] && log "경고: uv 사용자/시스템 설정 $f 이 있습니다. 인덱스 등 설정이 lock 설치에 섞이지 않는지 확인하세요."
done
for c in git curl tar shasum df sysctl sw_vers; do command -v "$c" >/dev/null || die "필수 명령 '$c'이(가) 없습니다."; done
git --version >/dev/null 2>&1 || die "git이 동작하지 않습니다. Xcode Command Line Tools가 필요합니다: xcode-select --install (사용자가 직접 실행)"
avail_mb="$(df -Pm "$WS" | awk 'NR==2{print $4}')"
log "여유 공간: ${avail_mb} MB ($(df -P "$WS" | awk 'NR==2{print $6}'))"
if [[ ! -x "$WS/.venv/bin/python" && "$avail_mb" -lt "$REQUIRED_FREE_MB" ]]; then
  die "여유 공간이 ${REQUIRED_FREE_MB} MB보다 적습니다. 공간을 확보한 뒤 다시 실행하세요."
fi

sha_check() {  # $1=sha256 $2=file
  if command -v sha256sum >/dev/null 2>&1; then
    echo "$1  $2" | sha256sum -c --quiet -
  else
    echo "$1  $2" | shasum -a 256 -c --quiet -
  fi
}

# ---- 1. uv 고정 바이너리 ----
uv_ok() { [[ -x "$UV" ]] && [[ "$("$UV" --version 2>/dev/null | awk '{print $2}')" == "$UV_VERSION" ]]; }
if uv_ok; then
  log "uv $UV_VERSION 재사용"
else
  log "uv $UV_VERSION 내려받기(체크섬 검증)"
  dl="$TMPDIR/dl"; mkdir -p "$dl"
  rm -f "$dl/$UV_ASSET"
  curl -fsSL --retry 3 -o "$dl/$UV_ASSET" "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/$UV_ASSET" \
    || die "uv 다운로드 실패. 네트워크 확인 후 다시 실행하세요."
  sha_check "$UV_SHA256" "$dl/$UV_ASSET" || die "uv 체크섬 불일치. 파일을 사용하지 않습니다: $dl/$UV_ASSET"
  top="$(tar -tzf "$dl/$UV_ASSET" | head -n1)"
  [[ "$top" == "${UV_ASSET%.tar.gz}/" ]] || die "uv 아카이브 구조가 예상과 다릅니다(최상위 '$top')."
  rm -rf "$WS/.tools/uv.new"; mkdir -p "$WS/.tools/uv.new"
  tar -xzf "$dl/$UV_ASSET" -C "$WS/.tools/uv.new" --strip-components=1
  if [[ -e "$WS/.tools/uv" ]]; then mv "$WS/.tools/uv" "$WS/.tools/uv.old-$(date +%Y%m%d_%H%M%S)"; fi
  mv "$WS/.tools/uv.new" "$WS/.tools/uv"
  uv_ok || die "uv 설치 확인 실패"
fi

# ---- 2. uv managed Python(작업공간 .tools/python) ----
# UV_PYTHON_PREFERENCE=only-managed + UV_PYTHON_INSTALL_DIR로 작업공간 managed Python만 찾는다
# (--managed-python 플래그는 이 환경변수와 함께 쓸 수 없음). --system: 작업공간 .venv를 찾지 않고 기반 인터프리터를 찾는다.
py_find() { "$UV" python find --system "$PYTHON_VERSION" 2>/dev/null || true; }
py_ok() {
  local p="$1"
  [[ -n "$p" && -x "$p" ]] || return 1
  "$p" -I - "$PYTHON_VERSION" "$WS/.tools/python" <<'EOF' >/dev/null 2>&1
import sys, platform, os, ssl, sqlite3, ctypes, zlib, hashlib  # 표준 확장 모듈 로드 확인
want, root = sys.argv[1], os.path.realpath(sys.argv[2])
assert platform.python_version() == want, platform.python_version()
assert platform.machine() == "arm64", platform.machine()
assert os.path.realpath(sys.base_prefix).startswith(root + os.sep), sys.base_prefix
assert sys.prefix == sys.base_prefix, "venv 인터프리터가 아니라 managed 기반 인터프리터여야 함"
EOF
}
PYSYS="$(py_find)"
if py_ok "$PYSYS"; then
  log "Python $PYTHON_VERSION(managed) 재사용: $PYSYS"
else
  reinstall=()
  [[ -n "$PYSYS" ]] && { log "Python $PYTHON_VERSION 설치본이 손상되었거나 확인에 실패했습니다 → 다시 설치합니다."; reinstall=(--reinstall); }
  log "Python $PYTHON_VERSION 내려받기(uv managed, .tools/python, --no-bin)"
  UV_PYTHON_DOWNLOADS=manual "$UV" python install --no-bin ${reinstall[@]+"${reinstall[@]}"} "$PYTHON_VERSION" \
    || die "Python 설치 실패. 네트워크 확인 후 다시 실행하세요."
  PYSYS="$(py_find)"
  py_ok "$PYSYS" || die "Python $PYTHON_VERSION 확인 실패: ${PYSYS:-없음}"
fi

# ---- 3. 공식 LeRobot 고정 SHA checkout(원본 참조·설치본 동일성 검증용) ----
EXT="$WS/external/lerobot"
if [[ -d "$EXT/.git" ]]; then
  head_sha="$("${GITX[@]}" -C "$EXT" rev-parse HEAD 2>/dev/null || echo none)"
  dirty="$("${GITX[@]}" -C "$EXT" status --porcelain 2>/dev/null | head -n1)"
  if [[ "$head_sha" == "$LEROBOT_SHA" && -z "$dirty" ]]; then
    log "external/lerobot @ $LEROBOT_SHA 재사용"
  elif [[ -n "$dirty" ]]; then
    die "external/lerobot에 수정된 파일이 있습니다. 덮어쓰지 않습니다. 'git -C external/lerobot status'로 확인하세요."
  else
    log "external/lerobot이 ${head_sha}에 있습니다. 수정 사항이 없으므로 ${LEROBOT_SHA}로 전환합니다."
    "${GITX[@]}" -C "$EXT" fetch -q origin "$LEROBOT_SHA" || die "fetch 실패. 네트워크 확인 후 다시 실행하세요."
    "${GITX[@]}" -C "$EXT" -c advice.detachedHead=false checkout -q --detach "$LEROBOT_SHA"
  fi
elif [[ -e "$EXT" ]]; then
  die "${EXT}가 git checkout이 아닙니다. 내용을 확인하고 직접 옮긴 뒤 다시 실행하세요(자동 삭제하지 않음)."
else
  log "LeRobot $LEROBOT_TAG($LEROBOT_SHA) 받기"
  mkdir -p "$WS/external"
  rm -rf "$EXT.partial"   # 이전 실행이 남긴 이 설치기 전용 임시 폴더
  "${GITX[@]}" clone -q --filter=blob:none --no-checkout "$LEROBOT_REPO" "$EXT.partial" || die "clone 실패. 다시 실행하세요."
  "${GITX[@]}" -C "$EXT.partial" -c advice.detachedHead=false checkout -q --detach "$LEROBOT_SHA" || die "checkout 실패"
  mv "$EXT.partial" "$EXT"
fi
[[ "$("${GITX[@]}" -C "$EXT" rev-parse HEAD)" == "$LEROBOT_SHA" ]] || die "external/lerobot SHA 불일치"
tag_sha="$("${GITX[@]}" -C "$EXT" rev-parse "refs/tags/$LEROBOT_TAG^{commit}" 2>/dev/null || true)"
[[ -z "$tag_sha" || "$tag_sha" == "$LEROBOT_SHA" ]] || die "태그 $LEROBOT_TAG($tag_sha)가 고정 SHA와 다릅니다."

# ---- 4. (유지보수) lock 재해결 ----
if [[ "$MODE" == relock ]]; then
  log "[relock] lock/macos-arm64/uv.lock 재해결"
  "$UV" lock --project "$LOCKDIR" --python "$PYSYS"
  log "[relock] lock 점검(해시·로컬 경로·sdist·macOS arm64 휠)"
  "$PYSYS" -I "$WS/tools/lock_tools.py" check-macos "$LOCKDIR/uv.lock" || die "[relock] lock 점검 실패"
  log "[relock] 공식 uv.lock과 비교(버전)"
  "$PYSYS" -I "$WS/tools/lock_tools.py" diff "$EXT/uv.lock" "$LOCKDIR/uv.lock"
  log "[relock] 공식 uv.lock과 비교(macOS arm64 cp312 휠 해시)"
  "$PYSYS" -I "$WS/tools/lock_tools.py" hashes "$EXT/uv.lock" "$LOCKDIR/uv.lock"
fi
[[ -f "$LOCKDIR/uv.lock" ]] || die "lock/macos-arm64/uv.lock이 없습니다(유지보수자가 --relock으로 생성)."

# ---- 5. venv ----
if [[ -e "$WS/.venv" ]]; then
  vpy="$WS/.venv/bin/python"
  vver="$("$vpy" -c 'import platform;print(platform.python_version())' 2>/dev/null || echo none)"
  if [[ "$vver" != "$PYTHON_VERSION" ]]; then
    if [[ "$RESET_VENV" == 1 ]]; then
      bk="$WS/.venv.broken-$(date +%Y%m%d_%H%M%S)"
      log ".venv(Python $vver)을 ${bk}로 옮깁니다."
      mv "$WS/.venv" "$bk"
    else
      die ".venv의 Python이 ${vver}입니다($PYTHON_VERSION 필요). --reset-venv로 옮기고 새로 만들 수 있습니다."
    fi
  fi
fi
if [[ ! -e "$WS/.venv" ]]; then
  log ".venv 생성(managed Python $PYTHON_VERSION)"
  "$UV" venv --quiet --python "$PYSYS" "$WS/.venv"
fi

# ---- 6. lock 그대로 동기화(재해결 없음, lock에 없는 패키지 제거, 누락·버전 차이 복구) ----
sync_args=(sync --project "$LOCKDIR" --locked --python "$WS/.venv/bin/python")
[[ "$MODE" == repair ]] && sync_args+=(--reinstall --no-cache)
if "$UV" sync --project "$LOCKDIR" --locked --python "$WS/.venv/bin/python" --check >/dev/null 2>&1 && [[ "$MODE" != repair ]]; then
  log "패키지 상태가 lock과 일치 → 재사용"
else
  log "uv sync --locked 실행"
  "$UV" "${sync_args[@]}" || die "의존성 설치 실패. 네트워크 확인 후 다시 실행하세요(이미 받은 파일은 .cache/uv에서 재사용)."
fi
"$UV" sync --project "$LOCKDIR" --locked --python "$WS/.venv/bin/python" --check >/dev/null || die "설치 후에도 환경이 lock과 다릅니다."
"$UV" pip check --python "$WS/.venv/bin/python" || die "의존성 불일치(uv pip check)"

# ---- 7. 실제 상태 검증(소프트웨어 점검) 후 stamp 기록 ----
log "소프트웨어 점검(scripts/so101 doctor --scope software)"
set +e
SO101_INSTALLING=1 "$WS/scripts/so101" doctor --scope software
rc=$?
set -e
if [[ $rc -ne 0 && $rc -ne 2 ]]; then
  die "소프트웨어 점검 실패. 위 FAIL 항목을 확인하세요. 파일 손상이 의심되면 --repair로 다시 실행하세요."
fi
"$WS/.venv/bin/python" -I - "$WS" "$LEROBOT_SHA" "$UV_VERSION" <<'EOF'
import hashlib, json, sys, time, pathlib, platform
ws, sha, uvv = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
h = lambda p: hashlib.sha256((ws / p).read_bytes()).hexdigest()
stamp = {
    "platform": "macos-arm64",
    "lerobot_sha": sha,
    "uv_version": uvv,
    "python": platform.python_version(),
    "uv_lock_sha256": h("lock/macos-arm64/uv.lock"),
    "pyproject_sha256": h("lock/macos-arm64/pyproject.toml"),
    "platform_env_sha256": h("lock/macos-arm64/platform.env"),
    "lerobot_env_sha256": h("lock/lerobot.env"),
    "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
}
(ws / ".venv/so101_install_stamp.json").write_text(json.dumps(stamp, indent=2) + "\n")
EOF
log "완료. 다음: ./01_setup/doctor.sh (상세), 현장 절차는 docs/SETUP.md"
