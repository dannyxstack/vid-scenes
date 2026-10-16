import logging
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config, jobs, pipeline  # noqa: F401  pipeline 注册任务处理器
from .composer import compose, default_settings
from .db import get_session, init_db
from .models import Clip, Composition, Job, Music, Video

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mts", ".ts"}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    jobs.start_worker()
    yield


app = FastAPI(title="vid-scenes", lifespan=lifespan)
config.ensure_dirs()
app.mount("/media", StaticFiles(directory=config.DATA_DIR), name="media")
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(config.STATIC_DIR / "index.html")


# ---------- 序列化 ----------

def _job_brief(s: Session, kind: str, target_id: int) -> dict | None:
    job = s.scalars(
        select(Job).where(Job.kind == kind, Job.target_id == target_id).order_by(Job.id.desc())
    ).first()
    if job is None:
        return None
    return {"id": job.id, "status": job.status, "progress": job.progress,
            "message": job.message, "error": job.error}


def clip_out(c: Clip) -> dict:
    return {
        "id": c.id, "video_id": c.video_id, "idx": c.idx,
        "start": c.start, "end": c.end, "duration": round(c.duration, 3),
        "enabled": c.enabled, "thumb_url": config.to_media_url(c.thumb_path),
        "motion": c.motion, "brightness": c.brightness, "saturation": c.saturation,
        "sharpness": c.sharpness, "color_hex": c.color_hex,
        "peak_offset": c.peak_offset, "peak_strength": c.peak_strength,
    }


def video_out(s: Session, v: Video, clip_count: int | None = None) -> dict:
    return {
        "id": v.id, "filename": v.filename, "status": v.status, "error": v.error,
        "duration": v.duration, "width": v.width, "height": v.height, "fps": v.fps,
        "codec": v.codec, "created_at": v.created_at.isoformat(),
        "thumb_url": config.to_media_url(v.thumb_path),
        "proxy_url": config.to_media_url(v.proxy_path),
        "clip_count": clip_count if clip_count is not None else len(v.clips),
        "job": _job_brief(s, "ingest", v.id),
    }


def music_out(s: Session, m: Music, full: bool = False) -> dict:
    out = {
        "id": m.id, "filename": m.filename, "status": m.status, "error": m.error,
        "duration": m.duration, "bpm": m.bpm, "created_at": m.created_at.isoformat(),
        "audio_url": config.to_media_url(m.wav_path),
        "engine": (m.analysis or {}).get("engine"),
        "job": _job_brief(s, "analyze", m.id),
    }
    if full:
        out["analysis"] = m.analysis
    return out


def comp_out(s: Session, c: Composition, full: bool = False) -> dict:
    tl = c.timeline or {}
    out = {
        "id": c.id, "music_id": c.music_id, "music_filename": c.music.filename,
        "status": c.status, "error": c.error, "settings": c.settings,
        "created_at": c.created_at.isoformat(),
        "segment_count": len(tl.get("segments", [])),
        "duration": tl.get("duration"),
        "output_url": config.to_media_url(c.output_path),
        "job": _job_brief(s, "render", c.id),
    }
    if full:
        thumbs = {}
        ids = {seg["clip_id"] for seg in tl.get("segments", [])}
        if ids:
            for clip in s.scalars(select(Clip).where(Clip.id.in_(ids))):
                thumbs[clip.id] = config.to_media_url(clip.thumb_path)
        out["timeline"] = tl
        out["clip_thumbs"] = thumbs
    return out


# ---------- 上传 ----------

