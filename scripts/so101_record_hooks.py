#!/usr/bin/env python3
"""녹화 수동 진행(스페이스바) 모드 — 공식 lerobot-record의 시작·종료 시점만 바꾼다.

scripts/so101_launch.py가 환경변수 SO101_RECORD_MANUAL=1일 때, 공식 console script를 실행하기 직전에 install()을 호출한다.
공식 LeRobot 파일은 수정하지 않는다. 같은 프로세스 안에서 공식 함수 두 개만 감싼다.
  - lerobot.utils.keyboard_input.create_key_listener: 스페이스바를 공식 '다음(→)' 조작으로 전달하고 눌림을 기록한다.
    r(다시 녹화)·q(녹화 종료)·n/→/←/Esc 등 공식 키는 그대로 동작한다.
  - lerobot.scripts.lerobot_record.record_loop: 공식 루프를 그대로 호출하되,
      * 세션 첫 에피소드 전에 '준비' 구간(데이터셋 없이 = 저장 없이 리더 추종만)을 스페이스바까지 유지
      * 공식 리셋 구간(데이터셋 없이 호출됨)을 시간 대신 스페이스바까지 유지(r로 끝나도 계속 대기, 재녹화 표시는 유지)
      * 녹화 구간은 공식 그대로(에피소드 길이 상한은 래퍼가 --dataset.episode_time_s로 전달)

흐름: 준비 → [스페이스바] → 녹화 → [스페이스바=저장 / r=버림] → 환경 재설정 → [스페이스바] → 녹화 → …
마지막 에피소드를 스페이스바로 끝내면 공식 코드가 저장·마무리(finalize)하고 종료한다(마지막 뒤에는 공식적으로 리셋 구간이 없다).
"""
from __future__ import annotations

import os
import threading

SPACE = threading.Event()
WAIT_S = float(os.environ.get("SO101_RECORD_WAIT_S", "86400"))  # 준비·재설정 구간 최대 대기(사실상 무기한)
CONTROLS = "스페이스바=시작/종료, r=다시 녹화, q=녹화 종료"
_state = {"ready_done": False, "last_ep": None, "installed": False}


def say(msg: str) -> None:
    print(f"\n[so101] {msg}", flush=True)


def _arg(args: tuple, kw: dict, name: str, pos: int):
    return kw[name] if name in kw else (args[pos] if len(args) > pos else None)


def _wait_for_space(orig, args: tuple, kw: dict, events: dict, phase: str) -> None:
    """공식 record_loop를 데이터셋 없이(저장 없음, 리더 추종은 계속) 반복 호출하며 스페이스바를 기다린다."""
    SPACE.clear()
    kw = {**kw, "dataset": None, "control_time_s": WAIT_S}
    while not events["stop_recording"]:
        orig(*args, **kw)
        if SPACE.is_set() or events["stop_recording"]:
            break
        events["exit_early"] = False  # r 등으로 끝났으면 계속 대기
        if phase == "ready":
            events["rerecord_episode"] = False  # 녹화 전에는 버릴 에피소드가 없다
        elif events.get("rerecord_episode"):
            say("방금 에피소드는 저장하지 않고 다시 녹화합니다. 준비되면 스페이스바")
    SPACE.clear()
    events["exit_early"] = False


def install() -> None:
    if _state["installed"]:
        return
    from lerobot.utils import keyboard_input as K
    import lerobot.scripts.lerobot_record as R

    orig_ckl = K.create_key_listener

    def create_key_listener(dispatch, *, controls_help: str = ""):
        def on_name(name: str) -> None:
            if name == "space":
                SPACE.set()
                dispatch("right")  # 공식 '다음' 조작(현재 구간 종료)
            else:
                dispatch(name)

        return orig_ckl(on_name, controls_help=CONTROLS)

    K.create_key_listener = create_key_listener

    orig_rl = R.record_loop

    def record_loop(*args, **kw):
        events = _arg(args, kw, "events", 1)
        dataset = kw.get("dataset")
        if dataset is None:  # 공식 리셋 구간
            nxt = _state["last_ep"]
            say("■ 환경 재설정: 물체를 다시 놓고 리더를 시작 자세로 옮기세요. 준비되면 스페이스바 → "
                + ("같은 에피소드 다시 녹화" if events.get("rerecord_episode") else f"다음 에피소드 녹화"
                   + (f"(에피소드 {nxt + 1})" if nxt is not None else ""))
                + "  (r=방금 에피소드 버리기, q=종료)")
            _wait_for_space(orig_rl, args, kw, events, "reset")
            return None
        if not _state["ready_done"]:
            say(f"▶ 준비: 물체를 놓고 리더를 시작 자세로 옮기세요. 준비되면 스페이스바 → 녹화 시작(에피소드 {dataset.num_episodes})  (q=종료)")
            _wait_for_space(orig_rl, args, kw, events, "ready")
            _state["ready_done"] = True
            if events["stop_recording"]:
                return None
        _state["last_ep"] = dataset.num_episodes
        SPACE.clear()
        say(f"● 녹화 중: 에피소드 {dataset.num_episodes} — 끝나면 스페이스바, 다시 하려면 r  (q=종료)")
        result = orig_rl(*args, **kw)
        if events["stop_recording"]:
            say("녹화 종료 요청: 저장된 에피소드까지 마무리합니다(진행 중이던 에피소드는 공식 동작에 따라 처리)")
        elif events.get("rerecord_episode"):
            say("r: 이번 에피소드는 저장하지 않습니다")
        elif SPACE.is_set():
            say("스페이스바: 에피소드 종료 → 저장합니다")
        else:
            say("에피소드 최대 길이(안전 상한)에 도달해 종료 → 저장합니다")
        return result

    R.record_loop = record_loop
    _state["installed"] = True
