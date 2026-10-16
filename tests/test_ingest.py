from app import config, features, media, scenes


def test_probe(sample_video):
    info = media.probe(sample_video)
    assert info["has_video"]
    assert abs(info["duration"] - 6.0) < 0.1
    assert (info["width"], info["height"]) == (640, 360)
    assert abs(info["fps"] - 30) < 0.01


def test_scene_detection_finds_three_shots(sample_video):
    ranges = scenes.detect_scenes(sample_video, 6.0)
    assert len(ranges) == 3
    for (a, b), expected in zip(ranges, [0, 2, 4]):
        assert abs(a - expected) < 0.1
    assert abs(ranges[-1][1] - 6.0) < 0.1


def test_merge_short():
    merged = scenes.merge_short([(0, 2), (2, 2.2), (2.2, 5)], 0.5)
    assert merged == [(0, 2.2), (2.2, 5)]


def test_clip_features(sample_video, tmp_path):
    ranges = scenes.detect_scenes(sample_video, 6.0)
    thumbs = [tmp_path / f"{i}.jpg" for i in range(len(ranges))]
    feats = features.analyze_clips(sample_video, ranges, thumbs, config.FEATURE_SAMPLE_FPS)
    assert len(feats) == 3
    assert all(t.exists() for t in thumbs)
    moving, red, _ = feats
    # 纯红镜头几乎没有运动，主色调是红色
    assert red["motion"] < moving["motion"]
    r, g, b = (int(red["color_hex"][i:i + 2], 16) for i in (1, 3, 5))
    assert r > 200 and g < 60 and b < 60
    for f in feats:
        assert 0 <= f["peak_offset"] <= 2.05
        assert f["motion_curve"]["v"]
