# 场景定制参考（make-video）

改场景代码前先读完本文。模板结构：8 段配音 → 6 个视觉场景，时间轴全由 `src/durations.ts` 驱动。

## 时间轴系统

- `scripts/gen_tts.py` 按 SEGS 实际音频时长生成 `src/durations.ts`（`FPS=30`、`SCENE_LEAD=0.5`、`SCENE_TAIL=0.8`、`NARR=[...]`）。
- `src/timeline.ts` 用它算每场景帧数：`sceneDur(sec) = ceil((0.5 + sec + 0.8) * 30)`，配音在场景开头 15 帧后起播（`LEAD_FRAMES`）。
- 场景内动画延迟别写死大帧数，用比例对齐配音节奏：`Math.round(dur * 0.5)` 这类写法在文案改长改短后仍然对。
- 改段数时同步改 `src/Main.tsx` 的 Sequence 摆放和 `src/timeline.ts` 的导出。

## 场景 ↔ 文案段映射

| 场景文件 | 配音段 | 视觉内容 | 常改点 |
|---|---|---|---|
| `scenes/S1Hook.tsx` | seg1 | 左右对比卡（成功 vs 失败）+ 底部大问题 | 两卡标题/副标、`DemoBars` 柱高、`FailLine` 折线、大问题文案 |
| `scenes/S2Problem.tsx` | seg2 | 两节点 + 断裂连线（抖动+红叉）+ 四标签 | 节点标题/副标、`chips` 数组（标签文字+颜色） |
| `scenes/S3Steps.tsx` | seg3–6 | 四步法，每步一屏，顶部进度指示器 | `STEPS` 数组（标题/图标/颜色）+ `Step1–4` 组件内的文案元素 |
| `scenes/S4Loop.tsx` | seg7 | 四节点环绕中心 hub 旋转 | `NODES` 数组、中心 hub 文案与图标 |
| `scenes/S5CTA.tsx` | seg8 | 两行金句 + logo + 出品字幕 | 两行金句、logo 文案、credits |

通用视觉层：`Background.tsx`（光斑/网格，一般不动）、`ui.tsx`（GlassCard/Kicker/进度条等积木）、`icons.tsx`（线性图标集，新增图标在此加 path）、`theme.ts`（调色板 `C` 与中文字体栈）。

## 动画写法约定

- 入场用 `ui.tsx` 的 `useRise(delay)` 或 `spring({frame: f - delay, fps})`；延迟一律相对场景内帧数或 `dur` 比例。
- SVG 画线进场：`strokeDasharray=CIRC + strokeDashoffset=CIRC*(1-p)` 只对**实线**有效，虚线会整体循环（见踩坑 2）。
- 旋转装饰（流动光环类）用 `transform: rotate(${f * k}deg)` + `transformOrigin` 记得写 px 单位。

## 踩坑实录（全部真实发生过，别再踩）

1. **`<Sequence>` 必须显式 `from`**。漏写时多个场景全从 0 帧叠加渲染，画面全糊。S3Steps 里用 `cum` 累计偏移的写法是标准答案。
2. **虚线不能用 dashoffset 做"逐段画出"进场**——虚线图案会循环导致线一开始就整条可见。正确做法：透明度淡入 + `strokeDashoffset={-f * k}` 做蚂蚁线行进。
3. **不要手改 `src/durations.ts`**，会被下次 `gen_tts.py` 覆盖；文案一改必须重跑 TTS（时长变了时间轴要跟着变）。
4. **布局重叠只能靠抽帧发现**（如标题压住圆环）。每个场景必须抽帧目检，别信代码想象。
5. **TTS 文本错字直接进音频**，生成前校对一遍中文（注意日文汉字混入，如"歩"）。
6. **生成脚本别放后台跑**，管道会吞 traceback（曾因此没发现音乐脚本 IndexError，直到渲染报音频缺失）。
7. **`remotion still` 遇到缺失音频报 MediaError**，先 `ls public/audio/` 确认配音和 music.mp3 都在。
8. 交互式 CLI（如 1pctl 密码）非 TTY 下传参无效，需要 `expect` 喂输入——与本技能无关但同会话踩过，记一笔。

## 竖版适配（1080×1920）

改 `Root.tsx` Composition 的 `width/height` 后，各场景的绝对定位坐标（x: 230/960/1560 等）需要整体重排：左右对比改上下堆叠，闭环场景圆心移到 `y≈1000` 并缩小 `R`。改完务必重新抽帧全量目检。
