#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
短视频音效功能：按理解层情绪点，在成片合适时间混入音效。
内置音效 = ffmpeg 合成的简易音效（骰子声/宣布提示音/欢呼）
自定义音效 = 用户提供 CC0 音效文件（sfx-dir 里放 掷骰.wav / 结果.wav / 欢呼.wav）

用法:
  python add_sfx.py <成片> <输出>
      [--plan 决策单] [--emotions emotions_result.json] [--sfx-dir 目录]
      [--volume 音效音量] [--pre 提前秒] [--post 延后秒]
"""
import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent


def get_ffmpeg() -> str:
    exe = os.getenv("FFMPEG")
    if exe and Path(exe).exists():
        return exe
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def synth_sfx(kind: str, out_wav: str, ff: str):
    """用 ffmpeg 合成内置音效。"""
    def lavfi(expr):
        return ["-f", "lavfi", "-i", f"aevalsrc={expr}"]

    if kind == "掷骰":  # 骰子落碗：三个短促低频敲击
        exprs = ["0.5*sin(2*PI*180*t)*exp(-8*t):d=0.15",
                 "0.5*sin(2*PI*150*t)*exp(-8*(t-0.2)):d=0.35",
                 "0.4*sin(2*PI*120*t)*exp(-8*(t-0.4)):d=0.55"]
        fc = "[0:a][1:a][2:a]amix=inputs=3:normalize=0"
        cmd = [ff, "-y"]
        for e in exprs:
            cmd += lavfi(e)
        cmd += ["-filter_complex", fc, "-ar", "44100", out_wav]
        subprocess.run(cmd, check=True, capture_output=True)
    elif kind == "结果":  # 宣布提示音：上行三连音
        exprs = ["0.5*sin(2*PI*523*t)*exp(-6*t):d=0.2",
                 "0.5*sin(2*PI*659*t)*exp(-6*(t-0.15)):d=0.35",
                 "0.5*sin(2*PI*784*t)*exp(-5*(t-0.3)):d=0.5"]
        fc = "[0:a][1:a][2:a]amix=inputs=3:normalize=0"
        cmd = [ff, "-y"]
        for e in exprs:
            cmd += lavfi(e)
        cmd += ["-filter_complex", fc, "-ar", "44100", out_wav]
        subprocess.run(cmd, check=True, capture_output=True)
    elif kind == "欢呼":
        subprocess.run([ff, "-y", "-f", "lavfi",
                        "-i", "anoisesrc=d=0.6:c=pink:amplitude=0.3",
                        "-af", "afade=t=in:d=0.05,afade=t=out:d=0.15,volume=0.5",
                        out_wav], check=True, capture_output=True)
    else:
        raise ValueError(f"未知内置音效类型: {kind}")


def build_delays(points, pre: float):
    """每个音效输入生成一条带音量/延迟的链，返回 (inputs, 链, 覆盖时长)。"""
    inputs, chains = [], []
    # 收集触发时间确定总时长
    tmax = max(p["dst_time"] for p in points) + 1.0
    for i, p in enumerate(points):
        t = p["dst_time"]
        sfx_kind = p.get("sfx") or (p["emotion"] if p["emotion"] == "结果公布" else "掷骰")
        start = max(0.0, t - pre)
        delay_ms = int(start * 1000)
        # adelay 需要采样率；统一 44100
        chains.append(f"[{i+1}:a]aresample=44100,volume=1.0,"
                      f"adelay={delay_ms}|{delay_ms}|{delay_ms}[sfx{i}]")
        inputs.append(("-i", p["sfx_path"]))
    return inputs, chains, tmax


def main():
    ap = argparse.ArgumentParser(description="短视频音效叠加")
    ap.add_argument("video", help="成片视频路径")
    ap.add_argument("output", help="输出视频路径")
    ap.add_argument("--plan", default=str(BASE / "out_video_understand" / "compact_result.json"))
    ap.add_argument("--emotions", default=str(BASE / "out_video_understand" / "emotions_result.json"))
    ap.add_argument("--sfx-dir", default="", help="自定义音效目录(放 掷骰.wav/结果.wav/欢呼.wav)")
    ap.add_argument("--volume", type=float, default=1.0, help="音效总体音量")
    ap.add_argument("--pre", type=float, default=0.05, help="音效提前触发秒数")
    args = ap.parse_args()

    ff = get_ffmpeg()
    # 读取情绪点并映射到成片时间
    from cut_time import kept_ranges, src_to_dst
    keeps = kept_ranges(Path(args.plan))
    ems = json.loads(Path(args.emotions).read_text(encoding="utf-8"))
    points = []
    for p in ems["points"]:
        dst = src_to_dst(p["time"], keeps)
        if dst is not None:
            points.append({**p, "dst_time": dst})
    print(f"音效点 {len(points)} 个")

    # 为每个点准备音效文件
    sfx_dir = Path(args.sfx_dir) if args.sfx_dir else None
    # 归一化音效类型：宣布->结果
    kind_aliases = {"宣布": "结果", "公布": "结果", "欢呼": "欢呼", "掷骰": "掷骰"}
    tmp = Path(tempfile.mkdtemp())
    for i, p in enumerate(points):
        raw = p.get("sfx") or (p["emotion"] if p["emotion"] == "结果公布" else "掷骰")
        kind = kind_aliases.get(raw, raw)
        custom = None
        if sfx_dir and sfx_dir.exists():
            for cand in [f"{kind}.wav", f"{kind}.mp3", "掷骰.wav", "结果.wav", "欢呼.wav"]:
                c = sfx_dir / cand
                if c.exists():
                    custom = str(c)
                    break
        if custom:
            p["sfx_path"] = custom
            print(f"  {p['dst_time']:6.2f}s 使用自定义音效 {custom}")
        else:
            wav = tmp / f"sfx{i}.wav"
            synth_sfx(kind, str(wav), ff)
            p["sfx_path"] = str(wav)
            print(f"  {p['dst_time']:6.2f}s 内置合成音效 [{kind}]")

    # 输入0=成片，之后每个音效
    inputs = [args.video]
    chains = []
    tmax = max(p["dst_time"] for p in points) + 1.2
    for i, p in enumerate(points):
        start = max(0.0, p["dst_time"] - args.pre)
        delay_ms = int(start * 1000)
        inputs.append(p["sfx_path"])
        chains.append(f"[{i+1}:a]aresample=44100,volume={args.volume},"
                      f"adelay={delay_ms}|{delay_ms}|{delay_ms}[sfx{i}]")

    # 拼接所有音效并混入主音轨
    n = len(points)
    mix_inputs = "".join(f"[sfx{i}]" for i in range(n))
    fc = ";".join(chains) + f";{mix_inputs}amix=inputs={n}:normalize=0,"
    # amix 后与主音轨 amix(短期)
    # 主音轨在 adelay 时长为视频时长，需要 atrim
    import re
    probe = subprocess.run([ff, "-i", args.video], capture_output=True, text=True)
    md = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", probe.stderr)
    vdur = (int(md.group(1)) * 3600 + int(md.group(2)) * 60 + float(md.group(3))) if md else 139.0
    fc += f"atrim=0:{vdur:.3f},asetpts=PTS-STARTPTS[sfxall];"
    fc += "[0:a]aresample=44100[a0];[a0][sfxall]amix=inputs=2:duration=first:normalize=0[aout]"

    cmd = [ff, "-y"]
    for inp in inputs:
        cmd += ["-i", inp]
    cmd += ["-filter_complex", fc, "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", args.output]
    print("运行 ffmpeg 混入音效...")
    subprocess.run(cmd, check=True)
    print(f"音效版已生成: {args.output}")


if __name__ == "__main__":
    main()
