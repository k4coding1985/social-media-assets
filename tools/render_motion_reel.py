#!/usr/bin/env python3
"""Render a 9:16 "motion-graphics explainer" Reel from a JSON/YAML spec.

Style (matches the DDoS-explainer reference):
  * flat near-black background (#0B0B0C), no particles
  * a big hand-drawn marker CHAPTER TITLE just under the top safe zone
    (Permanent Marker, all caps, one highlight word coloured by meaning)
    that changes per chapter (hook / bug / why / fix)
  * one continuous vector canvas: dark rounded UI windows (#1C1C24) with
    Mac traffic-light dots, small code windows (mono, purple keywords),
    white line-art icons (user, laptop, server, database), straight
    connection lines with small cyan (ok) / red (bad) data dots moving
    along them, capacity bars that fill cyan and turn red when overloaded,
    red X / DENIED-style badges, uppercase Inter labels
  * elements slide / fade / pop / retype exactly when the voice says the word
  * Neerja voiceover + very low ambient pad + quiet auto-placed UI SFX
    (whoosh, pop, typing ticks, alert, ding)
  * optional word-synced captions above the bottom safe zone (default ON),
    small @k4coding watermark, <= 1.5 s marker-font end card

Reuses the TTS / word-timing / segment mapping from render_diagram_reel.py
and the mixer/loudness pipeline from add_voiceover.py.

Spec format and a full example: tools/MOTION_REEL_TEMPLATE.md,
tools/motion_specs/n-plus-one-queries.json

Usage:
  python3 tools/render_motion_reel.py SPEC -o out.mp4 --cover cover.jpg
  python3 tools/render_motion_reel.py SPEC -o out-facebook.mp4 --variant facebook --cover fb.jpg
  python3 tools/render_motion_reel.py SPEC -o out.mp4 --preview 0,3.5,9,15,22
  python3 tools/render_motion_reel.py SPEC -o out.mp4 --lint-only
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))
import render_diagram_reel as base  # noqa: E402  (shared TTS + timing helpers)

ADD_VO = TOOLS_DIR / "add_voiceover.py"
FONTS = TOOLS_DIR / "fonts"
SFX_DIR = TOOLS_DIR / "sfx"
AMBIENT = TOOLS_DIR / "music" / "ambient-pad-bed.mp3"

W, H = 1080, 1920
SAFE_TOP, SAFE_BOTTOM = 220, H - 380
FPS = 30
SS = 2  # supersampling factor (anti-aliased lines/shapes)

PALETTE = {
    "bg": (11, 11, 12), "panel": (28, 28, 36), "panel2": (36, 36, 46),
    "header_line": (52, 52, 64), "white": (242, 242, 242), "grey": (160, 160, 160),
    "dim": (90, 90, 100), "line": (78, 78, 92),
    "red": (255, 91, 91), "bad": (255, 75, 75), "yellow": (255, 183, 77),
    "orange": (244, 129, 32), "purple": (157, 123, 255), "cyan": (66, 211, 165),
    "green": (66, 211, 165), "teal": (66, 211, 165), "mac_red": (255, 95, 86),
    "mac_yellow": (255, 189, 46), "mac_green": (39, 201, 63), "track": (44, 44, 54),
}
BG = PALETTE["bg"]

FONT_FILES = {
    "marker": [FONTS / "PermanentMarker-Regular.ttf",
               Path("/usr/share/fonts/truetype/sand-box/google/Permanent Marker/PermanentMarker-Regular.ttf")],
    "sans": [FONTS / "Inter-Variable.ttf",
             Path("/usr/share/fonts/truetype/sand-box/google/Inter/Inter-VariableFont_opsz,wght.ttf")],
    "mono": [FONTS / "JetBrainsMono-Variable.ttf",
             Path("/usr/share/fonts/truetype/sand-box/google/JetBrains Mono/JetBrainsMono-VariableFont_wght.ttf"),
             Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")],
}
_FC: dict = {}


def font(kind: str, size: float, weight: str = "Bold"):
    size = max(6, int(round(size)))
    key = (kind, size, weight)
    if key not in _FC:
        path = next((p for p in FONT_FILES[kind] if p.is_file()), None)
        if path is None:
            raise SystemExit(f"font '{kind}' missing; expected {FONT_FILES[kind][0]}")
        f = ImageFont.truetype(str(path), size)
        if kind != "marker":
            try:
                f.set_variation_by_name(weight)
            except Exception:
                pass
        _FC[key] = f
    return _FC[key]


def color(c, default="white"):
    if c is None:
        c = default
    if isinstance(c, (list, tuple)):
        return tuple(int(v) for v in c[:3])
    c = str(c)
    if c.startswith("#"):
        return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))
    return PALETTE[c]


clamp, ease, mix = base.clamp, base.ease, base.mix
parse_markup, strip_markup, norm_word = base.parse_markup, base.strip_markup, base.norm_word


def ease_out(u):
    u = clamp(u)
    return 1 - (1 - u) ** 3


def ease_back(u, k=1.7):
    u = clamp(u)
    return 1 + (k + 1) * (u - 1) ** 3 + k * (u - 1) ** 2


def blend(c, a):
    """Fade a colour toward the background (cheap alpha on a flat bg)."""
    return mix(BG, c, clamp(a))


# ------------------------------------------------------------ drawing ctx
class Ctx:
    """Thin wrapper over ImageDraw at SS x resolution with a per-element
    transform (scale about a pivot + offset) and an alpha."""

    def __init__(self, draw):
        self.d = draw
        self.px = self.py = 0.0
        self.s = 1.0
        self.dx = self.dy = 0.0
        self.a = 1.0

    def set(self, pivot=(0, 0), s=1.0, dx=0.0, dy=0.0, a=1.0):
        self.px, self.py = pivot
        self.s, self.dx, self.dy, self.a = s, dx, dy, a

    def T(self, x, y):
        return ((self.px + (x - self.px) * self.s + self.dx) * SS,
                (self.py + (y - self.py) * self.s + self.dy) * SS)

    def L(self, v):
        return v * self.s * SS

    def col(self, c, a=1.0):
        return blend(c, self.a * a)

    def rrect(self, x0, y0, x1, y1, r, fill=None, outline=None, width=0, a=1.0):
        X0, Y0 = self.T(x0, y0)
        X1, Y1 = self.T(x1, y1)
        self.d.rounded_rectangle((X0, Y0, X1, Y1), max(0, self.L(r)),
                                 fill=self.col(fill, a) if fill else None,
                                 outline=self.col(outline, a) if outline else None,
                                 width=max(1, int(self.L(width))) if outline else 0)

    def ellipse(self, cx, cy, rx, ry=None, fill=None, outline=None, width=0, a=1.0):
        ry = rx if ry is None else ry
        X0, Y0 = self.T(cx - rx, cy - ry)
        X1, Y1 = self.T(cx + rx, cy + ry)
        self.d.ellipse((X0, Y0, X1, Y1), fill=self.col(fill, a) if fill else None,
                       outline=self.col(outline, a) if outline else None,
                       width=max(1, int(self.L(width))) if outline else 0)

    def arc(self, cx, cy, rx, ry, a0, a1, c, width, a=1.0):
        X0, Y0 = self.T(cx - rx, cy - ry)
        X1, Y1 = self.T(cx + rx, cy + ry)
        self.d.arc((X0, Y0, X1, Y1), a0, a1, fill=self.col(c, a), width=max(1, int(self.L(width))))

    def line(self, pts, c, width, a=1.0, dash=None):
        P = [self.T(*p) for p in pts]
        wd = max(1, int(self.L(width)))
        if not dash:
            self.d.line(P, fill=self.col(c, a), width=wd, joint="curve")
            return
        on, off = dash[0] * SS * self.s, dash[1] * SS * self.s
        for (x0, y0), (x1, y1) in zip(P[:-1], P[1:]):
            L = math.hypot(x1 - x0, y1 - y0)
            k = 0.0
            while k < L:
                e = min(L, k + on)
                self.d.line([(x0 + (x1 - x0) * k / L, y0 + (y1 - y0) * k / L),
                             (x0 + (x1 - x0) * e / L, y0 + (y1 - y0) * e / L)],
                            fill=self.col(c, a), width=wd)
                k += on + off

    def text(self, xy, text, kind, size, c, anchor="la", weight="Bold", hl=None, a=1.0, upper=False):
        """Markup-aware text: {{word}} gets colour `hl`."""
        if upper:
            text = text.upper()
        f = font(kind, self.L(size), weight)
        parts = parse_markup(text)
        total = sum(f.getlength(p) for p, _ in parts)
        X, Y = self.T(*xy)
        if anchor[0] == "m":
            X -= total / 2
        elif anchor[0] == "r":
            X -= total
        for p, h in parts:
            self.d.text((X, Y), p, font=f, fill=self.col((hl or c) if h else c, a), anchor="l" + anchor[1])
            X += f.getlength(p)
        return total / SS / self.s


def text_width(text, kind, size, weight="Bold"):
    f = font(kind, size * SS, weight)
    return f.getlength(strip_markup(text)) / SS


# --------------------------------------------------------------- icons
def draw_icon(c: Ctx, kind, x, y, size, col, lw=None):
    s = size
    lw = lw or max(3.0, s * 0.055)
    if kind == "user":
        c.ellipse(x, y - s * 0.22, s * 0.2, outline=col, width=lw)
        c.arc(x, y + s * 0.42, s * 0.36, s * 0.36, 180, 360, col, lw)
        c.line([(x - s * 0.36, y + s * 0.42), (x - s * 0.36, y + s * 0.47)], col, lw)
        c.line([(x + s * 0.36, y + s * 0.42), (x + s * 0.36, y + s * 0.47)], col, lw)
    elif kind == "laptop":
        c.rrect(x - s * 0.38, y - s * 0.32, x + s * 0.38, y + s * 0.18, s * 0.05, outline=col, width=lw)
        c.line([(x - s * 0.5, y + s * 0.3), (x + s * 0.5, y + s * 0.3)], col, lw)
        c.line([(x - s * 0.42, y + s * 0.22), (x - s * 0.5, y + s * 0.3)], col, lw)
        c.line([(x + s * 0.42, y + s * 0.22), (x + s * 0.5, y + s * 0.3)], col, lw)
    elif kind == "server":
        for k in range(3):
            y0 = y - s * 0.42 + k * s * 0.29
            c.rrect(x - s * 0.36, y0, x + s * 0.36, y0 + s * 0.24, s * 0.04, outline=col, width=lw)
            c.ellipse(x - s * 0.22, y0 + s * 0.12, s * 0.035, fill=col)
            c.line([(x + s * 0.0, y0 + s * 0.12), (x + s * 0.24, y0 + s * 0.12)], col, lw * 0.8)
    elif kind == "database":
        rx, ry = s * 0.34, s * 0.11
        top, bot = y - s * 0.34, y + s * 0.34
        c.ellipse(x, top, rx, ry, outline=col, width=lw)
        c.arc(x, y, rx, ry, 0, 180, col, lw)
        c.arc(x, bot, rx, ry, 0, 180, col, lw)
        c.line([(x - rx, top), (x - rx, bot)], col, lw)
        c.line([(x + rx, top), (x + rx, bot)], col, lw)
    elif kind == "store":
        c.rrect(x - s * 0.36, y - s * 0.1, x + s * 0.36, y + s * 0.38, s * 0.03, outline=col, width=lw)
        c.line([(x - s * 0.42, y - s * 0.1), (x - s * 0.32, y - s * 0.36), (x + s * 0.32, y - s * 0.36),
                (x + s * 0.42, y - s * 0.1), (x - s * 0.42, y - s * 0.1)], col, lw)
        c.rrect(x - s * 0.12, y + s * 0.1, x + s * 0.06, y + s * 0.38, 0, outline=col, width=lw)
    elif kind == "globe":
        c.ellipse(x, y, s * 0.4, outline=col, width=lw)
        c.ellipse(x, y, s * 0.17, s * 0.4, outline=col, width=lw)
        c.line([(x - s * 0.4, y), (x + s * 0.4, y)], col, lw)
    elif kind == "lock":
        c.rrect(x - s * 0.32, y - s * 0.05, x + s * 0.32, y + s * 0.4, s * 0.05, outline=col, width=lw)
        c.arc(x, y - s * 0.05, s * 0.2, s * 0.26, 180, 360, col, lw)
    elif kind == "cpu":
        c.rrect(x - s * 0.3, y - s * 0.3, x + s * 0.3, y + s * 0.3, s * 0.05, outline=col, width=lw)
        c.rrect(x - s * 0.13, y - s * 0.13, x + s * 0.13, y + s * 0.13, 0, outline=col, width=lw)
        for k in (-0.15, 0, 0.15):
            for (a, b) in (((k, -0.3), (k, -0.42)), ((k, 0.3), (k, 0.42)), ((-0.3, k), (-0.42, k)), ((0.3, k), (0.42, k))):
                c.line([(x + s * a[0], y + s * a[1]), (x + s * b[0], y + s * b[1])], col, lw * 0.8)
    else:
        raise SystemExit(f"unknown icon kind '{kind}'")


# ------------------------------------------------------------- scene model
class Scene:
    def __init__(self, spec, seg, total):
        self.spec, self.seg, self.total = spec, seg, total
        self.el, self.order = {}, []
        for e in spec.get("elements", []):
            e = dict(e)
            self.el[e["id"]] = e
            self.order.append(e["id"])
            self._layout(e)
        self.tr = {}
        self.dots = []        # data dots in flight
        self.sfx = []         # (t, name, gain)
        self.events = []      # (t, dur) motion intervals for lint
        end = spec.get("end_card", {})
        sid = end.get("segment", "follow")
        max_end = float(end.get("max_duration", 1.45))
        self.end_start = max(seg[sid]["start"] + float(end.get("offset", 0.1)), total - max_end) \
            if sid in seg else total - max_end
        self.chapters = self._chapters()
        self._timeline()
        self.captions = self._captions()

    # ---- layout
    def _layout(self, e):
        t = e["type"]
        if t == "code":
            e.setdefault("size", 44)
            lh = e["size"] * 1.45
            e["_lh"] = lh
            n = max([len(e.get("lines", []))] + [len(s) for s in e.get("_alt_lines", [])] + [e.get("min_lines", 0)])
            e["h"] = e.get("h", 70 + 36 + n * lh)
        if t in ("window", "code", "bar", "badge"):
            e.setdefault("w", 800)
        if t == "bar":
            e.setdefault("h", 52)
        if t == "badge":
            sz = e.get("size", 44)
            if e.get("kind", "stamp") == "stamp":
                e["w"] = text_width(e.get("text", "DENIED"), "sans", sz, "ExtraBold") + 56
                e["h"] = sz + 34
            else:
                e["w"] = e["h"] = e.get("r", 44) * 2
        if t == "icon":
            e.setdefault("size", 110)
            e["w"] = e["h"] = e["size"]

    def bbox(self, e):
        t = e["type"]
        x, y = e.get("x", 0), e.get("y", 0)
        if t in ("window", "code", "bar", "badge", "icon"):
            x0, y0, x1, y1 = x - e["w"] / 2, y - e["h"] / 2, x + e["w"] / 2, y + e["h"] / 2
            if t == "icon" and e.get("label"):
                y1 += 18 + e.get("label_size", 44)
            if t == "bar" and (e.get("label") or e.get("label_right")):
                y0 -= 16 + e.get("label_size", 44)
            return x0, y0, x1, y1
        if t in ("text", "counter"):
            sz = e.get("size", 44)
            longest = max([self._fmt(e, e.get("value", 0)) if t == "counter" else e.get("text", "")] +
                          [s[1] for s in self.tr.get(e["id"], {}).get("text", [])] +
                          ([self._fmt(e, v[1]) for v in self.tr.get(e["id"], {}).get("val", [])] if t == "counter" else []),
                          key=lambda s: len(strip_markup(s)))
            wd = text_width(longest.upper() if e.get("upper", True) else longest,
                            e.get("font", "sans"), sz, e.get("weight", "ExtraBold"))
            al = e.get("align", "center")
            x0 = x if al == "left" else x - wd if al == "right" else x - wd / 2
            return x0, y - sz / 2, x0 + wd, y + sz / 2
        if t == "line":
            (ax, ay), (bx, by) = self.anchor(e["from"]), self.anchor(e["to"])
            return min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)
        return x, y, x, y

    def anchor(self, a):
        if isinstance(a, (list, tuple)):
            return float(a[0]), float(a[1])
        m = re.match(r"^(.+?)(?:\.(left|right|top|bottom|center))?([+\-]\d+(?:\.\d+)?)?(?:,([+\-]?\d+(?:\.\d+)?))?$", a)
        eid, side, ox, oy = m.groups()
        if eid not in self.el:
            raise SystemExit(f"unknown anchor element '{eid}' in '{a}'")
        e = self.el[eid]
        x0, y0, x1, y1 = self.bbox(e) if e["type"] != "icon" else \
            (e["x"] - e["w"] / 2, e["y"] - e["h"] / 2, e["x"] + e["w"] / 2, e["y"] + e["h"] / 2)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        p = {"left": (x0, cy), "right": (x1, cy), "top": (cx, y0), "bottom": (cx, y1)}.get(side, (cx, cy))
        return p[0] + float(ox or 0), p[1] + float(oy or 0)

    def at(self, at, prev):
        return base.Scene.resolve_at(self, at, prev)

    def T(self, eid):
        return self.tr.setdefault(eid, {"vis": [], "val": [], "text": [], "col": [], "pulse": [],
                                        "shake": [], "type": []})

    # ---- chapters
    def _chapters(self):
        out, prev = [], 0.0
        for ch in self.spec.get("chapters", []):
            t = self.at(ch.get("at", 0), prev) if out else -1.0
            prev = max(prev, t)
            out.append({"t": t, "id": ch.get("id"), "text": ch["text"], "hl": color(ch.get("color", "yellow")),
                        "size": int(ch.get("size", self.spec.get("chapter_size", 92)))})
            if out[-1]["t"] > 0:
                self.sfx.append((t, "whoosh", 0.55))
                self.events.append((t, 0.5))
        return out

    # ---- timeline
    def _timeline(self):
        prev = 0.0
        for e in self.el.values():
            if e.get("start_visible"):
                self.T(e["id"])["vis"].append((-1.0, 1.0, 0.01, "fade"))
            if e["type"] == "code" and not e.get("typed", True) is False and e.get("start_visible") and e.get("typed_at_start"):
                pass
        for ev in self.spec.get("timeline", []):
            t = self.at(ev.get("at", "+0"), prev)
            prev = t
            act = ev["do"]
            dur = float(ev.get("dur", {"send": 0.9, "type": 1.0, "set": 0.8}.get(act, 0.45)))
            tg = ev.get("target", [])
            tg = tg if isinstance(tg, list) else [tg]
            stag = float(ev.get("stagger", 0.08 if act == "show" else 0))
            sfx = ev.get("sfx", "auto")
            self.events.append((t, dur))
            if act in ("show", "hide"):
                anim = ev.get("anim", "pop")
                for i, g in enumerate(tg):
                    self._need(g)
                    tt = t + i * stag
                    self.T(g)["vis"].append((tt, 1.0 if act == "show" else 0.0, dur, anim))
                    e = self.el[g]
                    if act == "show" and e["type"] == "code" and e.get("autotype", True):
                        self.T(g)["type"].append((tt + dur * 0.6, float(ev.get("type_dur", 0.9)), None))
                        self._typing_sfx(tt + dur * 0.6, float(ev.get("type_dur", 0.9)))
                if act == "show" and sfx != "none":
                    name = sfx if sfx != "auto" else ("whoosh" if anim.startswith("slide") else "pop")
                    self.sfx.append((t, name, 0.5 if name == "whoosh" else 0.6))
            elif act == "set":
                for g in tg:
                    self._need(g)
                    self.T(g)["val"].append((t, float(ev["value"]), dur))
                    if sfx not in ("auto", "none"):
                        self.sfx.append((t, sfx, 0.7))
            elif act == "swap":
                for g in tg:
                    self._need(g)
                    e = self.el[g]
                    if e["type"] == "code":
                        self.T(g)["text"].append((t, ev["lines"], 0.25))
                        if ev.get("retype", True):
                            td = float(ev.get("type_dur", 1.0))
                            self.T(g)["type"].append((t + 0.2, td, ev["lines"]))
                            self._typing_sfx(t + 0.2, td)
                    else:
                        self.T(g)["text"].append((t, ev["text"], float(ev.get("dur", 0.3))))
                if sfx not in ("auto", "none"):
                    self.sfx.append((t, sfx, 0.6))
            elif act == "type":
                for g in tg:
                    self.T(g)["type"].append((t, dur, None))
                self._typing_sfx(t, dur)
            elif act == "color":
                for g in tg:
                    self._need(g)
                    self.T(g)["col"].append((t, ev["color"], dur))
                if sfx not in ("auto", "none"):
                    self.sfx.append((t, sfx, 0.7))
            elif act == "pulse":
                for g in tg:
                    self.T(g)["pulse"].append(t)
                if sfx not in ("auto", "none"):
                    self.sfx.append((t, sfx, 0.6))
            elif act == "shake":
                for g in tg:
                    self.T(g)["shake"].append((t, dur))
                if sfx not in ("auto", "none"):
                    self.sfx.append((t, sfx, 0.7))
            elif act == "send":
                self._send(ev, t, dur, sfx)
            elif act == "sfx":
                self.sfx.append((t, ev["name"], float(ev.get("gain", 0.6))))
            else:
                raise SystemExit(f"unknown timeline action '{act}'")
        for tr in self.tr.values():
            for k in ("vis", "val", "text", "col", "type"):
                tr[k].sort(key=lambda x: x[0])

    def _need(self, g):
        if g.split(":")[0] not in self.el:
            raise SystemExit(f"timeline targets unknown element '{g}'")

    def _typing_sfx(self, t0, dur):
        rng = np.random.default_rng(int(t0 * 1000))
        t = t0
        while t < t0 + dur:
            self.sfx.append((t, "tick", float(rng.uniform(0.25, 0.45))))
            t += float(rng.uniform(0.05, 0.09))

    def _send(self, ev, t, dur, sfx):
        count = int(ev.get("count", 1))
        interval = float(ev.get("interval", 0.15))
        col = ev.get("color", "cyan")
        polys, ends = [], []
        if "path" in ev:
            paths = ev["path"] if isinstance(ev["path"], list) else [ev["path"]]
            for p in paths:
                ln = self.el[p]
                a, b = self.anchor(ln["from"]), self.anchor(ln["to"])
                tgt = ln["from"] if ev.get("reverse") else ln["to"]
                polys.append([b, a] if ev.get("reverse") else [a, b])
                ends.append(tgt if isinstance(tgt, str) else None)
        else:
            frm, to = ev["from"], ev["to"]
            frm = frm if isinstance(frm, list) and frm and isinstance(frm[0], (list, str)) else [frm]
            to = to if isinstance(to, list) and to and isinstance(to[0], (list, str)) else [to]
            n = max(len(frm), len(to))
            for i in range(n):
                f_, t_ = frm[i % len(frm)], to[i % len(to)]
                polys.append([self.anchor(f_)] + [self.anchor(v) for v in ev.get("via", [])] + [self.anchor(t_)])
                ends.append(t_ if isinstance(t_, str) else None)
        hit = ev.get("pulse", "auto")
        last_pop = -9.0
        for k in range(count):
            i = k % len(polys)
            t0 = t + k * interval
            self.dots.append({"t0": t0, "dur": dur, "pts": polys[i], "col": col,
                              "r": float(ev.get("r", 9)), "label": ev.get("label")})
            arr = t0 + dur
            tgt = ends[i] if hit == "auto" else hit
            if tgt:
                tid = tgt.split(".")[0]
                if tid in self.el:
                    self.T(tid)["pulse"].append(arr)
            if sfx != "none" and arr - last_pop >= 0.14:
                self.sfx.append((arr, "pop" if sfx == "auto" else sfx, 0.35 if count > 3 else 0.5))
                last_pop = arr
        self.events.append((t, dur + (count - 1) * interval))

    # ---- captions (reuses diagram renderer logic)
    def _captions(self):
        cfg = self.spec.get("captions", {})
        return base.Scene._build_captions(self) if cfg.get("enabled", True) else []

    # ---- state
    @staticmethod
    def _value(ch, t, v0=0.0):
        v = v0
        for c in ch:
            t0, target, d = c[0], c[1], c[2]
            if t < t0:
                break
            v = v + (target - v) * ease((t - t0) / max(d, 1e-3))
        return v

    def vis(self, eid, t):
        tr = self.tr.get(eid)
        if not tr or not tr["vis"]:
            return 0.0, None, 1.0
        v, last, prog = 0.0, None, 1.0
        for (t0, target, d, anim) in tr["vis"]:
            if t < t0:
                break
            u = clamp((t - t0) / max(d, 1e-3))
            v = v + (target - v) * ease(u)
            last, prog = (anim, target), u
        return v, last, prog

    def val(self, eid, t, v0):
        return self._value(self.tr.get(eid, {}).get("val", []), t, v0)

    def col(self, eid, base_col, t):
        c = color(base_col)
        for (t0, target, d) in self.tr.get(eid, {}).get("col", []):
            if t < t0:
                break
            c = mix(c, color(target), ease((t - t0) / max(d, 1e-3)))
        return c

    def text(self, eid, base_txt, t):
        cur = base_txt
        for (t0, txt, d) in self.tr.get(eid, {}).get("text", []):
            if t < t0:
                break
            u = ease((t - t0) / max(d, 1e-3))
            if u < 1:
                return [(cur, 1 - u), (txt, u)]
            cur = txt
        return [(cur, 1.0)]

    def typed(self, eid, t):
        """Fraction of the current code text revealed (1.0 if never typed)."""
        ev = self.tr.get(eid, {}).get("type", [])
        frac = 1.0 if not ev else 0.0
        for (t0, d, _) in ev:
            if t < t0:
                break
            frac = clamp((t - t0) / max(d, 1e-3))
        return frac

    def pulse(self, eid, t):
        p = 0.0
        for t0 in self.tr.get(eid, {}).get("pulse", []):
            if t0 <= t < t0 + 0.35:
                p = max(p, math.sin(math.pi * (t - t0) / 0.35))
        return p

    def shake(self, eid, t):
        for (t0, d) in self.tr.get(eid, {}).get("shake", []):
            if t0 <= t < t0 + d:
                u = (t - t0) / d
                return 12 * math.sin(u * math.pi * 8) * (1 - u)
        return 0.0

    @staticmethod
    def _fmt(e, v):
        n = int(round(v))
        f = e.get("format_one") if n == 1 and e.get("format_one") else e.get("format", "{n}")
        return f.replace("{n}", f"{n:,}")


# ---------------------------------------------------------------- render
def transform(scene, e, t):
    """Return (alpha, scale, dx, dy) for an element at time t."""
    v, last, prog = scene.vis(e["id"], t)
    if v <= 0.004:
        return 0.0, 1, 0, 0
    s, dx, dy = 1.0, 0.0, 0.0
    if last:
        anim, target = last
        if target > 0 and prog < 1:
            if anim == "pop":
                s = 0.55 + 0.45 * ease_back(prog)
            elif anim == "slide_up":
                dy = 90 * (1 - ease_out(prog))
            elif anim == "slide_down":
                dy = -90 * (1 - ease_out(prog))
            elif anim == "slide_left":
                dx = 160 * (1 - ease_out(prog))
            elif anim == "slide_right":
                dx = -160 * (1 - ease_out(prog))
        elif target == 0 and prog < 1:
            s = 1 - 0.06 * ease(prog)
    s *= 1 + 0.06 * scene.pulse(e["id"], t)
    dx += scene.shake(e["id"], t)
    return v, s, dx, dy


def draw_element(c: Ctx, scene: Scene, e, t, a, s, dx, dy):
    typ = e["type"]
    x, y = e.get("x", 0), e.get("y", 0)
    c.set((x, y), s, dx, dy, a)
    if typ == "window":
        w, h = e["w"], e["h"]
        x0, y0, x1, y1 = x - w / 2, y - h / 2, x + w / 2, y + h / 2
        c.rrect(x0, y0, x1, y1, 26, fill=PALETTE["panel"])
        border = scene.col(e["id"], e.get("border", "panel"), t)
        if border != PALETTE["panel"]:
            c.rrect(x0, y0, x1, y1, 26, outline=border, width=3)
        hh = e.get("header_h", 92)
        for i, k in enumerate(("mac_red", "mac_yellow", "mac_green")):
            c.ellipse(x0 + 38 + i * 30, y0 + hh / 2, 9, fill=PALETTE[k])
        c.line([(x0 + 28, y0 + hh), (x1 - 28, y0 + hh)], PALETTE["header_line"], 2)
        title = e.get("title", "")
        icon = e.get("icon")
        tsz = e.get("title_size", 46)
        tw = text_width(title, "marker", tsz)
        tx = x - tw / 2 + (32 if icon else 0)
        if icon:
            draw_icon(c, icon, tx - 46, y0 + hh / 2, 56, PALETTE["white"], 3.2)
        for txt, ta in scene.text(e["id"] + ":title", title, t):
            c.text((tx, y0 + hh / 2 + 2), txt, "marker", tsz, PALETTE["white"], "lm", a=ta, upper=True)
        if e.get("tag"):
            sc = scene.col(e["id"] + ":status", e.get("status", "cyan"), t)
            c.text((x1 - 92, y0 + hh / 2), e["tag"], "marker", 30, PALETTE["grey"], "rm", upper=True)
            for i in range(2):
                c.ellipse(x1 - 66 + i * 24, y0 + hh / 2, 8, fill=sc)
        for txt, ta in scene.text(e["id"], e.get("body", ""), t):
            if txt:
                c.text((x, y0 + hh + (h - hh) / 2), txt, e.get("body_font", "mono"), e.get("body_size", 44),
                       PALETTE["white"], "mm", "Medium", hl=color(e.get("hl", "purple")), a=ta)
    elif typ == "code":
        w, h = e["w"], e["h"]
        x0, y0, x1, y1 = x - w / 2, y - h / 2, x + w / 2, y + h / 2
        bc = scene.col(e["id"], e.get("border", "purple"), t)
        c.rrect(x0, y0, x1, y1, 20, fill=(20, 19, 28), outline=bc, width=3)
        for i, k in enumerate(("mac_red", "mac_yellow", "mac_green")):
            c.ellipse(x0 + 34 + i * 26, y0 + 34, 8, fill=PALETTE[k])
        if e.get("title"):
            c.text((x1 - 30, y0 + 34), e["title"], "sans", 30, PALETTE["grey"], "rm", "SemiBold", upper=True)
        frac = scene.typed(e["id"], t)
        hl = scene.col(e["id"] + ":hl", e.get("hl", "purple"), t)
        for lines, la in scene.text(e["id"], e.get("lines", []), t):
            total = sum(len(strip_markup(L)) for L in lines) or 1
            budget = int(round(frac * total))
            for i, L in enumerate(lines):
                plain = strip_markup(L)
                if budget <= 0:
                    break
                shown = L if budget >= len(plain) else _cut_markup(L, budget)
                ly = y0 + 70 + 18 + i * e["_lh"] + e["_lh"] / 2
                wd = c.text((x0 + 40, ly), shown, "mono", e["size"], PALETTE["white"], "lm", "Medium", hl=hl, a=la)
                if budget < len(plain) and frac < 1:
                    c.rrect(x0 + 44 + wd, ly - e["size"] * 0.5, x0 + 44 + wd + e["size"] * 0.55,
                            ly + e["size"] * 0.5, 2, fill=PALETTE["purple"], a=la * 0.9)
                budget -= len(plain)
    elif typ == "bar":
        w, h = e["w"], e["h"]
        x0, y0, x1, y1 = x - w / 2, y - h / 2, x + w / 2, y + h / 2
        v = clamp(scene.val(e["id"], t, float(e.get("value", 0.1))))
        th = float(e.get("threshold", 0.7))
        bad = clamp((v - th) / 0.08 + 0.5)
        fc = mix(color(e.get("ok_color", "cyan")), color(e.get("bad_color", "bad")), bad)
        c.rrect(x0, y0, x1, y1, 12, fill=PALETTE["track"])
        if v > 0.005:
            c.rrect(x0 + 5, y0 + 5, x0 + 5 + (w - 10) * v, y1 - 5, 9, fill=mix(fc, (0, 0, 0), 0.12))
        if e.get("marker", True):
            mx = x0 + w * th
            c.line([(mx, y0 - 10), (mx, y1 + 10)], PALETTE["white"], 3)
        ls = e.get("label_size", 44)
        if e.get("label"):
            for txt, ta in scene.text(e["id"] + ":label", e["label"], t):
                c.text((x0 + 4, y0 - 14), txt, "mono", ls, PALETTE["white"], "ld", "Medium", a=ta)
        if e.get("label_right"):
            for txt, ta in scene.text(e["id"] + ":label_right", e["label_right"], t):
                c.text((x1 - 4, y0 - 14), txt, "mono", ls, fc, "rd", "Medium", a=ta)
    elif typ == "icon":
        col_ = scene.col(e["id"], e.get("color", "white"), t)
        draw_icon(c, e["kind"], x, y, e["size"], col_)
        if e.get("label"):
            for txt, ta in scene.text(e["id"] + ":label", e["label"], t):
                c.text((x, y + e["size"] / 2 + 18), txt, "sans", e.get("label_size", 44),
                       scene.col(e["id"] + ":label", e.get("label_color", "grey"), t), "ma", "ExtraBold", a=ta, upper=True)
    elif typ in ("text", "counter"):
        sz = e.get("size", 44)
        col_ = scene.col(e["id"], e.get("color", "white"), t)
        anc = {"left": "lm", "right": "rm"}.get(e.get("align"), "mm")
        kind = e.get("font", "sans")
        if typ == "counter":
            items = [(Scene._fmt(e, scene.val(e["id"], t, float(e.get("value", 0)))), 1.0)]
        else:
            items = scene.text(e["id"], e.get("text", ""), t)
        for txt, ta in items:
            c.text((x, y), txt, kind, sz, col_, anc, e.get("weight", "ExtraBold"),
                   hl=color(e.get("hl", "yellow")), a=ta, upper=e.get("upper", True))
    elif typ == "line":
        pts = [scene.anchor(e["from"]), scene.anchor(e["to"])]
        c.set((0, 0), 1, 0, 0, a)
        v, last, prog = scene.vis(e["id"], t)
        if last and last[0] == "draw" and last[1] > 0 and prog < 1:
            u = ease_out(prog)
            pts = [pts[0], (pts[0][0] + (pts[1][0] - pts[0][0]) * u, pts[0][1] + (pts[1][1] - pts[0][1]) * u)]
            c.a = 1.0
        col_ = scene.col(e["id"], e.get("color", "line"), t)
        c.line(pts, col_, e.get("width", 3), dash=e.get("dash"))
        if e.get("arrow"):
            (ax, ay), (bx, by) = pts
            ang = math.atan2(by - ay, bx - ax)
            for da in (2.6, -2.6):
                c.line([(bx, by), (bx + 16 * math.cos(ang + da), by + 16 * math.sin(ang + da))], col_, e.get("width", 3))
    elif typ == "badge":
        kind = e.get("kind", "stamp")
        bc = color(e.get("color", "red" if kind != "check" else "cyan"))
        if kind == "stamp":
            w, h = e["w"], e["h"]
            c.rrect(x - w / 2, y - h / 2, x + w / 2, y + h / 2, 12, fill=mix(BG, bc, 0.18), outline=bc, width=4)
            c.text((x, y + 2), e.get("text", "DENIED"), "sans", e.get("size", 44), bc, "mm", "ExtraBold", upper=True)
        else:
            r = e.get("r", 44)
            c.ellipse(x, y, r, fill=mix(BG, bc, 0.2), outline=bc, width=5)
            if kind == "x":
                k = r * 0.42
                c.line([(x - k, y - k), (x + k, y + k)], bc, 7)
                c.line([(x - k, y + k), (x + k, y - k)], bc, 7)
            else:
                c.line([(x - r * 0.45, y + r * 0.02), (x - r * 0.12, y + r * 0.35), (x + r * 0.48, y - r * 0.33)], bc, 7)
            if e.get("label"):
                c.text((x, y + r + 16), e["label"], "sans", e.get("label_size", 44), bc, "ma", "ExtraBold", upper=True)


def _cut_markup(L, n):
    out, k = [], 0
    for p, h in parse_markup(L):
        if k >= n:
            break
        take = p[:n - k]
        out.append("{{" + take + "}}" if h and take else take)
        k += len(take)
    return "".join(out)


def draw_dots(c: Ctx, scene: Scene, t, fe):
    c.set((0, 0), 1, 0, 0, fe)
    for dt in scene.dots:
        u = (t - dt["t0"]) / dt["dur"]
        if u < 0 or u > 1.12:
            continue
        a = clamp(u / 0.08) * (1 - clamp((u - 1) / 0.12))
        uu = ease_out(min(u, 1.0)) * 0.15 + min(u, 1.0) * 0.85
        px, py = base.polyline_point(dt["pts"], uu)
        col_ = color(dt["col"])
        r = dt["r"]
        for k in range(1, 4):   # short trail
            tu = max(0.0, min(u, 1) - k * 0.035)
            qx, qy = base.polyline_point(dt["pts"], ease_out(tu) * 0.15 + tu * 0.85)
            c.ellipse(qx, qy, r * (1 - k * 0.2), fill=col_, a=a * (0.5 - k * 0.13))
        c.ellipse(px, py, r * 1.9, fill=col_, a=a * 0.22)
        c.ellipse(px, py, r, fill=col_, a=a)
        if dt.get("label"):
            c.text((px + r + 10, py), dt["label"], "mono", 30, col_, "lm", "Medium", a=a)


def draw_chapter(c: Ctx, scene: Scene, t, fe):
    chs = scene.chapters
    if not chs:
        return
    cur = 0
    for i, ch in enumerate(chs):
        if ch["t"] <= t:
            cur = i
    ch = chs[cur]
    u = clamp((t - ch["t"]) / 0.35) if ch["t"] > 0 else 1.0
    items = [(ch, u, False)]
    if u < 1 and cur > 0:
        items.append((chs[cur - 1], 1 - clamp((t - ch["t"]) / 0.18), True))
    for ch_, a, leaving in items:
        lines = ch_["text"].split("\n")
        size = ch_["size"]
        widest = max(text_width(L.upper(), "marker", size) for L in lines)
        if widest > 980:
            size = size * 980 / widest
        y0 = scene.spec.get("chapter_y", 236)
        s = 1.0 if leaving else 0.82 + 0.18 * ease_back(a)
        dy = -20 * (1 - a) if leaving else 0
        c.set((W / 2, y0 + size * 0.6), s, 0, dy, a * fe)
        for i, L in enumerate(lines):
            c.text((W / 2, y0 + i * size * 1.12), L, "marker", size, PALETTE["white"], "ma", hl=ch_["hl"], upper=True)


def render_frame(scene: Scene, t: float, show_captions=True):
    img = Image.new("RGB", (W * SS, H * SS), BG)
    c = Ctx(ImageDraw.Draw(img))
    fe = 1 - ease((t - scene.end_start) / 0.25) if t >= scene.end_start else 1.0
    if fe > 0.01:
        lines = [e for e in scene.el.values() if e["type"] == "line"]
        others = [scene.el[i] for i in scene.order if scene.el[i]["type"] != "line"]
        for e in lines:
            a, s, dx, dy = transform(scene, e, t)
            if a > 0.01:
                draw_element(c, scene, e, t, a * fe, s, dx, dy)
        draw_dots(c, scene, t, fe)
        for e in others:
            a, s, dx, dy = transform(scene, e, t)
            if a > 0.01:
                draw_element(c, scene, e, t, a * fe, s, dx, dy)
        draw_chapter(c, scene, t, fe)
    c.set((0, 0), 1, 0, 0, 1)
    wm = scene.spec.get("watermark", "@k4coding")
    if wm:
        c.text((W - 44, SAFE_BOTTOM - 4), wm, "sans", 28, (105, 105, 112), "rd", "SemiBold")
    if show_captions and scene.captions and t < scene.end_start:
        kwc = color(scene.spec.get("captions", {}).get("keyword_color", "yellow"))
        for cap in scene.captions:
            if cap["start"] <= t < cap["end"]:
                f = font("sans", 40 * SS, "SemiBold")
                line = " ".join(w for _, w, _ in cap["words"])
                x = W / 2 - f.getlength(line) / SS / 2
                y = SAFE_BOTTOM - 96
                ca = clamp((t - cap["start"]) / 0.12) * clamp((cap["end"] - t) / 0.12)
                for (ws, w, kw) in cap["words"]:
                    col_ = (kwc if kw else PALETTE["white"]) if t >= ws else (100, 100, 108)
                    c.d.text((x * SS, y * SS), w, font=f, fill=blend(col_, ca), anchor="lm")
                    x += f.getlength(w + " ") / SS
                break
    if t >= scene.end_start:
        ea = ease((t - scene.end_start - 0.1) / 0.3)
        if ea > 0.01:
            end = scene.spec.get("end_card", {})
            c.set((W / 2, 860), 0.85 + 0.15 * ease_back(clamp((t - scene.end_start - 0.1) / 0.35)), 0, 0, ea)
            draw_icon(c, "user", W / 2, 700, 150, PALETTE["white"])
            c.ellipse(W / 2 + 70, 640, 30, fill=PALETTE["purple"])
            c.line([(W / 2 + 56, 640), (W / 2 + 84, 640)], PALETTE["white"], 6)
            c.line([(W / 2 + 70, 626), (W / 2 + 70, 654)], PALETTE["white"], 6)
            c.text((W / 2, 860), end.get("line1", "FOLLOW"), "marker", 110, PALETTE["white"], "mm")
            c.text((W / 2, 990), end.get("line2", "{{@K4CODING}}"), "marker", 104, PALETTE["white"], "mm",
                   hl=PALETTE["purple"])
            sub = end.get("line3", "one concept, one diagram, daily")
            if sub:
                c.text((W / 2, 1100), sub, "sans", 40, PALETTE["grey"], "mm", "SemiBold")
    return img.resize((W, H), Image.LANCZOS)


# ------------------------------------------------------------------ SFX
def read_wav_mono(p: Path):
    with wave.open(str(p)) as w:
        sr, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
        x = np.frombuffer(w.readframes(n), dtype="<i2").astype(np.float32) / 32768
    if ch > 1:
        x = x.reshape(-1, ch).mean(1)
    return x, sr


def mix_voice_sfx(speech: Path, scene: Scene, total: float, out: Path, sfx_db: float):
    """Voice + quiet SFX track -> one WAV handed to add_voiceover.py as --speech-file."""
    vw = out.with_name("voice48k.wav")
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(speech),
                    "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(vw)], check=True)
    voice, sr = read_wav_mono(vw)
    n = int(total * sr) + sr
    track = np.zeros(n, dtype=np.float32)
    cache = {}
    for (t, name, g) in scene.sfx:
        if t < 0 or t >= scene.end_start + 0.6:
            continue
        if name not in cache:
            p = SFX_DIR / f"{name}.wav"
            if not p.is_file():
                raise SystemExit(f"missing SFX {p}; run tools/sfx/generate_motion_sfx.py")
            cache[name] = read_wav_mono(p)[0]
        s = cache[name]
        i = int(t * sr)
        j = min(n, i + len(s))
        track[i:j] += s[:j - i] * g
    vpk = float(np.percentile(np.abs(voice), 99.5)) or 0.3
    track *= vpk * 10 ** (sfx_db / 20) / 0.7
    mixed = track.copy()
    mixed[:len(voice)] += voice[:n]
    mixed = mixed[:int(total * sr)]          # drop edge-tts trailing silence
    fade = min(len(mixed), int(0.08 * sr))
    mixed[-fade:] *= np.linspace(1, 0, fade)
    mixed = np.clip(mixed, -1, 1)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((mixed * 32767).astype("<i2").tobytes())
    return out


# ------------------------------------------------------------------ lint
def lint(spec, scene: Scene, total):
    warn = []
    segs = spec["voiceover"]
    words = " ".join(s["text"] for s in segs).split()
    if not 60 <= len(words) <= 90:
        warn.append(f"voiceover is {len(words)} words (target 60-90)")
    ids = [s["id"] for s in segs]
    for need in ("hook", "bug", "why", "fix", "follow"):
        if need not in ids:
            warn.append(f"voiceover has no '{need}' segment")
    if segs and "follow k four coding" not in segs[-1]["text"].lower():
        warn.append("last segment should be 'Follow K four coding.'")
    if not 25 <= total <= 40:
        warn.append(f"duration {total:.1f}s (target 25-40s, aim ~30)")
    if total - scene.end_start > 1.6:
        warn.append(f"end card is {total - scene.end_start:.2f}s (target <= 1.5s)")
    for ch in scene.chapters:
        widest = max(text_width(L.upper(), "marker", ch["size"]) for L in ch["text"].split("\n"))
        eff = ch["size"] * min(1.0, 980 / widest)
        if eff < 80:
            warn.append(f"chapter '{strip_markup(ch['text'])}' renders at {eff:.0f}px (< 80); shorten it")
    if not scene.chapters or scene.chapters[0]["t"] > 0:
        warn.append("no chapter title on frame 0")
    if not any(e.get("start_visible") for e in scene.el.values()):
        warn.append("no element is start_visible: the main visual must be on frame 0")
    for e in scene.el.values():
        t = e["type"]
        for k in ("size", "label_size", "body_size"):
            if k in e and t in ("text", "counter", "code", "icon", "bar", "badge", "window") and e[k] < 44:
                warn.append(f"{e['id']}: {k} {e[k]} < 44")
        x0, y0, x1, y1 = scene.bbox(e)
        if y0 < SAFE_TOP + 130 or y1 > SAFE_BOTTOM - 130 or x0 < 24 or x1 > W - 24:
            warn.append(f"{e['id']}: bbox ({x0:.0f},{y0:.0f})-({x1:.0f},{y1:.0f}) leaves the canvas band "
                        f"y {SAFE_TOP + 130}-{SAFE_BOTTOM - 130}")
        if t == "code":
            sets = [e.get("lines", [])] + [x[1] for x in scene.tr.get(e["id"], {}).get("text", [])]
            for ls in sets:
                for L in ls:
                    if 40 + text_width(strip_markup(L), "mono", e["size"], "Medium") > e["w"] - 30:
                        warn.append(f"{e['id']}: code line too wide: '{strip_markup(L)}'")
                if 70 + 36 + len(ls) * e["_lh"] > e["h"] + 1:
                    warn.append(f"{e['id']}: {len(ls)} lines overflow the window (set h or min_lines)")
        if t == "window" and e.get("body"):
            for b in [e["body"]] + [x[1] for x in scene.tr.get(e["id"], {}).get("text", [])]:
                if text_width(strip_markup(b), e.get("body_font", "mono"), e.get("body_size", 44), "Medium") > e["w"] - 60:
                    warn.append(f"{e['id']}: body '{strip_markup(b)}' wider than window")
    iv = sorted(scene.events + [(d["t0"], d["dur"]) for d in scene.dots])
    iv = [(a, a + d) for a, d in iv if a < scene.end_start]
    first = min([a for a, _ in iv if a >= 0] or [99])
    if first > 0.3:
        warn.append(f"first animation at {first:.2f}s (rule: by 0.3s)")
    reach = 0.0
    for a, b in [x for x in iv if x[0] >= 0] + [(scene.end_start, scene.end_start)]:
        if a - reach > 2.0:
            warn.append(f"nothing new between {reach:.1f}s and {a:.1f}s (aim: every 1-2s)")
        reach = max(reach, min(b, a + 1.0))
    return warn


# ------------------------------------------------------------- variants
def apply_variant(spec, name):
    if not name:
        return spec
    v = spec.get("variants", {}).get(name)
    if v is None:
        raise SystemExit(f"spec has no variant '{name}' (have: {', '.join(spec.get('variants', {})) or 'none'})")
    spec = copy.deepcopy(spec)
    for ch in spec.get("chapters", []):
        if ch.get("id") in v.get("chapters", {}):
            o = v["chapters"][ch["id"]]
            ch.update(o if isinstance(o, dict) else {"text": o})
    for k, val in v.items():
        if k != "chapters":
            spec[k] = val
    return spec


# ------------------------------------------------------------------ main
_SCENE = None


def _init(spec, seg, total):
    global _SCENE
    _SCENE = Scene(spec, seg, total)


def _render_idx(i):
    return render_frame(_SCENE, i / FPS).tobytes()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--cover", type=Path, help="also write a cover JPG (frame at cover_at, no captions)")
    ap.add_argument("--variant", help="apply spec.variants.NAME (e.g. facebook: different chapter titles)")
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
    args = ap.parse_args(argv)
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise SystemExit(f"{tool} is required")

    spec = apply_variant(base.load_spec(args.spec), args.variant)
    if args.no_captions:
        spec.setdefault("captions", {})["enabled"] = False
    vo = spec.get("voice", {})
    voice = args.voice or vo.get("name", base.DEFAULT_VOICE)
    rate = args.rate or vo.get("rate", base.DEFAULT_RATE)
    pitch = args.pitch or vo.get("pitch", base.DEFAULT_PITCH)
    segs = spec["voiceover"]
    script = " ".join(s["text"].strip() for s in segs)
    out = args.output.expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="motion_reel_") as td:
        tdir = Path(td)
        mp3, words, engine, speech_dur = base.synthesize(script, voice, rate, pitch, tdir)
        print(f"Speech: {speech_dur:.2f}s via {engine}, {len(words)} word timings", file=sys.stderr)
        seg = base.map_segments(segs, words, speech_dur)
        for s in segs:
            print(f"  segment {s['id']:<8} {seg[s['id']]['start']:6.2f} -> {seg[s['id']]['end']:6.2f}s", file=sys.stderr)
        total = round(min(speech_dur, max(v["end"] for v in seg.values())) + float(spec.get("tail", 0.35)), 3)
        scene = Scene(spec, seg, total)
        warns = lint(spec, scene, total)
        for w in warns:
            print("lint:", w, file=sys.stderr)
        print(f"Total {total:.2f}s, end card {total - scene.end_start:.2f}s, {len(scene.sfx)} SFX hits", file=sys.stderr)
        if warns and args.strict:
            raise SystemExit("lint failed (--strict)")
        if args.lint_only:
            return 0
        if args.preview:
            for ts in args.preview.split(","):
                p = out.with_name(f"{out.stem}-t{float(ts):05.2f}.png")
                render_frame(scene, float(ts)).save(p)
                print(f"preview {p}", file=sys.stderr)
            return 0
        if args.cover:
            cat = spec.get("cover_at")
            ct = scene.at(cat, 0) if cat is not None else min(scene.end_start - 0.5, 6.0)
            render_frame(scene, ct, show_captions=False).save(args.cover, quality=92)
            print(f"Cover: {args.cover} (t={ct:.2f}s)", file=sys.stderr)

        n_frames = int(math.ceil(total * FPS))
        silent = tdir / "silent.mp4"
        ff = subprocess.Popen([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-profile:v", "high", "-level", "4.1", "-movflags", "+faststart", str(silent)], stdin=subprocess.PIPE)
        with Pool(args.workers, initializer=_init, initargs=(spec, seg, total)) as pool:
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
            speech = mix_voice_sfx(speech, scene, total, tdir / "voice_sfx.wav", sfx_db)
        py = str(base.VENV_PY) if base.VENV_PY.exists() else sys.executable
        cmd = [py, str(ADD_VO), "-i", str(silent), "-o", str(out), "--speech-file", str(speech),
               "-t", script, "--voice", voice, f"--rate={rate}", f"--pitch={pitch}"]
        if args.no_music:
            cmd.append("--no-music")
        else:
            cmd += ["--music", str(args.music)]
        if subprocess.run(cmd).returncode != 0:
            raise SystemExit("add_voiceover.py failed")
    print(f"Done: {out} ({base.probe_duration(out):.2f}s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
