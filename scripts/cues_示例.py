# 《溢出》的音画同步点：场景（app/src/scenes/*）、配乐（synth.py）、H3 镜头（h3/）和剪辑都从 data/cues.json 读同一份时间。
# 时间来自排好的旁白（data/lyrics.json）和节拍网格（data/plan.json，120 BPM：一拍 0.5 s，一小节 2 s）。
#
# 关键约定
# - meter：震撼度仪表的关键帧 [t, value, mode]。value 是显示用的字符串；mode：
#   "nan" 故障闪烁 / "set" 在这一拍跳到新值 / "roll" 从上一个值滚动到新值（持续到下一个关键帧）/
#   "burst" 位数失控的数字瀑布 / "overflow" 显示「溢出」/ "off" 仪表隐藏。
# - H3 片段在时间轴上的位置：[start, end, clip_id]。H3 是 24 fps，首尾帧转场（fl2v）固定 124 帧 = 5.1667 s；
#   转场的第一帧 = 代码画面在 start 这一刻的那一帧（所以切换是无缝的），最后一帧 = 对应写实镜头的第一帧。
import json, math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BEAT, BAR = 0.5, 2.0
FL2V = 124 / 24
CLIMAX_EXTRA = 2 * 2.0   # v2: +2 bars of climax (fireworks + 算) before the white

plan = json.loads((ROOT / "data/plan.json").read_text("utf-8"))
lyr = {l["id"]: l for l in json.loads((ROOT / "data/lyrics.json").read_text("utf-8"))["lines"]}
sec = {s["name"]: s for s in plan["sections"]}


def word(lid: str, text: str, nth: int = 0, end: bool = False) -> float:
    l, i = lyr[lid], -1
    for _ in range(nth + 1):
        i = l["text"].index(text, i + 1)
    return round(l["chars"][i + len(text) - 1][1] if end else l["chars"][i][0], 4)


def s(name: str, key: str = "start") -> float:
    return sec[name][key]


def snap(t: float, g: float = BEAT) -> float:
    return round(round(t / g) * g, 4)


