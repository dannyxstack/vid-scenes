"""片段基础视觉特征：对代理文件做一次顺序解码，按片段累计。"""

from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

ANALYSIS_WIDTH = 160
THUMB_WIDTH = 320
# 运动强度按 0.1 秒间隔归一化，使不同帧率的素材可比
MOTION_REF_DT = 0.1


@dataclass
class _Acc:
    start: float
    end: float
    times: list[float] = field(default_factory=list)
    motion: list[float] = field(default_factory=list)
    bright_delta: list[float] = field(default_factory=list)
    brightness: list[float] = field(default_factory=list)
    saturation: list[float] = field(default_factory=list)
    sharpness: list[float] = field(default_factory=list)
    prev_gray: np.ndarray | None = None
    prev_v: float | None = None
    prev_t: float | None = None
    mid_frame: np.ndarray | None = None
    mid_dist: float = float("inf")


def dominant_color(bgr: np.ndarray, k: int = 3) -> str:
    small = cv2.resize(bgr, (48, 27), interpolation=cv2.INTER_AREA)
    pixels = small.reshape(-1, 3).astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, labels, centers = cv2.kmeans(pixels, k, None, criteria, 2, cv2.KMEANS_PP_CENTERS)
    best = centers[np.bincount(labels.ravel(), minlength=k).argmax()]
    b, g, r = (int(round(x)) for x in best)
    return f"#{r:02x}{g:02x}{b:02x}"


def _summarize(acc: _Acc) -> dict:
    n = len(acc.times)
    if n == 0:
        return {"motion": 0.0, "brightness": 0.0, "saturation": 0.0, "sharpness": 0.0,
                "peak_offset": 0.0, "peak_strength": 1.0, "motion_curve": {"dt": 0.0, "v": []},
                "color_hex": "#000000"}
    motion = np.array(acc.motion)
    # 视觉节拍：运动突变 + 亮度突变（闪光）
    novelty = motion + 0.5 * np.array(acc.bright_delta)
    if n >= 3 and novelty[1:].max() > 0:
        i = int(np.argmax(novelty[1:])) + 1
        peak_offset = acc.times[i] - acc.start
        peak_strength = float(novelty[i] / (novelty[1:].mean() + 1e-6))
    else:
        peak_offset, peak_strength = 0.0, 1.0
    dt = float(np.median(np.diff(acc.times))) if n > 1 else 0.0
    return {
        "motion": float(motion[1:].mean()) if n > 1 else 0.0,
        "brightness": float(np.mean(acc.brightness)),
        "saturation": float(np.mean(acc.saturation)),
        "sharpness": float(np.mean(acc.sharpness)),
        "peak_offset": float(peak_offset),
        "peak_strength": peak_strength,
        "motion_curve": {"dt": round(dt, 4), "t0": round(acc.times[0] - acc.start, 4),
                         "v": [round(float(x), 4) for x in motion]},
        "color_hex": dominant_color(acc.mid_frame) if acc.mid_frame is not None else "#000000",
    }


def analyze_clips(
    proxy_path: str | Path,
    clips: list[tuple[float, float]],
    thumb_paths: list[str | Path],
    sample_fps: float,
    report: Callable[[float], None] | None = None,
) -> list[dict]:
    """返回每个片段的特征字典，并把片段中点帧写成缩略图。"""
    cap = cv2.VideoCapture(str(proxy_path))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频: {proxy_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    step = max(1, int(round(fps / sample_fps)))
    starts = [c[0] for c in clips]
    accs = [_Acc(start=a, end=b) for a, b in clips]

    idx = 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if idx % step == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            t = idx / fps
            ci = max(0, bisect_right(starts, t) - 1)
            acc = accs[ci]
            h, w = frame.shape[:2]
            small = cv2.resize(frame, (ANALYSIS_WIDTH, max(1, int(h * ANALYSIS_WIDTH / w))),
                               interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
            v = float(hsv[..., 2].mean()) / 255.0
            if acc.prev_gray is not None:
                diff = float(cv2.absdiff(gray, acc.prev_gray).mean()) / 255.0
                scale = MOTION_REF_DT / max(t - acc.prev_t, 1e-3)
                acc.motion.append(diff * scale)
                acc.bright_delta.append(abs(v - acc.prev_v) * scale)
            else:
                acc.motion.append(0.0)
                acc.bright_delta.append(0.0)
            acc.times.append(t)
            acc.brightness.append(v)
            acc.saturation.append(float(hsv[..., 1].mean()) / 255.0)
            acc.sharpness.append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))
            acc.prev_gray, acc.prev_v, acc.prev_t = gray, v, t
            mid = (acc.start + acc.end) / 2
            if abs(t - mid) < acc.mid_dist:
                acc.mid_dist = abs(t - mid)
                acc.mid_frame = frame
            if report and idx % (step * 20) == 0:
                report(min(1.0, idx / total))
        idx += 1
    cap.release()

    results = []
    for acc, thumb in zip(accs, thumb_paths):
        if acc.mid_frame is not None:
            h, w = acc.mid_frame.shape[:2]
            tw = min(THUMB_WIDTH, w)
            th = int(h * tw / w) // 2 * 2
            cv2.imwrite(str(thumb), cv2.resize(acc.mid_frame, (tw, th), interpolation=cv2.INTER_AREA),
                        [cv2.IMWRITE_JPEG_QUALITY, 85])
        results.append(_summarize(acc))
    return results
