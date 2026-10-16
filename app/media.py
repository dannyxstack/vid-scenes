"""FFmpeg / ffprobe 封装。"""

import functools
import json
import subprocess
from fractions import Fraction
from pathlib import Path

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

# Windows 下不弹出控制台窗口
_CREATE_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class MediaError(RuntimeError):
    pass


def run(args: list[str]) -> str:
    proc = subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=_CREATE_FLAGS,
    )
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise MediaError(f"{Path(args[0]).name} 失败 (code {proc.returncode}):\n{tail}")
    return proc.stdout


def ffmpeg(*args: str) -> str:
    return run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args])


def _parse_rate(rate: str | None) -> float | None:
    if not rate or rate in ("0/0", "0"):
        return None
    try:
        return float(Fraction(rate))
    except (ValueError, ZeroDivisionError):
        return None


def probe(path: str | Path) -> dict:
    out = run([FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    data = json.loads(out)
    fmt = data.get("format", {})
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    duration = float(fmt.get("duration") or (video or audio or {}).get("duration") or 0)
    info = {"duration": duration, "has_video": video is not None, "has_audio": audio is not None}
    if video:
        info.update(
            width=int(video.get("width") or 0),
            height=int(video.get("height") or 0),
            fps=_parse_rate(video.get("avg_frame_rate")) or _parse_rate(video.get("r_frame_rate")),
            codec=video.get("codec_name"),
        )
    return info


@functools.lru_cache(maxsize=1)
def has_nvenc() -> bool:
    try:
        ffmpeg("-f", "lavfi", "-i", "color=black:s=256x256:d=0.1", "-frames:v", "1",
               "-c:v", "h264_nvenc", "-f", "null", "-")
        return True
    except (MediaError, FileNotFoundError):
        return False


def h264_args(quality: str = "high", gop: int | None = None) -> list[str]:
    """H.264 编码参数：优先 NVENC，不可用时退回 libx264。quality: high | proxy。"""
    if has_nvenc():
        cq = "19" if quality == "high" else "30"
        args = ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", cq, "-b:v", "0"]
    else:
        crf = "18" if quality == "high" else "28"
        preset = "medium" if quality == "high" else "veryfast"
        args = ["-c:v", "libx264", "-preset", preset, "-crf", crf]
    if gop:
        args += ["-g", str(gop)]
    return args + ["-pix_fmt", "yuv420p"]


def make_proxy(src: str | Path, dst: str | Path, height: int) -> None:
    ffmpeg(
        "-i", str(src),
        "-vf", f"scale=-2:'min({height},ih)'",
        *h264_args("proxy", gop=30),
        "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart",
        str(dst),
    )


def thumbnail(src: str | Path, t: float, dst: str | Path, width: int = 320) -> None:
    ffmpeg("-ss", f"{max(0.0, t):.3f}", "-i", str(src), "-frames:v", "1",
           "-vf", f"scale={width}:-2", "-q:v", "4", str(dst))


def to_wav(src: str | Path, dst: str | Path, sr: int = 44100) -> None:
    ffmpeg("-i", str(src), "-vn", "-ac", "2", "-ar", str(sr), "-c:a", "pcm_s16le", str(dst))
