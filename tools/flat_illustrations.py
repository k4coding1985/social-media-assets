"""Built-in flat 2D vector illustrations for render_2d_reel.py (no photos).

Each builder returns a list of *items* (pre-rendered, supersampled sprites with a
position and an animation) laid out inside a panel of size (w, h).  The renderer
composites them per frame:  anim = pop | slide_up | slide_left | slide_right | rotate |
wipe | blink | float | none, delay = seconds after the scene starts.

Types: table, database, server_rack, laptop, terminal, git_branch, users, cloud, lock, clock
Spec:  "illustration": "database"   or   {"type": "table", "columns": [...], ...}
"""
import math
from PIL import Image, ImageDraw, ImageFont
import os
FONTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')
NAVY = (24, 34, 54); SLATE = (52, 66, 92); STEEL = (88, 104, 132); LIGHT = (232, 238, 247); PAPER = (250, 251, 254)
RED = (230, 57, 70); GREEN = (61, 200, 140); CYAN = (80, 200, 255); AMBER = (255, 200, 87); WHITE = (255, 255, 255)
SS = 3
TYPES = ('table', 'database', 'server_rack', 'laptop', 'terminal', 'git_branch', 'users', 'cloud', 'lock', 'clock')

def F(w, s): return ImageFont.truetype(os.path.join(FONTS, f'Poppins-{w}.ttf'), max(6, int(s)))
def MONO(s):
    f = ImageFont.truetype(os.path.join(FONTS, 'JetBrainsMono-Variable.ttf'), max(6, int(s)))
    try: f.set_variation_by_name('Bold')
    except Exception: pass
    return f
def sprite(w, h, fn):
    w, h = max(2, int(w)), max(2, int(h))
    im = Image.new('RGBA', (w * SS, h * SS), (0, 0, 0, 0)); fn(ImageDraw.Draw(im), SS, w, h)
    return im.resize((w, h), Image.LANCZOS)
