"""后台任务处理器：素材入库、音乐分析、成片渲染。"""

from pathlib import Path

from sqlalchemy import delete, select

from . import audio, config, features, jobs, media, render, scenes
from .composer import ClipInfo
from .db import session_scope
from .models import Clip, Composition, Music, Video


def _set(model, obj_id: int, **fields) -> None:
    with session_scope() as s:
        obj = s.get(model, obj_id)
        for k, v in fields.items():
            setattr(obj, k, v)


@jobs.register("ingest")
def ingest(job_id: int, video_id: int, report) -> None:
    with session_scope() as s:
        v = s.get(Video, video_id)
        src = Path(v.path)
        v.status, v.error = "processing", None
    try:
        report(0.02, "读取元数据")
        info = media.probe(src)
        if not info["has_video"]:
            raise ValueError("文件里没有视频流")
        _set(Video, video_id, duration=info["duration"], width=info["width"],
             height=info["height"], fps=info["fps"], codec=info["codec"])

        report(0.05, "生成代理文件")
        proxy = src.parent / "proxy.mp4"
        media.make_proxy(src, proxy, config.PROXY_HEIGHT)
        thumb = src.parent / "thumb.jpg"
        media.thumbnail(proxy, info["duration"] * 0.1, thumb)
        _set(Video, video_id, proxy_path=str(proxy), thumb_path=str(thumb))

        report(0.4, "转场检测")
        ranges = scenes.detect_scenes(proxy, info["duration"])

        report(0.6, f"分析 {len(ranges)} 个片段")
        thumbs_dir = src.parent / "clips"
        thumbs_dir.mkdir(exist_ok=True)
        thumb_paths = [thumbs_dir / f"{i:04d}.jpg" for i in range(len(ranges))]
        feats = features.analyze_clips(
            proxy, ranges, thumb_paths, config.FEATURE_SAMPLE_FPS,
            report=lambda p: report(0.6 + 0.38 * p, "分析片段特征"),
        )

        with session_scope() as s:
            s.execute(delete(Clip).where(Clip.video_id == video_id))
            for i, ((a, b), f, tp) in enumerate(zip(ranges, feats, thumb_paths)):
                s.add(Clip(video_id=video_id, idx=i, start=a, end=b,
                           thumb_path=str(tp) if tp.exists() else None, **f))
            s.get(Video, video_id).status = "ready"
    except Exception as e:
        _set(Video, video_id, status="error", error=str(e))
        raise


@jobs.register("analyze")
def analyze_music(job_id: int, music_id: int, report) -> None:
    with session_scope() as s:
        m = s.get(Music, music_id)
        src = Path(m.path)
        m.status, m.error = "processing", None
    try:
        report(0.05, "转换音频")
        wav = src.parent / "audio.wav"
        media.to_wav(src, wav)
        report(0.2, "节拍与能量分析")
        result = audio.analyze(wav)
        _set(Music, music_id, wav_path=str(wav), duration=result["duration"],
             bpm=result["bpm"], analysis=result, status="ready")
    except Exception as e:
        _set(Music, music_id, status="error", error=str(e))
        raise


def load_clip_pool(session) -> list[ClipInfo]:
    rows = session.execute(
        select(Clip).join(Video).where(Clip.enabled.is_(True), Video.status == "ready")
    ).scalars().all()
    return [
        ClipInfo(id=c.id, video_id=c.video_id, start=c.start, end=c.end,
                 motion=c.motion or 0.0, peak_offset=c.peak_offset or 0.0,
                 peak_strength=c.peak_strength or 1.0, color_hex=c.color_hex or "#000000")
        for c in rows
    ]


@jobs.register("render")
def render_composition(job_id: int, comp_id: int, report) -> None:
    with session_scope() as s:
        comp = s.get(Composition, comp_id)
        timeline = comp.timeline
        audio_path = comp.music.wav_path
        vids = {seg["video_id"] for seg in timeline["segments"]}
        sources = {v.id: v.path for v in s.scalars(select(Video).where(Video.id.in_(vids)))}
        comp.status, comp.error = "rendering", None
    try:
        missing = vids - sources.keys()
        if missing:
            raise ValueError(f"时间线引用的素材已被删除: {sorted(missing)}")
        out_dir = config.RENDERS_DIR / str(comp_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / "output.mp4"
        render.render(timeline, sources, audio_path, out, out_dir / "work", report=report)
        _set(Composition, comp_id, status="done", output_path=str(out))
    except Exception as e:
        _set(Composition, comp_id, status="error", error=str(e))
        raise