def _save_upload(upload: UploadFile, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    ext = Path(upload.filename or "").suffix.lower()
    dst = folder / f"source{ext}"
    with dst.open("wb") as f:
        shutil.copyfileobj(upload.file, f, length=4 * 1024 * 1024)
    return dst


# ---------- 素材 ----------

@app.post("/api/videos")
def upload_videos(files: list[UploadFile] = File(...), s: Session = Depends(get_session)):
    created = []
    for up in files:
        ext = Path(up.filename or "").suffix.lower()
        if ext not in VIDEO_EXTS:
            raise HTTPException(400, f"不支持的视频格式: {up.filename}")
        v = Video(filename=up.filename, path="")
        s.add(v)
        s.flush()
        v.path = str(_save_upload(up, config.VIDEOS_DIR / str(v.id)))
        s.commit()
        jobs.enqueue("ingest", v.id)
        created.append(v.id)
    return {"ids": created}


@app.get("/api/videos")
def list_videos(s: Session = Depends(get_session)):
    counts = dict(s.execute(select(Clip.video_id, func.count()).group_by(Clip.video_id)).all())
    vids = s.scalars(select(Video).order_by(Video.id.desc())).all()
    return [video_out(s, v, counts.get(v.id, 0)) for v in vids]


@app.get("/api/videos/{video_id}")
def get_video(video_id: int, s: Session = Depends(get_session)):
    v = s.get(Video, video_id) or _404("素材")
    return {**video_out(s, v), "clips": [clip_out(c) for c in v.clips]}


@app.delete("/api/videos/{video_id}")
def delete_video(video_id: int, s: Session = Depends(get_session)):
    v = s.get(Video, video_id) or _404("素材")
    s.delete(v)
    s.commit()
    shutil.rmtree(config.VIDEOS_DIR / str(video_id), ignore_errors=True)
    return {"ok": True}


@app.post("/api/videos/{video_id}/reprocess")
def reprocess_video(video_id: int, s: Session = Depends(get_session)):
    v = s.get(Video, video_id) or _404("素材")
    v.status = "pending"
    s.commit()
    return {"job_id": jobs.enqueue("ingest", video_id)}


class ClipPatch(BaseModel):
    enabled: bool


@app.patch("/api/clips/{clip_id}")
def patch_clip(clip_id: int, body: ClipPatch, s: Session = Depends(get_session)):
    c = s.get(Clip, clip_id) or _404("片段")
    c.enabled = body.enabled
    return clip_out(c)


@app.get("/api/library/stats")
def library_stats(s: Session = Depends(get_session)):
    n_clips, total = s.execute(
        select(func.count(Clip.id), func.coalesce(func.sum(Clip.end - Clip.start), 0))
        .join(Video).where(Clip.enabled.is_(True), Video.status == "ready")
    ).one()
    return {"videos": s.scalar(select(func.count(Video.id))), "clips": n_clips,
            "clip_seconds": round(float(total), 1)}


# ---------- 音乐 ----------

@app.post("/api/music")
def upload_music(file: UploadFile = File(...), s: Session = Depends(get_session)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in AUDIO_EXTS:
        raise HTTPException(400, f"不支持的音频格式: {file.filename}")
    m = Music(filename=file.filename, path="")
    s.add(m)
    s.flush()
    m.path = str(_save_upload(file, config.MUSIC_DIR / str(m.id)))
    s.commit()
    jobs.enqueue("analyze", m.id)
    return {"id": m.id}


@app.get("/api/music")
def list_music(s: Session = Depends(get_session)):
    return [music_out(s, m) for m in s.scalars(select(Music).order_by(Music.id.desc()))]


@app.get("/api/music/{music_id}")
def get_music(music_id: int, s: Session = Depends(get_session)):
    m = s.get(Music, music_id) or _404("音乐")
    return music_out(s, m, full=True)


@app.delete("/api/music/{music_id}")
def delete_music(music_id: int, s: Session = Depends(get_session)):
    m = s.get(Music, music_id) or _404("音乐")
    comp_ids = s.scalars(select(Composition.id).where(Composition.music_id == music_id)).all()
    for cid in comp_ids:
        s.delete(s.get(Composition, cid))
    s.delete(m)
    s.commit()
    shutil.rmtree(config.MUSIC_DIR / str(music_id), ignore_errors=True)
    for cid in comp_ids:
        shutil.rmtree(config.RENDERS_DIR / str(cid), ignore_errors=True)
    return {"ok": True}


# ---------- 成片 ----------

class ComposeRequest(BaseModel):
    music_id: int
    settings: dict = {}
    render: bool = True


@app.get("/api/compose/defaults")
def compose_defaults():
    return default_settings()


@app.post("/api/compositions")
def create_composition(body: ComposeRequest, s: Session = Depends(get_session)):
    m = s.get(Music, body.music_id) or _404("音乐")
    if m.status != "ready":
        raise HTTPException(400, "音乐还没分析完")
    try:
        timeline = compose(m.analysis, pipeline.load_clip_pool(s), body.settings)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    c = Composition(music_id=m.id, settings=timeline["settings"], timeline=timeline)
    s.add(c)
    s.commit()
    if body.render:
        c.status = "queued"
        s.commit()
        jobs.enqueue("render", c.id)
    return comp_out(s, c)


@app.post("/api/compositions/{comp_id}/render")
def render_composition(comp_id: int, s: Session = Depends(get_session)):
    c = s.get(Composition, comp_id) or _404("成片")
    c.status = "queued"
    s.commit()
    return {"job_id": jobs.enqueue("render", c.id)}


@app.get("/api/compositions")
def list_compositions(s: Session = Depends(get_session)):
    return [comp_out(s, c) for c in s.scalars(select(Composition).order_by(Composition.id.desc()))]


@app.get("/api/compositions/{comp_id}")
def get_composition(comp_id: int, s: Session = Depends(get_session)):
    c = s.get(Composition, comp_id) or _404("成片")
    return comp_out(s, c, full=True)


@app.delete("/api/compositions/{comp_id}")
def delete_composition(comp_id: int, s: Session = Depends(get_session)):
    c = s.get(Composition, comp_id) or _404("成片")
    s.delete(c)
    s.commit()
    shutil.rmtree(config.RENDERS_DIR / str(comp_id), ignore_errors=True)
    return {"ok": True}


# ---------- 任务 ----------

@app.get("/api/jobs")
def list_jobs(active: bool = False, s: Session = Depends(get_session)):
    q = select(Job).order_by(Job.id.desc()).limit(100)
    if active:
        q = q.where(Job.status.in_(("queued", "running")))
    return [{"id": j.id, "kind": j.kind, "target_id": j.target_id, "status": j.status,
             "progress": j.progress, "message": j.message, "error": j.error}
            for j in s.scalars(q)]


def _404(what: str):
    raise HTTPException(404, f"{what}不存在")
