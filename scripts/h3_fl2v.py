# First/last-frame -> video (FL2VA) for MiniMax H3 through the ComfyUI API on :8190 (agent E, 《溢出》).
# Usage:
#   python h3_fl2v.py <first> <last> <prompt.txt> <prefix> [--seed N] [--secs 5] [--w 1344 --h 768] [--turbo 768|544]
#                     [--copy dest.mp4] [--dry]
#   <first>/<last>: a PNG/JPG, or a video with an optional frame selector: clip.mp4 (= frame 0), clip.mp4@0, clip.mp4@-1 (last frame).
#   Use "-" for <first> (L2VA, last frame only) or for <last> (I2VA, first frame only).
# Both images are cover-cropped (scale to cover, centre crop, Lanczos) to exactly W x H before upload, because
# MiniMaxH3ImageToVideo *stretches* first_frame to the canvas (last_frame is centre-cropped).
# If the prompt file does not already start with the alignment instruction, the official one is prepended:
#   FL2VA: "How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark
#           of the target video; Picture 2 (from Shot N) aligns with the S.SS-second mark of the target video."
#   (N = number of [Shot k] in the prompt, S.SS = frames / 24)
# Graph = h3_shot2.py's T2VA graph (fl2va int8 + turbo LoRA [+ shift 6/3 for 768p] + euler, 8 steps) + LoadImage -> first_frame / last_frame.
import argparse, json, os, re, shutil, subprocess, sys, time, urllib.request, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
URL = "http://127.0.0.1:8190"
OUT = r"D:\Projects\ai-film-2\h3\out"

ap = argparse.ArgumentParser()
ap.add_argument("first"); ap.add_argument("last"); ap.add_argument("prompt"); ap.add_argument("prefix")
ap.add_argument("--seed", type=int, default=11); ap.add_argument("--secs", type=float, default=5.0)
ap.add_argument("--w", type=int, default=1344); ap.add_argument("--h", type=int, default=768)
ap.add_argument("--turbo", default="768"); ap.add_argument("--copy"); ap.add_argument("--dry", action="store_true")
a = ap.parse_args()

n = max(5, round(a.secs * 24)); L = n + (5 - n % 17) % 17
work = os.path.join(HERE, "fl2v_work"); os.makedirs(work, exist_ok=True)


def grab(spec, tag):
    """Return a W x H RGB PNG path for an image or a video frame spec."""
    from PIL import Image, ImageOps
    path, frame = spec, 0
    m = re.match(r"^(.*\.(?:mp4|mov|mkv|webm))(?:@(-?\d+))?$", spec, re.I)
    if m:
        path, frame = m.group(1), int(m.group(2) or 0)
        if frame < 0:
            nb = int(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries",
                                     "stream=nb_read_frames", "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip())
            frame = nb + frame
        raw = os.path.join(work, f"{a.prefix}_{tag}_raw.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path, "-vf", f"select='eq(n\\,{frame})'", "-frames:v", "1", raw], check=True)
        path = raw
    im = Image.open(path).convert("RGB")
    src = im.size
    im = ImageOps.fit(im, (a.w, a.h), Image.LANCZOS, centering=(0.5, 0.5))
    out = os.path.join(work, f"{a.prefix}_{tag}.png"); im.save(out)
    print(f"{tag}: {spec} (frame {frame if m else '-'}, {src[0]}x{src[1]}) -> {out} {a.w}x{a.h}", flush=True)
    return out


def upload(png):
    name = "yichu_" + os.path.basename(png)
    b = uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\nContent-Type: image/png\r\n\r\n").encode() \
        + open(png, "rb").read() + (f"\r\n--{b}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue"
                                     f"\r\n--{b}\r\nContent-Disposition: form-data; name=\"type\"\r\n\r\ninput\r\n--{b}--\r\n").encode()
    req = urllib.request.Request(URL + "/upload/image", data=body, headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    r = json.loads(urllib.request.urlopen(req, timeout=60).read())
    return (r["subfolder"] + "/" + r["name"]) if r.get("subfolder") else r["name"]


ptxt = open(a.prompt, encoding="utf-8").read().strip()
shots = max(1, len(re.findall(r"\[Shot \d+\]", ptxt)))
S = f"{L / 24:.2f}"
if not ptxt.startswith(("How the reference pictures", "For the target video")):
    if a.first != "-" and a.last != "-":
        head = (f"How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the "
                f"target video; Picture 2 (from Shot {shots}) aligns with the {S}-second mark of the target video.")
    elif a.first != "-":
        head = "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced."
    else:
        head = f"How the reference pictures align with the target video — <Picture 1> (from [Shot {shots}]) aligns with the {S}-second mark of the target video."
    ptxt = head + "\n\n" + ptxt
open(os.path.join(work, a.prefix + "_prompt.txt"), "w", encoding="utf-8").write(ptxt)

g = {
 "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": "minimax_h3_fl2va_pruned_int8_convrot.safetensors", "weight_dtype": "default"}},
 "lora": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["unet", 0], "strength_model": 1.0,
          "lora_name": "minimax_h3_fl2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors" if a.turbo == "768" else "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"}},
 "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "type": "minimax", "device": "default"}},
 "vae_v": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_fp16.safetensors"}},
 "vae_a": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"}},
}
m = ["lora", 0]
if a.turbo == "768":
    g["shift"] = {"class_type": "MiniMaxH3SigmaShift", "inputs": {"model": m, "shift_video": 6.0, "shift_audio": 3.0}}; m = ["shift", 0]
