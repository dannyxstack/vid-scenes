"""根据时间线 JSON 用 FFmpeg 渲染成片：逐段编码 → concat 无损拼接 → 合成音轨。"""

import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from . import media

PARALLEL = 3


def _segment_cmd(seg: dict, src: str, out: Path, tl: dict) -> list[str]:
    w, h, fps = tl["width"], tl["height"], tl["fps"]
    pad = seg["frames"] / fps + 1.0
    vf = (
        f"fps={fps},"
        f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=bicubic,"
        f"crop={w}:{h},setsar=1,"
        f"tpad=stop_mode=clone:stop_duration={pad:.3f}"
    )
    return [
        "-ss", f"{seg['src_in']:.4f}", "-i", src, "-an",
        "-vf", vf, "-frames:v", str(seg["frames"]),
        *media.h264_args("high", gop=fps * 2), "-r", str(fps),
        str(out),
    ]


def render(
    timeline: dict,
    sources: dict[int, str],
    audio_path: str | Path,
    out_path: str | Path,
    work_dir: str | Path,
    report: Callable[[float, str], None] | None = None,
) -> None:
    """sources: video_id → 原视频路径。"""
    work = Path(work_dir)
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    segs = timeline["segments"]
    if not segs:
        raise ValueError("时间线为空")

    files = [work / f"seg_{s['index']:05d}.mp4" for s in segs]
    done = 0
    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        futures = [
            pool.submit(media.ffmpeg, *_segment_cmd(s, sources[s["video_id"]], f, timeline))
            for s, f in zip(segs, files)
        ]
        for fut in as_completed(futures):
            fut.result()
            done += 1
            if report:
                report(0.95 * done / len(segs), f"编码片段 {done}/{len(segs)}")

    list_file = work / "concat.txt"
    list_file.write_text(
        "".join(f"file '{f.resolve().as_posix()}'\n" for f in files), encoding="utf-8"
    )
    if report:
        report(0.96, "拼接与合成音轨")
    media.ffmpeg(
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-i", str(audio_path),
        "-map", "0:v", "-map", "1:a",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "320k",
        "-shortest", "-movflags", "+faststart",
        str(out_path),
    )
    shutil.rmtree(work, ignore_errors=True)
