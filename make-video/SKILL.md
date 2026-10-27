---
name: make-video
description: 把文案变成带中文配音、背景音乐和 React 动画的高质量成片视频（Remotion + Edge-TTS + 程序化合成音乐，全部素材零版权）。当用户要求制作视频、宣传片、动画视频、explainer 视频、产品介绍片、知识类短视频、配音视频，或说"做个视频""来个成片""把这段文案做成视频""给这个主题出个片"时使用——即使用户只给了文案或主题，也应触发本技能。
description_zh: "文案一键成片：配音+音乐+动画视频制作流水线"
description_en: "Turn copy into narrated, scored, animated videos (Remotion + Edge-TTS)"
version: 1.0.0
---

# make-video：文案 → 成片

把用户文案加工成 1080p/30fps/H.264+AAC 的动画讲解视频：Edge-TTS 中文配音（自动响度归一化）、numpy 程序化背景音乐（零版权风险）、Remotion React 动画场景。流水线已在真实项目中验证过，照做即可，不要另起炉灶重新发明。

## 1. 环境检查（缺什么装什么）

```bash
node -v          # 需 ≥ 20
ffmpeg -version  # 任意现代版本
python3 --version
```

缺失时：`brew install ffmpeg`、`brew install node`（或 nvm）。Python 依赖每个工程独立 venv（见下）。

## 2. 初始化工程

```bash
cp -R ~/.workbuddy/skills/make-video/assets/template <工作目录>/<项目名>
cd <项目名>
npm install                          # remotion / react / typescript 等，lock 文件已带版本
python3 -m venv .venv && .venv/bin/pip install edge-tts numpy
```

模板自带 5 个场景组件（开场对比→问题→四步法→闭环→金句收尾）和全套构建脚本。**先通读 `references/scenes.md` 再改场景代码**——里面有场景与文案段的映射表和踩坑实录。

## 3. 写文案、生成配音

编辑 `scripts/gen_tts.py` 顶部的 `SEGS`（8 段是模板结构，可增减，每段一句、建议 ≤ 45 字），然后：

```bash
.venv/bin/python scripts/gen_tts.py
```

该脚本做三件事：生成 `public/audio/narration_N.mp3`（loudnorm 归一化）、测出真实时长、**自动写入 `src/durations.ts`**。时间轴全部由真实音频时长驱动——永远不要手改 `durations.ts`，改文案就重跑此脚本。文案生成前先校对错别字，错字会直接进音频。

## 4. 背景音乐

```bash
.venv/bin/python scripts/gen_music.py [总秒数]   # 默认 96s
```

成片预计超过 90 秒时传入更长时长（音乐自带淡入淡出结构）。配音音量已在混音时压低（music volume ≈ 0.17），无需再调。

## 5. 改造场景

按 `references/scenes.md` 的映射表改各场景的标题、卡片文本、节点 label、配色（`src/theme.ts` 的调色板 `C`）。改完先类型检查：

```bash
npx tsc --noEmit
```

## 6. 自检循环（必做，不可跳过）

本流水线的历史 bug（时序错乱、动画失效、布局重叠）全部靠抽帧发现，纯靠读代码看不出来。**每个场景至少抽 1–2 帧**，帧号覆盖该场景动画的高峰时刻：

```bash
mkdir -p stills
npx remotion still src/index.ts AiLanding stills/f<N>.png --frame=<N> --log=error
```

用 Read 逐张看图，发现问题（文字重叠、元素越界、动画没出现）→ 修 → 重抽该场景帧，直到全部干净。首次渲染会自动下载 Chrome Headless Shell，属正常等待。

## 7. 最终渲染与校验

```bash
npx remotion render src/index.ts AiLanding out/<名称>-1080p.mp4 --codec=h264
```

校验成片（用 ffprobe），应满足：1920x1080、30fps、h264 + aac 立体声：

```bash
ffprobe -v error -show_entries format=duration:stream=codec_name,codec_type,width,height,r_frame_rate -of default=nw=1 out/<名称>-1080p.mp4
ffmpeg -i out/<名称>-1080p.mp4 -af volumedetect -f null - 2>&1 | grep -E 'mean_volume|max_volume'
```

max_volume 大于 -1dB 说明有削波风险，回混音调整。最后从成片不同时间点抽 2 帧 Read 确认与预览一致。

## 8. 交付

给出成片绝对路径的 Markdown 链接 + 时长/分辨率/大小，并告知维护入口：改文案 → 重跑 `gen_tts.py` → `npx remotion render ...` 一键重渲。

## 边界与提醒

- 生成类脚本（gen_tts / gen_music）**前台运行**，别用后台管道吞掉报错。
- 音频文件缺失时 `remotion still` 会报 MediaError——先确认 `public/audio/` 齐全再抽帧。
- 需要竖版（1080×1920）时改 `src/Root.tsx` 的 Composition 尺寸并按 scenes.md 重排场景布局。
