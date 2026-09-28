"""H3 clips -> frame sequences for the engine's VideoPlate (app/src/engine/video.ts).

    python tools/clips.py <id> [<id> ...]        convert yichu/clips_src/<id>.mp4
    python tools/clips.py --all                  every clips_src/*.mp4 that is new or changed since its last conversion
    python tools/clips.py <id> --src other.mp4   convert another file under that id (one id only)
    python tools/clips.py --list                 what is converted, what is new/changed/missing
    python tools/clips.py --rm <id> [<id> ...]   delete converted frames
    options: --quality 90 (JPEG)  --force (reconvert even if up to date)

Output: app/public/clips/<id>/00000.jpg, 00001.jpg ... (frame index from 0, 1920x1080: the source is scaled to
cover 16:9 with lanczos and centre-cropped -- 1344x768 loses ~9 px top and bottom, 960x544 loses 4) and
meta.json {id, fps, frames, duration, width, height, pattern, version, src: {file, width, height, fps, frames}}.
A conversion is written to a temp dir and swapped in at the end, so a running render never sees half a clip.
Run with the film's venv: D:/Projects/ai-film/.venv/Scripts/python.exe (needs Pillow; ffmpeg/ffprobe on PATH).
"""
import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "clips_src"
OUT = ROOT / "app" / "public" / "clips"
W, H = 1920, 1080
PATTERN = "%05d.jpg"


def probe(src: Path) -> dict:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=width,height,r_frame_rate,nb_read_frames,duration", "-of", "json", str(src)],
        capture_output=True, text=True, check=True)
    s = json.loads(r.stdout)["streams"][0]
    return {"width": int(s["width"]), "height": int(s["height"]), "fps": float(Fraction(s["r_frame_rate"])),
            "frames": int(s.get("nb_read_frames") or 0), "duration": float(s.get("duration") or 0)}


def stamp(src: Path) -> dict:
    st = src.stat()
    return {"size": st.st_size, "mtime": round(st.st_mtime, 3)}


def up_to_date(cid: str, src: Path) -> bool:
    meta = OUT / cid / "meta.json"
    if not meta.exists():
        return False
    try:
        m = json.loads(meta.read_text("utf-8"))
    except Exception:
        return False
    s = m.get("src", {})
    return s.get("size") == stamp(src)["size"] and s.get("mtime") == stamp(src)["mtime"] and m.get("frames", 0) > 0


def convert(cid: str, src: Path, quality: int) -> dict:
    t0 = time.time()
    info = probe(src)
    tmp = OUT / f".{cid}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos+accurate_rnd+full_chroma_int,"
          f"crop={W}:{H},format=rgb24")
    ff = subprocess.Popen(["ffmpeg", "-v", "error", "-nostdin", "-threads", "4", "-i", str(src), "-vf", vf,
                           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    size = W * H * 3
    n = 0

    def save(i: int, buf: bytes):
        Image.frombuffer("RGB", (W, H), buf, "raw", "RGB", 0, 1).save(tmp / (PATTERN % i), "JPEG", quality=quality)

    # JPEG encoding releases the GIL: a few threads, with a bounded backlog (each raw frame is 6 MB)
    with ThreadPoolExecutor(4) as pool:
        pending = []
        while True:
            buf = ff.stdout.read(size)
            if len(buf) < size:
                break
            pending.append(pool.submit(save, n, buf))
            n += 1
            if len(pending) >= 8:
                pending.pop(0).result()
        for p in pending:
            p.result()
    if ff.wait() != 0 or n == 0:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError(f"ffmpeg failed on {src} ({n} frames)")
    fps = info["fps"] or 24.0
    meta = {
        "id": cid, "fps": fps, "frames": n, "duration": round(n / fps, 4), "width": W, "height": H,
        "pattern": PATTERN, "quality": quality, "version": int(time.time()),
        "src": {"file": src.name if src.parent == SRC else str(src), "width": info["width"], "height": info["height"],
                "fps": fps, "frames": info["frames"] or n, **stamp(src)},
        "made": dt.datetime.now().replace(microsecond=0).isoformat(),
    }
    (tmp / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
    dst = OUT / cid
    old = OUT / f".{cid}.old"
    shutil.rmtree(old, ignore_errors=True)
    if dst.exists():
        dst.rename(old)
    tmp.rename(dst)
    shutil.rmtree(old, ignore_errors=True)
    mb = sum(f.stat().st_size for f in dst.glob("*.jpg")) / 1e6
    print(f"{cid}: {info['width']}x{info['height']} @ {fps:g} fps -> {n} frames {W}x{H} q{quality} "
          f"({mb:.0f} MB, {time.time() - t0:.1f} s)")
    return meta


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--src")
    ap.add_argument("--quality", type=int, default=90)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--rm", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    if a.list:
        done = {p.name for p in OUT.iterdir() if (p / "meta.json").exists()}
        srcs = {p.stem: p for p in SRC.glob("*.mp4")} if SRC.exists() else {}
        for cid in sorted(done | set(srcs)):
            if cid in srcs and cid in done:
                state = "ok" if up_to_date(cid, srcs[cid]) else "CHANGED (rerun)"
            elif cid in srcs:
                state = "NEW (not converted)"
            else:
                state = "converted (source gone)"
            print(f"{cid:24s} {state}")
        return

    if a.rm:
        for cid in a.ids:
            shutil.rmtree(OUT / cid, ignore_errors=True)
            print(f"removed {OUT / cid}")
        return

    if a.src:
        if len(a.ids) != 1:
            sys.exit("--src takes exactly one id")
        jobs = [(a.ids[0], Path(a.src).resolve())]
    elif a.all:
        jobs = [(p.stem, p) for p in sorted(SRC.glob("*.mp4"))]
    else:
        jobs = [(cid, SRC / f"{cid}.mp4") for cid in a.ids]
    if not jobs:
        sys.exit("nothing to do (give clip ids, or --all)")
    bad = 0
    for cid, src in jobs:
        if not src.exists():
            print(f"{cid}: no source {src}")
            bad += 1
            continue
        if not a.force and up_to_date(cid, src):
            print(f"{cid}: up to date")
            continue
        try:
            convert(cid, src, a.quality)
        except Exception as e:  # keep going with the others
            print(f"{cid}: FAILED {e}")
            bad += 1
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
