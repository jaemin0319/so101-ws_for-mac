#!/usr/bin/env python3
"""SO-101 리더→팔로워 추종(·macOS 로컬 데이터셋 녹화)용 얇은 래퍼.

모터 통신·설정·보정·추종 루프·녹화는 공식 LeRobot(lock/lerobot.env의 고정 버전) CLI/API를 그대로 쓴다.
이 파일이 하는 일: 설정 검증, 비구동 점검, 읽기 전용 모터 확인(probe), 공식 CLI 인자 생성·실행·기록,
추종 종료 후 양팔 토크 해제 재시도(독립 정리).
플랫폼: Linux(Ubuntu 24.04 x86_64, 기존 경로 그대로)와 macOS arm64(IS_MAC 분기: 포트 열거·점유 확인·고아 방지·절전 방지).

직접 실행하지 말고 scripts/so101 (환경 격리 진입점)로 실행한다. 사용법: scripts/so101 --help
"""
from __future__ import annotations

import argparse
import ctypes
import grp
import hashlib
import json
import math
import os
import platform
import pwd
import re
import select
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

WS = Path(os.environ.get("SO101_WS") or Path(__file__).resolve().parent.parent)
VENV = WS / ".venv"
VENV_BIN = VENV / "bin"
LOCK_ENV = WS / "lock" / "lerobot.env"
DEFAULT_CONFIG = WS / "configs" / "robot.local.yaml"
LOG_DIR = WS / "logs"
RUNS_LOG = LOG_DIR / "runs.jsonl"
STAMP = VENV / "so101_install_stamp.json"

# macOS arm64는 별도 lock(lock/macos-arm64)과 플랫폼 고정값(platform.env)을 쓴다. Linux는 기존 lock/ 그대로.
IS_MAC = sys.platform == "darwin"
LOCK_DIR = WS / "lock" / "macos-arm64" if IS_MAC else WS / "lock"
PLATFORM_ENV = WS / "lock" / "macos-arm64" / "platform.env"
LAUNCHER = WS / "scripts" / "so101_launch.py"
# macOS 동적 링커 변수도 격리 대상(Linux에서는 원래 없는 변수)
LEAK_VARS = ("PYTHONPATH", "PYTHONHOME", "LD_LIBRARY_PATH") + (
    ("DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES") if IS_MAC else ())

# 공식 SO101 모터 맵의 관절 이름(lerobot/robots/so_follower/so_follower.py, teleoperators/so_leader/so_leader.py).
# doctor가 공식 클래스에서 다시 읽어 같은지 확인한다(official_motor_map).
JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
ROLE_TYPES = {"leader": "so101_leader", "follower": "so101_follower"}
OFFICIAL_CLIS = ("lerobot-teleoperate", "lerobot-calibrate", "lerobot-setup-motors", "lerobot-find-port", "lerobot-info")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

# 종료 처리 한도
INTERRUPT_GRACE_S = 20.0  # SIGINT 후 자식 종료 대기
TERM_GRACE_S = 5.0  # SIGTERM 후 대기, 그다음 SIGKILL
CLEANUP_TIMEOUT_S = 10.0  # 팔 하나의 토크 해제 재시도 한도
CLEANUP_PACKET_TIMEOUT_MS = 100  # 정리 시 버스 패킷 timeout(공식 기본 1000ms보다 짧게)
WRAP_EDGE = 20  # 보정 범위가 0~WRAP_EDGE 이하와 4095-WRAP_EDGE 이상에 동시에 닿으면 엔코더 넘어감으로 판정

OK, WARN, FAIL, INFO = "OK", "WARN", "FAIL", "INFO"


# --------------------------------------------------------------------------------------------
# 공통 출력/기록
# --------------------------------------------------------------------------------------------
@dataclass
class Report:
    items: list[tuple[str, str, str]] = field(default_factory=list)

    def add(self, status: str, title: str, detail: str = "") -> None:
        self.items.append((status, title, detail))
        mark = {OK: "  OK ", WARN: " WARN", FAIL: " FAIL", INFO: " INFO"}[status]
        print(f"[{mark}] {title}" + (f"\n         {detail}" if detail else ""), flush=True)

    @property
    def n_fail(self) -> int:
        return sum(1 for s, _, _ in self.items if s == FAIL)

    @property
    def n_warn(self) -> int:
        return sum(1 for s, _, _ in self.items if s == WARN)

    def exit_code(self) -> int:
        """0: 모두 OK, 1: FAIL 있음(실행 불가), 2: WARN만 있음(참고)."""
        return 1 if self.n_fail else (2 if self.n_warn else 0)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def append_run_log(entry: dict) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(RUNS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:  # 기록 실패가 원래 결과를 가리지 않게 경고만 한다
        print(f"[so101] 경고: 실행 기록 저장 실패: {e}", file=sys.stderr)


def read_lock_env() -> dict[str, str]:
    out: dict[str, str] = {}
    files = [LOCK_ENV] + ([PLATFORM_ENV] if IS_MAC else [])  # macOS 값이 공통값 위에 덮인다(UV_ASSET 등)
    for f in files:
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def git_base() -> list[str]:
    """external/lerobot용 git 명령. macOS에서는 사용자 전역 git-lfs 필터(미설치 시 실패)를 이 호출에서만 끈다."""
    if IS_MAC:
        return ["git", "-c", "filter.lfs.process=", "-c", "filter.lfs.smudge=cat", "-c", "filter.lfs.clean=cat",
                "-c", "filter.lfs.required=false"]
    return ["git"]


def locked_version(name: str) -> str | None:
    """현재 플랫폼 lock(LOCK_DIR/uv.lock)에 잠긴 패키지 버전."""
    import tomllib

    try:
        data = tomllib.loads((LOCK_DIR / "uv.lock").read_text())
    except (OSError, ValueError):
        return None
    vs = [p.get("version") for p in data.get("package", []) if p.get("name") == name]
    return vs[0] if len(vs) == 1 else None


# --------------------------------------------------------------------------------------------
# 설정
# --------------------------------------------------------------------------------------------
@dataclass
class ArmCfg:
    role: str  # leader | follower
    type: str
    id: str | None
    port: str | None
    # 선택: USB 지문(ports 마법사가 기록). {vid, pid, serial, location, id_by: serial|location}. 없으면 기존과 같다.
    usb: dict[str, str | None] | None = None


@dataclass
class Config:
    path: Path
    leader: ArmCfg
    follower: ArmCfg
    disable_torque_on_disconnect: bool
    max_relative_target: float | dict[str, float] | None
    fps: int
    time_s: float | None
    calibration_root: Path

    def arm(self, role: str) -> ArmCfg:
        return self.leader if role == "leader" else self.follower


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x))


def load_config(path: Path) -> tuple[Config | None, list[str]]:
    """YAML 설정을 읽고 타입을 검증한다. 하드웨어 전제(null 금지, 포트 존재)는 여기서 보지 않는다."""
    import yaml  # draccus 의존성으로 venv에 있다

    errors: list[str] = []
    if not path.is_file():
        how = ("./01_setup/ports.sh로 포트·장치 ID를 지정해 만드세요(또는 cp configs/robot.example.yaml configs/robot.local.yaml 후 직접 작성)."
               if IS_MAC else "cp configs/robot.example.yaml configs/robot.local.yaml 후 값을 채우세요.")
        return None, [f"설정 파일이 없습니다: {path}  →  {how}"]
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        return None, [f"YAML 파싱 실패: {e}"]
    if not isinstance(raw, dict):
        return None, ["설정 최상위는 mapping이어야 합니다."]
    known_top = {"leader", "follower", "teleop", "calibration_root"}
    for k in raw:
        if k not in known_top:
            errors.append(f"알 수 없는 최상위 키: {k}")

    arms: dict[str, ArmCfg] = {}
    extra: dict[str, Any] = {}
    for role, expected_type in ROLE_TYPES.items():
        sec = raw.get(role)
        if not isinstance(sec, dict):
            errors.append(f"'{role}' 섹션이 없거나 mapping이 아닙니다.")
            arms[role] = ArmCfg(role, expected_type, None, None)
            continue
        allowed = {"type", "id", "port", "usb"} | ({"disable_torque_on_disconnect", "max_relative_target"} if role == "follower" else set())
        for k in sec:
            if k not in allowed:
                errors.append(f"{role}.{k}: 지원하지 않는 키입니다.")
        t = sec.get("type", expected_type)
        if t != expected_type:
            errors.append(f"{role}.type은 '{expected_type}'이어야 합니다(현재 {t!r}).")
        dev_id = sec.get("id")
        if dev_id is not None and (not isinstance(dev_id, str) or not ID_RE.match(dev_id)):
            errors.append(f"{role}.id는 null 또는 영문/숫자/_.- 문자열이어야 합니다(현재 {dev_id!r}).")
            dev_id = None
        port = sec.get("port")
        if port is not None and (not isinstance(port, str) or not os.path.isabs(port)):
            errors.append(f"{role}.port는 null 또는 절대경로 문자열이어야 합니다(예: /dev/serial/by-id/...; 현재 {port!r}).")
            port = None
        usb = sec.get("usb")
        if usb is not None:
            usb_err = validate_usb_fingerprint(usb)
            if usb_err:
                errors.append(f"{role}.usb: {usb_err}")
                usb = None
        arms[role] = ArmCfg(role, expected_type, dev_id, port, usb)
        if role == "follower":
            extra = sec

    dtod = extra.get("disable_torque_on_disconnect", True)
    if not isinstance(dtod, bool):
        errors.append("follower.disable_torque_on_disconnect는 true/false여야 합니다.")
        dtod = True
    elif dtod is False:
        errors.append("follower.disable_torque_on_disconnect=false는 허용하지 않습니다(종료 시 토크 해제가 공식 동작).")

    mrt = extra.get("max_relative_target")
    if mrt is not None:
        if _is_number(mrt):
            if float(mrt) <= 0:
                errors.append("follower.max_relative_target 숫자는 0보다 커야 합니다.")
            mrt = float(mrt)
        elif isinstance(mrt, dict):
            keys = set(mrt)
            if keys != set(JOINTS):
                errors.append(
                    "follower.max_relative_target dict는 6개 관절 키가 정확히 있어야 합니다"
                    f"(공식 ensure_safe_goal_position 조건). 누락={sorted(set(JOINTS) - keys)}, 불필요={sorted(keys - set(JOINTS))}"
                )
            bad = [k for k, v in mrt.items() if not _is_number(v) or float(v) <= 0]
            if bad:
                errors.append(f"follower.max_relative_target 값은 양수여야 합니다: {bad}")
            mrt = {k: float(v) for k, v in mrt.items() if _is_number(v)}
        else:
            errors.append("follower.max_relative_target은 null, 양수, 또는 6개 관절 dict여야 합니다.")
            mrt = None

    tsec = raw.get("teleop") or {}
    if not isinstance(tsec, dict):
        errors.append("'teleop' 섹션은 mapping이어야 합니다.")
        tsec = {}
    for k in tsec:
        if k not in {"fps", "time_s"}:
            errors.append(f"teleop.{k}: 지원하지 않는 키입니다.")
    fps = tsec.get("fps", 60)
    if not isinstance(fps, int) or isinstance(fps, bool) or fps <= 0:
        errors.append(f"teleop.fps는 양의 정수여야 합니다(현재 {fps!r}).")
        fps = 60
    time_s = tsec.get("time_s")
    if time_s is not None and (not _is_number(time_s) or float(time_s) <= 0):
        errors.append(f"teleop.time_s는 null 또는 양수(초)여야 합니다(현재 {time_s!r}).")
        time_s = None

    croot = raw.get("calibration_root")
    if croot is None:
        calib_root = WS / "calibration"
    elif isinstance(croot, str) and croot:
        calib_root = Path(os.path.expanduser(croot))
        if not calib_root.is_absolute():
            calib_root = WS / calib_root
    else:
        errors.append("calibration_root는 null 또는 경로 문자열이어야 합니다.")
        calib_root = WS / "calibration"

    cfg = Config(
        path=path,
        leader=arms["leader"],
        follower=arms["follower"],
        disable_torque_on_disconnect=True,
        max_relative_target=mrt,
        fps=fps,
        time_s=float(time_s) if time_s is not None else None,
        calibration_root=calib_root,
    )
    return cfg, errors


USB_KEYS = ("vid", "pid", "serial", "location", "id_by")


def validate_usb_fingerprint(usb: Any) -> str | None:
    """선택 키 usb의 형식 검사. 문제가 있으면 메시지, 없으면 None."""
    if not isinstance(usb, dict):
        return "mapping이어야 합니다(예: {vid: \"1a86\", pid: \"55d3\", serial: \"...\", location: \"...\", id_by: serial})."
    extra = set(usb) - set(USB_KEYS)
    if extra:
        return f"지원하지 않는 키 {sorted(extra)}"
    for k in USB_KEYS:
        v = usb.get(k)
        if v is not None and not isinstance(v, str):
            return f"{k}는 문자열 또는 null이어야 합니다(현재 {v!r}). 16진 값은 따옴표로 감싸세요."
    if usb.get("id_by") not in ("serial", "location"):
        return "id_by는 serial 또는 location이어야 합니다."
    if not usb.get("vid") or not usb.get("pid"):
        return "vid·pid가 필요합니다."
    if not usb.get(usb["id_by"]):
        return f"id_by={usb['id_by']}인데 {usb['id_by']} 값이 비어 있습니다."
    return None


def apply_calibration_env(cfg: Config | None) -> None:
    """공식 코드가 import 시 읽는 HF_LEROBOT_CALIBRATION을 lerobot import 전에 설정한다."""
    root = cfg.calibration_root if cfg else WS / "calibration"
    os.environ["HF_LEROBOT_CALIBRATION"] = str(root)


def calibration_file(cfg: Config, role: str) -> Path | None:
    arm = cfg.arm(role)
    if not arm.id:
        return None
    # 공식 경로 규칙: HF_LEROBOT_CALIBRATION/{robots|teleoperators}/{클래스 name}/{id}.json
    # (lerobot/robots/robot.py, lerobot/teleoperators/teleoperator.py). 클래스 name은 so_follower/so_leader.
    sub = ("robots", "so_follower") if role == "follower" else ("teleoperators", "so_leader")
    return cfg.calibration_root / sub[0] / sub[1] / f"{arm.id}.json"


# --------------------------------------------------------------------------------------------
# 공식 클래스/명령
# --------------------------------------------------------------------------------------------
def official_device(role: str, port: str, dev_id: str, calibration_dir: Path | None = None):
    """공식 SO101Leader/SO101Follower 객체를 *생성만* 한다(connect하지 않음 → 포트를 열지 않음).
    모터 맵과 공식 보정 파일 로더 결과(obj.calibration)를 얻는 용도다. 생성자는 보정 폴더를 mkdir한다."""
    if role == "follower":
        from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

        return SO101Follower(SO101FollowerConfig(port=port, id=dev_id, calibration_dir=calibration_dir))
    from lerobot.teleoperators.so_leader import SO101Leader, SO101LeaderConfig

    return SO101Leader(SO101LeaderConfig(port=port, id=dev_id, calibration_dir=calibration_dir))


def make_bus(role: str, port: str, dev_id: str | None):
    """공식 모터 맵·보정으로 별도 FeetechMotorsBus를 만든다.
    공식 Robot/Teleoperator의 connect/configure/calibrate 경로와 그 객체의 bus는 쓰지 않는다
    (객체 bus는 열리지 않으므로 소멸자의 disconnect(토크 쓰기)도 실행되지 않는다)."""
    from copy import deepcopy

    from lerobot.motors.feetech import FeetechMotorsBus

    obj = official_device(role, port, dev_id or "so101-unnamed")
    motors = deepcopy(obj.bus.motors)
    calib = deepcopy(obj.calibration) if dev_id else {}
    assert not obj.bus.is_connected
    del obj
    return FeetechMotorsBus(port=port, motors=motors, calibration=calib or None)


def official_cmd(name: str) -> str:
    return str(VENV_BIN / name)


def build_teleop_argv(cfg: Config, time_s: float | None, *, placeholder: bool = False) -> list[str]:
    def val(x: str | None, what: str) -> str:
        if x is None:
            if placeholder:
                return f"<{what} 미지정>"
            raise ValueError(f"{what} 미지정")
        return x

    argv = [
        official_cmd("lerobot-teleoperate"),
        "--robot.type=so101_follower",
        f"--robot.port={val(cfg.follower.port, 'follower.port')}",
        f"--robot.id={val(cfg.follower.id, 'follower.id')}",
        "--robot.disable_torque_on_disconnect=true",
        "--teleop.type=so101_leader",
        f"--teleop.port={val(cfg.leader.port, 'leader.port')}",
        f"--teleop.id={val(cfg.leader.id, 'leader.id')}",
        f"--fps={cfg.fps}",
        "--display_data=false",
    ]
    mrt = cfg.max_relative_target
    if isinstance(mrt, float):
        argv.append(f"--robot.max_relative_target={mrt!r}")
    elif isinstance(mrt, dict):
        argv.append("--robot.max_relative_target=" + json.dumps({k: float(v) for k, v in mrt.items()}))
    if time_s is not None:
        argv.append(f"--teleop_time_s={float(time_s)!r}")
    return argv


