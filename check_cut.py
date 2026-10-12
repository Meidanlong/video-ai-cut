#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
关键信息完整性校验门（质量门）：剪辑后必须通过，否则报错。
作用：从字幕中找出"结果/输赢/宣布"等关键信息句，逐句核对它们的时间段
是否都落在保留段内（即没有被删除区间吃掉）。任何关键句缺失 => 报错列出，
防止"报结果被误删"这类问题在成片里出现而不自知。

用法: python check_cut.py <决策单.json> <字幕.srt>
退出码 0=通过，非0=有关键信息被删（列出具体被删的句子）。
"""
import json
import re
import sys
from pathlib import Path

KEYWORDS = ["中", "赢", "百", "千", "结果", "二举", "一秀", "状元",
            "榜眼", "探花", "开仓", "放粮", "宣布", "赢了", "中了", "块钱"]


def ts2sec(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def srt_segments(srt_text: str) -> list:
    lines = [l.strip() for l in srt_text.splitlines() if l.strip()]
    segs = []
    for i in range(0, len(lines), 3):
        m = re.match(r"(\d+:\d+:\d+,\d+)\s*-->\s*(\d+:\d+:\d+,\d+)", lines[i + 1])
        if m:
            def s(t):
                h, mn, r = t.split(":")
                ss, ms = r.split(",")
                return int(h) * 3600 + int(mn) * 60 + int(ss) + int(ms) / 1000
            segs.append((s(m.group(1)), s(m.group(2)), lines[i + 2]))
    return segs


def kept_ranges(plan) -> list:
    deletes = sorted((ts2sec(p["start"]), ts2sec(p["end"])) for p in plan["deletes"])
    dur = max(e for _, e in deletes) + 5
    keeps = [(0.0, dur)]
    for ds, de in deletes:
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
    return [(s, e) for s, e in keeps if e - s > 0]


def main():
    plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    segs = srt_segments(Path(sys.argv[2]).read_text(encoding="utf-8"))
    keeps = kept_ranges(plan)

    def inside(t: float) -> bool:
        return any(s - 0.1 <= t <= e + 0.1 for s, e in keeps)

    missing = []
    for a, b, text in segs:
        if any(k in text for k in KEYWORDS):
            if not inside(a):
                missing.append((a, b, text))

    if missing:
        print("!!! 关键信息缺失：以下结果/输赢句被删除，成片将丢失重要内容 !!!")
        for a, b, t in missing:
            print(f"  [{a:.1f}-{b:.1f}] {t.strip()}")
        sys.exit(1)
    else:
        print("校验通过：所有关键结果信息均已保留。")
        sys.exit(0)


if __name__ == "__main__":
    main()
