import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("VIDSCENES_DATA", ROOT / "data")).resolve()
DB_PATH = DATA_DIR / "app.db"
VIDEOS_DIR = DATA_DIR / "videos"
MUSIC_DIR = DATA_DIR / "music"
RENDERS_DIR = DATA_DIR / "renders"
STATIC_DIR = Path(__file__).resolve().parent / "static"

# 代理文件高度（用于预览和分析）
PROXY_HEIGHT = 540
# 特征分析时每秒采样帧数
FEATURE_SAMPLE_FPS = 10
# 短于该时长的片段会并入相邻片段
MIN_CLIP_SECONDS = 0.5

# 不同能量等级的切点间隔（拍）
DEFAULT_CUT_BEATS = {"low": 8, "mid": 4, "high": 2}


def ensure_dirs() -> None:
    for d in (DATA_DIR, VIDEOS_DIR, MUSIC_DIR, RENDERS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def to_media_url(path: str | Path | None) -> str | None:
    """把 data 目录下的文件路径转换成 /media/... URL。"""
    if not path:
        return None
    rel = Path(path).resolve().relative_to(DATA_DIR)
    return "/media/" + rel.as_posix()
