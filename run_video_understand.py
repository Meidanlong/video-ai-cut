#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用豆包视频理解 API 直接分析一段本地视频：
上传(服务端抽帧+转写) -> 输出 内容概述 + 分段时间线 + 剪辑决策点(带时间戳)。

用法: ./venv/bin/python run_video_understand.py <视频路径> [剪辑规则]
"""
import os
import sys
import time
import json
from pathlib import Path
from openai import OpenAI

API_KEY = os.environ["ARK_API_KEY"]
MODEL = "doubao-seed-2-1-pro-260628"
BASE = "https://ark.cn-beijing.volces.com/api/v3"

video = sys.argv[1]
rule = sys.argv[2] if len(sys.argv) > 2 else "识别内容并给出剪辑建议"

client = OpenAI(api_key=API_KEY, base_url=BASE)

print("[1/3] 上传视频...")
with open(video, "rb") as f:
    file = client.files.create(file=f, purpose="user_data",
                               extra_body={"preprocess_configs": {"video": {"fps": 0.3}}})
print(f"   file_id={file.id} status={file.status}")

while True:
    file = client.files.retrieve(file.id)
    print(f"   处理中... status={file.status}")
    if file.status != "processing":
        break
    time.sleep(5)
if file.status != "active":
    print(f"文件处理失败: {file.status}")
    sys.exit(1)

print("[2/3] 豆包理解视频内容...")
prompt = (
    "请完整理解这段视频。输出纯 JSON（不要多余文字），格式：\n"
    "{\n"
    '  "video_type": "视频类型(口播/录屏教程/生活记录/带货/采访/其他)",\n'
    '  "summary": "内容概述(100字内)",\n'
    '  "timeline": [{"start":"HH:MM:SS","end":"HH:MM:SS","desc":"该时间段发生了什么"}],\n'
    '  "edit_points": [{"start":"HH:MM:SS","end":"HH:MM:SS","type":"删除|保留|高光|静默","reason":"一句话"}],\n'
    '  "notes": "剪辑建议"\n'
    "}\n"
    f"剪辑规则参考：{rule}"
)
resp = client.responses.create(
    model=MODEL,
    input=[{"role": "user", "content": [
        {"type": "input_video", "file_id": file.id},
        {"type": "input_text", "text": prompt},
    ]}],
)
text = resp.output_text if hasattr(resp, "output_text") else str(resp)
print("[3/3] 分析结果：")
print(text)

out_dir = Path("out_video_understand")
out_dir.mkdir(exist_ok=True)
(out_dir / "understand_result.json").write_text(text, encoding="utf-8")
print(f"\n结果已保存到 {out_dir/'understand_result.json'}")
