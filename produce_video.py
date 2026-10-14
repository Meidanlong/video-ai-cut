#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
短视频"理解+剪辑+包装"一键成片（封面/贴图/音效三能力演示版）。

链路：情绪点标注 -> 基础成片(降噪+BGM+字幕) -> 封面海报 -> 贴图版 -> 音效版

用法:
  python produce_video.py <原视频>
      [--output 成品.mp4] [--title 封面标题] [--subtitle 副标题]
      [--sticker-dir 贴图目录] [--sfx-dir 音效目录] [--no-bgm]
"""
import argparse
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent


def run(label, *cmd):
    print(f"\n[{label}]")
    subprocess.run(list(cmd), check=True)


def main():
    ap = argparse.ArgumentParser(description="视频AI剪辑+三包装一键成片")
    ap.add_argument("video", help="原视频路径")
    ap.add_argument("--output", default=str(BASE / "成片_成品版.mp4"))
    ap.add_argument("--plan", default=str(BASE / "out_video_understand" / "compact_result.json"))
    ap.add_argument("--srt", default=str(BASE / "out_video_understand" / "transcript.srt"))
    ap.add_argument("--bgm", default=str(BASE / "bgm_happy_days.mp3"))
    ap.add_argument("--title", default="中秋博饼\n开仓放粮")
    ap.add_argument("--subtitle", default="厦门·博饼")
    ap.add_argument("--cover-size", default="both")
    ap.add_argument("--sticker-dir", default="")
    ap.add_argument("--sfx-dir", default="")
    ap.add_argument("--no-bgm", action="store_true")
    args = ap.parse_args()

    py = sys.executable
    out = Path(args.output)
    base = out.stem
    emo = str(BASE / "out_video_understand" / "emotions_result.json")

    run("1/5 情绪点标注", py, str(BASE / "understand_emotions.py"))
    fc = [py, str(BASE / "final_cut.py"), args.video, str(out),
          "--plan", args.plan, "--srt", args.srt]
    if args.no_bgm:
        fc.append("--no-bgm")
    run("2/5 基础成片(降噪+BGM+字幕)", *fc)
    run("3/5 封面海报(双尺寸)", py, str(BASE / "make_cover.py"), args.video,
        "--title", args.title, "--subtitle", args.subtitle, "--size", args.cover_size)
    ov = [py, str(BASE / "add_overlays.py"), str(out), str(BASE / f"{base}_贴图版.mp4"),
          "--plan", args.plan, "--emotions", emo]
    if args.sticker_dir:
        ov += ["--sticker-dir", args.sticker_dir]
    run("4/5 贴图版成片", *ov)
    sf = [py, str(BASE / "add_sfx.py"), str(out), str(BASE / f"{base}_音效版.mp4"),
          "--plan", args.plan, "--emotions", emo]
    if args.sfx_dir:
        sf += ["--sfx-dir", args.sfx_dir]
    run("5/5 音效版成片", *sf)
    print("\n===== 完成 =====")
    print(f"封面   : {BASE}/封面海报_34.png, 封面海报_916.png")
    print(f"基础   : {out}")
    print(f"贴图版 : {BASE}/{base}_贴图版.mp4")
    print(f"音效版 : {BASE}/{base}_音效版.mp4")


if __name__ == "__main__":
    main()
