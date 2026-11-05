# 01_setup — 설치와 초기 세팅

순서와 성공 기준·실패 시 조치는 [docs/SETUP.md](../docs/SETUP.md)를 따른다. 각 스크립트는 `--help`를 지원한다.

| 스크립트 | 역할 |
|---|---|
| install.sh | 설치(재실행·복구 `--repair`·`--reset-venv`) |
| doctor.sh | 비구동 점검(`--hardware`: 포트·지문·보정 파일, 포트를 열지 않음) |
| ports.sh | USB 포트 지정 마법사(포트 설정까지만 자동화) |
| probe.sh | 모터 읽기 전용 확인 |
| motors.sh | 공식 모터 ID·baud 설정(필요한 팔만, 사람이 직접) |
| calibrate.sh | 공식 보정(사람이 직접) |