def build_device_argv(cli: str, cfg: Config, role: str, *, placeholder: bool = False) -> list[str]:
    arm = cfg.arm(role)
    key = "robot" if role == "follower" else "teleop"
    port = arm.port or ("<port 미지정>" if placeholder else None)
    dev_id = arm.id or ("<id 미지정>" if placeholder else None)
    if port is None or dev_id is None:
        raise ValueError(f"{role}.port/id 미지정")
    return [official_cmd(cli), f"--{key}.type={arm.type}", f"--{key}.port={port}", f"--{key}.id={dev_id}"]


def official_parse_check(argv: list[str]) -> tuple[bool, str]:
    """공식 TeleoperateConfig를 draccus로 파싱해 인자 타입을 확인한다(객체 생성·장치 접근 없음)."""
    import draccus

    from lerobot.scripts.lerobot_teleoperate import TeleoperateConfig

    try:
        c = draccus.parse(config_class=TeleoperateConfig, args=argv[1:])
    except BaseException as e:  # draccus는 SystemExit을 낼 수 있다
        return False, f"{type(e).__name__}: {e}"
    m = c.robot.max_relative_target
    if m is not None and not (isinstance(m, float) or (isinstance(m, dict) and all(isinstance(v, float) for v in m.values()))):
        return False, f"max_relative_target 파싱 타입이 float/dict[float]가 아님: {m!r}"
    return True, f"robot.max_relative_target={m!r}, fps={c.fps}, teleop_time_s={c.teleop_time_s!r}"


# --------------------------------------------------------------------------------------------
# 포트 정보(읽기 전용: 파일시스템/sysfs/proc만 본다. 장치를 열지 않는다)
# macOS: pyserial comports()(IOKit 조회, 포트를 열지 않음)와 lsof를 쓴다.
# --------------------------------------------------------------------------------------------
COMPORTS_FN: Callable[[], list] | None = None  # 검증 도구가 가짜 장치 목록을 주입할 때만 사용


def canonical_port(path: str) -> str:
    """같은 물리 장치를 가리키는 경로를 하나로 정규화한다(장치를 열지 않음).
    Linux: realpath(by-id/by-path 링크 해석, 기존 동작). macOS: realpath 후 /dev/tty.X → /dev/cu.X.
    macOS의 tty.X(dial-in)와 cu.X(call-out)는 같은 USB 시리얼 인터페이스의 서로 다른 장치 노드라
    realpath로 합쳐지지 않으므로 이름 규칙으로 묶는다."""
    real = os.path.realpath(path)
    if IS_MAC:
        d, b = os.path.split(real)
        if d == "/dev" and b.startswith("tty."):
            return "/dev/cu." + b[4:]
    return real


def mac_aliases(cu: str) -> list[str]:
    """macOS cu.X의 별칭 노드 목록(cu.X, tty.X 중 실제 있는 것)."""
    b = os.path.basename(cu)
    names = [cu] + (["/dev/tty." + b[3:]] if b.startswith("cu.") else [])
    return [n for n in names if os.path.lexists(n)]


def mac_usb_ports() -> list[dict[str, Any]]:
    """macOS USB 시리얼 장치 목록(pyserial comports, IOKit 조회만 하고 포트를 열지 않음).
    vid가 없는 항목(Bluetooth·debug-console 등 비USB)은 로봇 후보에서 뺀다. 같은 장치의 tty/cu는 한 항목이다."""
    if COMPORTS_FN is not None:
        raw = COMPORTS_FN()
    else:
        from serial.tools import list_ports

        raw = list_ports.comports()
    out: dict[str, dict[str, Any]] = {}
    for c in raw:
        if getattr(c, "vid", None) is None:
            continue
        dev = canonical_port(c.device)
        out[dev] = {
            "device": dev,
            "vid": f"{c.vid:04x}",
            "pid": f"{c.pid:04x}" if c.pid is not None else None,
            "serial": (c.serial_number or None),
            "location": (c.location or None),
            "manufacturer": c.manufacturer,
            "product": c.product,
            "description": c.description,
        }
    return [out[k] for k in sorted(out)]


def usb_info(real_dev: str) -> dict[str, str]:
    if IS_MAC:
        dev = canonical_port(real_dev)
        for u in mac_usb_ports():
            if u["device"] == dev:
                info = {"idVendor": u["vid"], "idProduct": u["pid"] or "?", "usb_path": u["location"] or "?"}
                for k_src, k_dst in (("serial", "serial"), ("manufacturer", "manufacturer"), ("product", "product")):
                    if u[k_src]:
                        info[k_dst] = u[k_src]
                return info
        return {}
    name = os.path.basename(real_dev)
    info: dict[str, str] = {}
    p = Path(f"/sys/class/tty/{name}/device")
    try:
        p = p.resolve(strict=True)
    except OSError:
        return info
    for d in [p, *p.parents]:
        if (d / "idVendor").is_file():
            for k in ("idVendor", "idProduct", "serial", "manufacturer", "product", "busnum", "devpath"):
                f = d / k
                if f.is_file():
                    try:
                        info[k] = f.read_text().strip()
                    except OSError:
                        pass
            info["usb_path"] = d.name
            break
    return info


def serial_links() -> dict[str, list[str]]:
    """realpath → [by-id/by-path 링크]"""
    links: dict[str, list[str]] = {}
    for sub in ("by-id", "by-path"):
        d = Path("/dev/serial") / sub
        if d.is_dir():
            for e in sorted(d.iterdir()):
                links.setdefault(os.path.realpath(e), []).append(str(e))
    return links


def serial_devices() -> list[str]:
    if IS_MAC:
        return [u["device"] for u in mac_usb_ports()]
    devs = set(serial_links())
    for pat in ("ttyACM*", "ttyUSB*"):
        devs.update(str(p) for p in Path("/dev").glob(pat))
    return sorted(devs)


class PortCheckError(RuntimeError):
    """점유 확인 자체가 실패함(점유 없음으로 간주하지 않는다)."""


