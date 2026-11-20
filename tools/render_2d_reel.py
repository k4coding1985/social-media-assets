#!/usr/bin/env python3
"""K4Coding 2D explainer Reel renderer (spec-driven).

Flat 2D motion graphics (PIL + ffmpeg) with built-in flat vector illustrations
(NO photos: specs with a photo/image are rejected), Chatterbox voice
(ref_am_michael), voice only. See tools/TWO_D_REEL_TEMPLATE.md.

  CB=/workspace/ingress/work/tts2/cbvenv/bin/python
  $CB tools/render_2d_reel.py spec.json --out-dir OUT                 # Instagram variant
  $CB tools/render_2d_reel.py spec.json --out-dir OUT --variant facebook
  $CB tools/render_2d_reel.py spec.json --out-dir OUT --preview        # + PNG frames
  $CB tools/render_2d_reel.py spec.json --out-dir OUT --preview-only --fake-tts  # layout check, no TTS
"""
import argparse, copy, fcntl, hashlib, json, math, os, re, subprocess, sys, time
from multiprocessing import Pool
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flat_illustrations as FLAT

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, 'fonts')
BADGE_PATH = os.path.join(HERE, 'assets', 'k4-badge.png')
REF_VOICE = '/workspace/ingress/work/tts2/ref_am_michael.wav'
LOCK = '/workspace/content-production-heavy.lock'
W, H, FPS, SR = 1080, 1920, 30, 24000
WHITE = (255, 255, 255); INK = (20, 30, 45); AMBER = (255, 200, 87); RED = (230, 57, 70)
GREEN = (61, 220, 151); CYAN = (80, 200, 255)
PALETTE = ['#1F3A5F', '#0E4D64', '#4A2C6B', '#17408B', '#7A2E4D', '#1E6F5C', '#3D4F7C', '#2F4858']
BANNED = re.compile(r'illustrat', re.I)   # banned in ON-SCREEN text (the spec key "illustration" is fine)
IMG_EXT = re.compile(r'\.(jpe?g|png|webp|gif|bmp|tiff?|heic|avif)\b', re.I)
PHOTO_KEYS = {'photo', 'photos', 'image', 'images', 'img', 'picture', 'background_image', 'bg_image'}
def lint_no_photos(obj, where='spec'):
    """Fail if the spec references any photo / raster image. 2D Reels use flat illustrations only."""
    errs = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() in PHOTO_KEYS: errs.append(f'{where}.{k}: photos/images are not allowed (use "illustration")')
            errs += lint_no_photos(v, f'{where}.{k}')
    elif isinstance(obj, list):
        for i, v in enumerate(obj): errs += lint_no_photos(v, f'{where}[{i}]')
    elif isinstance(obj, str) and IMG_EXT.search(obj): errs.append(f'{where}: image file reference {obj!r} not allowed')
    return errs

def F(w, s): return ImageFont.truetype(os.path.join(FONTS, f'Poppins-{w}.ttf'), int(s))
def MONO(s):
    f = ImageFont.truetype(os.path.join(FONTS, 'JetBrainsMono-Variable.ttf'), int(s))
    try: f.set_variation_by_name('Bold')
    except Exception: pass
    return f
def hexrgb(h): h = h.lstrip('#'); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
def clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def eo3(x): x = clamp(x); return 1 - (1 - x) ** 3
def eio(x): x = clamp(x); return 3 * x * x - 2 * x ** 3
def back(x, s=1.70158): x = clamp(x); return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2

# ---------------------------------------------------------------- drawing helpers
def rr_mask(size, r):
    m = Image.new('L', size, 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], r, fill=255); return m
