#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快节奏版：复用已上传的视频 file_id，让豆包按"抖音快节奏"标准细粒度识别
可删除的低信息段(查手机/停顿/重复/无意义动作)，输出细粒度剪辑点。

用法: ./venv/bin/python compact_understand.py <file_id>
"""
import os
import sys
import json
from pathlib import Path
from openai import OpenAI

API_KEY = os.environ["ARK_API_KEY"]
MODEL = "doubao-seed-2-1-pro-260628"
BASE = "https://ark.cn-beijing.volces.com/api/v3"

file_id = sys.argv[1]

client = OpenAI(api_key=API_KEY, base_url=BASE)

prompt = (
    "这是要剪成抖音式快节奏短视频的餐厅掷骰子素材。请逐段精确识别所有可删除的低信息、冗余、拖节奏内容，"
    "包括但不限于：1) 查看手机/查规则、犹豫、停顿 2) 重复的掷骰准备或平淡过程 3) 静止空档、无意义晃动。\n"
    "规则：节奏要快，只保留有信息量或情绪看点的片段。\n"
    "输出纯 JSON（不要多余文字）：\n"
    "{\n"
    '  "deletes": [{"start":"HH:MM:SS","end":"HH:MM:SS","reason":"为何删"}],\n'
    '  "highlights": [{"start":"HH:MM:SS","end":"HH:MM:SS","reason":"必留看点"}],\n'
    '  "summary": "成片节奏建议一句话"\n'
    "}\n"
    "要求：deletes 区间尽量精确到秒；不要删除开场和结局，不要删除有情绪反应的关键时刻。"
)
resp = client.responses.create(
    model=MODEL,
    input=[{"role": "user", "content": [
        {"type": "input_video", "file_id": file_id},
        {"type": "input_text", "text": prompt},
    ]}],
)
text = resp.output_text if hasattr(resp, "output_text") else str(resp)
print(text)

out_dir = Path("out_video_understand")
out_dir.mkdir(exist_ok=True)
(out_dir / "compact_result.json").write_text(text, encoding="utf-8")
print("\n已保存到 out_video_understand/compact_result.json")