cond = {"clip": ["clip", 0], "vae": ["vae_v", 0], "prompt": ptxt, "width": a.w, "height": a.h, "length": L}
imgs = {}
if a.first != "-":
    imgs["first"] = grab(a.first, "first"); cond["first_frame"] = ["img_first", 0]
if a.last != "-":
    imgs["last"] = grab(a.last, "last"); cond["last_frame"] = ["img_last", 0]
print("frames", L, "=", S, "s |", a.w, "x", a.h, "| turbo", a.turbo, "| seed", a.seed, flush=True)
print("prompt head:", ptxt.split("\n")[0], flush=True)
if a.dry:
    print(json.dumps({k: v for k, v in cond.items() if k != "prompt"})); sys.exit(0)
for k, p in imgs.items():
    g["img_" + k] = {"class_type": "LoadImage", "inputs": {"image": upload(p)}}
g.update({
 "cond": {"class_type": "MiniMaxH3ImageToVideo", "inputs": cond},
 "noise": {"class_type": "RandomNoise", "inputs": {"noise_seed": a.seed}},
 "guider": {"class_type": "BasicGuider", "inputs": {"model": m, "conditioning": ["cond", 0]}},
 "sampler": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler" if a.turbo == "768" else "res_multistep"}},
 "sched": {"class_type": "BasicScheduler", "inputs": {"model": m, "scheduler": "simple", "steps": 8, "denoise": 1.0}},
 "sample": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["noise", 0], "guider": ["guider", 0], "sampler": ["sampler", 0], "sigmas": ["sched", 0], "latent_image": ["cond", 1]}},
 "dec_v": {"class_type": "VAEDecode", "inputs": {"samples": ["sample", 0], "vae": ["vae_v", 0]}},
 "dec_a": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["sample", 0], "vae": ["vae_a", 0]}},
 "video": {"class_type": "CreateVideo", "inputs": {"images": ["dec_v", 0], "fps": 24.0, "audio": ["dec_a", 0]}},
 "save": {"class_type": "SaveVideo", "inputs": {"video": ["video", 0], "filename_prefix": a.prefix, "format": "mp4", "codec": "auto"}},
})
req = urllib.request.Request(URL + "/prompt", data=json.dumps({"prompt": g, "client_id": str(uuid.uuid4())}).encode(), headers={"Content-Type": "application/json"})
try:
    pid = json.loads(urllib.request.urlopen(req, timeout=60).read())["prompt_id"]
except urllib.error.HTTPError as e:
    print("HTTP", e.code, e.read().decode("utf-8", "replace")[:3000]); sys.exit(1)
print(a.prefix, "queued", flush=True); t0 = time.time()
while True:
    time.sleep(5)
    try:
        h = json.loads(urllib.request.urlopen(f"{URL}/history/{pid}", timeout=30).read())
    except Exception as e:  # transient
        print("poll error", e, flush=True); continue
    if pid in h:
        st = h[pid].get("status", {}); outs = h[pid].get("outputs", {})
        fn = (outs.get("save", {}).get("images") or [{}])[0].get("filename")
        print(a.prefix, "done in %.0fs" % (time.time() - t0), st.get("status_str"), fn, flush=True)
        if st.get("status_str") != "success":
            print(json.dumps(st.get("messages"), ensure_ascii=False)[-3000:]); sys.exit(2)
        if a.copy and fn:
            shutil.copyfile(os.path.join(OUT, fn), a.copy); print("copied ->", a.copy, flush=True)
        break
