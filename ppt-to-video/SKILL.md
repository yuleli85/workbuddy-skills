---
name: ppt-to-video
description: 把 pptx 转成 1080p 幻灯片视频（LibreOffice → pdftoppm → ffmpeg）。当用户使用 `/ppt-to-video <pptx路径>` 指令，或要求"PPT 转视频/pptx 变 mp4/幻灯片成片"时触发。批量场景：先遍历目录生成命令列表，再逐个执行本技能。
version: 1.0.0
agent_created: true
---

# ppt-to-video：PPTX → 1080p 幻灯片视频

把一个 pptx 转成 H.264 MP4：每页渲染成 1920x1080 静帧，默认每页 5 秒，无音轨。

## 一键执行

```bash
chmod +x ~/.workbuddy/skills/ppt-to-video/scripts/pptx2mp4.zsh
~/.workbuddy/skills/ppt-to-video/scripts/pptx2mp4.zsh <文件.pptx> [每页秒数]
```

产物：`~/WorkBuddy/<会话工作区>/ppt2video/<文件名>/<文件名>-1080p.mp4`，中间产物（PNG/PDF）自动清理。

## 依赖

全部本机已装：`~/Applications/LibreOffice.app/Contents/MacOS/soffice`、`pdftoppm`（poppler）、`ffmpeg`（homebrew）。

## 踩坑实录（不要重蹈）

1. **ffmpeg 8.1 concat demuxer 的 `duration` 指令不可靠**：`file X + duration 5` 的经典幻灯片写法实测每条目都被拉成 5s（末页补帧导致 65s 而非 60s），追加 `duration 0.04` 也无效。**必须用 `-loop 1 -t 5 -i` 每图独立输入 + `filter_complex concat`**，时长才精确。
2. **一条 ffmpeg 命令多输出时 `-ss` 别放在多个 input 前**：`ffmpeg -ss 2 -i v.mp4 f1.png -ss 32 -i v.mp4 f2.png` 的第二个输出**默认仍映射第一个输入**，抽出的是同一帧（MD5 相同）。验证抽帧一律单输入单输出分两条跑。
3. LibreOffice 无头转换前确保没有正在运行的 LibreOffice GUI 实例（会抢锁导致静默失败）。
4. pdftoppm `-r 144` 对 16:9 幻灯片正好出 1920x1080；若源不是 16:9，加 `-vf scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2`。

## 批量转换

遍历目录生成命令清单后逐条执行（shell 循环即可）：

```bash
for f in /Users/shan/Desktop/ppt/*.pptx; do
  ~/.workbuddy/skills/ppt-to-video/scripts/pptx2mp4.zsh "$f"
done
```

## 扩展点（按需再开发）

- 配音解说：接 make-video 技能的 Edge-TTS 管线，按页文案生成 narration，用 `-shortest` 或逐页时长对齐。
- 转场/背景音乐：ffmpeg `xfade` 滤镜 + 音轨混入。
- 竖版 1080x1920：改 pad/scale 参数。
