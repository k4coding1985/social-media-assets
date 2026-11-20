# 2D explainer Reel template (`render_2d_reel.py`)

From **Fri 20 Nov 2026, 6 PM IST** this is the standard for **all three daily** Instagram and Facebook
Reels (1 PM, 6 PM, 9 PM IST), approved by the user on 19–20 Nov 2026. It replaces the viral template
(`VIRAL_REEL_TEMPLATE.md`) for new Reels. Already posted or scheduled Reels are not re-rendered.
Reference look: `/workspace/shorts-template/2d-explainer-template/` (TEMPLATE.md + reference-short/).

**20 Nov 2026 update (user): no real images.** Reels use **only flat 2D vector illustrations drawn in PIL**
(`flat_illustrations.py`). Photos are impossible by default: the renderer refuses any spec with a
`photo`/`image`/`img`/`picture` key or any `.jpg/.png/.webp/...` path, it never opens an image file except the
K4 badge, and the QA fails if either rule is broken. No photo credits appear on screen.

## Rules (do not break)

- **Flat 2D motion graphics** drawn with PIL and encoded with ffmpeg. No 3D, no Pixar look, no AI video, **no photos or stock images**.
- Each scene's panel is a **built-in flat illustration** (`illustration` key): flat server racks with blinking LEDs, database cylinder with
  NULL bubbles, laptop with code bars, terminal, git branch graph, data table, users, cloud, lock, clock — plus result **chips**.
  Every object animates in 2D (pop-in, slide, rotate, wipe, blink, zoom); the panel itself enters with `motion`.
  Also on screen: a flat **icon badge** on the panel corner, **label tags**, a **headline wipe**, word-highlighted **captions** and a **progress bar**.
- **Coding topics must show code**: illustration panel on top, flat code card below. Broken line = red bar with ✕, fixed line = green bar with ✓. Max ~3–4 short lines.
- **1080×1920, 30 fps**, 25–40 s. **Topic card 1.5–2 s** (series pill + hook + title); the **hook is on screen from frame 0** and spoken in the first second.
- **K4Coding Academy badge** top-right on **every frame** (drawn last; QA checks all frames).
- **Voice**: Chatterbox TTS, reference voice `/workspace/ingress/work/tts2/ref_am_michael.wav`. **Voice only — no music, no SFX bed.**
- Never put the word "illustrative" on screen (renderer refuses it in any on-screen field; the spec *key* `illustration` is fine).
- **Cover text = the title, exactly** (`title`). The cover has the title, a flat illustration panel, an icon and the badge.
- Kept from the old rules: **one idea per Reel**, one real question in the caption (a specific either/or, not just "yes or no"), short hashtag list,
  facts checked against official docs (put the URL in `fact_source`), hypotheticals labeled.

## Spec format (JSON)

