#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
豆包(火山方舟) 视频理解 → 剪辑决策单 管线骨架（备用）。
本地 ffmpeg+ASR → 豆包决策的完整链路示例。
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _load_env(path: str = ".env"):
    p = Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


_load_env(Path(__file__).resolve().parent / ".env")

ARK_API_KEY = os.getenv("ARK_API_KEY", "")
ARK_CHAT_MODEL = "doubao-1-5-pro-256k-250115"
ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_RULE = "去掉口误和废话, 去掉明显静默段, 保留高光卖点, 输出竖屏9:16可用片段"


def extract_audio(video: str, out_wav: str) -> str:
    cmd = ["ffmpeg", "-y", "-i", video, "-vn", "-ac", "1", "-ar", "16000",
           "-acodec", "pcm_s16le", out_wav]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_wav


def transcribe_whisper(wav: str):
    import whisper
    model = whisper.load_model("base")
    result = model.transcribe(wav, language="zh", word_timestamps=True)
    return [{"start": round(float(s["start"]), 2), "end": round(float(s["end"]), 2),
             "text": s["text"].strip()} for s in result["segments"]]


def _call_ark(messages, model_id: str, temperature: float = 0.2):
    from openai import OpenAI
    client = OpenAI(api_key=ARK_API_KEY, base_url=ARK_BASE_URL)
    params = dict(model=model_id, messages=messages, temperature=temperature,
                  response_format={"type": "json_object"})
    resp = client.chat.completions.create(**params)
    return resp.choices[0].message.content


def gen_edit_plan(segments, rule: str, dry_run: bool = False):
    if dry_run:
        return {"cuts": [{"start": segments[0]["start"], "end": segments[0]["end"],
                          "type": "高光", "reason": "示例：开场金句(dry-run)"},
                         {"start": segments[-1]["start"], "end": segments[-1]["end"],
                          "type": "保留", "reason": "示例：结尾总结(dry-run)"}],
                "_dry_run": True}
    lines = "\n".join(f'[{s["start"]:.1f}-{s["end"]:.1f}s] {s["text"]}' for s in segments)
    prompt = (f"你是短视频剪辑策划。根据下面带时间戳的语音转写，按用户规则生成剪辑决策单。\n"
              f"剪辑规则：{rule}\n\n要求：\n1. 输出 JSON，格式："
              "{\"cuts\": [{\"start\": 秒, \"end\": 秒, \"type\": \"保留|删除|高光|静默\", "
              "\"reason\": \"一句话原因\"}]}\n2. 只基于转写内容判断。\n\n转写字幕：\n" + lines)
    messages = [{"role": "system", "content": "你只输出合法的 JSON。"},
                {"role": "user", "content": prompt}]
    return json.loads(_call_ark(messages, ARK_CHAT_MODEL))


def save_outputs(outdir: Path, segments, plan):
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "transcript.json").write_text(json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8")
    (outdir / "edit_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    keep = [c for c in plan.get("cuts", []) if c.get("type") in ("保留", "高光")]
    srt_lines = []
    for i, c in enumerate(keep, 1):
        ms = int(round(c["start"] * 1000))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        srt_lines += [str(i), f"{h:02d}:{m:02d}:{s:02d},{ms:03d} --> "
                      + f"{h:02d}:{m:02d}:{s:02d},{ms:03d}".replace(f":{s:02d},", f":{int(ms):03d}".replace(" ", "")), c.get("reason", ""), ""]
    (outdir / "timeline.srt").write_text("\n".join(srt_lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="豆包视频理解 → 剪辑决策单")
    ap.add_argument("--video", required=True, help="输入视频路径")
    ap.add_argument("--rule", default=DEFAULT_RULE, help="剪辑规则")
    ap.add_argument("--out", default="out", help="输出目录")
    ap.add_argument("--dry-run", action="store_true", help="不联网，跑流程骨架")
    args = ap.parse_args()
    dry_run = args.dry_run or not ARK_API_KEY
    outdir = Path(args.out)
    with tempfile.TemporaryDirectory() as tmp:
        wav = extract_audio(args.video, os.path.join(tmp, "audio.wav"))
        segments = transcribe_whisper(wav)
        print(f"[ASR] 识别到 {len(segments)} 段")
    plan = gen_edit_plan(segments, args.rule, dry_run=dry_run)
    print(f"[plan] 生成 {len(plan.get('cuts', []))} 个剪辑点")
    save_outputs(outdir, segments, plan)
    print(f"[done] 产物目录: {outdir.resolve()}")


if __name__ == "__main__":
    main()
