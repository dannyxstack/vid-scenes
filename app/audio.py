"""音乐分析：节拍、小节第一拍、BPM、按小节的能量等级、波形峰值。"""

import logging
import threading
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

ANALYSIS_SR = 22050
PHRASE_BARS = 4
HIGH_RATIO = 0.8   # 相对 p95 能量 ≥ 该值为 high
LOW_RATIO = 0.55   # 相对 p95 能量 < 该值为 low
WAVEFORM_POINTS = 1500

_model = None
_model_lock = threading.Lock()


def _beat_this(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    global _model
    import torch
    from beat_this.inference import File2Beats

    with _model_lock:
        if _model is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
            _model = File2Beats(checkpoint_path="final0", device=device, dbn=False)
        beats, downbeats = _model(str(path))
    return np.asarray(beats, dtype=float), np.asarray(downbeats, dtype=float)


def _infer_downbeats(beats: np.ndarray, y: np.ndarray, sr: int) -> np.ndarray:
    """按 4/4 推算小节第一拍：选起音强度总和最大的相位。"""
    import librosa

    if len(beats) < 4:
        return beats[:1]
    onset = librosa.onset.onset_strength(y=y, sr=sr)
    frames = np.clip(librosa.time_to_frames(beats, sr=sr), 0, len(onset) - 1)
    strength = onset[frames]
    phase = int(np.argmax([strength[p::4].mean() for p in range(4)]))
    return beats[phase::4]


def _librosa_beats(y: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    import librosa

    _, frames = librosa.beat.beat_track(y=y, sr=sr)
    beats = librosa.frames_to_time(frames, sr=sr)
    return beats, _infer_downbeats(beats, y, sr)


def detect_beats(path: str | Path, y: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray, str]:
    try:
        beats, downbeats = _beat_this(path)
        if len(beats) >= 4:
            return beats, downbeats, "beat_this"
        log.warning("beat_this 只检测到 %d 拍，改用 librosa", len(beats))
    except Exception:  # noqa: BLE001
        log.exception("beat_this 不可用，改用 librosa")
    beats, downbeats = _librosa_beats(y, sr)
    return beats, downbeats, "librosa"


def _snap_downbeats(beats: np.ndarray, downbeats: np.ndarray) -> np.ndarray:
    """把小节第一拍吸附到最近的拍上，保证它是拍集合的子集。"""
    if len(beats) == 0:
        return downbeats
    idx = np.unique(np.abs(beats[None, :] - downbeats[:, None]).argmin(axis=1))
    return beats[idx]


def _clean_downbeats(beats: np.ndarray, downbeats: np.ndarray, min_gap: int = 3) -> np.ndarray:
    """去掉离上一个强拍不足 min_gap 拍的伪强拍（兼容 3/4 拍）。"""
    if len(downbeats) == 0:
        return downbeats
    idx = np.searchsorted(beats, downbeats)
    kept = [idx[0]]
    for i in idx[1:]:
        if i - kept[-1] >= min_gap:
            kept.append(i)
    return beats[np.array(kept)]


def bar_levels(energies: np.ndarray) -> list[str]:
    if len(energies) == 0:
        return []
    phrase = np.array([
        energies[i:i + PHRASE_BARS].mean()
        for i in range(0, len(energies), PHRASE_BARS)
        for _ in range(min(PHRASE_BARS, len(energies) - i))
    ])
    ref = np.percentile(energies, 95) or 1.0
    ratio = phrase / ref
    return ["high" if r >= HIGH_RATIO else "low" if r < LOW_RATIO else "mid" for r in ratio]


def analyze(wav_path: str | Path) -> dict:
    import librosa

    y, sr = librosa.load(str(wav_path), sr=ANALYSIS_SR, mono=True)
    duration = len(y) / sr
    beats, downbeats, engine = detect_beats(wav_path, y, sr)
    beats = np.sort(beats[(beats >= 0) & (beats < duration)])
    downbeats = _clean_downbeats(beats, _snap_downbeats(beats, np.sort(downbeats)))
    # 每小节拍数不合理（比如把每一拍都当成强拍）时，按 4/4 重新推算
    beats_per_bar = len(beats) / max(1, len(downbeats))
    if not 2.5 <= beats_per_bar <= 8:
        log.warning("小节第一拍不可信（平均每小节 %.1f 拍），按 4/4 重新推算", beats_per_bar)
        downbeats = _infer_downbeats(beats, y, sr)

    intervals = np.diff(beats)
    bpm = float(60.0 / np.median(intervals)) if len(intervals) else 0.0

    hop = 512
    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    rms_t = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop)
    bounds = list(downbeats) + [duration]
    energies = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        m = (rms_t >= a) & (rms_t < b)
        energies.append(float(rms[m].mean()) if m.any() else 0.0)
    energies = np.array(energies)
    levels = bar_levels(energies)
    ref = float(np.percentile(energies, 95)) if len(energies) else 1.0
    bars = [
        {"start": round(float(a), 4), "end": round(float(b), 4),
         "energy": round(float(e / ref) if ref else 0.0, 4), "level": lv}
        for a, b, e, lv in zip(bounds[:-1], bounds[1:], energies, levels)
    ]

    bins = np.array_split(np.abs(y), min(WAVEFORM_POINTS, len(y)))
    peaks = [round(float(b.max()), 3) if len(b) else 0.0 for b in bins]

    return {
        "engine": engine,
        "duration": round(duration, 4),
        "bpm": round(bpm, 2),
        "beats": [round(float(b), 4) for b in beats],
        "downbeats": [round(float(b), 4) for b in downbeats],
        "bars": bars,
        "waveform": peaks,
    }
