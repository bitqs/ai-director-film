# 时间轴：把每句旁白排到 120 BPM 的节拍网格上，段落从小节线开始。
# 输出 data/plan.json（段落与每句的起止）、data/lyrics.json（给渲染器：逐词/逐字时间）、audio/vo_track.wav。
import json, math, sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).parent))
from script import LINES

ROOT = Path(__file__).resolve().parent.parent
BPM = 120.0
BEAT = 60.0 / BPM
BAR = 4 * BEAT
SR = 48000
GRID = BEAT / 2  # lines start on 8th notes

vo = {x["id"]: x for x in json.loads((ROOT / "data/vo.json").read_text("utf-8"))}
text_of = {l["id"]: l.get("show", None) for l in LINES}

# Each section: (name, min_bars, items). Items:
#   ("line", id, {gap: s after the previous line's speech, hit: (text, "bar"|"beat") puts that word's start on the grid})
#   ("at", beats)  -> next line not before section start + beats
#   ("tail", s)    -> section lasts at least until last speech end + s
# The section ends on the next bar line after max(content, min_bars).
SECTIONS = [
    ("open", 7, [("at", 1), ("line", "o1", {}), ("line", "o2", {"gap": 0.5}), ("line", "o3", {"gap": 0.5}),
                 ("line", "o4", {"gap": 0.25, "hit": ("爆表", "bar")}), ("tail", 1.5)]),
    ("code", 15, [("at", 2), ("line", "c1", {}), ("line", "c2", {"gap": 0.5, "hit": ("摄像机", "bar")}), ("line", "c3", {"hit": ("演员", "bar")}),
                  ("line", "c4", {"hit": ("AI", "bar")}), ("line", "c5", {"gap": 1.0}), ("tail", 2.0)]),
    ("spark", 8, [("at", 2), ("line", "s1", {}), ("line", "s2", {"gap": 0.5, "hit": ("变成", "bar")}), ("tail", 1.5)]),
    ("title", 4, []),
    ("cross", 18, [("at", 20), ("line", "k1", {}), ("line", "k2", {"gap": 0.4}), ("line", "k3", {"gap": 0.5}), ("tail", 4.0)]),
    ("wild", 20, [("at", 4), ("line", "w1", {"hit": ("四十二", "bar")}), ("line", "w2", {"gap": 3.0}), ("tail", 4.0)]),
    ("overflow", 16, [("at", 2), ("line", "v1", {}), ("at", 54), ("line", "v2", {"hit": ("溢出", "bar")}), ("tail", 2.5)]),   # v2: climax +2 bars (user: 让高潮再多来几秒)
    ("end", 10, [("at", 4), ("line", "e1", {}), ("line", "e2", {"gap": 0.8}), ("line", "e3", {"gap": 1.6}), ("tail", 3.5)]),
]



def snap_up(t, g):
    return math.ceil(t / g - 1e-6) * g


def build():
    t_sec = 0.0
    sections, lines = [], []
    for name, min_bars, items in SECTIONS:
        start = t_sec
        cursor = start  # earliest time for the next line's first syllable
        last_end = start
        tail = 0.0
        for it in items:
            if it[0] == "at":
                cursor = max(cursor, start + it[1] * BEAT)
            elif it[0] == "tail":
                tail = it[1]
            elif it[0] == "line":
                lid, opt = it[1], it[2]
                v = vo[lid]
                first = v["words"][0]["start"]
                s_end = v["words"][-1]["end"]
                earliest = max(cursor, last_end + opt.get("gap", 0.0) if lines and last_end > start else cursor)
                if "hit" in opt:
                    word, unit = opt["hit"]
                    w0 = v["chars"][v["say"].index(word)][0]
                    g = BAR if unit == "bar" else BEAT
                    # clip offset so that `word` starts on the grid, not before `earliest`
                    ws = snap_up(earliest + (w0 - first), g)
                    clip = ws - w0
                else:
                    ws = snap_up(earliest, GRID)
                    clip = ws - first
                sp0, sp1 = clip + first, clip + s_end
                lines.append({"id": lid, "section": name, "clip": round(clip, 4), "start": round(sp0, 4), "end": round(sp1, 4), "dur": v["dur"]})
                last_end = sp1
                cursor = sp1
        content_end = max(last_end + tail, start + min_bars * BAR) if items else start + min_bars * BAR
        end = snap_up(content_end, BAR)
        sections.append({"name": name, "start": round(start, 4), "end": round(end, 4), "bar0": round(start / BAR), "bar1": round(end / BAR)})
        t_sec = end
    return sections, lines, t_sec


def main():
    sections, lines, total = build()
    total_out = total + 0.0
    print(f"{'section':8} {'bars':>9} {'start':>7} {'end':>7}")
    for s in sections:
        print(f"{s['name']:8} {s['bar0']:>4}-{s['bar1']:<4} {s['start']:7.2f} {s['end']:7.2f}")
    print(f"total {total_out:.2f}s = {int(total_out // 60)}:{total_out % 60:05.2f}  ({total_out / BAR:.0f} bars)")
    if "--print" in sys.argv:
        for l in lines:
            print(f"  {l['id']:3} {l['start']:7.2f} -> {l['end']:7.2f}  {vo[l['id']]['say']}")

    # lyrics.json for the renderer: absolute word and char times
    out_lines = []
    for l in lines:
        v = vo[l["id"]]
        off = l["clip"]
        # what the screen shows: `show` when the script has one (same length as `say`, char timings carry over 1:1)
        show = text_of.get(l["id"])
        text = show if show and len(show) == len(v["say"]) else v["say"]
        words = [{"w": w["w"], "start": round(w["start"] + off, 4), "end": round(w["end"] + off, 4)} for w in v["words"]]
        chars = [[round(a + off, 4), round(b + off, 4)] for a, b in v["chars"]]
        out_lines.append({"id": l["id"], "section": l["section"], "text": text, "start": l["start"], "end": l["end"], "words": words, "chars": chars})
    (ROOT / "data/lyrics.json").write_text(json.dumps({"lines": out_lines}, ensure_ascii=False, indent=1), "utf-8")
    (ROOT / "data/plan.json").write_text(json.dumps({"bpm": BPM, "duration": total_out, "sections": sections, "lines": lines}, ensure_ascii=False, indent=1), "utf-8")

    # the voice track, clips placed at their offsets
    track = np.zeros(int(math.ceil(total_out * SR)) + SR, dtype=np.float32)
    for l in lines:
        x, sr = sf.read(ROOT / f"audio/vo/{l['id']}.wav", dtype="float32")
        assert sr == SR
        i0 = int(round(l["clip"] * SR))
        if i0 < 0:
            x, i0 = x[-i0:], 0
        track[i0:i0 + len(x)] += x[: len(track) - i0]
    sf.write(ROOT / "audio/vo_track.wav", track[: int(total_out * SR)], SR, subtype="FLOAT")


if __name__ == "__main__":
    main()
