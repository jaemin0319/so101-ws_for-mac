#!/usr/bin/env python3
"""하드웨어 없이 래퍼의 안전 관련 동작을 검증한다(검증 전용 도구, 운영 CLI에 노출하지 않음).

실행:  .venv/bin/python tools/verify_offline.py        (ROS 변수는 스스로 제거하고 다시 실행한다)

가짜 장치: pty 위에서 Feetech protocol 0(PING/READ/WRITE/SYNC_READ/SYNC_WRITE 등)에 응답하는 가짜 서보 버스.
공식 FeetechMotorsBus와 scservo_sdk가 실제 pyserial 경로로 이 pty를 연다. 가짜 장치가 받은 모든 쓰기 계열 명령
(WRITE, REG_WRITE, ACTION, RESET, SYNC_WRITE 등)을 *선로 수준*에서 기록하므로, 코드에 write 문자열이 있는지와
무관하게 실제로 모터 쓰기가 전송됐는지를 판정한다. 실제 /dev/tty* 장치는 열지 않는다.

검사 항목은 아래 TESTS 목록과 같다. 결과는 표준출력과 .tmp/verify/result.json에 남는다.

macOS(Darwin)에서의 차이(시험 판정 기준은 같다):
- 열린 fd 확인: /proc/self/fd 대신 /dev/fd + fcntl(F_GETPATH).
- macOS pty는 pyserial이 1,000,000 baud 설정에 쓰는 IOSSIOSPEED ioctl을 지원하지 않는다(ENOTTY). 가짜 장치(pty)를 열 때만
  그 ioctl 실패를 무시하는 시험용 shim을 쓴다(실제 USB 장치 경로에는 적용하지 않음).
- 가짜 장치를 USB 장치 목록(pyserial comports 대체)에 등록해 USB 지문 검사를 거치게 한다.
- 부모 SIGKILL 고아 방지는 prctl 대신 scripts/so101_launch.py(kqueue)로 검증한다. macOS 전용 시험(test_macos)을 추가로 실행한다.
"""
from __future__ import annotations

import json
import os
import pty
import types
import signal
import subprocess
import sys
import tempfile
import threading
import time
import tty
from pathlib import Path

WS = Path(__file__).resolve().parent.parent

# ---- 실행 환경 격리: ROS 경로가 있으면 지운 환경으로 다시 실행 ----
IS_MAC = sys.platform == "darwin"
_LEAK = ("PYTHONPATH", "PYTHONHOME", "LD_LIBRARY_PATH") + (
    ("DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES") if IS_MAC else ())
# --timing-child는 런처 아래 자식(부모가 이미 격리한 환경)이다. 런처의 훅이 cv2를 import하며 라이브러리 경로 변수를 남기므로
# 여기서 다시 실행하면 훅이 사라진다 → 건너뛴다.
if "--timing-child" not in sys.argv and "--coreml-child" not in sys.argv and (any(os.environ.get(k) for k in _LEAK) or os.environ.get("PYTHONNOUSERSITE") != "1"):
    env = {k: v for k, v in os.environ.items() if k not in _LEAK}
    env.update(PYTHONNOUSERSITE="1", SO101_WS=str(WS), HF_HOME=str(WS / ".cache/huggingface"), HF_HUB_OFFLINE="1",
               TMPDIR=str(WS / ".tmp"))
    os.execve(sys.executable, [sys.executable, *sys.argv], env)

sys.path.insert(0, str(WS / "scripts"))
VERIFY_DIR = WS / ".tmp" / "verify"

INST_PING, INST_READ, INST_WRITE, INST_REG_WRITE, INST_ACTION, INST_RESET = 1, 2, 3, 4, 5, 6
INST_SYNC_READ, INST_SYNC_WRITE = 0x82, 0x83
WRITE_INSTS = {INST_WRITE: "WRITE", INST_REG_WRITE: "REG_WRITE", INST_ACTION: "ACTION", INST_RESET: "RESET",
               INST_SYNC_WRITE: "SYNC_WRITE", 0x08: "REBOOT", 0x0A: "RECOVERY"}


# ============================================================================================
# 가짜 Feetech 서보 버스(pty)
# ============================================================================================
class FakeServoBus:
    LIVE: list["FakeServoBus"] = []  # macOS: 가짜 USB 장치 목록(comports 대체)에 노출
    _SEQ = 0

    def __init__(self, motors: dict[int, dict] | None, *, silent_ids: set[int] = frozenset()):
        """motors: id -> {"fw": (major, minor), "pos": int, "offset": int, "min": int, "max": int, "model": int}
        motors=None이면 아무 응답도 하지 않는 버스(장치 무응답)."""
        self.master, slave = pty.openpty()
        tty.setraw(self.master)
        self.slave_path = os.ttyname(slave)
        os.close(slave)  # 테스트 대상이 경로로 연다
        self.silent = set(silent_ids)
        self.writes: list[tuple[str, int, list[int]]] = []  # (inst, id, params)
        self.instructions: list[tuple[int, int]] = []
        self.regs: dict[int, bytearray] = {}
        for mid, m in (motors or {}).items():
            r = bytearray(256)
            r[0], r[1] = m.get("fw", (3, 10))
            self._put(r, 3, m.get("model", 777), 2)
            r[5] = mid
            r[6] = 0  # baud index (1M)
            self._put(r, 9, m.get("min", 1000), 2)
            self._put(r, 11, m.get("max", 3000), 2)
            off = m.get("offset", 0)
            self._put(r, 31, (-off | (1 << 11)) if off < 0 else off, 2)
            r[33] = 0
            r[40] = m.get("torque", 0)
            r[55] = 0
            self._put(r, 56, m.get("pos", 2048), 2)
            self.regs[mid] = r
        self._stop = False
        FakeServoBus._SEQ += 1
        self.usb = {"vid": "1a86", "pid": "55d3", "serial": f"FAKE{FakeServoBus._SEQ:04d}", "location": f"9-{FakeServoBus._SEQ}"}
        FakeServoBus.LIVE.append(self)
        self.th = threading.Thread(target=self._run, daemon=True)
        self.th.start()

    @staticmethod
    def _put(r: bytearray, addr: int, val: int, n: int) -> None:
        for i in range(n):
            r[addr + i] = (val >> (8 * i)) & 0xFF

    def _status(self, mid: int, params: list[int]) -> bytes:
        body = [mid, len(params) + 2, 0, *params]
        return bytes([0xFF, 0xFF, *body, (~sum(body)) & 0xFF])

    def _run(self) -> None:
        buf = b""
        while not self._stop:
            try:
                chunk = os.read(self.master, 1024)
            except OSError as e:
                if e.errno == 5 and not self._stop:  # EIO: 아직 아무도 slave를 열지 않음 → 기다림
                    time.sleep(0.005)
                    continue
                return
            if not chunk:
                if IS_MAC and not self._stop:  # macOS: slave가 열려 있지 않으면 EIO 대신 EOF(0바이트)를 돌려준다 → 기다림
                    time.sleep(0.005)
                    continue
                return
            buf += chunk
            while True:
                i = buf.find(b"\xff\xff")
                if i < 0 or len(buf) < i + 4:
                    break
                ln = buf[i + 3]
                if len(buf) < i + 4 + ln:
                    break
                pkt = buf[i:i + 4 + ln]
                buf = buf[i + 4 + ln:]
                self._handle(pkt[2], pkt[4], list(pkt[5:-1]))

    def _reply(self, data: bytes) -> None:
        try:
            os.write(self.master, data)
        except OSError:
            pass

    def _handle(self, mid: int, inst: int, params: list[int]) -> None:
        self.instructions.append((inst, mid))
        if inst in WRITE_INSTS:
            self.writes.append((WRITE_INSTS[inst], mid, params))
        targets = list(self.regs) if mid == 0xFE else [mid]
        if inst == INST_SYNC_READ:
            addr, n, ids = params[0], params[1], params[2:]
            out = b""
            for t in ids:
                if t in self.regs and t not in self.silent:
                    out += self._status(t, list(self.regs[t][addr:addr + n]))
            self._reply(out)
            return
        if inst == INST_SYNC_WRITE:
            return  # 응답 없음(기록만)
        for t in targets:
            if t not in self.regs or t in self.silent:
                continue
            r = self.regs[t]
            if inst == INST_PING:
                self._reply(self._status(t, []))
            elif inst == INST_READ:
                addr, n = params[0], params[1]
                self._reply(self._status(t, list(r[addr:addr + n])))
            elif inst == INST_WRITE:
                addr, data = params[0], params[1:]
                r[addr:addr + len(data)] = bytes(data)
                if mid != 0xFE:
                    self._reply(self._status(t, []))

    def write_summary(self) -> list[str]:
        return [f"{inst} id={mid} addr={p[0] if p else '-'} data={p[1:]}" for inst, mid, p in self.writes]

    def close(self) -> None:
        self._stop = True
        if self in FakeServoBus.LIVE:
            FakeServoBus.LIVE.remove(self)
        try:
            os.close(self.master)
        except OSError:
            pass


def fake_comports() -> list:
    """macOS: 살아 있는 가짜 버스를 pyserial ListPortInfo처럼 보이게 한다(+비USB 항목 하나)."""
    out = [types.SimpleNamespace(device="/dev/cu.so101-verify-bluetooth", vid=None, pid=None, serial_number=None, location=None,
                                 manufacturer=None, product=None, description="n/a")]
    for b in FakeServoBus.LIVE:
        out.append(types.SimpleNamespace(device=b.slave_path, vid=int(b.usb["vid"], 16), pid=int(b.usb["pid"], 16),
                                         serial_number=b.usb["serial"], location=b.usb["location"], manufacturer="verify",
                                         product="FakeServoBus", description="FakeServoBus"))
    return out


def fake_usb_for(port: str | None) -> dict | None:
    if not port:
        return None
    real = os.path.realpath(port)
    for b in FakeServoBus.LIVE:
        if b.slave_path == real:
            return {**b.usb, "id_by": "serial"}
    return None


def install_pty_baud_shim() -> None:
    """macOS 시험용: pty에서만 IOSSIOSPEED(비표준 baud) ioctl 실패(ENOTTY)를 무시한다."""
    import errno

    import serial.serialposix as sp

    orig = sp.Serial._set_special_baudrate
    if getattr(orig, "_so101_shim", False):
        return

    def shim(self, baudrate):
        try:
            return orig(self, baudrate)
        except OSError as e:
            if e.errno == errno.ENOTTY and str(self.port or "").startswith("/dev/ttys"):
                return None
            raise

    shim._so101_shim = True
    sp.Serial._set_special_baudrate = shim


def open_fds_to(path: str) -> int:
    n = 0
    if IS_MAC:
        import fcntl

        for name in os.listdir("/dev/fd"):
            try:
                got = fcntl.fcntl(int(name), fcntl.F_GETPATH, bytes(1024)).split(b"\0", 1)[0].decode()
            except (OSError, ValueError):
                continue
            n += got == path
        return n
    for fd in Path("/proc/self/fd").iterdir():
        try:
            if os.readlink(fd) == path:
                n += 1
        except OSError:
            pass
    return n


# ============================================================================================
# 공용
# ============================================================================================
RESULTS: list[dict] = []


def check(name: str, cond: bool, detail: str = "") -> bool:
    RESULTS.append({"test": name, "pass": bool(cond), "detail": detail})
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""), flush=True)
    return cond


def setup_module():
    import so101

    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    so101.LOG_DIR = VERIFY_DIR / "logs"
    so101.RUNS_LOG = so101.LOG_DIR / "runs.jsonl"
    os.environ["HF_LEROBOT_CALIBRATION"] = str(VERIFY_DIR / "calibration")
    if IS_MAC:
        install_pty_baud_shim()
        so101.COMPORTS_FN = fake_comports
    return so101


def std_motors(**over) -> dict[int, dict]:
    m = {i: {"fw": (3, 10), "pos": 2000 + 10 * i, "offset": -50 + 10 * i, "min": 800 + i, "max": 3200 + i} for i in range(1, 7)}
    for k, v in over.items():
        m.update(v) if k == "replace" else None
    return m


def write_calibration(so101, role: str, dev_id: str, motors: dict[int, dict]) -> Path:
    import draccus

    from lerobot.motors import MotorCalibration

    sub = ("robots", "so_follower") if role == "follower" else ("teleoperators", "so_leader")
    p = Path(os.environ["HF_LEROBOT_CALIBRATION"]) / sub[0] / sub[1] / f"{dev_id}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    cal = {j: MotorCalibration(id=i + 1, drive_mode=0, homing_offset=motors[i + 1]["offset"], range_min=motors[i + 1]["min"],
                               range_max=motors[i + 1]["max"]) for i, j in enumerate(so101.JOINTS)}
    with open(p, "w") as f, draccus.config_type("json"):
        draccus.dump(cal, f, indent=4)
    return p


