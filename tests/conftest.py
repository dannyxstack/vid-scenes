import os
import tempfile
from pathlib import Path

# 必须在导入 app 之前设置，测试数据与真实数据隔离
_TMP = Path(tempfile.mkdtemp(prefix="vidscenes-test-"))
os.environ["VIDSCENES_DATA"] = str(_TMP / "data")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
import soundfile as sf  # noqa: E402

from app import media  # noqa: E402

FIXTURES = _TMP / "fixtures"
FIXTURES.mkdir(parents=True, exist_ok=True)

BPM = 120.0
MUSIC_SECONDS = 24.0
QUIET_SECONDS = 8.0


@pytest.fixture(scope="session")
def sample_video() -> Path:
    """三个明显不同的镜头，各 2 秒：运动的测试图 → 纯红 → 分形缩放。"""
    out = FIXTURES / "three_scenes.mp4"
    if not out.exists():
        media.ffmpeg(
            "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=2",
            "-f", "lavfi", "-i", "color=c=red:size=640x360:rate=30:duration=2",
            "-f", "lavfi", "-i", "mandelbrot=size=640x360:rate=30,trim=duration=2",
            "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
            "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out),
        )
    return out


@pytest.fixture(scope="session")
def sample_music() -> Path:
    """120 BPM 的四拍子音轨：底鼓 + 反拍镲 + 每小节换音的贝斯。
    前 8 秒小声（低能量），之后大声（高能量），小节第一拍加重。"""
    out = FIXTURES / "groove_120.wav"
    if not out.exists():
        sr = 44100
        n = int(MUSIC_SECONDS * sr)
        y = np.zeros(n)
        rng = np.random.default_rng(0)
        kick_t = np.arange(int(0.2 * sr)) / sr
        kick = np.sin(2 * np.pi * (50 + 120 * np.exp(-kick_t * 30)) * kick_t) * np.exp(-kick_t * 18)
        hat = rng.standard_normal(int(0.02 * sr)) * np.exp(-np.arange(int(0.02 * sr)) / sr * 250)
        interval = 60.0 / BPM
        bass_notes = [55.0, 73.4, 82.4, 65.4]
        for i in range(int(MUSIC_SECONDS / interval)):
            t = i * interval
            amp = 0.15 if t < QUIET_SECONDS else 0.9
            accent = 1.0 if i % 4 == 0 else 0.75
            s = int(t * sr)
            seg = kick[: n - s]
            y[s:s + len(seg)] += amp * accent * seg
            h = int((t + interval / 2) * sr)
            if h < n:
                hs = hat[: n - h]
                y[h:h + len(hs)] += amp * 0.08 * hs
            if i % 4 == 0:
                # 贝斯音高在每个小节第一拍变化，提供和声上的小节线索
                bar_len = min(int(4 * interval * sr), n - s)
                bt = np.arange(bar_len) / sr
                f = bass_notes[(i // 4) % len(bass_notes)]
                y[s:s + bar_len] += amp * 0.25 * np.sin(2 * np.pi * f * bt) * np.exp(-bt * 0.8)
        y = np.clip(y, -1, 1)
        sf.write(out, np.stack([y, y], axis=1), sr)
    return out
