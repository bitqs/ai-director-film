# Sequential H3 job runner for 《溢出》 (agent E). Only one job on the GPU at a time.
# Reads queue.txt line by line; each line runs once (key recorded in done.txt), so re-rolls can be appended while it runs.
#   t2v <id> <seed> <secs> [extra h3_shot2.py args]   -> prompts/<id>.txt, ComfyUI prefix yichu_<id>_s<seed>
#   cmd <tag> <command ...>                           -> any command (e.g. the FL2V test), output to logs/<tag>.log
# After each t2v job: 6-frame contact sheet check/<prefix>.jpg, first frame check/<prefix>_f0.png, line in runs.tsv.
# CUDA out-of-memory reported by ComfyUI -> one automatic retry at 960x544 (544p turbo), noted in runs.tsv.
# Server unreachable -> wait (never start/restart it). A job lost to a server crash is re-run once at full size, then
# (second crash) once at 960x544. Exits after the queue has been empty for IDLE seconds. Lock: runner.pid.
import os, re, shlex, subprocess, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
H3 = r"D:\Projects\ai-film-2\h3"
OUT = os.path.join(H3, "out")
URL = "http://127.0.0.1:8190"
PY = sys.executable
IDLE = int(os.environ.get("IDLE", "240"))
Q, DONE, RUNS, LOCK = (os.path.join(HERE, n) for n in ("queue.txt", "done.txt", "runs.tsv", "runner.pid"))
LOST = re.compile(r"actively refused|ConnectionRefused|ConnectionReset|RemoteDisconnected|URLError|timed out", re.I)
crashes = {}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def server_up():
    try:
        urllib.request.urlopen(URL + "/system_stats", timeout=10).read(); return True
    except Exception:
        return False


def wait_server():
    if server_up():
        return
    log("WAIT server down - waiting for the user to restart H3 (not touching it)")
    t0 = time.time()
    while not server_up():
        if time.time() - t0 > 3 * 3600:
            log("GIVE UP server down for 3 h - exiting"); sys.exit(3)
        time.sleep(20)
    log("SERVER BACK after %.0f s - starting in 60 s" % (time.time() - t0)); time.sleep(60)


def sheet(mp4, stem):
    """6 evenly spaced frames tiled 3x2 + full-size first frame."""
    try:
        nb = int(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=nb_frames",
                                 "-of", "csv=p=0", mp4], capture_output=True, text=True).stdout.strip() or 0)
    except ValueError:
        nb = 0
    nb = nb or 124
    idx = sorted({round(i * (nb - 1) / 5) for i in range(6)})
    sel = "+".join(f"eq(n\\,{i})" for i in idx)
    jpg = os.path.join(HERE, "check", stem + ".jpg"); png = os.path.join(HERE, "check", stem + "_f0.png")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", mp4, "-vf", f"select='{sel}',scale=640:-2,tile=3x2",
                    "-frames:v", "1", "-q:v", "3", jpg])
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", mp4, "-vf", "select='eq(n\\,0)'", "-frames:v", "1", png])
    return jpg, nb


