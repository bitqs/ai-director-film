# 旁白脚本：一行一句，id 前缀即所属场景。`at` 是这句开始的拍号（120 BPM，一拍 0.5 s，一小节 4 拍），
# 由 plan.py 排好；这里只放文字。`say` 是念的，`show` 是画面上显示的（默认同 say）。
# 《溢出》：《足够震撼》续集。贯穿道具是震撼度仪表；前半代码画面，后半 H3 写实画面，跨界靠首尾帧转场。

LINES = [
    # ---- open：冷开场（上一部的仪表重启）
    dict(id="o1", say="我是 Opus 五点五。", show="我是 Opus 5.5。"),
    dict(id="o2", say="上一部结尾，震撼度爆表了。我算不出来。"),
    dict(id="o3", say="这一次，我想看看——"),
    dict(id="o4", say="爆表之后，是什么。"),
    # ---- code：代码的世界
    dict(id="c1", say="上一部，每一帧都是我算出来的。"),
    dict(id="c2", say="摄像机，零台。"),
    dict(id="c3", say="演员，零个。"),
    dict(id="c4", say="AI生成的画面，零张。"),
    dict(id="c5", say="这一次，我想要真实。"),
    # ---- spark：第一次跨界
    dict(id="s1", say="所以这一次，我找了个帮手：一个视频模型。"),
    dict(id="s2", say="我负责算。它负责——变成真的。"),
    # ---- cross：三次跨界
    dict(id="k1", say="每一次跨过去，第一帧是我算的。"),
    dict(id="k2", say="最后一帧，是它画的。"),
    dict(id="k3", say="中间，让它自己接上。"),
    # ---- wild：失控
    dict(id="w1", say="震撼度，四十二。"),
    dict(id="w2", say="这个数，开始不受控制了。"),
    # ---- overflow：溢出
    dict(id="v1", say="上一部，我只算到十的三百零八次方。"),
    dict(id="v2", say="震撼度：溢出。"),
    # ---- end：结尾
    dict(id="e1", say="我还是算不出来。"),
    dict(id="e2", say="但这一次，你看到了。"),
    dict(id="e3", say="下一部拍什么，你说了算。"),
]


def zh_number(n: int) -> str:
    """Integer -> Chinese reading (up to 99,999,999), e.g. 11640 -> 一万一千六百四十, 12120 -> 一万两千一百二十."""
    digits = "零一二三四五六七八九"
    units = ["", "十", "百", "千"]

    def four(x: int) -> str:
        s, zero = "", False
        for i in range(3, -1, -1):
            d = x // 10**i % 10
            if d == 0:
                zero = bool(s)
                continue
            if zero:
                s += "零"
                zero = False
            s += ("两" if d == 2 and i >= 2 else digits[d]) + units[i]  # 两千 / 两百，二十
        return s

    if n == 0:
        return "零"
    hi, lo = divmod(n, 10000)
    s = (("两" if hi == 2 else four(hi)) + "万" if hi else "") + ("零" if hi and 0 < lo < 1000 else "") + four(lo)
    return s[1:] if s.startswith("一十") else s