def text_layer(txt, font, fill, pad=6, stroke=0, stroke_fill=None):
    b = ImageDraw.Draw(Image.new('RGBA', (1, 1))).textbbox((0, 0), txt, font=font, stroke_width=stroke)
    im = Image.new('RGBA', (max(1, b[2] - b[0] + 2 * pad), max(1, b[3] - b[1] + 2 * pad)), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((pad - b[0], pad - b[1]), txt, font=font, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
    return im
def word_layer(txt, font, fill, stroke=0, stroke_fill=None):
    asc, desc = font.getmetrics(); w = int(ImageDraw.Draw(Image.new('RGBA', (1, 1))).textlength(txt, font=font)) + 2 * stroke + 2
    im = Image.new('RGBA', (w, asc + desc + 2 * stroke), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((stroke, stroke), txt, font=font, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill); return im
def wrap(txt, font, maxw):
    d = ImageDraw.Draw(Image.new('RGBA', (1, 1))); lines = []; cur = ''
    for w in txt.split():
        t = (cur + ' ' + w).strip()
        if d.textlength(t, font=font) <= maxw or not cur: cur = t
        else: lines.append(cur); cur = w
    lines.append(cur); return lines
def multiline(txt, font, fill, maxw, lh=1.12, align='left', stroke=0, stroke_fill=None):
    ls = wrap(txt, font, maxw); layers = [text_layer(l, font, fill, stroke=stroke, stroke_fill=stroke_fill) for l in ls]
    w = max(l.width for l in layers); step = int(font.size * lh); h = step * (len(ls) - 1) + layers[-1].height
    im = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    for i, l in enumerate(layers): im.alpha_composite(l, ((w - l.width) // 2 if align == 'center' else 0, step * i))
    return im
def fit_font(txt, weight, start, maxw, maxlines, minsize=40):
    s = start
    while s > minsize:
        f = F(weight, s)
        if len(wrap(txt, f, maxw)) <= maxlines and all(ImageDraw.Draw(Image.new('RGBA', (1, 1))).textlength(l, font=f) <= maxw for l in wrap(txt, f, maxw)): return f
        s -= 4
    return F(weight, minsize)
def pill(txt, font, fg, bg, padx=28, pady=12):
    t = text_layer(txt, font, fg, pad=0); w = t.width + 2 * padx; h = t.height + 2 * pady + 6
    im = Image.new('RGBA', (w, h), (0, 0, 0, 0)); ImageDraw.Draw(im).rounded_rectangle([0, 0, w - 1, h - 1], h // 2, fill=bg)
    im.alpha_composite(t, (padx, (h - t.height) // 2)); return im
def paste_t(canvas, img, cx, cy, scale=1.0, angle=0.0, alpha=1.0):
    if alpha <= 0.005 or scale <= 0.01: return
    if abs(scale - 1) > 0.003: img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.BILINEAR)
    if abs(angle) > 0.05: img = img.rotate(angle, resample=Image.BICUBIC, expand=True)
    if alpha < 0.995:
        img = img.copy(); img.putalpha(img.getchannel('A').point(lambda v: int(v * alpha)))
    x, y = int(cx - img.width / 2), int(cy - img.height / 2)
    x0, y0 = max(0, x), max(0, y); x1, y1 = min(canvas.width, x + img.width), min(canvas.height, y + img.height)
    if x1 > x0 and y1 > y0: canvas.alpha_composite(img.crop((x0 - x, y0 - y, x1 - x, y1 - y)), (x0, y0))
def shadow_for(size, r=26, blur=18, alpha=120):
    pad = blur * 3; s = Image.new('RGBA', (size[0] + 2 * pad, size[1] + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(s).rounded_rectangle([pad, pad, pad + size[0], pad + size[1]], r, fill=(0, 0, 0, alpha))
    return s.filter(ImageFilter.GaussianBlur(blur))

# ---------------------------------------------------------------- flat icons
def icon(key, col, S=150):
    s = S * 4; im = Image.new('RGBA', (s, s), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.ellipse([0, 0, s - 1, s - 1], fill=col + (255,)); d.ellipse([s * .04, s * .04, s * .96, s * .96], outline=WHITE + (255,), width=int(s * .035))
    w = WHITE + (255,); u = s / 100; c = col + (255,)
    R = lambda a, b, cc, dd, fill=w, r=0: d.rounded_rectangle([a * u, b * u, cc * u, dd * u], r * u, fill=fill)
    E = lambda a, b, cc, dd, fill=w: d.ellipse([a * u, b * u, cc * u, dd * u], fill=fill)
    L = lambda pts, wd, fill=w: d.line([(x * u, y * u) for x, y in pts], fill=fill, width=int(wd * u), joint='curve')
    P = lambda pts, fill=w: d.polygon([(x * u, y * u) for x, y in pts], fill=fill)
    if key == 'database':
        for y in (62, 46, 30):
            R(28, y, 72, y + 14, fill=w); E(28, y + 6, 72, y + 22, fill=w); E(28, y - 8, 72, y + 8, fill=w if y != 30 else w)
            if y != 30: E(28, y - 8, 72, y + 8, fill=w); L([(28, y), (72, y)], 0)
        E(30, 22, 70, 36, fill=c); E(33, 24, 67, 34, fill=w)
        for y in (46, 62): d.arc([28 * u, (y - 8) * u, 72 * u, (y + 8) * u], 0, 180, fill=c, width=int(3 * u))
    elif key == 'server':
        for y in (24, 44, 64): R(24, y, 76, y + 14, r=3); E(64, y + 4, 70, y + 10, fill=c); R(30, y + 5, 52, y + 9, fill=c)
    elif key == 'code':
        L([(40, 32), (24, 50), (40, 68)], 8); L([(60, 32), (76, 50), (60, 68)], 8); L([(55, 26), (45, 74)], 7)
    elif key == 'bug':
        E(34, 34, 66, 78); E(40, 22, 60, 40); L([(50, 44), (50, 76)], 3, fill=c)
        for y in (46, 58, 70): L([(34, y), (20, y - 4)], 5); L([(66, y), (80, y - 4)], 5)
    elif key == 'check':
        L([(26, 52), (43, 68), (75, 34)], 11)
    elif key == 'cross':
        L([(30, 30), (70, 70)], 11); L([(70, 30), (30, 70)], 11)
    elif key == 'question':
        d.text((50 * u, 52 * u), '?', font=F('Black', 70 * u), fill=w, anchor='mm')
    elif key == 'warning':
        P([(50, 18), (84, 78), (16, 78)]); R(46, 36, 54, 60, fill=c, r=3); E(45, 64, 55, 74, fill=c)
    elif key == 'follow':
        E(30, 20, 58, 48); d.pieslice([18 * u, 50 * u, 70 * u, 100 * u], 180, 360, fill=w); R(70, 36, 76, 60); R(61, 45, 85, 51)
    elif key == 'clock':
        E(20, 20, 80, 80); L([(50, 50), (50, 30)], 6, fill=c); L([(50, 50), (64, 58)], 6, fill=c)
    elif key == 'lock':
        d.arc([32 * u, 18 * u, 68 * u, 58 * u], 180, 360, fill=w, width=int(8 * u)); R(28, 40, 72, 80, r=6); E(45, 52, 55, 62, fill=c); R(48, 58, 52, 70, fill=c)
    elif key == 'git':
        L([(34, 26), (34, 74)], 7); L([(34, 40), (64, 54)], 7); E(26, 18, 42, 34); E(26, 66, 42, 82); E(56, 46, 72, 62)
    else:
        d.text((50 * u, 52 * u), (key or '?')[:2].upper(), font=F('Black', 40 * u), fill=w, anchor='mm')
    return im.resize((S, S), Image.LANCZOS)

def cross_mark(S, col=RED):
    im = Image.new('RGBA', (S * 4, S * 4), (0, 0, 0, 0)); d = ImageDraw.Draw(im); d.ellipse([0, 0, S * 4 - 1, S * 4 - 1], fill=col + (255,))
    d.line([(S * 1.2, S * 1.2), (S * 2.8, S * 2.8)], fill=WHITE, width=int(S * .55)); d.line([(S * 2.8, S * 1.2), (S * 1.2, S * 2.8)], fill=WHITE, width=int(S * .55))
    return im.resize((S, S), Image.LANCZOS)
def check_mark(S, col=GREEN):
    im = Image.new('RGBA', (S * 4, S * 4), (0, 0, 0, 0)); d = ImageDraw.Draw(im); d.ellipse([0, 0, S * 4 - 1, S * 4 - 1], fill=col + (255,))
    d.line([(S * 1.0, S * 2.1), (S * 1.7, S * 2.8), (S * 3.0, S * 1.3)], fill=WHITE, width=int(S * .5), joint='curve')
    return im.resize((S, S), Image.LANCZOS)

# ---------------------------------------------------------------- TTS
def sha(s): return hashlib.sha1(s.encode()).hexdigest()[:16]
class Voice:
    def __init__(self, cfg, cache):
        self.cfg = cfg; self.cache = cache; self.m = None; os.makedirs(cache, exist_ok=True)
    def path(self, text, seed):
        c = self.cfg; return os.path.join(self.cache, sha(f"{text}|{c.get('ref', REF_VOICE)}|{c.get('exaggeration', .45)}|{c.get('cfg_weight', .4)}|{seed}") + '.wav')
    def get(self, text, seed, fake=False):
        import soundfile as sf
        p = self.path(text, seed)
        if fake:
            n = int(SR * (0.35 + len(text.split()) / 2.7)); return np.zeros(n, np.float32) + 1e-4
        if not os.path.exists(p):
            if self.m is None:
                import torch; torch.set_num_threads(int(os.environ.get('CB_THREADS', '6')))
                from chatterbox.tts import ChatterboxTTS
                t0 = time.time(); self.m = ChatterboxTTS.from_pretrained(device='cpu'); log(f'chatterbox loaded {time.time() - t0:.0f}s')
            import torch; torch.manual_seed(seed); t0 = time.time()
            w = self.m.generate(text, audio_prompt_path=self.cfg.get('ref', REF_VOICE), exaggeration=self.cfg.get('exaggeration', .45), cfg_weight=self.cfg.get('cfg_weight', .4))
            w = w.squeeze().numpy(); sf.write(p, w, self.m.sr)
            log(f'tts {len(w) / self.m.sr:.1f}s audio in {time.time() - t0:.0f}s: {text[:50]}')
        w, sr = sf.read(p, dtype='float32')
        if w.ndim > 1: w = w.mean(1)
        assert sr == SR, sr
        idx = np.where(np.abs(w) > 0.01)[0]
        if len(idx): w = w[max(0, idx[0] - int(.03 * SR)): idx[-1] + int(.08 * SR)]
        return w

def log(*a): print('[2d]', *a, flush=True)

# ---------------------------------------------------------------- spec
def load_spec(path, variant):
    spec = json.load(open(path)); base = os.path.dirname(os.path.abspath(path))
    if variant and variant != 'instagram':
        ov = spec.get('variants', {}).get(variant)
        if ov is None: sys.exit(f'spec has no variants.{variant}')
        ov = copy.deepcopy(ov); sc_ov = ov.pop('scenes', {})
        spec.update(ov)
        for s in spec['scenes']:
            if s['id'] in sc_ov:
                o = sc_ov[s['id']]
                if 'voice' in o and 'caption' not in o: s.pop('caption', None)   # caption must follow the new voice line
                s.update(o)
    errs = lint_no_photos(spec)
    if errs: sys.exit('NO-PHOTO lint failed:\n  ' + '\n  '.join(errs))
    spec['_base'] = base
    for k in ('title', 'hook', 'series', 'question'):
        if k in spec and BANNED.search(str(spec[k])): sys.exit(f'banned word in {k}')
    for s in spec['scenes']:
        for k in ('headline', 'sub', 'caption', 'question'):
            if BANNED.search(str(s.get(k, ''))): sys.exit(f'banned word "illustrative" on screen in scene {s["id"]}.{k}')
        for t in s.get('tags', []):
            if BANNED.search(t): sys.exit('banned word in tag')
        ill = s.get('illustration')
        if ill is not None:
            typ = ill if isinstance(ill, str) else ill.get('type')
            if typ not in FLAT.TYPES: sys.exit(f'scene {s["id"]}: unknown illustration {typ!r}; use one of {FLAT.TYPES}')
            for c in ([] if isinstance(ill, str) else ill.get('chips', [])):
                if BANNED.search(c if isinstance(c, str) else c.get('text', '')): sys.exit('banned word in chip')
    return spec

def build_timeline(spec, voice, fake):
    lead = spec.get('lead', 0.15); t = lead; chunks = [np.zeros(int(lead * SR), np.float32)]; tl = []
    seed0 = spec.get('voice', {}).get('seed', 900)
    for i, s in enumerate(spec['scenes']):
        seed = s.get('seed', seed0 + i)
        w = voice.get(s['voice'], seed, fake); d = len(w) / SR; pause = s.get('pause', 0.22)
        tl.append(dict(id=s['id'], start=round(t, 3), end=round(t + d, 3), voice=s['voice'], caption=s.get('caption', s['voice'])))
        chunks += [w, np.zeros(int(pause * SR), np.float32)]; t += d + pause
    tail = spec.get('tail', 0.6); chunks.append(np.zeros(int(tail * SR), np.float32))
    a = np.concatenate(chunks); pk = np.abs(a).max()
    if pk > 0.02: a = a / pk * 0.89
    return a, tl, len(a) / SR

# ---------------------------------------------------------------- renderer
class Reel:
    def __init__(self, spec, tl, total):
        self.spec = spec; self.tl = tl; self.total = total
        self.badge = Image.open(BADGE_PATH).convert('RGBA'); bw = 250
        self.badge = self.badge.resize((bw, int(self.badge.height * bw / self.badge.width)), Image.LANCZOS)
        self.accent = hexrgb(spec.get('accent', '#FFC857'))
        self.series = pill(spec['series'].upper(), F('ExtraBold', 34), INK, self.accent + (255,), padx=26, pady=10) if spec.get('series') else None
        self.scenes = []
        n = len(spec['scenes'])
        for i, (s, L) in enumerate(zip(spec['scenes'], tl)):
            st = 0.0 if i == 0 else L['start'] - 0.06
            en = (tl[i + 1]['start'] - 0.06) if i + 1 < n else total
            self.scenes.append(dict(s=s, st=st, en=en, a=self.prep(s, i)))
        self.caps = self.prep_captions()
        self.topic_dur = clamp(spec.get('topic_card', 1.8), 1.5, 2.0)
        self.prep_topic()

    # ---- assets per scene
    def prep(self, s, i):
        a = {}; typ = s.get('type', 'scene'); typ = 'scene' if typ == 'photo' else typ
        a['bg'] = hexrgb(s.get('bg', PALETTE[i % len(PALETTE)]))
        bgim = Image.new('RGBA', (W, H), a['bg'] + (255,))
        wm = s.get('watermark', self.spec.get('watermark', ''))
        if wm:
            wl = text_layer(wm.upper(), F('Black', 360), (255, 255, 255, 16), pad=0); paste_t(bgim, wl, W / 2, 1660)
        # soft vignette at the bottom
        g = Image.new('L', (1, H)); [g.putpixel((0, y), int(70 * clamp((y - 1300) / 620))) for y in range(H)]
        bgim.alpha_composite(Image.merge('RGBA', [Image.new('L', (W, H), 0)] * 3 + [g.resize((W, H))]))
        a['bgim'] = bgim
        a['tags'] = [pill(t.upper(), F('Bold', 32), INK if j == 0 else WHITE, (self.accent + (255,)) if j == 0 else (255, 255, 255, 46), padx=24, pady=8) for j, t in enumerate(s.get('tags', []))]
        if s.get('headline'):
            f = fit_font(s['headline'], 'ExtraBold', 80 if s.get('code') else 88, W - 120, 2, 56); a['head'] = multiline(s['headline'], f, WHITE, W - 120, 1.08)
        if s.get('sub'): a['sub'] = multiline(s['sub'], F('Medium', 38), (255, 255, 255, 225), W - 120, 1.15)
        a['icon'] = icon(s.get('icon', 'code'), tuple(int(c * .8) for c in self.accent) if s.get('icon_color') is None else hexrgb(s['icon_color']), 150)
        has_code = bool(s.get('code'))
        if s.get('illustration') is not None:
            size = (940, 360) if has_code else (960, 620)
            if typ in ('question', 'end'): size = (800, 440)
            a['panel_size'] = size; a['panel_items'] = FLAT.build(s['illustration'], size[0], size[1], self.accent)
            a['panel_base'] = self.panel_base(size, a['bg']); a['panel_shadow'] = shadow_for(size, r=34, alpha=90)
        if has_code: a['code'] = self.prep_code(s['code'])
        if typ == 'question':
            q = s.get('question', self.spec.get('question', ''))
            a['q'] = multiline(q, fit_font(q, 'ExtraBold', 88, W - 140, 3, 56), WHITE, W - 140, 1.1, 'center')
            a['yes'] = pill(s.get('yes', 'YES'), F('Black', 72), INK, GREEN + (255,), padx=60, pady=18)
            a['no'] = pill(s.get('no', 'NO'), F('Black', 72), WHITE, RED + (255,), padx=70, pady=18)
            a['ask'] = text_layer(s.get('ask', 'COMMENT BELOW'), F('Bold', 40), (255, 255, 255, 230), pad=2)
        if typ == 'end':
            nxt = s.get('next_label') or (f"FOLLOW FOR #{self.spec['next']}" if self.spec.get('next') else 'FOLLOW FOR MORE')
            a['follow'] = multiline(nxt, fit_font(nxt, 'Black', 120, W - 120, 2, 70), self.accent, W - 120, 1.05, 'center')
            a['handle'] = pill(self.spec.get('handle', '@K4CODING'), F('Black', 76), INK, WHITE + (255,), padx=50, pady=18)
            a['follow_icon'] = icon('follow', RED, 120)
            a['hook_small'] = multiline(self.spec['hook'], fit_font(self.spec['hook'], 'ExtraBold', 64, W - 160, 2, 44), WHITE, W - 160, 1.08, 'center')
        return a

    def panel_base(self, size, bg):
        w, h = size; k = 3; im = Image.new('RGBA', (w * k, h * k), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        fill = tuple(int(c * 0.62 + 8) for c in bg)
        d.rounded_rectangle([0, 0, w * k - 1, h * k - 1], 34 * k, fill=fill + (255,))
        ov = Image.new('RGBA', im.size, (0, 0, 0, 0)); o = ImageDraw.Draw(ov)   # translucent decor, composited (not overwritten)
        for i in range(0, w * k, 46 * k):           # flat dot grid
            for j in range(0, h * k, 46 * k): o.ellipse([i + 20 * k, j + 20 * k, i + 25 * k, j + 25 * k], fill=(255, 255, 255, 26))
        o.ellipse([w * k * .72, -h * k * .35, w * k * 1.15, h * k * .4], fill=(255, 255, 255, 18))
        o.rounded_rectangle([0, 0, w * k - 1, h * k - 1], 34 * k, outline=(255, 255, 255, 70), width=3 * k)
        im.alpha_composite(Image.composite(ov, Image.new('RGBA', im.size, (0, 0, 0, 0)), im.getchannel('A')))
        return im.resize(size, Image.LANCZOS)

    def prep_code(self, c):
        lines = c['lines']; f = None
        for s in range(52, 28, -2):
            f = MONO(s)
            if max(ImageDraw.Draw(Image.new('RGBA', (1, 1))).textlength(l, font=f) for l in lines) <= 860: break
        lh = int(f.size * 1.55); cw = 980; ch = 96 + lh * len(lines) + 34
        card = Image.new('RGBA', (cw, ch), (0, 0, 0, 0)); d = ImageDraw.Draw(card)
        d.rounded_rectangle([0, 0, cw - 1, ch - 1], 28, fill=(15, 22, 33, 250))
        d.rounded_rectangle([0, 0, cw - 1, 70], 28, fill=(32, 42, 58, 255)); d.rectangle([0, 40, cw - 1, 70], fill=(32, 42, 58, 255))
        for k, col in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]): d.ellipse([28 + k * 38, 22, 52 + k * 38, 46], fill=col)
        d.text((cw / 2, 36), c.get('file', 'query.sql'), font=F('SemiBold', 28), fill=(200, 210, 225), anchor='mm')
        rows = []
        for j, l in enumerate(lines):
            kind = 'bad' if j in c.get('bad', []) else ('good' if j in c.get('good', []) else ('dim' if j in c.get('dim', []) else ''))
            col = (255, 255, 255) if kind != 'dim' else (140, 155, 175)
            if l.strip().startswith('--') or l.strip().startswith('#') or l.strip().startswith('//'): col = (150, 165, 185) if kind == '' else col
            rows.append(dict(img=text_layer(l, f, col, pad=0), kind=kind, y=96 + lh * j, h=lh))
        return dict(card=card, rows=rows, size=(cw, ch), lh=lh, shadow=shadow_for((cw, ch)),
                    appear=c.get('appear', 0.25), step=c.get('line_step', 0.3), mark=c.get('mark_at', 1.0),
                    stamp=c.get('stamp'))

    def prep_captions(self):
        caps = []
        for L in self.tl:
            words = L['caption'].split(); chunks = []; cur = []
            for w in words:
                cur.append(w)
                if len(cur) >= 4 or re.search(r'[.?!,:;]$', w) and len(cur) >= 2: chunks.append(cur); cur = []
            if cur:
                if chunks and len(cur) == 1: chunks[-1] += cur
                else: chunks.append(cur)
            tot = sum(len(w) + 1 for w in words); t = L['start']; dur = L['end'] - L['start']
            for ch in chunks:
                wt = []
                for w in ch:
                    d = dur * (len(w) + 1) / tot; wt.append((w, t, t + d)); t += d
                caps.append(dict(st=wt[0][1], en=wt[-1][2], words=wt))
        f = F('ExtraBold', 56)
        for c in caps:
            c['layers'] = [word_layer(w, f, WHITE, stroke=4, stroke_fill=(10, 16, 28)) for w, _, _ in c['words']]
            c['hl'] = [word_layer(w, f, INK, stroke=4, stroke_fill=self.accent) for w, _, _ in c['words']]
        return caps

    def prep_topic(self):
        s = self.spec
        self.tc_hook = multiline(s['hook'], fit_font(s['hook'], 'Black', 120, W - 110, 3, 70), self.accent, W - 110, 1.04, 'center')
        self.tc_title = multiline(s['title'], fit_font(s['title'], 'Bold', 58, W - 140, 2, 40), WHITE, W - 140, 1.1, 'center')
        self.tc_series = pill(s.get('series', '').upper(), F('ExtraBold', 46), INK, self.accent + (255,), padx=34, pady=14) if s.get('series') else None

    # ---- frame drawing
    def draw_panel(self, c, a, s, t, cx, cy):
        size = a['panel_size']; mo = s.get('motion', 'popin'); sd = 0.55
        panel = a['panel_base'].copy(); FLAT.draw(panel, a['panel_items'], t)
        p = t / sd; scale, ang, dx, alpha = 1.0, -1.2, 0, clamp(t / 0.15)
        if mo == 'popin': scale = 0.55 + 0.45 * back(p)
        elif mo == 'slide': dx = (1 - eo3(p)) * 900
        elif mo == 'rotate': ang = -1.2 + (1 - back(p)) * 14; scale = 0.8 + 0.2 * eo3(p)
        elif mo in ('zoom', 'kenburns'): scale = 0.9 + 0.1 * eo3(p) + 0.03 * clamp(t / 6); alpha = clamp(t / 0.3)
        bob = math.sin(t * 1.5) * 4
        paste_t(c, a['panel_shadow'], cx + dx, cy + 16 + bob, scale, ang, alpha * 0.9)
        paste_t(c, panel, cx + dx, cy + bob, scale, ang, alpha)
        ib = back((t - 0.45) / 0.4)
        paste_t(c, a['icon'], cx - size[0] / 2 + 34 + dx, cy - size[1] / 2 + 16 + bob, ib, math.sin(t * 2.2) * 5 + (1 - clamp((t - 0.45) / 0.4)) * -70)

    def draw_code(self, c, cd, t, cx, cy):
        p = eo3((t - cd['appear']) / 0.5)
        if p <= 0: return
        cw, ch = cd['size']; img = cd['card'].copy(); d = ImageDraw.Draw(img, 'RGBA')
        mk = clamp((t - cd['mark']) / 0.35)
        for j, r in enumerate(cd['rows']):
            ra = clamp((t - cd['appear'] - 0.25 - j * cd['step']) / 0.25)
            if ra <= 0: continue
            if r['kind'] in ('bad', 'good') and mk > 0:
                col = RED if r['kind'] == 'bad' else GREEN; ww = int((cw - 40) * eo3(mk))
                d.rounded_rectangle([20, r['y'] - 10, 20 + ww, r['y'] + r['h'] - 16], 12, fill=col + (70,))
                d.rectangle([20, r['y'] - 10, 28, r['y'] + r['h'] - 16], fill=col + (255,))
            ri = r['img']
            if ra < 1: ri = ri.copy(); ri.putalpha(ri.getchannel('A').point(lambda v: int(v * ra)))
            img.alpha_composite(ri, (int(48 + (1 - ra) * 30), r['y']))
        paste_t(c, cd['shadow'], cx + (1 - p) * 800, cy + 14, 1, 0, p * .9); paste_t(c, img, cx + (1 - p) * 800, cy, 1, 0, p)
        for j, r in enumerate(cd['rows']):
            if r['kind'] in ('bad', 'good') and mk > 0:
                m = cross_mark(64) if r['kind'] == 'bad' else check_mark(64)
                paste_t(c, m, cx + cw / 2 - 52, cy - ch / 2 + r['y'] + r['h'] / 2 - 12, back(mk), 0)
        st = cd.get('stamp')
        if st and t > cd['mark'] + 0.3:
            k = back((t - cd['mark'] - 0.3) / 0.4)
            sp = pill(st['text'], F('Black', 64), WHITE, (RED if st.get('color', 'red') == 'red' else (30, 150, 95)) + (255,), padx=36, pady=14)
            paste_t(c, sp, cx + cw / 2 - sp.width / 2 - 20, cy + ch / 2 - 10, k * (1.6 - 0.6 * k), 5)

    def header(self, c, a, t, y0=180):
        x = 60
        for j, tg in enumerate(a['tags']):
            paste_t(c, tg, x + tg.width / 2, y0 + tg.height / 2, back((t - 0.05 - j * 0.12) / 0.35)); x += tg.width + 16
        y = y0 + (a['tags'][0].height + 18 if a['tags'] else 0)
        if 'head' in a:
            wp = eo3((t - 0.15) / 0.55); hd = a['head']
            if wp > 0:
                ww = max(1, int(hd.width * wp)); c.alpha_composite(hd.crop((0, 0, ww, hd.height)), (60, int(y)))
                if wp < 1: ImageDraw.Draw(c).rectangle([60 + ww, y + 6, 60 + ww + 10, y + hd.height - 6], fill=self.accent + (255,))
            y += hd.height + 14
        if 'sub' in a:
            sa = clamp((t - 0.55) / 0.4); sb = a['sub']
            if sa > 0: paste_t(c, sb, 60 + sb.width / 2, y + sb.height / 2 + (1 - sa) * 14, 1, 0, sa)
            y += sb.height + 10
        return y

    def scene_frame(self, k, t_abs):
        sc = self.scenes[k]; s = sc['s']; a = sc['a']; t = t_abs - sc['st']; typ = s.get('type', 'scene'); typ = 'scene' if typ == 'photo' else typ
        c = a['bgim'].copy()
        if typ == 'scene':
            y = self.header(c, a, t); has_code = 'code' in a
            if 'panel_items' in a:
                ph = a['panel_size']; cy = max(y + 40, 470 if has_code else 500) + ph[1] / 2
                self.draw_panel(c, a, s, t, W / 2, cy); y = cy + ph[1] / 2 + 40
            if has_code:
                cd = a['code']; cy = min(max(y + 10, 880) + cd['size'][1] / 2, 1385 - cd['size'][1] / 2); self.draw_code(c, cd, t, W / 2, cy)
        elif typ == 'question':
            y = self.header(c, a, t)
            if 'panel_items' in a: self.draw_panel(c, a, s, t, W / 2, 640); qy = 1000
            else: paste_t(c, a['icon'], W / 2, 560, 1.5 * back(t / 0.45), math.sin(t * 3) * 8); qy = 860
            paste_t(c, a['q'], W / 2, qy, back((t - 0.1) / 0.45))
            wob = math.sin(t * 5) * 3; yy = qy + a['q'].height / 2 + 120
            paste_t(c, a['yes'], W / 2 - 170, yy, back((t - 0.5) / 0.4), wob); paste_t(c, a['no'], W / 2 + 170, yy, back((t - 0.65) / 0.4), -wob)
        elif typ == 'end':
            if 'panel_items' in a: self.draw_panel(c, a, s, t, W / 2, 560)
            paste_t(c, a['hook_small'], W / 2, 900, 1, 0, clamp(t / 0.3))
            paste_t(c, a['follow'], W / 2, 1090, back((t - 0.1) / 0.45) * (1 + 0.03 * math.sin(t * 6)))
            fy = 1090 + a['follow'].height / 2 + 90
            paste_t(c, a['handle'], W / 2, fy, back((t - 0.35) / 0.45))
            paste_t(c, a['follow_icon'], W / 2 + a['handle'].width / 2 + 40, fy - 70, back((t - 0.6) / 0.4), math.sin(t * 8) * 8)
        return c

    def captions(self, c, t):
        cap = None
        for cp in self.caps:
            if cp['st'] - 0.05 <= t < cp['en'] + 0.15: cap = cp; break
        if not cap: return
        gap = 16; widths = [l.width for l in cap['layers']]; lines = [[]]; lw = 0
        for j, wdt in enumerate(widths):
            if lw + wdt > W - 140 and lines[-1]: lines.append([]); lw = 0
            lines[-1].append(j); lw += wdt + gap
        y = 1440 - (len(lines) - 1) * 40; a_ = clamp((t - cap['st'] + 0.05) / 0.12)
        for ln in lines:
            tw = sum(widths[j] for j in ln) + gap * (len(ln) - 1); x = (W - tw) / 2
            for j in ln:
                w, ws, we = cap['words'][j]; L = cap['layers'][j]
                if ws <= t < we + 0.02:
                    ImageDraw.Draw(c).rounded_rectangle([x - 10, y + 2, x + L.width + 10, y + L.height - 2], 14, fill=self.accent + (255,))
                    c.alpha_composite(cap['hl'][j], (int(x), int(y)))
                else: paste_t(c, L, x + L.width / 2, y + L.height / 2, 1, 0, a_)
                x += L.width + gap
            y += 80

    def progress(self, c, t):
        d = ImageDraw.Draw(c, 'RGBA'); x0, x1, y = 70, W - 70, 1575
        d.rounded_rectangle([x0, y - 5, x1, y + 5], 5, fill=(255, 255, 255, 70))
        p = clamp(t / self.total); d.rounded_rectangle([x0, y - 5, x0 + max(10, (x1 - x0) * p), y + 5], 5, fill=self.accent + (255,))
        for sc in self.scenes:
            x = x0 + (x1 - x0) * sc['st'] / self.total; on = t >= sc['st']
            d.ellipse([x - 11, y - 11, x + 11, y + 11], fill=(self.accent + (255,)) if on else (255, 255, 255, 255), outline=(10, 16, 28, 255), width=3)

    def topic_card(self, c, t):
        if t >= self.topic_dur: return
        fade_at = self.topic_dur - 0.35; a = 1.0 if t < fade_at else 1 - (t - fade_at) / 0.35
        ov = Image.new('RGBA', (W, H), (10, 18, 32, int(242 * a))); c.alpha_composite(ov)
        if self.tc_series: paste_t(c, self.tc_series, W / 2, 600, 0.85 + 0.15 * back(t / 0.3), 0, a)
        paste_t(c, self.tc_hook, W / 2, 860, 0.9 + 0.1 * back(t / 0.35) + 0.02 * t, 0, a)
        paste_t(c, self.tc_title, W / 2, 1120 + self.tc_hook.height / 2 - 120, 1, 0, a * clamp((t - 0.25) / 0.3))
        wp = clamp(t / self.topic_dur); d = ImageDraw.Draw(c, 'RGBA')
        d.rounded_rectangle([340, 1320, 340 + 400 * wp, 1330], 5, fill=self.accent + (int(255 * a),))

    def frame(self, t):
        k = 0
        for i, sc in enumerate(self.scenes):
            if sc['st'] <= t: k = i
        img = self.scene_frame(k, t); TR = 0.25; lt = t - self.scenes[k]['st']
        if k > 0 and lt < TR:
            prev = self.scene_frame(k - 1, t); img = Image.blend(prev, img, eio(lt / TR))
        if self.series: c = img; c.alpha_composite(self.series, (60, 62))
        self.progress(img, t)
        if t >= self.topic_dur - 0.2: self.captions(img, t)
        self.topic_card(img, t)
        img.alpha_composite(self.badge, (W - self.badge.width - 36, 46))   # badge always on top
        return img.convert('RGB')

    def cover(self, out):
        s = self.spec; sc = next((x for x in self.scenes if 'panel_items' in x['a']), None)
        c = Image.new('RGBA', (W, H), hexrgb(s.get('cover_bg', '#12233B')) + (255,))
        if sc:
            a = sc['a']; size = (980, 760); panel = self.panel_base(size, a['bg'])
            FLAT.draw(panel, FLAT.build(s.get('cover_illustration', sc['s']['illustration']), size[0], size[1], self.accent), 30.0)
            paste_t(c, shadow_for(size, r=34), W / 2, 1290, 1, -2); paste_t(c, panel, W / 2, 1270, 1, -2)
            paste_t(c, a['icon'], W / 2 - 430, 900, 1.1, 0)
        t = s['title']; f = fit_font(t, 'Black', 130, W - 120, 4, 64)
        tl = multiline(t, f, WHITE, W - 120, 1.05, 'center', stroke=6, stroke_fill=(8, 14, 26))
        paste_t(c, tl, W / 2, 330 + tl.height / 2)
        c.alpha_composite(self.badge, (W - self.badge.width - 36, 46))
        c.convert('RGB').save(out, quality=92)

R = None
def _init(r):
    global R; R = r
def _frame(i): return R.frame(i / FPS).tobytes()

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('spec'); ap.add_argument('--out-dir', required=True)
    ap.add_argument('--variant', default='instagram', help='instagram (default) or a key under spec.variants, e.g. facebook')
    ap.add_argument('--preview', action='store_true', help='also write PNG frames to OUT/preview-<variant>/')
    ap.add_argument('--preview-only', action='store_true'); ap.add_argument('--fake-tts', action='store_true', help='silent placeholder audio (layout checks only)')
    ap.add_argument('--times', default='', help='comma list of preview times (s)')
    ap.add_argument('--workers', type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument('--cache', default=os.environ.get('K4_TTS_CACHE', '/workspace/.cache/k4-2d-tts'))
    ap.add_argument('--no-lock', action='store_true'); ap.add_argument('--lock-wait', type=int, default=900, help='max seconds to wait for the shared heavy-job lock')
    a = ap.parse_args(); T0 = time.time()
    spec = load_spec(a.spec, a.variant); os.makedirs(a.out_dir, exist_ok=True)
    slug = spec.get('slug', 'reel') + ('' if a.variant == 'instagram' else '-' + a.variant)
    lockf = None
    if not a.no_lock and not a.fake_tts:
        lockf = open(LOCK, 'a+'); t0 = time.time()
        while True:
            try: fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB); break
            except BlockingIOError:
                if time.time() - t0 > a.lock_wait: log('lock wait exceeded, continuing without lock'); lockf = None; break
                time.sleep(5)
        if lockf: lockf.seek(0); lockf.truncate(); lockf.write(f'render_2d_reel {slug} pid={os.getpid()} {time.strftime("%Y-%m-%dT%H:%M:%S%z")}\n'); lockf.flush()
    voice = Voice(spec.get('voice', {}), a.cache)
    audio, tl, total = build_timeline(spec, voice, a.fake_tts); T1 = time.time(); log(f'voice {total:.1f}s ready in {T1 - T0:.0f}s')
    if voice.m is not None: del voice.m
    import soundfile as sf
    wav = os.path.join(a.out_dir, slug + '-voice.wav'); sf.write(wav, audio, SR)
    r = Reel(spec, tl, total)
    json.dump(dict(total=total, lines=tl), open(os.path.join(a.out_dir, slug + '-timeline.json'), 'w'), indent=1)
    # srt
    def ts(x): return f'{int(x // 3600):02d}:{int(x % 3600 // 60):02d}:{int(x % 60):02d},{int(round((x % 1) * 1000)) % 1000:03d}'
    open(os.path.join(a.out_dir, slug + '.srt'), 'w').write('\n'.join(f"{i + 1}\n{ts(c['st'])} --> {ts(c['en'])}\n{' '.join(w for w, _, _ in c['words'])}\n" for i, c in enumerate(r.caps)))
    # credits
    cr = [f"{spec.get('series', '')} {spec['title']}".strip(), '', 'Graphics: built-in flat 2D vector illustrations drawn in PIL (tools/flat_illustrations.py). No photos used.']
    cr += ['Voice: Chatterbox TTS (Resemble AI, MIT), reference voice ref_am_michael. Voice only, no music.', 'Fonts: Poppins, JetBrains Mono (SIL OFL 1.1).']
    open(os.path.join(a.out_dir, slug + '-credits.txt'), 'w').write('\n'.join(cr) + '\n')
    r.cover(os.path.join(a.out_dir, slug + '-cover.jpg'))
    if a.preview or a.preview_only:
        pd = os.path.join(a.out_dir, 'preview-' + a.variant); os.makedirs(pd, exist_ok=True)
        times = [float(x) for x in a.times.split(',') if x] or sorted({0.0, 0.5, 1.0, 1.7} | {round(sc['st'] + 0.3, 2) for sc in r.scenes} | {round((sc['st'] + sc['en']) / 2, 2) for sc in r.scenes} | {round(total - 0.05, 2)})
        for tt in times: r.frame(min(tt, total - 0.01)).save(os.path.join(pd, f't{tt:06.2f}.png'))
        log('preview frames ->', pd)
    if a.preview_only: return
    out = os.path.join(a.out_dir, slug + '.mp4'); n = int(math.ceil(total * FPS))
    ff = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-', '-i', wav,
                           '-af', 'loudnorm=I=-14:TP=-1.5:LRA=11', '-ar', '48000', '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p',
                           '-c:a', 'aac', '-b:a', '160k', '-shortest', '-movflags', '+faststart', out], stdin=subprocess.PIPE)
    with Pool(a.workers, initializer=_init, initargs=(r,)) as pool:
        for i, b in enumerate(pool.imap(_frame, range(n), chunksize=8)):
            ff.stdin.write(b)
            if i % 300 == 0: log(f'frame {i}/{n}')
    ff.stdin.close(); ff.wait()
    if ff.returncode: sys.exit('ffmpeg failed')
    log(f'DONE {out} ({total:.1f}s) voice {T1 - T0:.0f}s + video {time.time() - T1:.0f}s = {time.time() - T0:.0f}s total')
    print(json.dumps(dict(mp4=out, cover=os.path.join(a.out_dir, slug + '-cover.jpg'), credits=os.path.join(a.out_dir, slug + '-credits.txt'), duration=round(total, 2), seconds=round(time.time() - T0))))

if __name__ == '__main__': main()