def mac_port_users(dev: str) -> list[str]:
    """macOS: lsof로 cu/tty 두 노드를 모두 연 프로세스를 찾는다. lsof 실행·해석 실패는 PortCheckError.
    lsof는 관리자 권한 없이 같은 사용자의 프로세스만 볼 수 있다(다른 사용자 프로세스는 확인 불가)."""
    paths = mac_aliases(dev) or [dev]
    lsof = "/usr/sbin/lsof" if os.path.exists("/usr/sbin/lsof") else "lsof"
    try:
        r = subprocess.run([lsof, "-w", "-F", "pc", "--", *paths], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise PortCheckError(f"lsof 실행 실패: {e}") from e
    if r.returncode not in (0, 1) or (r.returncode == 1 and r.stderr.strip()):
        raise PortCheckError(f"lsof 오류(exit {r.returncode}): {r.stderr.strip()[:200]}")
    users, pid = [], None
    for line in r.stdout.splitlines():
        if line.startswith("p"):
            pid = line[1:]
        elif line.startswith("c") and pid and int(pid) != os.getpid():
            users.append(f"pid {pid} ({line[1:]})")
    return sorted(set(users))


def port_users(real_dev: str) -> tuple[list[str], int]:
    """/proc/*/fd에서 장치를 연 프로세스를 찾는다(권한상 볼 수 없는 프로세스 수도 반환).
    macOS는 lsof를 쓰며, 다른 사용자 프로세스는 볼 수 없다는 뜻으로 hidden=-1을 반환한다."""
    if IS_MAC:
        return mac_port_users(real_dev), -1
    users, hidden = [], 0
    for pid_dir in Path("/proc").iterdir():
        if not pid_dir.name.isdigit() or int(pid_dir.name) == os.getpid():
            continue
        try:
            for fd in (pid_dir / "fd").iterdir():
                try:
                    if os.readlink(fd) == real_dev:
                        comm = (pid_dir / "comm").read_text().strip()
                        users.append(f"pid {pid_dir.name} ({comm})")
                        break
                except OSError:
                    continue
        except PermissionError:
            hidden += 1
        except OSError:
            continue
    return users, hidden


def check_port(rep: Report, role: str, port: str | None) -> str | None:
    """포트 경로를 열지 않고 확인한다. 성공 시 realpath 반환."""
    if not port:
        rep.add(FAIL, f"{role} 포트 미지정", "configs/robot.local.yaml의 port를 지정하세요(scripts/so101 ports로 확인).")
        return None
    if not os.path.lexists(port):
        rep.add(FAIL, f"{role} 포트 경로 없음: {port}", "USB 연결·보드 전원(보드에 따라 필요)·경로 오타를 확인하고 "
                + ("./01_setup/ports.sh로 다시 지정하세요." if IS_MAC else "scripts/so101 ports로 다시 찾으세요."))
        return None
    real = canonical_port(port) if IS_MAC else os.path.realpath(port)
    try:
        st = os.stat(real)
    except OSError as e:
        rep.add(FAIL, f"{role} 포트 확인 실패: {port}", str(e))
        return None
    if not stat.S_ISCHR(st.st_mode):
        rep.add(FAIL, f"{role} 포트가 문자 장치가 아님: {port} → {real}")
        return None
    if not os.access(real, os.R_OK | os.W_OK) and IS_MAC:
        rep.add(FAIL, f"{role} 포트 읽기/쓰기 권한 없음: {real} (모드 {oct(st.st_mode & 0o777)})",
                "macOS USB 시리얼 노드는 보통 crw-rw-rw-입니다. 다른 사용자 세션·보안 소프트웨어를 확인하세요. chmod는 쓰지 않습니다.")
        return None
    if not os.access(real, os.R_OK | os.W_OK):
        gname = grp.getgrgid(st.st_gid).gr_name if st.st_gid is not None else "?"
        user = pwd.getpwuid(os.getuid()).pw_name
        member = user in grp.getgrgid(st.st_gid).gr_mem or pwd.getpwuid(os.getuid()).pw_gid == st.st_gid
        if member and st.st_gid not in os.getgroups():
            how = f"'{gname}' 그룹에는 가입되어 있지만 현재 세션에 반영되지 않았습니다. 로그아웃 후 다시 로그인(SSH 재접속)하세요."
        elif member:
            how = f"'{gname}' 그룹 권한이 있지만 장치 모드({oct(st.st_mode & 0o777)})가 접근을 막습니다."
        else:
            how = f"'{gname}' 그룹에 가입되어 있지 않습니다. 사용자가 직접: sudo usermod -aG {gname} {user}  → 로그아웃 후 다시 로그인."
        rep.add(FAIL, f"{role} 포트 읽기/쓰기 권한 없음: {real}", how)
        return None
    try:
        users, hidden = port_users(real)
    except PortCheckError as e:
        rep.add(FAIL, f"{role} 포트 점유 확인 실패: {real}", f"{e}  → 확인할 수 없으면 점유 없음으로 간주하지 않습니다. 다시 실행하세요.")
        return None
    if users:
        rep.add(FAIL, f"{role} 포트를 다른 프로세스가 사용 중: {real}", ", ".join(users) + "  → 해당 프로세스를 종료한 뒤 다시 실행하세요.")
        return None
    seen = "같은 사용자 프로세스 기준(lsof, cu·tty 모두). 다른 사용자 프로세스는 볼 수 없음" if hidden < 0 else f"볼 수 없는 프로세스 {hidden}개 제외"
    rep.add(OK, f"{role} 포트 {port} → {real}", f"점유 프로세스 없음({seen})")
    return real


def check_usb_fingerprint(rep: Report, role: str, arm: ArmCfg, real: str, *, strict: bool) -> bool:
    """macOS: 설정 포트가 기록된 USB 보드(지문)와 같은지 IOKit 정보로 대조한다(포트를 열지 않음).
    by-id가 없는 macOS에서 포트 이름만으로 역할을 믿지 않기 위한 검사다. strict=True(모터 쓰기·구동 명령)이면
    지문이 없거나 판단할 수 없을 때 FAIL, False(doctor·probe)이면 WARN. Linux는 by-id/by-path가 식별자라 생략한다."""
    if not IS_MAC:
        return True
    ports = mac_usb_ports()
    cur = next((u for u in ports if u["device"] == real), None)
    if cur is None:
        rep.add(FAIL, f"{role} 포트 {real}가 현재 USB 장치 목록에 없음", "USB 연결을 확인하고 ./01_setup/ports.sh로 다시 지정하세요.")
        return False
    now = f"VID:PID {cur['vid']}:{cur['pid']} serial={cur['serial'] or '(없음)'} 위치={cur['location'] or '?'}"
    fp = arm.usb
    if not fp:
        rep.add(FAIL if strict else WARN, f"{role} USB 지문이 설정에 없음({now})",
                "./01_setup/ports.sh로 지정하면 VID/PID/serial/USB 위치가 기록되어 실행 때마다 같은 보드인지 대조합니다.")
        return not strict
    mism = [k for k in ("vid", "pid") if (fp.get(k) or "").lower() != (cur[k] or "").lower()]
    if fp["id_by"] == "serial":
        if fp.get("serial") != cur["serial"]:
            mism.append("serial")
        dup = [u["device"] for u in ports
               if u["device"] != real and (u["vid"], u["pid"], u["serial"]) == (cur["vid"], cur["pid"], cur["serial"])]
        if not mism and dup:
            rep.add(FAIL, f"{role}: 같은 VID/PID/serial을 가진 장치가 여러 개입니다({real}, {', '.join(dup)})",
                    "serial로 구분할 수 없습니다. ./01_setup/ports.sh를 다시 실행하면 USB 위치 기준으로 기록합니다.")
            return False
        if not mism and fp.get("location") and fp.get("location") != cur["location"]:
            rep.add(INFO, f"{role} 보드가 기록과 다른 USB 단자에 연결됨(serial 일치: 같은 보드)", f"기록 위치 {fp.get('location')} → 현재 {cur['location']}")
    elif fp.get("location") != cur["location"]:
        mism.append("location")
    if mism:
        rep.add(FAIL, f"{role} 포트의 USB 지문이 기록과 다름({', '.join(mism)})",
                f"기록 {fp} / 현재 {now}\n         → 다른 보드이거나 다른 USB 단자(serial 없는 보드)입니다. 역할을 추측하지 말고 ./01_setup/ports.sh로 다시 지정하세요.")
        return False
    rep.add(OK, f"{role} USB 지문 일치(기준 {fp['id_by']})", now)
    return True


# --------------------------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------------------------
def doctor_macos_platform(rep: Report, lock: dict[str, str]) -> None:
    """macOS: native arm64·비Rosetta·macOS 버전·작업공간 managed Python(정확한 패치) 확인."""
    pyver = platform.python_version()
    want = lock.get("PYTHON_VERSION", "?")
    base = Path(sys.base_prefix).resolve()
    managed_root = (WS / ".tools" / "python").resolve()
    if pyver == want and managed_root in base.parents:
        rep.add(OK, f"Python {pyver} (uv managed, {base.relative_to(WS)})")
    else:
        rep.add(FAIL, f"Python {pyver} (필요: {want}, 작업공간 .tools/python)", f"base_prefix={base} → scripts/install_macos.sh --reset-venv")
    try:
        translated = subprocess.run(["sysctl", "-n", "sysctl.proc_translated"], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        translated = "?"
    mac = platform.mac_ver()[0]
    if platform.machine() == "arm64" and translated in ("0", ""):
        rep.add(OK, f"macOS {mac} native arm64", "Rosetta 번역 아님(sysctl.proc_translated=0)")
    else:
        rep.add(FAIL, f"arm64 native가 아님: machine={platform.machine()}, proc_translated={translated}", "native arm64 터미널에서 실행하세요.")
    need = lock.get("MACOS_MIN", "13.0")
    tup = lambda v: tuple(int(x) for x in (v.split(".") + ["0", "0"])[:3])  # noqa: E731
    if mac and tup(mac) >= tup(need):
        rep.add(OK, f"macOS {mac} ≥ {need}")
    else:
        rep.add(FAIL, f"macOS {mac} < {need}", "opencv·av macOS 휠의 최소 요구 버전")


def doctor_software(rep: Report) -> None:
    lock = read_lock_env()
    print("== 소프트웨어 점검(로봇·포트 설정 불필요, 장치를 열지 않음)")
    # 1) Python·venv·격리
    pyver = platform.python_version()
    installer = "scripts/install_macos.sh" if IS_MAC else "scripts/install.sh"
    if IS_MAC:
        doctor_macos_platform(rep, lock)
    elif sys.version_info[:2] == tuple(int(x) for x in lock["PYTHON_MINOR"].split(".")):
        rep.add(OK, f"Python {pyver}")
    else:
        rep.add(FAIL, f"Python {pyver} (필요: {lock['PYTHON_MINOR']})", "scripts/install.sh --reset-venv")
    if Path(sys.prefix).resolve() == VENV.resolve():
        rep.add(OK, f"작업공간 venv 사용: {VENV}")
    else:
        rep.add(FAIL, f"venv가 아님: sys.prefix={sys.prefix}", "scripts/so101로 실행하세요.")
    leaked = [k for k in LEAK_VARS if os.environ.get(k)]
    ros_paths = [p for p in sys.path if "/opt/ros" in p]
    import site

    if leaked or ros_paths or site.ENABLE_USER_SITE:
        rep.add(FAIL, "실행 환경 격리 실패", f"env={leaked}, sys.path ROS={ros_paths}, user site={site.ENABLE_USER_SITE}")
    else:
        rep.add(OK, "ROS·사용자 site-packages 격리", f"{'/'.join(LEAK_VARS)} 없음, sys.path에 /opt/ros 없음, user site 비활성")

    # 2) lock과 실제 설치 상태(stamp만 믿지 않고 uv로 다시 확인)
    uv = WS / ".tools/uv/uv"
    if uv.is_file():
        r = subprocess.run([str(uv), "--version"], capture_output=True, text=True)
        uvv = r.stdout.split()[1] if r.returncode == 0 else "?"
        rep.add(OK if uvv == lock["UV_VERSION"] else FAIL, f"uv {uvv} (기준 {lock['UV_VERSION']})")
        env = dict(os.environ, UV_PROJECT_ENVIRONMENT=str(VENV), UV_CACHE_DIR=os.environ.get("UV_CACHE_DIR", str(WS / ".cache/uv")),
                   UV_PYTHON_DOWNLOADS="never", UV_OFFLINE="1")
        r = subprocess.run([str(uv), "sync", "--project", str(LOCK_DIR), "--locked", "--check", "--python", sys.executable],
                           capture_output=True, text=True, env=env)
        lock_rel = (LOCK_DIR / "uv.lock").relative_to(WS)
        if r.returncode == 0:
            rep.add(OK, f"설치 패키지가 {lock_rel}과 정확히 일치(uv sync --locked --check)")
        else:
            rep.add(FAIL, "설치 패키지가 lock과 다름", (r.stderr or r.stdout).strip()[-600:] + f"\n         → {installer} 재실행")
        r = subprocess.run([str(uv), "pip", "check", "--python", sys.executable], capture_output=True, text=True, env=env)
        rep.add(OK if r.returncode == 0 else FAIL, "의존성 일관성(uv pip check)", "" if r.returncode == 0 else (r.stdout + r.stderr).strip()[-600:])
    else:
        rep.add(FAIL, "uv 고정 바이너리 없음", f"{installer} 실행")
    if STAMP.is_file():
        st = json.loads(STAMP.read_text())
        cur = hashlib.sha256((LOCK_DIR / "uv.lock").read_bytes()).hexdigest()
        if st.get("uv_lock_sha256") == cur and st.get("lerobot_sha") == lock["LEROBOT_SHA"]:
            rep.add(OK, "설치 stamp가 현재 lock·SHA와 일치", f"설치 시각 {st.get('installed_at')}")
        else:
            rep.add(WARN, "설치 stamp가 현재 lock과 다름", f"{installer} 재실행 권장(위 sync 확인이 실제 판정)")
    elif os.environ.get("SO101_INSTALLING") == "1":
        rep.add(INFO, f"설치 stamp는 이 점검 통과 후 {installer}가 기록함")
    else:
        rep.add(WARN, "설치 stamp 없음", f"{installer}가 끝까지 완료되지 않았을 수 있습니다.")

    # 3) 패키지 버전·위치·CPU torch
    from importlib import metadata

    def ver(name: str) -> str | None:
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            return None

    lv = ver("lerobot")
    rep.add(OK if lv == lock["LEROBOT_VERSION"] else FAIL, f"lerobot {lv} (기준 {lock['LEROBOT_VERSION']})")
    tv, tvv = ver("torch"), ver("torchvision")
    if IS_MAC:
        # macOS 빌드에는 CUDA 변형이 없어 +cpu 로컬 태그가 없다. lock에 잠긴 정확한 버전(PyPI macOS arm64 휠)인지 본다.
        want_t, want_v = locked_version("torch"), locked_version("torchvision")
        if tv and tv == want_t and tvv and tvv == want_v and "+" not in tv + tvv:
            rep.add(OK, f"torch {tv}, torchvision {tvv} (macOS arm64 PyPI 빌드, lock과 일치)", "GPU/MPS는 추종·녹화에 필요하지 않음")
        else:
            rep.add(FAIL, f"torch {tv}, torchvision {tvv}", f"lock 기준 torch {want_t}, torchvision {want_v} → {installer}")
    elif tv and tv.endswith("+cpu") and tvv and tvv.endswith("+cpu"):
        rep.add(OK, f"torch {tv}, torchvision {tvv} (CPU 빌드)")
    else:
        rep.add(FAIL, f"torch {tv}, torchvision {tvv}", "CPU 빌드(+cpu)가 아닙니다.")
    cuda_pkgs = sorted(d.metadata["Name"] for d in metadata.distributions() if re.match(r"^(nvidia-|triton)", d.metadata["Name"] or "", re.I))
    rep.add(OK if not cuda_pkgs else FAIL, "CUDA 전용 패키지 유입 없음" if not cuda_pkgs else f"CUDA 패키지 발견: {cuda_pkgs}")
    for n in ("feetech-servo-sdk", "pyserial", "deepdiff", "draccus"):
        v = ver(n)
        rep.add(OK if v else FAIL, f"{n} {v}")

    # 4) 설치된 lerobot 파일 = 고정 SHA checkout의 src/lerobot (바이트 비교)
    ext = WS / "external/lerobot"
    try:
        head = subprocess.run([*git_base(), "-C", str(ext), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run([*git_base(), "-C", str(ext), "status", "--porcelain"], capture_output=True, text=True).stdout.strip()
    except OSError:
        head, dirty = "", ""
    if head == lock["LEROBOT_SHA"] and not dirty:
        rep.add(OK, f"external/lerobot @ {head} (수정 없음)")
        dist = metadata.distribution("lerobot")
        files = [f for f in (dist.files or []) if str(f).startswith("lerobot/")]
        mism, missing = [], []
        for f in files:
            src = ext / "src" / str(f)
            inst = Path(dist.locate_file(f))
            if not src.is_file():
                missing.append(str(f))
            elif hashlib.sha256(src.read_bytes()).digest() != hashlib.sha256(inst.read_bytes()).digest():
                mism.append(str(f))
        if files and not mism and not missing:
            rep.add(OK, f"설치된 lerobot 파일 {len(files)}개가 고정 SHA 소스와 바이트 단위로 일치")
        else:
            rep.add(FAIL, "설치된 lerobot이 고정 SHA 소스와 다름", f"다름 {mism[:5]}, 소스에 없음 {missing[:5]}")
    else:
        rep.add(FAIL, "external/lerobot이 고정 SHA가 아니거나 수정됨", f"HEAD={head or '없음'}, dirty={bool(dirty)} → {installer}")

    # 5) 공식 모듈 import, CLI
    mods = ["lerobot.scripts.lerobot_teleoperate", "lerobot.scripts.lerobot_calibrate", "lerobot.scripts.lerobot_setup_motors",
            "lerobot.scripts.lerobot_find_port", "lerobot.robots.so_follower", "lerobot.teleoperators.so_leader",
            "lerobot.motors.feetech", "scservo_sdk", "serial"]
    import importlib

    failed = []
    for m in mods:
        try:
            importlib.import_module(m)
        except Exception as e:  # noqa: BLE001
            failed.append(f"{m}: {type(e).__name__}: {e}")
    rep.add(OK if not failed else FAIL, f"공식 모듈 import {len(mods) - len(failed)}/{len(mods)}", "; ".join(failed))
    for cli in OFFICIAL_CLIS:
        if not (VENV_BIN / cli).is_file():
            rep.add(FAIL, f"공식 CLI 없음: {cli}")
    for cli in ("lerobot-teleoperate", "lerobot-calibrate", "lerobot-setup-motors"):
        r = subprocess.run([official_cmd(cli), "--help"], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=180)
        ok = r.returncode == 0 and ("--robot" in r.stdout or "--teleop" in r.stdout)
        rep.add(OK if ok else FAIL, f"{cli} --help (exit {r.returncode})", "" if ok else (r.stderr or r.stdout)[-400:])
    rep.add(INFO, "lerobot-find-port는 USB 분리를 input()으로 기다리므로 자동 실행하지 않음(진입점 존재만 확인)")
    if IS_MAC:
        # macOS 설치는 데이터셋 생성(lerobot[dataset])까지 포함한다. 장치를 열지 않는 import·help·인코더 확인.
        import so101_dataset

        so101_dataset.doctor_dataset(rep)

    # 6) 공식 SO101 모터 맵과 래퍼 상수 일치(포트를 열지 않는 객체 생성, 임시 보정 폴더 사용)
    tmp_cal = WS / ".tmp" / "doctor_calibration"
    try:
        for role in ("leader", "follower"):
            obj = official_device(role, "/dev/so101-doctor-nonexistent", "so101-doctor-check", tmp_cal)
            motors = obj.bus.motors
            got = [(n, m.id, m.model) for n, m in motors.items()]
            want = [(n, i + 1, "sts3215") for i, n in enumerate(JOINTS)]
            assert not obj.bus.is_connected
            del obj
            rep.add(OK if got == want else FAIL, f"공식 {ROLE_TYPES[role]} 모터 맵: ID1~6 = {', '.join(n for n, _, _ in got)}",
                    "" if got == want else f"래퍼 상수와 다름: {got}")
    except Exception as e:  # noqa: BLE001
        rep.add(FAIL, "공식 모터 맵 확인 실패", f"{type(e).__name__}: {e}")

    # 7) 공식 CLI 인자 파싱(max_relative_target float/dict, time_s)
    probe_cfg = Config(WS / "-", ArmCfg("leader", "so101_leader", "l", "/dev/x"), ArmCfg("follower", "so101_follower", "f", "/dev/y"),
                       True, None, 60, None, WS / ".tmp")
    for label, mrt in (("float 5", 5.0), ("dict 6관절", {j: 5.0 for j in JOINTS})):
        probe_cfg.max_relative_target = mrt
        ok, msg = official_parse_check(build_teleop_argv(probe_cfg, 30.0))
        rep.add(OK if ok else FAIL, f"공식 teleop 인자 파싱: max_relative_target {label}", msg)

    # 8) 작업공간
    usage = os.statvfs(WS)
    free_gb = usage.f_bavail * usage.f_frsize / 1e9
    rep.add(OK if free_gb > 1 else WARN, f"작업공간 {WS} 여유 {free_gb:.1f} GB")


def doctor_hardware(rep: Report, cfg: Config | None, cfg_errors: list[str]) -> None:
    print("== 하드웨어 전제 점검(포트를 열지 않음. 모터 레지스터 확인은 probe가 담당)")
    if cfg is None or cfg_errors:
        for e in cfg_errors:
            rep.add(FAIL, "설정 오류", e)
        if cfg is None:
            return
    for role in ("leader", "follower"):
        arm = cfg.arm(role)
        if not arm.id:
            rep.add(FAIL, f"{role}.id 미지정", "물리 팔 라벨과 같은 장치 ID를 정하세요(예: so101_leader_a).")
    reals = {}
    for role in ("leader", "follower"):
        r = check_port(rep, role, cfg.arm(role).port)
        if r:
            reals[role] = r
    if len(reals) == 2 and reals["leader"] == reals["follower"]:
        rep.add(FAIL, "leader와 follower가 같은 실제 장치를 가리킴", f"{cfg.leader.port}, {cfg.follower.port} → {reals['leader']}")
    for role, real in reals.items():
        check_usb_fingerprint(rep, role, cfg.arm(role), real, strict=False)
    for role, real in reals.items():
        info = usb_info(real)
        if info:
            rep.add(INFO, f"{role} USB {info.get('idVendor')}:{info.get('idProduct')} serial={info.get('serial', '없음')} 경로={info.get('usb_path')}")
    for role in ("leader", "follower"):
        f = calibration_file(cfg, role)
        if f is None:
            continue
        if f.is_file():
            ok, msg = validate_calibration_file(f)
            rep.add(OK if ok else FAIL, f"{role} 보정 파일 {f}", msg)
        else:
            rep.add(WARN, f"{role} 보정 파일 없음: {f}", "teleop 전에 scripts/so101 calibrate " + role + " (또는 같은 팔의 보정 파일 복원)")
    if cfg.max_relative_target is None:
        rep.add(WARN, "follower.max_relative_target 미설정", "제한 없이 시작하면 첫 주기에 리더 위치가 그대로 지령됩니다. 두 팔 자세를 맞춘 뒤 시작하세요.")
    for pkg, svc in (("brltty", None), ("modemmanager", "ModemManager")):
        if Path(f"/var/lib/dpkg/info/{pkg}.list").exists():
            rep.add(INFO, f"{pkg} 설치됨", "실제로 포트가 사라지거나 점유되는 증상이 있을 때만 조치하세요(docs/HARDWARE.md).")


def validate_calibration_file(f: Path) -> tuple[bool, str]:
    """공식 형식(draccus JSON → dict[str, MotorCalibration])으로 읽고 관절·ID를 확인한다."""
    import draccus

    from lerobot.motors import MotorCalibration

    try:
        with open(f) as fh, draccus.config_type("json"):
            cal = draccus.load(dict[str, MotorCalibration], fh)
    except Exception as e:  # noqa: BLE001
        return False, f"공식 형식으로 읽기 실패: {type(e).__name__}: {e}"
    if set(cal) != set(JOINTS):
        return False, f"관절 키 불일치: {sorted(cal)}"
    bad = [j for i, j in enumerate(JOINTS) if cal[j].id != i + 1]
    if bad:
        return False, f"모터 ID 불일치: {bad}"
    # 가동 범위 기록 중 엔코더가 0↔4095로 넘어가면(가운데 자세가 범위 중간이 아니었을 때) 범위가 거의 0~4095로 저장된다.
    # wrist_roll(공식 코드가 0~4095로 고정)을 뺀 관절은 물리적으로 한 바퀴를 돌지 않으므로 이런 범위는 잘못된 보정이다.
    # 이 상태로 추종하면 리더 값이 경계를 넘는 순간 팔로워 목표가 반대쪽 끝으로 튈 수 있다.
    wrapped = [f"{j}({cal[j].range_min}~{cal[j].range_max})" for j in JOINTS
               if j != "wrist_roll" and cal[j].range_min <= WRAP_EDGE and cal[j].range_max >= 4095 - WRAP_EDGE]
    if wrapped:
        return False, ("가동 범위가 0~4095 전체로 저장됨(엔코더 넘어감): " + ", ".join(wrapped)
                       + " → 가운데 자세를 각 관절 가동 범위의 실제 중간에 두고 다시 보정하세요(docs/SETUP.md 6번).")
    return True, "공식 형식, 6개 관절, ID 1~6, 가동 범위 정상"


def cmd_doctor(args, cfg, cfg_errors) -> int:
    rep = Report()
    doctor_software(rep)
    if args.scope == "hardware":
        doctor_hardware(rep, cfg, cfg_errors)
    print(f"\n결과: FAIL {rep.n_fail}, WARN {rep.n_warn}  (종료 코드 0=OK, 1=FAIL, 2=WARN만)")
    return rep.exit_code()


# --------------------------------------------------------------------------------------------
# ports
# --------------------------------------------------------------------------------------------
def cmd_ports(args, cfg, cfg_errors) -> int:
    if IS_MAC:
        return cmd_ports_mac(cfg)
    links = serial_links()
    devs = serial_devices()
    if not devs:
        print("USB 시리얼 장치가 없습니다(/dev/serial, /dev/ttyACM*, /dev/ttyUSB*). 보드 USB 연결과 보드 전원 필요 여부를 확인하세요.")
        return 0
    seen_serial: dict[tuple, list[str]] = {}
    for real in devs:
        info = usb_info(real)
        print(f"\n{real}")
        print(f"  USB {info.get('idVendor', '?')}:{info.get('idProduct', '?')}  {info.get('manufacturer', '')} {info.get('product', '')}".rstrip())
        print(f"  serial={info.get('serial', '(없음)')}  USB 경로={info.get('usb_path', '?')}")
        for l in links.get(real, []):
            print(f"  ← {l}")
        if len([l for l in links.get(real, []) if '/by-id/' in l]) == 0:
            print("  (by-id 링크 없음 → by-path 사용)")
        key = (info.get("idVendor"), info.get("idProduct"), info.get("serial"))
        if info.get("serial"):
            seen_serial.setdefault(key, []).append(real)
    dup = {k: v for k, v in seen_serial.items() if len(v) > 1}
    if dup:
        print("\n[WARN] 같은 VID:PID:serial을 가진 장치가 여러 개입니다. by-id가 하나만 남거나 바뀔 수 있으니 by-path를 쓰세요:", dup)
    if cfg:
        print("\n설정(configs/robot.local.yaml) 매핑:")
        for role in ("leader", "follower"):
            p = cfg.arm(role).port
            print(f"  {role}: {p} → {os.path.realpath(p) if p and os.path.lexists(p) else '(없음)'}")
    return 0


def mac_usb_device_names() -> list[str]:
    """진단용: IOKit USB 트리의 장치 이름(ioreg, 읽기 전용). 시리얼 노드가 없는 USB 장치도 보인다."""
    try:
        r = subprocess.run(["/usr/sbin/ioreg", "-p", "IOUSB", "-w0"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return []
    names = []
    for line in r.stdout.splitlines():
        m = re.search(r"\+-o (.+?)@[0-9a-fA-F]+\s+<class", line)
        if m:
            names.append(m.group(1))
    return names


def describe_usb(u: dict[str, Any]) -> str:
    who = " ".join(x for x in (u.get("manufacturer"), u.get("product")) if x and x != "n/a")
    return (f"{u['device']}  (별칭 {' '.join(a for a in mac_aliases(u['device']) if a != u['device']) or '없음'})\n"
            f"    USB {u['vid']}:{u['pid']}  {who}\n"
            f"    serial={u['serial'] or '(없음)'}  USB 위치={u['location'] or '?'}")


def cmd_ports_mac(cfg: Config | None) -> int:
    ports = mac_usb_ports()
    if not ports:
        print("USB 시리얼 장치가 없습니다(pyserial/IOKit 기준. Bluetooth·debug-console 등 비USB 항목은 제외).")
        print("보드 USB 연결, 데이터 전송 가능한 케이블, 허브를 확인하세요. 보드에 따라 서보 전원이 있어야 보일 수 있습니다.")
    for u in ports:
        print("\n" + describe_usb(u))
    keyed: dict[tuple, list[str]] = {}
    for u in ports:
        if u["serial"]:
            keyed.setdefault((u["vid"], u["pid"], u["serial"]), []).append(u["device"])
    dup = {k: v for k, v in keyed.items() if len(v) > 1}
    if dup:
        print("\n[WARN] 같은 VID:PID:serial을 가진 장치가 여러 개입니다. serial로 구분할 수 없어 USB 위치(같은 단자)로 구분해야 합니다:", dup)
    if cfg:
        print("\n설정(configs/robot.local.yaml) 매핑:")
        rep = Report()
        for role in ("leader", "follower"):
            arm = cfg.arm(role)
            if not arm.port:
                print(f"  {role}: (port 미지정) → ./01_setup/ports.sh")
                continue
            real = canonical_port(arm.port)
            print(f"  {role}: {arm.port} → {real if os.path.lexists(arm.port) else '(없음)'}  id={arm.id}")
            if os.path.lexists(arm.port):
                check_usb_fingerprint(rep, role, arm, real, strict=False)
    return 0


# ---- 포트 지정 마법사(./01_setup/ports.sh): USB 연결 전후 장치 목록 차이로 역할별 포트를 찾고 설정에 저장 ----
EXAMPLE_CONFIG = WS / "configs" / "robot.example.yaml"


def _yaml_scalar(v: str | None) -> str:
    if v is None:
        return "null"
    if re.fullmatch(r"[A-Za-z/][A-Za-z0-9_./:-]*", v) and v.lower() not in ("null", "true", "false", "yes", "no", "on", "off", "y", "n", "~"):
        return v
    return json.dumps(v, ensure_ascii=False)


def _usb_flow(fp: dict[str, str | None]) -> str:
    return "{" + ", ".join(f"{k}: {json.dumps(fp.get(k)) if fp.get(k) is not None else 'null'}" for k in USB_KEYS) + "}"


def edit_arm_block(text: str, role: str, updates: dict[str, str]) -> str:
    """robot YAML 텍스트에서 '<role>:' 블록의 2칸 들여쓴 키 값만 바꾼다(주석·다른 줄 보존). 키가 없으면 블록에 추가.
    구조가 예상과 다르면 ValueError(자동 수정하지 않음)."""
    lines = text.splitlines(keepends=True)
    heads = [i for i, ln in enumerate(lines) if re.match(rf"^{role}:\s*(#.*)?$", ln.rstrip("\r\n"))]
    if len(heads) != 1:
        raise ValueError(f"'{role}:' 최상위 블록을 하나 찾지 못했습니다({len(heads)}개).")
    start = heads[0]
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"^[^\s#]", lines[i])), len(lines))
    for key, val in updates.items():
        idx = [i for i in range(start + 1, end) if re.match(rf"^  {key}:(\s|$)", lines[i])]
        if len(idx) > 1:
            raise ValueError(f"{role}.{key}가 여러 번 있습니다.")
        if idx:
            i = idx[0]
            nl = "\n" if lines[i].endswith("\n") else ""
            m = re.match(rf"^(  {key}:)([ \t]*)([^#\n]*?)([ \t]*)(#.*)?$", lines[i].rstrip("\r\n"))
            if not m:
                raise ValueError(f"{role}.{key} 줄을 해석하지 못했습니다: {lines[i]!r}")
            core = f"{m.group(1)} {val}"
            if m.group(5):
                col = len(m.group(1)) + len(m.group(2)) + len(m.group(3)) + len(m.group(4))
                core += " " * max(1, col - len(core)) + m.group(5)
            lines[i] = core + nl
        else:
            after = [i for i in range(start + 1, end) if re.match(r"^  (port|id|type):", lines[i])]
            pos = (after[-1] + 1) if after else start + 1
            lines.insert(pos, f"  {key}: {val}\n")
            end += 1
    return "".join(lines)


def usb_fingerprint_for(u: dict[str, Any], all_ports: list[dict[str, Any]]) -> tuple[dict[str, str | None] | None, str]:
    """고유 serial이 있으면 serial 기준, 없거나 중복이면 USB 위치 기준. 둘 다 없으면 None(구분 불가)."""
    fp = {"vid": u["vid"], "pid": u["pid"], "serial": u["serial"], "location": u["location"]}
    if u["serial"]:
        dup = [x["device"] for x in all_ports
               if x["device"] != u["device"] and (x["vid"], x["pid"], x["serial"]) == (u["vid"], u["pid"], u["serial"])]
        if not dup:
            return {**fp, "id_by": "serial"}, "고유 serial 기준(다른 USB 단자로 옮겨도 같은 보드로 확인됨)"
        why = f"serial이 다른 장치({', '.join(dup)})와 같음"
    else:
        why = "serial 없음"
    if u["location"]:
        return {**fp, "id_by": "location"}, f"{why} → USB 위치 기준: 앞으로 항상 같은 USB 단자(같은 허브 포트)에 연결하세요"
    return None, f"{why}, USB 위치 정보도 없어 보드를 구분할 수 없음"


def _scan_new(prev: set[str], wait_s: float = 3.0) -> list[dict[str, Any]]:
    """새 장치가 나타날 때까지 최대 wait_s 동안 0.5초 간격으로 다시 열거한다(읽기 전용)."""
    deadline = time.time() + wait_s
    while True:
        now = mac_usb_ports()
        if any(u["device"] not in prev for u in now) or time.time() >= deadline:
            return now
        time.sleep(0.5)


def _choose(role: str, cands: list[dict[str, Any]], ask: Callable[[str], str]) -> dict[str, Any] | None:
    if len(cands) == 1:
        return cands[0]
    print(f"\n새 USB 시리얼 장치가 {len(cands)}개 보입니다. 발견 순서로 역할을 정하지 않습니다. {role} 보드를 직접 고르세요:")
    for n, u in enumerate(cands, 1):
        print(f"  [{n}] " + describe_usb(u).replace("\n", "\n      "))
    while True:
        a = ask(f"{role} 보드 번호(1~{len(cands)}), 다시 확인=r, 취소=q: ").strip().lower()
        if a == "q":
            raise KeyboardInterrupt
        if a == "r":
            return None
        if a.isdigit() and 1 <= int(a) <= len(cands):
            return cands[int(a) - 1]
        print("번호를 다시 입력하세요.")


def _detect_role(role: str, prev: set[str], ask: Callable[[str], str], scan: Callable[[set[str]], list]) -> tuple[dict, list]:
    label = {"leader": "리더(손으로 움직이는 팔)", "follower": "팔로워(따라 움직이는 팔)"}[role]
    ask(f"\n{label} 보드의 USB만 맥에 연결하고 Enter (취소: Ctrl+C): ")
    while True:
        now = scan(prev)
        cands = [u for u in now if u["device"] not in prev]
        gone = [d for d in prev if d not in {u["device"] for u in now}]
        if gone:
            print(f"[WARN] 이전에 보이던 장치가 사라졌습니다: {gone}. 케이블이 빠지지 않았는지 확인하세요.")
        if cands:
            pick = _choose(role, cands, ask)
            if pick is not None:
                return pick, now
        else:
            print("\n새 USB 시리얼 장치가 보이지 않습니다.")
            print("  - 데이터 전송 가능한 케이블인지, 허브/어댑터에 확실히 꽂혔는지 확인하세요.")
            print("  - 보드에 따라 USB만으로는 포트가 보이지 않을 수 있습니다(서보 전원 필요). 그 경우 docs/HARDWARE.md 확인표로")
            print("    전압·극성을 확인한 뒤 전원을 넣고 다시 확인하세요.")
            names = mac_usb_device_names()
            if names:
                print("  - 참고: 현재 USB 장치 트리(ioreg):", ", ".join(names[:12]))
        a = ask("다시 확인=Enter, 취소=q: ").strip().lower()
        if a == "q":
            raise KeyboardInterrupt


def _ask_id(role: str, current: str | None, other: str | None, ask: Callable[[str], str]) -> str:
    print(f"\n{role} 장치 ID: 물리 팔 라벨과 같은 이름이며 보정 파일 이름(<id>.json)이 됩니다. 모터 ID 1~6과 다릅니다.")
    while True:
        hint = f" [Enter=기존 값 유지: {current}]" if current else f" (예: so101_{role}_a — 직접 입력)"
        v = ask(f"{role} 장치 ID{hint}: ").strip()
        if not v and current:
            v = current
        if not v:
            print("ID를 입력하세요. 예시 값을 자동으로 쓰지 않습니다.")
            continue
        if not ID_RE.match(v):
            print("영문/숫자로 시작하고 영문/숫자/_.- 만 쓸 수 있습니다(최대 64자).")
            continue
        if other and v == other:
            print("리더와 팔로워에 같은 ID를 쓰지 않습니다(보정 파일 혼동 방지). 다른 ID를 입력하세요.")
            continue
        return v


def save_config_atomic(target: Path, new_text: str) -> Path | None:
    """백업(기존 파일이 있으면) → 같은 폴더 임시 파일에 쓰고 fsync → os.replace. 반환: 백업 경로."""
    import tempfile

    target.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if target.exists():
        backup = target.with_name(f"{target.name}.bak-{time.strftime('%Y%m%d_%H%M%S')}")
        n = 1
        while backup.exists():
            backup = target.with_name(f"{target.name}.bak-{time.strftime('%Y%m%d_%H%M%S')}-{n}")
            n += 1
        backup.write_bytes(target.read_bytes())
    fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    dfd = os.open(str(target.parent), os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)
    return backup


def cmd_assign_ports(args, cfg, cfg_errors, *, ask: Callable[[str], str] = input,
                     scan: Callable[[set[str]], list] | None = None) -> int:
    """USB 포트 지정 마법사(포트를 열지 않음). 자동화 범위: 포트 식별·장치 ID 확인·설정 저장까지."""
    import difflib

    import yaml

    if not IS_MAC:
        print("이 마법사는 macOS용입니다. Linux는 README 4절(scripts/so101 ports, by-id/by-path)을 따르세요.")
        return 2
    scan = scan or _scan_new
    target: Path = args.config
    if target.exists():
        old_text = target.read_text(encoding="utf-8")
        cfg0, errs = load_config(target)
        if errs:
            print(f"[FAIL] 기존 설정 {target}에 오류가 있어 자동으로 수정하지 않습니다:")
            for e in errs:
                print("   -", e)
            return 1
    else:
        old_text = EXAMPLE_CONFIG.read_text(encoding="utf-8")
        cfg0 = None
        print(f"[INFO] {target}이 없어 {EXAMPLE_CONFIG.relative_to(WS)}를 바탕으로 새로 만듭니다(저장 전 확인).")
    try:
        old_parsed = yaml.safe_load(old_text) or {}
        print("== USB 포트 지정(포트를 열지 않고 장치 목록만 읽습니다)")
        print("1) 모터 외부 전원(어댑터)을 모두 끄고, 리더·팔로워 보드의 USB를 맥에서 모두 뽑으세요.")
        ask("   준비되면 Enter (취소: Ctrl+C): ")
        base = mac_usb_ports()
        if base:
            print("\n[INFO] 지금 연결된 USB 시리얼 장치(로봇 보드가 아니어야 함):")
            for u in base:
                print("  " + describe_usb(u).replace("\n", "\n  "))
            print("로봇 보드가 이 목록에 있으면 뽑고 다시 실행하세요. 이 장치들은 후보에서 제외됩니다.")
        prev = {u["device"] for u in base}
        leader, now1 = _detect_role("leader", prev, ask, scan)
        print("\n리더 보드:\n  " + describe_usb(leader).replace("\n", "\n  "))
        # 팔로워 후보 = 리더 단계 이후 새로 나타난 장치만(리더 단계에 함께 나타났지만 고르지 않은 장치는 제외)
        follower, now2 = _detect_role("follower", prev | {u["device"] for u in now1} | {leader["device"]}, ask, scan)
        print("\n팔로워 보드:\n  " + describe_usb(follower).replace("\n", "\n  "))
        devs_now = {u["device"] for u in now2}
        if leader["device"] not in devs_now:
            print("[FAIL] 팔로워를 연결하는 동안 리더 보드가 사라졌습니다. 두 보드를 모두 연결한 상태로 다시 실행하세요.")
            return 1
        if leader["device"] == follower["device"]:
            print("[FAIL] 두 역할이 같은 장치를 가리킵니다. 저장하지 않습니다.")
            return 1
        fps, notes = {}, {}
        for role, u in (("leader", leader), ("follower", follower)):
            fp, note = usb_fingerprint_for(u, now2)
            if fp is None:
                print(f"[FAIL] {role}: {note}. 자동 지정을 거부합니다. 보드·허브를 바꿔 다시 확인하거나 docs/SETUP.md의 수동 절차를 따르세요.")
                return 1
            fps[role], notes[role] = fp, note
        if fps["leader"]["id_by"] == fps["follower"]["id_by"] == "location" and fps["leader"]["location"] == fps["follower"]["location"]:
            print("[FAIL] 두 보드의 USB 위치가 같아 구분할 수 없습니다. 저장하지 않습니다.")
            return 1
        cur_ids = {r: (cfg0.arm(r).id if cfg0 else None) for r in ("leader", "follower")}
        lid = _ask_id("leader", cur_ids["leader"], None, ask)
        fid = _ask_id("follower", cur_ids["follower"], lid, ask)
        ids = {"leader": lid, "follower": fid}
        new_text = old_text
        for role, u in (("leader", leader), ("follower", follower)):
            new_text = edit_arm_block(new_text, role, {"id": _yaml_scalar(ids[role]), "port": _yaml_scalar(u["device"]),
                                                       "usb": _usb_flow(fps[role])})
        new_parsed = yaml.safe_load(new_text) or {}
        expected = json.loads(json.dumps(old_parsed))
        for role, u in (("leader", leader), ("follower", follower)):
            expected.setdefault(role, {}).update({"id": ids[role], "port": u["device"], "usb": fps[role]})
        if new_parsed != expected:
            print("[FAIL] 편집 결과 검증 실패(바꾼 키 외 값이 달라짐). 저장하지 않습니다.")
            return 1
        # 공식 형식 검증(포트 존재는 보지 않음)
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".yaml", dir=str(WS / ".tmp") if (WS / ".tmp").is_dir() else None,
                                         delete=False, encoding="utf-8") as tf:
            tf.write(new_text)
        try:
            _, errs = load_config(Path(tf.name))
        finally:
            os.unlink(tf.name)
        if errs:
            print("[FAIL] 새 설정 검증 실패. 저장하지 않습니다:", errs)
            return 1
        print("\n== 저장할 내용")
        for role, u in (("leader", leader), ("follower", follower)):
            print(f"  {role}: id={ids[role]}  port={u['device']}  ({notes[role]})")
        diff = "".join(difflib.unified_diff(old_text.splitlines(True), new_text.splitlines(True),
                                            fromfile=f"{target.name} (기존)" if target.exists() else EXAMPLE_CONFIG.name,
                                            tofile=f"{target.name} (새)"))
        print(diff or "(변경 없음)")
        if ask(f"\n{target}에 저장하려면 yes 입력: ").strip() != "yes":
            print("취소: 설정을 바꾸지 않았습니다.")
            return 1
        backup = save_config_atomic(target, new_text)
    except (KeyboardInterrupt, EOFError):
        print("\n취소: 설정을 바꾸지 않았습니다.")
        return 1
    except ValueError as e:
        print(f"[FAIL] 설정 파일 구조가 예상과 달라 자동으로 수정하지 않습니다: {e}")
        print("       configs/robot.local.yaml의 leader/follower 아래 id·port를 직접 고치거나, 파일을 옮겨 둔 뒤 다시 실행하세요.")
        return 1
    print(f"\n[OK] 저장: {target}" + (f"  (백업: {backup.name})" if backup else ""))
    append_run_log({"ts": now_iso(), "host": socket.gethostname(), "cmd": "assign-ports",
                    "leader": {"id": lid, "port": leader["device"], "usb": fps["leader"]},
                    "follower": {"id": fid, "port": follower["device"], "usb": fps["follower"]},
                    "backup": str(backup) if backup else None})
    print("\n다음 순서(이 마법사는 포트를 열거나 모터를 움직이지 않았습니다):")
    print("  1. ./01_setup/doctor.sh --hardware        # 포트·지문·보정 파일 점검(포트를 열지 않음)")
    print("  2. docs/HARDWARE.md 2절 확인표: 모터 라벨 전압·어댑터 정격·극성·배선 확인 → 각 팔에 맞는 전원 연결")
    print("  3. ./01_setup/probe.sh follower ; ./01_setup/probe.sh leader   # 읽기 전용 모터 확인")
    print("  4. (ID 누락·충돌이 확인된 팔만) ./01_setup/motors.sh <role>")
    print("  5. ./01_setup/calibrate.sh follower ; ./01_setup/calibrate.sh leader")
    print("  6. ./02_teleop/run.sh --dry-run → ./02_teleop/run.sh --time-s 30")
    return 0


# --------------------------------------------------------------------------------------------
# probe (명시적 실기 읽기. 모터에 쓰지 않는다)
# --------------------------------------------------------------------------------------------
PROBE_REGS = ("Present_Position", "Torque_Enable", "Operating_Mode", "Homing_Offset", "Min_Position_Limit",
              "Max_Position_Limit", "Firmware_Major_Version", "Firmware_Minor_Version")


def probe_arm(role: str, port: str, dev_id: str | None, *, bus_factory: Callable | None = None) -> dict:
    """읽기 전용 모터 확인.
    호출하는 공식 API: FeetechMotorsBus(생성), bus.connect(handshake=False)(포트 열기+timeout 설정),
    bus.ping / bus.read / bus.sync_read(읽기), bus.disconnect(disable_torque=False)(포트 닫기만).
    공식 Robot/Teleoperator의 connect/configure/calibrate와 bus.connect(handshake=True)는 쓰지 않는다
    (handshake=True는 읽기뿐이지만 펌웨어가 다르면 예외로 끝나서 관절별 진단을 못 함)."""
    res: dict[str, Any] = {"role": role, "port": port, "id": dev_id, "joints": {}, "errors": []}
    bus = (bus_factory or make_bus)(role, port, dev_id)
    file_cal = dict(bus.calibration or {})
    try:
        try:
            bus.connect(handshake=False)
        except Exception as e:  # noqa: BLE001
            res["errors"].append(f"포트 열기 실패: {type(e).__name__}: {e}")
            res["port_open"] = False
            return res
        res["port_open"] = True
        expected_model = bus.model_number_table["sts3215"]
        for name in JOINTS:
            j: dict[str, Any] = {"id": bus.motors[name].id}
            try:
                j["model"] = bus.ping(name, num_retry=1, raise_on_error=True)
            except Exception as e:  # noqa: BLE001
                j["ping_error"] = str(e).strip()
                res["joints"][name] = j
                continue
            for reg in PROBE_REGS:
                try:
                    j[reg] = bus.read(reg, name, normalize=False, num_retry=1)
                except Exception as e:  # noqa: BLE001
                    j.setdefault("read_errors", {})[reg] = str(e).strip()[:120]
            j["model_ok"] = j["model"] == expected_model
            res["joints"][name] = j
        # 보정 파일 대 모터 레지스터(공식 is_calibrated가 비교하는 필드: homing_offset, range_min, range_max)
        cmp: dict[str, Any] = {}
        for name in JOINTS:
            j = res["joints"][name]
            if name not in file_cal or "ping_error" in j or j.get("read_errors"):
                continue
            c = file_cal[name]
            diffs = {k: (getattr(c, a), j[r]) for k, a, r in (("homing_offset", "homing_offset", "Homing_Offset"),
                                                               ("range_min", "range_min", "Min_Position_Limit"),
                                                               ("range_max", "range_max", "Max_Position_Limit")) if getattr(c, a) != j[r]}
            if c.id != j["id"]:
                diffs["id"] = (c.id, j["id"])
            cmp[name] = diffs
        res["calib_compare"] = cmp
        all_ok = all(res["joints"][n].get("model_ok") and not res["joints"][n].get("read_errors") for n in JOINTS)
        res["comm_ok"] = all_ok
        fw = {n: f"{res['joints'][n].get('Firmware_Major_Version')}.{res['joints'][n].get('Firmware_Minor_Version')}"
              for n in JOINTS if "ping_error" not in res["joints"][n]}
        res["firmware"] = fw
        res["firmware_same"] = len(set(fw.values())) <= 1
        if not file_cal:
            res["calib_status"] = "missing"
        elif all_ok and len(cmp) == 6:
            res["calib_status"] = "match" if not any(cmp.values()) else "mismatch"
        else:
            res["calib_status"] = "unknown"
        if all_ok and res["calib_status"] == "match":
            try:
                res["normalized"] = bus.sync_read("Present_Position", normalize=True, num_retry=1)
            except Exception as e:  # noqa: BLE001
                res["errors"].append(f"정규화 위치 sync_read 실패: {e}")
        return res
    finally:
        if bus.is_connected:
            bus.disconnect(disable_torque=False)  # 포트만 닫는다(토크 쓰기 없음)


def print_probe(res: dict) -> None:
    print(f"\n== probe {res['role']} ({res['id']}) {res['port']}")
    for e in res["errors"]:
        print(f"  [FAIL] {e}")
    if not res.get("port_open"):
        return
    print(f"  {'관절':<14}{'ID':>3} {'모델':>6} {'펌웨어':>7} {'위치(raw)':>9} {'토크':>4} {'모드':>4} {'offset':>7} {'min':>5} {'max':>5}  보정파일")
    for name in JOINTS:
        j = res["joints"][name]
        if "ping_error" in j:
            print(f"  {name:<14}{j['id']:>3}  응답 없음/오류: {j['ping_error'][:90]}")
            continue
        g = lambda r: j.get(r, "ERR")  # noqa: E731
        cmpd = res.get("calib_compare", {}).get(name)
        cs = "-" if cmpd is None else ("일치" if not cmpd else "불일치 " + ", ".join(f"{k}:파일 {a}≠모터 {b}" for k, (a, b) in cmpd.items()))
        mark = "" if j.get("model_ok") else "  ←모델 번호 다름"
        print(f"  {name:<14}{j['id']:>3} {g('model') if 'model' in j else '?':>6} {g('Firmware_Major_Version')}.{g('Firmware_Minor_Version'):<5}"
              f" {g('Present_Position'):>9} {g('Torque_Enable'):>4} {g('Operating_Mode'):>4} {g('Homing_Offset'):>7}"
              f" {g('Min_Position_Limit'):>5} {g('Max_Position_Limit'):>5}  {cs}{mark}")
        if j.get("read_errors"):
            print(f"      읽기 오류: {j['read_errors']}")
    n_ok = sum(1 for n in JOINTS if res["joints"][n].get("model_ok"))
    print(f"  응답·모델 일치: {n_ok}/6")
    if not res.get("firmware_same"):
        print("  [WARN] 펌웨어 버전이 서로 다릅니다:", res.get("firmware"))
        print("         공식 connect의 handshake(_assert_same_firmware)가 이 조건에서 실패하므로 공식 calibrate/teleop이 연결되지 않습니다.")
        print("         펌웨어 갱신은 Feetech 공식 도구로 사용자가 판단해 진행하세요. 이 래퍼는 갱신·초기화를 하지 않습니다.")
    if n_ok < 6:
        print("  [FAIL] 응답하지 않거나 모델이 다른 모터가 있습니다. 점검 순서: 전원 → 케이블(보드↔1번, 체인) → 보드 모드 → 포트 →")
        print("         baud(`probe --scan`). 그다음에도 ID 누락/충돌이면 공식 setup-motors(모터 하나씩 연결)를 검토하세요.")
    print(f"  보정 파일 상태: {res.get('calib_status')}  (match=공식 is_calibrated와 같은 필드 일치)")
    if res.get("normalized"):
        print("  현재 위치(정규화, 몸체=도, gripper=0~100):", {k: round(v, 1) for k, v in res["normalized"].items()})
    print("  참고: 정상 응답은 '해당 ID가 응답했다'는 뜻이며, 중복 ID 부재·관절 물리 배치·6개 실물 존재를 완전히 증명하지 않습니다.")


def cmd_probe(args, cfg, cfg_errors) -> int:
    if cfg is None or cfg_errors:
        for e in cfg_errors:
            print("[FAIL] 설정:", e)
        return 1
    roles = ["leader", "follower"] if args.role == "both" else [args.role]
    rc = 0
    for role in roles:
        rep = Report()
        arm = cfg.arm(role)
        if not arm.id:
            rep.add(FAIL, f"{role}.id 미지정")
        real = check_port(rep, role, arm.port)
        if real:
            check_usb_fingerprint(rep, role, arm, real, strict=False)
        if rep.n_fail:
            rc = 1
            continue
        if args.scan:
            from lerobot.motors.feetech import FeetechMotorsBus

            print(f"[{role}] 공식 FeetechMotorsBus.scan_port: 호스트 포트 baud를 바꿔 가며 broadcast ping(모터 EEPROM baud 쓰기 아님)")
            print(FeetechMotorsBus.scan_port(real))
            continue
        res = probe_arm(role, arm.port, arm.id)
        print_probe(res)
        append_run_log({"ts": now_iso(), "host": socket.gethostname(), "cmd": "probe", "role": role, "port": arm.port, "id": arm.id,
                        "comm_ok": res.get("comm_ok"), "firmware": res.get("firmware"), "calib_status": res.get("calib_status"),
                        "errors": res["errors"]})
        if not res.get("comm_ok"):
            rc = 1
    return rc


# --------------------------------------------------------------------------------------------
# 공식 프로세스 실행(신호 전달·출력 중계·기록)
# --------------------------------------------------------------------------------------------
LOOP_RE = re.compile(rb"Teleop loop time: ([0-9.]+)ms")
# 공식 lerobot-record의 루프 지연 경고(실제 녹화 루프가 목표 FPS보다 느릴 때). 저장 timestamp는 frame_index/fps라 이 경고가 실측 근거다.
RECORD_SLOW_RE = re.compile(rb"Record loop is running slower \(([0-9.]+) Hz\)")


def _child_preexec(parent_pid: int) -> None:
    # 터미널 hangup(SSH 끊김)에서 자식이 정리 없이 즉시 죽지 않게 SIGHUP을 무시하고, 부모가 SIGINT를 전달한다.
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    # 부모(래퍼)가 비정상 종료하면 자식에게 SIGINT를 보내 고아로 계속 구동되지 않게 한다(Linux prctl).
    # macOS에는 prctl이 없다. 대신 자식을 scripts/so101_launch.py(kqueue 부모 감시)로 실행한다(run_official).
    if not IS_MAC:
        try:
            libc = ctypes.CDLL("libc.so.6", use_errno=True)
            libc.prctl(1, signal.SIGINT)  # PR_SET_PDEATHSIG
        except OSError:
            pass
    if os.getppid() != parent_pid:
        os.kill(os.getpid(), signal.SIGINT)


def run_official(argv: list[str], *, env: dict[str, str], log_name: str, parse_loop: bool = False,
                 after_exit: Callable[[], dict] | None = None, interrupt_grace: float = INTERRUPT_GRACE_S,
                 term_grace: float = TERM_GRACE_S, extra: dict | None = None, keep_awake: bool = False) -> dict:
    """공식 CLI를 자식으로 실행한다.
    - stdin은 터미널을 그대로 물려준다(공식 input() 프롬프트 유지). 같은 프로세스 그룹이라 Ctrl+C는 자식이 직접 받는다.
      부모는 SIGINT를 전달하지 않는다(중복 SIGINT 방지).
    - SIGTERM/SIGHUP을 받으면 자식에게 SIGINT를 한 번 전달하고, 한도 시간 뒤 SIGTERM → SIGKILL로 올린다.
    - stdout/stderr는 부모가 터미널과 logs/<log_name>.log로 중계한다. 추종 루프 출력으로 실제 루프 구간과 Hz를 기록한다.
    - 자식 종료 후 after_exit(예: 양팔 토크 해제 재시도)를 실행하고 결과를 함께 기록한다.
    - macOS: 자식을 so101_launch.py로 감싸 부모 사망 감시(kqueue)를 하고, keep_awake=True(팔을 쓰는 명령)이면
      `caffeinate -i -w <자식 PID>`로 자식이 사는 동안만 유휴 절전을 막는다(덮개 닫기 절전은 막지 못함)."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = LOG_DIR / f"{log_name}.log"
    rec: dict[str, Any] = {"ts_start": now_iso(), "host": socket.gethostname(), "argv": argv, "log": str(raw_path.relative_to(WS)),
                           **(extra or {})}
    t0 = time.time()
    state = {"interrupt_at": None, "forwarded": None, "tty_ok": True, "escalated": []}
    loop = {"first": None, "last": None, "n": 0, "ms": [], "slow": []}
    parent_pid = os.getpid()
    popen_argv = [sys.executable, str(LAUNCHER), str(parent_pid), "--", *argv] if IS_MAC else argv
    if IS_MAC:
        rec["launcher"] = "scripts/so101_launch.py(kqueue 부모 감시)"
    proc = subprocess.Popen(popen_argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0,
                            preexec_fn=lambda: _child_preexec(parent_pid))
    caff = None
    if IS_MAC and keep_awake:
        try:
            caff = subprocess.Popen(["/usr/bin/caffeinate", "-i", "-w", str(proc.pid)], stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            rec["keep_awake"] = {"caffeinate_pid": caff.pid}
        except OSError as e:
            rec["keep_awake"] = {"error": str(e)}
            print(f"[so101] 경고: caffeinate 실행 실패({e}). 실행 중 맥이 잠들지 않게 직접 확인하세요.", file=sys.stderr)

    def on_sigint(signum, frame):  # 터미널 Ctrl+C: 자식도 직접 받았으므로 기록만
        if state["interrupt_at"] is None:
            state["interrupt_at"] = time.time()

    def on_forward(signum, frame):
        if signum == signal.SIGHUP:
            state["tty_ok"] = False
        if state["forwarded"] is None and proc.poll() is None:
            state["forwarded"] = signal.Signals(signum).name
            state["interrupt_at"] = state["interrupt_at"] or time.time()
            try:
                proc.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass

    old = {s: signal.signal(s, h) for s, h in ((signal.SIGINT, on_sigint), (signal.SIGTERM, on_forward), (signal.SIGHUP, on_forward))}
    fd = proc.stdout.fileno()
    buf = b""
    try:
        with open(raw_path, "ab") as raw:
            raw.write(f"\n===== {rec['ts_start']} {' '.join(argv)}\n".encode())
            eof = False
            while True:
                if not eof:
                    r, _, _ = select.select([fd], [], [], 0.5)
                    if r:
                        chunk = os.read(fd, 65536)
                        if not chunk:
                            eof = True
                        else:
                            raw.write(chunk)
                            raw.flush()
                            if state["tty_ok"]:
                                try:
                                    sys.stdout.buffer.write(chunk)
                                    sys.stdout.buffer.flush()
                                except OSError:
                                    state["tty_ok"] = False
                            if parse_loop:
                                buf += chunk
                                *lines, buf = buf.split(b"\n")
                                for ln in lines:
                                    ms = RECORD_SLOW_RE.search(ln)
                                    if ms:
                                        loop["slow"].append(float(ms.group(1)))
                                    m = LOOP_RE.search(ln)
                                    if m:
                                        tnow = time.time()
                                        loop["first"] = loop["first"] or tnow
                                        loop["last"] = tnow
                                        loop["n"] += 1
                                        loop["ms"].append(float(m.group(1)))
                if eof and proc.poll() is not None:
                    break
                if proc.poll() is not None and eof:
                    break
                ia = state["interrupt_at"]
                if ia is not None and proc.poll() is None:
                    el = time.time() - ia
                    if el > interrupt_grace + term_grace and "SIGKILL" not in state["escalated"]:
                        proc.kill()
                        state["escalated"].append("SIGKILL")
                    elif el > interrupt_grace and "SIGTERM" not in state["escalated"]:
                        proc.terminate()
                        state["escalated"].append("SIGTERM")
                if eof:
                    try:
                        proc.wait(timeout=0.5)
                    except subprocess.TimeoutExpired:
                        pass
    finally:
        if proc.poll() is None:  # 래퍼 내부 예외 등으로 빠져나온 경우에도 자식을 남기지 않는다
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=interrupt_grace)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        for s, h in old.items():
            signal.signal(s, h)
        if caff is not None:  # 자식 종료와 함께 끝나지만(-w), 어떤 경로로 나와도 남기지 않는다
            if caff.poll() is None:
                caff.terminate()
                try:
                    caff.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    caff.kill()
                    caff.wait()
            rec["keep_awake"]["ended"] = True
            rec["keep_awake"]["exit_code"] = caff.returncode
    rc = proc.returncode
    rec.update({"ts_end": now_iso(), "duration_s": round(time.time() - t0, 2), "exit_code": rc,
                "exit_signal": signal.Signals(-rc).name if rc is not None and rc < 0 else None,
                "user_interrupt": state["interrupt_at"] is not None and state["forwarded"] is None,
                "forwarded_signal": state["forwarded"], "escalated": state["escalated"]})
    if parse_loop:
        ms = sorted(loop["ms"])
        rec["teleop_loop"] = {
            "loop_lines": loop["n"],
            "first_loop_at": time.strftime("%H:%M:%S", time.localtime(loop["first"])) if loop["first"] else None,
            "last_loop_at": time.strftime("%H:%M:%S", time.localtime(loop["last"])) if loop["last"] else None,
            "loop_span_s": round(loop["last"] - loop["first"], 2) if loop["first"] else 0.0,
            "loop_ms_median": ms[len(ms) // 2] if ms else None,
            "loop_ms_p95": ms[int(len(ms) * 0.95)] if ms else None,
            "loop_ms_max": ms[-1] if ms else None,
            "hz_median": round(1000 / ms[len(ms) // 2], 1) if ms and ms[len(ms) // 2] > 0 else None,
        }
        if loop["slow"]:
            rec["record_slow_warnings"] = {"count": len(loop["slow"]), "min_hz": min(loop["slow"])}
    if after_exit is not None:
        rec["cleanup"] = after_exit()
    append_run_log(rec)
    return rec


# --------------------------------------------------------------------------------------------
# 추종 종료 후 독립 정리(양팔 토크 해제 재시도)
# --------------------------------------------------------------------------------------------
def disable_torque_one(role: str, port: str, dev_id: str | None, bus_factory: Callable | None = None) -> dict:
    """공식 bus API만 사용: connect(handshake=False) → set_timeout → 모터별 disable_torque(Torque_Enable=0, Lock=0)
    → disconnect(disable_torque=False). Robot/Teleoperator connect/configure·목표 위치 쓰기는 하지 않는다."""
    bus = (bus_factory or make_bus)(role, port, dev_id)
    out: dict[str, Any] = {"motors": {}}
    try:
        bus.connect(handshake=False)
        bus.set_timeout(CLEANUP_PACKET_TIMEOUT_MS)
        for name in JOINTS:
            try:
                bus.disable_torque(name, num_retry=2)
                out["motors"][name] = "ok"
            except Exception as e:  # noqa: BLE001
                out["motors"][name] = f"{type(e).__name__}: {str(e).strip()[:100]}"
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {str(e).strip()[:200]}"
    finally:
        try:
            if bus.is_connected:
                bus.disconnect(disable_torque=False)
        except Exception as e:  # noqa: BLE001
            out["close_error"] = str(e)[:100]
    ok = "error" not in out and all(v == "ok" for v in out["motors"].values()) and len(out["motors"]) == len(JOINTS)
    out["status"] = "성공" if ok else "실패"
    return out


def cleanup_arms(arms: list[ArmCfg], *, timeout_s: float = CLEANUP_TIMEOUT_S, one: Callable | None = None) -> dict:
    """팔마다 별도 스레드로 독립 시도한다. 한쪽 실패·지연이 다른 쪽을 막지 않으며, 한도 시간을 넘기면 '확인 불가'."""
    one = one or disable_torque_one
    results: dict[str, dict] = {}

    def worker(a: ArmCfg) -> None:
        try:
            results[a.role] = one(a.role, a.port, a.id)
        except BaseException as e:  # noqa: BLE001
            results[a.role] = {"status": "실패", "error": f"{type(e).__name__}: {e}"}

    threads = [threading.Thread(target=worker, args=(a,), daemon=True) for a in arms]
    deadline = time.time() + timeout_s
    for t in threads:
        t.start()
    for t in threads:
        t.join(max(0.0, deadline - time.time()))
    for a in arms:
        results.setdefault(a.role, {"status": "확인 불가", "error": f"{timeout_s}s 안에 끝나지 않음"})
    return dict(results)


# --------------------------------------------------------------------------------------------
# 공식 명령 래핑 서브커맨드
# --------------------------------------------------------------------------------------------
def child_env(cfg: Config | None) -> dict[str, str]:
    env = dict(os.environ)
    env["HF_LEROBOT_CALIBRATION"] = str(cfg.calibration_root if cfg else WS / "calibration")
    env["PYTHONUNBUFFERED"] = "1"
    for k in ("PYTHONPATH", "PYTHONHOME", "LD_LIBRARY_PATH"):
        env.pop(k, None)
    return env


def print_cmd(argv: list[str], env: dict[str, str]) -> None:
    import shlex

    print("공식 명령:")
    print("  " + " \\\n    ".join(shlex.quote(a) for a in argv))
    print("실행 환경(래퍼가 설정하는 값만): HF_LEROBOT_CALIBRATION=" + env["HF_LEROBOT_CALIBRATION"]
          + f", PYTHONUNBUFFERED=1, PYTHONNOUSERSITE=1, {'/'.join(LEAK_VARS)} 제거")


def require_cfg(cfg, cfg_errors) -> bool:
    if cfg is None or cfg_errors:
        for e in cfg_errors:
            print("[FAIL] 설정:", e)
        return False
    return True


def stamp_name(kind: str) -> str:
    return f"{kind}-{time.strftime('%Y%m%d_%H%M%S')}"


def cmd_find_port(args, cfg, cfg_errors) -> int:
    print("공식 lerobot-find-port를 실행합니다. 안내가 나오면 해당 보드의 USB만 뽑고 Enter를 누르세요.")
    print("(서보 전원을 넣기 전에 USB가 보이는 보드라면 전원 투입 전에 하는 것이 안전합니다.)")
    rec = run_official([official_cmd("lerobot-find-port")], env=child_env(cfg), log_name=stamp_name("find-port"))
    return rec["exit_code"] or 0


def cmd_setup_motors(args, cfg, cfg_errors) -> int:
    if not require_cfg(cfg, cfg_errors):
        return 1
    argv = build_device_argv("lerobot-setup-motors", cfg, args.role, placeholder=args.dry_run)
    env = child_env(cfg)
    if args.dry_run:
        print_cmd(argv, env)
        return 0
    rep = Report()
    if not cfg.arm(args.role).id:
        rep.add(FAIL, f"{args.role}.id 미지정")
    real = check_port(rep, args.role, cfg.arm(args.role).port)
    if real:
        check_usb_fingerprint(rep, args.role, cfg.arm(args.role), real, strict=True)
    if rep.n_fail:
        return 1
    print("공식 setup-motors: gripper부터 안내되는 모터 *하나만* 보드에 연결하고 Enter. ID와 baud를 그 모터 EEPROM에 씁니다.")
    print("버스에 그 모터 하나만 남도록, 그 모터에서 다음 모터로 이어지는 케이블도 분리하세요. 케이블을 바꾸기 전에는 모터 전원을 끕니다.")
    print("probe에서 ID 누락·충돌이 확인된 경우에만 실행하세요. 정상 응답한 조립 팔에는 필요 없습니다.")
    print("케이블 재배선 시 전원 처리는 보드/제조사 안내를 따르세요.")
    if input("계속하려면 yes 입력: ").strip() != "yes":
        print("취소")
        return 1
    rec = run_official(argv, env=env, log_name=stamp_name(f"setup-motors-{args.role}"), keep_awake=True)
    return rec["exit_code"] or 0


def cmd_calibrate(args, cfg, cfg_errors) -> int:
    if not require_cfg(cfg, cfg_errors):
        return 1
    argv = build_device_argv("lerobot-calibrate", cfg, args.role, placeholder=args.dry_run)
    env = child_env(cfg)
    if args.dry_run:
        print_cmd(argv, env)
        return 0
    rep = Report()
    if not cfg.arm(args.role).id:
        rep.add(FAIL, f"{args.role}.id 미지정")
    real = check_port(rep, args.role, cfg.arm(args.role).port)
    if real:
        check_usb_fingerprint(rep, args.role, cfg.arm(args.role), real, strict=True)
    if rep.n_fail:
        return 1
    f = calibration_file(cfg, args.role)
    print(f"보정 파일 위치: {f}" + (" (이미 있음: 공식 프롬프트에서 Enter=파일을 모터에 기록, c=다시 보정)" if f and f.is_file() else " (새로 생성)"))
    if args.role == "follower":
        print("주의: 공식 calibrate는 연결 시 팔로워 설정을 쓰고 토크를 켠 뒤, 재보정에서 토크를 끕니다. 팔이 처질 수 있으니 손으로 받치세요.")
    print("공식 순서: 모든 관절을 가동 범위 가운데에 두고 Enter → wrist_roll을 제외한 관절을 끝에서 끝까지 움직임 → Enter.")
    rec = run_official(argv, env=env, log_name=stamp_name(f"calibrate-{args.role}"), keep_awake=True)
    if rec["exit_code"] == 0 and f and f.is_file():
        ok, msg = validate_calibration_file(f)
        print(f"[{'OK' if ok else 'FAIL'}] 보정 파일 {f}: {msg}")
        print("백업 예: tar czf <백업폴더>/so101_calibration_$(date +%Y%m%d).tar.gz -C <작업공간> calibration  (docs/HARDWARE.md)")
    return rec["exit_code"] or 0


CHECKLIST = (
    "역할 라벨 확인: leader/follower 보드·팔이 설정 파일의 port/id와 같다",
    "팔로워가 책상에 고정되어 있고 작업 반경에 사람·물체가 없다",
    "팔로워 전원 차단 수단(어댑터 스위치/DC 잭)이 손 닿는 곳에 있다",
    "종료 시 팔로워를 받칠 수 있다(토크 해제로 처질 수 있음, time_s 자동 종료 포함)",
    "리더를 팔로워 현재 자세 가까이 맞췄다(아래 자세 차이 표 확인)",
)


CHECKLIST_MAC = (
    "맥북 전원 어댑터를 연결했고 덮개를 닫지 않는다(덮개를 닫으면 절전으로 통신이 멈출 수 있음)",
    "USB 허브·케이블이 고정되어 실행 중 빠지지 않는다",
)


def arm_session_precheck(cfg: Config, *, purpose: str, pre_probe: Callable[[Report], None] | None = None
                         ) -> tuple[Report, dict[str, dict]]:
    """추종·녹화 공통 사전 점검(모터 쓰기 0건): id·포트·같은 장치·USB 지문·보정 파일·(pre_probe: 인자 파싱 등)
    → 여기까지 FAIL이 없을 때만 모터 응답·펌웨어·보정 일치(probe). FAIL이 있으면 공식 명령을 실행하지 않는다."""
    rep = Report()
    print(f"== {purpose} 사전 점검")
    for role in ("leader", "follower"):
        if not cfg.arm(role).id:
            rep.add(FAIL, f"{role}.id 미지정")
    reals = {r: check_port(rep, r, cfg.arm(r).port) for r in ("leader", "follower")}
    if reals["leader"] and reals["leader"] == reals["follower"]:
        rep.add(FAIL, "leader와 follower가 같은 실제 장치", str(reals["leader"]))
    for role in ("leader", "follower"):
        if reals[role]:
            check_usb_fingerprint(rep, role, cfg.arm(role), reals[role], strict=True)
    for role in ("leader", "follower"):
        f = calibration_file(cfg, role)
        if f and not f.is_file():
            rep.add(FAIL, f"{role} 보정 파일 없음: {f}",
                    f"공식 명령은 이 경우 대화형 보정을 자동 시작합니다. 먼저 scripts/so101 calibrate {role} 또는 같은 팔의 보정 파일을 복원하세요.")
        elif f:
            ok, msg = validate_calibration_file(f)
            if not ok:
                rep.add(FAIL, f"{role} 보정 파일 형식 오류", msg)
    if pre_probe is not None:
        pre_probe(rep)
    probes: dict[str, dict] = {}
    if rep.n_fail:
        return rep, probes
    for role in ("leader", "follower"):
        res = probe_arm(role, cfg.arm(role).port, cfg.arm(role).id)
        print_probe(res)
        probes[role] = res
        if not res.get("comm_ok"):
            rep.add(FAIL, f"{role} 모터 6개 응답·모델 확인 실패")
        elif not res.get("firmware_same"):
            rep.add(FAIL, f"{role} 펌웨어 버전 불일치(공식 handshake 실패 조건)", str(res.get("firmware")))
        elif res.get("calib_status") != "match":
            rep.add(FAIL, f"{role} 보정 파일과 모터 레지스터 불일치({res.get('calib_status')})",
                    f"공식 명령이 Enter 프롬프트로 파일을 모터에 쓰는 경로를 피합니다. scripts/so101 calibrate {role}로 처리하세요.")
    return rep, probes


def print_pose_and_confirm(cfg: Config, probes: dict[str, dict], time_s: float | None, onsite_confirmed: bool,
                           *, enter_to_start: bool = False) -> bool:
    """시작 자세 차이 표·안전 정보·현장 체크리스트를 보여 주고 사람의 'yes'를 받는다."""
    ln, fn = probes["leader"].get("normalized") or {}, probes["follower"].get("normalized") or {}
    print("\n== 시작 자세 차이(리더 - 팔로워, 몸체=도, gripper=0~100). 자동 판정 없음: 사람이 보고 판단")
    for j in JOINTS:
        if j in ln and j in fn:
            print(f"  {j:<14} 리더 {ln[j]:8.1f}  팔로워 {fn[j]:8.1f}  차이 {ln[j] - fn[j]:+8.1f}")
    print(f"\n이동량 제한(max_relative_target): {cfg.max_relative_target!r}"
          " — 매 주기 '현재 위치 기준 목표 오프셋'만 제한합니다. 속도·충돌 안전을 보장하지 않습니다.")
    print(f"시간 상한: {time_s!r} — 상한에 도달해도 공식 코드가 토크를 해제하므로 팔이 처질 수 있습니다.")
    print("\n현장 확인:")
    for i, c in enumerate(CHECKLIST + (CHECKLIST_MAC if IS_MAC else ()), 1):
        print(f"  {i}. {c}")
    if onsite_confirmed:
        print("(--onsite-confirmed: 현장 확인 완료로 기록)")
        return True
    if not sys.stdin.isatty():
        print("터미널 입력이 아니므로 현장 확인을 받을 수 없습니다. 로봇 옆 터미널에서 실행하세요.")
        return False
    if enter_to_start:  # 텔레옵: Enter(빈 입력)만 시작, 그 밖의 입력은 취소
        if input("모두 확인했으면 Enter로 시작(취소: q 또는 다른 입력 후 Enter, Ctrl+C): ").strip() != "":
            print("취소")
            return False
        return True
    if input("모두 확인했으면 yes 입력: ").strip() != "yes":
        print("취소")
        return False
    return True


def print_cleanup_summary(rec: dict) -> int:
    clean = rec.get("cleanup", {})
    for role in ("leader", "follower"):
        c = clean.get(role, {})
        print(f"  {role} 토크 해제 재시도: {c.get('status')}  {c.get('error', '')}")
    if rec.get("keep_awake"):
        print(f"  절전 방지(caffeinate): {rec['keep_awake']}")
    print(f"  기록: {RUNS_LOG.relative_to(WS) if RUNS_LOG.is_relative_to(WS) else RUNS_LOG}, {rec['log']}")
    if rec["exit_code"] not in (0, None):
        return rec["exit_code"] if rec["exit_code"] > 0 else 128 - rec["exit_code"]
    if any(c.get("status") != "성공" for c in clean.values()):
        print("  [FAIL] 토크 해제 재시도가 성공하지 못한 팔이 있습니다. 팔을 받치고 전원 상태를 확인하세요.")
        return 3
    return 0


def cmd_teleop(args, cfg, cfg_errors) -> int:
    if not require_cfg(cfg, cfg_errors):
        return 1
    time_s = args.time_s if args.time_s is not None else cfg.time_s
    env = child_env(cfg)
    if args.dry_run:
        argv = build_teleop_argv(cfg, time_s, placeholder=True)
        print_cmd(argv, env)
        if cfg.leader.port and cfg.follower.port and cfg.leader.id and cfg.follower.id:
            ok, msg = official_parse_check(argv)
            print(f"[{'OK' if ok else 'FAIL'}] 공식 TeleoperateConfig 파싱: {msg}")
            return 0 if ok else 1
        print("[INFO] port/id 미지정 항목이 있어 공식 파싱 확인은 생략했습니다(실행 시에는 거부됨).")
        return 0

    def parse(rep: Report) -> None:  # 기존 순서: 파일·포트·인자 파싱 확인 후에만 모터 읽기
        ok, msg = official_parse_check(build_teleop_argv(cfg, time_s, placeholder=True))
        rep.add(OK if ok else FAIL, "공식 teleop 인자 파싱", msg)

    rep, probes = arm_session_precheck(cfg, purpose="추종", pre_probe=parse)
    if rep.n_fail:
        print("사전 점검 실패로 추종을 시작하지 않습니다.")
        return 1
    if not print_pose_and_confirm(cfg, probes, time_s, args.onsite_confirmed, enter_to_start=True):
        return 1
    ln, fn = probes["leader"].get("normalized") or {}, probes["follower"].get("normalized") or {}
    print("\n종료: 리더를 쉬는 자세로 천천히 옮기고 → 팔로워를 받치고 → Ctrl+C. 응답이 없으면 팔로워 전원을 차단하세요.\n")
    argv = build_teleop_argv(cfg, time_s)
    arms = [cfg.leader, cfg.follower]
    pose = {j: round(ln[j] - fn[j], 2) for j in JOINTS if j in ln and j in fn}
    rec = run_official(argv, env=env, log_name=stamp_name("teleop"), parse_loop=True, after_exit=lambda: cleanup_arms(arms),
                       extra={"cmd": "teleop", "onsite_confirmed_flag": bool(args.onsite_confirmed),
                              "start_pose_diff_leader_minus_follower": pose,
                              "firmware": {r: probes[r].get("firmware") for r in probes}},
                       keep_awake=True)
    print("\n== 종료 요약")
    print(f"  공식 프로세스 exit={rec['exit_code']} signal={rec['exit_signal']} 전체 {rec['duration_s']}s")
    tl = rec.get("teleop_loop", {})
    print(f"  추종 루프 출력 {tl.get('loop_lines')}줄, 첫/마지막 {tl.get('first_loop_at')}~{tl.get('last_loop_at')}"
          f" (루프 구간 {tl.get('loop_span_s')}s), 중앙값 {tl.get('loop_ms_median')}ms ≈ {tl.get('hz_median')}Hz")
    return print_cleanup_summary(rec)


# --------------------------------------------------------------------------------------------
# 데이터셋(macOS): 카메라 확인·공식 lerobot-record·검사. 세부 로직은 scripts/so101_dataset.py
# --------------------------------------------------------------------------------------------
def record_robot_args(cfg: Config, *, placeholder: bool) -> list[str]:
    """lerobot-record의 --robot.*/--teleop.* 인자(teleop과 같은 값·같은 안전 설정)."""
    def val(x: str | None, what: str) -> str:
        if x is None:
            if placeholder:
                return f"<{what} 미지정>"
            raise ValueError(f"{what} 미지정")
        return x

    argv = [
        "--robot.type=so101_follower",
        f"--robot.port={val(cfg.follower.port, 'follower.port')}",
        f"--robot.id={val(cfg.follower.id, 'follower.id')}",
        "--robot.disable_torque_on_disconnect=true",
        "--teleop.type=so101_leader",
        f"--teleop.port={val(cfg.leader.port, 'leader.port')}",
        f"--teleop.id={val(cfg.leader.id, 'leader.id')}",
    ]
    mrt = cfg.max_relative_target
    if isinstance(mrt, float):
        argv.append(f"--robot.max_relative_target={mrt!r}")
    elif isinstance(mrt, dict):
        argv.append("--robot.max_relative_target=" + json.dumps({k: float(v) for k, v in mrt.items()}))
    return argv


def file_sha256(p: Path) -> str | None:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return None


def git_state() -> dict[str, Any]:
    try:
        head = subprocess.run(["git", "-C", str(WS), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(WS), "status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True, timeout=10).stdout.strip()
        return {"head": head or None, "tracked_changes": bool(dirty)}
    except (OSError, subprocess.TimeoutExpired):
        return {"head": None}


def write_manifest(root: Path, data: dict[str, Any]) -> Path:
    """공식 데이터셋 폴더 밖(형제 파일 <이름>.so101.json)에 수집 환경 기록을 남긴다. 공식 metadata는 건드리지 않는다."""
    mp = root.parent / f"{root.name}.so101.json"
    old = json.loads(mp.read_text()) if mp.is_file() else {}
    sessions = old.get("sessions", [])
    if data.get("session"):
        sessions.append(data.pop("session"))
    old.update(data)
    old["sessions"] = sessions
    tmp = mp.with_name(mp.name + ".tmp")
    tmp.write_text(json.dumps(old, ensure_ascii=False, indent=1, default=str) + "\n")
    os.replace(tmp, mp)
    return mp


def write_checksums(root: Path) -> Path:
    """데이터셋 폴더 전체 파일의 sha256 목록(<이름>.sha256, `cd <부모> && shasum -a 256 -c <이름>.sha256`로 검증)."""
    out = root.parent / f"{root.name}.sha256"
    lines = []
    for f in sorted(root.rglob("*")):
        if f.is_file():
            lines.append(f"{file_sha256(f)}  {f.relative_to(root.parent).as_posix()}")
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n")
    os.replace(tmp, out)
    return out


def _nearest_existing(p: Path) -> Path:
    while not p.exists() and p != p.parent:
        p = p.parent
    return p


MIRROR_DIR = WS / ".tmp" / "live"
VIEWER_SRC = WS / "tools" / "camera_view_dual.swift"
VIEWER_BIN = WS / ".tmp" / "bin" / "camera_view_dual"


def prepare_camera_mirror(env: dict[str, str], open_window: bool) -> subprocess.Popen | None:
    """[macOS] 공식 프로세스가 읽은 카메라 프레임을 MIRROR_DIR/<이름>.jpg로 내보내게 하고(scripts/so101_camera_mirror.py,
    런처가 SO101_CAMERA_MIRROR를 보고 설치), open_window이면 그 파일만 읽는 창을 띄운다(카메라를 다시 열지 않음).
    창은 키보드 초점을 가져가지 않고(--no-focus, 녹화 키 입력은 터미널), 터미널 Ctrl+C를 받지 않도록 새 세션으로 띄운다."""
    MIRROR_DIR.mkdir(parents=True, exist_ok=True)
    for f in MIRROR_DIR.glob("*.jpg"):
        f.unlink(missing_ok=True)
    env["SO101_CAMERA_MIRROR"] = str(MIRROR_DIR)
    if not open_window:
        print(f"카메라 영상 내보내기: {MIRROR_DIR}. 다른 터미널에서 창 띄우기:")
        print(f"  swift {VIEWER_SRC} --mirror {MIRROR_DIR} --no-focus")
        return None
    try:
        if not VIEWER_BIN.exists() or VIEWER_SRC.stat().st_mtime > VIEWER_BIN.stat().st_mtime:
            print("카메라 창 빌드 중(처음 한 번, 수십 초)...")
            VIEWER_BIN.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["xcrun", "swiftc", "-O", str(VIEWER_SRC), "-o", str(VIEWER_BIN)], check=True)
        log = open(MIRROR_DIR / "viewer.log", "w")
        v = subprocess.Popen([str(VIEWER_BIN), "--mirror", str(MIRROR_DIR), "--no-focus"], stdout=log, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        print("카메라 창: 위 front / 아래 wrist(정책·데이터셋에 저장되는 것과 같은 영상, 약 10장/초). 키 입력은 이 터미널에서.")
        return v
    except Exception as e:  # noqa: BLE001 — 창 실패는 녹화를 막지 않는다
        print(f"[WARN] 카메라 창을 띄우지 못함({type(e).__name__}: {e}). 녹화는 계속합니다. 다른 터미널에서: "
              f"swift {VIEWER_SRC} --mirror {MIRROR_DIR} --no-focus")
        return None


def stop_viewer(v: subprocess.Popen | None) -> None:
    if v is not None and v.poll() is None:
        v.terminate()
        try:
            v.wait(timeout=3)
        except subprocess.TimeoutExpired:
            v.kill()


def cmd_record(args, cfg, cfg_errors) -> int:
    import so101_dataset as D

    if not IS_MAC:
        print("녹화 래퍼는 macOS 설치(lock/macos-arm64, lerobot[dataset])에서 제공합니다. Linux lock에는 dataset extra가 없습니다.")
        return 2
    if not require_cfg(cfg, cfg_errors):
        return 1
    errors: list[str] = []
    cams: dict[str, dict] = {}
    if not args.no_cameras:
        cams, cerr = D.load_cameras(args.cameras)
        errors += cerr
        if not cams and not cerr:
            errors.append("선택한 카메라가 없습니다. configs/cameras.local.yaml에 카메라를 적거나, 영상 없이 녹화하려면 --no-cameras를 명시하세요.")
    rec, rerr = D.load_recording(args.recording, {"name": args.name, "task": args.task, "num_episodes": args.episodes,
                                                  "episode_time_s": args.episode_time_s, "reset_time_s": args.reset_time_s,
                                                  "fps": args.fps, "datasets_dir": args.datasets_dir,
                                                  "manual_advance": True if args.manual else (False if args.auto else None)})
    errors += rerr
    if rec is not None:
        if not rec.name:
            errors.append("dataset.name(데이터셋 폴더 이름)이 없습니다. recording.local.yaml 또는 --name으로 지정하세요.")
        if not rec.task:
            errors.append("dataset.task(작업 설명)가 없습니다. recording.local.yaml 또는 --task로 지정하세요.")
        for name, c in cams.items():
            if c.get("fps") and rec and c["fps"] != rec.fps:
                errors.append(f"카메라 {name} fps {c['fps']} ≠ 녹화 fps {rec.fps}. 같은 값으로 맞추세요(공식 기본 30).")
    if errors or rec is None:
        for e in errors:
            print("[FAIL] 설정:", e)
        return 1
    root = rec.root
    assert root is not None
    rep = Report()
    print("== 녹화 설정")
    print(f"  데이터셋: {rec.repo_id}  →  {root}")
    print(f"  task: {rec.task}")
    print(f"  fps {rec.fps}, 에피소드 {rec.num_episodes}개(이번 실행에서 {'추가로 ' if args.resume else ''}녹화할 수), "
          + (f"진행 방식: 스페이스바(수동), 에피소드 최대 {rec.max_episode_time_s:g}s(안전 상한)" if rec.manual_advance
             else f"진행 방식: 시간(자동), 에피소드 {rec.episode_time_s:g}s, 리셋 {rec.reset_time_s:g}s")
          + f", 영상 {rec.video} {rec.vcodec}")
    print(f"  카메라: {json.dumps(cams, ensure_ascii=False) if cams else '없음(--no-cameras)'}")
    print("  Hub 업로드: 안 함(push_to_hub=false 고정, HF_HUB_OFFLINE=1)")
    if args.resume:
        if not (root / "meta" / "info.json").is_file():
            rep.add(FAIL, f"--resume인데 기존 데이터셋이 없음: {root}", "새로 만들려면 --resume 없이 실행하세요.")
        else:
            probs = D.resume_compat(root, rec, D.expected_features(cams, rec.video))
            rep.add(FAIL if probs else OK, "기존 데이터셋과 카메라·관절·fps 호환" + (" 아님" if probs else ""), "; ".join(probs))
    elif root.exists():
        rep.add(FAIL, f"데이터셋 폴더가 이미 있음: {root}", "덮어쓰거나 지우지 않습니다. 이어서 녹화하려면 --resume, 새 데이터셋이면 다른 --name을 쓰세요.")
    if rec.datasets_dir != D.DATASETS_DIR.resolve() and rec.datasets_dir != D.DATASETS_DIR:
        if not rec.datasets_dir.is_dir():
            rep.add(FAIL, f"저장 폴더가 없음: {rec.datasets_dir}", "외장 저장소가 연결·마운트되었는지 확인하세요(자동으로 만들지 않음).")
        elif not os.access(rec.datasets_dir, os.W_OK):
            rep.add(FAIL, f"저장 폴더에 쓸 수 없음: {rec.datasets_dir}")
    need = D.estimate_bytes(cams, rec) if cams else 200 * int(rec.fps * rec.episode_time_s) * rec.num_episodes
    base = _nearest_existing(rec.datasets_dir)
    st = os.statvfs(base)
    free = st.f_bavail * st.f_frsize
    margin = 1_000_000_000
    rep.add(OK if free >= need * 1.5 + margin else FAIL, f"저장 공간: 여유 {free / 1e9:.1f} GB, 추정 필요 {need / 1e9:.2f} GB(+여유 1 GB)",
            f"{base}. 추정은 임시 PNG(에피소드 1개)+영상+표 기준입니다." + ("" if free >= need * 1.5 + margin else " 공간을 확보하거나 --datasets-dir로 외장 저장소를 지정하세요."))
    argv = D.build_record_argv(record_robot_args(cfg, placeholder=True), cams, rec, resume=args.resume)
    ok, msg, _ = D.parse_record_argv(argv)
    rep.add(OK if ok else FAIL, "공식 RecordConfig 파싱", msg)
    env = child_env(cfg)
    if args.dry_run:
        print_cmd(argv, env)
        if not (cfg.leader.port and cfg.follower.port and cfg.leader.id and cfg.follower.id):
            print("[INFO] port/id 미지정 항목이 있어 자리표시자로 표시했습니다(실제 실행은 거부됨). ./01_setup/ports.sh로 지정하세요.")
        print(f"\n결과: FAIL {rep.n_fail}, WARN {rep.n_warn}  (dry-run: 포트·카메라를 열지 않았습니다)")
        return 1 if rep.n_fail else 0
    if rep.n_fail:
        print("사전 점검 실패로 녹화를 시작하지 않습니다.")
        return 1
    # 카메라 확인(모터 구동 전): 공식 OpenCVCamera로 열어 해상도·FPS 검증 후 닫는다.
    for name, c in cams.items():
        r = D.camera_probe(c, seconds=1.0)
        if r.get("error"):
            rep.add(FAIL, f"카메라 {name} 확인 실패", r["error"] + "  → ./03_dataset/cameras.sh로 index·해상도·FPS를 다시 확인하세요.")
        else:
            rep.add(OK, f"카메라 {name}: {r['shape']} 측정 {r['measured_fps']:.1f} fps (요청 {c.get('fps')})")
    if rep.n_fail:
        print("사전 점검 실패로 녹화를 시작하지 않습니다.")
        return 1
    rep2, probes = arm_session_precheck(cfg, purpose="녹화")
    if rep2.n_fail:
        print("사전 점검 실패로 녹화를 시작하지 않습니다.")
        return 1
    if not print_pose_and_confirm(cfg, probes, None, args.onsite_confirmed):
        return 1
    if rec.manual_advance:
        env["SO101_RECORD_MANUAL"] = "1"
        print("\n녹화 조작(스페이스바 진행, 이 터미널에 초점):")
        print("  ▶ 준비 → [스페이스바] 녹화 시작 → ● 녹화 중 → [스페이스바] 종료·저장 / [r] 버리고 다시")
        print("  → ■ 환경 재설정(물체·리더 자세 정리, 저장 안 함) → [스페이스바] 다음 녹화 시작 → …")
        print(f"  q = 녹화 종료. 스페이스바를 누르지 않으면 에피소드는 최대 {rec.max_episode_time_s:g}초에서 끝나 저장됩니다(안전 상한).")
        print("  마지막 에피소드는 스페이스바로 끝내면 바로 저장·마무리됩니다(그 뒤 재설정 단계 없음). 비상시 Ctrl+C.")
    else:
        print("\n녹화 조작(이 터미널에 초점): n 또는 → = 이번 에피소드 저장 후 다음, r 또는 ← = 다시 녹화, q 또는 Esc = 녹화 종료.")
        print("에피소드·리셋 시간이 지나면 자동으로 넘어갑니다. 비상시 Ctrl+C(진행 중 에피소드는 저장되지 않음).")
    print("종료 시 공식 코드가 데이터셋을 마무리(finalize)한 뒤 팔 연결을 끊습니다. 그동안 팔로워는 토크를 유지하므로 받쳐 두세요.\n")
    rec.datasets_dir.mkdir(parents=True, exist_ok=True)
    eps_before = D.episode_count(root) if args.resume else 0  # 녹화 후 이번에 저장된 에피소드만 검사하기 위해
    argv = D.build_record_argv(record_robot_args(cfg, placeholder=False), cams, rec, resume=args.resume)
    arms = [cfg.leader, cfg.follower]
    calib = {r: {"id": cfg.arm(r).id, "file": str(calibration_file(cfg, r)), "sha256": file_sha256(calibration_file(cfg, r))}
             for r in ("leader", "follower")}
    viewer = None
    if (args.view or args.mirror) and cams:
        viewer = prepare_camera_mirror(env, open_window=bool(args.view))
    elif args.view or args.mirror:
        print("[WARN] 카메라 없이 녹화하므로 카메라 창을 띄우지 않습니다.")
    try:
        run = run_official(argv, env=env, log_name=stamp_name(f"record-{rec.name}"), parse_loop=True, after_exit=lambda: cleanup_arms(arms),
                           extra={"cmd": "record", "dataset": str(root), "repo_id": rec.repo_id, "resume": bool(args.resume),
                                  "onsite_confirmed_flag": bool(args.onsite_confirmed),
                                  "camera_view": "window" if args.view else ("mirror" if args.mirror else None)}, keep_awake=True)
    finally:
        stop_viewer(viewer)
    print("\n== 녹화 종료 요약")
    print(f"  공식 프로세스 exit={run['exit_code']} signal={run['exit_signal']} 전체 {run['duration_s']}s")
    slow = run.get("record_slow_warnings")
    print(f"  루프 지연 경고: {slow['count']}회, 최저 {slow['min_hz']} Hz" if slow else "  루프 지연 경고: 없음")
    insp = None
    new_eps: set[int] = set()
    if (root / "meta" / "info.json").is_file():
        new_eps = set(range(eps_before, D.episode_count(root)))
        print(f"\n== 이번 녹화에서 저장된 에피소드 검사: {len(new_eps)}개"
              + (f"(에피소드 {min(new_eps)}~{max(new_eps)})" if new_eps else "(새로 저장된 에피소드 없음)")
              + (f", 기존 {eps_before}개는 데이터셋 수준만 확인" if eps_before else ""))
        insp = D.inspect_dataset(root, decode=True, episodes=new_eps)
    else:
        print("  데이터셋 메타데이터가 없습니다(저장된 에피소드 없음 또는 비정상 종료). 로그를 확인하세요:", run["log"])
    mp = write_manifest(root, {
        "dataset": {"repo_id": rec.repo_id, "root": str(root), "fps": rec.fps, "task": rec.task, "video": rec.video, "vcodec": rec.vcodec},
        "environment": {"host": socket.gethostname(), "platform": f"macOS {platform.mac_ver()[0]} {platform.machine()}",
                        "python": platform.python_version(), "lerobot_sha": read_lock_env().get("LEROBOT_SHA"),
                        "lock_sha256": file_sha256(LOCK_DIR / "uv.lock"), "repo": git_state()},
        "session": {"ts": now_iso(), "resume": bool(args.resume), "episodes_requested": rec.num_episodes,
                    "manual_advance": rec.manual_advance, "max_episode_time_s": rec.max_episode_time_s if rec.manual_advance else None,
                    "episode_time_s": rec.episode_time_s, "reset_time_s": rec.reset_time_s, "cameras": cams,
                    "arms": calib, "ports": {"leader": cfg.leader.port, "follower": cfg.follower.port},
                    "max_relative_target": cfg.max_relative_target, "exit_code": run["exit_code"], "duration_s": run["duration_s"],
                    "record_slow_warnings": slow, "cleanup": run.get("cleanup"), "log": run["log"],
                    "episodes_before": eps_before, "episodes_saved": sorted(new_eps),
                    "inspect": {"fail": insp["fail"], "warn": insp["warn"], "episodes_checked": len(insp.get("episodes", []))} if insp else None},
    })
    print(f"  수집 기록(manifest): {mp}")
    rc = print_cleanup_summary(run)
    if rc == 0 and insp and insp["fail"]:
        print("  [FAIL] 저장된 데이터셋 검사에 실패 항목이 있습니다. 위 결과를 확인하세요.")
        return 1
    return rc


def cmd_cameras(args, cfg, cfg_errors) -> int:
    import so101_dataset as D

    if not IS_MAC:
        print("카메라 도구는 macOS 설치(lerobot[dataset])에서 제공합니다.")
        return 2
    print("== 연결된 카메라 이름(system_profiler, 카메라를 열지 않음)")
    try:
        r = subprocess.run(["/usr/sbin/system_profiler", "SPCameraDataType"], capture_output=True, text=True, timeout=30)
        names = [ln.strip().rstrip(":") for ln in r.stdout.splitlines() if ln.startswith("    ") and ln.strip().endswith(":")
                 and not ln.startswith("      ")]
        print("  " + (", ".join(names) if names else "(없음)"))
    except (OSError, subprocess.TimeoutExpired) as e:
        print("  확인 실패:", e)
    print("  주의: OpenCV index와 이 이름 순서는 같지 않을 수 있습니다. 내장·iPhone(연속성) 카메라가 있으면 index가 바뀔 수 있으니 세션마다 확인하세요.")
    cams, cerr = D.load_cameras(args.cameras)
    out_dir = LOG_DIR / f"cameras-{time.strftime('%Y%m%d_%H%M%S')}"
    find_argv = [official_cmd("lerobot-find-cameras"), "opencv", "--output-dir", str(out_dir), "--record-time-s", "1"]
    if args.dry_run:
        print("\n공식 탐색 명령(실행 시 모든 카메라를 잠깐 엽니다):")
        print("  " + " ".join(find_argv))
        print(f"\n카메라 설정 {args.cameras}: " + ("오류 " + "; ".join(cerr) if cerr else json.dumps(cams, ensure_ascii=False)))
        print("dry-run: 카메라를 열지 않았습니다.")
        return 1 if cerr and args.cameras.is_file() else 0
    if args.test:
        if cerr or args.test not in cams:
            print("[FAIL] 카메라 설정:", "; ".join(cerr) or f"'{args.test}'가 {args.cameras}에 없습니다.")
            return 1
        print(f"\n== 설정한 카메라 '{args.test}' 읽기 시험({args.seconds:g}초, 공식 OpenCVCamera). 처음이면 macOS 카메라 권한 창에서 허용하세요.")
        res = D.camera_probe(cams[args.test], seconds=args.seconds, save_dir=out_dir)
        append_run_log({"ts": now_iso(), "host": socket.gethostname(), "cmd": "cameras-test", "camera": args.test,
                        "config": cams[args.test], **res})
        if res.get("error"):
            print("[FAIL]", res["error"])
            print("  → index·해상도·FPS를 lerobot-find-cameras 결과에 맞추세요. 권한을 거부했다면 시스템 설정 > 개인정보 보호 및 보안 > 카메라에서 이 터미널 앱을 허용하세요.")
            return 1
        print(f"[OK] 프레임 {res['frames']}개, 형태 {res['shape']}, 측정 {res['measured_fps']:.1f} fps (요청 {cams[args.test].get('fps')})")
        print(f"     저장된 확인용 사진: {res.get('snapshot')}  ← 원하는 카메라가 맞는지 눈으로 확인하세요.")
        if cams[args.test].get("fps") and res["measured_fps"] < 0.9 * cams[args.test]["fps"]:
            print("[WARN] 측정 FPS가 요청보다 10% 넘게 낮습니다(조명·USB 대역·카메라 모드). 녹화 루프 지연 경고가 날 수 있습니다.")
        return 0
    print("\n== 공식 lerobot-find-cameras opencv (모든 카메라를 잠깐 열고 확인용 사진을 저장)")
    print("처음이면 macOS가 이 터미널 앱(VS Code 등)의 카메라 접근 허용을 묻습니다. 사용자가 직접 허용해야 합니다.")
    if sys.stdin.isatty():
        try:
            input("계속하려면 Enter (취소: Ctrl+C): ")
        except (KeyboardInterrupt, EOFError):
            print("\n취소")
            return 1
    rec = run_official(find_argv, env=child_env(cfg), log_name=stamp_name("find-cameras"))
    print(f"\n확인용 사진: {out_dir}")
    print("다음: configs/cameras.local.yaml의 index_or_path·width·height·fps를 위 결과에 맞추고 ./03_dataset/cameras.sh --test <이름>")
    return rec["exit_code"] or 0


def cmd_inspect(args, cfg, cfg_errors) -> int:
    import so101_dataset as D

    root = args.root if args.root.is_absolute() else (Path.cwd() / args.root)
    try:
        eps = D.parse_episode_spec(args.episodes) if args.episodes else None
    except ValueError as e:
        print(f"[FAIL] --episodes 형식: {e} (예: 50-59 또는 3,5,7)")
        return 1
    res = D.inspect_dataset(root, decode=not args.no_decode, episodes=eps)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    jp = LOG_DIR / f"inspect-{root.name}-{time.strftime('%Y%m%d_%H%M%S')}.json"
    jp.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    print(f"검사 기록: {jp}")
    if args.write_manifest and (root / "meta" / "info.json").is_file():
        cs = write_checksums(root)
        mp = write_manifest(root, {"last_inspect": {"ts": res["ts"], "fail": res["fail"], "warn": res["warn"],
                                                    "episodes": len(res.get("episodes", [])), "log": str(jp)},
                                   "checksums": {"file": cs.name, "sha256": file_sha256(cs)}})
        print(f"체크섬 목록: {cs}  (검증: cd {root.parent} && shasum -a 256 -c {cs.name})")
        print(f"manifest: {mp}")
    return 1 if res["fail"] else (2 if res["warn"] else 0)


# --------------------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="scripts/so101", description="SO-101 공식 LeRobot 래퍼")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="설정 파일(기본 configs/robot.local.yaml)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("doctor", help="비구동 점검. software=로봇 불필요, hardware=포트·권한·설정·보정 파일(포트를 열지 않음)")
    p.add_argument("--scope", choices=("software", "hardware"), default="software")
    sub.add_parser("ports", help="USB 시리얼 장치·by-id/by-path·식별정보 목록(읽기 전용)")
    sub.add_parser("find-port", help="공식 lerobot-find-port 실행(USB 분리 방식)")
    p = sub.add_parser("probe", help="모터 읽기 전용 확인(ID·모델·펌웨어·위치·토크·보정 레지스터)")
    p.add_argument("role", choices=("leader", "follower", "both"))
    p.add_argument("--scan", action="store_true", help="공식 scan_port로 모든 baud에서 broadcast ping(명시적으로만)")
    for name, helptext in (("setup-motors", "공식 lerobot-setup-motors(ID·baud 쓰기, 필요할 때만)"), ("calibrate", "공식 lerobot-calibrate")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("role", choices=("leader", "follower"))
        p.add_argument("--dry-run", action="store_true", help="공식 명령만 표시(포트·보정 파일 확인 생략, 장치 열지 않음)")
    p = sub.add_parser("teleop", help="공식 lerobot-teleoperate(카메라 없음) + 사전 점검 + 종료 후 양팔 토크 해제 재시도")
    p.add_argument("--time-s", type=float, default=None, help="공식 --teleop_time_s(초). 설정 파일 값보다 우선")
    p.add_argument("--dry-run", action="store_true", help="공식 명령과 인자 파싱만 확인(장치 열지 않음, 로봇 객체 생성 없음)")
    p.add_argument("--onsite-confirmed", action="store_true", help="현장 체크리스트를 이미 확인했음(프롬프트 생략, 기록됨)")
    # --- macOS 추가 명령 ---
    sub.add_parser("assign-ports", help="[macOS] USB 연결 전후 차이로 리더·팔로워 포트를 찾아 설정에 저장(포트를 열지 않음)")
    p = sub.add_parser("record", help="[macOS] 공식 lerobot-record 로컬 데이터셋 녹화(+사전 점검·토크 해제 재시도·검사)")
    p.add_argument("--dry-run", action="store_true", help="설정·공식 인자 파싱·경로·공간만 확인(포트·카메라를 열지 않음)")
    p.add_argument("--resume", action="store_true", help="기존 데이터셋에 이어서 녹화(호환성 확인 후). --episodes는 추가 수")
    p.add_argument("--name", default=None, help="데이터셋 이름(datasets/<이름>). 설정 파일보다 우선")
    p.add_argument("--task", default=None, help="작업 설명. 설정 파일보다 우선")
    p.add_argument("--episodes", type=int, default=None, help="이번 실행에서 녹화할 에피소드 수")
    p.add_argument("--episode-time-s", type=float, default=None)
    p.add_argument("--reset-time-s", type=float, default=None)
    p.add_argument("--fps", type=int, default=None)
    p.add_argument("--datasets-dir", default=None, help="데이터셋 부모 폴더(외장 저장소 등, 이미 있어야 함). 기본 <작업공간>/datasets")
    p.add_argument("--cameras", type=Path, default=WS / "configs" / "cameras.local.yaml")
    p.add_argument("--recording", type=Path, default=WS / "configs" / "recording.local.yaml")
    p.add_argument("--no-cameras", action="store_true", help="카메라 없이 관절만 녹화(명시적으로만)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--manual", action="store_true", help="이번 실행만 스페이스바 진행(설정 manual_advance보다 우선)")
    g.add_argument("--auto", action="store_true", help="이번 실행만 시간 자동 진행(설정 manual_advance보다 우선)")
    p.add_argument("--onsite-confirmed", action="store_true", help="현장 체크리스트를 이미 확인했음(프롬프트 생략, 기록됨)")
    gv = p.add_mutually_exclusive_group()
    gv.add_argument("--view", action="store_true", help="녹화 중 카메라 창 띄우기(카메라를 다시 열지 않고 녹화 프로세스의 프레임을 표시)")
    gv.add_argument("--mirror", action="store_true", help="카메라 영상만 .tmp/live로 내보냄(다른 터미널에서 camera_view_dual.swift --mirror로 보기)")
    p = sub.add_parser("cameras", help="[macOS] 공식 lerobot-find-cameras 실행, 또는 설정한 카메라 읽기 시험(--test)")
    p.add_argument("--dry-run", action="store_true", help="명령·설정만 표시(카메라를 열지 않음)")
    p.add_argument("--test", default=None, metavar="NAME", help="configs/cameras.local.yaml의 카메라 하나를 공식 OpenCVCamera로 읽기 시험")
    p.add_argument("--seconds", type=float, default=3.0)
    p.add_argument("--cameras", type=Path, default=WS / "configs" / "cameras.local.yaml")
    p = sub.add_parser("inspect", help="공식 LeRobotDataset으로 데이터셋을 다시 열어 검사(모터·카메라를 열지 않음)")
    p.add_argument("root", type=Path)
    p.add_argument("--no-decode", action="store_true", help="영상 디코드 검사 생략")
    p.add_argument("--episodes", default=None, help="에피소드별 검사 범위(예: 50-59, 3,5). 기본: 전체")
    p.add_argument("--write-manifest", action="store_true", help="전체 파일 sha256 목록과 manifest를 데이터셋 옆에 기록(이관용)")
    args = ap.parse_args(argv)

    cfg, cfg_errors = (None, [])
    if args.cmd in ("inspect",):
        pass  # 로봇 설정 불필요
    elif args.cmd != "doctor" or args.scope == "hardware" or args.config != DEFAULT_CONFIG or DEFAULT_CONFIG.is_file():
        cfg, cfg_errors = load_config(args.config)
    if args.cmd == "doctor" and args.scope == "software":
        cfg_errors = []  # software 점검은 로컬 설정과 무관
    apply_calibration_env(cfg)
    if args.cmd == "teleop" and args.time_s is not None and args.time_s <= 0:
        print("--time-s는 양수여야 합니다.")
        return 2
    handler = {"doctor": cmd_doctor, "ports": cmd_ports, "find-port": cmd_find_port, "probe": cmd_probe,
               "setup-motors": cmd_setup_motors, "calibrate": cmd_calibrate, "teleop": cmd_teleop,
               "assign-ports": cmd_assign_ports, "record": cmd_record, "cameras": cmd_cameras, "inspect": cmd_inspect}[args.cmd]
    return handler(args, cfg, cfg_errors)


if __name__ == "__main__":
    sys.exit(main())
