#!/usr/bin/env python3
"""Synthesize a short, quiet tech/corporate instrumental bed.

Original work for the k4coding social-media-assets project. No third-party
samples are used. Released as CC0 1.0 (see ../MUSIC_LICENSES.md).
"""
from __future__ import annotations

import math
import random
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

SR = 48000
BPM = 120
BEAT = 60.0 / BPM  # 0.5 s
BARS = 8
DURATION = BARS * 4 * BEAT  # 16.0 s
SEED = 4  # reproducible "k4"


def midi(n: float) -> float:
    return 440.0 * (2.0 ** ((n - 69.0) / 12.0))


def cents(freq: float, c: float) -> float:
    return freq * (2.0 ** (c / 1200.0))


def render() -> tuple[list[float], list[float]]:
    n = int(SR * DURATION)
    left = [0.0] * n
    right = [0.0] * n
    rng = random.Random(SEED)

    # I–V–vi–IV, two bars each, then repeat: C, G, Am, F
    chords = [
        (48, 60, 64, 67),  # C
        (47, 59, 62, 67),  # G
        (45, 60, 64, 69),  # Am
        (41, 60, 65, 69),  # F
    ]
    # two bars per chord, twice through
    progression = []
    for _rep in range(2):
        for chord in chords:
            progression.append(chord)
            progression.append(chord)

    def add(buf: list[float], idx: int, value: float) -> None:
        if 0 <= idx < n:
            buf[idx] += value

    def add_stereo(i: int, l: float, r: float) -> None:
        add(left, i, l)
        add(right, i, r)

    # --- pad (slow, detuned sines on chord tones) ---
    pad_attack = 0.45
    pad_release = 0.50
    for bar, chord in enumerate(progression):
        start = bar * 4 * BEAT
        end = start + 4 * BEAT
        length = end - start
        tones = [midi(chord[0] + 12), midi(chord[1]), midi(chord[2]), midi(chord[3])]
        for freq in tones:
            detunes = (-7.0, 0.0, 6.5)
            for d in detunes:
                f = cents(freq, d)
                phase_l = rng.random() * 2 * math.pi
                phase_r = phase_l + 0.15
                amp = 0.045 if freq < 200 else 0.055
                i0 = int(start * SR)
                i1 = min(n, int(end * SR))
                for i in range(i0, i1):
                    t = i / SR - start
                    if t < pad_attack:
                        env = t / pad_attack
                    elif t > length - pad_release:
                        env = max(0.0, (length - t) / pad_release)
                    else:
                        env = 1.0
                    trem = 0.85 + 0.15 * math.sin(2 * math.pi * 0.18 * (i / SR) + d)
                    sl = math.sin(phase_l + 2 * math.pi * f * (i / SR)) * amp * env * trem
                    sr_ = math.sin(phase_r + 2 * math.pi * f * (i / SR)) * amp * env * trem
                    add_stereo(i, sl, sr_)

    # --- bass (sine + light 2nd harmonic, root, quarter notes) ---
    for bar, chord in enumerate(progression):
        root = midi(chord[0])  # already in a low octave
        for beat in range(4):
            start = (bar * 4 + beat) * BEAT
            amp = 0.22 if beat in (0, 2) else 0.14
            i0 = int(start * SR)
            length = int(0.46 * SR)
            phase = 0.0
            for k in range(length):
                t = k / SR
                # tiny pitch settle at the start
                f = root * (1.0 + 0.02 * math.exp(-t * 40))
                phase += 2 * math.pi * f / SR
                env = math.exp(-t * 3.2)
                if t < 0.01:
                    env *= t / 0.01
                sample = (math.sin(phase) + 0.18 * math.sin(2 * phase)) * amp * env
                add_stereo(i0 + k, sample, sample)

    # --- soft kick on 1 and 3 ---
    for bar in range(BARS):
        for beat in (0, 2):
            start = (bar * 4 + beat) * BEAT
            amp = 0.42 if beat == 0 else 0.30
            i0 = int(start * SR)
            length = int(0.22 * SR)
            phase = 0.0
            for k in range(length):
                t = k / SR
                f = 98.0 * math.exp(-t * 18) + 36.0
                phase += 2 * math.pi * f / SR
                env = math.exp(-t * 13)
                click = math.sin(2 * math.pi * 1800 * t) * math.exp(-t * 90) * 0.12
                sample = (math.sin(phase) * env + click) * amp
                add_stereo(i0 + k, sample, sample)

    # --- light snap on 2 and 4 ---
    for bar in range(BARS):
        for beat in (1, 3):
            start = (bar * 4 + beat) * BEAT
            i0 = int(start * SR)
            length = int(0.12 * SR)
            lp = 0.0
            for k in range(length):
                t = k / SR
                noise = rng.uniform(-1, 1)
                lp = lp * 0.6 + noise * 0.4  # simple lowpass then highpass
                hp = noise - lp
                env = math.exp(-t * 28)
                body = math.sin(2 * math.pi * 190 * t) * math.exp(-t * 16) * 0.25
                sample = (hp * 0.55 + body) * 0.16 * env
                # slight stereo spread
                add_stereo(i0 + k, sample * 0.9, sample * 1.1)

    # --- closed hats, 8th notes ---
    for eighth in range(BARS * 8):
        start = eighth * (BEAT / 2)
        amp = 0.07 if eighth % 2 == 0 else 0.045
        i0 = int(start * SR)
        length = int(0.06 * SR)
        lp = 0.0
        for k in range(length):
            t = k / SR
            noise = rng.uniform(-1, 1)
            lp = lp * 0.85 + noise * 0.15
            hp = noise - lp
            env = math.exp(-t * 70)
            sample = hp * amp * env
            add_stereo(i0 + k, sample * 1.05, sample * 0.95)

    # --- plucky arpeggio (8ths), delayed slightly on the right ---
    delay = int(0.014 * SR)
    for bar, chord in enumerate(progression):
        tones = [midi(chord[1] + 12), midi(chord[2] + 12), midi(chord[3] + 12), midi(chord[1] + 24)]
        pattern = [0, 1, 2, 3, 2, 1, 0, 2]
        for step, idx in enumerate(pattern):
            start = (bar * 4 * BEAT) + step * (BEAT / 2)
            freq = tones[idx]
            i0 = int(start * SR)
            length = int(0.32 * SR)
            for k in range(length):
                t = k / SR
                env = math.exp(-t * 9) * (1.0 if t > 0.003 else t / 0.003)
                # gentle low-pass as it decays (add a bit of 2nd / 3rd then let them fade faster)
                s1 = math.sin(2 * math.pi * freq * t)
                s2 = math.sin(2 * math.pi * freq * 2 * t) * math.exp(-t * 18) * 0.25
                sample = (s1 + s2) * 0.11 * env
                add(left, i0 + k, sample)
                add(right, i0 + k + delay, sample * 0.92)

    return left, right


