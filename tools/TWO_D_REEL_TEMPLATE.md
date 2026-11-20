# 2D explainer Reel template (`render_2d_reel.py`)

From **Fri 20 Nov 2026, 6 PM IST** this is the standard for Instagram and Facebook
Reels (the user approved it on 19–20 Nov 2026). It replaces the viral template
(`VIRAL_REEL_TEMPLATE.md`) for new Reels. Already posted or scheduled Reels are not re-rendered.
Reference look: `/workspace/shorts-template/2d-explainer-template/` (TEMPLATE.md + reference-short/).

## Rules (do not break)

- **Flat 2D motion graphics** drawn with PIL and encoded with ffmpeg. No 3D, no Pixar look, no AI video (`GenerateVideo`).
- **Real, freely licensed photos** (Wikimedia Commons via `fetch_photo.py`; Unsplash or Pexels by hand if needed), with a visible credit line under each photo and a `-credits.txt` file. No NC/ND licenses.
- Each key object moves in 2D: the photo is a white-bordered cut-out card (pop-in, slide, rotate or Ken Burns, plus a slow zoom inside), with a flat **icon badge** on its corner, **label tags** (pills), a **headline wipe**, and a **progress bar** with one dot per scene.
- **Coding topics must show code**: real photo (server, laptop, database…) on top, flat code card below. Broken line = red bar with ✕, fixed line = green bar with ✓. Max ~3–4 short lines.
- **1080×1920, 30 fps**, 25–40 s. **Topic card 1.5–2 s** (series pill + hook + title) and the **hook is on screen from frame 0** and spoken in the first second.
- **K4Coding Academy badge** top-right on **every frame** (drawn last; the QA checks all frames).
- **Voice**: Chatterbox TTS, reference voice `/workspace/ingress/work/tts2/ref_am_michael.wav`. **Voice only — no music, no SFX bed.**
- Never put the word "illustrative" on screen (the renderer refuses specs that contain it).
- **Cover text = the title, exactly** (`title`). The cover has only the title, a photo card, an icon and the badge.
- Kept from the old rules: **one idea per Reel**, one real question in the caption, short hashtag list, facts checked against official docs (put the source URL in `fact_source`), hypotheticals labeled.

## Spec format (JSON)

