#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
时间线映射工具：把"原视频时间"映射到"成片时间"。
成片是原视频按 compact_result.json 删除冗余段后拼接的，因此原视频里
位于删除段之后的时间在成片里会前移。

用法: python cut_time.py --map <原视频秒> [--plan 决策单]
"""
import argparse
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent


def ts2sec(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def load_delete_ranges(plan_path: Path):
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if "deletes" in plan:
        return [(ts2sec(p["start"]), ts2sec(p["end"])) for p in plan["deletes"]]
    return [(ts2sec(p["start"]), ts2sec(p["end"]))
            for p in plan["edit_points"] if p["type"] == "删除"]


def kept_ranges(plan_path: Path, duration: float = None):
    deletes = sorted(load_delete_ranges(plan_path))
    if duration is None:
        duration = max((e for _, e in deletes), default=0) + 60
    keeps = [(0.0, duration)]
    for ds, de in deletes:
        nk = []
        for s, e in keeps:
            if de <= s or ds >= e:
                nk.append((s, e))
            else:
                if s < ds:
                    nk.append((s, ds))
                if de < e:
                    nk.append((de, e))
        keeps = nk
    return [(round(s, 3), round(e, 3)) for s, e in keeps if e - s > 0.3]


def src_to_dst(t: float, keeps) -> float | None:
    offset = 0.0
    for s, e in keeps:
        if s <= t <= e:
            return round(offset + (t - s), 3)
        offset += (e - s)
    return None


def main():
    ap = argparse.ArgumentParser(description="原视频时间 -> 成片时间映射")
    ap.add_argument("--map", type=float, help="原视频秒")
    ap.add_argument("--list", action="store_true", help="列出所有保留片段")
    ap.add_argument("--plan", default=str(BASE / "out_video_understand" / "compact_result.json"))
    args = ap.parse_args()
    keeps = kept_ranges(Path(args.plan))
    if args.list:
        for s, e in keeps:
            print(f"保留 [{s:.2f}-{e:.2f}] ({e-s:.2f}s)")
        print(f"共 {len(keeps)} 段")
        return
    if args.map is not None:
        dst = src_to_dst(args.map, keeps)
        print(f"原视频 {args.map:.2f}s -> 成片 {dst}s" if dst is not None
              else f"原视频 {args.map:.2f}s 落在删除段内(已剪掉)")


if __name__ == "__main__":
    main()