# ============================================================================================
# 테스트: probe (읽기 전용)
# ============================================================================================
def test_probe(so101):
    motors = std_motors()
    write_calibration(so101, "follower", "vf_ok", motors)
    fake = FakeServoBus(motors)
    try:
        res = so101.probe_arm("follower", fake.slave_path, "vf_ok")
        check("probe 정상: 6개 응답·모델 일치", res.get("comm_ok") is True, str(res.get("errors")))
        check("probe 정상: 보정 파일=레지스터 일치", res.get("calib_status") == "match", str(res.get("calib_compare")))
        check("probe 정상: 정규화 위치 sync_read", bool(res.get("normalized")), str(res.get("normalized")))
        check("probe 정상: 모터 쓰기 명령 0건(선로 수준)", not fake.writes, "; ".join(fake.write_summary()))
        check("probe 정상: 종료 후 포트 닫힘", open_fds_to(fake.slave_path) == 0)
    finally:
        fake.close()

    # 보정 불일치 + 펌웨어 다름 + ID 3 무응답
    m2 = std_motors()
    m2[5]["fw"] = (3, 9)
    m2[2]["max"] = 3999
    write_calibration(so101, "leader", "vl_bad", std_motors())
    fake = FakeServoBus(m2, silent_ids={3})
    try:
        res = so101.probe_arm("leader", fake.slave_path, "vl_bad")
        j = res["joints"]
        check("probe 진단: ID3 무응답을 관절별로 표시", "ping_error" in j["elbow_flex"] and j["shoulder_pan"].get("model_ok"),
              j["elbow_flex"].get("ping_error", "")[:80])
        check("probe 진단: 펌웨어 차이 감지(강제 조치 없음)", res.get("firmware_same") is False, str(res.get("firmware")))
        check("probe 진단: 보정 불일치 필드 표시", res["calib_compare"].get("shoulder_lift", {}).get("range_max") == (3202, 3999),
              str(res["calib_compare"].get("shoulder_lift")))
        check("probe 진단: 쓰기 0건", not fake.writes, "; ".join(fake.write_summary()))
        check("probe 진단: 포트 닫힘", open_fds_to(fake.slave_path) == 0)
    finally:
        fake.close()

    # 장치 무응답
    fake = FakeServoBus(None)
    try:
        res = so101.probe_arm("follower", fake.slave_path, "vf_ok")
        check("probe 무응답: comm_ok False, 예외 없이 결과 반환", res.get("comm_ok") is False)
        check("probe 무응답: 쓰기 명령 전송 0건", not fake.writes, "; ".join(fake.write_summary()))
        check("probe 무응답: 포트 닫힘", open_fds_to(fake.slave_path) == 0)
    finally:
        fake.close()

    # 없는 포트
    res = so101.probe_arm("follower", "/dev/so101-verify-nonexistent", "vf_ok")
    check("probe 없는 포트: 포트 열기 실패로 보고", res.get("port_open") is False and res["errors"], str(res["errors"])[:100])

    # Ctrl+C(KeyboardInterrupt)가 읽기 도중 발생
    fake = FakeServoBus(motors)
    try:
        def factory(role, port, dev_id):
            bus = so101.make_bus(role, port, dev_id)
            orig, n = bus.read, {"c": 0}

            def read(*a, **k):
                n["c"] += 1
                if n["c"] == 5:
                    raise KeyboardInterrupt
                return orig(*a, **k)

            bus.read = read
            return bus

        got = None
        try:
            so101.probe_arm("follower", fake.slave_path, "vf_ok", bus_factory=factory)
        except KeyboardInterrupt:
            got = "KeyboardInterrupt"
        check("probe Ctrl+C: 예외가 전파되고(원래 오류 보존)", got == "KeyboardInterrupt")
        check("probe Ctrl+C: 정리 경로에서도 쓰기 0건", not fake.writes, "; ".join(fake.write_summary()))
        check("probe Ctrl+C: 포트 닫힘", open_fds_to(fake.slave_path) == 0)
    finally:
        fake.close()

    # 객체 소멸자: make_bus가 만든 공식 객체/버스를 GC해도 쓰기 없음
    fake = FakeServoBus(motors)
    try:
        import gc

        bus = so101.make_bus("follower", fake.slave_path, "vf_ok")
        bus.connect(handshake=False)
        bus.disconnect(disable_torque=False)
        del bus
        gc.collect()
        time.sleep(0.2)
        check("make_bus: 공식 객체·버스 소멸 시 쓰기 0건", not fake.writes, "; ".join(fake.write_summary()))
    finally:
        fake.close()


# ============================================================================================
# 테스트: 독립 cleanup
# ============================================================================================
def test_cleanup(so101):
    motors = std_motors()
    fake = FakeServoBus({k: dict(v, torque=1) for k, v in motors.items()})
    try:
        arms = [so101.ArmCfg("leader", "so101_leader", "vl", "/dev/so101-verify-missing"),
                so101.ArmCfg("follower", "so101_follower", "vf", fake.slave_path)]
        t0 = time.time()
        res = so101.cleanup_arms(arms)
        dt = time.time() - t0
        check("cleanup: leader 실패가 follower 정리를 막지 않음", res["leader"]["status"] == "실패" and res["follower"]["status"] == "성공",
              json.dumps({k: v["status"] for k, v in res.items()}, ensure_ascii=False))
        addrs = sorted({(w[1], w[2][0], tuple(w[2][1:])) for w in fake.writes})
        expect = sorted({(i, a, (0,)) for i in range(1, 7) for a in (40, 55)})
        check("cleanup: 쓰기는 Torque_Enable(40)=0, Lock(55)=0 뿐", addrs == expect and all(w[0] == "WRITE" for w in fake.writes),
              "; ".join(fake.write_summary()[:4]) + " ...")
        check("cleanup: 목표 위치(42) 쓰기 없음", not any(w[2][0] == 42 for w in fake.writes))
        check("cleanup: 포트 닫힘", open_fds_to(fake.slave_path) == 0)
        check("cleanup: 시간 한도 안에 종료", dt < so101.CLEANUP_TIMEOUT_S, f"{dt:.2f}s")
    finally:
        fake.close()

    # 한 모터 무응답
    fake = FakeServoBus(motors, silent_ids={4})
    try:
        t0 = time.time()
        res = so101.cleanup_arms([so101.ArmCfg("follower", "so101_follower", "vf", fake.slave_path)])
        dt = time.time() - t0
        m = res["follower"].get("motors", {})
        check("cleanup 부분 실패: 무응답 모터만 실패로 기록, 나머지 성공", res["follower"]["status"] == "실패"
              and m.get("wrist_flex") != "ok" and all(m[j] == "ok" for j in so101.JOINTS if j != "wrist_flex"), f"{dt:.2f}s")
    finally:
        fake.close()

    # 한쪽이 멈춤 → 확인 불가, 다른 쪽은 성공, 전체는 한도 시간에 종료
    def one(role, port, dev_id):
        if role == "leader":
            time.sleep(60)
        return {"status": "성공"}

    t0 = time.time()
    res = so101.cleanup_arms([so101.ArmCfg("leader", "so101_leader", "a", "/dev/x"), so101.ArmCfg("follower", "so101_follower", "b", "/dev/y")],
                             timeout_s=1.5, one=one)
    dt = time.time() - t0
    check("cleanup 지연: 멈춘 팔은 '확인 불가', 다른 팔은 성공, 한도 시간에 반환",
          res["leader"]["status"] == "확인 불가" and res["follower"]["status"] == "성공" and dt < 2.5, f"{dt:.2f}s")


# ============================================================================================
# 테스트: 공식 프로세스 실행기(신호·입력·고아 방지) — 가짜 자식 사용
# ============================================================================================
def fake_child(mode: str, marker: str) -> None:
    """검증 전용 가짜 자식 프로세스."""
    n = {"sigint": 0}
    info = {"mode": mode, "sighup_ignored": signal.getsignal(signal.SIGHUP) == signal.SIG_IGN}
    Path(marker + ".pid").write_text(str(os.getpid()))
    if mode == "checkcaff":  # macOS: 자식이 사는 동안 caffeinate -w <자식 PID>가 떠 있는지
        time.sleep(0.8)
        r = subprocess.run(["pgrep", "-f", f"caffeinate -i -w {os.getpid()}"], capture_output=True, text=True)
        info["caffeinate_pids"] = r.stdout.split()
        Path(marker).write_text(json.dumps(info))
        return

    def on_int(s, f):
        n["sigint"] += 1
        if n["sigint"] == 1:
            raise KeyboardInterrupt

    if mode == "stubborn":
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        while True:
            time.sleep(0.1)
    signal.signal(signal.SIGINT, on_int)
    try:
        if mode == "interactive":
            sys.stdout.write("입력: ")
            sys.stdout.flush()
            info["line"] = sys.stdin.readline().strip()
            return
        while True:
            print("Teleop loop time: 16.50ms (61 Hz)\x1b[1A", flush=True)
            time.sleep(0.05)
    except KeyboardInterrupt:
        info["got_keyboardinterrupt"] = True
        time.sleep(0.6)  # 중복 SIGINT가 오는지 관찰
    except BrokenPipeError:  # 부모가 죽어 출력 파이프가 닫힘(공식 코드라면 finally의 disconnect가 실행되는 경로)
        info["broken_pipe"] = True
    finally:
        info["sigint_count"] = n["sigint"]
        Path(marker).write_text(json.dumps(info))


def harness(scenario: str, outdir: str) -> None:
    """pty의 세션 리더로 실행되어 so101.run_official을 호출한다."""
    so101 = setup_module()
    so101.LOG_DIR = Path(outdir)
    so101.RUNS_LOG = Path(outdir) / "runs.jsonl"
    mode = {"interactive": "interactive", "ctrlc": "loop", "sigterm": "loop", "sighup": "loop", "parentkill": "loop",
            "stubborn": "stubborn", "parentkill_poll": "loop", "parentkill_stubborn": "stubborn", "awake": "checkcaff",
            "awake_ctrlc": "loop"}[scenario]
    if scenario == "parentkill_poll":
        os.environ.update(SO101_LAUNCH_FORCE_POLL="1", SO101_LAUNCH_DEBUG="1")
    if scenario == "parentkill_stubborn":
        os.environ.update(SO101_LAUNCH_INT_GRACE="1", SO101_LAUNCH_TERM_GRACE="1", SO101_LAUNCH_DEBUG="1")
    if scenario == "parentkill":
        os.environ.update(SO101_LAUNCH_DEBUG="1")
    marker = str(Path(outdir) / "child.json")
    argv = [sys.executable, __file__, "--fake-child", mode, marker]
    Path(outdir, "harness.pid").write_text(str(os.getpid()))
    rec = so101.run_official(argv, env=dict(os.environ), log_name="fake", parse_loop=True,
                             after_exit=lambda: {"after_exit": "called"}, interrupt_grace=2.0, term_grace=1.0,
                             keep_awake=scenario.startswith("awake"))
    Path(outdir, "rec.json").write_text(json.dumps(rec, ensure_ascii=False))


def run_pty_scenario(scenario: str, action) -> tuple[dict | None, dict | None, str]:
    outdir = tempfile.mkdtemp(prefix=f"run_{scenario}_", dir=VERIFY_DIR)
    pid, master = pty.fork()
    if pid == 0:
        os.execv(sys.executable, [sys.executable, __file__, "--harness", scenario, outdir])
    out = b""

    def drain(t):
        nonlocal out
        end = time.time() + t
        while time.time() < end:
            try:
                import select

                r, _, _ = select.select([master], [], [], 0.05)
                if r:
                    out += os.read(master, 4096)
            except OSError:
                return

    drain(1.5)
    action(master, pid, drain, outdir)
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            wpid, _ = os.waitpid(pid, os.WNOHANG)
            if wpid:
                break
        except ChildProcessError:
            break
        drain(0.1)
    try:
        os.close(master)
    except OSError:
        pass
    rec = json.loads(Path(outdir, "rec.json").read_text()) if Path(outdir, "rec.json").exists() else None
    child = json.loads(Path(outdir, "child.json").read_text()) if Path(outdir, "child.json").exists() else None
    return rec, child, out.decode(errors="replace")


