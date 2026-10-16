from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _now() -> datetime:
    return datetime.now()


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(512))
    path: Mapped[str] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending/processing/ready/error
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    codec: Mapped[str | None] = mapped_column(String(64), nullable=True)
    proxy_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    thumb_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    clips: Mapped[list["Clip"]] = relationship(
        back_populates="video", cascade="all, delete-orphan", order_by="Clip.idx"
    )


class Clip(Base):
    __tablename__ = "clips"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    start: Mapped[float] = mapped_column(Float)  # 秒，相对原视频
    end: Mapped[float] = mapped_column(Float)
    thumb_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # 基础视觉特征（0..1 归一化，sharpness 为拉普拉斯方差原值）
    motion: Mapped[float | None] = mapped_column(Float, nullable=True)
    brightness: Mapped[float | None] = mapped_column(Float, nullable=True)
    saturation: Mapped[float | None] = mapped_column(Float, nullable=True)
    sharpness: Mapped[float | None] = mapped_column(Float, nullable=True)
    color_hex: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # 视觉节拍：最强峰值相对片段入点的偏移（秒）和强度（峰值/均值）
    peak_offset: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_strength: Mapped[float | None] = mapped_column(Float, nullable=True)
    # {"dt": 采样间隔秒, "v": [运动强度...]}，第一个采样点相对片段入点
    motion_curve: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    video: Mapped[Video] = relationship(back_populates="clips")

    @property
    def duration(self) -> float:
        return self.end - self.start


class Music(Base):
    __tablename__ = "music"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(512))
    path: Mapped[str] = mapped_column(String(1024))
    wav_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    bpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Composition(Base):
    __tablename__ = "compositions"

    id: Mapped[int] = mapped_column(primary_key=True)
    music_id: Mapped[int] = mapped_column(ForeignKey("music.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="composed")  # composed/rendering/done/error
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    settings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    timeline: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    music: Mapped[Music] = relationship()


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))  # ingest/analyze/render
    target_id: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="queued")  # queued/running/done/error
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
