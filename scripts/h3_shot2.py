# 通用镜头生成：文字 + 可选人物参考图（<Picture 1>）+ 可选运镜参考视频（<Video 1>），ref2va 模式。
# 用法：python h3_shot2.py <prompt.txt> <prefix> [--img her_ref.png] [--vid ref.mp4] [--seed N] [--secs 5] [--turbo 544|768] [--realism 0.8] [--w 1344 --h 768]
import argparse, json, sys, time, urllib.request, uuid
ap = argparse.ArgumentParser(); ap.add_argument("prompt"); ap.add_argument("prefix")
ap.add_argument("--img", action="append"); ap.add_argument("--vid"); ap.add_argument("--aud"); ap.add_argument("--seed", type=int, default=11); ap.add_argument("--secs", type=float, default=5.0)
ap.add_argument("--w", type=int, default=1344); ap.add_argument("--h", type=int, default=768)
ap.add_argument("--turbo", default="768"); ap.add_argument("--realism", type=float, default=0.0); ap.add_argument("--ref_size", default="match")
a = ap.parse_args()
URL = "http://127.0.0.1:8190"
n = max(5, round(a.secs * 24)); L = n + (5 - n % 17) % 17
ptxt = open(a.prompt, encoding="utf-8").read().strip()
if a.realism > 0: ptxt = "r34l1sm " + ptxt
cond_in = {"clip": ["clip", 0], "vae": ["vae_v", 0], "audio_vae": ["vae_a", 0], "prompt": ptxt,
           "width": a.w, "height": a.h, "length": L, "ref_image_size": a.ref_size}
g = {
 "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": "minimax_h3_fl2va_pruned_int8_convrot.safetensors", "weight_dtype": "default"}},
 "lora": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["unet", 0], "strength_model": 1.0,
          "lora_name": "minimax_h3_fl2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors" if a.turbo == "768" else "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"}},
 "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "type": "minimax", "device": "default"}},
 "vae_v": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_fp16.safetensors"}},
 "vae_a": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"}},
}
for k, im in enumerate(a.img or []):
    g[f"refi{k}"] = {"class_type": "LoadImage", "inputs": {"image": im}}; cond_in[f"ref_images.ref_image_{k}"] = [f"refi{k}", 0]
if a.aud:
    g["refa"] = {"class_type": "LoadAudio", "inputs": {"audio": a.aud}}; cond_in["ref_audios.ref_audio_0"] = ["refa", 0]
if a.vid:
    g["refv"] = {"class_type": "VHS_LoadVideo", "inputs": {"video": a.vid, "force_rate": 24, "custom_width": a.w, "custom_height": a.h, "frame_load_cap": L,
                  "skip_first_frames": 0, "select_every_nth": 1, "format": "None"}}; cond_in["ref_videos.ref_video_0"] = ["refv", 0]
m = ["lora", 0]
if a.realism > 0:
    g["real"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": m, "lora_name": "h3-realism-people-t2v-i2v-r2v.safetensors", "strength_model": a.realism}}; m = ["real", 0]
if a.turbo == "768":
    g["shift"] = {"class_type": "MiniMaxH3SigmaShift", "inputs": {"model": m, "shift_video": 6.0, "shift_audio": 3.0}}; m = ["shift", 0]
g.update({
 "cond": {"class_type": "MiniMaxH3ReferenceToVideo" if (a.img or a.vid or a.aud) else "MiniMaxH3ImageToVideo",
          "inputs": cond_in if (a.img or a.vid or a.aud) else {k: cond_in[k] for k in ("clip", "vae", "prompt", "width", "height", "length")}},
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
    h = json.loads(urllib.request.urlopen(f"{URL}/history/{pid}", timeout=30).read())
    if pid in h:
        st = h[pid].get("status", {}); outs = h[pid].get("outputs", {})
        fn = (outs.get("save", {}).get("images") or [{}])[0].get("filename")
        print(a.prefix, "done in %.0fs" % (time.time() - t0), st.get("status_str"), fn, flush=True)
        if st.get("status_str") != "success": print(json.dumps(st.get("messages"), ensure_ascii=False)[-3000:])
        break
