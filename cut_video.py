#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按豆包的剪辑决策点自动裁剪成片。
读取剪辑决策单(compact_result.json 的 deletes 或 understand_result.json 的 edit_points)，
删除指定区间，把其余片段用 ffmpeg trim+concat 拼接输出。

用法: python cut_video.py <原视频路径> [输出路径] [--plan 决策单路径]
"""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent


def get_ffmpeg() -> str:
    """定位 ffmpeg：优先环境变量 FFMPEG，否则用 imageio-ffmpeg 预编译二进制。"""
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
    """用 ffmpeg -i 输出的 Duration 解析总时长(秒)。"""
    out = subprocess.run([FFMPEG, "-i", video], capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", out.stderr)
    if not m:
        raise RuntimeError("无法解析视频时长: " + out.stderr[-300:])
    h, mm, ss = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return h * 3600 + mm * 60 + ss


def build_keep_segments(duration: float, delete_ranges):
    """从完整时长中减去删除区间，得到保留片段列表 [(start, end), ...]。"""
    keeps = [(0.0, duration)]
    for d_start, d_end in sorted(delete_ranges):
        new_keeps = []
        for s, e in keeps:
            if d_end <= s or d_start >= e:      # 不相交
                new_keeps.append((s, e))
            else:                                # 有重叠 -> 拆成前后两段
                if s < d_start:
                    new_keeps.append((s, d_start))
                if d_end < e:
                    new_keeps.append((d_end, e))
        keeps = new_keeps
    return [(round(s, 3), round(e, 3)) for s, e in keeps if e - s > 0.3]


def load_delete_ranges(plan_path: Path):
    """读取剪辑决策单，兼容两种结构。返回删除区间列表 [(start, end)]。"""
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if "deletes" in plan:
        return [(ts_to_sec(p["start"]), ts_to_sec(p["end"])) for p in plan["deletes"]]
    return [
        (ts_to_sec(p["start"]), ts_to_sec(p["end"]))
        for p in plan["edit_points"] if p["type"] == "删除"
    ]


def main():
    ap = argparse.ArgumentParser(description="按剪辑决策单自动裁剪成片")
    ap.add_argument("video", help="原视频路径")
    ap.add_argument("output", nargs="?", help="输出路径")
    ap.add_argument("--plan", default=str(BASE / "out_video_understand" / "compact_result.json"),
                    help="剪辑决策单 JSON 路径")
    args = ap.parse_args()

    video = args.video
    out_path = args.output or str(BASE / "成片_剪辑版.mp4")
    plan_path = Path(args.plan)
    if not plan_path.exists():
        plan_path = BASE / "out_video_understand" / "understand_result.json"

    delete_ranges = load_delete_ranges(plan_path)
    print(f"使用剪辑决策单: {plan_path}")

    duration = get_duration(video)
    keeps = build_keep_segments(duration, delete_ranges)
    print(f"视频总长 {duration:.1f}s")
    print(f"删除区间: {delete_ranges}")
    print(f"保留片段: {keeps}")

    n = len(keeps)
    parts, filters = [], []
    for i, (s, e) in enumerate(keeps):
        parts += [f"[0:v]trim=start={s}:end={e},setpts=PTS-STARTPTS[v{i}]",
                  f"[0:a]atrim=start={s}:end={e},asetpts=PTS-STARTPTS[a{i}]"]
        filters += [f"[v{i}][a{i}]"]
    fc = ";".join(parts) + ";" + "".join(filters) + f"concat=n={n}:v=1:a=1[outv][outa]"

    cmd = [FFMPEG, "-y", "-i", video, "-filter_complex", fc,
           "-map", "[outv]", "-map", "[outa]",
           "-c:v", "libx264", "-preset", "fast", "-crf", "20",
           "-c:a", "aac", "-b:a", "192k",
           "-movflags", "+faststart", out_path]
    print("运行:", " ".join(cmd[:12]), "...")
    subprocess.run(cmd, check=True)
    print(f"成片已生成: {out_path}")


if __name__ == "__main__":
    main()
