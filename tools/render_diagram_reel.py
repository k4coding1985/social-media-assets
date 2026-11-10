#!/usr/bin/env python3
"""Render a 9:16 "dotted schematic diagram" Reel from a JSON/YAML scene spec.

Style: pure black background with drifting particles, dotted nodes
(spheres, circles, rounded boxes, tables, database cylinders, phones),
glowing white data packets travelling along dotted paths, monospace text
with the key token in bright blue (#3B82F6), word-synced captions, a small
@k4coding watermark and a short black end card.

Pipeline:
  1. Synthesize the voiceover once with edge-tts (word boundaries on).
  2. Map word timings to the spec's voiceover segments, resolve every
     timeline event's "at" anchor (e.g. "bug@twice+0.2") to seconds.
  3. Render PIL frames in parallel and pipe them to ffmpeg (H.264).
  4. Call add_voiceover.py with --speech-file (the same audio) so the
     voice + quiet music bed are mixed and loudness-normalized.

Spec format and a full example: tools/DIAGRAM_REEL_TEMPLATE.md

Usage:
  python3 tools/render_diagram_reel.py spec.json -o out.mp4 --cover cover.jpg
  python3 tools/render_diagram_reel.py spec.json -o out.mp4 --preview 1,5,12,20
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

TOOLS_DIR = Path(__file__).resolve().parent
VENV_PY = TOOLS_DIR / ".venv" / "bin" / "python"
ADD_VO = TOOLS_DIR / "add_voiceover.py"

W, H = 1080, 1920
SAFE_TOP, SAFE_BOTTOM = 220, H - 380  # no key content outside this band
FPS = 30
DEFAULT_VOICE = "en-IN-NeerjaExpressiveNeural"
DEFAULT_RATE = "+5%"
DEFAULT_PITCH = "+0Hz"

BLUE = (59, 130, 246)          # #3B82F6
BLUE_FILL = (30, 58, 138)      # #1E3A8A (used at low opacity)
WHITE = (240, 240, 240)
DOT = (205, 205, 205)
DIM = (125, 125, 125)
LABEL = (225, 225, 225)
FILL = (17, 17, 17)

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/sand-box/google/JetBrains Mono/JetBrainsMono-VariableFont_wght.ttf",
    "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Regular.ttf",
    "/usr/share/fonts/truetype/firacode/FiraCode-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]


# ----------------------------------------------------------------- utilities
def find_font() -> str:
    env = os.environ.get("DIAGRAM_REEL_FONT")
    if env and Path(env).is_file():
        return env
    for c in FONT_CANDIDATES:
        if Path(c).is_file():
            return c
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}", "JetBrains Mono"],
                             capture_output=True, text=True).stdout.strip()
        if out and Path(out).is_file():
            return out
    except FileNotFoundError:
        pass
    raise SystemExit("No monospace font found. Install JetBrains Mono "
                     "(apt install fonts-jetbrains-mono) or set DIAGRAM_REEL_FONT.")


_FONT_CACHE: dict = {}
FONT_PATH = ""


def font(size: int, weight: str = "Medium") -> ImageFont.FreeTypeFont:
    key = (size, weight)
    if key not in _FONT_CACHE:
        f = ImageFont.truetype(FONT_PATH, size)
        try:
            f.set_variation_by_name(weight)
        except Exception:
            pass
        _FONT_CACHE[key] = f
    return _FONT_CACHE[key]


def clamp(v, a=0.0, b=1.0):
    return a if v < a else b if v > b else v


def ease(u):
    u = clamp(u)
    return 4 * u * u * u if u < 0.5 else 1 - (-2 * u + 2) ** 3 / 2


def mix(c1, c2, t):
    return tuple(int(round(a + (b - a) * t)) for a, b in zip(c1, c2))


def dim(c, a):
    return tuple(int(round(v * clamp(a))) for v in c)


def parse_markup(text: str):
    """'SELECT {{key}} x' -> [(str, highlighted_bool), ...]"""
    parts, pos = [], 0
    for m in re.finditer(r"\{\{(.+?)\}\}", text):
        if m.start() > pos:
            parts.append((text[pos:m.start()], False))
        parts.append((m.group(1), True))
        pos = m.end()
    if pos < len(text):
        parts.append((text[pos:], False))
    return parts


def strip_markup(text: str) -> str:
    return re.sub(r"\{\{(.+?)\}\}", r"\1", text)


def resample(points, spacing, closed=True):
    pts = np.asarray(points, dtype=float)
    if closed:
        pts = np.vstack([pts, pts[:1]])
    seg = np.sqrt(((pts[1:] - pts[:-1]) ** 2).sum(1))
    cum = np.concatenate([[0], np.cumsum(seg)])
    total = cum[-1]
    if total <= 0:
        return pts[:1]
    n = max(2, int(round(total / spacing)))
    ts = np.linspace(0, total, n, endpoint=not closed)
    xs = np.interp(ts, cum, pts[:, 0])
    ys = np.interp(ts, cum, pts[:, 1])
    return np.stack([xs, ys], 1)


def rrect_outline(cx, cy, w, h, r, steps=10):
    r = min(r, w / 2, h / 2)
    x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
    pts = []
    corners = [(x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)]
    for ccx, ccy, a0 in corners:
        for i in range(steps + 1):
            a = math.radians(a0 + 90 * i / steps)
            pts.append((ccx + r * math.cos(a), ccy + r * math.sin(a)))
    return pts


def ellipse_arc(cx, cy, rx, ry, a0, a1, n=120):
    return [(cx + rx * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
             cy + ry * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]


def polyline_point(pts, u):
    pts = np.asarray(pts, dtype=float)
    seg = np.sqrt(((pts[1:] - pts[:-1]) ** 2).sum(1))
    cum = np.concatenate([[0], np.cumsum(seg)])
    d = clamp(u) * cum[-1]
    return float(np.interp(d, cum, pts[:, 0])), float(np.interp(d, cum, pts[:, 1]))


def _sentence_end(seg_text: str, word: str) -> bool:
    """edge-tts word boundaries drop punctuation, so look the word up in the source text."""
    m = re.search(re.escape(word) + r"([.?!,:;])", seg_text)
    return bool(m and m.group(1) in ".?!:")


def norm_word(w: str) -> str:
    return re.sub(r"[^a-z0-9#@]+", "", w.lower())


# ------------------------------------------------------------------- TTS
TTS_SNIPPET = r'''
import asyncio, json, sys
import edge_tts
text, voice, rate, pitch, out_mp3, out_json = sys.argv[1:7]
async def main():
    c = edge_tts.Communicate(text, voice=voice, rate=rate, pitch=pitch, boundary="WordBoundary")
    words = []
    with open(out_mp3, "wb") as f:
        async for chunk in c.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append({"start": chunk["offset"] / 1e7,
                              "dur": chunk["duration"] / 1e7, "text": chunk["text"]})
    json.dump(words, open(out_json, "w"))
asyncio.run(main())
'''

FALLBACK_SNIPPET = r'''
import sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from add_voiceover import synthesize_speech
print(synthesize_speech(sys.argv[2], Path(sys.argv[3]), sys.argv[4], sys.argv[5], sys.argv[6]))
'''


def ensure_venv():
    if not VENV_PY.exists():
        # add_voiceover.py bootstraps tools/.venv on first run.
        subprocess.run([sys.executable, str(ADD_VO), "--help"], capture_output=True)
    return str(VENV_PY) if VENV_PY.exists() else sys.executable


def probe_duration(p: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(p)], capture_output=True, text=True)
    return float(out.stdout.strip())


def synthesize(text, voice, rate, pitch, workdir: Path):
    py = ensure_venv()
    mp3, js = workdir / "speech.mp3", workdir / "words.json"
    script = workdir / "tts.py"
    script.write_text(TTS_SNIPPET)
    words = None
    for attempt in range(3):
        r = subprocess.run([py, str(script), text, voice, rate, pitch, str(mp3), str(js)],
                           capture_output=True, text=True)
        if r.returncode == 0 and mp3.exists() and mp3.stat().st_size > 1000:
            words = json.loads(js.read_text())
            break
        print(f"edge-tts attempt {attempt + 1} failed: {r.stderr.strip()[-300:]}", file=sys.stderr)
    engine = "edge-tts"
    if words is None:
        fb = workdir / "fallback.py"
        fb.write_text(FALLBACK_SNIPPET)
        r = subprocess.run([py, str(fb), str(TOOLS_DIR), text, str(mp3), voice, rate, pitch],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit("All TTS engines failed:\n" + r.stderr)
        engine = r.stdout.strip() + " (no word timings; estimated)"
        words = []
    return mp3, words, engine, probe_duration(mp3)


def map_segments(segments, words, speech_dur):
    """Return {seg_id: {start, end, words:[{start,end,text}]}}."""
    full, ranges = "", []
    for s in segments:
        if full:
            full += " "
        ranges.append((len(full), len(full) + len(s["text"])))
        full += s["text"]
    out = {s["id"]: {"start": None, "end": None, "words": []} for s in segments}
    if words:
        cursor = 0
        for w in words:
            idx = full.find(w["text"], cursor)
            if idx < 0:
                idx = cursor
            else:
                cursor = idx + len(w["text"])
            for s, (a, b) in zip(segments, ranges):
                if a <= idx < b + 1:
                    o = out[s["id"]]
                    o["words"].append({"start": w["start"], "end": w["start"] + w["dur"], "text": w["text"]})
                    break
        for s in segments:
            o = out[s["id"]]
            if o["words"]:
                o["start"], o["end"] = o["words"][0]["start"], o["words"][-1]["end"]
    # Fill anything missing by character-proportional estimate.
    total_chars = sum(len(s["text"]) for s in segments) or 1
    t = 0.15
    span = max(0.5, speech_dur - 0.3)
    for s in segments:
        d = span * len(s["text"]) / total_chars
        o = out[s["id"]]
        if o["start"] is None:
            o["start"], o["end"] = t, t + d
            toks = s["text"].split()
            for i, tok in enumerate(toks):
                a = t + d * i / len(toks)
                o["words"].append({"start": a, "end": a + d / len(toks), "text": tok})
        t = o["end"] + 0.1
    return out


# ------------------------------------------------------------- scene model
class Scene:
    def __init__(self, spec, seg_times, total, captions_on=True):
        self.spec = spec
        self.seg = seg_times
        self.total = total
        self.captions_on = captions_on
        self.el = {}
        self.order = []
        for e in spec.get("nodes", []) + spec.get("paths", []) + spec.get("code", []):
            e = dict(e)
            if "type" not in e:
                e["type"] = "path" if "points" in e else "code"
            self.el[e["id"]] = e
            self.order.append(e["id"])
            if e["type"] == "table":
                self._layout_table(e)
        self.tracks = {}   # id -> {"vis": [], "hl": [], "text": [], "pulse": []}
        self.moves = []    # packet moves
        self.events = []
        self._compile_timeline()
        self._precompute()
        rng = np.random.default_rng(spec.get("seed", 7))
        n = int(spec.get("particles", 90))
        self.particles = np.stack([
            rng.uniform(0, W, n), rng.uniform(0, H, n), rng.uniform(-4, 4, n),
            rng.uniform(-14, -4, n), rng.uniform(0.8, 2.2, n), rng.uniform(40, 150, n),
            rng.uniform(0, 6.28, n)], 1)
        yy, xx = np.mgrid[0:H, 0:W]
        d = np.sqrt(((xx - W / 2) / (W * 0.75)) ** 2 + ((yy - H * 0.48) / (H * 0.5)) ** 2)
        vig = np.clip(1 - d, 0, 1) ** 1.6 * 13
        self.bg = np.repeat(vig[:, :, None], 3, 2).astype(np.uint8)
        end = spec.get("end_card", {})
        seg_id = end.get("segment")
        if seg_id and seg_id in seg_times:
            self.end_start = seg_times[seg_id]["start"] + float(end.get("offset", 0.25))
        else:
            self.end_start = total - float(end.get("duration", 1.3))
        self.captions = self._build_captions()

    # --- layout helpers
    def _layout_table(self, e):
        rows = e.get("rows", [])
        row_h, gap, pad = e.get("row_h", 84), e.get("gap", 22), e.get("pad", 26)
        h = pad * 2 + len(rows) * row_h + max(0, len(rows) - 1) * gap
        e["h"] = h
        top = e["y"] - h / 2
        for i, r in enumerate(rows):
            r = {"text": r} if isinstance(r, str) else dict(r)
            rid = f'{e["id"]}.r{i}'
            r.update({"id": rid, "type": "row", "parent": e["id"],
                      "x": e["x"], "y": top + pad + row_h / 2 + i * (row_h + gap),
                      "w": e["w"] - pad * 2, "h": row_h,
                      "size": e.get("row_size", 44)})
            self.el[rid] = r

    def bbox(self, e):
        t = e["type"]
        if t in ("sphere", "circle"):
            r = e.get("r", 60)
            return e["x"] - r, e["y"] - r, e["x"] + r, e["y"] + r
        if t in ("box", "table", "row", "cylinder", "phone"):
            w, h = e.get("w", 200), e.get("h", 120)
            return e["x"] - w / 2, e["y"] - h / 2, e["x"] + w / 2, e["y"] + h / 2
        if t in ("text", "code"):
            f = font(e.get("size", 44))
            txt = ("| " if t == "code" else "") + strip_markup(e.get("text", ""))
            wdt = f.getlength(txt)
            x = e["x"] if t == "code" or e.get("align") == "left" else e["x"] - wdt / 2
            return x, e["y"], x + wdt, e["y"] + e.get("size", 44)
        return e.get("x", 0), e.get("y", 0), e.get("x", 0), e.get("y", 0)

    def anchor(self, a):
        if isinstance(a, (list, tuple)):
            return float(a[0]), float(a[1])
        parts = a.split(".")
        side = None
        if parts[-1] in ("left", "right", "top", "bottom", "center"):
            side = parts.pop()
        eid = ".".join(parts)
        if eid not in self.el:
            raise SystemExit(f"Unknown anchor element '{eid}' in '{a}'")
        x0, y0, x1, y1 = self.bbox(self.el[eid])
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        return {"left": (x0, cy), "right": (x1, cy), "top": (cx, y0),
                "bottom": (cx, y1)}.get(side, (cx, cy))

    def resolve_at(self, at, prev):
        if isinstance(at, (int, float)):
            return float(at)
        s = str(at).strip()
        if s.startswith("+") or s.startswith("-"):
            return prev + float(s)
        m = re.match(r"^([A-Za-z0-9_\-]+)(?::(start|end))?(?:@([^+\-]+?))?\s*([+\-]\s*[\d.]+)?$", s)
        if not m:
            raise SystemExit(f"Bad 'at' value: {at}")
        sid, edge, word, off = m.groups()
        if sid not in self.seg:
            raise SystemExit(f"'at' references unknown segment '{sid}'")
        seg = self.seg[sid]
        t = seg["end"] if edge == "end" else seg["start"]
        if word:
            target = norm_word(word)
            hit = next((w for w in seg["words"] if norm_word(w["text"]) == target), None)
            if hit is None:
                hit = next((w for w in seg["words"] if target in norm_word(w["text"])), None)
            if hit is None:
                print(f"warning: word '{word}' not found in segment '{sid}'", file=sys.stderr)
            else:
                t = hit["start"]
        if off:
            t += float(off.replace(" ", ""))
        return t

    def track(self, eid):
        return self.tracks.setdefault(eid, {"vis": [], "hl": [], "text": [], "pulse": []})

    def _compile_timeline(self):
        prev = 0.0
        pk_auto = 0
        for e in self.el.values():
            if e.get("start_visible"):
                self.track(e["id"])["vis"].append((-1.0, 1.0, 0.01))
                if e["type"] == "table":
                    for rid in [k for k in self.el if k.startswith(e["id"] + ".r")]:
                        if not self.el[rid].get("hidden"):
                            self.track(rid)["vis"].append((-1.0, 1.0, 0.01))
        for ev in self.spec.get("timeline", []):
            t = self.resolve_at(ev.get("at", "+0"), prev)
            prev = t
            self.events.append(t)
            act = ev.get("do")
            dur = float(ev.get("dur", 0.5))
            targets = ev.get("target", [])
            targets = targets if isinstance(targets, list) else [targets]
            if act in ("show", "hide"):
                for i, tg in enumerate(targets):
                    tt = t + i * float(ev.get("stagger", 0))
                    if tg in self.el and self.el[tg]["type"] == "table" and act == "show":
                        for rid in [k for k in self.el if k.startswith(tg + ".r")]:
                            if not self.el[rid].get("hidden"):
                                self.track(rid)["vis"].append((tt + 0.1, 1.0, dur))
                    if tg in self.el and self.el[tg]["type"] == "table" and act == "hide":
                        for rid in [k for k in self.el if k.startswith(tg + ".r")]:
                            self.track(rid)["vis"].append((tt, 0.0, dur))
                    self.track(tg)["vis"].append((tt, 1.0 if act == "show" else 0.0, dur))
            elif act in ("highlight", "unhighlight"):
                for tg in targets:
                    self.track(tg)["hl"].append((t, 1.0 if act == "highlight" else 0.0, dur))
            elif act == "swap":
                for tg in targets:
                    self.track(tg)["text"].append((t, ev["text"], float(ev.get("dur", 0.4))))
            elif act == "pulse":
                for tg in targets:
                    self.track(tg)["pulse"].append(t)
            elif act == "move":
                dur = float(ev.get("dur", 1.2))
                tos = ev.get("to")
                if "path" in ev:
                    paths = [ev["path"]] if isinstance(ev["path"], str) else ev["path"]
                    polys = [[self.anchor(p) for p in self.el[pid]["points"]] for pid in paths]
                else:
                    tos = tos if isinstance(tos, list) else [tos]
                    frm = ev["from"] if isinstance(ev["from"], list) and not isinstance(ev["from"][0], (int, float)) else [ev["from"]] * len(tos)
                    polys = []
                    for f_, to in zip(frm, tos):
                        a, b = self.anchor(f_), self.anchor(to)
                        via = ev.get("via")
                        polys.append([a] + ([self.anchor(v) for v in via] if via else []) + [b])
                pids = ev.get("packet")
                if pids is None:
                    pids = [f"_pk{pk_auto}_{i}" for i in range(len(polys))]
                    pk_auto += 1
                pids = pids if isinstance(pids, list) else [pids]
                if len(pids) < len(polys):
                    pids = [f"{pids[0]}_{i}" for i in range(len(polys))]
                for i, (pid, poly) in enumerate(zip(pids, polys)):
                    self.moves.append({"pid": pid, "pts": poly, "t0": t + i * float(ev.get("stagger", 0)),
                                       "dur": dur, "keep": bool(ev.get("keep", False)),
                                       "label": ev.get("label")})
                    self.track(pid)
            else:
                raise SystemExit(f"Unknown timeline action: {act}")
        for tr in self.tracks.values():
            for k in ("vis", "hl", "text"):
                tr[k].sort(key=lambda x: x[0])

    def _precompute(self):
        sp = 12.5
        for e in self.el.values():
            t = e["type"]
            if t in ("box", "row"):
                r = e.get("radius", 28 if t == "row" else 34)
                e["_dots"] = resample(rrect_outline(e["x"], e["y"], e["w"], e["h"], r), sp)
            elif t == "table":
                e["_dots"] = resample(rrect_outline(e["x"], e["y"], e["w"], e["h"], 30), 15)
            elif t == "phone":
                w, h = e.get("w", 130), e.get("h", 230)
                e["w"], e["h"] = w, h
                d = [resample(rrect_outline(e["x"], e["y"], w, h, 24), 11)]
                d.append(resample([(e["x"] - w * 0.3, e["y"] - h * 0.38), (e["x"] + w * 0.3, e["y"] - h * 0.38)], 11, False))
                d.append(resample([(e["x"] - w * 0.15, e["y"] + h * 0.41), (e["x"] + w * 0.15, e["y"] + h * 0.41)], 9, False))
                e["_dots"] = np.vstack(d)
            elif t == "circle":
                e["_dots"] = resample(ellipse_arc(e["x"], e["y"], e.get("r", 60), e.get("r", 60), 0, 360), 12, True)
            elif t == "cylinder":
                w, h = e.get("w", 240), e.get("h", 200)
                e["w"], e["h"] = w, h
                rx, ry = w / 2, w * 0.17
                top, bot = e["y"] - h / 2 + ry, e["y"] + h / 2 - ry
                d = [resample(ellipse_arc(e["x"], top, rx, ry, 0, 360), 10.5, True),
                     resample(ellipse_arc(e["x"], (top + bot) / 2, rx, ry, 0, 180), 10.5, False),
                     resample(ellipse_arc(e["x"], bot, rx, ry, 0, 180), 10.5, False),
                     resample([(e["x"] - rx, top), (e["x"] - rx, bot)], 10.5, False),
                     resample([(e["x"] + rx, top), (e["x"] + rx, bot)], 10.5, False)]
                e["_dots"] = np.vstack(d)
            elif t == "path":
                pts = [self.anchor(p) for p in e["points"]]
                e["_dots"] = resample(pts, e.get("spacing", 14), False)
            elif t == "sphere":
                n = int(e.get("dots", 260))
                i = np.arange(n) + 0.5
                phi = np.arccos(1 - 2 * i / n)
                theta = math.pi * (1 + 5 ** 0.5) * i
                e["_sph"] = np.stack([np.cos(theta) * np.sin(phi), np.sin(theta) * np.sin(phi), np.cos(phi)], 1)

    def _build_captions(self):
        cfg = self.spec.get("captions", {})
        kws = [k.lower().split() for k in cfg.get("keywords", [])]
        max_chars = int(cfg.get("max_chars", 28))
        chunks = []
        for s in self.spec["voiceover"]:
            if s.get("caption") is False:
                continue
            st = self.seg[s["id"]]
            if "caption" in s:
                toks = s["caption"].split()
                d = st["end"] - st["start"]
                words = [{"start": st["start"] + d * i / len(toks), "text": tok} for i, tok in enumerate(toks)]
            else:
                words = [{"start": w["start"], "text": w["text"]} for w in st["words"]]
            # keyword flags (multi-word phrases)
            norms = [norm_word(w["text"]) for w in words]
            flags = [False] * len(words)
            for kw in kws:
                kwn = [norm_word(k) for k in kw]
                for i in range(len(words) - len(kwn) + 1):
                    if norms[i:i + len(kwn)] == kwn:
                        for j in range(len(kwn)):
                            flags[i + j] = True
            cur, cur_len = [], 0
            for w, f in zip(words, flags):
                L = len(w["text"]) + (1 if cur else 0)
                if cur and (cur_len + L > max_chars):
                    chunks.append(cur)
                    cur, cur_len = [], 0
                    L = len(w["text"])
                cur.append((w["start"], w["text"], f))
                cur_len += L
                if s.get("text", "") and _sentence_end(s["text"], w["text"]):
                    chunks.append(cur)
                    cur, cur_len = [], 0
            if cur:
                chunks.append(cur)
        out = []
        for i, c in enumerate(chunks):
            end = chunks[i + 1][0][0] if i + 1 < len(chunks) else self.total
            out.append({"start": c[0][0] - 0.05, "end": min(end, c[-1][0] + 1.6), "words": c})
        return out

    # --- state evaluation
    @staticmethod
    def _value(changes, t, v0=0.0):
        v = v0
        for (t0, target, d) in changes:
            if t < t0:
                break
            v = v + (target - v) * ease((t - t0) / max(d, 1e-3))
        return v

    def vis(self, eid, t):
        e = self.el.get(eid)
        tr = self.tracks.get(eid)
        v = self._value(tr["vis"], t) if tr else 0.0
        if e and e.get("parent"):
            v = min(v, self.vis(e["parent"], t) if self.tracks.get(e["parent"]) else v)
        return v

    def text_at(self, eid, base, t):
        """Return [(text, alpha)] for crossfading label swaps."""
        tr = self.tracks.get(eid)
        if not tr or not tr["text"]:
            return [(base, 1.0)]
        cur = base
        for (t0, txt, d) in tr["text"]:
            if t < t0:
                break
            u = ease((t - t0) / d)
            if u < 1:
                return [(cur, 1 - u), (txt, u)]
            cur = txt
        return [(cur, 1.0)]

    def pulse(self, eid, t):
        tr = self.tracks.get(eid)
        if not tr:
            return 0.0
        p = 0.0
        for t0 in tr["pulse"]:
            if t0 <= t < t0 + 0.5:
                p = max(p, math.sin(math.pi * (t - t0) / 0.5))
        return p


# ---------------------------------------------------------------- drawing
def draw_markup(draw, xy, text, size, base_color, alpha, weight="Medium", anchor="la", hl_color=BLUE):
    f = font(size, weight)
    parts = parse_markup(text)
    total = sum(f.getlength(p) for p, _ in parts)
    x, y = xy
    if anchor[0] == "m":
        x -= total / 2
    elif anchor[0] == "r":
        x -= total
    for p, hl in parts:
        draw.text((x, y), p, font=f, fill=dim(hl_color if hl else base_color, alpha), anchor="l" + anchor[1])
        x += f.getlength(p)


def dots(draw, pts, color, r=2.1, glow=None, gscale=0.25, galpha=0.0):
    for x, y in pts:
        draw.ellipse((x - r, y - r, x + r, y + r), fill=color)
    if glow is not None and galpha > 0:
        gc = dim(color, galpha)
        for x, y in pts[::2]:
            gx, gy = x * gscale, y * gscale
            glow.ellipse((gx - 1.2, gy - 1.2, gx + 1.2, gy + 1.2), fill=gc)


def render_frame(scene: Scene, t: float, show_captions=True):
    img = Image.fromarray(scene.bg.copy())
    d = ImageDraw.Draw(img)
    gimg = Image.new("RGB", (W // 4, H // 4))
    g = ImageDraw.Draw(gimg)
    texts = []  # deferred text draws: (callable)

    # end-card fade for scene content
    fe = 1 - ease((t - scene.end_start) / 0.3) if t >= scene.end_start else 1.0

    # particles
    P = scene.particles
    for x0, y0, vx, vy, sz, br, ph in P:
        x = (x0 + vx * t) % W
        y = (y0 + vy * t) % H
        b = br * (0.7 + 0.3 * math.sin(ph + t * 1.3))
        d.ellipse((x - sz, y - sz, x + sz, y + sz), fill=(int(b),) * 3)

    for eid in scene.order + [k for k in scene.el if k not in scene.order]:
        e = scene.el[eid]
        a = scene.vis(eid, t) * fe
        if a <= 0.01:
            continue
        typ = e["type"]
        hl = scene._value(scene.tracks.get(eid, {}).get("hl", []), t)
        pl = scene.pulse(eid, t)
        s = 0.9 + 0.1 * a + 0.05 * pl
        cx, cy = e.get("x", 0), e.get("y", 0)
        dot_c = dim(mix(DOT, BLUE, hl), a)
        if typ in ("box", "row", "table", "phone", "circle", "cylinder", "path"):
            pts = e["_dots"]
            if typ in ("row", "box"):
                fill = mix(FILL, dim(BLUE_FILL, 0.55), hl)
                w, h = e["w"] * s, e["h"] * s
                r = e.get("radius", 28 if typ == "row" else 34) * s
                d.rounded_rectangle((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), r, fill=dim(fill, a))
            if typ == "table":
                w, h = e["w"] * s, e["h"] * s
                d.rounded_rectangle((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), 30 * s,
                                    fill=dim(mix((9, 9, 9), dim(BLUE_FILL, 0.4), hl), a))
            if typ == "cylinder":
                rx = e["w"] / 2
                g.ellipse(((cx - rx * 0.6) / 4, (cy - e["h"] / 2 - 20) / 4, (cx + rx * 0.6) / 4, (cy - e["h"] / 2 + 60) / 4),
                          fill=dim((60, 60, 60), a))
            if typ != "path":
                pts = (pts - [cx, cy]) * s + [cx, cy]
            col = dim(mix(DIM, BLUE, hl), a) if typ == "path" else dot_c
            rad = 1.9 if typ in ("path", "table") else 2.2
            dots(d, pts, col, rad, g, galpha=0.5 + 0.5 * hl)
        elif typ == "sphere":
            sph = e["_sph"]
            ang = t * e.get("spin", 0.5)
            ca, sa = math.cos(ang), math.sin(ang)
            x = sph[:, 0] * ca + sph[:, 2] * sa
            z = -sph[:, 0] * sa + sph[:, 2] * ca
            y = sph[:, 1]
            r = e.get("r", 60) * s
            order = np.argsort(z)
            base = mix(WHITE, BLUE, hl)
            for i in order:
                depth = (z[i] + 1) / 2
                rr = 1.0 + 2.2 * depth
                px, py = cx + x[i] * r, cy + y[i] * r
                d.ellipse((px - rr, py - rr, px + rr, py + rr), fill=dim(base, a * (0.25 + 0.75 * depth)))
            g.ellipse(((cx - r) / 4, (cy - r) / 4, (cx + r) / 4, (cy + r) / 4), fill=dim((45, 45, 45), a))

        # labels / inner text, drawn after glow
        if typ == "row":
            for txt, ta in scene.text_at(eid, e.get("text", ""), t):
                texts.append(("mk", (e["x"] - e["w"] / 2 + 30, e["y"]), txt, e.get("size", 44),
                              WHITE, a * ta, "Medium", "lm"))
        elif typ in ("box", "circle") and e.get("text"):
            for txt, ta in scene.text_at(eid, e["text"], t):
                texts.append(("mk", (e["x"], e["y"]), txt, e.get("size", 44), WHITE, a * ta, "Medium", "mm"))
        elif typ in ("text", "code"):
            base_txt = e.get("text", "")
            for txt, ta in scene.text_at(eid, base_txt, t):
                size = e.get("size", 44)
                col = e.get("color")
                col = tuple(int(col[i:i + 2], 16) for i in (1, 3, 5)) if isinstance(col, str) else (col or (WHITE if typ == "code" else LABEL))
                off = (1 - a) * 18
                if typ == "code":
                    texts.append(("mk", (e["x"] - off, e["y"]), "| " + txt, size, col, a * ta,
                                  e.get("weight", "Regular"), "la"))
                else:
                    anc = {"left": "la", "right": "ra"}.get(e.get("align"), "ma")
                    texts.append(("mk", (e["x"], e["y"] + off), txt, size, col, a * ta, e.get("weight", "Medium"), anc))
        if e.get("label") and typ not in ("text", "code", "path"):
            lsize = e.get("label_size", 44)
            pos = e.get("label_pos")
            x0, y0, x1, y1 = scene.bbox(e)
            if typ in ("table", "box") and pos in (None, "top"):
                xy, anc = (x0 + 6, y0 - 14), "ld"
            elif pos == "top":
                xy, anc = ((x0 + x1) / 2, y0 - 16), "md"
            elif pos == "right":
                xy, anc = (x1 + 22, (y0 + y1) / 2), "lm"
            elif pos == "left":
                xy, anc = (x0 - 22, (y0 + y1) / 2), "rm"
            else:
                xy, anc = ((x0 + x1) / 2, y1 + 18), "ma"
            for txt, ta in scene.text_at(eid + ":label", e["label"], t):
                texts.append(("mk", xy, txt, lsize, LABEL, a * ta, "Medium", anc))

    # packets
    by_pid = {}
    for m in scene.moves:
        by_pid.setdefault(m["pid"], []).append(m)
    for pid, ms in by_pid.items():
        ms = sorted(ms, key=lambda m: m["t0"])
        cur = None
        for m in ms:
            if m["t0"] <= t:
                cur = m
        if cur is None:
            continue
        u = (t - cur["t0"]) / cur["dur"]
        alpha = min(1.0, (t - cur["t0"]) / 0.15 + (0.0 if cur is not ms[0] else 0.0)) if cur is ms[0] else 1.0
        if u >= 1:
            if not cur["keep"]:
                alpha *= 1 - clamp((t - cur["t0"] - cur["dur"]) / 0.3)
            hv = scene.tracks.get(pid, {}).get("vis", [])
            hide = [c for c in hv if c[1] == 0.0 and c[0] <= t]
            if hide:
                alpha *= 1 - clamp((t - hide[-1][0]) / 0.3)
        alpha *= fe
        if alpha <= 0.01:
            continue
        ue = ease(u) if u < 1 else 1.0
        trail = [(ease(max(0, u - k * 0.05)) if u < 1 else None) for k in range(1, 5)]
        for k, tu in enumerate(trail):
            if tu is None or tu >= ue:
                continue
            px, py = polyline_point(cur["pts"], tu)
            rr = 5.5 - k * 1.1
            d.ellipse((px - rr, py - rr, px + rr, py + rr), fill=dim(WHITE, alpha * (0.55 - k * 0.12)))
        px, py = polyline_point(cur["pts"], ue)
        rr = 10
        d.ellipse((px - rr, py - rr, px + rr, py + rr), fill=dim((255, 255, 255), alpha))
        gx, gy = px / 4, py / 4
        g.ellipse((gx - 7, gy - 7, gx + 7, gy + 7), fill=dim((255, 255, 255), alpha))
        if cur.get("label"):
            texts.append(("mk", (px, py - 26), cur["label"], 36, WHITE, alpha, "Medium", "md"))

    # glow composite
    gl = gimg.filter(ImageFilter.GaussianBlur(4.5)).resize((W, H), Image.BILINEAR)
    arr = np.asarray(img, dtype=np.uint16) + (np.asarray(gl, dtype=np.uint16) * 1.4).astype(np.uint16)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)

    for kind, xy, txt, size, col, a, weight, anc in texts:
        if a > 0.01:
            draw_markup(d, xy, txt, size, col, a, weight, anc)

    # title (frame 0 onwards)
    title = scene.spec.get("title", "")
    if title:
        tsz = int(scene.spec.get("title_size", 66))
        lines = title.split("\n")
        for i, ln in enumerate(lines):
            draw_markup(d, (W / 2, 262 + i * (tsz + 12)), ln, tsz, WHITE, fe, "Bold", "ma")

    # watermark
    wm = scene.spec.get("watermark", "@k4coding")
    if wm:
        draw_markup(d, (W - 48, 232 if not title else 226), wm, 28, (115, 115, 115), 1.0, "Medium", "ra")

    # captions
    if show_captions and scene.captions_on and t < scene.end_start:
        for c in scene.captions:
            if c["start"] <= t < c["end"]:
                f = font(44, "Medium")
                line = " ".join(w for _, w, _ in c["words"])
                x = W / 2 - f.getlength(line) / 2
                y = SAFE_BOTTOM - 70
                ca = clamp((t - c["start"]) / 0.12) * clamp((c["end"] - t) / 0.12)
                for (ws, w, kw) in c["words"]:
                    spoken = t >= ws
                    col = (BLUE if kw else WHITE) if spoken else (95, 95, 95)
                    d.text((x, y), w, font=f, fill=dim(col, ca))
                    x += f.getlength(w + " ")
                break

    # end card
    if t >= scene.end_start:
        ea = ease((t - scene.end_start - 0.12) / 0.35)
        if ea > 0:
            end = scene.spec.get("end_card", {})
            l1 = end.get("line1", "Follow")  # drawn below the sphere
            l2 = end.get("line2", "{{@k4coding}}")
            draw_markup(d, (W / 2, 830), l1, 60, WHITE, ea, "Medium", "ma")
            draw_markup(d, (W / 2, 915), l2, 84, WHITE, ea, "Bold", "ma")
            sub = end.get("line3", "one bug, one diagram, daily")
            if sub:
                draw_markup(d, (W / 2, 1040), sub, 40, (150, 150, 150), ea, "Regular", "ma")
            # small dotted sphere above the text, same look as diagram spheres
            n = 220
            i = np.arange(n) + 0.5
            phi = np.arccos(1 - 2 * i / n)
            th = math.pi * (1 + 5 ** 0.5) * i
            ang = t * 0.8
            x = np.cos(th) * np.sin(phi)
            z = np.cos(phi)
            xr, zr = x * math.cos(ang) + z * math.sin(ang), -x * math.sin(ang) + z * math.cos(ang)
            y = np.sin(th) * np.sin(phi)
            r = 80 * (0.85 + 0.15 * ea)
            for k in np.argsort(zr):
                dep = (zr[k] + 1) / 2
                rr = 1.0 + 2.0 * dep
                px, py = W / 2 + xr[k] * r, 700 + y[k] * r
                col = BLUE if k % 9 == 0 else WHITE
                d.ellipse((px - rr, py - rr, px + rr, py + rr), fill=dim(col, ea * (0.25 + 0.75 * dep)))
    return img


# ------------------------------------------------------------- multiproc
_SCENE = None


def _init(spec, seg, total, font_path):
    global _SCENE, FONT_PATH
    FONT_PATH = font_path
    _SCENE = Scene(spec, seg, total)


def _render_idx(i):
    return render_frame(_SCENE, i / FPS).tobytes()


# ------------------------------------------------------------------ lint
def lint(spec, scene: Scene, total):
    warn = []
    script = " ".join(s["text"] for s in spec["voiceover"])
    n = len(script.split())
    if not 50 <= n <= 80:
        warn.append(f"voiceover is {n} words (target 50-80)")
    if not 20 <= total <= 35:
        warn.append(f"duration {total:.1f}s (target 20-35s)")
    if total - scene.end_start > 1.6:
        warn.append(f"end card is {total - scene.end_start:.2f}s (target <= 1.5s)")
    if int(spec.get("title_size", 66)) < 64:
        warn.append("title_size below 64 px")
    for e in scene.el.values():
        if e["type"] in ("path",):
            continue
        sz = e.get("size", e.get("label_size", 44))
        if e["type"] in ("text", "code", "row") and sz < 44:
            warn.append(f"{e['id']}: text size {sz} < 44")
        x0, y0, x1, y1 = scene.bbox(e)
        if y0 < SAFE_TOP or y1 > SAFE_BOTTOM - 90 or x0 < 20 or x1 > W - 20:
            warn.append(f"{e['id']}: bbox ({x0:.0f},{y0:.0f})-({x1:.0f},{y1:.0f}) outside safe area")
        if e.get("label") and e["type"] not in ("text", "code"):
            lw = font(e.get("label_size", 44)).getlength(strip_markup(e["label"]))
            if e.get("label_pos") == "left" and x0 - 22 - lw < 20:
                warn.append(f"{e['id']}: label runs off the left edge")
            if e.get("label_pos") == "right" and x1 + 22 + lw > W - 20:
                warn.append(f"{e['id']}: label runs off the right edge")
        if e["type"] == "row":
            par = scene.el[e["parent"]]
            longest = max([strip_markup(e.get("text", ""))] +
                          [strip_markup(x[1]) for x in scene.tracks.get(e["id"], {}).get("text", [])], key=len)
            if font(e.get("size", 44)).getlength(longest) > e["w"] - 50:
                warn.append(f"{e['id']}: text '{longest}' is wider than the row")
    for c in scene.el.values():
        if c["type"] == "code":
            longest = max([c.get("text", "")] + [x[1] for x in scene.tracks.get(c["id"], {}).get("text", [])],
                          key=lambda s: len(strip_markup(s)))
            if c["x"] + font(c.get("size", 44)).getlength("| " + strip_markup(longest)) > W - 30:
                warn.append(f"{c['id']}: code line too wide: '{strip_markup(longest)}'")
    iv = sorted([(x, x + 0.5) for x in scene.events] + [(m["t0"], m["t0"] + m["dur"]) for m in scene.moves])
    iv = [x for x in iv if x[0] < scene.end_start]
    if iv and iv[0][0] > 1.0:
        warn.append(f"first animation starts at {iv[0][0]:.2f}s; show the bug inside 1-2 s")
    reach = iv[0][1] if iv else 0
    for a, b in iv[1:] + [(scene.end_start, scene.end_start)]:
        if a - reach > 1.5:
            warn.append(f"nothing new moves between {reach:.1f}s and {a:.1f}s (aim for every 1-1.5 s)")
        reach = max(reach, b)
    return warn


# ------------------------------------------------------------------ main
def load_spec(p: Path):
    txt = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yml", ".yaml"):
        import yaml  # pip install pyyaml
        return yaml.safe_load(txt)
    return json.loads(txt)


def main(argv=None):
    global FONT_PATH
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--cover", type=Path, help="Write a cover JPG (frame at spec cover_at, no captions)")
    ap.add_argument("--voice", default=None)
    ap.add_argument("--rate", default=None)
    ap.add_argument("--pitch", default=None)
    ap.add_argument("--no-music", action="store_true", help="Voice only (default mixes the quiet CC0 bed)")
    ap.add_argument("--preview", help="Comma-separated seconds; write PNG frames next to the output and stop")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--strict", action="store_true", help="Fail on lint warnings")
    args = ap.parse_args(argv)

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise SystemExit(f"{tool} is required")
    FONT_PATH = find_font()
    spec = load_spec(args.spec)
    vo = spec.get("voice", {})
    voice = args.voice or vo.get("name", DEFAULT_VOICE)
    rate = args.rate or vo.get("rate", DEFAULT_RATE)
    pitch = args.pitch or vo.get("pitch", DEFAULT_PITCH)
    segments = spec["voiceover"]
    script = " ".join(s["text"].strip() for s in segments)

    out = args.output.expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="diagram_reel_") as td:
        tdir = Path(td)
        mp3, words, engine, speech_dur = synthesize(script, voice, rate, pitch, tdir)
        print(f"Speech: {speech_dur:.2f}s via {engine}, {len(words)} word timings", file=sys.stderr)
        seg = map_segments(segments, words, speech_dur)
        for s in segments:
            st = seg[s["id"]]
            print(f"  segment {s['id']:<10} {st['start']:6.2f} -> {st['end']:6.2f}s", file=sys.stderr)
        last_end = max(st["end"] for st in seg.values())
        total = round(min(speech_dur, last_end) + float(spec.get("tail", 0.3)), 3)
        if speech_dur > total:
            trimmed = tdir / "speech_trim.wav"
            subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(mp3),
                            "-t", f"{total:.3f}", "-af", "afade=t=out:st=%.3f:d=0.08" % (total - 0.08),
                            str(trimmed)], check=True)
            mp3 = trimmed
            print(f"Trimmed trailing silence: speech now {total:.2f}s", file=sys.stderr)
        scene = Scene(spec, seg, total)
        warns = lint(spec, scene, total)
        for w in warns:
            print("lint:", w, file=sys.stderr)
        if warns and args.strict:
            raise SystemExit("lint failed (--strict)")

        if args.preview:
            for ts in args.preview.split(","):
                p = out.with_name(f"{out.stem}-t{float(ts):05.2f}.png")
                render_frame(scene, float(ts)).save(p)
                print(f"preview {p}", file=sys.stderr)
            return 0

        if args.cover:
            cat = spec.get("cover_at")
            ct = scene.resolve_at(cat, 0) if cat is not None else min(scene.end_start - 0.5, 6.0)
            render_frame(scene, ct, show_captions=False).convert("RGB").save(args.cover, quality=92)
            print(f"Cover: {args.cover} (t={ct:.2f}s)", file=sys.stderr)

        n_frames = int(math.ceil(total * FPS))
        silent = tdir / "silent.mp4"
        ff = subprocess.Popen([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-profile:v", "high", "-level", "4.1", "-movflags", "+faststart", str(silent)],
            stdin=subprocess.PIPE)
        with Pool(args.workers, initializer=_init, initargs=(spec, seg, total, FONT_PATH)) as pool:
            for i, buf in enumerate(pool.imap(_render_idx, range(n_frames), chunksize=4)):
                ff.stdin.write(buf)
                if i % 150 == 0:
                    print(f"  frame {i}/{n_frames}", file=sys.stderr)
        ff.stdin.close()
        if ff.wait() != 0:
            raise SystemExit("ffmpeg encode failed")

        cmd = [str(VENV_PY) if VENV_PY.exists() else sys.executable, str(ADD_VO),
               "-i", str(silent), "-o", str(out), "--speech-file", str(mp3),
               "-t", script, "--voice", voice, f"--rate={rate}", f"--pitch={pitch}"]
        if args.no_music:
            cmd.append("--no-music")
        r = subprocess.run(cmd)
        if r.returncode != 0:
            raise SystemExit("add_voiceover.py failed")
    print(f"Done: {out} ({probe_duration(out):.2f}s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
