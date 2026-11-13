# Motion Reel template (`render_motion_reel.py`)

The Instagram/Facebook Reel style from 11 Nov 2026 is a motion-graphics explainer
modelled on the "What is a DDoS attack" reference, cut down to our ~30 s format.

## Look

| Area | What goes there |
|---|---|
| Background | Flat near-black `#0B0B0C`, no particles |
| y 236 to ~340 | **Chapter title** in Permanent Marker, all caps, white, with one `{{highlight}}` word. It changes per chapter (hook / bug / why / fix). It renders at 92 px and auto-shrinks to fit 980 px. Lint fails it under 80 px. |
| y ~350 to 1410 | **Canvas**: dark UI windows `#1C1C24` with Mac dots, code windows (mono, purple keywords), white line-art icons, straight connection lines carrying cyan (ok) or red (bad) data dots, capacity bars (cyan, turning red past the threshold), TIMEOUT/DENIED stamps, ✓/✗ badges |
| y ~1444 | Word-synced captions (Inter 40 px, keywords tinted). On by default, `"captions": {"enabled": false}` or `--no-captions` turns them off |
| bottom-right, y 1536 | Small `@k4coding` watermark |
| y ~178 | Optional **series tag** pill (e.g. `SQL BUGS #4`) above the chapter title, on screen from frame 0, set with `"series"` |
| last ≤1.45 s | End card: `FOLLOW @K4CODING` in the marker font, or `FOLLOW FOR #<N+1>` when `"series"` is set |

Colour meaning: `red` #FF5B5B for errors, `yellow` #FFB74D for terms, `orange` #F48120 or `purple` #9D7BFF for the fix/tool, `cyan` #42D3A5 for ok/normal, `bad` #FF4B4B for bad data dots and an overloaded bar.
Other palette names: `white`, `grey`, `dim`, `line`, `panel`, `green` (= cyan). Any `#RRGGBB` also works.

Audio: Neerja (`en-IN-NeerjaExpressiveNeural`, `+5%`, `+0Hz`) plus `music/ambient-pad-bed.mp3`, which `add_voiceover.py` keeps ~16 dB under the voice with sidechain ducking. Quiet UI SFX are added automatically at -18 dB vs the voice peak:
whoosh for chapter changes and `slide_*` shows, pop for `pop` shows and when dots arrive (throttled), typing ticks while code types, plus `alert`/`ding` when you ask for them with `"sfx"`. The final mix is normalized to -14 LUFS.

## Rules lint checks

- 60-90 voiceover words, with `hook`, `bug`, `why`, `fix` and `follow` segments. The last segment must be `Follow K four coding.` (series Reels: `Follow K four coding for part <N+1>.`, number spelled as a word).
- Duration 25-40 s (aim ~30). End card ≤1.5 s.
- A chapter title on frame 0, plus at least one `start_visible` element. The first animation must come by 0.3 s.
- No gap of more than 2 s without something new moving or appearing.
- Element sizes (`size`, `label_size`, `body_size`) must be ≥44 px. The marker window titles (46) are fine. Tags, code-window filenames and the watermark are decorative and smaller.
- Every element must sit inside x 24-1056 and y 350-1410. That keeps the top 220 px clear, leaves room for the title, and keeps everything above the captions and the bottom 380 px.
- Code lines must fit their window, and window body text must fit its window.

## Commands

```bash
cd /workspace/social-media-assets
S=tools/motion_specs/<slug>.json
python3 tools/render_motion_reel.py $S -o /tmp/x.mp4 --lint-only            # timings + lint, ~3 s
python3 tools/render_motion_reel.py $S -o /tmp/x.mp4 --preview 0,4,10,18,26  # PNG frames
python3 tools/render_motion_reel.py $S -o posts/<date>-<slug>.mp4 --cover posts/<date>-<slug>-cover.jpg
python3 tools/render_motion_reel.py $S --variant facebook \
        -o posts/<date>-<slug>-facebook.mp4 --cover posts/<date>-<slug>-facebook-cover.jpg
```

Other flags: `--strict` (fail on lint), `--no-sfx`, `--sfx-db -22`, `--no-music`, `--music FILE`, `--no-captions`, `--voice/--rate/--pitch`, `--workers N`.
A full render takes about 30 s on 8 cores. The first run creates `tools/.venv` (edge-tts).

## Spec format (JSON, or YAML with pyyaml)

```jsonc
{
  "voice": {"name": "en-IN-NeerjaExpressiveNeural", "rate": "+5%", "pitch": "+0Hz"},
  "captions": {"enabled": true, "keywords": ["round trip", "JOIN"], "keyword_color": "yellow", "max_chars": 30},
  "cover_at": "why@timing+0.7",          // time anchor for --cover (pick the most dramatic frame)
  "sfx_db": -18,                          // optional SFX level
  "tail": 0.35,                           // seconds after the last word
  "chapters": [                           // first one is on screen from frame 0
    {"id": "hook", "text": "WHY IS MY API {{SLOW}}?", "color": "red"},
    {"id": "bug",  "at": "bug:start", "text": "THE {{N+1}} QUERY BUG", "color": "yellow"}
  ],
  "voiceover": [ {"id": "hook", "text": "..."}, ..., {"id": "follow", "text": "Follow K four coding."} ],
  "elements": [ ... ],
  "timeline": [ ... ],
  "series": {"label": "SQL Bugs", "number": 4, "color": "yellow"},   // optional: tag pill + "FOLLOW FOR #5" end card; optional "y" (178), "size" (34)
  "end_card": {"segment": "follow", "line1": "FOLLOW", "line2": "{{@K4CODING}}", "line3": "one concept, one diagram, daily"},
  "variants": {"facebook": {"chapters": {"hook": {"text": "{{101 QUERIES}} PER PAGE?", "color": "red"}}, "cover_at": "bug@queries+0.8"}}
}
```

