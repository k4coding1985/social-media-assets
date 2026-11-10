#!/usr/bin/env python3
"""Add an AI voiceover (and optional quiet music bed) to a silent Reel.

Takes a voiceover script and a silent (or near-silent) MP4, synthesizes
speech, optionally mixes a ducked royalty-free music bed, and writes a
new Instagram-Reels-valid MP4 (H.264 + AAC, 9:16, under 50 MB).

If the speech is longer than the video, the last frame is frozen to
cover the remaining audio. If the speech is shorter, the video length
is kept and the audio is padded with silence.

TTS fallback chain: edge-tts → gTTS → piper → espeak-ng.

Examples:
  tools/.venv/bin/python tools/add_voiceover.py \\
      -i posts/2026-11-10-0900-sql-is-null-vs-equals-null.mp4 \\
      -o /tmp/reel-with-vo.mp4 \\
      -t "Where email equals NULL returns zero rows. Use IS NULL."

  tools/.venv/bin/python tools/add_voiceover.py \\
      -i in.mp4 -o out.mp4 --text-file script.txt --no-music
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
VENV_PY = TOOLS_DIR / ".venv" / "bin" / "python"
REQUIREMENTS = TOOLS_DIR / "requirements.txt"
DEFAULT_MUSIC = TOOLS_DIR / "music" / "soft-tech-bed.mp3"
DEFAULT_VOICE = "en-IN-PrabhatNeural"
TARGET_LUFS = -14.0
TRUE_PEAK = -1.5
MAX_BYTES = 50 * 1024 * 1024
# Music sits this many dB below the voice before sidechain ducking.
MUSIC_DUCK_DB = -16.0
FADE_IN_S = 0.40
FADE_OUT_S = 0.70
SPEECH_TAIL_S = 0.25  # extra hold after a longer voiceover so the last word isn't cut


def bootstrap_and_reexec() -> None:
    """Create the local venv if needed, then re-exec inside it."""
    in_our_venv = Path(sys.executable).resolve() == VENV_PY.resolve()
    if in_our_venv:
        return
    if not VENV_PY.exists():
        print("Creating tools/.venv and installing TTS dependencies…", file=sys.stderr)
        subprocess.run([sys.executable, "-m", "venv", str(TOOLS_DIR / ".venv")], check=True)
        pip = [str(VENV_PY), "-m", "pip", "install", "--upgrade", "pip"]
        subprocess.run(pip, check=True)
        if REQUIREMENTS.exists():
            subprocess.run([str(VENV_PY), "-m", "pip", "install", "-r", str(REQUIREMENTS)], check=True)
        else:
            subprocess.run([str(VENV_PY), "-m", "pip", "install", "edge-tts", "gTTS"], check=True)
    os.execv(str(VENV_PY), [str(VENV_PY), *sys.argv])


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kwargs)


def probe_duration(path: Path) -> float:
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        text=True,
    ).strip()
    return float(out)


def probe_has_audio(path: Path) -> bool:
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            str(path),
        ],
        text=True,
    ).strip()
    return bool(out)


def probe_video_size(path: Path) -> tuple[int, int]:
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0",
            str(path),
        ],
        text=True,
    ).strip()
    w, h = out.split(",")
    return int(w), int(h)


def tts_edge(text: str, dest: Path, voice: str, rate: str) -> None:
    import asyncio
    import edge_tts

    async def _synth() -> None:
        communicate = edge_tts.Communicate(text, voice=voice, rate=rate)
        await communicate.save(str(dest))

    asyncio.run(_synth())
    if dest.stat().st_size < 1000:
        raise RuntimeError("edge-tts wrote an empty or tiny file")


def tts_gtts(text: str, dest: Path) -> None:
    from gtts import gTTS

    # en / co.in reads clearly for a mixed India + global coding audience.
    tts = gTTS(text=text, lang="en", tld="co.in")
    tts.save(str(dest))
    if dest.stat().st_size < 1000:
        raise RuntimeError("gTTS wrote an empty or tiny file")


def _as_wav_path(dest: Path) -> Path:
    """espeak/piper write WAV; copy back if the caller asked for another suffix."""
    return dest if dest.suffix.lower() == ".wav" else dest.with_suffix(".wav")


def _finalize_audio(written: Path, dest: Path) -> None:
    if written.resolve() == dest.resolve():
        return
    # Keep a single dest path for the transcode step; ffmpeg autodetects WAV.
    written.replace(dest)


def tts_piper(text: str, dest: Path) -> None:
    piper = shutil.which("piper")
    if not piper:
        raise RuntimeError("piper is not installed")
    model = os.environ.get("PIPER_MODEL")
    if not model:
        # Common local locations; skip if none exist.
        candidates = [
            Path.home() / ".local/share/piper/en_US-lessac-medium.onnx",
            Path("/usr/share/piper/voices/en_US-lessac-medium.onnx"),
            TOOLS_DIR / "piper" / "en_US-lessac-medium.onnx",
        ]
        model_path = next((p for p in candidates if p.exists()), None)
        if model_path is None:
            raise RuntimeError("piper is installed but no voice model was found")
        model = str(model_path)
    wav_dest = _as_wav_path(dest)
    with wav_dest.open("wb") as fh:
        subprocess.run(
            [piper, "--model", model, "--output_file", "-"],
            input=text.encode("utf-8"),
            stdout=fh,
            check=True,
        )
    if wav_dest.stat().st_size < 1000:
        raise RuntimeError("piper wrote an empty or tiny file")
    _finalize_audio(wav_dest, dest)


def tts_espeak(text: str, dest: Path) -> None:
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    if not exe:
        raise RuntimeError("espeak-ng is not installed")
    wav_dest = _as_wav_path(dest)
    run([exe, "-v", "en-us", "-s", "165", "-w", str(wav_dest), text])
    if wav_dest.stat().st_size < 1000:
        raise RuntimeError("espeak wrote an empty or tiny file")
    _finalize_audio(wav_dest, dest)


def synthesize_speech(text: str, dest: Path, voice: str, rate: str) -> str:
    """Try TTS engines in order. Returns the name of the engine that worked."""
    engines = [
        ("edge-tts", lambda: tts_edge(text, dest, voice, rate)),
        ("gTTS", lambda: tts_gtts(text, dest)),
        ("piper", lambda: tts_piper(text, dest)),
        ("espeak-ng", lambda: tts_espeak(text, dest)),
    ]
    errors: list[str] = []
    for name, fn in engines:
        try:
            # Retry the first (network) engine once on a transient failure.
            attempts = 2 if name == "edge-tts" else 1
            last_exc: Exception | None = None
            for _ in range(attempts):
                try:
                    fn()
                    print(f"TTS: {name} succeeded", file=sys.stderr)
                    return name
                except Exception as exc:  # noqa: BLE001 — we fall through the chain
                    last_exc = exc
            raise last_exc  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")
            print(f"TTS: {name} failed ({exc}); trying next engine…", file=sys.stderr)
            dest.unlink(missing_ok=True)
    raise RuntimeError("All TTS engines failed:\n  " + "\n  ".join(errors))


def to_wav_48k_stereo(src: Path, dest: Path) -> None:
    run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src),
        "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le",
        str(dest),
    ])


def audio_mix_filter(out_dur: float, speech_dur: float, with_music: bool) -> str:
    """Build the audio graph (no loudnorm). Voice is padded to out_dur with silence."""
    pad_dur = max(0.0, out_dur - speech_dur) + 0.05
    fade_out_start = max(0.0, out_dur - FADE_OUT_S)
    parts = [
        # pad_dur is more reliable than whole_dur inside a filter graph.
        f"[0:a]aresample=48000,aformat=channel_layouts=stereo,"
        f"apad=pad_dur={pad_dur:.3f},atrim=0:{out_dur:.3f},asetpts=PTS-STARTPTS[vox]"
    ]
    if with_music:
        parts.append(
            f"[1:a]aresample=48000,aformat=channel_layouts=stereo,"
            f"atrim=0:{out_dur:.3f},asetpts=PTS-STARTPTS,"
            f"afade=t=in:st=0:d={FADE_IN_S},"
            f"afade=t=out:st={fade_out_start:.3f}:d={FADE_OUT_S},"
            f"volume={MUSIC_DUCK_DB}dB[mus]"
        )
        parts.append(
            "[mus][vox]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=280"
            ":makeup=1:knee=4:level_sc=1[ducked]"
        )
        parts.append(
            "[vox][ducked]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,"
            f"atrim=0:{out_dur:.3f},alimiter=limit=0.95[a]"
        )
    else:
        parts.append("[vox]alimiter=limit=0.95[a]")
    return ";".join(parts)


def render_mix_wav(voice_wav: Path, music: Path | None, dest: Path,
                   out_dur: float, speech_dur: float) -> None:
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(voice_wav),
    ]
    if music is not None:
        cmd.extend(["-stream_loop", "-1", "-i", str(music)])
    cmd.extend([
        "-filter_complex", audio_mix_filter(out_dur, speech_dur, music is not None),
        "-map", "[a]",
        "-c:a", "pcm_s16le",
        "-t", f"{out_dur:.3f}",
        str(dest),
    ])
    run(cmd)


def measure_loudnorm(path: Path) -> dict:
    proc = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-i", str(path),
            "-af", f"loudnorm=I={TARGET_LUFS}:TP={TRUE_PEAK}:LRA=11:print_format=json",
            "-f", "null", "-",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    err = proc.stderr
    start, end = err.rfind("{"), err.rfind("}")
    if start == -1 or end == -1:
        raise RuntimeError("loudnorm did not print measurement JSON:\n" + err[-2000:])
    return json.loads(err[start:end + 1])


def loudnorm_filter(measured: dict) -> str:
    return (
        f"loudnorm=I={TARGET_LUFS}:TP={TRUE_PEAK}:LRA=11:"
        f"measured_I={measured['input_i']}:"
        f"measured_LRA={measured['input_lra']}:"
        f"measured_TP={measured['input_tp']}:"
        f"measured_thresh={measured['input_thresh']}:"
        f"offset={measured['target_offset']}:"
        f"linear=true"
    )


def mux(
    video: Path,
    voice_wav: Path,
    music: Path | None,
    output: Path,
    video_dur: float,
    speech_dur: float,
    workdir: Path,
) -> None:
    extend = 0.0
    if speech_dur > video_dur + 0.05:
        extend = (speech_dur - video_dur) + SPEECH_TAIL_S
    out_dur = video_dur + extend

    mix_wav = workdir / "mix.wav"
    render_mix_wav(voice_wav, music, mix_wav, out_dur, speech_dur)
    measured = measure_loudnorm(mix_wav)
    print(
        f"Mix loudness: {measured['input_i']} LUFS "
        f"(target {TARGET_LUFS}, linear two-pass)",
        file=sys.stderr,
    )

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video),
        "-i", str(mix_wav),
        "-af", loudnorm_filter(measured),
    ]
    if extend > 0:
        cmd.extend([
            "-vf", f"tpad=stop_mode=clone:stop_duration={extend:.3f}",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "medium",
            "-crf", "18",
            "-profile:v", "high",
            "-level", "4.1",
            "-r", "30",
        ])
    else:
        # Keep the original video bitstream when the length does not change.
        cmd.extend(["-c:v", "copy"])

    cmd.extend([
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",
        "-ac", "2",
        "-movflags", "+faststart",
        "-t", f"{out_dur:.3f}",
        str(output),
    ])
    run(cmd)


def ensure_under_50mb(path: Path) -> None:
    size = path.stat().st_size
    if size <= MAX_BYTES:
        return
    print(f"Output is {size} bytes (>50 MB); re-encoding at CRF 23…", file=sys.stderr)
    tmp = path.with_suffix(".reenc.mp4")
    run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(path),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        str(tmp),
    ])
    tmp.replace(path)
    if path.stat().st_size > MAX_BYTES:
        raise RuntimeError(
            f"Output is still {path.stat().st_size} bytes after recompressing; "
            "it exceeds Instagram's 50 MB cap."
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Add an AI voiceover and optional quiet music bed to a silent Reel.",
    )
    p.add_argument("-i", "--input", required=True, type=Path, help="Input silent MP4")
    p.add_argument("-o", "--output", required=True, type=Path, help="Output MP4 path")
    text = p.add_mutually_exclusive_group(required=True)
    text.add_argument("-t", "--text", help="Voiceover script text")
    text.add_argument("--text-file", type=Path, help="File containing the voiceover script")
    p.add_argument("--voice", default=DEFAULT_VOICE, help=f"edge-tts voice (default: {DEFAULT_VOICE})")
    p.add_argument("--rate", default="+0%", help='edge-tts rate, e.g. "+5%%" or "-10%%"')
    p.add_argument("--music", type=Path, default=DEFAULT_MUSIC, help="Music bed file (looped/trimmed)")
    p.add_argument("--no-music", action="store_true", help="Voice only; skip the music bed")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    bootstrap_and_reexec()
    args = parse_args(argv)

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        print("ffmpeg and ffprobe are required.", file=sys.stderr)
        return 1

    input_path = args.input.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    if not input_path.is_file():
        print(f"Input not found: {input_path}", file=sys.stderr)
        return 1

    text = args.text if args.text is not None else args.text_file.read_text(encoding="utf-8")
    text = text.strip()
    if not text:
        print("Voiceover text is empty.", file=sys.stderr)
        return 1

    music_path: Path | None
    if args.no_music:
        music_path = None
    else:
        music_path = args.music.expanduser().resolve()
        if not music_path.is_file():
            print(f"Music bed not found: {music_path}", file=sys.stderr)
            return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)

    video_dur = probe_duration(input_path)
    width, height = probe_video_size(input_path)
    print(f"Input: {input_path} ({width}x{height}, {video_dur:.3f}s)", file=sys.stderr)

    with tempfile.TemporaryDirectory(prefix="add_voiceover_") as td:
        tdir = Path(td)
        raw_speech = tdir / "speech_raw.mp3"
        engine = synthesize_speech(text, raw_speech, args.voice, args.rate)
        voice_wav = tdir / "speech.wav"
        to_wav_48k_stereo(raw_speech, voice_wav)
        speech_dur = probe_duration(voice_wav)
        print(f"Speech: {speech_dur:.3f}s via {engine}", file=sys.stderr)

        mux(
            video=input_path,
            voice_wav=voice_wav,
            music=music_path,
            output=output_path,
            video_dur=video_dur,
            speech_dur=speech_dur,
            workdir=tdir,
        )

    ensure_under_50mb(output_path)
    out_dur = probe_duration(output_path)
    has_audio = probe_has_audio(output_path)
    size = output_path.stat().st_size
    print(
        f"Wrote {output_path} ({out_dur:.3f}s, {size} bytes, audio={'yes' if has_audio else 'NO'})",
        file=sys.stderr,
    )
    if not has_audio:
        print("Output has no audio stream.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
