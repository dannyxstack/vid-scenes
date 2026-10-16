"""规则编排：根据音乐能量决定切点，再按打分贪心挑选片段，输出时间线 JSON。"""

from dataclasses import dataclass

import numpy as np

from . import config

MIN_FIRST_SEGMENT = 0.25  # 第一个强拍之前的前奏短于该值时并入第一段
MIN_SEGMENT = 0.3  # 短于该值的镜头并入前一段
MIN_CLIP_FOR_POOL = 0.3
MOTION_TARGET = {"low": 0.2, "mid": 0.5, "high": 0.85}
RECENT_WINDOW = 8
EDGE_MARGIN = 0.05  # 避免取到下一个镜头的边缘帧

W_ENERGY, W_FIT, W_PEAK, W_COLOR, W_NOISE = 1.0, 2.0, 0.3, 0.2, 0.15
P_REUSE, P_RECENT, P_SAME_VIDEO = 0.5, 2.0, 0.3


@dataclass
class ClipInfo:
    id: int
    video_id: int
    start: float
    end: float
    motion: float
    peak_offset: float
    peak_strength: float
    color_hex: str

    @property
    def duration(self) -> float:
        return self.end - self.start


def default_settings() -> dict:
    return {"width": 1920, "height": 1080, "fps": 30, "seed": 0,
            "cut_beats": dict(config.DEFAULT_CUT_BEATS)}


def _level_at(bars: list[dict], t: float) -> str:
    if not bars:
        return "mid"
    for b in bars:
        if b["start"] <= t < b["end"]:
            return b["level"]
    return bars[0]["level"] if t < bars[0]["start"] else bars[-1]["level"]


def cut_points(analysis: dict, cut_beats: dict[str, int]) -> list[tuple[float, str]]:
    """返回 [(切点时间, 该段能量等级)]，第一个切点总是 0。"""
    beats = analysis["beats"]
    bars = analysis["bars"]
    if not beats:
        raise ValueError("音乐没有检测到节拍")
    down = set(analysis["downbeats"])
    is_down = [b in down for b in beats]
    j = next((i for i, d in enumerate(is_down) if d), 0)

    cuts = [0.0]
    if beats[j] >= MIN_FIRST_SEGMENT:
        cuts.append(beats[j])
    n = len(beats)
    while j < n:
        level = _level_at(bars, beats[j])
        step = max(1, int(cut_beats.get(level, 4)))
        k = j + 1
        if step >= 4:
            # 按小节切：经过 step//4 个强拍；能量等级变化时提前切
            need, passed = step // 4, 0
            while k < n:
                if is_down[k]:
                    passed += 1
                    if passed >= need or _level_at(bars, beats[k]) != level:
                        break
                k += 1
        else:
            # 拍内切：每 step 拍一刀，遇到强拍重新对齐
            while k < n and k < j + step and not is_down[k]:
                k += 1
        if k >= n:
            break
        cuts.append(beats[k])
        j = k
    # 太短的镜头（比如伪拍造成的）并入前一段
    duration = float(analysis["duration"])
    kept = [cuts[0]]
    for t in cuts[1:]:
        if t - kept[-1] >= MIN_SEGMENT and duration - t >= MIN_SEGMENT:
            kept.append(t)
    return [(t, _level_at(bars, t)) for t in kept]


def _hex_rgb(h: str) -> np.ndarray:
    h = (h or "#000000").lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=float)


def compose(analysis: dict, clips: list[ClipInfo], settings: dict | None = None) -> dict:
    s = {**default_settings(), **(settings or {})}
    s["cut_beats"] = {**config.DEFAULT_CUT_BEATS, **(s.get("cut_beats") or {})}
    fps = int(s["fps"])
    duration = float(analysis["duration"])
    pool = [c for c in clips if c.duration >= MIN_CLIP_FOR_POOL]
    if not pool:
        raise ValueError("素材库里没有可用片段")

    cuts = cut_points(analysis, s["cut_beats"])
    # 切点按帧累计取整，避免漂移
    frame_marks = [round(t * fps) for t, _ in cuts] + [round(duration * fps)]
    raw = []
    for i, (t, level) in enumerate(cuts):
        f0, f1 = frame_marks[i], frame_marks[i + 1]
        if f1 > f0:
            raw.append((f0, f1 - f0, level))

    rng = np.random.default_rng(int(s["seed"]))
    motion = np.array([c.motion for c in pool])
    rank = motion.argsort().argsort() / max(1, len(pool) - 1)
    durs = np.array([c.duration for c in pool])
    peak = np.clip(np.array([c.peak_strength for c in pool]), 0, 5) / 5
    colors = np.stack([_hex_rgb(c.color_hex) for c in pool])
    video_ids = np.array([c.video_id for c in pool])
    used = np.zeros(len(pool))
    last_used = np.full(len(pool), -10_000)

    segments = []
    prev = None
    for i, (f0, nframes, level) in enumerate(raw):
        d = nframes / fps
        fit = np.minimum(1.0, durs / d)
        score = (
            W_ENERGY * (1 - np.abs(rank - MOTION_TARGET.get(level, 0.5)))
            + W_FIT * (fit - 1)
            + (W_PEAK * peak if level == "high" else 0)
            - P_REUSE * used
            - P_RECENT * ((i - last_used) <= RECENT_WINDOW)
            + W_NOISE * rng.random(len(pool))
        )
        if prev is not None:
            score += W_COLOR * (1 - np.linalg.norm(colors - colors[prev], axis=1) / 441.7)
            score -= P_SAME_VIDEO * (video_ids == video_ids[prev])
            if len(pool) > 1:
                score[prev] = -np.inf  # 硬约束：相邻镜头不用同一个片段
        ci = int(np.argmax(score))
        c = pool[ci]

        latest = c.end - d - EDGE_MARGIN
        hold = latest < c.start
        if hold:
            src_in = c.start
        elif used[ci] == 0:
            # 首次使用：把视觉峰值放在切点（强拍）上
            src_in = min(max(c.start + c.peak_offset, c.start), latest)
        else:
            src_in = float(rng.uniform(c.start, latest))
        used[ci] += 1
        last_used[ci] = i
        prev = ci
        segments.append({
            "index": len(segments),
            "start_frame": f0,
            "frames": nframes,
            "start": round(f0 / fps, 4),
            "duration": round(d, 4),
            "level": level,
            "clip_id": c.id,
            "video_id": c.video_id,
            "src_in": round(src_in, 4),
            "hold": bool(hold),
            "score": round(float(score[ci]), 3),
        })

    return {
        "version": 1,
        "fps": fps,
        "width": int(s["width"]),
        "height": int(s["height"]),
        "duration": duration,
        "total_frames": frame_marks[-1],
        "settings": s,
        "segments": segments,
    }
