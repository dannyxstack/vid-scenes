"""转场检测。检测器可插拔：P0 用 PySceneDetect，P1 加 TransNetV2。"""

from pathlib import Path

from . import config


def detect_pyscenedetect(path: str | Path) -> list[tuple[float, float]]:
    from scenedetect import AdaptiveDetector, detect

    scenes = detect(str(path), AdaptiveDetector(), show_progress=False, start_in_scene=True)
    return [(a.get_seconds(), b.get_seconds()) for a, b in scenes]


DETECTORS = {"pyscenedetect": detect_pyscenedetect}


def merge_short(scenes: list[tuple[float, float]], min_len: float) -> list[tuple[float, float]]:
    """把短于 min_len 的片段并入前一个（第一个则并入后一个）。"""
    out: list[list[float]] = []
    for start, end in scenes:
        if out and (end - start < min_len or out[-1][1] - out[-1][0] < min_len):
            out[-1][1] = end
        else:
            out.append([start, end])
    return [(a, b) for a, b in out]


def detect_scenes(path: str | Path, duration: float, detector: str = "pyscenedetect") -> list[tuple[float, float]]:
    scenes = DETECTORS[detector](path)
    if not scenes:
        scenes = [(0.0, duration)]
    # 最后一个片段延伸到视频结尾，避免丢掉尾巴
    if duration and scenes[-1][1] < duration:
        scenes[-1] = (scenes[-1][0], duration)
    return merge_short(scenes, config.MIN_CLIP_SECONDS)