def test_runner():
    # 1) 대화형 입력 유지
    rec, child, out = run_pty_scenario("interactive", lambda m, p, d, o: (os.write(m, "abc\n".encode()), d(1.0)))
    check("runner: 자식이 터미널 입력을 그대로 받음", child is not None and child.get("line") == "abc", str(child))
    check("runner: 자식 프롬프트가 터미널에 중계됨", "입력:" in out)
    check("runner: after_exit 실행·기록", rec is not None and rec.get("cleanup") == {"after_exit": "called"})

    # 2) Ctrl+C: 같은 프로세스 그룹 → 자식이 한 번만 SIGINT를 받음
    rec, child, out = run_pty_scenario("ctrlc", lambda m, p, d, o: (d(1.0), os.write(m, b"\x03"), d(2.0)))
    check("runner Ctrl+C: 자식 KeyboardInterrupt로 정상 정리", child is not None and child.get("got_keyboardinterrupt"), str(child))
    check("runner Ctrl+C: SIGINT 중복 없음(1회)", child is not None and child.get("sigint_count") == 1, str(child))
    check("runner Ctrl+C: 기록에 사용자 중단·exit 0", rec is not None and rec.get("user_interrupt") and rec.get("exit_code") == 0,
          json.dumps({k: rec.get(k) for k in ("user_interrupt", "exit_code", "forwarded_signal")} if rec else {}, ensure_ascii=False))
    tl = (rec or {}).get("teleop_loop", {})
    check("runner: 추종 루프 출력으로 루프 구간·Hz 기록", tl.get("loop_lines", 0) > 5 and tl.get("loop_span_s", 0) > 0.3 and tl.get("hz_median"),
          json.dumps(tl, ensure_ascii=False))

    # 3) SIGTERM → 자식에게 SIGINT 전달
    def term(m, p, d, o):
        d(1.0)
        os.kill(int(Path(o, "harness.pid").read_text()), signal.SIGTERM)
        d(2.0)

    rec, child, _ = run_pty_scenario("sigterm", term)
    check("runner SIGTERM: 자식에게 SIGINT 1회 전달 후 정상 정리", child is not None and child.get("sigint_count") == 1
          and rec is not None and rec.get("forwarded_signal") == "SIGTERM" and rec.get("cleanup"), str(child))

    # 4) SIGHUP(터미널 끊김: pty master 닫기) → 자식은 SIGHUP 무시, 부모가 SIGINT 전달, 정리·기록 완료
    def hup(m, p, d, o):
        d(1.0)
        os.close(m)

    rec, child, _ = run_pty_scenario("sighup", hup)
    check("runner SIGHUP: 자식이 SIGHUP을 무시하도록 실행됨", child is not None and child.get("sighup_ignored"), str(child))
    check("runner SIGHUP: 부모가 SIGINT를 전달해 자식이 정상 정리", child is not None and child.get("got_keyboardinterrupt")
          and rec is not None and rec.get("forwarded_signal") == "SIGHUP", json.dumps(rec.get("forwarded_signal") if rec else None))
    check("runner SIGHUP: 터미널이 없어도 after_exit와 기록 완료", rec is not None and rec.get("cleanup") == {"after_exit": "called"})

    # 5) 부모 비정상 종료(SIGKILL) → PDEATHSIG로 자식에게 SIGINT → 고아로 남지 않음
    def kill_parent(m, p, d, o):
        d(1.0)
        os.kill(int(Path(o, "harness.pid").read_text()), signal.SIGKILL)
        d(2.0)

    rec, child, _ = run_pty_scenario("parentkill", kill_parent)
    check("runner 부모 SIGKILL: 자식이 SIGINT를 받아 정리하고 종료(고아 방지)", child is not None and child.get("got_keyboardinterrupt"), str(child))

    # 6) SIGINT를 무시하는 자식 → SIGTERM → SIGKILL 단계적 종료(한도 시간)
    def stub(m, p, d, o):
        d(0.5)
        os.write(m, b"\x03")
        d(5.0)

    t0 = time.time()
    rec, child, _ = run_pty_scenario("stubborn", stub)
    check("runner 무응답 자식: 한도 후 SIGTERM/SIGKILL로 끝내고 원래 종료 상태 기록",
          rec is not None and rec.get("escalated") and rec.get("exit_signal") in ("SIGTERM", "SIGKILL"),
          json.dumps({k: rec.get(k) for k in ("escalated", "exit_signal")} if rec else {}, ensure_ascii=False) + f" {time.time() - t0:.1f}s")


# ============================================================================================
# 테스트: dry-run이 장치를 열지 않고 객체를 만들지 않음, 설정 검증, hardware doctor 진단
# ============================================================================================
def write_cfg(path: Path, **kw) -> Path:
    import yaml

    base = {"leader": {"type": "so101_leader", "id": "vl", "port": None},
            "follower": {"type": "so101_follower", "id": "vf", "port": None, "max_relative_target": None},
            "teleop": {"fps": 60, "time_s": None}, "calibration_root": str(VERIFY_DIR / "calibration")}
    for k, v in kw.items():
        sec, key = k.split("__")
        base[sec][key] = v
    if IS_MAC:  # 가짜 장치 포트에는 ports 마법사가 기록하는 것과 같은 USB 지문을 붙인다
        for role in ("leader", "follower"):
            fp = fake_usb_for(base[role].get("port"))
            if fp and "usb" not in base[role]:
                base[role]["usb"] = fp
    path.write_text(yaml.safe_dump(base, allow_unicode=True))
    return path


def test_dryrun_and_config(so101):
    import contextlib
    import io

    fake = FakeServoBus(std_motors())
    fake2 = FakeServoBus(std_motors())
    try:
        cfgp = write_cfg(VERIFY_DIR / "cfg_dry.yaml", leader__port=fake.slave_path, follower__port=fake2.slave_path,
                         follower__max_relative_target={j: 5.0 for j in so101.JOINTS})
        opened, created = [], []

        def hook(event, args):
            if event == "open" and args and isinstance(args[0], (str, bytes)) and str(args[0]).startswith("/dev/") \
                    and str(args[0]) not in ("/dev/null", "/dev/urandom"):
                opened.append(str(args[0]))

        sys.addaudithook(hook)
        from lerobot.robots.so_follower import SOFollower
        from lerobot.teleoperators.so_leader import SOLeader

        orig_f, orig_l = SOFollower.__init__, SOLeader.__init__
        SOFollower.__init__ = lambda self, *a, **k: (created.append("follower"), orig_f(self, *a, **k))[1]
        SOLeader.__init__ = lambda self, *a, **k: (created.append("leader"), orig_l(self, *a, **k))[1]
        rcs = {}
        try:
            for cmd in (["teleop", "--dry-run"], ["calibrate", "follower", "--dry-run"], ["setup-motors", "leader", "--dry-run"]):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rcs[" ".join(cmd)] = so101.main(["--config", str(cfgp), *cmd])
        finally:
            SOFollower.__init__, SOLeader.__init__ = orig_f, orig_l
        check("dry-run 3종 exit 0", all(v == 0 for v in rcs.values()), str(rcs))
        check("dry-run: /dev 장치 open 0건(audit hook)", not opened, str(opened))
        check("dry-run: 공식 Robot/Teleoperator 객체 생성 0건", not created, str(created))
        check("dry-run: 포트 쪽 선로에 아무 패킷도 없음", not fake.instructions and not fake2.instructions)
        # 없는 포트에서도 명령 확인 가능
        cfg_missing = write_cfg(VERIFY_DIR / "cfg_missing.yaml", leader__port="/dev/so101-nope-a", follower__port="/dev/so101-nope-b")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = so101.main(["--config", str(cfg_missing), "teleop", "--dry-run"])
        check("dry-run: 없는 포트여도 명령 표시·파싱 확인", rc == 0 and "lerobot-teleoperate" in buf.getvalue(), buf.getvalue().splitlines()[-1][:120])

        # 설정 타입 검증
        bad = write_cfg(VERIFY_DIR / "cfg_bad.yaml", teleop__time_s="<null 또는 초>", teleop__fps=True,
                        follower__max_relative_target={"shoulder_pan": 5.0})
        cfg, errs = so101.load_config(bad)
        joined = " | ".join(errs)
        check("설정 검증: 문자열 time_s 거부", "teleop.time_s" in joined)
        check("설정 검증: bool fps 거부", "teleop.fps" in joined)
        check("설정 검증: 관절 dict 키 누락 거부", "6개 관절 키" in joined, joined[:200])

        # hardware doctor 진단(포트를 열지 않음)
        rep = so101.Report()
        buf = io.StringIO()
        link_a, link_b = VERIFY_DIR / "link_a", VERIFY_DIR / "link_b"
        for l in (link_a, link_b):
            l.unlink(missing_ok=True)
            l.symlink_to(fake.slave_path)
        same = write_cfg(VERIFY_DIR / "cfg_same.yaml", leader__port=str(link_a), follower__port=str(link_b))
        cfg, errs = so101.load_config(same)
        opened.clear()
        with contextlib.redirect_stdout(buf):
            so101.doctor_hardware(rep, cfg, errs)
        titles = " | ".join(t for s, t, _ in rep.items if s == "FAIL")
        check("hardware doctor: 서로 다른 링크가 같은 실제 장치를 가리키면 FAIL", "같은 실제 장치" in titles, titles[:200])
        check("hardware doctor: 포트를 열지 않음", not opened, str(opened))
        check("hardware doctor: 보정 파일 없음은 WARN(teleop에서 거부)",
              any(s == "WARN" and "보정 파일 없음" in t for s, t, _ in rep.items))

        nul = write_cfg(VERIFY_DIR / "cfg_null.yaml")
        cfg, errs = so101.load_config(nul)
        rep = so101.Report()
        with contextlib.redirect_stdout(io.StringIO()):
            so101.doctor_hardware(rep, cfg, errs)
        check("hardware doctor: port null → FAIL '포트 미지정'", any("포트 미지정" in t for s, t, _ in rep.items if s == "FAIL"))

        miss = write_cfg(VERIFY_DIR / "cfg_m.yaml", leader__port="/dev/so101-nope-a", follower__port="/dev/so101-nope-b")
        cfg, errs = so101.load_config(miss)
        rep = so101.Report()
        with contextlib.redirect_stdout(io.StringIO()):
            so101.doctor_hardware(rep, cfg, errs)
        check("hardware doctor: 없는 포트 → FAIL '경로 없음'", any("경로 없음" in t for s, t, _ in rep.items if s == "FAIL"))

        os.chmod(fake2.slave_path, 0)
        try:
            perm = write_cfg(VERIFY_DIR / "cfg_p.yaml", leader__port=fake.slave_path, follower__port=fake2.slave_path)
            cfg, errs = so101.load_config(perm)
            rep = so101.Report()
            with contextlib.redirect_stdout(io.StringIO()):
                so101.doctor_hardware(rep, cfg, errs)
            msgs = [(t, d) for s, t, d in rep.items if s == "FAIL" and "권한" in t]
            check("hardware doctor: 권한 없음 진단(테스트용 pty, chmod 000)", bool(msgs), str(msgs)[:200])
        finally:
            os.chmod(fake2.slave_path, 0o620)

        # 점유 감지: 다른 프로세스가 포트를 열고 있음
        holder = subprocess.Popen([sys.executable, "-c", f"import os,time; fd=os.open({fake.slave_path!r}, os.O_RDWR|os.O_NOCTTY); time.sleep(30)"])
        time.sleep(0.5)
        try:
            busy = write_cfg(VERIFY_DIR / "cfg_b.yaml", leader__port=fake.slave_path, follower__port=fake2.slave_path)
            cfg, errs = so101.load_config(busy)
            rep = so101.Report()
            with contextlib.redirect_stdout(io.StringIO()):
                so101.doctor_hardware(rep, cfg, errs)
            check("hardware doctor: 다른 프로세스 점유 감지", any("사용 중" in t for s, t, _ in rep.items if s == "FAIL"))
        finally:
            holder.kill()
            holder.wait()
    finally:
        fake.close()
        fake2.close()


def test_teleop_refusal(so101):
    """보정 파일 없음/불일치이면 공식 teleop을 실행하지 않는다(자동 보정 진입 방지)."""
    import contextlib
    import io

    m = std_motors()
    fl, ff = FakeServoBus(m), FakeServoBus(m)
    launched = []
    orig = so101.run_official
    so101.run_official = lambda *a, **k: launched.append(a) or {
        "exit_code": 0, "exit_signal": None, "duration_s": 0.0, "teleop_loop": {}, "log": "logs/x.log",
        "cleanup": {"leader": {"status": "성공"}, "follower": {"status": "성공"}}}
    try:
        cfgp = write_cfg(VERIFY_DIR / "cfg_t.yaml", leader__port=fl.slave_path, follower__port=ff.slave_path,
                         leader__id="vt_leader", follower__id="vt_follower")
        for p in (VERIFY_DIR / "calibration").rglob("vt_*.json"):
            p.unlink()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = so101.main(["--config", str(cfgp), "teleop", "--onsite-confirmed"])
        check("teleop: 보정 파일 없으면 공식 명령 실행 거부", rc == 1 and not launched, buf.getvalue().strip().splitlines()[-1])
        write_calibration(so101, "leader", "vt_leader", m)
        mm = std_motors()
        mm[1]["offset"] = 99
        write_calibration(so101, "follower", "vt_follower", mm)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = so101.main(["--config", str(cfgp), "teleop", "--onsite-confirmed"])
        check("teleop: 보정 불일치면 공식 명령 실행 거부", rc == 1 and not launched and "불일치" in buf.getvalue())
        check("teleop 사전 점검: 모터 쓰기 0건", not fl.writes and not ff.writes, "; ".join(fl.write_summary() + ff.write_summary()))
        write_calibration(so101, "follower", "vt_follower", m)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = so101.main(["--config", str(cfgp), "teleop", "--onsite-confirmed", "--time-s", "30"])
        argv = launched[0][0] if launched else []
        check("teleop: 조건 충족 시 공식 lerobot-teleoperate 인자로 실행",
              bool(launched) and argv[0].endswith("lerobot-teleoperate") and "--teleop_time_s=30.0" in argv
              and f"--robot.port={ff.slave_path}" in argv, " ".join(argv[1:4]))
        check("teleop: 시작 자세 차이 표 출력", "시작 자세 차이" in buf.getvalue())
    finally:
        so101.run_official = orig
        fl.close()
        ff.close()


# ============================================================================================
# 테스트: macOS 전용(런처·tty/cu·comports·USB 지문·포트 마법사·caffeinate)
# ============================================================================================
def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _wait_gone(pid: int, timeout: float) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if not _alive(pid):
            return True
        time.sleep(0.1)
    return not _alive(pid)


