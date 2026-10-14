#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
理解层情绪点标注：复用理解层角色标注(roles_result.json)，
把 AI 判断出的核心结果/关键动作等映射为"情绪/事件触发点"。

用法: ./venv/bin/python understand_emotions.py
输出: out_video_understand/emotions_result.json
"""
import json
import re
from pathlib import Path

BASE = Path("out_video_understand")


def ts2sec(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def midpoint(a: str, b: str) -> float:
    return (ts2sec(a) + ts2sec(b)) / 2.0


EMOTION_MAP = [
    (["核心结果"], "结果公布",
     {"sfx": "宣布", "sticker": "🎯 结果", "region": "bottom-center",
      "desc_hint": "宣布结果/输赢/金额"}),
    (["关键动作"], "关键动作",
     {"sfx": None, "sticker": "🎲 掷骰", "region": "top-right",
      "desc_hint": "核心动作"}),
]


def parse_roles():
    raw = (BASE / "roles_result.json").read_text(encoding="utf-8").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
    return json.loads(raw)["segments"]


def build_emotions(segs):
    points = []
    for s in segs:
        role = s["role"]
        desc = s.get("desc", "")
        st, en = s["start"], s["end"]
        for roles, emotion, spec in EMOTION_MAP:
            if role in roles:
                points.append({"time": round(midpoint(st, en), 2), "emotion": emotion,
                               "sfx": spec["sfx"], "sticker": spec["sticker"],
                               "region": spec["region"], "role": role,
                               "start": st, "end": en, "desc": desc})
                break
    points.sort(key=lambda p: p["time"])
    return points


def main():
    segs = parse_roles()
    points = build_emotions(segs)
    out = {"points": points, "source": "roles_result.json (AI角色标注派生)",
           "summary": "情绪/事件触发点，供封面选帧、贴图、音效定位"}
    (BASE / "emotions_result.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"情绪点 {len(points)} 个:")
    for p in points:
        print(f"  {p['time']:6.2f}s [{p['emotion']}] {p['role']}: {p['desc'][:25]}")
    print(f"\n已保存到 {BASE/'emotions_result.json'}")


if __name__ == "__main__":
    main()
