from app import audio

from .conftest import BPM, MUSIC_SECONDS, QUIET_SECONDS


def test_analyze_click_track(sample_music):
    a = audio.analyze(sample_music)
    assert abs(a["duration"] - MUSIC_SECONDS) < 0.05
    assert abs(a["bpm"] - BPM) < 2
    n_beats = len(a["beats"])
    assert n_beats >= MUSIC_SECONDS * BPM / 60 * 0.85
    assert set(a["downbeats"]) <= set(a["beats"])
    assert len(a["downbeats"]) >= n_beats // 4 - 2
    quiet = [b["level"] for b in a["bars"] if b["end"] <= QUIET_SECONDS]
    # 只看完整小节，结尾不足一小节的余音不算
    loud = [b["level"] for b in a["bars"] if b["start"] >= QUIET_SECONDS + 1 and b["end"] - b["start"] > 1]
    assert quiet and all(lv == "low" for lv in quiet)
    assert loud and all(lv == "high" for lv in loud)
    assert len(a["waveform"]) > 100


def test_bar_levels_phrase_smoothing():
    import numpy as np

    levels = audio.bar_levels(np.array([0.1, 0.1, 0.1, 0.1, 1, 1, 1, 1]))
    assert levels == ["low"] * 4 + ["high"] * 4