def test_macos_launcher(so101):
    py, L = sys.executable, str(so101.LAUNCHER)
    tmp = Path(tempfile.mkdtemp(prefix="launcher_", dir=VERIFY_DIR))
    env = dict(os.environ, SO101_LAUNCH_DEBUG="1")

    def script(name: str, body: str) -> str:
        f = tmp / name
        f.write_text(body)
        return str(f)

    s7 = script("exit7.py", "import sys\nsys.exit(7)\n")
    r = subprocess.run([py, L, str(os.getpid()), "--", py, s7], capture_output=True, text=True, env=env, timeout=30)
    check("launcher: 종료 코드 보존(sys.exit(7) → 7)", r.returncode == 7, r.stderr.strip()[-120:])
    sx = script("raise.py", "raise ValueError('boom-from-official')\n")
    r = subprocess.run([py, L, str(os.getpid()), "--", py, sx], capture_output=True, text=True, env=env, timeout=30)
    check("launcher: 예외 traceback·종료 코드 1 보존", r.returncode == 1 and "ValueError: boom-from-official" in r.stderr
          and "Traceback" in r.stderr, r.stderr.strip().splitlines()[-1][:120] if r.stderr.strip() else "")
    sa = script("argv.py", "import sys, json, signal\nprint(json.dumps({'argv': sys.argv, 'path0': sys.path[0], "
                "'int_default': signal.getsignal(signal.SIGINT) is signal.default_int_handler, "
                "'hup_ign': signal.getsignal(signal.SIGHUP) == signal.SIG_IGN, 'name': __name__}))\n")
    r = subprocess.run([py, L, str(os.getpid()), "--", py, sa, "a b", "--x=1"], capture_output=True, text=True, env=env, timeout=30)
    try:
        j = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        j = {}
    check("launcher: argv·__main__·sys.path[0]·SIGINT 기본 핸들러·SIGHUP 무시",
          j.get("argv") == [sa, "a b", "--x=1"] and j.get("name") == "__main__" and j.get("path0") == str(tmp)
          and j.get("int_default") and j.get("hup_ign"), json.dumps(j)[:200])
    cli = str(so101.VENV_BIN / "lerobot-find-cameras")
    d = subprocess.run([cli, "--help"], capture_output=True, text=True, timeout=180)
    w = subprocess.run([py, L, str(os.getpid()), "--", cli, "--help"], capture_output=True, text=True, env=env, timeout=180)
    check("launcher: 공식 console script(lerobot-find-cameras --help)가 직접 실행과 같은 출력·종료 코드",
          d.returncode == w.returncode == 0 and d.stdout.replace(cli, "") == w.stdout.replace(cli, ""), f"rc {d.returncode}/{w.returncode}")
    # 시작 시점에 지정한 부모가 이미 없음(경합): 등록 실패 → 즉시 SIGINT
    dead = subprocess.Popen(["/usr/bin/true"])
    dead.wait()
    mk = tmp / "gone.json"
    sg = script("gone.py", f"import time, json, pathlib\ntry:\n    time.sleep(10)\n    r='timeout'\nexcept KeyboardInterrupt:\n"
                f"    r='KeyboardInterrupt'\npathlib.Path({str(mk)!r}).write_text(json.dumps(r))\n")
    t0 = time.time()
    r = subprocess.run([py, L, str(dead.pid), "--", py, sg], capture_output=True, text=True, env=env, timeout=30)
    dt = time.time() - t0
    # 공식 스크립트를 시작하기 전에 SIGINT로 끝나야 한다(스크립트 본문 미실행 = 모터에 접근하지 않음).
    check("launcher: 시작 시 부모가 이미 없으면(등록 실패 포함) 공식 스크립트 실행 전 즉시 종료",
          not mk.exists() and r.returncode in (-2, 130) and "kqueue registration failed" in r.stderr
          and "parent gone -> SIGINT self" in r.stderr and dt < 5,
          f"rc={r.returncode} {dt:.1f}s marker={mk.exists()}")


def test_macos_runner_extra():
    # kqueue 대신 폴링 경로(등록 실패 대체 경로)에서도 부모 SIGKILL 후 정리
    def kill_parent(m, p, d, o):
        d(1.0)
        os.kill(int(Path(o, "harness.pid").read_text()), signal.SIGKILL)
        d(2.5)

    rec, child, _ = run_pty_scenario("parentkill", kill_parent)
    log = "".join(Path(x).read_text(errors="replace") for x in Path(VERIFY_DIR).glob("run_parentkill_*/fake.log"))
    check("runner(macOS): 부모 SIGKILL 감시 방식이 kqueue였음(로그)", "parent watch: kqueue" in log, "")
    rec, child, _ = run_pty_scenario("parentkill_poll", kill_parent)
    log = "".join(Path(x).read_text(errors="replace") for x in Path(VERIFY_DIR).glob("run_parentkill_poll_*/fake.log"))
    pid = int(next(Path(VERIFY_DIR).glob("run_parentkill_poll_*/child.json.pid")).read_text()) if child else None
    reason = "SIGINT" if (child or {}).get("got_keyboardinterrupt") else ("출력 파이프 닫힘" if (child or {}).get("broken_pipe") else "?")
    check("runner(macOS): 폴링 대체 경로에서도 부모 SIGKILL 후 자식 정리 경로 실행·종료(고아 없음)",
          child is not None and reason != "?" and "parent watch: poll" in log and pid is not None and _wait_gone(pid, 3.0),
          f"종료 원인={reason}, {child}")

    # SIGINT를 무시하는 자식 + 부모 SIGKILL → 런처가 SIGTERM으로 단계적 종료(고아로 남지 않음)
    pid_box = {}

    def kill_parent_stub(m, p, d, o):
        d(1.2)
        pid_box["child"] = int(next(Path(o).glob("child.json.pid")).read_text())
        os.kill(int(Path(o, "harness.pid").read_text()), signal.SIGKILL)
        d(0.2)

    run_pty_scenario("parentkill_stubborn", kill_parent_stub)
    cp = pid_box.get("child")
    check("runner(macOS): SIGINT 무시 자식도 부모 사망 후 SIGTERM/SIGKILL로 종료(고아 없음)", cp is not None and _wait_gone(cp, 6.0),
          f"child pid {cp}")

    # caffeinate: 자식이 사는 동안만 존재, 끝나면 종료(정상 종료·Ctrl+C)
    rec, child, _ = run_pty_scenario("awake", lambda m, p, d, o: d(2.0))
    cpids = [int(x) for x in (child or {}).get("caffeinate_pids", [])]
    ka = (rec or {}).get("keep_awake", {})
    check("caffeinate: 공식 자식 실행 중 caffeinate -i -w <자식PID>가 존재", len(cpids) == 1 and ka.get("caffeinate_pid") == cpids[0],
          f"{cpids} {ka}")
    check("caffeinate: 자식 정상 종료 후 함께 종료", bool(cpids) and _wait_gone(cpids[0], 3.0) and ka.get("ended"), str(ka))
    rec, child, _ = run_pty_scenario("awake_ctrlc", lambda m, p, d, o: (d(1.0), os.write(m, b"\x03"), d(2.0)))
    ka = (rec or {}).get("keep_awake", {})
    check("caffeinate: Ctrl+C 종료 경로에서도 종료", ka.get("ended") and not _alive(ka.get("caffeinate_pid", 0) or 0) if ka.get("caffeinate_pid") else False,
          str(ka))


def test_macos_ports(so101):
    import contextlib
    import io

    NS = types.SimpleNamespace
    c = so101.canonical_port
    check("tty/cu 정규화: /dev/tty.X와 /dev/cu.X는 같은 장치, 다른 이름은 다른 장치",
          c("/dev/tty.usbmodemA1") == c("/dev/cu.usbmodemA1") == "/dev/cu.usbmodemA1" and c("/dev/cu.usbmodemB2") != c("/dev/cu.usbmodemA1")
          and c("/dev/ttys012") == "/dev/ttys012")
    orig = so101.COMPORTS_FN

    def mk(dev, vid=0x1a86, pid=0x55d3, serial=None, loc=None):
        return NS(device=dev, vid=vid, pid=pid, serial_number=serial, location=loc, manufacturer="m", product="p", description="d")

    try:
        so101.COMPORTS_FN = lambda: [mk("/dev/cu.Bluetooth-Incoming-Port", vid=None, pid=None), mk("/dev/cu.debug-console", vid=None, pid=None),
                                     mk("/dev/cu.usbmodemA1", serial="A1", loc="0-1"), mk("/dev/tty.usbmodemA1", serial="A1", loc="0-1")]
        ports = so101.mac_usb_ports()
        check("comports: Bluetooth·debug-console 제외, 같은 보드의 tty/cu는 1개", [u["device"] for u in ports] == ["/dev/cu.usbmodemA1"],
              str([u["device"] for u in ports]))

        # USB 지문 대조
        def fp_rep(arm_usb, ports_list, strict=True):
            so101.COMPORTS_FN = lambda: ports_list
            rep = so101.Report()
            arm = so101.ArmCfg("follower", "so101_follower", "f", "/dev/cu.usbmodemA1", arm_usb)
            with contextlib.redirect_stdout(io.StringIO()):
                ok = so101.check_usb_fingerprint(rep, "follower", arm, "/dev/cu.usbmodemA1", strict=strict)
            return ok, rep

        base = [mk("/dev/cu.usbmodemA1", serial="A1", loc="0-1"), mk("/dev/cu.usbmodemB2", serial="B2", loc="0-2")]
        ok, rep = fp_rep({"vid": "1a86", "pid": "55d3", "serial": "A1", "location": "0-1", "id_by": "serial"}, base)
        check("USB 지문: serial 기준 일치 → OK", ok and not rep.n_fail)
        ok, rep = fp_rep({"vid": "1a86", "pid": "55d3", "serial": "ZZ", "location": "0-1", "id_by": "serial"}, base)
        check("USB 지문: serial 다름(다른 보드) → FAIL", not ok and rep.n_fail == 1)
        ok, rep = fp_rep({"vid": "1a86", "pid": "55d3", "serial": "A1", "location": "0-9", "id_by": "serial"}, base)
        check("USB 지문: serial 같고 단자만 바뀜 → OK + 안내(INFO)", ok and not rep.n_fail and any(s == "INFO" for s, _, _ in rep.items))
        dupl = [mk("/dev/cu.usbmodemA1", serial="SAME", loc="0-1"), mk("/dev/cu.usbmodemB2", serial="SAME", loc="0-2")]
        ok, rep = fp_rep({"vid": "1a86", "pid": "55d3", "serial": "SAME", "location": "0-1", "id_by": "serial"}, dupl)
        check("USB 지문: 같은 serial 장치가 둘 → serial로 판단 불가 FAIL", not ok and rep.n_fail == 1)
        nos = [mk("/dev/cu.usbmodemA1", serial=None, loc="0-1"), mk("/dev/cu.usbmodemB2", serial=None, loc="0-2")]
        ok, rep = fp_rep({"vid": "1a86", "pid": "55d3", "serial": None, "location": "0-2", "id_by": "location"}, nos)
        check("USB 지문: serial 없는 보드 위치가 다름 → FAIL", not ok and rep.n_fail == 1)
        ok, rep = fp_rep(None, base, strict=True)
        ok2, rep2 = fp_rep(None, base, strict=False)
        check("USB 지문: 기록 없음 → 쓰기·구동 명령 FAIL, doctor·probe WARN", not ok and rep.n_fail == 1 and ok2 and rep2.n_warn == 1)
    finally:
        so101.COMPORTS_FN = orig


