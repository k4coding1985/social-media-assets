#!/usr/bin/env python3
"""Render a 9:16 'viral' Reel from a JSON/YAML spec.

This is the standard for Instagram/Facebook Reels from 15 Nov 2026. It
reuses render_motion_reel.py (same canvas, series tag from frame 1,
Neerja voice, SFX, captions, add_voiceover.py mix) and adds the viral
wrapper used on the Git Mistakes #3 sample:

  * 7-beat structure (hook, pattern break, problem, fix, payoff,
    comment bait, end card)
  * hook-style end fade: the last ~0.7 s crossfades from the full-screen
    end card back to the opening hook, with FOLLOW FOR #N+1 / @K4CODING
    sitting under the hook visual so the last frame matches the first
    and the Reel loops
  * audio gate: the output must have an audio stream and mean_volume
    above -35 dB

Spec format, beats, voiceover and caption patterns:
  tools/VIRAL_REEL_TEMPLATE.md
  tools/examples/viral-git-branch-rescue.json

Usage:
  python3 tools/render_viral_reel.py SPEC -o out.mp4 --cover cover.jpg
  python3 tools/render_viral_reel.py SPEC -o out-facebook.mp4 --variant facebook --cover fb.jpg
  python3 tools/render_viral_reel.py SPEC -o out.mp4 --preview 0.5,12,25
  python3 tools/render_viral_reel.py SPEC -o out.mp4 --lint-only
"""
from __future__ import annotations

import argparse
import math
import os
import shutil
import subprocess
import sys
import tempfile
from multiprocessing import Pool
from pathlib import Path

from PIL import Image, ImageDraw

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))
import render_motion_reel as motion  # noqa: E402
import render_diagram_reel as base  # noqa: E402

W, H, FPS = motion.W, motion.H, motion.FPS
ADD_VO = motion.ADD_VO
AMBIENT = motion.AMBIENT
DEFAULT_FADE = 0.70
# Lower placement of the end-card lines on the hook frame (below the
# typical terminal / payoff window, above the caption / watermark band).
HOOK_LINE1_Y = 1190
HOOK_LINE2_Y = 1300
HOOK_LINE1_SIZE = 110
HOOK_LINE2_SIZE = 104
AUDIO_GATE_DB = -35.0


def hook_end_card(spec):
    """Return (line1, line2) for the hook-style end card."""
    end = dict(spec.get("end_card", {}))
    se = motion.series_info(spec)
    line1 = end.get("line1")
    if not line1 and se:
        line1 = f"FOLLOW FOR #{se['number'] + 1}"
    line1 = line1 or "FOLLOW"
    line2 = end.get("line2", "{{@K4CODING}}")
    return line1, line2


def hook_loop_time(scene):
    """A moment still in the hook, after start_visible code has typed in.

    Frame t=0 often has an empty code window because a `type` event at 0 s
    has fraction 0. Use the end of those opening types, but stay before the
    first pulse / colour hit (~0.15 s) so the loop frame matches the start.
    """
    t = 1 / FPS
    for e in scene.el.values():
        if not e.get("start_visible"):
            continue
        for (t0, d, _) in scene.tr.get(e["id"], {}).get("type", []):
            if t0 <= 0.05:
                t = max(t, t0 + d + 1 / FPS)
    return min(t, 0.12)


def render_hook_loop_frame(scene):
    """Hook visual (no captions) plus lower end-card lines.

    When this is the last frame of the video, a loop back to the opening
    keeps the series tag, chapter title and opening window in place.
    """
    img = motion.render_frame(scene, hook_loop_time(scene), show_captions=False, scale=False)
    line1, line2 = hook_end_card(scene.spec)
    c = motion.Ctx(ImageDraw.Draw(img))
    c.set((W / 2, HOOK_LINE1_Y), 1, 0, 0, 1)
    c.text((W / 2, HOOK_LINE1_Y), line1, "marker", HOOK_LINE1_SIZE,
           motion.PALETTE["white"], "mm")
    c.text((W / 2, HOOK_LINE2_Y), line2, "marker", HOOK_LINE2_SIZE,
           motion.PALETTE["white"], "mm", hl=motion.PALETTE["purple"])
    return img.resize((W, H), Image.LANCZOS).convert("RGB")


