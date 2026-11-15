# Viral Reel template (`render_viral_reel.py`)

From **15 Nov 2026** this is the standard for daily Instagram and Facebook
Reels. It supersedes the motion-graphics template (`MOTION_REEL_TEMPLATE.md`,
`render_motion_reel.py`) for those posts. The viral tool still *reuses* the
motion renderer for the canvas, series tag, Neerja voice, SFX, captions and
`add_voiceover.py` mix, then applies a hook-style end fade so the last frame
matches the first and the Reel loops.

Full example: `tools/examples/viral-git-branch-rescue.json`
(Git Mistakes #3, “deleted a branch / git reflog”).

## 7 beats (25–35 seconds)

| Beat | Time | What the viewer sees |
|---|---|---|
| 1. Hook | 0–1.5 s | The bug or bad result is already on screen. Big marker title, a bold claim, no intro or logo. Series tag is visible from frame 1. |
| 2. Pattern break | 1.5–3 s | A red ✕ badge (drawn as a vector X — fonts have no emoji) plus a whoosh/alert, and the line “Most devs … here”. This is what holds people past 3 seconds. |
| 3. Problem | 3–10 s | The broken code in one window, **at most 3 lines**, bad line highlighted **red**. Voiceover explains why it breaks in one sentence. |
| 4. Fix | 10–20 s | Fixed code, change highlighted in green/cyan, a ✓ badge labelled **Do this instead**. |
| 5. Payoff | 20–25 s | A big number or result (“BACK IN 5 SECONDS”, “101 queries become 1”). Numbers get saves. |
| 6. Comment bait | 25–28 s | On-screen question: “Ever lost a branch? YES or NO”. No emoji (the fonts cannot render them). Simple choices get comments. |
| 7. End card | last ~0.7–1.5 s | `FOLLOW FOR #N+1` and `@K4CODING` sit under the hook visual. The last frame matches the first (series tag, hook title, opening window) so a loop looks seamless. |

Change something on screen every **1–1.5 seconds** (zoom, highlight, new line, pop). Big text stays under **6 words per line**. Canvas elements stay out of the **top 15%** and **bottom 25%** (chapter title and series tag sit in the top band, captions and the watermark in the bottom band — the same layout as the motion engine).

## Look

Same canvas as the motion template: flat `#0B0B0C` background, Permanent Marker chapter titles, dark UI windows with Mac dots, JetBrains Mono code, Inter captions, `@k4coding` watermark. Colour meaning is unchanged (`red` for the bug, `cyan`/`green` for the fix, `yellow` for terms, `purple`/`orange` for the tool).

The series tag pill (for example `GIT MISTAKES #3`) is on screen from the first frame, set with `"series"`. The end card becomes `FOLLOW FOR #<N+1>` automatically when `"series"` is set.

## Voiceover script (55–90 words, Neerja)

Voice: `en-IN-NeerjaExpressiveNeural`, rate `+5%`, pitch `+0Hz`, over the quiet ambient pad (`add_voiceover.py` ducks the music about 16 dB under the voice).

Write 55–90 words in this pattern (numbers spelled for TTS, “K four coding”):

1. Hook question — the pain in one line: “You deleted a branch and lost a week of work?”
2. “Most devs panic here.” (pattern break)
3. One-sentence why, then the fix, then the payoff number.
4. “Comment yes or no.”
5. “Follow K four coding for part \<N+1\>.”

Example (Git Mistakes #3, 58 words):

> You deleted a branch and lost a week of work? Most devs panic here. But Git never forgets. Run git reflog, find your last commit, then git branch rescue with that hash. Your work is back in five seconds. Have you ever lost a branch? Comment yes or no. Follow K four coding for part four.

Segments: `hook`, `bug` (pattern break), `why` (problem), `fix` (fix + payoff can share this segment), `bait`, `follow`.

## Caption pattern (the post, not the burned-in subtitles)

1. One-line lesson.
2. The same YES / NO question.
3. `Save this for later.`
4. 3–5 hashtags.
5. `Follow @k4coding`

Example:

```
You deleted a branch and thought a week of work was gone. Git never forgets: run git reflog, find the commit, then git branch rescue with that hash. Back in five seconds.

Ever lost a branch? Comment YES or NO.

Save this for later.

#git #gitreflog #gittips #learninpublic

Follow @k4coding
```

Burned-in captions stay word-synced (Inter 40 px, keywords tinted). They turn off for the end-card / hook-loop fade.

## Audio gate

After the mix, the tool checks (and fails if either check does not pass, unless you pass `--skip-audio-gate`):

1. `ffprobe` must report an **audio stream**.
2. `ffmpeg -af volumedetect` **mean_volume** must be **greater than -35 dB**.

The mix itself is still normalized to about -14 LUFS by `add_voiceover.py`.

## Commands

```bash
cd /workspace/social-media-assets
S=tools/examples/viral-git-branch-rescue.json
python3 tools/render_viral_reel.py $S -o /tmp/x.mp4 --lint-only
python3 tools/render_viral_reel.py $S -o /tmp/x.mp4 --preview 0.5,12,25.8
python3 tools/render_viral_reel.py $S -o posts/<date>-<slug>.mp4 --cover posts/<date>-<slug>-cover.jpg
python3 tools/render_viral_reel.py $S --variant facebook \
        -o posts/<date>-<slug>-facebook.mp4 --cover posts/<date>-<slug>-facebook-cover.jpg
```

Other flags match the motion renderer: `--strict`, `--no-sfx`, `--sfx-db`, `--no-music`, `--music FILE`, `--no-captions`, `--voice/--rate/--pitch`, `--workers N`. Viral-specific: `--fade 0.7` (hook-style end fade, also settable as `"end_card": {"fade": 0.7}`), `--skip-audio-gate`.

A full render takes about 30 s on 8 cores. The first run creates `tools/.venv` (edge-tts).

## Spec fields

The JSON/YAML spec is the motion-reel format, authored against the 7 beats. Important fields:

```jsonc
{
  "slug": "viral-sample-git-branch-rescue",
  "series": {"label": "Git Mistakes", "number": 3, "color": "orange"},
  "voice": {"name": "en-IN-NeerjaExpressiveNeural", "rate": "+5%", "pitch": "+0Hz"},
  "captions": {"enabled": true, "keywords": ["deleted", "branch", "reflog"], "keyword_color": "yellow", "max_chars": 30},
  "cover_at": "fix@rescue+0.4",
  "tail": 2.5,
  "chapters": [
    {"id": "hook",   "text": "DELETED A {{BRANCH}}?", "color": "red"},
    {"id": "bug",    "at": "bug:start",  "text": "MOST DEVS {{PANIC}}", "color": "yellow"},
    {"id": "why",    "at": "why:start",  "text": "{{GONE}} FROM LOG", "color": "red"},
    {"id": "fix",    "at": "fix:start",  "text": "RUN {{REFLOG}}", "color": "purple"},
    {"id": "payoff", "at": "fix@back",   "text": "BACK IN {{5 SECONDS}}", "color": "cyan"},
    {"id": "bait",   "at": "bait:start", "text": "YES OR {{NO}}?", "color": "yellow"}
  ],
  "voiceover": [ {"id": "hook", "text": "..."}, {"id": "bug", "text": "Most devs panic here."}, "...",
                 {"id": "bait", "text": "... Comment yes or no."},
                 {"id": "follow", "text": "Follow K four coding for part four."} ],
  "elements": [ /* hook window/code start_visible; red X; check + 'Do this instead'; payoff; YES/NO boxes */ ],
  "timeline": [ /* motion every 1-1.5 s, tied to spoken words */ ],
  "end_card": {
    "segment": "follow",
    "line1": "FOLLOW FOR #4",
    "line2": "{{@K4CODING}}",
    "line3": "Git Mistakes, one fix at a time",
    "fade": 0.7
  }
}
```

`end_card.line3` is used on the brief full-screen end card and is dropped on the hook-style loop frame (so the opening window can sit in that space). Time anchors, element types and timeline actions are documented in `MOTION_REEL_TEMPLATE.md`.

Window body highlights (`{{word}}`, colour target `id:hl`) now follow `color` events. Narrow-window titles are kept clear of the Mac traffic-light dots; wide windows are unchanged.

## Authoring recipe

1. Pick the next episode in a series (SQL Bugs, Git Mistakes, JS Gotchas, Backend Basics, or a new one). Write the 55–90 word script in the pattern above.
2. Write six short chapter titles (hook / pattern break / problem / fix / payoff / bait), one highlight each, under 6 words a line. No emoji.
3. Put the broken result on frame 0 (`start_visible`). Open with a pulse/shake by 0.3 s. Pattern-break with a red X and “Most devs … here”. Keep the problem window to 3 lines, highlight the bad line red, then swap to the fix with a ✓ “Do this instead” and a payoff number. Close with a YES / NO question.
4. Run `--lint-only`, then `--preview 0.5,3,8,14,22` plus a time near the end, read the PNGs for safe zones and legibility, render, and confirm the audio gate in the log.