def test_macos_wizard(so101):
    import contextlib
    import io

    import yaml

    NS = types.SimpleNamespace
    orig = so101.COMPORTS_FN
    wdir = VERIFY_DIR / "wizard"
    wdir.mkdir(parents=True, exist_ok=True)
    opened: list[str] = []

    def hook(event, args):
        if event == "open" and args and isinstance(args[0], (str, bytes)) and str(args[0]).startswith("/dev/") \
                and str(args[0]) not in ("/dev/null", "/dev/urandom"):
            opened.append(str(args[0]))

    sys.addaudithook(hook)

    def mk(dev, serial, loc, vid=0x1a86):
        return NS(device=dev, vid=vid, pid=0x55d3, serial_number=serial, location=loc, manufacturer="QinHeng", product="USB Single Serial",
                  description="d")

    def run(target: Path, stages: list[list], answers: list[str], *, raise_at: str | None = None):
        """stages: [기준 목록, 리더 연결 후, 팔로워 연결 후], answers: 입력 응답 순서."""
        st = {"i": 0}
        so101.COMPORTS_FN = lambda: stages[min(st["i"], len(stages) - 1)]
        prompts: list[str] = []
        ans = list(answers)

        def ask(prompt: str) -> str:
            prompts.append(prompt)
            if raise_at and raise_at in prompt:
                raise KeyboardInterrupt
            if "연결하고 Enter" in prompt:
                st["i"] += 1
            if not ans:  # 실제 input()처럼 입력이 끝나면 EOFError(마법사는 취소로 처리)
                raise EOFError
            return ans.pop(0)

        args = NS(config=target)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = so101.cmd_assign_ports(args, None, [], ask=ask, scan=lambda prev: so101.mac_usb_ports())
        return rc, buf.getvalue(), prompts

    L = mk("/dev/cu.usbmodemL1", "L1", "0-1")
    F = mk("/dev/cu.usbmodemF2", "F2", "0-2")
    other = mk("/dev/cu.usbserial-OTHER", "O9", "0-3", vid=0x0403)
    try:
        # 1) 새 파일: 예시 기반 생성, 저장, 주석 보존, 지문 기록
        t1 = wdir / "new.local.yaml"
        rc, out, _ = run(t1, [[], [L], [L, F]], ["", "", "", "arm_leader_a", "arm_follower_a", "yes"])
        cfg, errs = so101.load_config(t1) if t1.exists() else (None, ["없음"])
        text = t1.read_text() if t1.exists() else ""
        check("ports 마법사: 정상 저장(예시 기반 새 파일)", rc == 0 and not errs and cfg.leader.port == L.device and cfg.follower.port == F.device
              and cfg.leader.id == "arm_leader_a" and cfg.follower.usb and cfg.follower.usb["serial"] == "F2", (out[-200:] if rc else ""))
        check("ports 마법사: 예시 주석·다른 값 보존", "# 공식 teleop 타입(고정)" in text and "disable_torque_on_disconnect: true" in text
              and "max_relative_target: null" in text)
        # 2) 기존 파일 갱신: 다른 설정(max_relative_target·fps·주석) 보존, 백업 생성, id Enter=유지
        raw = yaml.safe_load(t1.read_text())
        t1.write_text(t1.read_text().replace("  max_relative_target: null", "  max_relative_target: 7.5").replace("  fps: 60", "  fps: 50"))
        before = t1.read_bytes()
        L2 = mk("/dev/cu.usbmodemL1", "L1", "0-5")
        rc, out, _ = run(t1, [[other], [other, L2], [other, L2, F]], ["", "", "", "", "", "yes"])
        cfg, errs = so101.load_config(t1)
        baks = list(wdir.glob("new.local.yaml.bak-*"))
        check("ports 마법사: 기존 설정 갱신 시 다른 값 보존·백업 생성·id 유지", rc == 0 and not errs and cfg.max_relative_target == 7.5
              and cfg.fps == 50 and cfg.leader.id == "arm_leader_a" and len(baks) == 1 and baks[0].read_bytes() == before
              and cfg.leader.usb["location"] == "0-5", f"rc={rc} errs={errs} baks={len(baks)}")
        check("ports 마법사: 이미 연결된 비로봇 USB 장치는 후보에서 제외", cfg.leader.port == L2.device and cfg.follower.port == F.device)
        # 3) 후보 여러 개 → 사용자 선택(발견 순서로 추측하지 않음)
        t3 = wdir / "multi.local.yaml"
        X = mk("/dev/cu.usbmodemX7", "X7", "0-7")
        # 목록은 장치 이름순(usbmodemL1=1번, usbmodemX7=2번). 1번을 고르고, 고르지 않은 X7은 팔로워 후보에서도 빠져야 한다.
        rc, out, prompts = run(t3, [[], [X, L], [X, L, F]], ["", "", "1", "", "la", "fa", "yes"])
        cfg, errs = so101.load_config(t3) if t3.exists() else (None, ["없음"])
        check("ports 마법사: 새 장치 여러 개 → 번호 선택, 고르지 않은 장치는 팔로워 후보에서 제외",
              rc == 0 and cfg and cfg.leader.port == L.device and cfg.follower.port == F.device
              and sum("보드 번호" in p for p in prompts) == 1, out[-150:] if rc else f"follower={cfg.follower.port if cfg else None}")
        # 4) serial 없음/중복 → 위치 기준, 둘 다 없으면 거부
        t4 = wdir / "noserial.local.yaml"
        Ln, Fn = mk("/dev/cu.usbserial-110", None, "0-1"), mk("/dev/cu.usbserial-120", None, "0-2")
        rc, out, _ = run(t4, [[], [Ln], [Ln, Fn]], ["", "", "", "la", "fa", "yes"])
        cfg, _ = so101.load_config(t4) if t4.exists() else (None, [])
        check("ports 마법사: serial 없는 보드 → USB 위치 기준(id_by=location)으로 저장", rc == 0 and cfg and cfg.leader.usb["id_by"] == "location"
              and cfg.follower.usb["location"] == "0-2")
        t4b = wdir / "dupserial.local.yaml"
        Ld, Fd = mk("/dev/cu.usbmodemD1", "DUP", "0-1"), mk("/dev/cu.usbmodemD2", "DUP", "0-2")
        rc, out, _ = run(t4b, [[], [Ld], [Ld, Fd]], ["", "", "", "la", "fa", "yes"])
        cfg, _ = so101.load_config(t4b) if t4b.exists() else (None, [])
        check("ports 마법사: 같은 serial 두 보드 → 같은 보드로 오판하지 않고 위치 기준으로 저장", rc == 0 and cfg and cfg.leader.port != cfg.follower.port
              and cfg.leader.usb["id_by"] == cfg.follower.usb["id_by"] == "location")
        t4c = wdir / "noinfo.local.yaml"
        Lx, Fx = mk("/dev/cu.usbserial-A", None, None), mk("/dev/cu.usbserial-B", None, None)
        rc, out, _ = run(t4c, [[], [Lx], [Lx, Fx]], ["", "", "", "la", "fa", "yes"])
        check("ports 마법사: serial·위치 정보가 모두 없으면 자동 지정 거부(파일 미생성)", rc == 1 and not t4c.exists(), out.strip().splitlines()[-1][:120])
        # 5) 같은 보드 재사용(팔로워 단계에 새 장치 없음) → 취소, 파일 불변
        before = t1.read_bytes()
        rc, out, _ = run(t1, [[], [L], [L]], ["", "", "", "q"])
        check("ports 마법사: 팔로워 단계에서 새 장치가 없으면(같은 보드) 지정하지 않고 취소, 파일 불변", rc == 1 and t1.read_bytes() == before)
        # 6) 같은 ID 거부 후 재입력
        rc, out, prompts = run(t1, [[], [L], [L, F]], ["", "", "", "same_id", "same_id", "fid2", "yes"])
        cfg, _ = so101.load_config(t1)
        check("ports 마법사: 리더·팔로워 같은 ID 거부 후 재입력", rc == 0 and cfg.leader.id == "same_id" and cfg.follower.id == "fid2")
        # 7) 취소(Ctrl+C)·'no'·저장 중 예외 → 원본 불변, 임시 파일 없음
        before = t1.read_bytes()
        rc, out, _ = run(t1, [[], [L], [L, F]], ["", "", ""], raise_at="팔로워")
        check("ports 마법사: 진행 중 Ctrl+C → 원본 바이트 불변", rc == 1 and t1.read_bytes() == before)
        rc, out, _ = run(t1, [[], [L], [L, F]], ["", "", "", "", "", "no"])
        check("ports 마법사: 최종 확인에서 yes가 아니면 저장 안 함", rc == 1 and t1.read_bytes() == before)
        orig_replace = os.replace

        def boom(*a, **k):
            raise OSError("디스크 오류 시뮬레이션")

        os.replace = boom
        try:
            try:
                rc, out, _ = run(t1, [[], [L], [L, F]], ["", "", "", "", "", "yes"])
                exc = None
            except OSError as e:
                exc = e
        finally:
            os.replace = orig_replace
        leftovers = [x.name for x in wdir.glob(".new.local.yaml.*.tmp")]
        check("ports 마법사: 원자적 교체 실패 시 원본 불변·임시 파일 정리", exc is not None and t1.read_bytes() == before and not leftovers,
              f"{exc} leftovers={leftovers}")
        # 8) 구조가 예상과 다른 설정은 자동 수정 거부
        t8 = wdir / "weird.local.yaml"
        t8.write_text("leader: {type: so101_leader, id: a, port: null}\nfollower: {type: so101_follower, id: b, port: null}\n")
        b8 = t8.read_bytes()
        rc, out, _ = run(t8, [[], [L], [L, F]], ["", "", "", "", "", "yes"])
        check("ports 마법사: 예상과 다른 YAML 구조(flow mapping)는 자동 수정 거부, 파일 불변", rc == 1 and t8.read_bytes() == b8,
              out.strip().splitlines()[-1][:120] if out.strip() else "")
        check("ports 마법사: 모든 경로에서 /dev 장치 open 0건(audit hook)", not opened, str(opened[:5]))
    finally:
        so101.COMPORTS_FN = orig


