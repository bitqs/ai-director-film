# 逐句合成旁白，存 audio/vo/<id>.wav 和 data/vo.json（每句的时长、逐词与逐字时间）。
# 默认用火山豆包语音合成 2.0（密钥在 .env 的 VOLC_SPEECH_API_KEY），PROVIDER = "edge" 可退回 edge-tts（走本机代理）。
# 每句响度统一到 TARGET_LUFS（旧 edge 旁白的中位数），synth.py 的人声链不用改。
# 文字、音色、风格都没变的句子不重做。用法：python tools/tts.py [--force]
import asyncio, base64, hashlib, json, subprocess, sys, urllib.request, uuid
from pathlib import Path

import numpy as np
import pyloudnorm as pyln
import soundfile as sf

sys.path.insert(0, str(Path(__file__).parent))
from script import LINES, zh_number   # 旁白台词表：见 script_示例.py（在你的工程里命名为 tools/script.py）

ROOT = Path(__file__).resolve().parent.parent
VO = ROOT / "audio" / "vo"
OUT = ROOT / "data" / "vo.json"
PARAMS = ROOT / "data" / "params.json"
SR = 48000
TARGET_LUFS = -23.8
PUNCT = "，。：；？！、,.:;?!"  # 豆包把句读粘在前一个字上（"画，"）：去掉，句读在 chars 里占零长度

PROVIDER = "doubao"
# 豆包：高冷沉稳 2.0；风格指令对每句都一样
DOUBAO = dict(resource="seed-tts-2.0", speaker="zh_male_gaolengchenwen_uranus_bigtts",
              style="用冷静、克制、略带神秘感的语气，像电影预告片的旁白，语速稍慢。")
# edge-tts（旧）
EDGE = dict(voice="zh-CN-YunjianNeural", rate="-4%", pitch="-2Hz", proxy="http://127.0.0.1:7890")


def env() -> dict:
    return dict(l.split("=", 1) for l in (ROOT / ".env").read_text("utf-8").splitlines() if "=" in l and not l.startswith("#"))


def fill(text: str, params: dict) -> str:
    n = params["code_lines"]
    approx = zh_number(n // 1000 * 1000) + "多" if n >= 1000 else zh_number(n)  # 14390 -> 一万四千多
    return text.format(code_approx=approx, frames_zh=zh_number(params["frames"]))


def char_times(say: str, words: list[dict]) -> list[list[float]]:
    """Per character of `say`: [start, end] from the word boundaries (even split inside a word);
    punctuation and anything unmatched gets a zero-length slot at the previous char's end."""
    out: list[list[float]] = []
    i, t = 0, words[0]["start"] if words else 0.0
    for w in words:
        j = say.find(w["w"], i)
        if j < 0:
            continue
        for _ in range(i, j):  # punctuation before this word
            out.append([t, t])
        n = len(w["w"])
        for k in range(n):
            a = w["start"] + (w["end"] - w["start"]) * k / n
            out.append([a, w["start"] + (w["end"] - w["start"]) * (k + 1) / n])
        i, t = j + n, w["end"]
    while len(out) < len(say):
        out.append([t, t])
    return [[round(a, 4), round(b, 4)] for a, b in out]


def voice_id() -> str:
    return f"doubao|{DOUBAO['resource']}|{DOUBAO['speaker']}|{DOUBAO['style']}" if PROVIDER == "doubao" else f"{EDGE['voice']}|{EDGE['rate']}|{EDGE['pitch']}"


def synth_doubao(text: str) -> tuple[np.ndarray, list[dict]]:
    rp = {"text": text, "speaker": DOUBAO["speaker"],
          "audio_params": {"format": "pcm", "sample_rate": SR, "enable_subtitle": True},
          "additions": json.dumps({"context_texts": [DOUBAO["style"]]}, ensure_ascii=False)}
    req = urllib.request.Request("https://openspeech.bytedance.com/api/v3/tts/unidirectional",
                                 data=json.dumps({"user": {"uid": "ai-film"}, "req_params": rp}).encode(),
                                 headers={"X-Api-Key": env()["VOLC_SPEECH_API_KEY"], "X-Api-Resource-Id": DOUBAO["resource"],
                                          "X-Api-Request-Id": str(uuid.uuid4()), "Content-Type": "application/json"})
    pcm, words, last = b"", [], None
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=120) as r:  # 国内服务，不走代理
        for line in r:
            if not line.strip():
                continue
            j = json.loads(line)
            last = j
            if j.get("data"):
                pcm += base64.b64decode(j["data"])
            # 每个分句一条，逐字时间是整句音频里的绝对时间（整段文字那条的 words 为空）
            for w in (j.get("sentence") or {}).get("words") or []:
                words.append({"w": w["word"].strip().rstrip(PUNCT), "start": round(w["startTime"], 4), "end": round(w["endTime"], 4)})
    if not pcm or (last or {}).get("code") != 20000000:
        raise RuntimeError(f"doubao: {last}")
    x = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0
    return x, [w for w in words if w["w"]]


async def synth_edge(text: str) -> tuple[np.ndarray, list[dict]]:
    import edge_tts
    c = edge_tts.Communicate(text, EDGE["voice"], rate=EDGE["rate"], pitch=EDGE["pitch"], boundary="WordBoundary", proxy=EDGE["proxy"])
    mp3, words = b"", []
    async for ch in c.stream():
        if ch["type"] == "audio":
            mp3 += ch["data"]
        elif ch["type"] == "WordBoundary":
            s = ch["offset"] / 1e7
            words.append({"w": ch["text"], "start": round(s, 4), "end": round(s + ch["duration"] / 1e7, 4)})
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-ac", "1", "-ar", str(SR), "-f", "f32le", "pipe:1"], input=mp3, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype="<f4").copy(), words


async def synth(line: dict, text: str) -> dict:
    x, words = synth_doubao(text) if PROVIDER == "doubao" else await synth_edge(text)
    lufs = pyln.Meter(SR).integrated_loudness(x.astype(np.float64)) if len(x) > SR * 0.4 else TARGET_LUFS
    x = x * 10 ** ((TARGET_LUFS - lufs) / 20)
    sf.write(VO / f"{line['id']}.wav", x.astype(np.float32), SR, subtype="FLOAT")
    return {"id": line["id"], "say": text, "dur": round(len(x) / SR, 4), "words": words, "chars": char_times(text, words)}


async def main():
    force = "--force" in sys.argv
    VO.mkdir(parents=True, exist_ok=True)
    params = json.loads(PARAMS.read_text("utf-8")) if PARAMS.exists() else {"code_lines": 4000, "frames": 11640}
    old = {x["id"]: x for x in json.loads(OUT.read_text("utf-8"))} if OUT.exists() else {}
    res = []
    for line in LINES:
        text = fill(line["say"], params)
        key = hashlib.sha1(f"{voice_id()}|{text}".encode()).hexdigest()[:12]
        o = old.get(line["id"])
        if not force and o and o.get("key") == key and (VO / f"{line['id']}.wav").exists():
            res.append(o)
            continue
        for attempt in range(4):
            try:
                r = await synth(line, text)
                break
            except Exception as e:  # flaky network: retry
                print(f"{line['id']} retry {attempt}: {e!r}"[:200])
                await asyncio.sleep(2 * (attempt + 1))
        else:
            raise SystemExit(f"tts failed: {line['id']}")
        r["key"] = key
        print(f"{r['id']}  {r['dur']:.2f}s  {text}")
        res.append(r)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), "utf-8")
    print(f"total speech {sum(x['dur'] for x in res):.1f}s in {len(res)} lines")


asyncio.run(main())