def chip(text, bg, fg=WHITE, size=40):
    f = F('ExtraBold', size * SS); tw = ImageDraw.Draw(Image.new('RGBA', (1, 1))).textlength(text, font=f) / SS
    w, h = tw + size * 1.2, size * 1.75
    def fn(d, s, W, H):
        d.rounded_rectangle([0, 0, W * s - 1, H * s - 1], H * s // 2, fill=bg + (255,))
        d.text((W * s / 2, H * s / 2), text, font=f, fill=fg, anchor='mm')
    return sprite(w, h, fn)
def arrow(length, col=WHITE, thick=10):
    def fn(d, s, W, H):
        y = H * s / 2; d.line([(0, y), (W * s - thick * 2.6 * s, y)], fill=col + (255,), width=int(thick * s))
        d.polygon([(W * s, y), (W * s - thick * 3 * s, y - thick * 1.8 * s), (W * s - thick * 3 * s, y + thick * 1.8 * s)], fill=col + (255,))
    return sprite(length, thick * 4, fn)
def blob(w, h, col, alpha=60):
    return sprite(w, h, lambda d, s, W, H: d.ellipse([0, 0, W * s - 1, H * s - 1], fill=col + (alpha,)))

# ------------------------------------------------------------------ objects
def cylinder(w, h, col=CYAN, dark=None, bands=3):
    dark = dark or tuple(int(c * .72) for c in col)
    def fn(d, s, W, H):
        W, H = W * s, H * s; e = H * 0.16; band = (H - e) / bands
        for i in range(bands - 1, -1, -1):
            y0 = e / 2 + i * band
            d.rectangle([0, y0, W - 1, y0 + band], fill=col + (255,))
            d.ellipse([0, y0 + band - e / 2, W - 1, y0 + band + e / 2 - 1], fill=dark + (255,) if i == bands - 1 else col + (255,))
            d.arc([0, y0 + band - e / 2, W - 1, y0 + band + e / 2 - 1], 0, 180, fill=dark + (255,), width=int(4 * s))
        d.ellipse([0, 0, W - 1, e - 1], fill=tuple(min(255, int(c * 1.15)) for c in col) + (255,))
        d.ellipse([W * .08, e * .15, W * .92, e * .85], outline=dark + (255,), width=int(3 * s))
        for i in range(bands):  # LEDs
            y = e / 2 + i * band + band * .55; d.ellipse([W * .78, y - 6 * s, W * .78 + 12 * s, y + 6 * s], fill=WHITE + (230,))
    return sprite(w, h, fn)
def rack(w, h, units=6):
    def fn(d, s, W, H):
        W, H = W * s, H * s; d.rounded_rectangle([0, 0, W - 1, H - 1], 18 * s, fill=NAVY + (255,))
        d.rounded_rectangle([10 * s, 10 * s, W - 10 * s, H - 10 * s], 12 * s, fill=SLATE + (255,))
        uh = (H - 40 * s) / units
        for i in range(units):
            y = 20 * s + i * uh; d.rounded_rectangle([20 * s, y + 4 * s, W - 20 * s, y + uh - 4 * s], 6 * s, fill=NAVY + (255,))
            for k in range(4): d.rectangle([34 * s + k * 16 * s, y + uh * .35, 42 * s + k * 16 * s, y + uh * .65], fill=STEEL + (255,))
    return sprite(w, h, fn)
def led(r, col): return sprite(r * 2, r * 2, lambda d, s, W, H: d.ellipse([0, 0, W * s - 1, H * s - 1], fill=col + (255,)))
def laptop(w, h):
    def fn(d, s, W, H):
        W, H = W * s, H * s; sh = H * .78
        d.rounded_rectangle([W * .1, 0, W * .9, sh], 16 * s, fill=NAVY + (255,))
        d.rounded_rectangle([W * .1 + 14 * s, 14 * s, W * .9 - 14 * s, sh - 14 * s], 8 * s, fill=(14, 20, 32, 255))
        d.polygon([(W * .04, sh + 4 * s), (W * .96, sh + 4 * s), (W, H - 1), (0, H - 1)], fill=STEEL + (255,))
        d.rounded_rectangle([W * .42, sh + 8 * s, W * .58, sh + 20 * s], 6 * s, fill=SLATE + (255,))
    return sprite(w, h, fn)
def bar(w, h, col): return sprite(w, h, lambda d, s, W, H: d.rounded_rectangle([0, 0, W * s - 1, H * s - 1], H * s // 2, fill=col + (255,)))
def window(w, h, title='terminal'):
    def fn(d, s, W, H):
        W, H = W * s, H * s; d.rounded_rectangle([0, 0, W - 1, H - 1], 20 * s, fill=(15, 22, 33, 255))
        d.rounded_rectangle([0, 0, W - 1, 46 * s], 20 * s, fill=(36, 46, 64, 255)); d.rectangle([0, 26 * s, W - 1, 46 * s], fill=(36, 46, 64, 255))
        for k, col in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]): d.ellipse([18 * s + k * 26 * s, 15 * s, 34 * s + k * 26 * s, 31 * s], fill=col)
        d.text((W / 2, 23 * s), title, font=F('SemiBold', 20 * s), fill=(190, 200, 215), anchor='mm')
    return sprite(w, h, fn)
def text(t, size, col=WHITE, mono=False, weight='Bold'):
    f = (MONO if mono else (lambda z: F(weight, z)))(size * SS)
    b = ImageDraw.Draw(Image.new('RGBA', (1, 1))).textbbox((0, 0), t, font=f)
    return sprite((b[2] - b[0]) / SS + 4, (b[3] - b[1]) / SS + 6, lambda d, s, W, H: d.text((2 * s - b[0], 3 * s - b[1]), t, font=f, fill=col))
def person(w, h, col):
    def fn(d, s, W, H):
        W, H = W * s, H * s; d.ellipse([W * .28, 0, W * .72, H * .42], fill=col + (255,)); d.pieslice([0, H * .48, W - 1, H * 1.5], 180, 360, fill=col + (255,))
    return sprite(w, h, fn)
def cloud(w, h, col=LIGHT):
    def fn(d, s, W, H):
        W, H = W * s, H * s; d.ellipse([W * .05, H * .35, W * .45, H * .95], fill=col + (255,)); d.ellipse([W * .25, H * .05, W * .7, H * .8], fill=col + (255,))
        d.ellipse([W * .55, H * .3, W * .95, H * .95], fill=col + (255,)); d.rounded_rectangle([W * .2, H * .55, W * .8, H * .95], H * .2, fill=col + (255,))
    return sprite(w, h, fn)
def padlock(w, h, col=AMBER):
    def fn(d, s, W, H):
        W, H = W * s, H * s; d.arc([W * .2, 0, W * .8, H * .7], 180, 360, fill=STEEL + (255,), width=int(W * .1)); d.rectangle([W * .2 - W * .05, H * .33, W * .25, H * .5], fill=STEEL + (255,)); d.rectangle([W * .75, H * .33, W * .85, H * .5], fill=STEEL + (255,))
        d.rounded_rectangle([0, H * .42, W - 1, H - 1], W * .1, fill=col + (255,)); d.ellipse([W * .42, H * .6, W * .58, H * .74], fill=NAVY + (255,)); d.rectangle([W * .47, H * .68, W * .53, H * .86], fill=NAVY + (255,))
    return sprite(w, h, fn)
def clockface(r):
    def fn(d, s, W, H):
        W, H = W * s, H * s; d.ellipse([0, 0, W - 1, H - 1], fill=PAPER + (255,), outline=NAVY + (255,), width=int(W * .06))
        for k in range(12):
            a = k * math.pi / 6; d.line([(W / 2 + math.cos(a) * W * .36, H / 2 + math.sin(a) * H * .36), (W / 2 + math.cos(a) * W * .42, H / 2 + math.sin(a) * H * .42)], fill=NAVY + (255,), width=int(W * .025))
    return sprite(r * 2, r * 2, fn)
def hand(length, thick, col):
    return sprite(thick, length * 2, lambda d, s, W, H: d.rounded_rectangle([0, 0, W * s - 1, H * s / 2], W * s // 2, fill=col + (255,)))

# ------------------------------------------------------------------ layouts
def I(img, x, y, anim='pop', delay=0.0, **kw): return dict(img=img, x=x, y=y, anim=anim, delay=delay, **kw)

def build(spec, w, h, accent=AMBER):
    if isinstance(spec, str): spec = {'type': spec}
    typ = spec.get('type', 'database'); k = min(w / 960, h / 400)
    items = [I(blob(w * .55, w * .55 * .62, WHITE, 26), w * .5, h * .55, 'float', 0, amp=4)]
    chips = spec.get('chips', [])
    if typ == 'table':
        cols = spec.get('columns', ['id', 'name', 'phone']); rows = spec.get('rows', [['1', 'Asha', '98…'], ['2', 'Ravi', 'NULL'], ['3', 'Mei', '91…'], ['4', 'Leo', 'NULL'], ['5', 'Zoe', '97…']])
        nr = len(rows) + 1; tw = min(w * (.5 if chips else .8), 640 * k); rh = min((h * .86) / nr, 84 * k); x0 = w * .05 if chips else (w - tw) / 2; y0 = (h - rh * nr) / 2
        cw = tw / len(cols)
        items.append(I(sprite(tw, rh, lambda d, s, W, H: d.rounded_rectangle([0, 0, W * s - 1, H * s - 1], 14 * s, fill=NAVY + (255,))), x0 + tw / 2, y0 + rh / 2, 'slide_up', 0.0))
        for j, cn in enumerate(cols): items.append(I(text(cn, rh * .42, AMBER), x0 + cw * j + cw / 2, y0 + rh / 2, 'none', 0.1))
        for i, r in enumerate(rows):
            yy = y0 + rh * (i + 1) + rh / 2; null = any(str(v).upper() == 'NULL' for v in r)
            items.append(I(sprite(tw, rh - 6 * k, lambda d, s, W, H, n=null: d.rounded_rectangle([0, 0, W * s - 1, H * s - 1], 10 * s, fill=(PAPER if not n else (255, 228, 230)) + (255,))), x0 + tw / 2, yy, 'slide_left', 0.15 + i * 0.12))
            for j, v in enumerate(r):
                n = str(v).upper() == 'NULL'
                items.append(I(text(str(v), rh * .4, RED if n else NAVY, mono=True), x0 + cw * j + cw / 2, yy, 'blink' if n else 'none', 0.15 + i * 0.12 + 0.2, period=1.2 if n else 0))
        cx = x0 + tw + (w - x0 - tw) / 2
    elif typ == 'database':
        dw = 230 * k; dh = 300 * k; cx0 = w * .32 if chips else w / 2
        items.append(I(cylinder(dw, dh, spec.get('color') and tuple(spec['color']) or CYAN), cx0, h * .52, 'pop', 0.05))
        for j, (dx, dy) in enumerate([(-0.62, -0.35), (0.62, -0.1), (-0.55, 0.42)][:spec.get('bubbles', 3)]):
            items.append(I(chip(spec.get('bubble', 'NULL'), RED, size=34 * k), cx0 + dx * dw * 1.05, h * .52 + dy * dh, 'pop', 0.45 + j * 0.18, float_amp=6))
        cx = w * .74
    elif typ == 'server_rack':
        rw, rh_ = 170 * k, min(h * .82, 420 * k); n = 3; gap = 26 * k; tot = n * rw + (n - 1) * gap; x0 = (w * (.62 if chips else 1) - tot) / 2 + rw / 2
        for i in range(n):
            x = x0 + i * (rw + gap); items.append(I(rack(rw, rh_), x, h * .53, 'slide_up', i * 0.12))
            uh = (rh_ - 40 * k) / 6
            for u in range(6):
                col = GREEN if (i + u) % 4 else RED
                items.append(I(led(7 * k, col), x + rw / 2 - 34 * k, h * .53 - rh_ / 2 + 20 * k + u * uh + uh / 2, 'blink', 0.4 + i * 0.12, period=0.6 + ((i * 7 + u * 3) % 5) * 0.17))
        cx = w * .82
    elif typ == 'laptop':
        lw, lh = min(w * .52, 600 * k), min(h * .8, 390 * k); lx = w * .33 if chips else w / 2; ly = h * .5
        items.append(I(laptop(lw, lh), lx, ly, 'rotate', 0.0))
        sx0 = lx - lw * .4 + 26 * k; sy0 = ly - lh / 2 + 34 * k; lines = spec.get('screen', [(0.7, CYAN), (0.5, WHITE), (0.82, GREEN if spec.get('ok', True) else RED), (0.4, WHITE)])
        for i, (frac, col) in enumerate(lines):
            bw = (lw * .8 - 60 * k) * frac; items.append(I(bar(bw, 20 * k, tuple(col)), sx0 + bw / 2, sy0 + 6 * k + i * 44 * k, 'wipe', 0.4 + i * 0.2))
        cx = w * .76
    elif typ == 'terminal':
        lines = spec.get('lines', ['$ psql -c "SELECT 1"', ' ?column?', '        1']); tw = min(w * (.6 if chips else .86), 760 * k); th = min(h * .86, (84 + 60 * len(lines)) * k)
        tx = (w * (.62 if chips else 1)) / 2
        items.append(I(window(tw, th, spec.get('title', 'terminal')), tx, h / 2, 'pop', 0.0))
        for i, l in enumerate(lines):
            im = text(l, 38 * k, GREEN if l.startswith('$') else LIGHT, mono=True)
            if im.width > tw - 50 * k: im = im.resize((int(tw - 50 * k), int(im.height * (tw - 50 * k) / im.width)), Image.LANCZOS)
            items.append(I(im, tx - tw / 2 + 28 * k + im.width / 2, h / 2 - th / 2 + 84 * k + i * 58 * k, 'wipe', 0.35 + i * 0.3))
        cx = w * .82
    elif typ == 'git_branch':
        y1, y2 = h * .38, h * .68; x0, x1 = w * .1, w * (.66 if chips else .9)
        items.append(I(bar(x1 - x0, 14 * k, STEEL), (x0 + x1) / 2, y1, 'wipe', 0.0))
        def br(d, s, W, H):
            d.line([(0, 0), (W * s * .3, H * s - 7 * s), (W * s - 1, H * s - 7 * s)], fill=accent + (255,), width=int(14 * s), joint='curve')
        items.append(I(sprite((x1 - x0) * .55, y2 - y1 + 7 * k, br), x0 + (x1 - x0) * .35 + (x1 - x0) * .55 / 2, (y1 + y2) / 2 + 3 * k, 'wipe', 0.4))
        for i in range(5): items.append(I(led(22 * k, CYAN), x0 + (x1 - x0) * (0.05 + i * 0.22), y1, 'pop', 0.1 + i * 0.12))
        for i in range(3): items.append(I(led(22 * k, accent), x0 + (x1 - x0) * (0.5 + i * 0.2), y2, 'pop', 0.7 + i * 0.15))
        items.append(I(text(spec.get('main', 'main'), 28 * k, LIGHT), x0 + 50 * k, y1 - 50 * k, 'pop', 0.3)); items.append(I(text(spec.get('branch', 'feature'), 28 * k, accent), x1 - 60 * k, y2 + 50 * k, 'pop', 0.9))
        cx = w * .84
    elif typ == 'users':
        n = spec.get('count', 5); gone = set(spec.get('gone', [1, 3])); pw = 110 * k; ph = 150 * k; gap = 30 * k
        tot = n * pw + (n - 1) * gap; x0 = (w * (.64 if chips else 1) - tot) / 2 + pw / 2
        for i in range(n):
            items.append(I(person(pw, ph, (STEEL if i in gone else LIGHT)), x0 + i * (pw + gap), h * .52, 'pop', 0.1 + i * 0.1, fade_to=0.35 if i in gone else None, fade_at=1.2))
        cx = w * .82
    elif typ == 'cloud':
        items.append(I(cloud(380 * k, 240 * k), w * (.36 if chips else .5), h * .45, 'pop', 0.0))
        for i in range(3): items.append(I(arrow(90 * k, WHITE, 8 * k).rotate(90, expand=True), w * (.36 if chips else .5) + (i - 1) * 90 * k, h * .8, 'slide_up', 0.4 + i * 0.12))
        cx = w * .78
    elif typ == 'lock':
        items.append(I(padlock(200 * k, 260 * k), w * (.34 if chips else .5), h * .52, 'rotate', 0.0)); cx = w * .76
    elif typ == 'clock':
        r = 140 * k; X = w * (.34 if chips else .5); items.append(I(clockface(r), X, h * .5, 'pop', 0.0))
        items.append(I(hand(r * .55, 12 * k, NAVY), X, h * .5, 'spin', 0.3, speed=40)); items.append(I(hand(r * .8, 7 * k, RED), X, h * .5, 'spin', 0.3, speed=240)); cx = w * .76
    else:
        raise ValueError(f'unknown illustration type {typ!r}; use one of {TYPES}')
    # chips (result labels) stacked on the right, arrow from the object to the first chip
    if chips:
        n = len(chips); ch = 80 * k; ys = [h / 2 + (i - (n - 1) / 2) * (ch + 22 * k) for i in range(n)]
        for i, c in enumerate(chips):
            txt, col = (c, accent) if isinstance(c, str) else (c['text'], {'red': RED, 'green': GREEN, 'cyan': CYAN}.get(c.get('color'), accent))
            im = chip(txt, col, NAVY if col in (accent, GREEN, CYAN) else WHITE, 44 * k)
            if im.width > w * .4: im = im.resize((int(w * .4), int(im.height * w * .4 / im.width)), Image.LANCZOS)
            items.append(I(im, min(max(cx, w * .58 + im.width / 2), w - im.width / 2 - 22), ys[i], 'pop', 1.0 + i * 0.25))
    return items

def ease_back(x, s=1.70158): x = max(0, min(1, x)); return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2
def ease_out(x): x = max(0, min(1, x)); return 1 - (1 - x) ** 3

def draw(panel, items, t):
    """Composite items onto panel (RGBA) at scene time t."""
    for it in items:
        lt = t - it['delay']
        if lt < 0: continue
        img = it['img']; x, y = it['x'], it['y']; sc, ang, al = 1.0, 0.0, 1.0; a = it['anim']; p = lt / 0.45
        if a == 'pop': sc = ease_back(p)
        elif a == 'slide_up': y += (1 - ease_out(p)) * 220; al = min(1, lt / 0.25)
        elif a == 'slide_left': x += (1 - ease_out(p)) * 260; al = min(1, lt / 0.25)
        elif a == 'slide_right': x -= (1 - ease_out(p)) * 260; al = min(1, lt / 0.25)
        elif a == 'rotate': ang = (1 - ease_back(p)) * 24; sc = 0.7 + 0.3 * ease_out(p)
        elif a == 'float': y += math.sin(t * 1.3) * it.get('amp', 4); sc = 1 + 0.03 * math.sin(t * .9)
        elif a == 'blink':
            al = min(1, lt / 0.2)
            if it.get('period'): al *= 0.45 + 0.55 * (0.5 + 0.5 * math.cos(2 * math.pi * lt / it['period']))
        elif a == 'wipe':
            q = ease_out(lt / 0.5)
            if q < 1: img = img.crop((0, 0, max(1, int(img.width * q)), img.height)); x -= (it['img'].width - img.width) / 2
        elif a == 'spin':
            ang = -lt * it.get('speed', 90); sc = ease_back(p)
        elif a == 'none': al = min(1, lt / 0.2)
        if it.get('float_amp'): y += math.sin(t * 2 + it['x']) * it['float_amp']
        if it.get('fade_to') is not None and lt > it.get('fade_at', 1):
            al *= 1 - (1 - it['fade_to']) * min(1, (lt - it['fade_at']) / 0.5)
        if al <= 0.01 or sc <= 0.01: continue
        if abs(sc - 1) > 0.004: img = img.resize((max(1, int(img.width * sc)), max(1, int(img.height * sc))), Image.BILINEAR)
        if abs(ang) > 0.05: img = img.rotate(ang, resample=Image.BICUBIC, expand=True)
        if al < 0.995: img = img.copy(); img.putalpha(img.getchannel('A').point(lambda v: int(v * al)))
        px, py = int(x - img.width / 2), int(y - img.height / 2)
        x0, y0 = max(0, px), max(0, py); x1, y1 = min(panel.width, px + img.width), min(panel.height, py + img.height)
        if x1 > x0 and y1 > y0: panel.alpha_composite(img.crop((x0 - px, y0 - py, x1 - px, y1 - py)), (x0, y0))
