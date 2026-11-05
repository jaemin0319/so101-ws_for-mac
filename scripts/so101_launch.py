#!/usr/bin/env python3
"""macOS 전용 자식 런처: 부모(래퍼) 비정상 종료 시 공식 CLI가 고아로 계속 구동되지 않게 한다.

Linux는 prctl(PR_SET_PDEATHSIG, SIGINT)로 같은 일을 하지만 macOS에는 이 기능이 없다. 그래서 이 런처가
같은 프로세스 안에서 (1) 부모 PID를 kqueue EVFILT_PROC/NOTE_EXIT로 감시하는 스레드를 띄우고 (2) 공식 console
script(.venv/bin/lerobot-*)를 runpy.run_path(..., run_name="__main__")로 실행한다. exec하지 않으므로 감시 스레드가
살아 있고, 공식 코드는 수정하지 않는다.

사용(scripts/so101.py의 run_official이 호출): python so101_launch.py <부모 PID> -- <프로그램> [인자...]
  <프로그램>이 python 인터프리터이면 다음 인자를 스크립트로 본다(검증 도구의 가짜 자식용).

부모가 죽으면: 자기 자신에게 SIGINT(공식 코드의 KeyboardInterrupt 정리 경로) → SO101_LAUNCH_INT_GRACE초 뒤에도 살아 있으면
SIGTERM → SO101_LAUNCH_TERM_GRACE초 뒤 SIGKILL. 시작 시 부모가 이미 바뀌었으면(경합) 즉시 같은 절차를 시작한다.
kqueue 등록이 실패하면 os.getppid() 0.2초 폴링으로 대체한다(SO101_LAUNCH_FORCE_POLL=1로 강제 가능, 검증용).
SIGHUP은 무시한다(터미널 끊김은 래퍼가 SIGINT로 전달). argv·종료 코드·traceback은 직접 실행과 같다.
SO101_LAUNCH_DEBUG=1이면 감시 방식과 동작을 stderr에 한 줄씩 남긴다.
"""
from __future__ import annotations

import os
import runpy
import select
import signal
import sys
import threading
import time


def _debug(msg: str) -> None:
    if os.environ.get("SO101_LAUNCH_DEBUG") == "1":
        try:
            sys.stderr.write(f"[so101-launch] {msg}\n")
            sys.stderr.flush()
        except OSError:
            pass


def _escalate() -> None:
    """부모 사망 후 자기 종료 절차(SIGINT → SIGTERM → SIGKILL)."""
    int_grace = float(os.environ.get("SO101_LAUNCH_INT_GRACE", "20"))
    term_grace = float(os.environ.get("SO101_LAUNCH_TERM_GRACE", "5"))
    me = os.getpid()
    _debug("parent gone -> SIGINT self")
    os.kill(me, signal.SIGINT)
    time.sleep(int_grace)
    _debug("still alive -> SIGTERM self")
    os.kill(me, signal.SIGTERM)
    time.sleep(term_grace)
    _debug("still alive -> SIGKILL self")
    os.kill(me, signal.SIGKILL)


def _watch_poll(parent: int) -> None:
    while os.getppid() == parent:
        time.sleep(0.2)
    _escalate()


def _watch_kqueue(kq, parent: int) -> None:
    try:
        while True:
            events = kq.control(None, 1, None)
            if any(e.ident == parent and e.fflags & select.KQ_NOTE_EXIT for e in events):
                break
    except OSError:
        _watch_poll(parent)
        return
    _escalate()


def start_parent_watch(parent: int) -> str:
    """감시 스레드를 시작하고 방식을 반환한다: kqueue | poll | already-gone."""
    method = "poll"
    target = _watch_poll
    args: tuple = (parent,)
    if os.environ.get("SO101_LAUNCH_FORCE_POLL") != "1":
        try:
            kq = select.kqueue()
            ev = select.kevent(parent, filter=select.KQ_FILTER_PROC, flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                               fflags=select.KQ_NOTE_EXIT)
            kq.control([ev], 0, 0)
            method, target, args = "kqueue", _watch_kqueue, (kq, parent)
        except (OSError, AttributeError) as e:  # 등록 실패(이미 종료된 PID 포함) → 폴링으로 대체
            _debug(f"kqueue registration failed ({type(e).__name__}: {e}); falling back to polling")
    # 등록 *후* 부모를 다시 확인한다: 그 사이 부모가 죽어 launchd(1)로 재부모화됐으면 PID 재사용과 무관하게 즉시 처리.
    if os.getppid() != parent:
        method = "already-gone"
        target, args = (lambda: _escalate()), ()
    threading.Thread(target=target, args=args, name="so101-parent-watch", daemon=True).start()
    _debug(f"parent watch: {method} (parent={parent}, self={os.getpid()})")
    return method


def main() -> None:
    if len(sys.argv) < 4 or sys.argv[2] != "--":
        sys.exit("usage: so101_launch.py <parent_pid> -- <program> [args...]")
    parent = int(sys.argv[1])
    target = sys.argv[3:]
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    if os.path.basename(target[0]).startswith("python"):
        target = target[1:]
    if not target:
        sys.exit("so101_launch.py: 실행할 스크립트가 없습니다.")
    script = os.path.abspath(target[0])
    start_parent_watch(parent)
    if os.environ.get("SO101_CAMERA_MIRROR"):
        # 카메라 영상 내보내기: 공식 프로세스가 읽은 프레임을 JPEG로 내보내 별도 창에서 본다(scripts/so101_camera_mirror.py).
        # 로봇 모듈이 import되기 전에 설치해야 카메라 이름(front·wrist)이 붙는다 → 녹화 훅보다 먼저.
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import so101_camera_mirror

        so101_camera_mirror.install()
        sys.path.pop(0)
    if os.environ.get("SO101_ACT_BACKEND", "").strip().lower() not in ("", "mps", "torch"):
        backend = os.environ["SO101_ACT_BACKEND"].strip().lower()
        if backend != "coreml":
            sys.exit(f"so101_launch.py: 알 수 없는 ACT backend {backend!r} (mps 또는 coreml)")
        # ACT 추론 Core ML backend(scripts/so101_act_coreml.py). 계측 훅보다 먼저 설치해야 계측이 Core ML 호출도 잰다.
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import so101_act_coreml

        so101_act_coreml.install()
        sys.path.pop(0)
    if os.environ.get("SO101_ROLLOUT_TIMING"):
        # rollout 제어 루프 단계별 시간 계측(scripts/so101_rollout_timing.py). 값은 바꾸지 않고 시간만 잰다.
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import so101_rollout_timing

        so101_rollout_timing.install()
        sys.path.pop(0)
    if os.environ.get("SO101_RECORD_MANUAL") == "1":
        # 녹화 수동 진행(스페이스바) 모드: 공식 lerobot-record의 시작·종료 시점만 감싼다(scripts/so101_record_hooks.py)
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import so101_record_hooks

        so101_record_hooks.install()
        sys.path.pop(0)
    # 스크립트를 직접 실행한 것과 같은 argv·sys.path[0]
    sys.argv = [script, *target[1:]]
    sys.path[0] = os.path.dirname(script)
    runpy.run_path(script, run_name="__main__")


if __name__ == "__main__":
    main()
