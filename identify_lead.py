#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主角识别：判断短视频里"第一个正面出镜、占画面主体"的人物，并给出其出镜时段。

口播类视频默认以第一个出场的人为主角，封面主图应取该主角出镜时段内"形象最佳"的一帧，
而不是固定抽"最终结果公布点"。

用法:
  python identify_lead.py <视频> [--start 0] [--scan-end 12] [--lead-end 64]
                          [--step 0.5] [--name 主角名] [--auto-end]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageFilter, ImageStat

BASE = Path(__file__).resolve().parent
UNDERSTAND_DIR = BASE / "out_video_understand"


def get_ffmpeg() -> str:
    exe = os.getenv("FFMPEG")
    if exe and Path(exe).exists():
        return exe
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def probe_duration(video: str) -> float:
    try:
        ff = get_ffmpeg()
        r = subprocess.run([ff, "-i", video], capture_output=True, text=True)
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", r.stderr or "")
        if not m:
            return 0.0
        h, mi, s = m.groups()
        return int(h) * 3600 + int(mi) * 60 + float(s)
    except Exception:
        return 0.0


def extract_frame(video: str, t: float, out_png: str):
    ff = get_ffmpeg()
    subprocess.run([ff, "-y", "-ss", f"{t:.3f}", "-i", video,
                    "-frames:v", "1", "-q:v", "2", out_png],
                   check=True, capture_output=True)


def get_face_detector():
    try:
        import cv2
    except Exception:
        return None
    xml = getattr(cv2.data, "haarcascades", "") + "haarcascade_frontalface_default.xml"
    if not os.path.exists(xml):
        return None
    clf = cv2.CascadeClassifier(xml)
    return None if clf.empty() else clf


def _central(img: Image.Image, ratio: float = 0.6) -> Image.Image:
    w, h = img.size
    cw, ch = int(w * ratio), int(h * ratio)
    left, top = (w - cw) // 2, (h - ch) // 2
    return img.crop((left, top, left + cw, top + ch))


def frame_metrics(png: str, detector=None) -> dict:
    img = Image.open(png).convert("L")
    w, h = img.size
    full_edges = ImageStat.Stat(img.filter(ImageFilter.FIND_EDGES)).var[0]
    c = _central(img)
    c_edges = ImageStat.Stat(c.filter(ImageFilter.FIND_EDGES)).var[0]
    c_mean = ImageStat.Stat(c).mean[0]
    m = {"sharpness": float(full_edges), "center_energy": float(c_edges / (full_edges + 1e-6)),
         "exposure_delta": float(abs(c_mean - 128.0)), "face_ratio": None}
    if detector is not None:
        try:
            import numpy as np
            import cv2
            arr = np.array(Image.open(png).convert("RGB"))
            gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
            faces = detector.detectMultiScale(gray, 1.15, 6, minSize=(int(h * 0.15), int(h * 0.15)))
            if len(faces):
                x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
                m["face_ratio"] = float(fw * fh) / float(w * h)
            else:
                m["face_ratio"] = 0.0
        except Exception:
            m["face_ratio"] = None
    return m


def score_frame(m: dict) -> float:
    import math
    sharp = min(math.log1p(m["sharpness"]) / math.log1p(2000.0), 1.0)
    energy = min(max(m["center_energy"], 0.0), 1.5) / 1.5
    expo = max(0.0, 1.0 - m["exposure_delta"] / 90.0)
    face = 0.5 if m["face_ratio"] is None else min(max(m["face_ratio"] / 0.18, 0.0), 1.0)
    return round(0.34 * sharp + 0.26 * energy + 0.20 * expo + 0.20 * face, 4)


def signature(png: str, size: int = 32) -> list:
    img = Image.open(png).convert("L").resize((size, size), Image.LANCZOS)
    px = list(img.get_flattened_data())
    m = sum(px) / len(px)
    return [p - m for p in px]


def similarity(a: list, b: list) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = sum(x * x for x in a) ** 0.5
    db = sum(y * y for y in b) ** 0.5
    if da == 0 or db == 0:
        return 0.0
    return max(0.0, min(1.0, num / (da * db)))


def load_support_evidence() -> dict:
    ev = {}
    p = UNDERSTAND_DIR / "roles_result.json"
    if p.exists():
        try:
            segs = json.loads(p.read_text(encoding="utf-8"))["segments"]
            ev["roles_first_segment"] = segs[0] if segs else None
        except Exception:
            pass
    p = UNDERSTAND_DIR / "transcript.srt"
    if p.exists():
        try:
            lines = [l for l in p.read_text(encoding="utf-8").splitlines() if "-->" in l]
            ev["transcript_first_line"] = lines[0] if lines else None
            ev["transcript_last_line"] = lines[-1] if lines else None
        except Exception:
            pass
    return ev


