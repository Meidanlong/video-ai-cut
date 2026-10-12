#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
角色标注 -> 分层剪辑决策。
删除: 冗余语音 / 冗余空白 / 废镜头
保留: 核心结果 / 关键动作 / 铺垫说明
再强制保护"结果句"语音(ASR关键词)不被删除区间吃掉。
写回 compact_result.json 供 final_cut 使用。
用法: ./venv/bin/python roles_to_plan.py
"""
import json
import re
from pathlib import Path

BASE = Path("out_video_understand")
DELETE_ROLES = {"冗余语音", "冗余空白", "废镜头"}
KEEP_ROLES = {"核心结果", "关键动作", "铺垫说明"}
# 结果句关键词（同 check_cut）：含这些的语音为"报结果"，强制保留
KEYWORDS = ["中", "赢", "百", "千", "结果", "二举", "一秀", "状元",
            "榜眼", "探花", "开仓", "放粮", "宣布", "赢了", "中了", "块钱"]


def ts2sec(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def sec2ts(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:02d}:{int(m):02d}:{s:05.2f}"


def result_speech_segments(srt_text: str) -> list:
    """返回含结果关键词的语音段时间。"""
    lines = [l.strip() for l in srt_text.splitlines() if l.strip()]
    out = []
    for i in range(0, len(lines), 3):
        m = re.match(r"(\d+:\d+:\d+,\d+)\s*-->\s*(\d+:\d+:\d+,\d+)", lines[i + 1])
        if not m:
            continue
        def s(t):
            h, mn, r = t.split(":")
            ss, ms = r.split(",")
            return int(h) * 3600 + int(mn) * 60 + int(ss) + int(ms) / 1000
        text = lines[i + 2]
        if any(k in text for k in KEYWORDS):
            out.append((s(m.group(1)) - 0.3, s(m.group(2)) + 0.3))
    return out


def protect(deletes: list, protected: list) -> list:
    """从删除区间中挖掉被保护(结果句)覆盖的部分。"""
    out = []
    for ds, de in deletes:
        cur = [(ds, de)]
        for a, b in protected:
            nxt = []
            for x, y in cur:
                if b <= x or a >= y:
                    nxt.append((x, y))
                else:
                    if x < a:
                        nxt.append((x, a))
                    if b < y:
                        nxt.append((b, y))
            cur = nxt
        out.extend(cur)
    out.sort()
    merged = []
    for x, y in out:
        if y - x < 0.4:
            continue
        if merged and x - merged[-1][1] < 0.15:
            merged[-1] = (merged[-1][0], max(merged[-1][1], y))
        else:
            merged.append((x, y))
    return merged


def main():
    roles = json.loads((BASE / "roles_result.json").read_text(encoding="utf-8"))
    segs = roles["segments"]

    # 1) 角色标注生成删除区间
    deletes = [(ts2sec(s["start"]), ts2sec(s["end"]))
               for s in segs if s["role"] in DELETE_ROLES]
    keeps = [s for s in segs if s["role"] in KEEP_ROLES]

    # 2) 强制保护结果句语音
    protected = result_speech_segments((BASE / "transcript.srt").read_text(encoding="utf-8"))
    final_del = protect(deletes, protected)

    plan = {
        "deletes": [{"start": sec2ts(a), "end": sec2ts(b),
                     "reason": "冗余(经结果句保护)"} for a, b in final_del],
        "highlights": [{"start": s["start"], "end": s["end"],
                        "reason": s.get("desc", "")} for s in keeps],
        "keep_roles": sorted({s["role"] for s in keeps}),
        "summary": "分层剪辑：核心结果/关键动作/铺垫保留，冗余删除，结果句强制保护",
    }
    (BASE / "compact_result.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"角色删除 {len(deletes)} 段 -> 经结果句保护后 {len(final_del)} 段")
    for a, b in final_del:
        print(f"  删 [{sec2ts(a)}-{sec2ts(b)}]  ({b-a:.1f}s)")
    print(f"保留 {len(keeps)} 段（核心结果 {sum(1 for s in keeps if s['role']=='核心结果')} / 关键动作 {sum(1 for s in keeps if s['role']=='关键动作')} / 铺垫 {sum(1 for s in keeps if s['role']=='铺垫说明')}）")


if __name__ == "__main__":
    main()