def blend_frames(a: Image.Image, b: Image.Image, u: float) -> Image.Image:
    u = motion.clamp(u)
    if u <= 0:
        return a
    if u >= 1:
        return b
    return Image.blend(a.convert("RGB"), b.convert("RGB"), u)


def frame_at(scene, t, hook_end, fade, last_t):
    """Motion frame, crossfading to the hook-style loop end over the last `fade` seconds."""
    img = motion.render_frame(scene, t)
    start = last_t - fade
    if t < start or fade <= 0:
        return img
    u = 1.0 if t >= last_t - 1e-6 else motion.clamp((t - start) / fade)
    return blend_frames(img, hook_end, u)


# ------------------------------------------------------------------ lint
_EMOJI = (
    "This font cannot render emoji; write 'YES or NO' rather than "
    "using emoji in on-screen text or the voiceover."
)


def _has_emoji(s: str) -> bool:
    for ch in s:
        o = ord(ch)
        if ch in "❌✅👇🔥💡⚠️✖️✔️➡️✖✔":
            return True
        if 0x1F300 <= o <= 0x1FAFF or 0x2600 <= o <= 0x27BF or 0xFE00 <= o <= 0xFE0F:
            return True
    return False


def viral_lint(spec, scene: motion.Scene, total):
    """Motion lint, plus viral-template checks (warnings, not hard errors)."""
    warn = motion.lint(spec, scene, total)
    # Replace the motion 60-90 word window with the viral 55-90 window.
    warn = [w for w in warn if "words (target 60-90)" not in w]
    segs = spec["voiceover"]
    words = " ".join(s["text"] for s in segs).split()
    if not 55 <= len(words) <= 90:
        warn.append(f"voiceover is {len(words)} words (target 55-90)")
    if not 25 <= total <= 35:
        # Keep the motion 25-40 warning out so this one is the source of truth.
        warn = [w for w in warn if "target 25-40s" not in w]
        warn.append(f"duration {total:.1f}s (target 25-35s)")
    ids = [s["id"] for s in segs]
    for need in ("hook", "bug", "fix", "follow"):
        if need not in ids:
            warn.append(f"voiceover has no '{need}' segment")
    if not any(i in ids for i in ("bait", "ask", "cta")):
        warn.append("voiceover has no comment-bait segment (id 'bait')")
    joined = " ".join(s["text"].lower() for s in segs)
    if "most devs" not in joined:
        warn.append("voiceover should include 'Most devs … here' on the pattern-break beat")
    if "comment yes or no" not in joined and "yes or no" not in joined:
        warn.append("voiceover should ask the viewer to 'Comment yes or no'")
    ch_ids = [c.get("id") for c in spec.get("chapters", [])]
    for need in ("hook", "bug", "fix"):
        if need not in ch_ids:
            warn.append(f"chapters have no '{need}' title")
    if "payoff" not in ch_ids:
        warn.append("chapters have no 'payoff' title (big number / result, beat 5)")
    if "bait" not in ch_ids:
        warn.append("chapters have no 'bait' title (YES or NO, beat 6)")
    # Tight motion: something new every 1-1.5 s (motion lint already flags 2 s).
    iv = sorted(scene.events + [(d["t0"], d["dur"]) for d in scene.dots])
    iv = [(a, a + d) for a, d in iv if 0 <= a < scene.end_start]
    reach = 0.0
    for a, b in iv + [(scene.end_start, scene.end_start)]:
        if a - reach > 1.5:
            warn.append(f"nothing new between {reach:.1f}s and {a:.1f}s (viral: motion every 1-1.5s)")
        reach = max(reach, min(b, a + 1.0))
    # Emoji / over-long title lines
    for ch in spec.get("chapters", []):
        for line in ch.get("text", "").split("\n"):
            plain = motion.strip_markup(line)
            if _has_emoji(plain):
                warn.append(f"chapter '{plain}': {_EMOJI}")
            if len(plain.split()) > 6:
                warn.append(f"chapter '{plain}' has >6 words on a line")
    for e in spec.get("elements", []):
        for key in ("text", "title", "body", "label", "tag"):
            val = e.get(key)
            if isinstance(val, str) and _has_emoji(val):
                warn.append(f"{e.get('id')}.{key}: {_EMOJI}")
        if e.get("type") == "code":
            lines = e.get("lines") or []
            if len(lines) > 3:
                warn.append(f"{e.get('id')}: problem/code window has {len(lines)} lines (max 3)")
    se = motion.series_info(spec)
    if not se:
        warn.append("set 'series' so the tag is on screen from frame 1 and the end card says FOLLOW FOR #N+1")
    return warn


