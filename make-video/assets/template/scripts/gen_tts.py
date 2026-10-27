import asyncio, json, os, subprocess
import edge_tts

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUB = os.path.join(ROOT, 'public', 'audio')
os.makedirs(PUB, exist_ok=True)

VOICE = 'zh-CN-YunxiNeural'
RATE = '+6%'

SEGS = [
    "为什么你的 AI 项目，演示时惊艳全场，上线后却无人问津？",
    "因为 AI 落地，从来不是调一个大模型接口那么简单。真正的挑战，藏在场景、数据、流程和投入产出比里。",
    "第一步，选对场景。高频、高价值、可评估，三者缺一不可。",
    "第二步，喂饱数据。垃圾进，垃圾出，数据质量，决定 AI 的上限。",
    "第三步，嵌入流程。让 AI 长在业务流程里，而不是做一个孤立的演示品。",
    "第四步，算清回报。效率提升、成本下降、质量可控，都要用数字来证明。",
    "当场景、数据、流程和回报形成闭环，AI 才能从惊艳的演示，变成持续的生产力。",
    "AI 不是风口，而是新的基础设施。落地的每一步，都算数。",
]


async def gen(i: int, text: str) -> float:
    mp3 = os.path.join(PUB, f'narration_{i + 1}.mp3')
    norm = os.path.join(PUB, f'narration_{i + 1}_n.mp3')
    await edge_tts.Communicate(text, voice=VOICE, rate=RATE).save(mp3)
    subprocess.run([
        'ffmpeg', '-y', '-v', 'error', '-i', mp3,
        '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11',
        '-ar', '44100', '-b:a', '160k', norm,
    ], check=True)
    os.replace(norm, mp3)
    out = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', mp3],
        capture_output=True, text=True)
    return float(out.stdout.strip())


async def main():
    secs = []
    for i, text in enumerate(SEGS):
        s = await gen(i, text)
        secs.append(s)
        print(f'seg{i + 1}: {s:.2f}s  {text[:16]}...')
    with open(os.path.join(ROOT, 'audio_segments.json'), 'w') as f:
        json.dump([{'i': i + 1, 'sec': s} for i, s in enumerate(secs)], f, ensure_ascii=False, indent=1)
    ts = ("// AUTO-GENERATED from public/audio — regenerate via scripts/gen_tts.py\n"
          "export const FPS = 30;\n"
          "export const SCENE_LEAD = 0.5;\n"
          "export const SCENE_TAIL = 0.8;\n"
          "export const NARR = [" + ", ".join(f"{s:.3f}" for s in secs) + "];\n")
    with open(os.path.join(ROOT, 'src', 'durations.ts'), 'w') as f:
        f.write(ts)
    print('src/durations.ts written')


asyncio.run(main())
