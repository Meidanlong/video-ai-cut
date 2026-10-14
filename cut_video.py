#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按豆包的剪辑决策点自动裁剪成片（优化版）。
优化点：场景切点吸附 / 音频平滑 afade / 静默检测(可选)。
"""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent


def get_ffmpeg() -> str:
    exe = os.getenv("FFMPEG")
    if exe and Path(exe).exists():
        return exe
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


FFMPEG = get_ffmpeg()


def ts_to_sec(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def get_duration(video: str) -> float:
    out = subprocess.run([FFMPEG, "-i", video], capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", out.stderr)
    if not m:
        raise RuntimeError("无法解析视频时长: " + out.stderr[-300:])
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def detect_scene_cuts(video: str, threshold: float = 0.30) -> list:
    cmd = [FFMPEG, "-i", video,
           "-vf", f"select='gt(scene,{threshold})',showinfo",
           "-an", "-f", "null", "-"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    cuts = [float(t) for t in re.findall(r"pts_time:([\d.]+)", out.stderr)]
    return sorted(set(round(c, 3) for c in cuts if c > 0.5))


def snap(boundary: float, cuts: list, window: float = 1.5) -> float:
    best, best_d = boundary, window
    for c in cuts:
        d = abs(c - boundary)
        if d < best_d:
            best, best_d = c, d
    return best


def detect_silences(video: str, noise_db: float = -30, min_dur: float = 0.6) -> list:
    cmd = [FFMPEG, "-i", video,
           "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}",
           "-f", "null", "-"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start:\s*([\d.]+)", out.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([\d.]+)", out.stderr)]
    return [(round(s, 3), round(e, 3)) for s, e in zip(starts, ends) if e - s >= min_dur]


def subtract_ranges(duration: float, delete_ranges) -> list:
    keeps = [(0.0, duration)]
    for d_start, d_end in sorted(delete_ranges):
        new_keeps = []
        for s, e in keeps:
            if d_end <= s or d_start >= e:
                new_keeps.append((s, e))
            else:
                if s < d_start:
                    new_keeps.append((s, d_start))
                if d_end < e:
                    new_keeps.append((d_end, e))
        keeps = new_keeps
    return [(round(s, 3), round(e, 3)) for s, e in keeps if e - s > 0.3]


def load_delete_ranges(plan_path: Path):
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if "deletes" in plan:
        return [(ts_to_sec(p["start"]), ts_to_sec(p["end"])) for p in plan["deletes"]]
    return [(ts_to_sec(p["start"]), ts_to_sec(p["end"]))
            for p in plan["edit_points"] if p["type"] == "删除"]


def main():
    ap = argparse.ArgumentParser(description="按剪辑决策单自动裁剪成片(优化版)")
    ap.add_argument("video", help="原视频路径")
    ap.add_argument("output", nargs="?", help="输出路径")
    ap.add_argument("--plan", default=str(BASE / "out_video_understand" / "compact_result.json"))
    ap.add_argument("--scene-threshold", type=float, default=0.30)
    ap.add_argument("--snap-window", type=float, default=1.5)
    ap.add_argument("--silence", action="store_true", help="启用静默段检测并删除")
    ap.add_argument("--no-fade", action="store_true")
    args = ap.parse_args()

    video = args.video
    out_path = args.output or str(BASE / "成片_剪辑版.mp4")
    plan_path = Path(args.plan)
    if not plan_path.exists():
        plan_path = BASE / "out_video_understand" / "understand_result.json"

    delete_ranges = load_delete_ranges(plan_path)
    print(f"使用剪辑决策单: {plan_path}")
    if args.silence:
        sils = detect_silences(video)
        if sils:
            print(f"[静默] 检测到 {len(sils)} 段静默: {sils}")
            delete_ranges += sils

    duration = get_duration(video)
    keeps = subtract_ranges(duration, delete_ranges)
    print(f"视频总长 {duration:.1f}s")

    if args.snap_window > 0:
        cuts = detect_scene_cuts(video, args.scene_threshold)
        print(f"[场景] 检测到 {len(cuts)} 个镜头切点")
        snapped = []
        for s, e in keeps:
            ns, ne = snap(s, cuts, args.snap_window), snap(e, cuts, args.snap_window)
            if ne - ns > 0.3:
                snapped.append((ns, ne))
        keeps = snapped
    print(f"保留片段: {keeps}")

    fade_audio = not args.no_fade
    n = len(keeps)
    parts, filters = [], []
    for i, (s, e) in enumerate(keeps):
        dur = e - s
        parts.append(f"[0:v]trim=start={s}:end={e},setpts=PTS-STARTPTS[v{i}]")
        if fade_audio and dur > 0.3:
            fade_out_st = max(0.0, dur - 0.06)
            parts.append(f"[0:a]atrim=start={s}:end={e},asetpts=PTS-STARTPTS,"
                         f"afade=t=in:d=0.05,afade=t=out:st={fade_out_st:.3f}:d=0.05[a{i}]")
        else:
            parts.append(f"[0:a]atrim=start={s}:end={e},asetpts=PTS-STARTPTS[a{i}]")
        filters.append(f"[v{i}][a{i}]")
    fc = ";".join(parts) + ";" + "".join(filters) + f"concat=n={n}:v=1:a=1[outv][outa]"
    cmd = [FFMPEG, "-y", "-i", video, "-filter_complex", fc,
           "-map", "[outv]", "-map", "[outa]",
           "-c:v", "libx264", "-preset", "fast", "-crf", "20",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out_path]
    print("运行 ffmpeg ...")
    subprocess.run(cmd, check=True)
    print(f"成片已生成: {out_path}")


if __name__ == "__main__":
    main()
