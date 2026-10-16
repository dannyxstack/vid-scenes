import pytest

from app.composer import ClipInfo, compose, cut_points


def make_analysis(duration=32.0, bpm=120.0, levels=("low", "low", "mid", "mid", "high", "high", "high", "high")):
    interval = 60 / bpm
    beats = [round(i * interval, 4) for i in range(int(duration / interval))]
    downbeats = beats[::4]
    bar_len = interval * 4
    bars = []
    for i, start in enumerate(downbeats):
        lv = levels[min(i * len(levels) // len(downbeats), len(levels) - 1)]
        bars.append({"start": start, "end": min(duration, start + bar_len), "energy": 0.5, "level": lv})
    return {"duration": duration, "bpm": bpm, "beats": beats, "downbeats": downbeats, "bars": bars}


def make_clips(n=12):
    return [
        ClipInfo(id=i, video_id=i // 3, start=0.0, end=3.0 + i % 4, motion=i / n,
                 peak_offset=0.4, peak_strength=1 + i % 3, color_hex="#336699")
        for i in range(n)
    ]


def test_cut_points_follow_energy():
    a = make_analysis()
    cuts = cut_points(a, {"low": 8, "mid": 4, "high": 2})
    assert cuts[0][0] == 0.0
    times = [t for t, _ in cuts]
    assert all(t in a["beats"] for t in times[1:])
    gaps = {lv: [] for lv in ("low", "mid", "high")}
    for (t, lv), (t2, _) in zip(cuts, cuts[1:]):
        gaps[lv].append(round(t2 - t, 3))
    # 120 BPM：8 拍 = 4 秒，4 拍 = 2 秒，2 拍 = 1 秒
    assert max(gaps["low"]) == pytest.approx(4.0)
    assert max(gaps["mid"]) == pytest.approx(2.0)
    assert max(gaps["high"]) == pytest.approx(1.0)


def test_compose_frames_are_exact():
    a = make_analysis()
    tl = compose(a, make_clips(), {"fps": 30, "seed": 1})
    segs = tl["segments"]
    assert sum(s["frames"] for s in segs) == tl["total_frames"] == round(a["duration"] * 30)
    beat_frames = {round(b * 30) for b in a["beats"]} | {0}
    pos = 0
    for s in segs:
        assert s["start_frame"] == pos
        assert s["start_frame"] in beat_frames
        pos += s["frames"]


def test_compose_avoids_immediate_repeats_and_respects_window():
    clips = make_clips()
    by_id = {c.id: c for c in clips}
    tl = compose(make_analysis(), clips, {"fps": 30, "seed": 3})
    ids = [s["clip_id"] for s in tl["segments"]]
    assert all(a != b for a, b in zip(ids, ids[1:]))
    for s in tl["segments"]:
        c = by_id[s["clip_id"]]
        assert c.start <= s["src_in"]
        if not s["hold"]:
            assert s["src_in"] + s["duration"] <= c.end + 1e-6


def test_compose_tiny_pool_never_repeats_adjacent():
    clips = make_clips(2)
    for seed in range(5):
        ids = [s["clip_id"] for s in compose(make_analysis(), clips, {"seed": seed})["segments"]]
        assert all(a != b for a, b in zip(ids, ids[1:]))


def test_short_segments_are_merged():
    a = make_analysis()
    # 在末尾附近插入一个伪拍
    a["beats"] = a["beats"] + [31.9]
    a["downbeats"] = a["downbeats"] + [31.9]
    cuts = [t for t, _ in cut_points(a, {"low": 8, "mid": 4, "high": 2})]
    gaps = [b - x for x, b in zip(cuts, cuts[1:] + [a["duration"]])]
    assert min(gaps) >= 0.3


def test_compose_seed_changes_result():
    a, clips = make_analysis(), make_clips()
    ids = lambda seed: [s["clip_id"] for s in compose(a, clips, {"seed": seed})["segments"]]  # noqa: E731
    assert ids(1) == ids(1)
    assert ids(1) != ids(2)


def test_compose_requires_clips():
    with pytest.raises(ValueError):
        compose(make_analysis(), [])