def test_macos_record(so101):
    """녹화 래퍼: dry-run 무개방·업로드 false 고정·설정 거부·resume/새 이름·사전 점검 거부·공식 명령 실행 인자."""
    import contextlib
    import io

    import yaml

    import so101_dataset as D

    m = std_motors()
    fl, ff = FakeServoBus(m), FakeServoBus(m)
    rdir = VERIFY_DIR / "record"
    rdir.mkdir(parents=True, exist_ok=True)
    dsdir = rdir / "datasets"
    dsdir.mkdir(exist_ok=True)
    opened, cam_connect, launched = [], [], []

    def hook(event, args):
        if event == "open" and args and isinstance(args[0], (str, bytes)) and str(args[0]).startswith("/dev/") \
                and str(args[0]) not in ("/dev/null", "/dev/urandom"):
            opened.append(str(args[0]))

    sys.addaudithook(hook)
    from lerobot.cameras.opencv import OpenCVCamera

    orig_connect, orig_probe, orig_run = OpenCVCamera.connect, D.camera_probe, so101.run_official
    OpenCVCamera.connect = lambda self, *a, **k: cam_connect.append(self.config.index_or_path)

    def cams_file(**over):
        c = {"type": "opencv", "index_or_path": 0, "width": 640, "height": 480, "fps": 30}
        c.update(over)
        f = rdir / "cameras.yaml"
        f.write_text(yaml.safe_dump({"cameras": {"front": c}}))
        return f

    def rec_file(**over):
        d = {"name": "trial_a", "task": "pick the cube", "fps": 30, "episode_time_s": 20, "reset_time_s": 10, "num_episodes": 2,
             "datasets_dir": str(dsdir), "video": True, "vcodec": "libsvtav1"}
        d.update(over)
        f = rdir / "recording.yaml"
        f.write_text(yaml.safe_dump({"dataset": d}, allow_unicode=True))
        return f

    cfgp = write_cfg(rdir / "robot.yaml", leader__port=fl.slave_path, follower__port=ff.slave_path, leader__id="vr_leader",
                     follower__id="vr_follower")
    for pth in (VERIFY_DIR / "calibration").rglob("vr_*.json"):
        pth.unlink()

    def run(*extra, cams=None, recf=None):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = so101.main(["--config", str(cfgp), "record", "--cameras", str(cams or cams_file()), "--recording", str(recf or rec_file()), *extra])
        return rc, buf.getvalue()

    try:
        so101.run_official = lambda argv, **k: launched.append((argv, k)) or {
            "exit_code": 0, "exit_signal": None, "duration_s": 0.0, "teleop_loop": {}, "log": "logs/x.log",
            "cleanup": {"leader": {"status": "성공"}, "follower": {"status": "성공"}}}
        rc, out = run("--dry-run", "--manual")
        check("record --manual --dry-run: 스페이스바 진행 표시, 공식 episode_time_s=안전 상한 120",
              rc == 0 and "진행 방식: 스페이스바" in out and "--dataset.episode_time_s=120" in out, out.strip().splitlines()[-1][:120])
        rc, out = run("--dry-run")
        check("record --dry-run: exit 0, 공식 RecordConfig 파싱 OK", rc == 0 and "[  OK ] 공식 RecordConfig 파싱" in out, out.strip().splitlines()[-1])
        check("record --dry-run: push_to_hub=false·no_stamp·batch 1·play_sounds=false 고정, root=datasets/<name>",
              "--dataset.push_to_hub=false" in out and "--dataset.no_stamp=true" in out and "--dataset.video_encoding_batch_size=1" in out
              and "--play_sounds=false" in out and f"--dataset.root={dsdir / 'trial_a'}" in out and "--dataset.repo_id=local/trial_a" in out)
        check("record --dry-run: /dev open 0건·카메라 connect 0건·모터 패킷 0건·실행 0건",
              not opened and not cam_connect and not fl.instructions and not ff.instructions and not launched, f"{opened} {cam_connect}")
        bad_cases = [  # 파일을 실행 직전에 만든다(같은 파일 경로를 공유하므로 lambda로 지연)
            ("task 없음", lambda: {"recf": rec_file(task=None)}, "task"),
            ("eval_ 이름", lambda: {"recf": rec_file(name="eval_x")}, "eval_"),
            ("fps 0", lambda: {"recf": rec_file(fps=0)}, "fps"),
            ("음수 episode_time_s", lambda: {"recf": rec_file(episode_time_s=-1)}, "episode_time_s"),
            ("episodes 0", lambda: {"recf": rec_file(num_episodes=0)}, "num_episodes"),
            ("push_to_hub 키 시도", lambda: {"recf": rec_file(push_to_hub=True)}, "지원하지 않는 키"),
            ("카메라 index 미지정", lambda: {"cams": cams_file(index_or_path=None)}, "index_or_path"),
            ("카메라 fps ≠ 녹화 fps", lambda: {"cams": cams_file(fps=15)}, "fps"),
            ("없는 외장 저장 폴더", lambda: {"recf": rec_file(datasets_dir=str(rdir / "no_such_drive"))}, "저장 폴더가 없음"),
        ]
        for label, mkkw, needle in bad_cases:
            rc, out = run("--dry-run", **mkkw())
            check(f"record 설정 거부: {label}", rc == 1 and needle in out, out.strip().splitlines()[-1][:120] if out.strip() else "")
        rc, out = run("--dry-run", "--no-cameras", cams=rdir / "none.yaml")
        check("record: 카메라 없이 녹화는 --no-cameras 명시 때만 허용", rc == 0 and "카메라: 없음" in out)
        rc, out = run("--dry-run", cams=rdir / "missing_cameras.yaml")
        check("record: 카메라 설정 없음(+--no-cameras 아님) → 거부", rc == 1)
        # 기존 데이터셋: 덮어쓰기 거부, resume 호환 검사
        exist = dsdir / "trial_a"
        (exist / "meta").mkdir(parents=True, exist_ok=True)
        feats = D.expected_features({"front": {"type": "opencv", "index_or_path": 0, "width": 640, "height": 480, "fps": 30}}, True)
        (exist / "meta" / "info.json").write_text(json.dumps({"fps": 15, "robot_type": "so_follower", "features": feats}))
        rc, out = run("--dry-run")
        check("record: 같은 이름 데이터셋이 있으면 덮어쓰지 않고 거부(--resume/새 이름 안내)", rc == 1 and "이미 있음" in out)
        rc, out = run("--dry-run", "--resume")
        check("record --resume: fps 등 기존 데이터셋과 다르면 거부", rc == 1 and "fps: 기존 15" in out, out.strip().splitlines()[-1][:120])
        (exist / "meta" / "info.json").write_text(json.dumps({"fps": 30, "robot_type": "so_follower", "features": feats}))
        rc, out = run("--dry-run", "--resume")
        check("record --resume: 호환되면 통과, 공식 인자 --resume=true", rc == 0 and "--resume=true" in out)
        rc, out = run("--dry-run", "--resume", "--name", "trial_none")
        check("record --resume: 없는 데이터셋이면 거부", rc == 1 and "기존 데이터셋이 없음" in out)
        rc, out = run("--dry-run", "--name", "trial_b")
        check("record: 새 이름이면 통과", rc == 0)
        check("record dry-run 전체: /dev open 0건·카메라 connect 0건(resume 특징 계산 포함)", not opened and not cam_connect, f"{opened} {cam_connect}")
        # 실제 실행 경로(공식 명령은 가짜로 대체): 카메라 실패 → 모터 전 거부
        D.camera_probe = lambda c, **k: {"error": "카메라 열기 실패(시험)"}
        rc, out = run("--name", "trial_c", "--onsite-confirmed")
        check("record: 선택 카메라 실패 → 모터 접근 전 거부(패킷 0건)", rc == 1 and not launched and not fl.instructions and not ff.instructions)
        D.camera_probe = lambda c, **k: {"frames": 30, "measured_fps": 30.0, "shape": [480, 640, 3]}
        rc, out = run("--name", "trial_c", "--onsite-confirmed")
        check("record: 보정 파일 없음 → 공식 명령 실행 거부, 모터 쓰기 0건", rc == 1 and not launched and not fl.writes and not ff.writes)
        write_calibration(so101, "leader", "vr_leader", m)
        write_calibration(so101, "follower", "vr_follower", m)
        rc, out = run("--name", "trial_c", "--onsite-confirmed")
        argv, kw = launched[0] if launched else ([], {})
        launched.clear()
        rc_m, _ = run("--name", "trial_m", "--onsite-confirmed", "--manual")
        check("record --manual: 자식 환경에 SO101_RECORD_MANUAL=1 전달, episode_time_s=120",
              rc_m == 0 and launched and launched[-1][1]["env"].get("SO101_RECORD_MANUAL") == "1"
              and "--dataset.episode_time_s=120" in launched[-1][0])
        launched.clear()
        rc, out = run("--name", "trial_c2", "--onsite-confirmed", "--auto")
        argv, kw = launched[0] if launched else ([], {})
        check("record --auto: 자식 환경에 수동 모드 표시 없음, 설정 시간(20초) 사용",
              rc == 0 and "SO101_RECORD_MANUAL" not in kw.get("env", {}) and "--dataset.episode_time_s=20" in argv)
        # 녹화 중 카메라 보기: --mirror(내보내기만) / --view(창: 가짜 실행 파일로 대체, 녹화 뒤 종료되는지)
        orig_mdir, orig_vbin = so101.MIRROR_DIR, so101.VIEWER_BIN
        try:
            so101.MIRROR_DIR = rdir / "live"
            fake_v = rdir / "fake_viewer"
            fake_v.write_text("#!/bin/sh\necho \"$@\" > \"$(dirname \"$0\")/viewer_args\"\nexec sleep 30\n")
            fake_v.chmod(0o755)
            so101.VIEWER_BIN = fake_v
            os.utime(fake_v, (time.time() + 60, time.time() + 60))  # 소스보다 새것 → 빌드하지 않음
            launched.clear()
            rc_mi, out_mi = run("--name", "trial_mi", "--onsite-confirmed", "--mirror")
            env_mi = launched[-1][1]["env"] if launched else {}
            check("record --mirror: 자식 환경에 SO101_CAMERA_MIRROR 전달, 창은 띄우지 않고 다른 터미널 명령 안내",
                  rc_mi == 0 and env_mi.get("SO101_CAMERA_MIRROR") == str(so101.MIRROR_DIR) and not (rdir / "viewer_args").exists()
                  and "--mirror" in out_mi and "--no-focus" in out_mi, out_mi.strip().splitlines()[-1][:120] if out_mi.strip() else "")
            started: list = []
            orig_prep = so101.prepare_camera_mirror
            so101.prepare_camera_mirror = lambda env, open_window: started.append(orig_prep(env, open_window)) or started[-1]
            launched.clear()
            fast_run = so101.run_official
            so101.run_official = lambda argv, **k: time.sleep(0.8) or fast_run(argv, **k)  # 녹화 중 창이 떠 있는 시간
            rc_v, _ = run("--name", "trial_v", "--onsite-confirmed", "--view")
            so101.run_official = fast_run
            so101.prepare_camera_mirror = orig_prep
            vp = started[0] if started else None
            time.sleep(0.3)
            vargs = (rdir / "viewer_args").read_text().split() if (rdir / "viewer_args").exists() else []
            check("record --view: 창을 --mirror <폴더> --no-focus(키보드 초점 유지)로 띄우고, 녹화가 끝나면 종료",
                  rc_v == 0 and vp is not None and vp.poll() is not None and vargs == ["--mirror", str(so101.MIRROR_DIR), "--no-focus"]
                  and launched and launched[-1][1]["env"].get("SO101_CAMERA_MIRROR") == str(so101.MIRROR_DIR),
                  f"args={vargs} exited={vp.poll() if vp else None}")
            try:
                with contextlib.redirect_stderr(io.StringIO()):
                    rc_x, _ = run("--name", "trial_x", "--onsite-confirmed", "--view", "--mirror")
            except SystemExit as e:  # argparse 거부
                rc_x = e.code
            check("record: --view와 --mirror는 함께 쓸 수 없음", rc_x != 0)
        finally:
            so101.MIRROR_DIR, so101.VIEWER_BIN = orig_mdir, orig_vbin
        check("record: 조건 충족 시 공식 lerobot-record를 업로드 없이 실행(절전 방지·양팔 정리 포함)",
              rc == 0 and argv and argv[0].endswith("lerobot-record") and "--dataset.push_to_hub=false" in argv
              and kw.get("keep_awake") is True and callable(kw.get("after_exit")) and not fl.writes and not ff.writes,
              " ".join(a for a in argv[1:4]))
        check("record: 수집 기록(manifest)을 공식 폴더 밖에 남김(보정 파일 hash 포함)",
              (dsdir / "trial_c.so101.json").is_file() and json.loads((dsdir / "trial_c.so101.json").read_text())["sessions"][0]["arms"]["follower"]["sha256"])
    finally:
        OpenCVCamera.connect, D.camera_probe, so101.run_official = orig_connect, orig_probe, orig_run
        fl.close()
        ff.close()


def test_macos_record_hooks(so101):
    """스페이스바 진행 모드: 공식 init_keyboard_listener(키 해석)는 그대로, 녹화 루프만 가짜로 바꿔 단계 전환을 확인한다."""
    import contextlib
    import io

    import lerobot.scripts.lerobot_record as R
    from lerobot.utils import keyboard_input as K

    import so101_record_hooks as H

    log: list[tuple[str, float]] = []
    captured = {}

    def fake_ckl(dispatch, *, controls_help=""):  # 공식 리스너 대신 dispatch만 잡는다(터미널을 읽지 않음)
        captured["d"] = dispatch
        return types.SimpleNamespace(stop=lambda: None)

    def fake_record_loop(robot, events, fps, a=None, b=None, c=None, dataset=None, teleop=None, control_time_s=None, **kw):
        log.append(("record" if dataset is not None else "wait", control_time_s))
        t0 = time.time()
        while time.time() - t0 < min(control_time_s, 30):
            if events["exit_early"]:
                events["exit_early"] = False
                break
            time.sleep(0.01)

    orig = (K.create_key_listener, R.record_loop, dict(H._state))
    K.create_key_listener, R.record_loop = fake_ckl, fake_record_loop
    H._state.update(ready_done=False, last_ep=None, installed=False)
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            H.install()
            listener, events = K.init_keyboard_listener()  # 공식 키 매핑(n/r/q, 방향키)을 그대로 사용
        press = captured["d"]
        ds = types.SimpleNamespace(num_episodes=0)

        def run(**kw):
            th = threading.Thread(target=lambda: R.record_loop(None, events, 30, None, None, None, **kw), daemon=True)
            th.start()
            return th

        def settle():
            time.sleep(0.25)

        with contextlib.redirect_stdout(out):
            # 1) 첫 에피소드: 준비 단계에서 r은 무시, 스페이스바로 녹화 시작, 스페이스바로 종료
            th = run(dataset=ds, control_time_s=10)
            settle(); press("r"); settle()
            ready_still = th.is_alive() and all(k == "wait" for k, _ in log) and not events["rerecord_episode"]
            press("space"); settle()
            started = any(k == "record" for k, _ in log)
            press("space"); th.join(3)
            ok1 = (not th.is_alive()) and not events["rerecord_episode"]
            # 2) 환경 재설정: r → 버림 표시 유지하며 계속 대기, 스페이스바로 끝
            log.clear()
            th = run(dataset=None, control_time_s=10)
            settle(); press("r"); settle()
            reset_wait = th.is_alive() and events["rerecord_episode"]
            press("space"); th.join(3)
            ok2 = (not th.is_alive()) and events["rerecord_episode"] and all(c >= 1000 for _, c in log)
            events["rerecord_episode"] = False
            # 3) 두 번째 녹화: 준비 단계 없이 바로 녹화, 키를 안 누르면 안전 상한에서 종료
            log.clear()
            ds.num_episodes = 1
            th = run(dataset=ds, control_time_s=0.3)
            th.join(3)
            ok3 = (not th.is_alive()) and [k for k, _ in log] == ["record"]
            # 4) q: 대기 단계에서도 종료
            log.clear()
            th = run(dataset=None, control_time_s=10)
            settle(); press("q"); th.join(3)
            ok4 = (not th.is_alive()) and events["stop_recording"]
        text = out.getvalue()
        check("스페이스바 모드: 준비 단계에서 r은 무시되고 계속 대기(저장 없는 공식 루프)", ready_still)
        check("스페이스바 모드: 준비 → 스페이스바 → 녹화 시작 → 스페이스바 → 종료(재녹화 아님)", started and ok1)
        check("스페이스바 모드: 재설정 단계에서 r → 버림 표시 유지·계속 대기, 스페이스바로 다음 단계", reset_wait and ok2)
        check("스페이스바 모드: 두 번째 에피소드는 준비 없이 바로 녹화, 무입력 시 안전 상한에서 종료", ok3 and "안전 상한" in text)
        check("스페이스바 모드: q는 대기 단계에서도 녹화 종료", ok4)
        check("스페이스바 모드: 단계 안내 문구 출력", all(m in text for m in ("▶ 준비", "● 녹화 중", "■ 환경 재설정")))
    finally:
        K.create_key_listener, R.record_loop = orig[0], orig[1]
        H._state.clear(); H._state.update(orig[2])