# ------------------------------------------------------------------ audio gate
def audio_gate(path: Path, min_mean: float = AUDIO_GATE_DB):
    """Return (ok, message). Requires an audio stream and mean_volume > min_mean dB."""
    try:
        streams = subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=codec_type,codec_name",
             "-of", "csv=p=0", str(path)],
            text=True,
        ).strip()
    except subprocess.CalledProcessError as e:
        return False, f"ffprobe failed: {e}"
    if not streams:
        return False, "no audio stream (ffprobe)"
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path),
         "-af", "volumedetect", "-f", "null", "-"],
        check=False, capture_output=True, text=True,
    )
    mean = None
    for line in (proc.stderr or "").splitlines():
        if "mean_volume:" in line:
            try:
                mean = float(line.split("mean_volume:")[1].split("dB")[0].strip())
            except ValueError:
                pass
    if mean is None:
        return False, "volumedetect did not report mean_volume"
    if mean <= min_mean:
        return False, f"mean_volume {mean:.1f} dB (need > {min_mean:.0f} dB)"
    return True, f"audio stream ok, mean_volume {mean:.1f} dB"


# ------------------------------------------------------------------ main
_SCENE = None
_HOOK_END = None
_FADE = DEFAULT_FADE
_LAST_T = 0.0


def _init(spec, seg, total, fade, last_t):
    global _SCENE, _HOOK_END, _FADE, _LAST_T
    _SCENE = motion.Scene(spec, seg, total)
    _HOOK_END = render_hook_loop_frame(_SCENE)
    _FADE = fade
    _LAST_T = last_t