def peak(left: list[float], right: list[float]) -> float:
    p = 1e-9
    for l, r in zip(left, right):
        p = max(p, abs(l), abs(r))
    return p


def normalize(left: list[float], right: list[float], peak_target: float = 0.55) -> None:
    p = peak(left, right)
    g = peak_target / p
    for i in range(len(left)):
        left[i] *= g
        right[i] *= g


def write_wav(path: Path, left: list[float], right: list[float]) -> None:
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        frames = bytearray()
        for l, r in zip(left, right):
            li = max(-32767, min(32767, int(l * 32767)))
            ri = max(-32767, min(32767, int(r * 32767)))
            frames += struct.pack("<hh", li, ri)
        wf.writeframes(frames)


def main() -> int:
    out_dir = Path(__file__).resolve().parent
    wav_path = out_dir / "soft-tech-bed.wav"
    mp3_path = out_dir / "soft-tech-bed.mp3"
    print(f"Rendering {DURATION:.1f}s bed at {SR} Hz…")
    left, right = render()
    normalize(left, right, 0.55)
    write_wav(wav_path, left, right)
    # Also keep a compact MP3 for the repo; the script can use either.
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(wav_path),
        "-codec:a", "libmp3lame", "-b:a", "192k",
        str(mp3_path),
    ]
    try:
        subprocess.run(cmd, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"wav written but mp3 encode failed: {exc}", file=sys.stderr)
        return 1
    # Drop the large wav; mp3 is the canonical asset.
    wav_path.unlink(missing_ok=True)
    print(f"Wrote {mp3_path} ({mp3_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
