#!/usr/bin/env python3
"""Synthesize the CC0 UI sound effects and ambient bed used by render_motion_reel.py.

Everything is generated from scratch with numpy (noise, sines, envelopes),
so there are no third-party samples. Deterministic (fixed seed).

Outputs (48 kHz mono 16-bit WAV, peak-normalized to about -3 dBFS):
  tools/sfx/whoosh.wav  - soft filtered-noise swoosh (window slides in, chapter change)
  tools/sfx/pop.wav     - short soft bubble pop (dot hits a node, element pops in)
  tools/sfx/tick.wav    - one soft key tick (typing; the renderer scatters several)
  tools/sfx/alert.wav   - low, muted two-note error blip (overload, timeout, denied)
  tools/sfx/ding.wav    - gentle two-note success chime (fix lands)
  tools/music/ambient-pad-bed.mp3 - 24 s very low ambient synth pad (needs ffmpeg)

Usage: python3 tools/sfx/generate_motion_sfx.py
"""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np

SR = 48000
HERE = Path(__file__).resolve().parent
MUSIC = HERE.parent / "music"
rng = np.random.default_rng(20261110)


def write_wav(path: Path, x: np.ndarray, peak_db: float = -3.0) -> None:
    x = np.asarray(x, dtype=np.float64)
    m = np.max(np.abs(x)) or 1.0
    x = x / m * 10 ** (peak_db / 20)
    data = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())
    print("wrote", path)


def t_axis(dur):
    return np.arange(int(SR * dur)) / SR


def onepole_lp(x, cutoff):
    """Time-varying one-pole low-pass; cutoff may be an array (Hz)."""
    cutoff = np.broadcast_to(np.asarray(cutoff, dtype=float), x.shape)
    a = np.exp(-2 * np.pi * cutoff / SR)
    y = np.empty_like(x)
    s = 0.0
    for i in range(len(x)):
        s = (1 - a[i]) * x[i] + a[i] * s
        y[i] = s
    return y


def whoosh(dur=0.42):
    t = t_axis(dur)
    u = t / dur
    noise = rng.standard_normal(len(t))
    sweep = 300 + 2600 * np.sin(np.pi * u) ** 2       # filter opens then closes
    band = onepole_lp(noise, sweep) - onepole_lp(noise, sweep * 0.25)
    env = np.sin(np.pi * np.clip(u, 0, 1)) ** 1.6
    return band * env


def pop(dur=0.09):
    t = t_axis(dur)
    f = 900 * np.exp(-t * 28) + 380                 # quick downward pitch drop
    ph = 2 * np.pi * np.cumsum(f) / SR
    env = (1 - np.exp(-t * 900)) * np.exp(-t * 55)
    return np.sin(ph) * env


def tick(dur=0.035):
    t = t_axis(dur)
    click = rng.standard_normal(len(t)) * np.exp(-t * 260)
    body = np.sin(2 * np.pi * 1900 * t) * np.exp(-t * 180) * 0.5
    return onepole_lp(click, 5000) + body


def tone(freq, dur, decay, harm=(1.0, 0.25, 0.08)):
    t = t_axis(dur)
    x = sum(a * np.sin(2 * np.pi * freq * (k + 1) * t) for k, a in enumerate(harm))
    env = (1 - np.exp(-t * 400)) * np.exp(-t * decay)
    return x * env


def alert():
    a = tone(220, 0.22, 14, (1.0, 0.5, 0.2))
    b = tone(185, 0.30, 11, (1.0, 0.5, 0.2))
    out = np.zeros(int(SR * 0.42))
    out[:len(a)] += a
    o = int(SR * 0.12)
    out[o:o + len(b)] += b
    return onepole_lp(out, 1800)


def ding():
    a = tone(880, 0.6, 7, (1.0, 0.15, 0.05))
    b = tone(1320, 0.7, 6, (1.0, 0.12, 0.04))
    out = np.zeros(int(SR * 0.8))
    out[:len(a)] += a
    o = int(SR * 0.09)
    out[o:o + len(b)] += b * 0.8
    return out


def ambient_bed(dur=24.0):
    """Slow, dark pad: detuned saws through a soft low-pass, chord every 6 s."""
    t = t_axis(dur)
    chords = [(110.0, 164.81, 220.0, 261.63), (98.0, 146.83, 196.0, 246.94),
              (87.31, 130.81, 174.61, 220.0), (98.0, 146.83, 196.0, 233.08)]
    out = np.zeros_like(t)
    seg = dur / len(chords)
    for i, ch in enumerate(chords):
        start = i * seg
        env = np.clip((t - start + 1.5) / 1.5, 0, 1) * np.clip((start + seg + 1.5 - t) / 1.5, 0, 1)
        env = np.sin(env * np.pi / 2) ** 2
        for f in ch:
            for det in (-0.12, 0.0, 0.11):
                ph = 2 * np.pi * (f + det) * t + rng.uniform(0, 6.28)
                out += env * (np.sin(ph) + 0.18 * np.sin(2 * ph) + 0.06 * np.sin(3 * ph))
    lfo = 0.85 + 0.15 * np.sin(2 * np.pi * t / 8.0)
    out = onepole_lp(out * lfo, 900)
    air = onepole_lp(rng.standard_normal(len(t)), 2500) * 0.02
    out = out / np.max(np.abs(out)) + air
    # seamless loop: crossfade the tail into the head
    xf = int(SR * 1.5)
    head, tail = out[:xf].copy(), out[-xf:]
    ramp = np.linspace(0, 1, xf)
    out[:xf] = head * ramp + tail * (1 - ramp)
    return out[:-xf]


def main():
    write_wav(HERE / "whoosh.wav", whoosh())
    write_wav(HERE / "pop.wav", pop())
    write_wav(HERE / "tick.wav", tick())
    write_wav(HERE / "alert.wav", alert())
    write_wav(HERE / "ding.wav", ding())
    MUSIC.mkdir(exist_ok=True)
    tmp = MUSIC / "_ambient.wav"
    write_wav(tmp, ambient_bed(), peak_db=-6.0)
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(tmp),
                    "-ac", "2", "-c:a", "libmp3lame", "-b:a", "128k", str(MUSIC / "ambient-pad-bed.mp3")],
                   check=True)
    tmp.unlink()
    print("wrote", MUSIC / "ambient-pad-bed.mp3")


if __name__ == "__main__":
    main()
