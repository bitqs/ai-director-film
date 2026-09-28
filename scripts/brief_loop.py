# 每 10 分钟往飞书发一条《溢出》制作进度简报（任务状态 + H3 出片数 + 预计剩余时间）。
# 任务状态来自 STATUS.json（总导演在 agent 交活时更新），H3 进度来自 clips_src/ 和 ComfyUI 队列。
# 全部任务完成（或 STATUS.json 里 "stop": true）时发最后一条并退出。用法：python tools/brief_loop.py [--once]
import datetime as dt, json, os, shutil, subprocess, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USER = os.environ.get("FEISHU_USER_OPEN_ID", "ou_你的飞书open_id")   # 发给谁：你自己的飞书 open_id
EVERY = 600
WILD = ["spark_real", "city_real", "storm_real", "wave_real", "fireworks"] + [f"wild_{k}" for k in
        ("supercell", "volcano", "rocket", "aurora", "citylights", "lightning", "glacier", "sandstorm", "underwater", "milkyway")]
FL2V = ["spark_fl2v", "city_fl2v", "storm_fl2v", "wave_fl2v"]


def now():
    return dt.datetime.now().replace(microsecond=0)


def parse(s):
    return dt.datetime.fromisoformat(s) if s else None


def queue():
    try:
        d = json.loads(urllib.request.urlopen("http://127.0.0.1:8190/queue", timeout=5).read())
        return len(d["queue_running"]), len(d["queue_pending"])
    except Exception:
        return None


def gpu_cost(line):
    """Seconds of GPU for one queue line, fitted to runs.tsv (5 s: 270, 7.3 s: 456, 10.83 s: 881)."""
    p = line.split()
    if p[0] == "t2v":
        return 105 + 6.6 * float(p[3]) ** 2
    return 300.0   # cmd: a 5 s FL2V crossing plus uploads


def h3_plan(t):
    """(minutes until the last crossing is done, minutes until the H3 queue is empty), from h3/queue.txt, done.txt and runner.log.
    The first pending line is the job on the GPU; crossings not queued yet are assumed to go in before the wild clips."""
    h3 = ROOT / "h3"
    try:
        done = set((h3 / "done.txt").read_text("utf-8").split("\n"))
        pend = [l.strip() for l in (h3 / "queue.txt").read_text("utf-8").split("\n") if l.strip() and not l.startswith("#") and l.strip() not in done]
        started = None
        for l in (h3 / "logs" / "runner.log").read_text("utf-8", errors="replace").split("\n"):
            if " START " in l:
                started = dt.datetime.combine(t.date(), dt.time.fromisoformat(l[:8]))
    except Exception:
        return None
    total, fl_end = 0.0, 0.0
    for k, line in enumerate(pend):
        c = gpu_cost(line)
        if k == 0 and started:
            c = max(30.0, c - (t - started).total_seconds())
        total += c
        if line.startswith("cmd ") and line.split()[1] in FL2V:
            fl_end = total
    queued = {l.split()[1] for l in pend if l.startswith("cmd ")}
    extra = 300.0 * sum(1 for n in FL2V if n not in queued and not (ROOT / "clips_src" / f"{n}.mp4").exists())
    return (fl_end + extra) / 60, (total + extra) / 60


def estimate(st, t):
    """Critical-path finish time per task (minutes from now)."""
    tasks = {x["id"]: x for x in st["tasks"]}
    fin = {}
    plan = h3_plan(t)

    def remaining(x):
        if x["status"] == "done":
            return 0.0
        est = float(x.get("est_min", 30))
        if x["status"] == "running" and x.get("started"):
            el = (t - parse(x["started"])).total_seconds() / 60
            if x["id"] in ("E1", "E2") and plan:   # H3: the GPU queue itself (plus a few minutes to review the last clip)
                return (plan[1] if x["id"] == "E1" else plan[0]) + 5.0
            return max(est * 0.15, est - el)
        return est

    def f(i):
        if i in fin:
            return fin[i]
        x = tasks[i]
        start = max([f(d) for d in x.get("after", [])] + [0.0]) if x["status"] != "running" else 0.0
        fin[i] = start + remaining(x)
        return fin[i]

    for i in tasks:
        f(i)
    return fin


def brief():
    st = json.loads((ROOT / "STATUS.json").read_text("utf-8"))
    t = now()
    fin = estimate(st, t)
    done = [x for x in st["tasks"] if x["status"] == "done"]
    run = [x for x in st["tasks"] if x["status"] == "running"]
    wait = [x for x in st["tasks"] if x["status"] not in ("done", "running")]
    lines = [f"{st['film']} 进度简报 · {t:%H:%M}（开工 {int((t - parse(st['start'])).total_seconds() // 60)} 分钟）"]
    if done:
        lines.append("已完成：" + "、".join(x["name"] for x in done))
    for x in run:
        el = int((t - parse(x["started"])).total_seconds() // 60) if x.get("started") else 0
        lines.append(f"进行中：{x['name']}（已 {el} 分钟，预计还要 {int(round(fin[x['id']] - 0))} 分钟）")
    for x in wait:
        byid = {y["id"]: y for y in st["tasks"]}
        deps = "、".join(byid[d].get("short", byid[d]["name"]) for d in x.get("after", []) if byid[d]["status"] != "done")
        lines.append(f"等待中：{x['name']}" + (f"（等 {deps} 完成）" if deps else ""))
    got = [c for c in WILD if (ROOT / "clips_src" / f"{c}.mp4").exists()]
    fl = [c for c in FL2V if (ROOT / "clips_src" / f"{c}.mp4").exists()]
    q = queue()
    lines.append(f"H3 出片：写实 {len(got)}/{len(WILD)}，转场 {len(fl)}/{len(FL2V)}" + (f"；GPU 队列 {q[0]} 条在跑、{q[1]} 条排队" if q else "；GPU 服务未响应"))
    total = max(fin.values()) if fin else 0
    eta = t + dt.timedelta(minutes=total)
    all_done = all(x["status"] == "done" for x in st["tasks"])
    if all_done:
        lines.append("全部完成 ✅")
    else:
        lines.append(f"预计还要约 {int(total // 60)} 小时 {int(total % 60)} 分，成片约 {eta:%H:%M}")
    if st.get("note"):
        lines.append("备注：" + st["note"])
    return "\n".join(lines), all_done or st.get("stop")


def send(text):
    # call node + the CLI's run.js directly: the npm .cmd shim cuts multi-line arguments at the first newline
    run_js = Path.home() / "AppData/Roaming/npm/node_modules/@larksuite/cli/scripts/run.js"
    cmd = [shutil.which("node") or "node", str(run_js)] if run_js.exists() else [shutil.which("lark-cli.cmd") or "lark-cli.cmd"]
    r = subprocess.run(cmd + ["im", "+messages-send", "--as", "bot", "--user-id", USER, "--text", text], capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok = '"ok": true' in (r.stdout or "")
    print(f"[{now():%H:%M:%S}] sent={ok}\n{text}\n", flush=True)
    return ok


if __name__ == "__main__":
    while True:
        try:
            text, stop = brief()
            send(text)
        except Exception as e:
            print("brief failed:", e, flush=True); stop = False
        if stop or "--once" in sys.argv:
            break
        time.sleep(EVERY)