def build() -> dict:
    c: dict = {"sections": {k: [v["start"], v["end"]] for k, v in sec.items()}}
    # ---- open: the old meter reboots from NaN to 0.00
    c["open_reboot"] = snap(lyr["o3"]["start"] - 0.25)          # NaN flickers through "上一部结尾，震撼度爆表了", resets on "这一次"
    c["open_boom"] = word("o4", "爆表")                       # low boom on the hook
    # ---- code: the ledger stamps (callback to part one) and the line "这一次，我想要真实。"
    c["stamps"] = [word("c2", "零"), word("c3", "零"), word("c4", "零")]
    c["want_real"] = lyr["c5"]["start"]
    c["code_squeeze"] = snap(lyr["c5"]["start"] - 1.0, BAR)  # all code visuals squeezed into one line of text
    # ---- spark: the first crossing (code spark -> real welding sparks)
    t_turn = word("s2", "变成")
    c["spark_fl2v"] = [round(t_turn - 2.0, 4), round(t_turn - 2.0 + FL2V, 4)]
    c["spark_real"] = word("s2", "真的")                      # meter slams into 1.00
    # ---- title
    c["title"] = s("title")
    # title beats (C's title.ts reads these; same values as its fallbacks): numbers flip into 溢出, fuse, subtitle types, melt, swap to cross
    t0 = s("title")
    c["title_show"], c["title_fuse"], c["title_sub"], c["title_melt"], c["title_swap"] = t0 + 1.0, t0 + 2.0, t0 + 2.6, t0 + 6.75, t0 + 7.0
    # ---- cross: three crossings, 6 bars each: 2 bars code, then the fl2v clip, then the real shot
    x0 = s("cross")
    c["crossings"] = []
    for i, name in enumerate(("city", "storm", "wave")):
        a = x0 + i * 6 * BAR
        c["crossings"].append({"name": name, "code": [a, a + 2 * BAR], "fl2v": [a + 2 * BAR, round(a + 2 * BAR + FL2V, 4)],
                               "real": [round(a + 2 * BAR + FL2V, 4), a + 6 * BAR], "jump": round(a + 2 * BAR + FL2V, 4)})
    # ---- wild: montage of real shots, one per 1-2 beats; meter runs away
    w0, w1 = s("wild"), s("wild", "end")
    c["wild_42"] = word("w1", "四十二")
    c["wild_cuts"] = [round(w0 + k * BEAT * 2, 4) for k in range(int((w1 - w0) / (BEAT * 2)))]   # every 2 beats; scenes may subdivide
    # ---- overflow: the climax
    o0 = s("overflow")
    c["of_record"] = lyr["v1"]["start"]                      # 10^308: "上一部，我只算到十的三百零八次方" (the float ceiling; film 1 went 10^64 → googol → 10^308 → ∞ → ERR)
    c["of_waterfall"] = [round(lyr["v1"]["end"] + 0.25, 4), o0 + 12.0]
    c["of_cracks"] = [round(o0 + 12.0 + k * BEAT, 4) for k in range(8)]   # one crack per beat
    c["of_shatter"] = o0 + 16.0                              # glass breaks, reality floods in
    X = CLIMAX_EXTRA                                         # v2: the climax holds 2 bars longer before the white (user: 让高潮再多来几秒)
    c["of_fireworks"] = [o0 + 16.0, o0 + 22.0 + X]           # H3 fireworks + code-drawn 算 above the city
    c["of_white"] = o0 + 22.0 + X
    c["of_silence"] = [o0 + 22.5 + X, o0 + 23.5 + X]
    c["of_word"] = o0 + 23.5 + X                             # the meter shows 「溢出」
    # v3: a heartbeat after 「溢出」 (user: 加点glitch，然后接类似心跳的滴滴声): the first 嘀 at of_word, then a double beep
    # (lub-dub, the second HEART_DUB s later) once a second on the bar/half-bar grid, through the start of `end`
    c["of_heart"] = [round(c["of_word"] + 0.5 + k, 4) for k in range(7)]
    c["of_heart_dub"] = 0.25
    # ---- end
    c["end_zero"] = s("end") + 1.0
    c["loop"] = s("end", "end") - BAR
    # ---- the meter track
    M = []
    M += [[0.0, "NaN", "nan"], [c["open_reboot"], "0.00", "set"]]
    M += [[lyr["c1"]["start"], "0.00", "set"], [c["stamps"][0], "0.10", "set"], [c["stamps"][1], "0.21", "set"], [c["stamps"][2], "0.31", "set"],
          [lyr["c5"]["start"], "0.62", "roll"]]                  # each stamp kicks the needle; then it creeps toward 0.62
    M += [[c["spark_real"], "1.00", "set"]]
    for i, v in enumerate(("2.00", "5.00", "10.0")):
        M.append([c["crossings"][i]["jump"], v, "set"])
    M += [[c["wild_42"], "42.0", "set"], [w0 + 16.0, "1 000", "set"], [w0 + 26.0, "10⁶", "set"], [w0 + 32.0, "10⁹", "set"]]
    M += [[c["of_record"], "10³⁰⁸", "set"], [c["of_waterfall"][0], "10³⁰⁸", "burst"], [c["of_shatter"], "", "off"],
          [c["of_word"], "溢出", "overflow"], [c["end_zero"], "0.00", "set"]]
    c["meter"] = [[round(t, 4), v, m] for t, v, m in M]
    return c


if __name__ == "__main__":
    c = build()
    (ROOT / "data/cues.json").write_text(json.dumps(c, ensure_ascii=False, indent=1), "utf-8")
    for k, v in c.items():
        if k not in ("meter", "sections", "crossings"):
            print(f"{k:14} {v}")
    for x in c["crossings"]:
        print("crossing", x)
    for m in c["meter"]:
        print("meter", m)