def _render_idx(i):
    return frame_at(_SCENE, i / FPS, _HOOK_END, _FADE, _LAST_T).tobytes()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--cover", type=Path, help="also write a cover JPG (frame at cover_at, no captions)")
    ap.add_argument("--variant", help="apply spec.variants.NAME (e.g. facebook)")
    ap.add_argument("--voice"), ap.add_argument("--rate"), ap.add_argument("--pitch")
    ap.add_argument("--music", type=Path, default=AMBIENT, help="music bed (default: ambient pad, CC0)")
    ap.add_argument("--no-music", action="store_true")
    ap.add_argument("--no-sfx", action="store_true")
    ap.add_argument("--sfx-db", type=float, default=None, help="SFX level vs voice peak (default -18 dB)")
    ap.add_argument("--no-captions", action="store_true")
    ap.add_argument("--preview", help="comma-separated seconds: write PNGs next to the output and stop")
    ap.add_argument("--lint-only", action="store_true")
    ap.add_argument("--strict", action="store_true", help="fail on lint warnings")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--fade", type=float, default=None,
                    help=f"hook-style end-fade length in seconds (default {DEFAULT_FADE})")
    ap.add_argument("--skip-audio-gate", action="store_true",
                    help="do not fail if the mix is missing audio or is quieter than -35 dB")
    args = ap.parse_args(argv)
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise SystemExit(f"{tool} is required")

    spec = motion.apply_variant(base.load_spec(args.spec), args.variant)
    if args.no_captions:
        spec.setdefault("captions", {})["enabled"] = False
    vo = spec.get("voice", {})
    voice = args.voice or vo.get("name", "en-IN-NeerjaExpressiveNeural")
    rate = args.rate or vo.get("rate", "+5%")
    pitch = args.pitch or vo.get("pitch", "+0Hz")
    segs = spec["voiceover"]
    script = " ".join(s["text"].strip() for s in segs)
    out = args.output.expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    fade = float(args.fade if args.fade is not None else spec.get("end_card", {}).get("fade", DEFAULT_FADE))

    with tempfile.TemporaryDirectory(prefix="viral_reel_") as td:
        tdir = Path(td)
        mp3, words, engine, speech_dur = base.synthesize(script, voice, rate, pitch, tdir)
        print(f"Speech: {speech_dur:.2f}s via {engine}, {len(words)} word timings", file=sys.stderr)
        seg = base.map_segments(segs, words, speech_dur)
        for s in segs:
            print(f"  segment {s['id']:<8} {seg[s['id']]['start']:6.2f} -> {seg[s['id']]['end']:6.2f}s",
                  file=sys.stderr)
        total = round(min(speech_dur, max(v["end"] for v in seg.values())) + float(spec.get("tail", 0.35)), 3)
        scene = motion.Scene(spec, seg, total)
        warns = viral_lint(spec, scene, total)
        for w in warns:
            print("lint:", w, file=sys.stderr)
        print(f"Total {total:.2f}s, end card {total - scene.end_start:.2f}s, "
              f"hook fade {fade:.2f}s, {len(scene.sfx)} SFX hits", file=sys.stderr)
        if warns and args.strict:
            raise SystemExit("lint failed (--strict)")
        if args.lint_only:
            return 0

        n_frames = int(math.ceil(total * FPS))
        last_t = (n_frames - 1) / FPS
        hook_end = render_hook_loop_frame(scene)

        if args.preview:
            for ts in args.preview.split(","):
                p = out.with_name(f"{out.stem}-t{float(ts):05.2f}.png")
                frame_at(scene, float(ts), hook_end, fade, last_t).save(p)
                print(f"preview {p}", file=sys.stderr)
            return 0
        if args.cover:
            cat = spec.get("cover_at")
            ct = scene.at(cat, 0) if cat is not None else min(scene.end_start - 0.5, 6.0)
            motion.render_frame(scene, ct, show_captions=False).save(args.cover, quality=92)
            print(f"Cover: {args.cover} (t={ct:.2f}s)", file=sys.stderr)

        silent = tdir / "silent.mp4"
        ff = subprocess.Popen([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-profile:v", "high", "-level", "4.1", "-movflags", "+faststart", str(silent)],
            stdin=subprocess.PIPE)
        with Pool(args.workers, initializer=_init, initargs=(spec, seg, total, fade, last_t)) as pool:
            for i, buf in enumerate(pool.imap(_render_idx, range(n_frames), chunksize=4)):
                ff.stdin.write(buf)
                if i % 150 == 0:
                    print(f"  frame {i}/{n_frames}", file=sys.stderr)
        ff.stdin.close()
        if ff.wait() != 0:
            raise SystemExit("ffmpeg encode failed")

        speech = Path(mp3)
        if not args.no_sfx:
            sfx_db = args.sfx_db if args.sfx_db is not None else float(spec.get("sfx_db", -18))
            speech = motion.mix_voice_sfx(speech, scene, total, tdir / "voice_sfx.wav", sfx_db)
        py = str(base.VENV_PY) if base.VENV_PY.exists() else sys.executable
        cmd = [py, str(ADD_VO), "-i", str(silent), "-o", str(out), "--speech-file", str(speech),
               "-t", script, "--voice", voice, f"--rate={rate}", f"--pitch={pitch}"]
        if args.no_music:
            cmd.append("--no-music")
        else:
            cmd += ["--music", str(args.music)]
        if subprocess.run(cmd).returncode != 0:
            raise SystemExit("add_voiceover.py failed")

    dur = base.probe_duration(out)
    print(f"Done: {out} ({dur:.2f}s)", file=sys.stderr)
    if not args.skip_audio_gate:
        ok, msg = audio_gate(out)
        print(f"audio gate: {msg}", file=sys.stderr)
        if not ok:
            raise SystemExit(f"audio gate failed: {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