A voiceover segment can also take `"caption": "override text"` or `"caption": false`.

### Time anchors (`at`, `cover_at`)
- `12.4` means absolute seconds.
- `"+0.5"` means relative to the previous timeline event.
- `"bug:start"` and `"why:end"` mean a segment's start or end.
- `"fix@JOIN"` means the moment the first word matching `JOIN` is spoken in segment `fix`. Matching ignores case and punctuation, falls back to a substring match, and warns if the word isn't found.
- `"fix@JOIN-0.1"` and `"why@timing+0.7"` add an offset.

### Element types (all positions are centre x/y in 1080x1920 px)
| type | keys |
|---|---|
| `window` | `w h title icon tag status body body_size body_font hl border header_h title_size`. A marker-font title sits in the header with the Mac dots. `tag` is the small grey label on the right with 2 status dots (colour target `id:status`). `body` is a centred mono line, with `{{x}}` in `hl` colour (default purple). Colour target `id` sets the border (`panel` means none). Swap target `id` sets the body. |
| `code` | `w lines[] size(44) min_lines title hl border(purple) autotype(true)`. Mac dots, mono lines, `{{kw}}` in `hl` colour (target `id:hl`). It types itself in when shown. `swap` with `lines` retypes it. |
| `bar` | `w h(52) value(0-1) threshold(0.7) label label_right ok_color bad_color marker(true)`. It fills cyan and blends to red past the threshold. Animate it with `set`. |
| `counter` | `value format("{n} queries") format_one font size align color upper`. Animate it with `set` (it counts up or down). |
| `icon` | `kind` (user, laptop, server, database, store, globe, lock, cpu), `size(110) color(white; use purple for devices) label label_color label_size` |
| `text` | `text size font(sans/mono/marker) weight align color hl upper(true)` |
| `line` | `from to` (anchors) `color(line) width dash:[on,off] arrow`. Lines are drawn under everything else, and data dots travel along them. |
| `badge` | `kind: stamp` (`text`, e.g. TIMEOUT / DENIED), or `kind: x` / `kind: check` (`r`, optional `label`), plus `color` |

Common keys: `id`, `start_visible: true` (on screen at frame 0). Anchors are written `"id"`, `"id.top"`, `"id.bottom-240"` (x offset) or `"id.right+0,-20"` (x,y offset), or given as `[x, y]`.

### Timeline actions (`do`)
| do | keys |
|---|---|
| `show` / `hide` | `target` (id or list), `anim`: `pop` (scale with overshoot, the default) / `fade` / `slide_up` / `slide_down` / `slide_left` / `slide_right` / `draw` (lines grow), `dur`, `stagger`, `type_dur` (code) |
| `send` | Data dots. Use `path` (line id or list, cycled) with optional `reverse`, or `from`/`to` (anchors or lists) with optional `via`. Other keys: `count interval dur color r label pulse` (auto pulses the arrival element) |
| `set` | `target value dur`, for a bar or counter |
| `swap` | `target text` (window body, text), or `target lines` (code, retypes; `type_dur`, `retype`) |
| `color` | `target` (`id`, `id:status`, `id:hl`, `id:label`) `color dur` |
| `pulse` / `shake` / `type` | `target` (`dur`) |
| `sfx` | `name` (whoosh, pop, tick, alert, ding), `gain` |

Every action also takes `"sfx": "none"` to mute its automatic sound, or a name to add one, e.g. `"sfx": "alert"` on the overload colour change.

## Authoring recipe (one concept, 25-40 s)
1. Write 60-90 words. The first 5 words state the pain or question. Segments are hook / bug / why / fix / `Follow K four coding.`
2. Write 4 chapter titles of 2-4 words each, one highlight per title. Use red for the bug or why, yellow for the term, and purple or orange for the fix. Keep each under ~16 characters so it stays at or above 80 px.
3. Put the main system on frame 0 (`start_visible`), e.g. a window over another window with 3-4 lines between them, and `send` cyan dots at 0.15 s.
4. Tie one event to a spoken word every 1-2 s. The bug turns things red (bar `set` over threshold, `color` borders/status red, red dots, a stamp, `shake`). The fix swaps the code, brings the bar back green, and pops a ✓ with `"sfx": "ding"`.
5. Run `--lint-only` and then `--preview`, read the PNGs, render, then check `ffprobe` and `volumedetect`.

Full example: `tools/motion_specs/n-plus-one-queries.json`.