def run_t2v(job, parts):
    """Returns 'lost' if the server died under the job (caller re-queues), else None."""
    sid, seed, secs, extra = parts[0], int(parts[1]), float(parts[2]), parts[3:]
    prompt = os.path.join(HERE, "prompts", sid + ".txt")
    small = crashes.get(job, 0) >= 2
    tries = [(f"yichu_{sid}_s{seed}" + ("_544" if small else ""),
              (["--w", "960", "--h", "544", "--turbo", "544"] if small else []) + list(extra),
              "server crashed twice at 1344x768 -> 960x544" if small else "")]
    for k, (prefix, ex, note) in enumerate(tries):
        wait_server()
        cmd = [PY, os.path.join(H3, "h3_shot2.py"), prompt, prefix, "--seed", str(seed), "--secs", str(secs)] + ex
        lf = os.path.join(HERE, "logs", prefix + ".log"); t0 = time.time()
        log("START", sid, f"s{seed}", f"{secs}s", " ".join(ex), note)
        with open(lf, "w", encoding="utf-8") as f:
            f.write(" ".join(cmd) + "\n"); f.flush()
            subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        txt = open(lf, encoding="utf-8", errors="replace").read(); dt = time.time() - t0
        m = re.search(r"done in \d+s (\S+) (\S+)", txt)
        status, fn = (m.group(1), m.group(2)) if m else ("error", "None")
        if status == "success" and fn != "None" and os.path.exists(os.path.join(OUT, fn)):
            jpg, nb = sheet(os.path.join(OUT, fn), prefix)
            with open(RUNS, "a", encoding="utf-8") as f:
                f.write("\t".join([sid, str(seed), str(secs), str(nb), time.strftime("%H:%M"), f"{dt:.0f}", fn, note or "ok"]) + "\n")
            log("DONE", sid, f"s{seed}", f"{dt:.0f}s", fn, "sheet=" + jpg, note)
            return None
        if not m and LOST.search(txt):
            crashes[job] = crashes.get(job, 0) + 1
            log("LOST", sid, f"s{seed}", f"{dt:.0f}s", "server unreachable during job (crash #%d) - will re-run" % crashes[job])
            with open(RUNS, "a", encoding="utf-8") as f:
                f.write("\t".join([sid, str(seed), str(secs), "-", time.strftime("%H:%M"), f"{dt:.0f}", "LOST", "server crashed/unreachable"]) + "\n")
            return "lost"
        oom = re.search(r"out of memory|OutOfMemory|OOM|CUDA error|allocat", txt, re.I)
        log("FAIL", sid, f"s{seed}", f"{dt:.0f}s", status, "OOM" if oom else "", "log=" + lf)
        if oom and k == 0 and not small:
            tries.append((prefix + "_544", ["--w", "960", "--h", "544", "--turbo", "544"] + list(extra), "OOM at 1344x768 -> retried 960x544"))
    with open(RUNS, "a", encoding="utf-8") as f:
        f.write("\t".join([sid, str(seed), str(secs), "-", time.strftime("%H:%M"), "-", "FAILED", tries[-1][2] or "failed"]) + "\n")
    return None


def run_cmd(job, parts):
    tag, cmd = parts[0], parts[1:]
    wait_server()
    lf = os.path.join(HERE, "logs", tag + ".log"); t0 = time.time()
    log("START", tag, " ".join(cmd))
    with open(lf, "w", encoding="utf-8") as f:
        r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=HERE, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    txt = open(lf, encoding="utf-8", errors="replace").read()
    if r.returncode != 0 and LOST.search(txt) and crashes.get(job, 0) < 2:
        crashes[job] = crashes.get(job, 0) + 1
        log("LOST", tag, "server unreachable during job - will re-run"); return "lost"
    log("DONE" if r.returncode == 0 else "FAIL", tag, f"{time.time() - t0:.0f}s", "rc=%d" % r.returncode, "log=" + lf)
    return None


def done_set():
    return set(open(DONE, encoding="utf-8").read().split("\n")) if os.path.exists(DONE) else set()


def pending():
    done = done_set()
    for line in open(Q, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and line not in done:
            return line
    return None


def unmark(job):
    lines = [l for l in open(DONE, encoding="utf-8").read().split("\n") if l and l != job]
    open(DONE, "w", encoding="utf-8").write("\n".join(lines) + ("\n" if lines else ""))


def alive(pid):
    r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
    return str(pid) in r.stdout


if os.path.exists(LOCK):
    try:
        old = int(open(LOCK).read().strip())
        if old != os.getpid() and alive(old):
            log("another runner is alive (pid %d) - exiting" % old); sys.exit(0)
    except ValueError:
        pass
open(LOCK, "w").write(str(os.getpid()))
log("runner pid", os.getpid())
idle_since = time.time()
try:
    while True:
        job = pending()
        if job is None:
            if time.time() - idle_since > IDLE:
                log("QUEUE EMPTY - exiting"); break
            time.sleep(10); continue
        with open(DONE, "a", encoding="utf-8") as f:
            f.write(job + "\n")
        kind, parts = job.split()[0], shlex.split(job, posix=False)[1:]
        try:
            res = (run_t2v if kind == "t2v" else run_cmd)(job, parts)
        except Exception as e:  # keep the queue alive
            log("FAIL", job, repr(e)); res = None
        if res == "lost" and crashes.get(job, 0) < 3:
            unmark(job)
        idle_since = time.time()
finally:
    try:
        if int(open(LOCK).read().strip()) == os.getpid():
            os.remove(LOCK)
    except Exception:
        pass
