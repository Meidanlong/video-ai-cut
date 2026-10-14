#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
短视频贴图功能：按理解层情绪点，在成片合适位置叠加贴图（文字气泡/表情/自定义PNG）。

用法:
  python add_overlays.py <成片> <输出>
      [--plan 决策单] [--emotions emotions_result.json]
      [--sticker-dir 目录] [--size 气泡字号] [--show 显示时长]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).resolve().parent


def get_ffmpeg() -> str:
    exe = os.getenv("FFMPEG")
    if exe and Path(exe).exists():
        return exe
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def get_font_path(name: str) -> str:
    aliases = {"PingFang SC": "STHeiti Medium.ttc", "PingFang": "STHeiti Medium.ttc",
               "Heiti": "STHeiti Medium.ttc", "Songti SC": "Songti.ttc"}
    target = aliases.get(name, name + ".ttf")
    for base in ["/System/Library/Fonts/", "/System/Library/Fonts/Supplemental/", "/Library/Fonts/"]:
        p = Path(base) / target
        if p.exists():
            return str(p)
    return str(Path("/System/Library/Fonts/STHeiti Medium.ttc"))


def make_bubble(text: str, size: int, color, scale: float = 1.0) -> Image:
    font = ImageFont.truetype(get_font_path("PingFang SC"), int(size * scale))
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    box = tmp.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    pad = int(size * 0.55)
    w, h = tw + pad * 2, th + pad * 2
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, w - 2, h - 2], radius=h // 2, fill=color,
                        outline=(0, 0, 0, 180), width=max(2, size // 20))
    d.polygon([(w // 2 - 14, h - 6), (w // 2 + 14, h - 6), (w // 2, h + 16)], fill=color)
    d.text((pad, pad - box[1]), text, font=font, fill=(255, 255, 255, 255))
    return img


def region_pos(region: str, img_w: int, img_h: int, vw: int, vh: int, margin=60):
    bw, bh = img_w, img_h
    if region == "top-right":
        return vw - bw - margin, margin
    if region == "top-left":
        return margin, margin
    if region == "bottom-center":
        return (vw - bw) // 2, int(vh * 0.30)
    if region == "center":
        return (vw - bw) // 2, (vh - bh) // 2
    return vw - bw - margin, margin


def load_points(emotions_path: Path, plan_path: Path):
    from cut_time import kept_ranges, src_to_dst
    keeps = kept_ranges(plan_path)
    ems = json.loads(emotions_path.read_text(encoding="utf-8"))
    points = []
    for p in ems["points"]:
        dst = src_to_dst(p["time"], keeps)
        if dst is not None:
            points.append({**p, "dst_time": dst})
    return points


def main():
    ap = argparse.ArgumentParser(description="短视频贴图叠加")
    ap.add_argument("video", help="成片视频路径")
    ap.add_argument("output", help="输出视频路径")
    ap.add_argument("--plan", default=str(BASE / "out_video_understand" / "compact_result.json"))
    ap.add_argument("--emotions", default=str(BASE / "out_video_understand" / "emotions_result.json"))
    ap.add_argument("--sticker-dir", default="", help="自定义贴图目录")
    ap.add_argument("--fontsize", type=int, default=52, help="气泡字号")
    ap.add_argument("--show", type=float, default=1.0, help="每个贴图显示秒数")
    ap.add_argument("--fade", type=float, default=0.15, help="淡入淡出秒数")
    args = ap.parse_args()

    ff = get_ffmpeg()
    probe = subprocess.run([ff, "-i", args.video], capture_output=True, text=True)
    m = re.search(r"(\d{3,4})x(\d{3,4})", probe.stderr)
    vw, vh = (int(m.group(1)), int(m.group(2))) if m else (1080, 1920)
    md = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", probe.stderr)
    duration = (int(md.group(1)) * 3600 + int(md.group(2)) * 60 + float(md.group(3))) if md else 139.0
    print(f"成片分辨率 {vw}x{vh}, 时长 {duration:.2f}s")

    points = load_points(Path(args.emotions), Path(args.plan))
    print(f"情绪点 {len(points)} 个（已映射成片时间）")

    sticker_dir = Path(args.sticker_dir) if args.sticker_dir else None
    emotion_text = {"结果公布": "结果公布", "关键动作": "掷骰时刻"}
    emotion_color = {"结果公布": (220, 53, 69, 230), "关键动作": (255, 193, 84, 235)}

    tmp = Path(tempfile.mkdtemp())
    inputs = ["-i", args.video]
    parts = []

    for i, p in enumerate(points):
        t = p["dst_time"]
        if sticker_dir and sticker_dir.exists():
            fname = emotion_text.get(p["emotion"], p["emotion"]) + ".png"
            sticker = sticker_dir / fname
            img = Image.open(sticker).convert("RGBA") if sticker.exists() else None
        else:
            img = None
        if img is None:
            img = make_bubble(emotion_text.get(p["emotion"], p["emotion"]),
                              args.fontsize, emotion_color.get(p["emotion"], (80, 80, 80, 230)))
        target_w = int(vw * 0.28)
        if img.width != target_w:
            ratio = target_w / img.width
            img = img.resize((target_w, int(img.height * ratio)), Image.LANCZOS)
        png = tmp / f"st{i}.png"
        img.save(png)
        inputs += ["-loop", "1", "-framerate", "30", "-i", str(png)]
        x, y = region_pos(p["region"], img.width, img.height, vw, vh)
        start = max(0.0, t - args.show / 2)
        dur = args.show
        ov_filter = (f"[{i+1}:v]format=rgba,"
                     f"fade=t=in:st={start:.2f}:d={args.fade:.2f}:alpha=1,"
                     f"fade=t=out:st={start+dur-args.fade:.2f}:d={args.fade:.2f}:alpha=1"
                     f"[ov{i}];")
        parts.append(ov_filter)
        enable = f"between(t,{start:.2f},{start+dur:.2f})"
        if i == 0:
            parts.append(f"[0:v][ov{i}]overlay=x={x}:y={y}:enable='{enable}'[v{i+1}];")
        else:
            parts.append(f"[v{i}][ov{i}]overlay=x={x}:y={y}:enable='{enable}'[v{i+1}];")

    fc = "".join(parts)
    v_out = f"[v{len(points)}]"
    cmd = [ff, "-y", *inputs, "-filter_complex", fc, "-map", v_out, "-map", "0:a",
           "-c:v", "libx264", "-preset", "fast", "-crf", "20",
           "-c:a", "copy", "-t", f"{duration:.3f}", "-movflags", "+faststart", args.output]
    print("运行 ffmpeg 叠加贴图(loop+shortest)...")
    subprocess.run(cmd, check=True)
    print(f"贴图版已生成: {args.output}")


if __name__ == "__main__":
    main()
