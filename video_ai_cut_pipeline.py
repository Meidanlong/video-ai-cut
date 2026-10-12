#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
豆包(火山方舟) 视频理解 → 剪辑决策单 管线骨架
识别视频内容 -> 在关键点输出剪辑决策单(带时间码的JSON)，后续可转 FCPXML/EDL 进达芬奇。

用法：
  export ARK_API_KEY="你的火山方舟API Key"
  python video_ai_cut_pipeline.py --video /path/to/xxx.mp4 --rule "去口误,去静默,保留高光段" --out out
"""
import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path


def _load_env(path: str = ".env"):
    """从本地 .env 读取环境变量（ARK_API_KEY 等）。"""
    p = Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


_load_env(Path(__file__).resolve().parent / ".env")

ARK_API_KEY = os.getenv("ARK_API_KEY", "")
ARK_CHAT_MODEL = "doubao-1-5-pro-256k-250115"   # 文本决策用，可自行更换
ARK_VISION_MODEL = "doubao-1.5-vision-pro-250328"  # 画面理解用(可选)
ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_RULE = "去掉口误和废话, 去掉明显静默段, 保留高光卖点, 输出竖屏9:16可用片段"


def extract_audio(video: str, out_wav: str) -> str:
    """从视频抽单声道 16k 音轨，供 ASR 使用。"""
    cmd = ["ffmpeg", "-y", "-i", video, "-vn", "-ac", "1", "-ar", "16000",
           "-acodec", "pcm_s16le", out_wav]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_wav


def transcribe_whisper(wav: str):
    """本地 Whisper 转写，返回 [{start, end, text}]，秒为单位。"""
    import whisper
    model = whisper.load_model("base")
    result = model.transcribe(wav, language="zh", word_timestamps=True)
    segs = []
    for s in result["segments"]:
        segs.append({"start": round(float(s["start"]), 2),
                     "end": round(float(s["end"]), 2),
                     "text": s["text"].strip()})
    return segs


ASR_BACKEND = {"name": "whisper", "fn": transcribe_whisper}


def _call_ark(messages, model_id: str, temperature: float = 0.2):
    """通过 OpenAI 兼容接口调用豆包。返回模型文本。"""
    from openai import OpenAI
    client = OpenAI(api_key=ARK_API_KEY, base_url=ARK_BASE_URL)
    params = dict(model=model_id, messages=messages, temperature=temperature)
    params["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**params)
    return resp.choices[0].message.content


def _build_plan_prompt(segments, rule: str) -> str:
    lines = []
    for s in segments:
        lines.append(f'[{s["start"]:.1f}-{s["end"]:.1f}s] {s["text"]}')
    transcript = "\n".join(lines)
    return (
        "你是短视频剪辑策划。根据下面带时间戳的语音转写，按用户规则生成剪辑决策单。\n"
        f"剪辑规则：{rule}\n\n"
        "要求：\n"
        "1. 输出 JSON，不要任何多余文字，格式：\n"
        "   {\"cuts\": [{\"start\": 秒, \"end\": 秒, \"type\": \"保留|删除|高光|静默\", "
        "\"reason\": \"一句话原因\"}]}\n"
        "2. 保留段的 start/end 必须来自给定字幕的边界。\n"
        "3. 只基于转写内容判断，不要编造。\n\n"
        f"转写字幕：\n{transcript}"
    )


def gen_edit_plan(segments, rule: str, dry_run: bool = False):
    """调用豆包生成剪辑决策单。dry_run=True 时不联网，返回示例结构。"""
    if dry_run:
        return {"cuts": [
            {"start": segments[0]["start"], "end": segments[0]["end"],
             "type": "高光", "reason": "示例（dry-run，未真正调用豆包）"},
            {"start": segments[-1]["start"], "end": segments[-1]["end"],
             "type": "保留", "reason": "示例（dry-run）"},
        ], "_dry_run": True}
    prompt = _build_plan_prompt(segments, rule)
    messages = [
        {"role": "system", "content": "你只输出合法的 JSON。"},
        {"role": "user", "content": prompt},
    ]
    return json.loads(_call_ark(messages, ARK_CHAT_MODEL))


def save_outputs(outdir: Path, segments, plan):
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "transcript.json").write_text(json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8")
    (outdir / "edit_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    keep = [c for c in plan.get("cuts", []) if c.get("type") in ("保留", "高光")]
    srt_lines = []
    for i, c in enumerate(keep, 1):
        srt_lines.append(str(i))
        srt_lines.append(f"{_srt_time(c['start'])} --> {_srt_time(c['end'])}")
        srt_lines.append(c.get("reason", ""))
        srt_lines.append("")
    (outdir / "timeline.srt").write_text("\n".join(srt_lines), encoding="utf-8")


def _srt_time(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def main():
    ap = argparse.ArgumentParser(description="豆包视频理解 → 剪辑决策单")
    ap.add_argument("--video", required=True, help="输入视频路径")
    ap.add_argument("--rule", default=DEFAULT_RULE, help="剪辑规则")
    ap.add_argument("--out", default="out", help="输出目录")
    ap.add_argument("--frames", action="store_true", help="启用画面抽帧理解(可选)")
    ap.add_argument("--frames-fps", type=int, default=1, help="抽帧 fps")
    ap.add_argument("--dry-run", action="store_true", help="不联网，跑流程骨架")
    args = ap.parse_args()

    dry_run = args.dry_run or not ARK_API_KEY
    if dry_run:
        print("[dry-run] 未检测到 ARK_API_KEY，将以示例数据跑通结构。")
    outdir = Path(args.out)

    with tempfile.TemporaryDirectory() as tmp:
        wav = extract_audio(args.video, os.path.join(tmp, "audio.wav"))
        segments = ASR_BACKEND["fn"](wav)
        print(f"[ASR] 识别到 {len(segments)} 段")
        if args.frames:
            frames = extract_frames(args.video, os.path.join(tmp, "frames"), fps=args.frames_fps)
            print(f"[frames] 抽取 {len(frames)} 帧（画面理解可选，暂未接入）")

    plan = gen_edit_plan(segments, args.rule, dry_run=dry_run)
    print(f"[plan] 生成 {len(plan.get('cuts', []))} 个剪辑点")
    save_outputs(outdir, segments, plan)
    print(f"[done] 产物目录: {outdir.resolve()}")
    for f in ("transcript.json", "edit_plan.json", "timeline.srt"):
        p = outdir / f
        if p.exists():
            print(f"   - {p.name}")


def extract_frames(video: str, outdir: str, fps: int = 1, max_sec: int = 0):
    Path(outdir).mkdir(parents=True, exist_ok=True)
    vf = f"fps={fps}"
    if max_sec:
        vf = f"fps={fps},select='lt(t,{max_sec})'"
    cmd = ["ffmpeg", "-y", "-i", video, "-vf", vf, os.path.join(outdir, "frame_%06d.jpg")]
    subprocess.run(cmd, check=True, capture_output=True)
    return [str(f) for f in sorted(Path(outdir).glob("frame_*.jpg"))]


if __name__ == "__main__":
    main()
