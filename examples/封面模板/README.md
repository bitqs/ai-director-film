# 抖音封面模板

`cover.html` 是《溢出》封面用的网页模板。

- **两种版式：**
  - `?layout=h`：横版 4:3，2160×1620。
  - `?layout=v`：竖版 3:4，1620×2160。
- **需要放在同一目录的图片：**
  - `bg_h.jpg`：横版背景。建议用成片里最炸的一帧，2 倍分辨率渲染后裁成 4:3，裁掉画面里的水印。
  - `bg_v.jpg`：竖版背景，同一帧裁成 3:4。
  - `avatar.jpg`：你的头像，正方形，脸居中。
- **字体：** 页面引用 `/fonts/` 下的字体（Noto Sans SC、Archivo、IBM Plex Mono），放在渲染工程的 `app/public/fonts/` 里，由 Vite 提供。
- **怎么出图：** 放进渲染工程的 `app/public/covers/`，让 AI 用无头 Chrome 分别截取两种版式。原工程用的是 `bun scripts/covers.ts`。

**改文案：** 片名、副标题、片长、频道名都在 HTML 里，直接让 AI 改，例如「副标题换成……，片长 3′06″」。
