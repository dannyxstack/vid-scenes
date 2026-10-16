"""端到端：通过 API 上传素材和音乐 → 后台处理 → 编排 → 渲染 → 校验成片。"""

import json

from fastapi.testclient import TestClient

from app import jobs, media
from app.main import app


def _count_frames(path) -> int:
    out = media.run([media.FFPROBE, "-v", "error", "-select_streams", "v:0", "-count_frames",
                     "-show_entries", "stream=nb_read_frames", "-of", "json", str(path)])
    return int(json.loads(out)["streams"][0]["nb_read_frames"])


def test_full_pipeline(sample_video, sample_music):
    with TestClient(app) as client:
        with sample_video.open("rb") as f:
            r = client.post("/api/videos", files=[("files", ("three.mp4", f, "video/mp4"))])
        assert r.status_code == 200, r.text
        vid = r.json()["ids"][0]
        with sample_music.open("rb") as f:
            r = client.post("/api/music", files={"file": ("click.wav", f, "audio/wav")})
        assert r.status_code == 200, r.text
        mid = r.json()["id"]
        jobs.wait_idle()

        v = client.get(f"/api/videos/{vid}").json()
        assert v["status"] == "ready", v
        assert len(v["clips"]) == 3
        assert v["proxy_url"] and v["thumb_url"]
        assert client.get(v["clips"][0]["thumb_url"]).status_code == 200

        m = client.get(f"/api/music/{mid}").json()
        assert m["status"] == "ready", m
        assert abs(m["bpm"] - 120) < 2

        r = client.post("/api/compositions", json={
            "music_id": mid, "settings": {"width": 320, "height": 180, "fps": 30, "seed": 7},
        })
        assert r.status_code == 200, r.text
        cid = r.json()["id"]
        jobs.wait_idle()

        c = client.get(f"/api/compositions/{cid}").json()
        assert c["status"] == "done", c
        tl = c["timeline"]
        from app.config import DATA_DIR

        out = DATA_DIR / c["output_url"].removeprefix("/media/")
        info = media.probe(out)
        assert (info["width"], info["height"]) == (320, 180)
        assert info["has_audio"]
        assert abs(info["duration"] - tl["duration"]) < 0.15
        # 帧精确：成片帧数与时间线一致
        assert abs(_count_frames(out) - tl["total_frames"]) <= 1

        # 范围请求（视频拖动进度条需要）
        r = client.get(c["output_url"], headers={"Range": "bytes=0-99"})
        assert r.status_code == 206
