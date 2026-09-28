# MiniMax H3 through the official API (MiniMax 开放平台, mainland host), for 2K takes of shots the local GPU made at 1344x768.
# Same prompts as the local runs (prompts/<id>.txt, the official T2VA three-section format). Output: api_out/<prefix>.mp4
# (2560x1440 @ 24 fps for 2K, stereo). The key is read from yichu/.env (MINIMAX_API_KEY) and never printed.
#
#   python h3/h3_api.py run <id> [<id> ...] [--secs 6] [--res 2K] [--ratio 16:9] [--tag 2k]   submit all, then wait + download
#   python h3/h3_api.py submit <id> ... / wait [<prefix> ...] / status                        (tasks are kept in api_tasks.json)
# Prices (2026-09): MiniMax-H3 768P ¥0.50/s, 2K ¥0.80/s.
import argparse, json, sys, time, urllib.error, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
HOST = "https://api.minimaxi.com"
TASKS = HERE / "api_tasks.json"
OUT = HERE / "api_out"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # domestic host: no proxy


def key() -> str:
    env = dict(l.split("=", 1) for l in (ROOT / ".env").read_text("utf-8").splitlines() if "=" in l)
    return env["MINIMAX_API_KEY"].strip()


def call(method: str, path: str, body: dict | None = None, tries: int = 4) -> dict:
    req = urllib.request.Request(HOST + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + key(), "Content-Type": "application/json"})
    for k in range(tries):
        try:
            return json.loads(OPENER.open(req, timeout=60).read())
        except urllib.error.HTTPError as e:
            return {"http_error": e.code, "body": e.read().decode("utf-8", "replace")[:500]}
        except urllib.error.URLError as e:
            # connection-level failure (the request never reached the server): safe to retry, even for a submit
            print(f"  network error ({e.reason}), retry {k + 1}/{tries - 1}", flush=True)
            time.sleep(5 * (k + 1))
    return {"network_error": True}


def load() -> dict:
    return json.loads(TASKS.read_text("utf-8")) if TASKS.exists() else {}


def save(t: dict):
    TASKS.write_text(json.dumps(t, ensure_ascii=False, indent=1), "utf-8")


def submit(ids, secs, res, ratio, tag):
    tasks = load()
    for i in ids:
        prompt = (HERE / "prompts" / f"{i}.txt").read_text("utf-8").strip()
        body = {"model": "MiniMax-H3", "content": [{"type": "text", "text": prompt}], "duration": secs, "resolution": res, "ratio": ratio}
        r = call("POST", "/v2/video_generation", body)
        tid = r.get("task_id") or (r.get("task") or {}).get("id")
        prefix = f"{i}_{tag}"
        print(prefix, "->", tid or r, flush=True)
        if tid:
            tasks[prefix] = {"id": i, "task_id": tid, "secs": secs, "res": res, "submitted": time.strftime("%H:%M:%S"), "status": "submitted"}
            save(tasks)


def wait(prefixes=None, every=15):
    tasks = load()
    todo = [p for p in (prefixes or tasks) if tasks[p]["status"] not in ("done", "failed", "cancelled")]
    OUT.mkdir(exist_ok=True)
    while todo:
        for p in list(todo):
            r = call("GET", f"/v2/query/video_generation/{tasks[p]['task_id']}")
            t = r.get("task") or r
            st = t.get("status") or r.get("status")
            if st in ("succeeded", "success", "Success"):
                url = (t.get("content") or {}).get("url") or t.get("url")
                dst = OUT / f"{p}.mp4"
                with OPENER.open(url, timeout=300) as src:
                    dst.write_bytes(src.read())
                tasks[p].update(status="done", finished=time.strftime("%H:%M:%S"), file=str(dst))
                print(f"{time.strftime('%H:%M:%S')} DONE {p} -> {dst} ({dst.stat().st_size // 1024} KB)", flush=True)
                todo.remove(p)
            elif st in ("failed", "cancelled", "Fail"):
                tasks[p].update(status="failed", error=str(t.get("error") or r)[:300])
                print(f"{time.strftime('%H:%M:%S')} FAIL {p}: {tasks[p]['error']}", flush=True)
                todo.remove(p)
            elif st is None:
                print(f"{time.strftime('%H:%M:%S')} ?? {p}: {str(r)[:300]}", flush=True)
            save(tasks)
        if todo:
            time.sleep(every)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "submit", "wait", "status"])
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--secs", type=int, default=6)
    ap.add_argument("--res", default="2K")
    ap.add_argument("--ratio", default="16:9")
    ap.add_argument("--tag", default="2k")
    a = ap.parse_args()
    if a.cmd in ("run", "submit"):
        submit(a.ids, a.secs, a.res, a.ratio, a.tag)
    if a.cmd in ("run", "wait"):
        wait([f"{i}_{a.tag}" for i in a.ids] if a.cmd == "run" else (a.ids or None))
    if a.cmd == "status":
        for p, t in load().items():
            print(p, t["status"], t.get("submitted"), t.get("finished", ""), t.get("error", ""))
