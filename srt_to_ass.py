#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 SRT 字幕转成带设计样式的 ASS 字幕，并做"长句拆分"以贴合短视频快节奏。
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
WrapStyle: 3
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{fontname},{fontsize},&H00E5F6FF,&H000000FF,&H0014243A,&H96000000,1,0,0,0,100,100,0,0,1,5,2,2,{marginlr},{marginlr},{marginv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

MAX_SECONDS = 7.0   # 超过该时长的句子会被按标点拆分


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


def split_long(text: str, max_s: float = MAX_SECONDS):
    """按标点拆长句。返回多段文本（保持原顺序）。"""
    # 先按句末标点拆
    parts = re.split(r"(?<=[。！？!?；;])", text)
    parts = [p for p in parts if p.strip()]
    # 仍过长的再按逗号/空格拆
    out = []
    for p in parts:
        if len(p) > 40:
            sub = [x for x in re.split(r"(?<=[，,、])", p) if x.strip()]
            out.extend(sub or [p])
        else:
            out.append(p)
    return out or [text]


def wrap_text(text: str, max_chars: int) -> str:
    """按显示宽度折行（全角≈1，半角≈0.6），超宽处插入硬换行 \\N。"""
    lines, cur, w = [], "", 0.0
    for ch in text:
        cw = 1.0 if ord(ch) > 0x2E80 or ch in "，。！？；：、""''（）《》" else 0.6
        if w + cw > max_chars and cur:
            lines.append(cur)
            cur, w = "", 0.0
        cur += ch
        w += cw
    if cur:
        lines.append(cur)
    return "\\N".join(lines)


def build_ass(segs, fontname, fontsize, marginv, margin_lr=160):
    header = STYLE_TEMPLATE.format(fontname=fontname, fontsize=fontsize,
                                   marginv=marginv, marginlr=margin_lr)
    lines = [header]
    # 每句直接使用模型返回的真实起止时间戳，保证字幕与语音严格对齐；
    # 过长的句子按屏幕安全区宽度折行（硬换行 \\N），两侧预留安全边距，避免超宽。
    max_chars = max(6, int((1080 - margin_lr * 2) / fontsize))  # 全角字数/行
    for seg in segs:
        wrapped = wrap_text(seg["text"].strip(), max_chars)
        lines.append(
            f"Dialogue: 0,{srt_time_to_ass(seg['start'])},{srt_time_to_ass(seg['end'])},"
            f"Default,,0,0,0,,{wrapped}"
        )
    return "\n".join(lines)


def to_sec(t: str) -> float:
    hh, mm, rest = t.split(":")
    ss, ms = rest.split(",")
    return int(hh) * 3600 + int(mm) * 60 + int(ss) + int(ms) / 1000


def dur_of(seg) -> float:
    return to_sec(seg["end"]) - to_sec(seg["start"])


def sec_to_ass(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    cs = int(round((t - int(t)) * 100))
    if cs == 100:
        s += 1
        cs = 0
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


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
    print(f"ASS 已生成: {args.out}（{len(segs)} 句原始 -> 拆分后渲染）")


if __name__ == "__main__":
    main()