def find_lead(video: str, start: float, scan_end: float, lead_end: float,
              step: float, name: str, auto_end: bool = False,
              sim_thr: float = 0.55, drop_run: int = 4):
    dur = probe_duration(video)
    limit = dur if dur > 0 else lead_end
    scan_end = min(scan_end, limit)
    lead_end = min(lead_end, limit)
    detector = get_face_detector()
    det_name = "cv2/haarcascade_frontalface_default" if detector else \
        "fallback: 中央区域高频能量 + 亮度 + 清晰度（未安装 cv2）"
    times, metrics = [], []
    with tempfile.TemporaryDirectory() as tmp:
        t = start
        while t <= lead_end + 1e-6:
            png = os.path.join(tmp, f"f_{t:07.2f}.png")
            try:
                extract_frame(video, t, png)
            except Exception:
                t += step
                continue
            times.append(round(t, 2))
            metrics.append((png, frame_metrics(png, detector)))
            t += step
        if not times:
            raise RuntimeError("未抽到任何帧，请检查视频路径")
        scan_idx = [i for i, tt in enumerate(times) if tt <= scan_end + 1e-6]
        scored = [(i, score_frame(metrics[i][1])) for i in scan_idx]
        if not scored:
            raise RuntimeError("扫描段内无有效帧")
        peak = max(s for _, s in scored)
        onset = next((i for i, s in scored if s >= peak * 0.8), scored[0][0])
        ref_idx = onset
        appearance_start = times[ref_idx]
        end_idx = len(times) - 1
        if auto_end:
            ref_sig = signature(metrics[ref_idx][0])
            below = 0
            for i in range(ref_idx + 1, len(times)):
                if similarity(ref_sig, signature(metrics[i][0])) < sim_thr:
                    below += 1
                    if below >= drop_run:
                        end_idx = i - drop_run + 1
                        break
                else:
                    below = 0
        appearance_end = times[end_idx]
        band = [(times[i], metrics[i][1], score_frame(metrics[i][1]))
                for i in range(ref_idx, end_idx + 1)]
        top = sorted(band, key=lambda x: -x[2])[:5]
    if auto_end:
        rule = ("开头(0~%.1fs)第一帧主体显著即主角；主角离场=与出场帧相似度连续%d帧<%.2f"
                % (scan_end, drop_run, sim_thr))
    else:
        rule = ("开头(0~%.1fs)第一帧主体显著、画面主体即主角；出镜时段上限 %.0fs"
                "（原视频0-64s为紧凑决策第一段完整保留的口播段）" % (scan_end, lead_end))
    result = {"lead_name": name, "appearance_start": appearance_start,
              "appearance_end": appearance_end,
              "evidence": {"video": os.path.basename(video), "video_duration": round(dur, 2),
                           "rule": rule, "auto_end": auto_end, "detector": det_name,
                           "frame_step": step, "frames_scanned": len(times),
                           "lead_frame_time": appearance_start,
                           "lead_frame_metrics": {k: (round(v, 4) if isinstance(v, float) else v)
                                                  for k, v in metrics[ref_idx][1].items()},
                           "top_frames_in_band": [
                               {"time": tt, "score": sc,
                                **{k: (round(v, 4) if isinstance(v, float) else v)
                                   for k, v in mm.items()}}
                               for tt, mm, sc in top],
                           "support": load_support_evidence()}}
    return result


def main():
    ap = argparse.ArgumentParser(description="识别口播视频主角及其出镜时段")
    ap.add_argument("video", help="视频路径")
    ap.add_argument("--start", type=float, default=0.0, help="扫描起始秒")
    ap.add_argument("--scan-end", type=float, default=12.0, help="开头判定段结束秒")
    ap.add_argument("--lead-end", type=float, default=64.0, help="出场时段上限秒")
    ap.add_argument("--step", type=float, default=0.5, help="抽帧步长秒")
    ap.add_argument("--name", default="口播主角", help="主角名")
    ap.add_argument("--auto-end", action="store_true",
                    help="按画面相似度自动判定主角离场（默认关闭，用 lead-end 上限）")
    ap.add_argument("--out", default=str(UNDERSTAND_DIR / "lead_result.json"))
    args = ap.parse_args()
    res = find_lead(args.video, args.start, args.scan_end, args.lead_end,
                    args.step, args.name, auto_end=args.auto_end)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"主角: {res['lead_name']}")
    print(f"出镜时段: {res['appearance_start']:.2f}s ~ {res['appearance_end']:.2f}s")
    print(f"检测方式: {res['evidence']['detector']}")
    print(f"已写入: {out}")


if __name__ == "__main__":
    main()
