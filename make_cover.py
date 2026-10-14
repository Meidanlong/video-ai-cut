#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
短视频封面海报生成：真帧主图 + 渐变遮罩 + 大字标题 + 可选 AI 装饰。
输出 3:4 (1080x1440) 和/或 9:16 (1080x1920) 封面。
默认在主角出镜时段内按量化指标选"形象最佳"帧（--lead），支持 --frame 手动兜底。
"""
import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

BASE = Path(__file__).resolve().parent


def get_ffmpeg() -> str:
    exe = os.getenv("FFMPEG")
    if exe and Path(exe).exists():
        return exe
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def get_font_path(name: str) -> str:
    candidates = ["/System/Library/Fonts/", "/System/Library/Fonts/Supplemental/",
                  "/Library/Fonts/", "/Library/Fonts/Supplemental/"]
    aliases = {"PingFang SC": "STHeiti Medium.ttc", "PingFang": "STHeiti Medium.ttc",
               "Heiti SC": "STHeiti Medium.ttc", "Heiti": "STHeiti Medium.ttc",
               "Songti SC": "Songti.ttc", "Songti": "Songti.ttc",
               "Hiragino Sans GB": "Hiragino Sans GB.ttc", "STKaiti": "Kaiti.ttc",
               "Kaiti": "Kaiti.ttc", "Arial": "Arial.ttf", "Helvetica": "Helvetica.ttc"}
    target = aliases.get(name, name + ".ttf")
    for base in candidates:
        p = Path(base) / target
        if p.exists():
            return str(p)
    for base in candidates:
        p = Path(base) / "STHeiti Medium.ttc"
        if p.exists():
            return str(p)
    raise FileNotFoundError(f"找不到字体 {name}")


def extract_frame(video: str, t: float, out_png: str):
    ff = get_ffmpeg()
    subprocess.run([ff, "-y", "-ss", f"{t:.3f}", "-i", video,
                    "-frames:v", "1", "-q:v", "2", out_png],
                   check=True, capture_output=True)


def probe_duration(video: str) -> float:
    try:
        ff = get_ffmpeg()
        r = subprocess.run([ff, "-i", video], capture_output=True, text=True)
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", r.stderr or "")
        if not m:
            return 0.0
        h, mi, s = m.groups()
        return int(h) * 3600 + int(mi) * 60 + float(s)
    except Exception:
        return 0.0


def pick_cover_time(video: str = None, plan=None) -> float:
    t = None
    try:
        ems = json.loads((BASE / "out_video_understand" / "emotions_result.json").read_text(encoding="utf-8"))
        result_pts = [p["time"] for p in ems["points"] if p["emotion"] == "结果公布"]
        t = max(result_pts) if result_pts else ems["points"][-1]["time"]
    except Exception:
        t = 1.0
    if video:
        dur = probe_duration(video)
        if dur > 0 and t >= dur:
            clamped = max(0.0, dur - 0.5)
            t = clamped
    return t


def pick_lead_frame(video: str, lead_result: str, step: float):
    try:
        import identify_lead as il
    except ImportError:
        print("[lead] 无法导入 identify_lead，跳过主角选帧")
        return None, None
    p = Path(lead_result)
    if not p.exists():
        print(f"[lead] 未找到 {p}，跳过主角选帧（先跑 identify_lead.py）")
        return None, None
    try:
        lead = json.loads(p.read_text(encoding="utf-8"))
        t0, t1 = float(lead["appearance_start"]), float(lead["appearance_end"])
        name = lead.get("lead_name", "主角")
    except Exception as e:
        print(f"[lead] 读取 {p} 失败: {e}")
        return None, None
    if t1 <= t0:
        print(f"[lead] 主角时段无效({t0}~{t1})，跳过主角选帧")
        return None, None
    detector = il.get_face_detector()
    det_name = "cv2/haarcascade" if detector else "fallback(无cv2): 锚定相似度+清晰度+构图+曝光"
    print(f"[lead] 主角={name} 出镜时段={t0:.2f}s~{t1:.2f}s  检测={det_name}")
    with tempfile.TemporaryDirectory() as tmp:
        anchor = os.path.join(tmp, "anchor.png")
        try:
            extract_frame(video, t0, anchor)
            ref_sig = il.signature(anchor)
        except Exception as e:
            print(f"[lead] 锚定帧({t0:.2f}s)抽帧失败: {e}，跳过主角选帧")
            return None, None
        best = None
        t = t0
        while t <= t1 + 1e-6:
            png = os.path.join(tmp, "cand.png")
            try:
                extract_frame(video, t, png)
            except Exception:
                t += step
                continue
            m = il.frame_metrics(png, detector)
            sim = il.similarity(ref_sig, il.signature(png))
            sharpness = min(math.log1p(m["sharpness"]) / math.log1p(2000.0), 1.0)
            center = min(max(m["center_energy"], 0.0), 1.5) / 1.5
            expo = max(0.0, 1.0 - m["exposure_delta"] / 90.0)
            parts = [(0.44, sim), (0.24, sharpness), (0.14, center), (0.12, expo)]
            if m["face_ratio"] is not None:
                parts.append((0.06, min(max(m["face_ratio"] / 0.18, 0.0), 1.0)))
            wsum = sum(w for w, _ in parts)
            score = sum(w * v for w, v in parts) / wsum
            cand = (score, round(t, 2), dict(m, anchor_sim=round(sim, 4),
                                             sharpness_n=round(sharpness, 4),
                                             center_n=round(center, 4)))
            if best is None or cand[0] > best[0]:
                best = cand
            t += step
        if best is None:
            print("[lead] 主角时段内未抽到帧，跳过主角选帧")
            return None, None
        score, t, info = best
        print(f"[lead] 选中 {t:.2f}s 得分={score:.4f}")
        keep = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        keep.close()
        extract_frame(video, t, keep.name)
        Image.open(keep.name).convert("RGB").save(keep.name, "PNG")
    return keep.name, {"time": t, "score": round(score, 4), "metrics": info,
                       "lead_name": name, "band": [t0, t1]}


def build_cover(frame_png: str, title: str, subtitle: str,
                fontname: str, fontsize: int, width: int, height: int,
                out_png: str):
    base = Image.open(frame_png).convert("RGB")
    scale = max(width / base.width, height / base.height)
    base = base.resize((int(base.width * scale), int(base.height * scale)), Image.LANCZOS)
    left = (base.width - width) // 2
    top = (base.height - height) // 2
    base = base.crop((left, top, left + width, top + height))
    base = base.filter(ImageFilter.GaussianBlur(1))
    base = base.resize((width, height), Image.LANCZOS)
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    grad_h = int(height * 0.62)
    for i in range(grad_h):
        alpha = int(210 * (i / grad_h) ** 1.4)
        od.line([(0, height - grad_h + i), (width, height - grad_h + i)],
                fill=(0, 0, 0, alpha))
    base = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(base)
    accent = (255, 193, 84)
    draw.rectangle([0, 0, width, 8], fill=accent)
    font_title = ImageFont.truetype(get_font_path(fontname), fontsize)
    font_sub = ImageFont.truetype(get_font_path(fontname), max(34, fontsize // 3))
    margin = 48
    if subtitle:
        draw.text((margin, height - fontsize * 1.0 - 40), subtitle,
                  font=font_sub, fill=(230, 235, 245, 255))
        draw.text((margin, height - fontsize * 0.4 - 40), "· · ·",
                  font=font_sub, fill=accent)
    import textwrap
    max_chars = max(4, (width - margin * 2) // fontsize)
    lines = textwrap.wrap(title, width=max_chars)
    y = height - fontsize * len(lines) - 28
    for ln in lines:
        draw.text((margin - 2, y - 2), ln, font=font_title, fill=(0, 0, 0, 255))
        draw.text((margin + 2, y + 2), ln, font=font_title, fill=(0, 0, 0, 255))
        draw.text((margin, y), ln, font=font_title, fill=(255, 255, 255, 255))
        y += fontsize + 6
    base.save(out_png, "PNG")
    print(f"封面已生成: {out_png} ({width}x{height})")
    return out_png


def main():
    ap = argparse.ArgumentParser(description="短视频封面海报生成")
    ap.add_argument("video", help="原视频路径")
    ap.add_argument("--title", default="中秋博饼\n开仓放粮", help="标题(可含换行)")
    ap.add_argument("--subtitle", default="厦门·博饼", help="副标题")
    ap.add_argument("--frame", type=float, default=None, help="抽帧时间(原视频秒)，手动兜底")
    ap.add_argument("--lead", dest="lead", action="store_true", default=True,
                    help="主角选帧：在主角出镜时段内选形象最佳帧（默认启用）")
    ap.add_argument("--no-lead", dest="lead", action="store_false",
                    help="关闭主角选帧，回到旧逻辑（情绪高潮帧）")
    ap.add_argument("--lead-result", default=str(BASE / "out_video_understand" / "lead_result.json"),
                    help="identify_lead.py 输出的主角结果 json")
    ap.add_argument("--step", type=float, default=0.5, help="主角选帧抽帧步长(秒)")
    ap.add_argument("--size", default="both", choices=["both", "34", "916"], help="封面尺寸")
    ap.add_argument("--fontname", default="PingFang SC", help="字体名")
    ap.add_argument("--fontsize", type=int, default=110, help="标题字号(竖屏1080基准)")
    ap.add_argument("--out", default="封面海报", help="输出文件名前缀")
    args = ap.parse_args()
    lead_info = None
    if args.frame is not None:
        t = args.frame
        print(f"选帧时间(原视频): {t:.2f}s  [来源: --frame 手动指定]")
    elif args.lead:
        frame_png, lead_info = pick_lead_frame(args.video, args.lead_result, args.step)
        if frame_png is None:
            t = pick_cover_time(args.video)
        else:
            t = lead_info["time"]
    else:
        t = pick_cover_time(args.video)
    with tempfile.TemporaryDirectory() as tmp:
        if lead_info is not None:
            frame = frame_png
        else:
            frame = os.path.join(tmp, "frame.jpg")
            extract_frame(args.video, t, frame)
        specs = []
        if args.size in ("both", "34"):
            specs.append((1080, 1440, "34"))
        if args.size in ("both", "916"):
            specs.append((1080, 1920, "916"))
        for w, h, tag in specs:
            out = f"{args.out}_{tag}.png"
            build_cover(frame, args.title, args.subtitle,
                        args.fontname, args.fontsize, w, h, out)
    if lead_info is not None and os.path.exists(frame_png):
        os.unlink(frame_png)


if __name__ == "__main__":
    main()
