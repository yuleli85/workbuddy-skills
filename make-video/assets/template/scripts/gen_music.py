"""Generative ambient-tech background music: pad + sub bass + arp + shimmer.

Chord loop Am9 - Fmaj7 - C - G6/9, 84 BPM, ~96s, deterministic (seeded).
Output: public/audio/music.wav, converted to mp3 by caller.
"""
import os
import subprocess
import wave

import numpy as np

SR = 44100
import sys
DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 96.0
N = int(SR * DUR)
t = np.arange(N) / SR
BPM = 84.0
beat = 60.0 / BPM
bar = beat * 4

rng = np.random.default_rng(7)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def midi_f(m):
    return 440.0 * 2 ** ((m - 69) / 12.0)


def env_line(points_x, points_y):
    return np.interp(t, points_x, points_y)


chords = [
    [57, 60, 64, 67, 71],   # Am9
    [53, 57, 60, 64],       # Fmaj7
    [48, 55, 60, 64, 67],   # C
    [55, 59, 62, 66, 69],   # G6/9
]
n_bars = int(np.ceil(DUR / bar))

# ---------- pad ----------
padL = np.zeros(N)
padR = np.zeros(N)
for k in range(n_bars):
    s0 = int(k * bar * SR)
    if s0 >= N:
        break
    seg_n = min(int(bar * SR) + int(0.8 * SR), N - s0)
    tt = np.arange(seg_n) / SR
    env = np.clip(tt / 0.9, 0, 1) * np.clip((tt[-1] - tt) / 1.4, 0, 1) ** 1.2
    for j, m in enumerate(chords[k % 4]):
        f0 = midi_f(m)
        for det, pan in ((-0.0016, -0.4), (0.0016, 0.4)):
            w = 2 * np.pi * f0 * (1 + det) * tt
            v = np.sin(w) + 0.35 * np.sin(2 * w) + 0.12 * np.sin(3 * w)
            breath = 0.85 + 0.3 * np.sin(2 * np.pi * 0.13 * t[s0] + j * 1.7)
            v *= env * 0.05 * breath
            padL[s0:s0 + seg_n] += v * (1 - pan) / 2
            padR[s0:s0 + seg_n] += v * (1 + pan) / 2

# ---------- sub bass (root -12, ducked per beat) ----------
bass = np.zeros(N)
for k in range(n_bars):
    s0 = int(k * bar * SR)
    if s0 >= N:
        break
    seg_n = min(int(bar * SR), N - s0)
    tt = np.arange(seg_n) / SR
    f0 = midi_f(chords[k % 4][0] - 12)
    duck = 0.45 + 0.55 * np.exp(-(tt % beat) / beat * 5)
    v = np.sin(2 * np.pi * f0 * tt) * duck * 0.15
    bass[s0:s0 + seg_n] += v

# ---------- pluck arp (8th notes) ----------
arpL = np.zeros(N)
arpR = np.zeros(N)
eight = beat / 2
for i in range(int(DUR / eight)):
    t0 = i * eight
    ch = chords[int(t0 / bar) % 4]
    tones = [m + 12 for m in ch]
    idxs = [0, 2, 1, 3, 2, 4]
    m = tones[idxs[i % len(idxs)] % len(tones)] + (12 if i % 16 == 12 else 0)
    f0 = midi_f(m)
    seg_n = int(eight * 1.6 * SR)
    tt = np.arange(seg_n) / SR
    v = np.sin(2 * np.pi * f0 * tt) * np.exp(-tt * 5.5) * 0.07
    pan = -0.5 if i % 2 == 0 else 0.5
    s0 = int(t0 * SR)
    if s0 + seg_n > N:
        seg_n = N - s0
        v = v[:seg_n]
    arpL[s0:s0 + seg_n] += v * (1 - pan) / 2
    arpR[s0:s0 + seg_n] += v * (1 + pan) / 2

# ---------- shimmer (high-passed noise, slow swell) ----------
noise = rng.standard_normal(N)
sh = np.diff(np.diff(noise, prepend=0.0), prepend=0.0)
sh *= 0.5 / (np.max(np.abs(sh)) + 1e-9)
swell = 0.5 - 0.5 * np.cos(2 * np.pi * t / (bar * 4))
shimmer = sh * swell * 0.012

# ---------- structure ----------
pad_gate = env_line([0, 2.5, DUR - 4, DUR], [0, 1, 1, 0])
bass *= env_line([0, 6, 72, 78], [0, 1, 1, 0])
arp_gate = env_line([0, 8, 72, 76], [0, 1, 1, 0])
shimmer *= env_line([0, 8, 88, 93], [0, 1, 1, 0])

L = padL * pad_gate + bass + arpL * arp_gate + shimmer
R = padR * pad_gate + bass + arpR * arp_gate + shimmer

# ---------- master ----------
mix = np.stack([L, R])
mix = np.tanh(mix * 1.4)
mix /= np.max(np.abs(mix)) + 1e-9
mix *= 0.85
pcm = (mix.T * 32767).astype(np.int16)

os.makedirs(os.path.join(ROOT, 'public', 'audio'), exist_ok=True)
wav_path = os.path.join(ROOT, 'public', 'audio', 'music.wav')
with wave.open(wav_path, 'wb') as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(pcm.tobytes())
print(f'music.wav written: {DUR}s')

subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', wav_path,
                '-codec:a', 'libmp3lame', '-b:a', '192k',
                os.path.join(ROOT, 'public', 'audio', 'music.mp3')], check=True)
os.remove(wav_path)
print('music.mp3 written')
