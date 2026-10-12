#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用火山方舟"音频理解"把音频转写成带时间戳的字幕(SRT)。
用法: python audio_to_srt.py <音频路径> [输出srt路径]
"""
import os
import sys
import time
import json
from pathlib import Path
from openai import OpenAI

API_KEY = os.environ["ARK_API_KEY"]
MODEL = "doubao-seed-2-0-lite-260428"   # 支持音频理解的模型
BASE = "https://ark.cn-beijing.volces.com/api/v3"

audio = sys.argv[1]
out_srt = sys.argv[2] if len(sys.argv) > 2 else "out_video_understand/transcript.srt"

client = OpenAI(api_key=API_KEY, base_url=BASE)

# 1) 上传音频
print("[1/3] 上传音频...")
with open(audio, "rb") as f:
    file = client.files.create(file=f, purpose="user_data")
print(f"   file_id={file.id}")
while True:
    file = client.files.retrieve(file.id)
    if file.status != "processing":
        break
    time.sleep(3)
if file.status != "active":
    print(f"文件处理失败: {file.status}")
    sys.exit(1)

# 2) 音频理解 -> 带时间戳逐句
print("[2/3] 豆包转写...")
prompt = (
    "请识别这段音频中的全部语音，按说话顺序逐句输出，每句带起止时间戳。"
    "只输出合法 JSON（不要多余文字）：\n"
    '{"segments":[{"start":"MM:SS.mmm","end":"MM:SS.mmm","text":"一句话"}]}\n'
    "要求：时间戳精确到毫秒；中文文本去掉语气词；按实际说话停顿分句。"
)
resp = client.responses.create(
    model=MODEL,
    input=[{
        "role": "user",
        "content": [
            {"type": "input_audio", "file_id": file.id},
            {"type": "input_text", "text": prompt},
        ],
    }],
)
text = resp.output_text if hasattr(resp, "output_text") else str(resp)
print("[3/3] 转写完成")
print(text)

# 3) 转成 SRT
def to_srt_time(ts: str) -> str:
    m, s = ts.split(":")
    s = float(s)
    mm = int(s)
    ms = int(round((s - mm) * 1000))
    return f"00:{int(m):02d}:{mm:02d},{ms:03d}"

data = json.loads(text)
segs = data.get("segments", [])
lines = []
for i, seg in enumerate(segs, 1):
    lines.append(str(i))
    lines.append(f"{to_srt_time(seg['start'])} --> {to_srt_time(seg['end'])}")
    lines.append(seg["text"].strip())
    lines.append("")

Path(out_srt).parent.mkdir(parents=True, exist_ok=True)
Path(out_srt).write_text("\n".join(lines), encoding="utf-8")
print(f"\nSRT 已保存: {out_srt}（{len(segs)} 句）")