Full example: `tools/examples/2d-example.json` (SQL Bugs #7, COUNT(column) skips NULLs).

```jsonc
{
  "slug": "sql-count-column-skips-nulls",      // output file names
  "series": "SQL Bugs #7",                      // pill, visible from frame 0
  "next": 8,                                    // end card: FOLLOW FOR #8
  "handle": "@K4CODING",
  "title": "COUNT(column) skips NULLs",         // topic-card subtitle + cover text (exact)
  "hook": "COUNT SAID 40. THE TABLE HAS 50.",   // big topic-card text, frame 0
  "accent": "#FFC857", "watermark": "NULL", "topic_card": 1.8,
  "question": "Has COUNT ever fooled you?",     // question-scene text
  "fact_source": "https://www.postgresql.org/docs/current/functions-aggregate.html",
  "cover_illustration": {"type": "table", "...": "..."},   // optional, default = first scene's illustration
  "voice": {"ref": ".../ref_am_michael.wav", "exaggeration": 0.45, "cfg_weight": 0.4, "seed": 900},
  "scenes": [
    {"id": "hook", "bg": "#1F3A5F", "icon": "database", "motion": "popin",
     "tags": ["THE BUG"], "headline": "Your COUNT is missing rows", "sub": "users table: 50 rows. COUNT(phone): 40.",
     "illustration": {"type": "table", "columns": ["id", "name", "phone"],
                      "rows": [["1", "Asha", "98…"], ["2", "Ravi", "NULL"]],          // cells "NULL" turn red + blink
                      "chips": [{"text": "ROWS: 50", "color": "cyan"}, {"text": "COUNT(phone): 40", "color": "red"}]},
     "voice": "Your count says forty users, but the table has fifty rows?",      // spoken (numbers as words)
     "caption": "Your COUNT says 40 users, but the table has 50 rows?"},         // optional on-screen caption
    {"id": "why", "motion": "slide", "icon": "bug", "tags": ["WHY"], "headline": "COUNT(column) skips NULLs",
     "illustration": {"type": "database", "bubble": "NULL", "chips": [{"text": "SKIPPED", "color": "red"}]},
     "code": {"file": "report.sql", "lines": ["SELECT COUNT(phone)", "FROM users;", "-- 40: ten phones are NULL"],
              "bad": [0], "mark_at": 1.6, "stamp": {"text": "40, NOT 50", "color": "red"}},
     "voice": "..."},
    {"id": "bait", "type": "question", "icon": "question", "tags": ["YOUR TURN"], "voice": "..."},
    {"id": "follow", "type": "end", "illustration": {"type": "table", "...": "same as hook = seamless loop"}, "voice": "Follow K four coding for part eight."}
  ],
  "variants": {"facebook": {"title": "Why COUNT(phone) hides 10 users", "hook": "40 USERS? YOUR TABLE HAS 50.",
                            "scenes": {"hook": {"voice": "...", "headline": "..."}}}}
}
```

### Illustration types (`illustration`: a type string, or an object with `type` + options)

| type | draws | options |
|---|---|---|
| `table` | data table, rows slide in, `NULL` cells red + blinking | `columns`, `rows` (list of lists) |
| `database` | flat DB cylinder pops in, floating bubbles | `bubble` (text, default `NULL`), `bubbles` (0–3), `color` [r,g,b] |
| `server_rack` | 3 flat racks slide up, LEDs blink | – |
| `laptop` | laptop rotates in, code bars wipe on screen | `ok` (true = green bar, false = red), `screen` [[frac,[r,g,b]],...] |
| `terminal` | terminal window, lines type on (`$ ` lines green) | `lines`, `title` |
| `git_branch` | main line + feature branch, commits pop | `main`, `branch` |
| `users` | row of people, some fade out ("vanish") | `count`, `gone` (indexes) |
| `cloud`, `lock`, `clock` | flat cloud + upload arrows / padlock / spinning clock | – |

Every type accepts `chips`: up to 3 result labels, strings or `{"text", "color": red|green|cyan|accent}`, popped in on the right.
Scene fields: `type` = `scene` (default) | `question` | `end`; `motion` = `popin` | `slide` | `rotate` | `zoom`;
`icon` = `database` `server` `code` `bug` `check` `cross` `question` `warning` `follow` `clock` `lock` `git`;
`bg` hex colour; `pause` seconds after the line (default 0.22); `seed` to re-take one TTS line;
`code.lines/bad/good/dim/mark_at/line_step/appear/stamp`.
Each scene lasts exactly as long as its voice line (+pause); captions are word-highlighted, timed by characters within each line.
In a variant, overriding a scene's `voice` without a `caption` drops the base caption (so captions always follow the spoken line).

**Voice tips (Chatterbox):** write `count` not `COUNT` in `voice` (all-caps was misread as "cut"), spell numbers ("forty"),
"K four coding", "count star" for `COUNT(*)`. Use `caption` for the on-screen spelling.

Suggested 6 beats, 75–90 words: hook (pain, 1 line) → why (bug code, red) → fix (fixed code, green) → payoff/pro tip →
question → end card (FOLLOW FOR #N+1 @K4CODING, repeats the hook text + hook illustration so the loop feels seamless).

## Commands

```bash
CB=/workspace/ingress/work/tts2/cbvenv/bin/python      # venv with chatterbox-tts, torch (CPU), pillow, soundfile
cd /workspace/social-media-assets

# 1. fast layout check (no TTS, ~5 s) - look at the PNGs before spending TTS time
$CB tools/render_2d_reel.py WORK/spec.json --out-dir WORK/out --preview-only --fake-tts

# 2. everything: IG + facebook render, preview PNGs, QA (exit 1 if any check fails)
tools/run_2d_reel.sh WORK/spec.json WORK/out
#   one variant:  $CB tools/render_2d_reel.py WORK/spec.json --out-dir WORK/out [--variant facebook] [--preview]
#   QA only:      python3 tools/qa_2d_reel.py WORK/out/<slug>.mp4 --spec WORK/spec.json [--variant facebook]
```

Outputs in `--out-dir`: `<slug>.mp4`, `<slug>-cover.jpg`, `<slug>-credits.txt`, `<slug>.srt`, `<slug>-timeline.json`,
`<slug>-voice.wav`, `<slug>.mp4.qa.json`, `preview-<variant>/t*.png`; the facebook variant uses `<slug>-facebook.*`.
Audio: speech peak-normalised, then `loudnorm I=-14` → AAC 48 kHz. TTS lines are cached in `/workspace/.cache/k4-2d-tts`
(keyed by text + voice settings + seed), so the facebook variant only re-speaks the lines it changes.

QA (`qa_2d_reel.py`, system `python3` with faster-whisper): 1080×1920 + audio stream, mean volume > −35 dB,
pauses between lines are digital silence (proves no music bed), per-line Whisper transcript ≥ 0.85 match with the script
(`lines_to_redo` lists lines to re-take with a new `seed`), badge pixel-matched on every frame, no "illustrative",
**no photos** (`no_photo_lint_errors` empty and the engine opens exactly one image file: the badge).

## Timing (8-core CPU box, no GPU)

SQL Bugs #7 test, 31.7 s Reel: Instagram variant ≈ **105 s** with cold TTS (Chatterbox ≈ 2.3× real time: 6 lines in 80 s incl. 8 s model load;
video ≈ 24 s with 7 worker processes); facebook variant ≈ **50 s** (one new line); QA ≈ 12 s each. Whole `run_2d_reel.sh` ≈ 3 min.
The renderer takes the shared `/workspace/content-production-heavy.lock` (waits up to 15 min, then continues; `--no-lock` to skip).

## Posting (unchanged)

Push the mp4 + cover to `posts/` with the usual `YYYY-MM-DD-HHMM-<slug>` names, append `posts/topics.log`, and schedule in Buffer as before
(Instagram needs `shouldShareToFeed`; Buffer cannot attach a cover image to video). No photo credit line is needed in the caption.
