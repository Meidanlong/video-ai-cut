#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
短视频成品合成脚本：降噪 + 按决策单裁剪 + 背景音乐混音 + 字幕烧录(可自定义字体)。

流程：
  Step1 字幕烧录：原视频 + ASS 字幕 -> 带字幕临时视频(音频不动)
  Step2 成品合成：临时视频按决策单裁剪保留段，每段音频做 afftdn 降噪 + afade 平滑，
        再与 BGM 混音 -> 最终成片

用法:
  python final_cut.py <原视频> [输出] [--plan 决策单] [--srt 字幕] [--bgm 音乐]
  示例:
  python final_cut.py 素材.mp4 成片.mp4
  python final_cut.py 素材.mp4 成片.mp4 --no-bgm --no-noise
"""
import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent


def get_ffmpeg() -> str:
    exe = os.getenv("FFMPEG")
    if exe and Path(exe).exists():
        return exe
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


FFMPEG = get_ffmpeg()
FONTS_DIR = "/System/Library/Fonts:/Library/Fonts:/System/Library/Fonts/Supplemental"


def ts_to_sec(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def get_duration(video: str) -> float:
    out = subprocess.run([FFMPEG, "-i", video], capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", out.stderr)
    if not m:
        raise RuntimeError("无法解析时长: " + out.stderr[-300:])
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def load_delete_ranges(plan_path: Path):
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if "deletes" in plan:
        return [(ts_to_sec(p["start"]), ts_to_sec(p["end"])) for p in plan["deletes"]]
    return [(ts_to_sec(p["start"]), ts_to_sec(p["end"]))
            for p in plan["edit_points"] if p["type"] == "删除"]


def subtract_ranges(duration: float, delete_ranges) -> list:
    keeps = [(0.0, duration)]
    for ds, de in sorted(delete_ranges):
        nk = []
        for s, e in keeps:
            if de <= s or ds >= e:
                nk.append((s, e))
            else:
                if s < ds:
                    nk.append((s, ds))
                if de < e:
                    nk.append((de, e))
        keeps = nk
    return [(round(s, 3), round(e, 3)) for s, e in keeps if e - s > 0.3]


def main():
    ap = argparse.ArgumentParser(description="短视频成品合成(降噪+BGM+字幕)")
    ap.add_argument("video", help="原视频路径")
    ap.add_argument("output", nargs="?", help="输出路径")
    ap.add_argument("--plan", default=str(BASE / "out_video_understand" / "compact_result.json"))
    ap.add_argument("--srt", default=str(BASE / "out_video_understand" / "transcript.srt"))
    ap.add_argument("--bgm", default=str(BASE / "bgm_happy_days.mp3"))
    ap.add_argument("--no-bgm", action="store_true", help="不加背景音乐")
    ap.add_argument("--no-noise", action="store_true", help="不降噪")
    ap.add_argument("--bgm-volume", type=float, default=0.26, help="BGM音量(0-1)")
    ap.add_argument("--fontsize", type=int, default=80)
    ap.add_argument("--fontname", default="PingFang SC")
    args = ap.parse_args()

    video = args.video
    out_path = args.output or str(BASE / "成片_成品版.mp4")
    plan = Path(args.plan)
    srt = Path(args.srt)

    from srt_to_ass import parse_srt, build_ass
    ass_tmp = Path(tempfile.mkdtemp()) / "subtitle.ass"
    segs = parse_srt(srt.read_text(encoding="utf-8"))
    ass_tmp.write_text(build_ass(segs, args.fontname, args.fontsize, 170), encoding="utf-8")
    print(f"[字幕] {len(segs)} 句 -> ASS 样式(Fontname={args.fontname}, Size={args.fontsize})")

    subbed = Path(tempfile.mkdtemp()) / "subbed.mp4"
    esc_ass = str(ass_tmp).replace("\\", "\\\\").replace(":", "\\:")
    sub_cmd = [FFMPEG, "-y", "-i", video,
               "-vf", f"subtitles='{esc_ass}'",
               "-c:v", "libx264", "-preset", "fast", "-crf", "18",
               "-c:a", "copy", "-movflags", "+faststart", str(subbed)]
    print("[1/2] 烧录字幕...")
    subprocess.run(sub_cmd, check=True, capture_output=True)

    delete_ranges = load_delete_ranges(plan)
    duration = get_duration(str(subbed))
    keeps = subtract_ranges(duration, delete_ranges)
    print(f"[2/2] 裁剪 {len(keeps)} 段 + 降噪 + BGM")

    n = len(keeps)
    parts, filters = [], []
    for i, (s, e) in enumerate(keeps):
        dur = e - s
        parts.append(f"[0:v]trim=start={s}:end={e},setpts=PTS-STARTPTS[v{i}]")
        if args.no_noise:
            audio_chain = f"atrim=start={s}:end={e},asetpts=PTS-STARTPTS"
        else:
            audio_chain = f"atrim=start={s}:end={e},asetpts=PTS-STARTPTS,afftdn=nr=12:nf=-25"
        if dur > 0.3:
            fo = max(0.0, dur - 0.06)
            audio_chain += f",afade=t=in:d=0.05,afade=t=out:st={fo:.3f}:d=0.05"
        parts.append(f"[0:a]{audio_chain}[a{i}]")
        filters.append(f"[v{i}][a{i}]")
    concat_in = "".join(filters) + f"concat=n={n}:v=1:a=1[convv][conva]"

    inputs = [str(subbed)]
    if not args.no_bgm and Path(args.bgm).exists():
        inputs.append(args.bgm)

    if not args.no_bgm and Path(args.bgm).exists():
        bgm_chain = (f"aloop=loop=-1:size=2e9,atrim=0:{duration:.3f},"
                     f"volume={args.bgm_volume},afade=t=in:d=1.5,afade=t=out:st={max(0.0, duration-2.5):.3f}:d=2.5")
        parts.append(f"[1:a]{bgm_chain}[bgm]")
        fc = (";".join(parts) + ";" + concat_in +
              f";[conva][bgm]amix=inputs=2:duration=first:dropout_transition=3:normalize=0[aout]")
        map_v, map_a = "[convv]", "[aout]"
    else:
        fc = ";".join(parts) + ";" + concat_in
        map_v, map_a = "[convv]", "[conva]"

    cmd = [FFMPEG, "-y", *sum((["-i", i] for i in inputs), []),
           "-filter_complex", fc, "-map", map_v, "-map", map_a,
           "-c:v", "libx264", "-preset", "fast", "-crf", "20",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out_path]
    subprocess.run(cmd, check=True)
    print(f"成品已生成: {out_path}")


if __name__ == "__main__":
    main()
