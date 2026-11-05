#!/usr/bin/env python3
"""SO-101 로컬 데이터셋(공식 LeRobotDataset v3) 지원 — 설정 로드·공식 lerobot-record 인자 생성·doctor 점검·검사(inspect).

녹화 루프·카메라 캡처·영상 인코딩·데이터 포맷은 공식 LeRobot(lerobot-record, LeRobotDataset)을 그대로 쓴다.
이 모듈은 scripts/so101.py가 import해서 쓰며(직접 실행 시 inspect만 제공), so101.py를 import하지 않는다.

  .venv/bin/python scripts/so101_dataset.py inspect <데이터셋 폴더> [--json out.json] [--no-decode]
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

WS = Path(os.environ.get("SO101_WS") or Path(__file__).resolve().parent.parent)
VENV_BIN = WS / ".venv" / "bin"
CAMERAS_EXAMPLE = WS / "configs" / "cameras.example.yaml"
CAMERAS_LOCAL = WS / "configs" / "cameras.local.yaml"
RECORDING_EXAMPLE = WS / "configs" / "recording.example.yaml"
RECORDING_LOCAL = WS / "configs" / "recording.local.yaml"
DATASETS_DIR = WS / "datasets"

OK, WARN, FAIL, INFO = "OK", "WARN", "FAIL", "INFO"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
CAM_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
# 공식 RGBEncoderConfig가 받는 코덱(lerobot/configs/video.py VALID_VIDEO_CODECS + 별칭 av1)
VCODECS = ("libsvtav1", "h264", "hevc", "libaom-av1", "auto", "av1", "h264_videotoolbox", "hevc_videotoolbox")
REPO_PREFIX = "local"  # 공식 repo_id = local/<name>. Hub 업로드는 하지 않는다(push_to_hub=false 고정).


# ============================================================================================
# 설정
# ============================================================================================
def _yaml_load(path: Path) -> tuple[Any, str | None]:
    import yaml

    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")), None
    except (OSError, yaml.YAMLError) as e:
        return None, f"{path}: 읽기/파싱 실패: {e}"


def _pos_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def _pos_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v)) and float(v) > 0


def load_cameras(path: Path) -> tuple[dict[str, dict], list[str]]:
    """configs/cameras*.yaml → {이름: 공식 OpenCVCameraConfig 필드}. 장치를 열지 않는다."""
    if not path.is_file():
        return {}, [f"카메라 설정 파일이 없습니다: {path}  →  cp configs/cameras.example.yaml configs/cameras.local.yaml 후 ./03_dataset/cameras.sh로 index를 확인하세요."]
    raw, err = _yaml_load(path)
    if err:
        return {}, [err]
    raw = raw or {}
    errors: list[str] = []
    if not isinstance(raw, dict) or set(raw) - {"cameras"}:
        return {}, ["카메라 설정 최상위는 'cameras:' 하나여야 합니다."]
    cams = raw.get("cameras") or {}
    if not isinstance(cams, dict):
        return {}, ["'cameras'는 이름 → 설정 mapping이어야 합니다."]
    out: dict[str, dict] = {}
    allowed = {"type", "index_or_path", "width", "height", "fps", "fourcc", "color_mode", "rotation", "warmup_s", "backend"}
    for name, c in cams.items():
        if not isinstance(name, str) or not CAM_NAME_RE.match(name):
            errors.append(f"카메라 이름 {name!r}: 소문자로 시작하는 영문 소문자/숫자/_ (데이터셋 키 observation.images.<이름>)")
            continue
        if not isinstance(c, dict):
            errors.append(f"cameras.{name}: mapping이어야 합니다.")
            continue
        for k in c:
            if k not in allowed:
                errors.append(f"cameras.{name}.{k}: 지원하지 않는 키")
        if c.get("type", "opencv") != "opencv":
            errors.append(f"cameras.{name}.type: 이 래퍼는 opencv(UVC/AVFoundation)만 지원합니다.")
        idx = c.get("index_or_path")
        if idx is None:
            errors.append(f"cameras.{name}.index_or_path 미지정 → ./03_dataset/cameras.sh로 이 세션의 index를 확인해 적으세요.")
        elif not ((isinstance(idx, int) and not isinstance(idx, bool) and idx >= 0) or (isinstance(idx, str) and os.path.isabs(idx))):
            errors.append(f"cameras.{name}.index_or_path: 0 이상의 정수 index(또는 절대경로)여야 합니다(현재 {idx!r}).")
        for k in ("width", "height", "fps"):
            v = c.get(k)
            if v is None or not _pos_int(v):
                errors.append(f"cameras.{name}.{k}: 양의 정수여야 합니다(현재 {v!r}). 녹화 데이터 형식을 고정하기 위해 생략하지 않습니다.")
        fourcc = c.get("fourcc")
        if fourcc is not None and (not isinstance(fourcc, str) or len(fourcc) != 4):
            errors.append(f"cameras.{name}.fourcc: 4글자(예: MJPG) 또는 null")
        out[name] = {"type": "opencv", **{k: v for k, v in c.items() if k != "type" and v is not None}}
    return out, errors


@dataclass
class RecCfg:
    name: str | None
    task: str | None
    fps: int
    episode_time_s: float
    reset_time_s: float
    num_episodes: int
    datasets_dir: Path
    video: bool
    vcodec: str
    path: Path
    manual_advance: bool = False  # True: 스페이스바로 시작·종료(scripts/so101_record_hooks.py), 에피소드 길이는 max_episode_time_s가 상한
    max_episode_time_s: float = 120.0

    @property
    def effective_episode_time_s(self) -> float:
        """공식 --dataset.episode_time_s로 넘기는 값(수동 모드는 안전 상한)."""
        return self.max_episode_time_s if self.manual_advance else self.episode_time_s

    @property
    def root(self) -> Path | None:
        return (self.datasets_dir / self.name) if self.name else None

    @property
    def repo_id(self) -> str | None:
        return f"{REPO_PREFIX}/{self.name}" if self.name else None


def load_recording(path: Path, overrides: dict[str, Any] | None = None) -> tuple[RecCfg | None, list[str]]:
    """configs/recording*.yaml(+명령행 덮어쓰기) → RecCfg. 경로 존재·쓰기 가능 여부는 여기서 보지 않는다."""
    if not path.is_file():
        return None, [f"녹화 설정 파일이 없습니다: {path}  →  cp configs/recording.example.yaml configs/recording.local.yaml 후 값을 채우세요."]
    raw, err = _yaml_load(path)
    if err:
        return None, [err]
    raw = raw or {}
    if not isinstance(raw, dict) or set(raw) - {"dataset"} or not isinstance(raw.get("dataset", {}), dict):
        return None, ["녹화 설정 최상위는 'dataset:' mapping 하나여야 합니다."]
    d = dict(raw.get("dataset") or {})
    for k, v in (overrides or {}).items():
        if v is not None:
            d[k] = v
    allowed = {"name", "task", "fps", "episode_time_s", "reset_time_s", "num_episodes", "datasets_dir", "video", "vcodec",
               "manual_advance", "max_episode_time_s"}
    errors = [f"dataset.{k}: 지원하지 않는 키" for k in d if k not in allowed]
    name = d.get("name")
    if name is not None and (not isinstance(name, str) or not NAME_RE.match(name)):
        errors.append(f"dataset.name: 영문/숫자로 시작하는 영문/숫자/_.- (현재 {name!r})")
        name = None
    if isinstance(name, str) and name.startswith("eval_"):
        errors.append("dataset.name: 'eval_'로 시작하는 이름은 공식 lerobot-record가 정책 평가용으로 예약했습니다.")
    task = d.get("task")
    if task is not None and (not isinstance(task, str) or not task.strip()):
        errors.append("dataset.task: 비어 있지 않은 작업 설명 문자열이어야 합니다.")
        task = None
    fps = d.get("fps", 30)
    if not _pos_int(fps):
        errors.append(f"dataset.fps: 양의 정수(현재 {fps!r})")
        fps = 30
    vals: dict[str, float] = {}
    for k, dflt in (("episode_time_s", 20), ("reset_time_s", 10)):
        v = d.get(k, dflt)
        if k == "reset_time_s" and isinstance(v, (int, float)) and not isinstance(v, bool) and v == 0:
            vals[k] = 0.0
        elif not _pos_num(v):
            errors.append(f"dataset.{k}: 양수(초)여야 합니다(현재 {v!r})" + (" 0은 reset_time_s만 허용" if k == "episode_time_s" else ""))
            vals[k] = float(dflt)
        else:
            vals[k] = float(v)
    n = d.get("num_episodes", 2)
    if not _pos_int(n):
        errors.append(f"dataset.num_episodes: 양의 정수(현재 {n!r})")
        n = 1
    ddir = d.get("datasets_dir")
    if ddir is None:
        datasets_dir = DATASETS_DIR
    elif isinstance(ddir, str) and ddir.strip():
        datasets_dir = Path(os.path.expanduser(ddir))
        if not datasets_dir.is_absolute():
            datasets_dir = WS / datasets_dir
    else:
        errors.append("dataset.datasets_dir: null 또는 경로 문자열")
        datasets_dir = DATASETS_DIR
    video = d.get("video", True)
    if not isinstance(video, bool):
        errors.append("dataset.video: true/false")
        video = True
    manual = d.get("manual_advance", False)
    if not isinstance(manual, bool):
        errors.append("dataset.manual_advance: true/false")
        manual = False
    max_ep = d.get("max_episode_time_s", 120)
    if not _pos_num(max_ep):
        errors.append(f"dataset.max_episode_time_s: 양수(초)여야 합니다(현재 {max_ep!r})")
        max_ep = 120
    vcodec = d.get("vcodec", "libsvtav1")
    if vcodec not in VCODECS:
        errors.append(f"dataset.vcodec: {VCODECS} 중 하나(현재 {vcodec!r})")
        vcodec = "libsvtav1"
    return RecCfg(name, task.strip() if isinstance(task, str) else None, fps, vals["episode_time_s"], vals["reset_time_s"],
                  n, datasets_dir.resolve() if datasets_dir.exists() else datasets_dir, video, vcodec, path,
                  manual, float(max_ep)), errors


def _num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else repr(float(v))


def build_record_argv(robot_argv: list[str], cams: dict[str, dict], rec: RecCfg, *, resume: bool) -> list[str]:
    """공식 lerobot-record 인자. robot_argv는 so101.py가 만든 --robot.*/--teleop.* 인자(teleop과 같은 값).
    push_to_hub=false·no_stamp=true·video_encoding_batch_size=1·play_sounds=false·display_data=false는 고정이다."""
    argv = [str(VENV_BIN / "lerobot-record"), *robot_argv]
    if cams:
        argv.append("--robot.cameras=" + json.dumps(cams, separators=(",", ":")))
    argv += [
        f"--dataset.repo_id={rec.repo_id}",
        f"--dataset.root={rec.root}",
        f"--dataset.single_task={rec.task}",
        f"--dataset.fps={rec.fps}",
        f"--dataset.episode_time_s={_num(rec.effective_episode_time_s)}",
        f"--dataset.reset_time_s={_num(rec.reset_time_s)}",
        f"--dataset.num_episodes={rec.num_episodes}",
        f"--dataset.video={'true' if rec.video else 'false'}",
        f"--dataset.rgb_encoder.vcodec={rec.vcodec}",
        "--dataset.push_to_hub=false",
        "--dataset.no_stamp=true",
        "--dataset.video_encoding_batch_size=1",
        "--display_data=false",
        "--play_sounds=false",
        f"--resume={'true' if resume else 'false'}",
    ]
    return argv


def parse_record_argv(argv: list[str]) -> tuple[bool, str, Any]:
    """공식 RecordConfig를 draccus로 파싱만 한다(로봇·카메라 객체 생성·장치 접근 없음)."""
    import draccus

    from lerobot.scripts.lerobot_record import RecordConfig

    try:
        c = draccus.parse(config_class=RecordConfig, args=argv[1:])
    except BaseException as e:  # draccus는 SystemExit을 낼 수 있다
        return False, f"{type(e).__name__}: {e}", None
    problems = []
    if c.dataset.push_to_hub:
        problems.append("push_to_hub가 true로 파싱됨")
    if c.dataset.video_encoding_batch_size != 1:
        problems.append("video_encoding_batch_size != 1")
    if problems:
        return False, "; ".join(problems), c
    cams = {k: (getattr(v, "index_or_path", None), v.width, v.height, v.fps) for k, v in (c.robot.cameras or {}).items()}
    return True, (f"repo_id={c.dataset.repo_id}, root={c.dataset.root}, fps={c.dataset.fps}, episodes={c.dataset.num_episodes}, "
                  f"vcodec={c.dataset.rgb_encoder.vcodec}, push_to_hub={c.dataset.push_to_hub}, resume={c.resume}, cameras={cams}"), c


def expected_features(cams: dict[str, dict], video: bool) -> dict[str, dict]:
    """공식 SO101Follower 객체(연결 없음)와 hw_to_dataset_features로 lerobot-record가 만들 특징 정의를 계산한다.
    카메라 객체는 생성만 되고 열리지 않는다. 보정 폴더는 .tmp 아래 임시 폴더를 쓴다."""
    from lerobot.cameras.opencv import OpenCVCameraConfig
    from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig
    from lerobot.utils.constants import ACTION, OBS_STR
    from lerobot.utils.feature_utils import hw_to_dataset_features

    cam_cfgs = {k: OpenCVCameraConfig(**{kk: vv for kk, vv in v.items() if kk != "type"}) for k, v in cams.items()}
    robot = SO101Follower(SO101FollowerConfig(port="/dev/so101-features-nonexistent", id="so101-features-check",
                                              calibration_dir=WS / ".tmp" / "features_calibration", cameras=cam_cfgs))
    try:
        feats = {**hw_to_dataset_features(robot.action_features, ACTION, video),
                 **hw_to_dataset_features(robot.observation_features, OBS_STR, video)}
    finally:
        assert not robot.is_connected
        del robot
    return feats


def resume_compat(root: Path, rec: RecCfg, expected: dict[str, dict]) -> list[str]:
    """기존 데이터셋(meta/info.json)과 이번 설정의 호환성(공식 resume 전 사전 확인). 문제 목록."""
    info_p = root / "meta" / "info.json"
    if not info_p.is_file():
        return [f"{info_p}가 없습니다. 공식 LeRobotDataset 폴더가 아니거나 녹화가 끝나지 않았습니다."]
    info = json.loads(info_p.read_text())
    probs = []
    if info.get("fps") != rec.fps:
        probs.append(f"fps: 기존 {info.get('fps')} ≠ 설정 {rec.fps}")
    if info.get("robot_type") not in (None, "so_follower"):
        probs.append(f"robot_type: 기존 {info.get('robot_type')} ≠ so_follower")
    feats = info.get("features", {})
    for k, v in expected.items():
        if k not in feats:
            probs.append(f"특징 {k}: 기존 데이터셋에 없음")
            continue
        if list(feats[k].get("shape", [])) != list(v.get("shape", [])):
            probs.append(f"{k} shape: 기존 {feats[k].get('shape')} ≠ 설정 {v.get('shape')}")
        if v.get("names") and feats[k].get("names") != v.get("names"):
            probs.append(f"{k} names: 기존 {feats[k].get('names')} ≠ 설정 {v.get('names')}")
        if feats[k].get("dtype") != v.get("dtype"):
            probs.append(f"{k} dtype: 기존 {feats[k].get('dtype')} ≠ 설정 {v.get('dtype')}")
    std = {"timestamp", "frame_index", "episode_index", "index", "task_index"}
    extra = [k for k in feats if k not in expected and k not in std]
    if extra:
        probs.append(f"기존 데이터셋에만 있는 특징(카메라 등): {extra}")
    return probs


def estimate_bytes(cams: dict[str, dict], rec: RecCfg) -> int:
    """보수적 용량 추정: 녹화 중 임시 PNG(원시 RGB의 약 60%) + 인코딩 후 영상(작음) + 표 데이터.
    공식 비스트리밍 모드는 에피소드마다 PNG를 쓴 뒤 인코딩하고 지운다(에피소드 1개 분량이 최대)."""
    frames_ep = int(rec.fps * rec.effective_episode_time_s)
    png_ep = sum(int(c["width"] * c["height"] * 3 * 0.6) for c in cams.values()) * frames_ep
    video_total = sum(int(c["width"] * c["height"] * 0.05) for c in cams.values()) * frames_ep * rec.num_episodes
    table = 200 * frames_ep * rec.num_episodes
    return png_ep + video_total + table


def camera_probe(cam: dict, *, seconds: float = 1.0, save_dir: Path | None = None) -> dict[str, Any]:
    """공식 OpenCVCamera로 카메라 하나를 열어(connect가 해상도·FPS를 검증) seconds 동안 읽고 닫는다.
    실제 측정 FPS·프레임 형태·확인용 사진 경로를 반환한다. 모터와 무관하다(녹화 사전 점검·cameras --test)."""
    from lerobot.cameras.opencv import OpenCVCamera, OpenCVCameraConfig

    res: dict[str, Any] = {}
    cam_obj = None
    try:
        cam_obj = OpenCVCamera(OpenCVCameraConfig(**{k: v for k, v in cam.items() if k != "type"}))
        cam_obj.connect()
        t0, n, frame = time.perf_counter(), 0, None
        while time.perf_counter() - t0 < seconds or n == 0:
            frame = cam_obj.read()
            n += 1
        el = time.perf_counter() - t0
        res.update(frames=n, elapsed_s=round(el, 3), measured_fps=n / el if el > 0 else 0.0, shape=list(frame.shape))
        if save_dir is not None:
            import cv2

            save_dir.mkdir(parents=True, exist_ok=True)
            snap = save_dir / f"snapshot_{int(time.time())}.png"
            cv2.imwrite(str(snap), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
            res["snapshot"] = str(snap)
    except Exception as e:  # noqa: BLE001
        res["error"] = f"{type(e).__name__}: {str(e)[:300]}"
    finally:
        if cam_obj is not None:
            try:
                if cam_obj.is_connected:
                    cam_obj.disconnect()
            except Exception:  # noqa: BLE001
                pass
    return res


# ============================================================================================
# doctor(데이터셋 소프트웨어) — 장치를 열지 않음
# ============================================================================================
def doctor_dataset(rep) -> None:
    from importlib import metadata

    def ver(n: str) -> str | None:
        try:
            return metadata.version(n)
        except metadata.PackageNotFoundError:
            return None

    pk = {n: ver(n) for n in ("av", "datasets", "pandas", "pyarrow", "jsonlines", "torchcodec", "opencv-python-headless")}
    need = [n for n in ("av", "datasets", "pandas", "pyarrow", "jsonlines", "opencv-python-headless") if not pk[n]]
    rep.add(FAIL if need else OK, "데이터셋 의존성(lerobot[dataset]) " + ", ".join(f"{k} {v}" for k, v in pk.items() if v),
            f"없음: {need}" if need else "")
    import importlib
    import logging

    failed = []
    for m in ("lerobot.scripts.lerobot_record", "lerobot.datasets.lerobot_dataset", "lerobot.cameras.opencv",
              "lerobot.scripts.lerobot_find_cameras", "av", "cv2"):
        try:
            importlib.import_module(m)
        except Exception as e:  # noqa: BLE001
            failed.append(f"{m}: {type(e).__name__}: {e}")
    rep.add(OK if not failed else FAIL, f"녹화·데이터셋 모듈 import {6 - len(failed)}/6", "; ".join(failed))
    # opencv-python-headless와 av 휠이 같은 이름의 libavdevice를 각각 포함한다 → 둘 다 로드하면 macOS objc가
    # "Class AVFFrameReceiver is implemented in both ..." 경고를 낸다(공식 lerobot-record도 둘 다 import).
    site = Path(av.__file__).parent.parent if (av := sys.modules.get("av")) else None
    if site is not None:
        dup = sorted({p.name for p in (site / "cv2" / ".dylibs").glob("libavdevice*.dylib")}
                     & {p.name for p in (site / "av" / ".dylibs").glob("libavdevice*.dylib")})
        if dup:
            rep.add(WARN, f"cv2와 av가 같은 FFmpeg 장치 라이브러리를 각각 포함({', '.join(dup)}): objc 중복 클래스 경고",
                    "원인: 공식 의존성 휠 두 개가 FFmpeg를 각각 번들. 영향: LeRobot은 카메라를 OpenCV(AVFoundation)로 열고 PyAV는 인코딩에만 써서 "
                    "중복 클래스(AVFFrameReceiver)를 쓰는 경로가 아니지만, 실제 카메라 녹화로는 아직 확인 전. 조치: 실카메라 시험·녹화에서 "
                    "충돌·프레임 오류가 없는지 확인(docs/DATASET.md). 의존성을 임의로 교체하지 않음.")
    # 기본 디코더 선택(공식 get_safe_default_video_backend). torchcodec은 별도 FFmpeg가 없으면 로드되지 않고 pyav로 대체된다.
    from lerobot.utils import import_utils

    lg = logging.getLogger(import_utils.__name__)
    old = lg.level
    lg.setLevel(logging.CRITICAL)
    try:
        backend = import_utils.get_safe_default_video_backend()
    finally:
        lg.setLevel(old)
    if backend == "pyav":
        rep.add(INFO, "영상 디코더: pyav(공식 대체 경로)",
                "torchcodec은 설치되어 있지만 외부 FFmpeg 라이브러리가 없어 로드되지 않습니다. 공식 코드가 pyav로 대체합니다. "
                "녹화 중 이 경고(긴 traceback)가 한 번 출력될 수 있습니다. 검사(inspect)는 pyav를 명시합니다.")
    else:
        rep.add(OK, f"영상 디코더: {backend}")
    import av

    enc = {}
    for c in ("libsvtav1", "h264", "hevc", "h264_videotoolbox", "hevc_videotoolbox", "libaom-av1"):
        try:
            av.codec.Codec(c, "w")
            enc[c] = True
        except Exception:  # noqa: BLE001
            enc[c] = False
    want = "libsvtav1"
    if RECORDING_LOCAL.is_file():
        rc, _ = load_recording(RECORDING_LOCAL)
        if rc:
            want = {"av1": "libsvtav1"}.get(rc.vcodec, rc.vcodec)
    ok = enc.get(want, want == "auto")
    rep.add(OK if ok else FAIL, f"PyAV {av.__version__} 인코더: 설정 코덱 {want} {'사용 가능' if ok else '없음'}",
            "사용 가능: " + ", ".join(k for k, v in enc.items() if v))
    for cli in ("lerobot-record", "lerobot-find-cameras"):
        exe = VENV_BIN / cli
        if not exe.is_file():
            rep.add(FAIL, f"공식 CLI 없음: {cli}")
            continue
        r = subprocess.run([str(exe), "--help"], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=180)
        ok = r.returncode == 0 and ("dataset" in r.stdout or "camera" in r.stdout.lower())
        rep.add(OK if ok else FAIL, f"{cli} --help (exit {r.returncode})", "" if ok else (r.stderr or r.stdout)[-400:])
    rep.add(INFO, "Hub 업로드 비활성", "래퍼가 --dataset.push_to_hub=false를 고정하고 HF_HUB_OFFLINE=1로 실행합니다(로그인·토큰 불필요).")


# ============================================================================================
# inspect — 공식 LeRobotDataset으로 다시 열어 검사(모터·카메라를 열지 않음)
# ============================================================================================
class Findings:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, str]] = []

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


def _expected_motor_names() -> list[str]:
    """공식 SO101Follower의 action 특징 이름(관절 순서·단위 표기 '.pos')."""
    from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

    r = SO101Follower(SO101FollowerConfig(port="/dev/so101-inspect-nonexistent", id="so101-inspect-check",
                                          calibration_dir=WS / ".tmp" / "inspect_calibration"))
    names = list(r.action_features)
    del r
    return names


def _count_video_frames(path: Path, t0: float, t1: float, fps: float) -> tuple[int, list[float]]:
    """PyAV로 MP4를 디코드해 [t0, t1) 구간(반 프레임 여유)의 프레임 수와 pts(초)를 센다."""
    import av

    half = 0.5 / fps
    pts: list[float] = []
    with av.open(str(path)) as c:
        st = c.streams.video[0]
        for fr in c.decode(st):
            if fr.pts is None:
                continue
            t = float(fr.pts * fr.time_base)
            if t0 - half <= t < t1 - half:
                pts.append(t)
    return len(pts), pts


def episode_count(root: Path) -> int:
    """meta/info.json의 total_episodes(없으면 0). 녹화 전후 비교로 이번에 저장된 에피소드를 찾는 데 쓴다."""
    p = Path(root) / "meta" / "info.json"
    try:
        return int(json.loads(p.read_text()).get("total_episodes", 0))
    except (OSError, ValueError):
        return 0


def parse_episode_spec(spec: str) -> set[int]:
    """'50-59', '3,5,7', '0-2,10' 형식 → 에피소드 번호 집합."""
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = (int(x) for x in part.split("-", 1))
            if b < a:
                raise ValueError(f"범위가 거꾸로입니다: {part}")
            out.update(range(a, b + 1))
        else:
            out.add(int(part))
    return out


def inspect_dataset(root: Path, *, decode: bool = True, sample: int = 3, episodes: set[int] | None = None) -> dict[str, Any]:
    """공식 LeRobotDataset(video_backend=pyav)으로 열어 형식·에피소드·프레임·timestamp·영상·NaN·task를 검사한다.
    episodes를 주면 에피소드별 검사(행·timestamp·NaN·영상 디코드)와 공식 샘플 읽기를 그 에피소드만 한다.
    데이터셋 수준 검사(열기·파일 존재·특징·전체 행 수·task·stats)는 항상 전체에 대해 한다."""
    import numpy as np

    f = Findings()
    root = root.resolve()
    out: dict[str, Any] = {"root": str(root), "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                           "checked_episodes": "all" if episodes is None else sorted(episodes)}
    print(f"== 데이터셋 검사: {root}")
    info_p = root / "meta" / "info.json"
    if not info_p.is_file():
        f.add(FAIL, "meta/info.json 없음", "공식 LeRobotDataset 폴더(meta/·data/·videos/)를 지정하세요.")
        return {**out, "fail": f.n_fail, "warn": f.n_warn, "items": f.items}
    info = json.loads(info_p.read_text())
    out["info"] = {k: info.get(k) for k in ("codebase_version", "robot_type", "fps", "total_episodes", "total_frames", "total_tasks")}
    f.add(INFO, "info.json", json.dumps(out["info"], ensure_ascii=False))
    if not str(info.get("codebase_version", "")).startswith("v3"):
        f.add(WARN, f"codebase_version {info.get('codebase_version')} (이 검사는 v3 기준)")

    from lerobot.datasets.dataset_metadata import LeRobotDatasetMetadata
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    repo_id = f"{REPO_PREFIX}/{root.name}"
    # 메타데이터가 가리키는 data/·videos/ 파일이 실제로 있는지 먼저 확인한다(없으면 공식 로더가 Hub에서 받으려다
    # 오프라인 오류로 끝나 원인이 가려진다).
    try:
        m0 = LeRobotDatasetMetadata(repo_id, root=root)
        missing = set()
        for i in range(len(m0.episodes)):
            e_idx = int(m0.episodes[i]["episode_index"])
            rels = [m0.get_data_file_path(e_idx)] + [m0.get_video_file_path(e_idx, vk) for vk in m0.video_keys]
            missing.update(str(r) for r in rels if not (root / r).is_file())
        if missing:
            f.add(FAIL, f"메타데이터가 가리키는 파일 {len(missing)}개 없음", ", ".join(sorted(missing))[:300])
            return {**out, "fail": f.n_fail, "warn": f.n_warn, "items": f.items}
        f.add(OK, "메타데이터가 가리키는 data/·videos/ 파일 모두 있음")
    except Exception as e:  # noqa: BLE001
        f.add(FAIL, "공식 LeRobotDatasetMetadata로 메타데이터 읽기 실패", f"{type(e).__name__}: {str(e)[:300]}")
        return {**out, "fail": f.n_fail, "warn": f.n_warn, "items": f.items}
    try:
        ds = LeRobotDataset(repo_id, root=root, video_backend="pyav")
    except Exception as e:  # noqa: BLE001
        hint = ""
        if "Offline" in type(e).__name__ or "offline" in str(e):
            hint = ("  → 데이터셋 파일(data/·videos/·meta/) 일부가 없습니다. 공식 코드가 없는 파일을 Hub에서 받으려다 오프라인 설정으로 "
                    "중단했습니다. 복사가 덜 됐는지 확인하세요(<이름>.sha256으로 검증).")
        f.add(FAIL, "공식 LeRobotDataset으로 열기 실패", f"{type(e).__name__}: {str(e)[:300]}{hint}")
        return {**out, "fail": f.n_fail, "warn": f.n_warn, "items": f.items}
    meta = ds.meta
    fps = float(meta.fps)
    f.add(OK, f"공식 LeRobotDataset으로 열림: 에피소드 {meta.total_episodes}, 프레임 {meta.total_frames}, fps {meta.fps}")

    # 1) 특징·관절 이름·순서·형태
    feats = meta.features
    want_names = _expected_motor_names()
    for key in ("observation.state", "action"):
        ft = feats.get(key)
        if not ft:
            f.add(FAIL, f"특징 {key} 없음")
            continue
        names = ft.get("names")
        ok = list(ft.get("shape", [])) == [len(want_names)] and names == want_names and ft.get("dtype") == "float32"
        f.add(OK if ok else FAIL, f"{key}: shape {ft.get('shape')}, dtype {ft.get('dtype')}, 이름 {'공식 SO101 순서와 일치' if names == want_names else '불일치'}",
              "" if ok else f"기대 이름 {want_names}, 실제 {names}")
    vkeys = list(meta.video_keys)
    out["video_keys"] = vkeys
    for vk in vkeys:
        ft = feats[vk]
        f.add(INFO, f"영상 {vk}: shape {ft.get('shape')} codec {ft.get('info', {}).get('video.codec')} "
                    f"pix_fmt {ft.get('info', {}).get('video.pix_fmt')} fps {ft.get('info', {}).get('video.fps')}")
    if not vkeys:
        f.add(WARN, "영상 특징 없음(카메라 없이 녹화된 데이터셋)")

    # 2) 표 데이터: 에피소드별 frame_index·timestamp·index, NaN·누락
    hf = ds.hf_dataset
    cols = hf.column_names
    for c in ("timestamp", "frame_index", "episode_index", "index", "task_index", "observation.state", "action"):
        if c not in cols:
            f.add(FAIL, f"데이터 열 {c} 없음")
    tbl = hf.with_format(None).to_pandas() if hasattr(hf, "to_pandas") else None
    ep_meta = meta.episodes
    n_eps = len(ep_meta)
    if n_eps != meta.total_episodes:
        f.add(FAIL, f"episodes 메타 행 수 {n_eps} ≠ info.total_episodes {meta.total_episodes}")
    if tbl is not None and len(tbl) != meta.total_frames:
        f.add(FAIL, f"데이터 행 수 {len(tbl)} ≠ info.total_frames {meta.total_frames}")
    tol = max(float(getattr(ds, "tolerance_s", 1e-4)), 1e-4)
    if episodes is not None:
        all_idx = {int(ep_meta[i]["episode_index"]) for i in range(n_eps)}
        unknown = sorted(set(episodes) - all_idx)
        if unknown:
            f.add(FAIL, f"검사하려는 에피소드가 데이터셋에 없음: {unknown[:10]}")
        sel = sorted(set(episodes) & all_idx)
        f.add(INFO, f"에피소드별 검사 범위: {len(sel)}개" + (f"(에피소드 {sel[0]}~{sel[-1]})" if sel else "(없음)"),
              f"나머지 {n_eps - len(sel)}개는 데이터셋 수준 검사만(열기·파일 존재·전체 행 수·task)")
    ep_results = []
    for i in range(n_eps):
        ep = ep_meta[i]
        e_idx = int(ep["episode_index"])
        if episodes is not None and e_idx not in episodes:
            continue
        length = int(ep["length"])
        r: dict[str, Any] = {"episode_index": e_idx, "length": length}
        rows = tbl[tbl["episode_index"] == e_idx] if tbl is not None else None
        bad = []
        if rows is not None:
            if len(rows) != length:
                bad.append(f"행 {len(rows)} ≠ length {length}")
            if int(ep["dataset_to_index"]) - int(ep["dataset_from_index"]) != length:
                bad.append("dataset_from/to_index 범위 ≠ length")
            if list(rows["index"]) != list(range(int(ep["dataset_from_index"]), int(ep["dataset_to_index"]))):
                bad.append("전역 index가 연속이 아니거나 offset 불일치")
            fi = rows["frame_index"].to_numpy()
            if list(fi) != list(range(len(fi))):
                bad.append("frame_index가 0부터 연속이 아님")
            ts = rows["timestamp"].to_numpy(dtype=float)
            d = np.diff(ts)
            if len(ts) and abs(ts[0]) > tol:
                bad.append(f"첫 timestamp {ts[0]:.6f} ≠ 0")
            if len(d) and (d <= 0).any():
                bad.append("timestamp가 단조 증가가 아님")
            if len(d) and (np.abs(d - 1.0 / fps) > tol).any():
                bad.append(f"timestamp 간격이 1/fps±{tol}를 벗어남(최대 {np.abs(d - 1.0 / fps).max():.6f})")
            for key in ("observation.state", "action"):
                if key in rows:
                    arr = np.stack(rows[key].to_numpy()).astype(float)
                    if arr.shape[1:] != (len(want_names),):
                        bad.append(f"{key} 행 형태 {arr.shape[1:]}")
                    elif np.isnan(arr).any() or np.isinf(arr).any():
                        bad.append(f"{key}에 NaN/Inf {int(np.isnan(arr).sum() + np.isinf(arr).sum())}개")
                    else:
                        body, grip = arr[:, :-1], arr[:, -1]
                        if np.abs(body).max() > 360 or grip.min() < -5 or grip.max() > 105:
                            f.add(WARN, f"episode {e_idx} {key} 값 범위가 공식 단위(몸체 도, gripper 0~100)와 맞지 않아 보임",
                                  f"몸체 |max| {np.abs(body).max():.1f}, gripper {grip.min():.1f}~{grip.max():.1f}")
            tis = set(int(x) for x in rows["task_index"].unique())
            r["task_index"] = sorted(tis)
        # 영상 구간(v3: 여러 에피소드가 한 MP4를 공유 → offset으로 비교)
        for vk in vkeys:
            t0, t1 = float(ep[f"videos/{vk}/from_timestamp"]), float(ep[f"videos/{vk}/to_timestamp"])
            vpath = root / meta.get_video_file_path(e_idx, vk)
            if not vpath.is_file():
                bad.append(f"{vk} 영상 파일 없음: {vpath.relative_to(root)}")
                continue
            if abs((t1 - t0) - length / fps) > 1.5 / fps:
                bad.append(f"{vk} 영상 구간 {t1 - t0:.3f}s ≠ length/fps {length / fps:.3f}s")
            if decode:
                n, pts = _count_video_frames(vpath, t0, t1, fps)
                r[f"{vk}_decoded"] = n
                if n != length:
                    bad.append(f"{vk} 디코드 프레임 {n} ≠ length {length}(누락/중복)")
                elif len(pts) > 1 and (np.abs(np.diff(pts) - 1.0 / fps) > 0.5 / fps).any():
                    bad.append(f"{vk} 영상 pts 간격 불규칙")
        r["problems"] = bad
        ep_results.append(r)
        f.add(FAIL if bad else OK, f"episode {e_idx}: {length} 프레임 ({length / fps:.2f}s)", "; ".join(bad))
    out["episodes"] = ep_results

    # 3) task 보존(meta/tasks.parquet + task_index)
    tasks = meta.tasks
    try:
        task_map = {int(v): str(k) for k, v in tasks["task_index"].items()}
    except Exception:  # noqa: BLE001
        task_map = {}
    if tbl is not None:  # 데이터셋 수준: 범위를 골랐어도 전체 프레임의 task_index를 확인한다
        used = sorted(int(x) for x in tbl["task_index"].unique())
    else:
        used = sorted({t for r in ep_results for t in r.get("task_index", [])})
    missing = [t for t in used if t not in task_map]
    if missing or not task_map:
        f.add(FAIL, "task 정보 누락", f"task_index {missing}가 meta/tasks.parquet에 없음")
    else:
        f.add(OK, f"task {len(task_map)}개(meta/tasks.parquet, 프레임의 task_index로 연결)", "; ".join(task_map[t] for t in used)[:300])
    out["tasks"] = task_map

    # 4) 공식 __getitem__ 경로(영상 디코드 포함) 샘플(에피소드를 골랐으면 그 범위 안에서)
    if episodes is not None:
        ranges = [(int(ep_meta[i]["dataset_from_index"]), int(ep_meta[i]["dataset_to_index"]))
                  for i in range(n_eps) if int(ep_meta[i]["episode_index"]) in episodes]
        lo, hi = (min(a for a, _ in ranges), max(b for _, b in ranges) - 1) if ranges else (None, None)
    else:
        lo, hi = (0, len(ds) - 1) if len(ds) else (None, None)
    if decode and lo is not None:
        idxs = sorted({lo, (lo + hi) // 2, hi})[:max(1, sample)]
        try:
            for i in idxs:
                item = ds[i]
                for vk in vkeys:
                    img = item[vk]
                    h, w = feats[vk]["shape"][0], feats[vk]["shape"][1]
                    if tuple(img.shape[-2:]) != (h, w):
                        raise ValueError(f"{vk} 프레임 크기 {tuple(img.shape)} ≠ ({h},{w})")
            f.add(OK, f"공식 __getitem__(pyav 디코드) 샘플 {len(idxs)}개 정상", f"index {idxs}")
        except Exception as e:  # noqa: BLE001
            f.add(FAIL, "공식 __getitem__ 샘플 실패", f"{type(e).__name__}: {str(e)[:300]}")
    stats_p = root / "meta" / "stats.json"
    f.add(OK if stats_p.is_file() else WARN, "meta/stats.json " + ("있음" if stats_p.is_file() else "없음"))
    f.add(INFO, "측정 한계", "timestamp는 공식 기록 규칙(frame_index/fps)으로 저장된 값입니다. 실제 녹화 루프 지연은 "
                         "logs의 'Record loop is running slower' 경고 수로 확인합니다. 카메라 실제 프레임 시각은 저장되지 않습니다.")
    out.update({"fail": f.n_fail, "warn": f.n_warn, "items": f.items})
    print(f"\n결과: FAIL {f.n_fail}, WARN {f.n_warn}  (종료 코드 0=OK, 1=FAIL, 2=WARN만)")
    return out


def main(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="so101_dataset.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("inspect")
    p.add_argument("root", type=Path)
    p.add_argument("--json", type=Path, default=None)
    p.add_argument("--no-decode", action="store_true")
    p.add_argument("--episodes", default=None, help="에피소드별 검사 범위(예: 50-59, 3,5). 기본: 전체")
    a = ap.parse_args(argv)
    res = inspect_dataset(a.root, decode=not a.no_decode, episodes=parse_episode_spec(a.episodes) if a.episodes else None)
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    return 1 if res["fail"] else (2 if res["warn"] else 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
