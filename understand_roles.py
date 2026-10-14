#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
理解层升级：逐段内容角色标注。让豆包把整个视频切成小段，每段标注剪辑角色，
从理解层区分"核心结果/关键动作/铺垫说明/冗余空白/废镜头"，供分层剪辑使用。

用法: ./venv/bin/python understand_roles.py <file_id>
输出: out_video_understand/roles_result.json
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

srt = Path("out_video_understand/transcript.srt").read_text(encoding="utf-8")

prompt = (
    "请结合视频画面和下方语音字幕，对视频逐段做内容角色判断（每段约2-8秒），"
    "给出精确起止时间戳。判断时务必结合语音说了什么，不要只凭画面动作。\n"
    "角色定义：\n"
    "- 核心结果：语音在宣布结果/输赢/金额——最关键，必保，绝不能删\n"
    "- 关键动作：掷骰等核心动作过程\n"
    "- 铺垫说明：介绍背景/规则/玩法，有价值信息\n"
    "- 冗余语音：查手机查规则、重复解说、无效尝试的对话、犹豫迟疑——即使有语音也算冗余，可删\n"
    "- 冗余空白：无语音的停顿、发呆、重复动作\n"
    "- 废镜头：无意义画面、镜头晃动无内容\n"
    "语音字幕（带时间戳）如下：\n"
    "----------\n"
    f"{srt}\n"
    "----------\n"
    "输出纯 JSON（不要多余文字），覆盖整个视频从 0 秒到结尾，分段连续不重叠、不遗漏：\n"
    '{"segments":[{"start":"HH:MM:SS","end":"HH:MM:SS","role":"核心结果","desc":"一句话说明"}]}\n'
    "要求：时间戳精确到秒；报结果/宣布金额必须标为核心结果，绝不能标成冗余。"
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
(out_dir / "roles_result.json").write_text(text, encoding="utf-8")
print("\n已保存到 out_video_understand/roles_result.json")
