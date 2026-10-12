#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 SRT 字幕转成带设计样式的 ASS 字幕。
用法: python srt_to_ass.py <input.srt> <output.ass> [--fontsize 80]
"""
import argparse
import re
from pathlib import Path

# 根据视频风格(生活记录/暖调/轻松)设计的字幕样式
# 竖屏 1080x1920，大字号、暖白字、深棕描边、底部居中
STYLE_TEMPLATE = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{fontname},{fontsize},&H00E5F6FF,&H000000FF,&H0014243A,&H96000000,1,0,0,0,100,100,0,0,1,5,2,2,120,120,{marginv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def srt_time_to_ass(t: str) -> str:
    hh, mm, rest = t.split(":")
    ss, ms = rest.split(",")
    cs = int(ms) // 10  # 毫秒 -> 厘秒
    return f"{int(hh)}:{mm}:{ss}.{cs:02d}"


def parse_srt(text: str):
    blocks = re.split(r"\n\s*\n", text.strip())
    segs = []
    for b in blocks:
        lines = [l.strip() for l in b.splitlines() if l.strip()]
        if not lines:
            continue
        time_line = next((l for l in lines if "-->" in l), None)
        if not time_line:
            continue
        m = re.match(r"(\S+)\s*-->\s*(\S+)", time_line)
        if not m:
            continue
        start, end = m.group(1), m.group(2)
        text = "".join(l for l in lines if "-->" not in l and not l.isdigit())
        segs.append({"start": start, "end": end, "text": text})
    return segs


def build_ass(segs, fontname, fontsize, marginv):
    header = STYLE_TEMPLATE.format(fontname=fontname, fontsize=fontsize, marginv=marginv)
    lines = [header]
    # 每句直接使用转写返回的真实起止时间戳，保证字幕与语音严格对齐；
    # 过长的句子由 ASS WrapStyle=0 自动换行，不做时间重分配。
    for seg in segs:
        lines.append(
            f"Dialogue: 0,{srt_time_to_ass(seg['start'])},{srt_time_to_ass(seg['end'])},"
            f"Default,,0,0,0,,{seg['text'].strip()}"
        )
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("srt", help="输入 SRT 路径")
    ap.add_argument("out", help="输出 ASS 路径")
    ap.add_argument("--fontname", default="PingFang SC", help="字体名(默认苹方)")
    ap.add_argument("--fontsize", type=int, default=80, help="字号(竖屏1080基准)")
    ap.add_argument("--marginv", type=int, default=170, help="底部边距")
    args = ap.parse_args()

    segs = parse_srt(Path(args.srt).read_text(encoding="utf-8"))
    ass = build_ass(segs, args.fontname, args.fontsize, args.marginv)
    Path(args.out).write_text(ass, encoding="utf-8")
    print(f"ASS 已生成: {args.out}（{len(segs)} 句）")


if __name__ == "__main__":
    main()
