# 01_setup/·02_teleop/·03_dataset/ 진입 스크립트가 source하는 공통 부분(bash 3.2 호환).
# 호출 전에 ROOT(프로젝트 루트, 스크립트 위치 기준)를 정해야 한다. 공통 CLI는 scripts/so101(.venv Python, 환경 격리)이다.
SO101="$ROOT/scripts/so101"
# SO101_CONFIG=<경로>이면 로봇 설정 파일을 바꾼다(기본 configs/robot.local.yaml).
SO101_GLOBAL=()
if [ -n "${SO101_CONFIG:-}" ]; then SO101_GLOBAL=(--config "$SO101_CONFIG"); fi

die() { printf '[%s] %s\n' "$(basename "$0")" "$*" >&2; exit 2; }

# need_role <값> <허용값...>: 역할 인자를 검사한다(임의로 고르지 않음).
need_role() {
  local v="${1:-}"; shift
  local a
  for a in "$@"; do [ "$v" = "$a" ] && return 0; done
  if [ -z "$v" ]; then
    printf '[%s] 역할을 지정하세요: %s\n' "$(basename "$0")" "$*" >&2
  else
    printf '[%s] 알 수 없는 역할 "%s". 가능한 값: %s\n' "$(basename "$0")" "$v" "$*" >&2
  fi
  printf '도움말: %s --help\n' "$0" >&2
  exit 2
}

run_so101() {
  if [ "${#SO101_GLOBAL[@]}" -gt 0 ]; then
    exec "$SO101" "${SO101_GLOBAL[@]}" "$@"
  fi
  exec "$SO101" "$@"
}
