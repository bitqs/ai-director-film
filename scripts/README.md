# 参考脚本

从《溢出》真实工程里摘出来的脚本，**密钥和个人信息都已去掉**。
它们依赖原工程的目录结构（`data/`、`audio/`、`clips_src/`、`app/public/clips/`）。最省事的用法：交给 AI，说「照着 scripts/xxx.py 在我的工程里写一个」。

| 脚本 | 干什么 | 需要的 `.env` |
|---|---|---|
| `script_示例.py` | 旁白台词表：`say` 是念的字，`show` 是屏幕上显示的字 | — |
| `tts_豆包示例.py` | 豆包语音 2.0 逐句合成，带逐字时间戳，统一每句响度；台词没变就不重做 | `VOLC_SPEECH_API_KEY` |
| `plan_示例.py` | 按 120 BPM 把旁白排进整数小节，生成时间轴和旁白逐字时间 | — |
| `cues_示例.py` | 生成全片唯一的同步点 `cues.json`：跳档、盖章、白屏……都从旁白和节拍推出来 | — |
| `h3_api.py` | MiniMax 官方 API 出片（2K / 768P）：提交、轮询、下载；网络断了自动重试 | `MINIMAX_API_KEY` |
| `h3_shot2.py` | 本地 ComfyUI 跑 H3：文生视频 / 参考生视频（人物图、参考视频、口型音频） | — |
| `h3_fl2v.py` | 本地 H3 首尾帧转场：首帧 = 代码画面，尾帧 = 写实镜头第一帧 | — |
| `run_queue.py` | 本地出片队列：一次只跑一条，服务挂了就等，每条出拼图 | — |
| `clips.py` | 写实镜头 → 1920×1080 逐帧 JPEG + meta.json，给渲染引擎用 | — |
| `brief_loop.py` | 每 10 分钟读 `STATUS.json`，往飞书发进度简报（任务、出片数、预计完成时间） | `FEISHU_USER_OPEN_ID`（+ 配好的 lark-cli） |

- **Python 依赖：** `numpy scipy soundfile pyloudnorm pillow`。
- **Windows 上：** 运行前设 `PYTHONIOENCODING=utf-8`。