def test_macos_camera_mirror(so101):
    """실행 중 카메라 보기: 공식 프로세스 안에서 이미 읽은 프레임만 JPEG로 내보낸다(카메라를 다시 열지 않음). 카메라 없이 검사."""
    import numpy as np

    import so101_camera_mirror as M

    tmp = Path(tempfile.mkdtemp(prefix="mirror_", dir=VERIFY_DIR))
    # 1) 내보내기 루프: 가짜 카메라(공식 OpenCVCamera와 같은 frame_lock·latest_frame·latest_timestamp)
    cam = types.SimpleNamespace(frame_lock=threading.Lock(), latest_frame=None, latest_timestamp=None)
    stop = threading.Event()
    res: dict = {}
    th = threading.Thread(target=lambda: res.setdefault("n", M.mirror_loop(cam, "front", tmp, 20.0, stop)), daemon=True)
    th.start()
    time.sleep(0.3)
    none_yet = not (tmp / "front.jpg").exists()
    t_end = time.time() + 1.0
    k = 0
    while time.time() < t_end:  # 공식 읽기 스레드처럼 30Hz로 새 배열을 바꿔 끼운다
        with cam.frame_lock:
            cam.latest_frame = np.full((480, 640, 3), k % 255, dtype=np.uint8)
            cam.latest_timestamp = time.perf_counter()
        k += 1
        time.sleep(1 / 30)
    time.sleep(0.3)  # 새 프레임 없음 → 다시 쓰지 않아야 함
    stop.set()
    th.join(2)
    import cv2

    img = cv2.imread(str(tmp / "front.jpg"))
    leftovers = [f.name for f in tmp.iterdir() if f.name.endswith(".tmp")]
    check("카메라 미러: 프레임이 생기기 전에는 쓰지 않고, 이후 <이름>.jpg를 원자적으로 갱신(임시 파일 없음)",
          none_yet and img is not None and img.shape == (480, 640, 3) and not leftovers, f"shape={None if img is None else img.shape}, tmp={leftovers}")
    check("카메라 미러: 지정 속도(20Hz) 이하로만 쓰고, 같은 프레임은 다시 쓰지 않음", 10 <= res.get("n", 0) <= 21 and not th.is_alive(),
          f"1초 동안 {res.get('n')}장(카메라 프레임 {k}장)")
    # 2) 오류가 나도 예외를 밖으로 내지 않고 그 카메라만 멈춤
    bad = types.SimpleNamespace(frame_lock=threading.Lock(), latest_frame="not-an-image", latest_timestamp=1.0)
    import contextlib
    import io

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            n_bad = M.mirror_loop(bad, "wrist", tmp, 50.0, threading.Event())
        raised = False
    except Exception:  # noqa: BLE001
        raised, n_bad = True, -1
    check("카메라 미러: 인코딩 오류는 경고 한 줄 후 그 카메라만 중단(공식 동작에 예외 전파 없음)", not raised and n_bad == 0 and "내보내기 중단" in buf.getvalue(),
          buf.getvalue().strip()[:120])
    # 3) 런처: SO101_CAMERA_MIRROR가 있으면 로봇 모듈 import 전에 설치 → so_follower가 쓰는 함수가 이름 붙이는 함수로 바뀜
    probe = tmp / "probe.py"
    probe.write_text("import json\nfrom lerobot.robots.so_follower import so_follower as m\n"
                     "from lerobot.cameras.opencv.camera_opencv import OpenCVCamera\n"
                     "from lerobot.cameras.opencv import OpenCVCameraConfig\n"
                     "cams = m.make_cameras_from_configs({'front': OpenCVCameraConfig(index_or_path=1, width=640, height=480, fps=30)})\n"
                     "print(json.dumps({'name': getattr(cams['front'], '_so101_mirror_name', None), "
                     "'connect': OpenCVCamera.connect.__qualname__}))\n")
    py, L = sys.executable, str(so101.LAUNCHER)

    def run(extra):
        env = {k: v for k, v in os.environ.items() if k not in ("SO101_CAMERA_MIRROR", "SO101_RECORD_MANUAL")}
        env.update(extra)
        r = subprocess.run([py, L, str(os.getpid()), "--", py, str(probe)], capture_output=True, text=True, env=env, timeout=120)
        try:
            return json.loads(r.stdout.strip().splitlines()[-1]), r
        except Exception:  # noqa: BLE001
            return {}, r
    j_on, r_on = run({"SO101_CAMERA_MIRROR": str(tmp / "live")})
    j_both, _ = run({"SO101_CAMERA_MIRROR": str(tmp / "live"), "SO101_RECORD_MANUAL": "1"})
    j_off, _ = run({})
    check("카메라 미러: 런처가 SO101_CAMERA_MIRROR일 때만 설치, 카메라 이름(front)이 붙음(녹화 스페이스바 모드와 함께여도)",
          j_on.get("name") == "front" and "install" in str(j_on.get("connect")) and j_both.get("name") == "front"
          and j_off.get("name") is None and "install" not in str(j_off.get("connect")),
          f"on={j_on} both={j_both} off={j_off} {r_on.stderr.strip()[-120:] if not j_on else ''}")
    # 4) 실행 스크립트: 문법, 인자 없으면 사용법만(카메라·창·모델을 열지 않음)
    sh = WS / "tools" / "rollout_with_view.sh"
    syn = subprocess.run(["bash", "-n", str(sh)], capture_output=True, text=True)
    use = subprocess.run([str(sh)], capture_output=True, text=True, timeout=30)
    check("rollout_with_view.sh: 문법 OK, 인자 없으면 사용법 출력 후 종료 코드 2", syn.returncode == 0 and use.returncode == 2 and "rollout" in use.stdout,
          (syn.stderr + use.stdout)[:120])


def timing_child(tag: str) -> None:
    """[macOS] 런처 아래에서 실행되는 rollout 루프 재현(하드웨어 없음): 가짜 서보(pty) + 실제 SO101Follower(max_relative_target)
    + 실제 SyncInferenceEngine(작은 무작위 ACT, CPU). SO101_ROLLOUT_TIMING이 있으면 런처가 계측 훅을 설치한 상태다."""
    import numpy as np
    import torch

    so101 = setup_module()
    motors = std_motors()
    cal = write_calibration(so101, "follower", "vt_follower", motors)
    fake = FakeServoBus(motors)
    from lerobot.configs.types import FeatureType, PolicyFeature
    from lerobot.policies.act.configuration_act import ACTConfig
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies.factory import make_pre_post_processors
    from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig
    from lerobot.rollout.inference.sync import SyncInferenceEngine
    from lerobot.rollout.robot_wrapper import ThreadSafeRobot
    from lerobot.utils.feature_utils import build_dataset_frame, combine_feature_dicts, hw_to_dataset_features

    torch.manual_seed(0)
    robot = SO101Follower(SO101FollowerConfig(port=fake.slave_path, id="vt_follower", calibration_dir=cal.parent, max_relative_target=3.0))
    obs_ft = dict(robot.observation_features, front=(48, 64, 3))
    feats = combine_feature_dicts(hw_to_dataset_features(robot.action_features, "action"), hw_to_dataset_features(obs_ft, "observation"))
    keys = list(robot.action_features)
    cfg = ACTConfig(device="cpu", n_action_steps=1, temporal_ensemble_coeff=0.01, chunk_size=10, pretrained_backbone_weights=None,
                    dim_model=64, dim_feedforward=128, n_heads=4, n_encoder_layers=1, n_vae_encoder_layers=1,
                    input_features={"observation.state": PolicyFeature(FeatureType.STATE, (6,)),
                                    "observation.images.front": PolicyFeature(FeatureType.VISUAL, (3, 48, 64))},
                    output_features={"action": PolicyFeature(FeatureType.ACTION, (6,))})
    policy = ACTPolicy(cfg).eval()
    stats = {"observation.state": {"mean": torch.zeros(6), "std": torch.ones(6) * 30},
             "action": {"mean": torch.zeros(6), "std": torch.ones(6) * 30},
             "observation.images.front": {"mean": torch.zeros(3, 1, 1), "std": torch.ones(3, 1, 1)}}
    pre, post = make_pre_post_processors(policy_cfg=cfg, dataset_stats=stats)
    eng = SyncInferenceEngine(policy=policy, preprocessor=pre, postprocessor=post, dataset_features=feats, ordered_action_keys=keys,
                              task="t", device="cpu", robot_type=robot.robot_type)
    robot.connect(calibrate=False)
    rw = ThreadSafeRobot(robot)
    T = sys.modules.get("so101_rollout_timing")
    if T:
        T._state["in_run"] = True  # BaseStrategy.run 안과 같은 상태
    rng = np.random.default_rng(0)
    sent = []
    try:
        for _ in range(12):
            obs = rw.get_observation()
            obs["front"] = rng.integers(0, 255, (48, 64, 3), dtype=np.uint8)
            a = eng.get_action(build_dataset_frame(feats, obs, prefix="observation"))
            out = rw.send_action({k: float(a[j]) for j, k in enumerate(keys)})
            sent.append([round(float(out[k]), 6) for k in keys])
            time.sleep(0.005)
    finally:
        if T:
            T._state["in_run"] = False
            T._write()
        robot.disconnect()
        fake.close()
    print("TIMING_CHILD " + json.dumps({"tag": tag, "sent": sent}))


def test_macos_rollout_timing(so101):
    """rollout 단계별 계측 훅: 런처 설치 여부, 단계별 기록, 출력 동일성, 래퍼 --timing 전달."""
    py, L = sys.executable, str(so101.LAUNCHER)
    tmp = Path(tempfile.mkdtemp(prefix="timing_", dir=VERIFY_DIR))
    me = str(Path(__file__).resolve())

    def run(tag, timing, mode=None):
        env = {k: v for k, v in os.environ.items()
               if k not in ("SO101_ROLLOUT_TIMING", "SO101_ROLLOUT_TIMING_MODE", "SO101_CAMERA_MIRROR", "SO101_RECORD_MANUAL")}
        if timing:
            env["SO101_ROLLOUT_TIMING"] = str(tmp / tag)
        if mode:
            env["SO101_ROLLOUT_TIMING_MODE"] = mode
        r = subprocess.run([py, L, str(os.getpid()), "--", py, me, "--timing-child", tag], capture_output=True, text=True, env=env, timeout=300)
        line = [x for x in r.stdout.splitlines() if x.startswith("TIMING_CHILD ")]
        return (json.loads(line[-1][13:]) if line else {}), r

    on, r_on = run("on", True)
    off, r_off = run("off", False)
    files = sorted((tmp / "on").glob("rollout-timing-*.json")) if (tmp / "on").is_dir() else []
    summ = json.loads(files[0].read_text())["summary"] if files else {}
    need = ("tick", "obs", "obs_motor", "to_tensor", "preprocessor", "model", "ensemble", "postprocessor", "engine", "send",
            "send_motor_read", "send_motor_write")
    missing = [k for k in need if not summ.get(k, {}).get("mean", 0) > 0]
    check("rollout 계측: 런처가 설치, 틱별 단계(모터 읽기·텐서 변환·전처리·모델·앙상블·후처리·제한용 읽기·쓰기) 모두 기록",
          bool(files) and not missing and summ.get("ticks_total") == 11 and "clip_ratio" in summ,
          f"missing={missing} ticks={summ.get('ticks_total')} clip={summ.get('clip_ratio')} {r_on.stderr.strip()[-160:] if not files else ''}")
    check("rollout 계측: 켜도 로봇에 보낸 목표값이 끄고 실행한 것과 같음(값 불변), 끄면 기록 파일 없음",
          on.get("sent") and on.get("sent") == off.get("sent") and not (tmp / "off").exists(),
          f"on={len(on.get('sent') or [])} off={len(off.get('sent') or [])} {r_off.stderr.strip()[-120:] if not off else ''}")
    lt, r_lt = run("light", True, "light")
    lf = sorted((tmp / "light").glob("rollout-timing-*.json")) if (tmp / "light").is_dir() else []
    lj = json.loads(lf[0].read_text()) if lf else {}
    ls_ = lj.get("summary", {})
    check("rollout 계측 light: 추가 동기화 단계(모델·앙상블·전처리) 없이 tick·관측·엔진·전송·모터만 기록, 값 불변",
          bool(lf) and lj.get("meta", {}).get("timing_mode") == "light"
          and all(ls_.get(k, {}).get("mean", 0) > 0 for k in ("tick", "obs", "obs_motor", "engine", "send", "send_motor_read", "send_motor_write"))
          and not any(k in ls_ for k in ("model", "ensemble", "preprocessor", "postprocessor", "to_tensor"))
          and lt.get("sent") == off.get("sent"),
          f"keys={sorted(k for k in ls_ if isinstance(ls_.get(k), dict))} {r_lt.stderr.strip()[-120:] if not lf else ''}")
    check("rollout 계측: 요약에 실제 주기(Hz)·max_relative_target 제한 비율·CSV 기록",
          "hz_mean" in summ and files and files[0].with_suffix(".csv").is_file() and "[so101-timing]" in r_on.stdout,
          f"hz={summ.get('hz_mean')}")
    fake_r = tmp / "env_probe.py"
    fake_r.write_text("import os, json\nprint('ENV ' + json.dumps({'t': os.environ.get('SO101_ROLLOUT_TIMING'), 'm': os.environ.get('SO101_CAMERA_MIRROR'), "
                      "'mode': os.environ.get('SO101_ROLLOUT_TIMING_MODE')}))\n")
    sh = str(WS / "tools" / "rollout_with_view.sh")
    res = {}
    for flags in (["--no-view", "--timing"], ["--timing", "--no-view"], ["--no-view"], ["--no-mirror", "--timing"], ["--no-view", "--timing=light"]):
        r = subprocess.run([sh, *flags, "--x"], capture_output=True, text=True, timeout=120,
                           env={**os.environ, "SO101_ROLLOUT_BIN": str(fake_r)})
        e = [x for x in r.stdout.splitlines() if x.startswith("ENV ")]
        res[" ".join(flags)] = json.loads(e[-1][4:]) if e else None
    check("rollout_with_view.sh --timing: 순서 무관하게 계측 켜짐(logs/), 없으면 꺼짐, 영상 내보내기 유지 / --no-mirror면 내보내기 끔",
          all(res[k] and res[k]["t"] == str(WS / "logs") for k in ("--no-view --timing", "--timing --no-view"))
          and res["--no-view"] and not res["--no-view"]["t"] and res["--no-view"]["m"]
          and res["--no-mirror --timing"] and not res["--no-mirror --timing"]["m"] and res["--no-mirror --timing"]["t"]
          and res["--no-view --timing"]["mode"] == "detail" and res["--no-view --timing=light"] and res["--no-view --timing=light"]["mode"] == "light",
          json.dumps(res)[:200])
    bad = subprocess.run([sh, "--timing=fast", "--x"], capture_output=True, text=True, timeout=60, env={**os.environ, "SO101_ROLLOUT_BIN": str(fake_r)})
    check("rollout_with_view.sh: 알 수 없는 계측 모드(--timing=fast)는 Python 실행 전에 거부(종료 코드 2)",
          bad.returncode == 2 and "ENV " not in bad.stdout, (bad.stdout + bad.stderr).strip()[-120:])


