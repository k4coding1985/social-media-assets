#!/usr/bin/env python3
"""QA gate for render_2d_reel.py output. Run with a python that has faster-whisper
(system python3 on the box):  python3 tools/qa_2d_reel.py OUT/slug.mp4 --spec spec.json [--variant facebook]
Checks: 1080x1920 + audio stream, mean_volume > -35 dB, voice-only (pauses are silent),
Whisper transcript matches the script, K4Coding badge present on EVERY frame,
no 'illustrative' in any on-screen text. Exit 1 on failure. Writes <mp4>.qa.json"""
import argparse, difflib, json, os, re, subprocess, sys
import numpy as np
from PIL import Image
HERE = os.path.dirname(os.path.abspath(__file__)); W, H = 1080, 1920
NUM = {'0': 'zero', '1': 'one', '2': 'two', '3': 'three', '4': 'four', '5': 'five', '6': 'six', '7': 'seven', '8': 'eight', '9': 'nine', '10': 'ten', '40': 'forty', '50': 'fifty'}
def norm(t):
    t = t.lower().replace('k4', 'k four').replace('*', ' star ').replace('-', ' ')
    ws = re.findall(r"[a-z0-9']+", t); return [NUM.get(w, w) for w in ws]
def run(*a): return subprocess.run(a, capture_output=True, text=True)
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('mp4'); ap.add_argument('--spec', required=True); ap.add_argument('--variant', default='instagram')
    ap.add_argument('--whisper', default='small'); ap.add_argument('--min-ratio', type=float, default=0.85)
    a = ap.parse_args(); res = {}; ok = True
    sys.path.insert(0, HERE); spec = json.load(open(a.spec))
    if a.variant != 'instagram':
        ov = spec['variants'][a.variant]; sc = ov.get('scenes', {}); spec.update({k: v for k, v in ov.items() if k != 'scenes'})
        for s in spec['scenes']: s.update(sc.get(s['id'], {}))
    pr = json.loads(run('ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', a.mp4).stdout)
    v = [s for s in pr['streams'] if s['codec_type'] == 'video'][0]; au = [s for s in pr['streams'] if s['codec_type'] == 'audio']
    dur = float(pr['format']['duration'])
    res['video'] = f"{v['width']}x{v['height']} {v['codec_name']} {dur:.1f}s"; res['audio_stream'] = bool(au)
    ok &= v['width'] == W and v['height'] == H and bool(au); res['duration_ok_25_40'] = 25 <= dur <= 40
    vd = run('ffmpeg', '-hide_banner', '-i', a.mp4, '-af', 'volumedetect', '-vn', '-f', 'null', '-').stderr
    mv = float(re.search(r'mean_volume: (-?[\d.]+)', vd).group(1)); res['mean_volume_db'] = mv; ok &= mv > -35
    # voice-only check: gaps between voice lines must be (near) digital silence -> no music/SFX bed
    pcm = np.frombuffer(subprocess.run(['ffmpeg', '-v', 'error', '-i', a.mp4, '-vn', '-ac', '1', '-ar', '16000', '-f', 'f32le', '-'], capture_output=True).stdout, dtype=np.float32)
    tlp = a.mp4[:-4] + '-timeline.json'; tl = json.load(open(tlp))['lines'] if os.path.exists(tlp) else []
    gaps = []
    for x, y in zip(tl, tl[1:]):
        g0, g1 = x['end'] + 0.06, y['start'] - 0.04
        if g1 - g0 >= 0.08:
            seg = pcm[int(g0 * 16000):int(g1 * 16000)]; gaps.append(20 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-9))
    res['pause_rms_db_max'] = round(float(max(gaps)), 1) if gaps else None; res['voice_only'] = bool((not gaps) or max(gaps) < -45); ok &= res['voice_only']
    # whisper
    from faster_whisper import WhisperModel
    m = WhisperModel(a.whisper, device='cpu', compute_type='int8')
    segs, _ = m.transcribe(pcm, language='en', beam_size=5, condition_on_previous_text=False)
    hyp = ' '.join(s.text.strip() for s in segs); ref = ' '.join(s['voice'] for s in spec['scenes'])
    res['whisper_full'] = hyp; res['full_match_ratio'] = round(difflib.SequenceMatcher(None, norm(ref), norm(hyp)).ratio(), 3)
    per = []
    for L, sc in zip(tl, spec['scenes']):
        seg = pcm[int(max(0, L['start'] - 0.1) * 16000):int((L['end'] + 0.15) * 16000)]
        z = np.zeros(8000, np.float32); seg = np.concatenate([z, seg, z])   # silence pad: Whisper can drop speech at a clip edge
        h = ' '.join(x.text.strip() for x in m.transcribe(seg, language='en', beam_size=5)[0])
        rr = difflib.SequenceMatcher(None, norm(sc['voice']), norm(h)).ratio()
        per.append(dict(id=L['id'], ratio=round(rr, 2), heard=h))
    res['lines_to_redo'] = [p for p in per if p['ratio'] < 0.8]   # re-render these with a new "seed" in the scene
    joined = ' '.join(p['heard'] for p in per) if per else hyp      # per-line transcripts are the gate (long-form Whisper can drop a tail)
    r = difflib.SequenceMatcher(None, norm(ref), norm(joined)).ratio(); res['script_match_ratio'] = round(r, 3); ok &= bool(r >= a.min_ratio) and not res['lines_to_redo']
    # badge on every frame
    badge = Image.open(os.path.join(HERE, 'assets', 'k4-badge.png')).convert('RGBA'); bw = 250
    badge = badge.resize((bw, int(badge.height * bw / badge.width)), Image.LANCZOS); bx, by = W - bw - 36, 46
    ref_px = np.asarray(badge).astype(np.float32); msk = ref_px[..., 3] > 250
    fr = subprocess.run(['ffmpeg', '-v', 'error', '-i', a.mp4, '-vf', f'crop={bw}:{badge.height}:{bx}:{by}', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True).stdout
    n = len(fr) // (bw * badge.height * 3); arr = np.frombuffer(fr, np.uint8)[:n * bw * badge.height * 3].reshape(n, badge.height, bw, 3).astype(np.float32)
    diffs = np.abs(arr[:, msk, :] - ref_px[msk][:, :3][None]).mean(axis=(1, 2))
    res['badge_frames'] = int(n); res['badge_worst_diff'] = round(float(diffs.max()), 1); res['badge_every_frame'] = bool((diffs < 30).all()); ok &= res['badge_every_frame']
    # banned on-screen words (all on-screen text comes from the spec)
    texts = [spec.get(k, '') for k in ('title', 'hook', 'series', 'question')] + [str(s.get(k, '')) for s in spec['scenes'] for k in ('headline', 'sub', 'caption', 'voice', 'code', 'tags', 'question', 'illustration')]
    res['no_illustrative_text'] = not any(re.search('illustrat', t, re.I) for t in texts) and 'illustrat' not in hyp.lower(); ok &= res['no_illustrative_text']
    # no photos: spec lint + the engine opens no image except the K4 badge
    import render_2d_reel as R2
    lint = R2.lint_no_photos(json.load(open(a.spec))); res['no_photo_lint_errors'] = lint
    src = open(os.path.join(HERE, 'render_2d_reel.py')).read() + open(os.path.join(HERE, 'flat_illustrations.py')).read()
    res['engine_image_opens'] = src.count('Image.open(')
    res['no_photos'] = not lint and res['engine_image_opens'] == 1; ok &= res['no_photos']
    res['PASS'] = bool(ok); json.dump(res, open(a.mp4 + '.qa.json', 'w'), indent=1); print(json.dumps(res, indent=1)); sys.exit(0 if ok else 1)
if __name__ == '__main__': main()