Full example: `tools/examples/2d-example.json` (SQL Bugs #7, COUNT(column) skips NULLs). Photo paths are relative to the spec file.

```jsonc
{
  "slug": "sql-count-column-skips-nulls",      // output file names
  "series": "SQL Bugs #7",                      // pill, visible from frame 0
  "next": 8,                                    // end card: FOLLOW FOR #8
  "handle": "@K4CODING",
  "title": "COUNT(column) skips NULLs",         // topic card subtitle + cover text (exact)
  "hook": "COUNT SAID 40. THE TABLE HAS 50.",   // big topic-card text, frame 0
  "accent": "#FFC857", "watermark": "NULL", "topic_card": 1.8,
  "question": "Has COUNT ever fooled you?",     // question scene text
  "fact_source": "https://www.postgresql.org/docs/current/functions-aggregate.html",
  "voice": {"ref": ".../ref_am_michael.wav", "exaggeration": 0.45, "cfg_weight": 0.4, "seed": 900},
  "scenes": [
    {"id": "hook", "bg": "#1F3A5F", "icon": "database", "motion": "popin",
     "tags": ["THE BUG"], "headline": "Your COUNT is missing rows", "sub": "optional one-liner",
     "photo": {"path": "photos/tech-rack.jpg", "focus": [0.5, 0.4]},   // credit read from photos/tech-rack.json
     "voice": "Your count says forty users, but the table has fifty rows?",   // spoken text (numbers as words)
     "caption": "Your COUNT says 40 users, but the table has 50 rows?"},       // optional on-screen caption text
    {"id": "why", "motion": "slide", "icon": "bug", "tags": ["WHY"], "headline": "COUNT(column) skips NULLs",
     "photo": {"path": "photos/wmf-servers.jpg"},
     "code": {"file": "report.sql", "lines": ["SELECT COUNT(phone)", "FROM users;", "-- 40: ten phones are NULL"],
              "bad": [0], "good": [], "mark_at": 1.6, "stamp": {"text": "40, NOT 50", "color": "red"}},
     "voice": "..."},
    {"id": "bait", "type": "question", "icon": "question", "tags": ["YOUR TURN"], "voice": "Has count ever fooled you? Comment yes or no."},
    {"id": "follow", "type": "end", "photo": {"path": "photos/tech-rack.jpg"}, "voice": "Follow K four coding for part eight."}
  ],
  "variants": {"facebook": {"title": "Why COUNT(phone) hides 10 users", "hook": "40 USERS? YOUR TABLE HAS 50.",
                            "scenes": {"hook": {"voice": "...", "headline": "..."}}}}
}
```

Scene fields: `type` = `photo` (default) | `question` | `end`; `motion` = `popin` | `slide` | `rotate` | `kenburns`;
`icon` = `database` `server` `code` `bug` `check` `cross` `question` `warning` `follow` `clock` `lock` `git` (anything else prints its first 2 letters);
`bg` hex colour; `pause` seconds after the line (default 0.22); `seed` to re-take one TTS line;
`code.lines/bad/good/dim/mark_at/line_step/appear/stamp`; `photo.path/credit/focus/pan`.
Timeline: every scene lasts exactly as long as its voice line (+pause); captions are word-highlighted, timed by characters inside each line.

**Voice tips (Chatterbox):** write `count` not `COUNT` in `voice` (all-caps can be misread — Whisper heard "cut star"), spell numbers ("forty"), "K four coding", "count star" for `COUNT(*)`. Use `caption` for the on-screen spelling.

Suggested 6 beats, 75–90 words: hook (pain, 1 line) → why (bug code, red) → fix (fixed code, green) → payoff/pro tip → question (YES/NO) → end card (FOLLOW FOR #N+1 @K4CODING; it repeats the hook text and hook photo so the loop feels seamless).

## Commands

```bash
CB=/workspace/ingress/work/tts2/cbvenv/bin/python      # venv with chatterbox-tts, torch (CPU), pillow, soundfile
cd /workspace/social-media-assets

# 1. photos (one per scene; writes .jpg + .json with license/author/credit)
python3 tools/fetch_photo.py "server rack data center" --list -o /tmp/x.jpg     # see candidates
python3 tools/fetch_photo.py "server rack data center" --pick 1 -o WORK/photos/rack.jpg
python3 tools/fetch_photo.py --title "File:Laptop computer.jpg" -o WORK/photos/laptop.jpg

# 2. fast layout check (no TTS, ~5 s) - look at the PNGs before spending TTS time
$CB tools/render_2d_reel.py WORK/spec.json --out-dir WORK/out --preview-only --fake-tts

# 3. everything: IG + facebook render, preview PNGs, QA (exit 1 if any check fails)
tools/run_2d_reel.sh WORK/spec.json WORK/out
#   or one variant:  $CB tools/render_2d_reel.py WORK/spec.json --out-dir WORK/out [--variant facebook] [--preview]
#   QA only:         python3 tools/qa_2d_reel.py WORK/out/<slug>.mp4 --spec WORK/spec.json [--variant facebook]
```

Outputs in `--out-dir`: `<slug>.mp4`, `<slug>-cover.jpg`, `<slug>-credits.txt`, `<slug>.srt`, `<slug>-timeline.json`,
`<slug>-voice.wav`, `preview-<variant>/t*.png`; the facebook variant uses `<slug>-facebook.*`.
Audio: speech peak-normalised, then `loudnorm I=-14` → AAC 48 kHz. TTS lines are cached in `/workspace/.cache/k4-2d-tts`
(keyed by text + voice settings + seed), so the facebook variant only re-speaks the lines it changes.

QA (`qa_2d_reel.py`, system `python3` with faster-whisper): 1080×1920 + audio stream, mean volume > −35 dB,
pauses between lines are digital silence (proves no music bed), Whisper transcript ≥ 0.85 match with the script
(`lines_to_redo` lists lines to re-take with a new `seed`), badge pixel-matched on every frame, no "illustrative".

## Timing (8-core CPU box, no GPU)

SQL Bugs #7 test, 31.7 s Reel: Instagram variant **105 s** (Chatterbox ~2.3× real time: 6 lines in 80 s incl. 8 s model load;
video 25 s with 7 worker processes); facebook variant **50 s** (one new line); QA ~12 s each. Whole `run_2d_reel.sh` ≈ 3 min.
The renderer takes the shared `/workspace/content-production-heavy.lock` (waits up to 15 min, then continues; `--no-lock` to skip).

## Posting (unchanged)

Push the mp4 + cover to `posts/` with the usual `YYYY-MM-DD-HHMM-<slug>` names, append `posts/topics.log`, and schedule in Buffer as before
(Instagram needs `shouldShareToFeed`; Buffer cannot attach a cover image to video, so the cover is for reference/YouTube).
Photo credits are burned in under each photo (CC BY / BY-SA attribution); push `-credits.txt` next to the mp4 in `posts/` as the record.