def _small_act_cfg(device: str = "cpu"):
    from lerobot.configs.types import FeatureType, PolicyFeature
    from lerobot.policies.act.configuration_act import ACTConfig

    return ACTConfig(device=device, n_action_steps=1, temporal_ensemble_coeff=0.01, chunk_size=10, pretrained_backbone_weights=None,
                     dim_model=64, dim_feedforward=128, n_heads=4, n_encoder_layers=1, n_vae_encoder_layers=1,
                     input_features={"observation.state": PolicyFeature(FeatureType.STATE, (6,)),
                                     "observation.images.front": PolicyFeature(FeatureType.VISUAL, (3, 48, 64)),
                                     "observation.images.wrist": PolicyFeature(FeatureType.VISUAL, (3, 48, 64))},
                     output_features={"action": PolicyFeature(FeatureType.ACTION, (6,))})


def coreml_child(ckpt: str, tag: str, device: str) -> None:
    """[macOS] 런처 아래 rollout 순서 재현: 정책 로드(from_pretrained) → 그다음 가짜 서보 로봇 연결 → 12틱(공식 엔진·제한)."""
    import numpy as np
    import torch

    so101 = setup_module()
    motors = std_motors()
    cal = write_calibration(so101, "follower", "vc_follower", motors)
    fake = FakeServoBus(motors)
    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies.factory import make_pre_post_processors
    from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig
    from lerobot.rollout.inference.sync import SyncInferenceEngine
    from lerobot.rollout.robot_wrapper import ThreadSafeRobot
    from lerobot.utils.feature_utils import build_dataset_frame, combine_feature_dicts, hw_to_dataset_features

    out: dict = {"tag": tag}
    try:
        cfg = PreTrainedConfig.from_pretrained(ckpt)
        cfg.device, cfg.n_action_steps, cfg.temporal_ensemble_coeff = device, 1, 0.01
        policy = ACTPolicy.from_pretrained(ckpt, config=cfg).eval()  # Core ML 훅은 여기서 붙거나 거부한다(로봇 연결 전)
    except Exception as e:  # noqa: BLE001
        out.update(error=f"{type(e).__name__}: {e}", writes=len(fake.writes))
        fake.close()
        print("COREML_CHILD " + json.dumps(out, ensure_ascii=False))
        return
    robot = SO101Follower(SO101FollowerConfig(port=fake.slave_path, id="vc_follower", calibration_dir=cal.parent, max_relative_target=3.0))
    obs_ft = dict(robot.observation_features, front=(48, 64, 3), wrist=(48, 64, 3))
    feats = combine_feature_dicts(hw_to_dataset_features(robot.action_features, "action"), hw_to_dataset_features(obs_ft, "observation"))
    keys = list(robot.action_features)
    stats = {"observation.state": {"mean": torch.zeros(6), "std": torch.ones(6) * 30}, "action": {"mean": torch.zeros(6), "std": torch.ones(6) * 30},
             "observation.images.front": {"mean": torch.zeros(3, 1, 1), "std": torch.ones(3, 1, 1)},
             "observation.images.wrist": {"mean": torch.zeros(3, 1, 1), "std": torch.ones(3, 1, 1)}}
    pre, post = make_pre_post_processors(policy_cfg=cfg, dataset_stats=stats)
    eng = SyncInferenceEngine(policy=policy, preprocessor=pre, postprocessor=post, dataset_features=feats, ordered_action_keys=keys,
                              task="t", device=device, robot_type=robot.robot_type)
    robot.connect(calibrate=False)
    rw = ThreadSafeRobot(robot)
    T = sys.modules.get("so101_rollout_timing")
    if T:
        T._state["in_run"] = True
    rng = np.random.default_rng(0)
    sent = []
    try:
        eng.reset()
        for _ in range(12):
            obs = rw.get_observation()
            obs["front"] = rng.integers(0, 255, (48, 64, 3), dtype=np.uint8)
            obs["wrist"] = rng.integers(0, 255, (48, 64, 3), dtype=np.uint8)
            a = eng.get_action(build_dataset_frame(feats, obs, prefix="observation"))
            o = rw.send_action({k: float(a[j]) for j, k in enumerate(keys)})
            sent.append([float(o[k]) for k in keys])
    finally:
        if T:
            T._state["in_run"] = False
            T._write()
        robot.disconnect()
        fake.close()
    out.update(sent=sent, backend=getattr(policy, "_so101_backend_info", {}).get("backend", "torch"),
               ensembler=type(policy.temporal_ensembler).__name__, coeff=policy.config.temporal_ensemble_coeff)
    print("COREML_CHILD " + json.dumps(out, ensure_ascii=False))


def test_macos_act_coreml(so101):
    """ACT Core ML backend: 변환 도구 → 런처 설치 → 같은 가중치 결과 대조, 잘못된 장치·변환본 없음 거부(로봇 연결 전), 래퍼 옵션."""
    import numpy as np
    import torch

    from lerobot.policies.act.modeling_act import ACTPolicy

    tmp = Path(tempfile.mkdtemp(prefix="coreml_", dir=VERIFY_DIR))
    torch.manual_seed(0)
    ckpt = tmp / "ckpt"
    ACTPolicy(_small_act_cfg()).save_pretrained(ckpt)
    py, L = sys.executable, str(so101.LAUNCHER)
    cache = tmp / "cache"
    ex = subprocess.run([py, str(WS / "tools" / "act_coreml_export.py"), "--checkpoint", str(ckpt), "--cache-root", str(cache)],
                        capture_output=True, text=True, timeout=600)
    mans = list(cache.glob("*/manifest.json"))
    man = json.loads(mans[0].read_text()) if mans else {}
    check("Core ML 변환 도구: FP32·GPU 변환본+manifest(키·연산 배치·검증 차이) 생성, 허용치 이내",
          ex.returncode == 0 and "[OK]" in ex.stdout and man.get("precision") == "FLOAT32" and man.get("probe_max_abs_vs_torch_cpu", 1) <= man.get("tol", 0),
          (ex.stdout + ex.stderr).strip()[-200:])
    me = str(Path(__file__).resolve())

    def child(tag, device="cpu", backend=None, cache_root=cache, timing=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith("SO101_ACT") and k not in ("SO101_ROLLOUT_TIMING", "SO101_CAMERA_MIRROR",
                                                                                                "SO101_RECORD_MANUAL", "SO101_COREML_CACHE")}
        if backend:
            env["SO101_ACT_BACKEND"] = backend
            env["SO101_COREML_CACHE"] = str(cache_root)
        if timing:
            env["SO101_ROLLOUT_TIMING"] = str(timing)
        r = subprocess.run([py, L, str(os.getpid()), "--", py, me, "--coreml-child", str(ckpt), tag, device], capture_output=True, text=True,
                           env=env, timeout=600)
        line = [x for x in r.stdout.splitlines() if x.startswith("COREML_CHILD ")]
        return (json.loads(line[-1][13:]) if line else {}), r

    ref, r_ref = child("torch")
    cm, r_cm = child("coreml", backend="coreml", timing=tmp / "timing")
    d = float(np.abs(np.array(cm.get("sent") or [[1e9]]) - np.array(ref.get("sent") or [[0]])).max()) if cm.get("sent") and ref.get("sent") else None
    check("Core ML backend: 런처 설치·시작 검증 통과, 같은 가중치 torch CPU와 보낸 명령 차이 ≤1e-3(관절 단위), 앙상블·계수 그대로",
          cm.get("backend") == "coreml" and d is not None and d <= 1e-3 and cm.get("ensembler") == "ACTTemporalEnsembler"
          and cm.get("coeff") == 0.01 and "[so101-coreml] Core ML backend 켜짐" in r_cm.stdout,
          f"diff={d} {cm.get('error') or ''} {r_cm.stderr.strip()[-160:] if not cm.get('sent') else ''}")
    tj = sorted((tmp / "timing").glob("rollout-timing-*.json"))
    ts = json.loads(tj[0].read_text())["summary"] if tj else {}
    check("Core ML backend + 계측: 계측 훅이 Core ML 추론을 model 단계로 기록", ts.get("model", {}).get("mean", 0) > 0, f"model={ts.get('model')}")
    bad_dev, _ = child("mps", device="mps", backend="coreml")
    check("Core ML backend: --device=cpu가 아니면 정책 로드 단계에서 거부(로봇 연결 전, 모터 쓰기 0)",
          "device=cpu" in str(bad_dev.get("error")) and bad_dev.get("writes") == 0, str(bad_dev)[:200])
    no_cache, _ = child("nocache", backend="coreml", cache_root=tmp / "empty_cache")
    check("Core ML backend: 변환본 없으면 변환 명령을 안내하며 거부(로봇 연결 전)",
          "act_coreml_export.py" in str(no_cache.get("error")) and no_cache.get("writes") == 0, str(no_cache)[:200])
    sh = str(WS / "tools" / "rollout_with_view.sh")
    fake_r = tmp / "env_probe.py"
    fake_r.write_text("import os, sys\nprint('BACKEND', repr(os.environ.get('SO101_ACT_BACKEND')), 'PDEV', '--policy.device=cpu' in sys.argv)\n")
    envr = {**os.environ, "SO101_ROLLOUT_BIN": str(fake_r)}
    ok = subprocess.run([sh, "--no-mirror", "--backend=coreml", "--device=cpu"], capture_output=True, text=True, timeout=60, env=envr)
    mpsdev = subprocess.run([sh, "--no-mirror", "--backend=coreml", "--device=mps"], capture_output=True, text=True, timeout=60, env=envr)
    nodev = subprocess.run([sh, "--no-mirror", "--backend=coreml", "--fps=30"], capture_output=True, text=True, timeout=60, env=envr)
    bogus = subprocess.run([sh, "--no-mirror", "--backend=onnx", "--device=cpu"], capture_output=True, text=True, timeout=60, env=envr)
    dflt = subprocess.run([sh, "--no-mirror", "--device=mps"], capture_output=True, text=True, timeout=60, env=envr)
    check("rollout_with_view.sh --backend: coreml+cpu 전달(--policy.device=cpu 자동 추가), coreml+mps·장치 미지정·알 수 없는 backend는 실행 전 거부, 기본은 공식 경로",
          "BACKEND 'coreml' PDEV True" in ok.stdout and mpsdev.returncode == 2 and nodev.returncode == 2 and bogus.returncode == 2
          and "BACKEND" not in mpsdev.stdout + nodev.stdout + bogus.stdout and "BACKEND '' PDEV False" in dflt.stdout,
          f"ok={ok.stdout.strip()[-40:]} rc={mpsdev.returncode},{nodev.returncode},{bogus.returncode} dflt={dflt.stdout.strip()[-30:]}")


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--fake-child":
        fake_child(sys.argv[2], sys.argv[3])
        return 0
    if len(sys.argv) >= 5 and sys.argv[1] == "--coreml-child":
        coreml_child(sys.argv[2], sys.argv[3], sys.argv[4])
        return 0
    if len(sys.argv) >= 3 and sys.argv[1] == "--timing-child":
        timing_child(sys.argv[2])
        return 0
    if len(sys.argv) >= 2 and sys.argv[1] == "--harness":
        harness(sys.argv[2], sys.argv[3])
        return 0
    import shutil

    if VERIFY_DIR.is_dir():  # 이 도구 전용 임시 폴더만 비운다
        shutil.rmtree(VERIFY_DIR)
    so101 = setup_module()
    print("== probe(읽기 전용)")
    test_probe(so101)
    print("== 독립 cleanup")
    test_cleanup(so101)
    print("== 실행기 신호·입력")
    test_runner()
    print("== dry-run·설정·hardware doctor")
    test_dryrun_and_config(so101)
    print("== teleop 사전 점검 거부")
    test_teleop_refusal(so101)
    n_common = len(RESULTS)
    if IS_MAC:
        print("== [macOS] 런처(부모 사망 감시)")
        test_macos_launcher(so101)
        print("== [macOS] 실행기 추가(폴링 대체·SIGINT 무시 자식·caffeinate)")
        test_macos_runner_extra()
        print("== [macOS] tty/cu·comports·USB 지문")
        test_macos_ports(so101)
        print("== [macOS] 포트 지정 마법사")
        test_macos_wizard(so101)
        print("== [macOS] 녹화 래퍼")
        test_macos_record(so101)
        print("== [macOS] 녹화 스페이스바 진행 모드")
        test_macos_record_hooks(so101)
        print("== [macOS] 실행 중 카메라 보기(미러)")
        test_macos_camera_mirror(so101)
        print("== [macOS] rollout 제어 루프 단계별 계측")
        test_macos_rollout_timing(so101)
        print("== [macOS] ACT Core ML backend")
        test_macos_act_coreml(so101)
    n_fail = sum(1 for r in RESULTS if not r["pass"])
    (VERIFY_DIR / "result.json").write_text(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "results": RESULTS},
                                                       ensure_ascii=False, indent=1))
    common_fail = sum(1 for r in RESULTS[:n_common] if not r["pass"])
    print(f"\n공통(Linux와 같은 시험) PASS {n_common - common_fail} / {n_common}" +
          (f", macOS 전용 PASS {len(RESULTS) - n_common - (n_fail - common_fail)} / {len(RESULTS) - n_common}" if IS_MAC else ""))
    print(f"합계 PASS {len(RESULTS) - n_fail} / {len(RESULTS)}, FAIL {n_fail}, SKIP 0")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
