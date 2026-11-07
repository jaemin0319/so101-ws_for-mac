#!/usr/bin/env python
"""팔 USB 포트를 찾고 follower / leader 를 모터 전압으로 구분한다. scripts/setup_local.sh 가 사용한다.

  python scripts/find_arms.py          # 결과를 사람이 읽기 좋게 출력
  python scripts/find_arms.py --json   # 마지막 줄에 JSON: {"follower": 포트|null, "leader": 포트|null, "ports": {포트: 전압|null}}

읽기 전용이다: 포트를 열고 모터의 Present_Voltage 레지스터만 읽은 뒤, 토크 해제 쓰기 없이 닫는다(모터가 움직이지 않음).
구분 기준: SO-101 follower 는 12V 전원(모터 전압 약 12V), leader 는 5V 전원(약 5~6V). 9V 이상 = follower.
팔 전원이 꺼져 있거나 USB 가 빠져 있으면 전압을 못 읽는다(null).
"""

import argparse
import glob
import json
import platform
import sys

THRESHOLD_V = 9.0


def candidates() -> list[str]:
    if platform.system() == "Darwin":
        return sorted(glob.glob("/dev/cu.usbmodem*"))
    return sorted(glob.glob("/dev/serial/by-id/*"))


def read_voltage(port: str) -> float | None:
    from lerobot.motors import Motor, MotorNormMode, SerialMotorsBus

    motors = {f"id{i}": Motor(i, "sts3215", MotorNormMode.RANGE_M100_100) for i in range(1, 7)}
    bus = SerialMotorsBus(port, motors)
    try:
        bus.connect(handshake=False)  # 포트만 연다(모터 확인·쓰기 없음)
    except Exception:  # noqa: BLE001
        return None
    try:
        for name in motors:  # 모터 하나만 답하면 된다
            try:
                raw = bus.read("Present_Voltage", name, normalize=False, num_retry=1)
                return round(float(raw) / 10.0, 1)  # 단위 0.1V
            except Exception:  # noqa: BLE001
                continue
        return None
    finally:
        bus.disconnect(disable_torque=False)  # 토크 해제(쓰기) 없이 포트만 닫는다


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    ports = {p: read_voltage(p) for p in candidates()}
    hi = [p for p, v in ports.items() if v is not None and v >= THRESHOLD_V]
    lo = [p for p, v in ports.items() if v is not None and v < THRESHOLD_V]
    result = {"follower": hi[0] if len(hi) == 1 else None, "leader": lo[0] if len(lo) == 1 else None, "ports": ports}

    if not ports:
        print("팔 USB 포트가 없다(연결 확인). macOS: ls /dev/cu.usbmodem*", file=sys.stderr)
    for p, v in ports.items():
        role = "follower" if p == result["follower"] else ("leader" if p == result["leader"] else "?")
        print(f"  {p}  전압 {'읽기 실패(전원·케이블 확인)' if v is None else f'{v} V'}  → {role}", file=sys.stderr)
    if len(hi) > 1 or len(lo) > 1:
        print("  전압이 비슷한 팔이 둘 이상이라 구분할 수 없다 → lerobot-find-port 로 하나씩 확인", file=sys.stderr)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
