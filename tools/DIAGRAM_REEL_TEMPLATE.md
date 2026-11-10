# Diagram Reel template (`render_diagram_reel.py`)

Renders a 1080x1920 Reel in the "dotted schematic" style: pure black
background with slow drifting particles, dotted nodes (spheres, circles,
rounded boxes, tables, database cylinders, phones), glowing white data
packets moving along dotted paths, JetBrains Mono everywhere, the key
token in bright blue `#3B82F6`, selected elements with a dark-blue fill and
blue dotted outline. Title on frame 0, `| ` code lines near the top,
the diagram in the middle, word-synced captions above the bottom 380 px,
a small `@k4coding` watermark top-right and a <=1.5 s black end card.

Audio: Neerja (`en-IN-NeerjaExpressiveNeural`, `+5%`, `+0Hz`) via
edge-tts plus the quiet CC0 music bed, mixed by `add_voiceover.py`
(`--speech-file`, so the audio is exactly the one the timings came from).

## Run

```bash
python3 tools/render_diagram_reel.py tools/diagram_specs/<topic>.json \
  -o posts/YYYY-MM-DD-0900-<topic>.mp4 \
  --cover posts/YYYY-MM-DD-0900-<topic>-cover.jpg
```

Options: `--preview 0,2,10,20` (write PNG frames next to `-o` and stop,
takes ~10 s; use it to check layout before the full render), `--voice`,
`--rate`, `--pitch` (override the spec), `--no-music` (don't; the user
wants music), `--strict` (fail on lint warnings), `--workers N`.
A full 30 s render takes about 30 s on the box. Needs system `python3` with
Pillow + numpy, ffmpeg/ffprobe and the `tools/.venv` that
`add_voiceover.py` creates (edge-tts).

The renderer prints lint warnings for: script outside 50-80 words,
duration outside 20-35 s, end card > 1.5 s, title < 64 px, text < 44 px,
anything outside the safe area (y 220 to 1450, x 20 to 1060), row text
or code lines too wide, the first animation after 1.0 s, and any stretch
longer than 1.5 s where nothing new moves. Fix every warning before posting.

## How timing works

The whole script is synthesized once with word boundaries. Each
voiceover segment gets a start/end time, and every timeline event's `at`
is resolved against those times, so scenes follow the narration even if
the voice speeds up or slows down. Video length = last spoken word +
`tail` (default 0.3 s); trailing TTS silence is trimmed.

`at` forms:

| `at` | meaning |
|---|---|
| `1.2` | absolute seconds |
| `"bug"` / `"bug:start"` | start of segment `bug` |
| `"bug:end"` | end of segment `bug` |
| `"bug@twice"` | when the first word "twice" in segment `bug` starts (case/punctuation ignored) |
| `"bug@twice+0.3"`, `"fix-0.2"` | either of the above plus/minus seconds |
| `"+0.7"` | 0.7 s after the previous event's `at` |

## Spec reference (JSON, or YAML if PyYAML is installed)

Top level:

| key | type | notes |
|---|---|---|
| `title` | string | top-center, frame 0, Bold. `{{word}}` is blue. Keep <= 24 chars at 66 px. `\n` for 2 lines |
| `title_size` | int | default 66 (min 64) |
| `voice` | object | `name`, `rate`, `pitch` (defaults Neerja, `+5%`, `+0Hz`) |
| `voiceover` | list | segments `{id, text, caption?}`. 50-80 words total, the first 5 words state the pain, last segment `"Follow K four coding."` with `"caption": false` |
| `captions` | object | `keywords` (words/phrases shown blue when spoken), `max_chars` (default 28 per caption line) |
| `nodes` | list | diagram elements (below) |
| `paths` | list | `{id, points:[anchor,...], spacing?}` dotted gray polylines |
| `code` | list | `{id, x, y, text, size?}` code lines; `| ` is added automatically; `{{...}}` is blue |
| `timeline` | list | events (below) |
| `end_card` | object | `segment` (the follow segment id), `offset` (default 0.25 s after it starts), `line1`, `line2`, `line3` |
| `cover_at` | `at` value | frame used for `--cover` (no captions). Pick the moment the bug is fully visible |
| `tail`, `seed`, `particles`, `watermark` | | optional tuning (`0.3`, `7`, `90`, `"@k4coding"`) |

Node types (all `x`,`y` are the center in px; all accept `label`,
`label_pos` (`top`/`bottom`/`left`/`right`), `label_size`, `start_visible`):

| type | extra keys | notes |
|---|---|---|
| `table` | `w`, `rows`, `row_h` 84, `row_size` 44, `gap` 22, `pad` 26 | dotted container with dotted pill rows. Height is computed. Rows are addressable as `id.r0`, `id.r1`... A row may be `{"text": ..., "hidden": true}` to appear later. Label sits above-left |
| `box` | `w`, `h`, `text`, `radius` | dotted rounded rect (queue, service, step) |
| `sphere` | `r`, `dots`, `spin` | rotating dotted 3D sphere (producer, client, server) |
| `circle` | `r`, `text` | flat dotted circle (consumer X/Y/Z) |
| `cylinder` | `w`, `h` | dotted database |
| `phone` | `w`, `h` | dotted phone/client |
| `text` | `text`, `size`, `align`, `color`, `weight` | free label |

Anchors (for `paths`, `from`, `to`, `via`): `"id"` (center),
`"id.left|right|top|bottom"`, `"table.r1"`, `"table.r1.right"`, or `[x, y]`.

Timeline events (`target` may be a string or a list):

| `do` | keys | effect |
|---|---|---|
| `show` / `hide` | `target`, `dur` 0.5, `stagger` | fade + scale in/out (tables bring their non-hidden rows) |
| `highlight` / `unhighlight` | `target`, `dur` | dark-blue fill + blue dotted outline |
| `swap` | `target`, `text` | crossfade text of a row, box, code line, text node, or a label (`"id:label"`) |
| `pulse` | `target` | quick scale bump (0.5 s) |
| `move` | `from`, `to` (one or a list), or `path` (path id or list), `via`, `dur` 1.2, `keep`, `label`, `packet`, `stagger` | glowing packet(s) with a short trail; one `from` and several `to` splits the packet |

## Authoring guidance

- Story in 4 segments + follow: `hook` (pain in the first 5 words, bug
  visible by ~1.5-2 s), `setup` (name the pieces), `bug` (show it happening),
  `fix` (show the fix in the same diagram), `follow`.
- Put the main nodes on screen at frame 0 with `start_visible`; start the
  first `move` at 0.2 s.
- One motion every 1-1.5 s: alternate `move`, `highlight`, `swap`, `pulse`
  anchored on spoken words (`seg@word`). Run `--preview` and read the lint.
- Layout bands: watermark y~226, title y 262, code lines y 370/428/486,
  diagram y 560-1450, captions y 1470. Two tables side by side: x 270 and
  810 with `w` 400; a result table under them at x 540, `w` 640.
- Text >= 44 px. Code lines <= 34 chars, row text <= ~12 chars in a 400 px
  table, labels <= 16 chars.
- Topics that suit a diagram: anything where data moves or gets
  matched: SQL JOINs/duplicates, NULL in JOIN/NOT IN, GROUP BY vs WHERE/
  HAVING, indexes (scan vs seek), transactions/isolation, N+1 queries,
  Git (commits as dotted nodes, branches as paths: merge vs rebase, reset vs
  revert, detached HEAD, cherry-pick), JS event loop/promises/async ordering,
  closures in loops, Python mutable default args, Linux pipes/exit codes.
  Avoid topics that are only a syntax list.

## Full example spec

`tools/diagram_specs/sql-join-duplicates.json` ("JOIN duplicated my rows",
renders to ~30 s):

```json
{
 "title": "{{JOIN}} duplicated my rows",
 "title_size": 66,
 "voice": {
  "name": "en-IN-NeerjaExpressiveNeural",
  "rate": "+5%",
  "pitch": "+0Hz"
 },
 "voiceover": [
  {
   "id": "hook",
   "text": "Your JOIN just duplicated customers. One row went in, two came out."
  },
  {
   "id": "setup",
   "text": "Asha is one row in customers. She has two rows in orders."
  },
  {
   "id": "bug",
   "text": "The join matches her row to every order, so Asha appears twice. Count customers now, and you get two, not one."
  },
  {
   "id": "fix",
   "text": "The fix: group orders by customer first, so each customer has one row. Then join."
  },
  {
   "id": "follow",
   "text": "Follow K four coding.",
   "caption": false
  }
 ],
 "captions": {
  "keywords": [
   "JOIN",
   "duplicated",
   "twice",
   "two",
   "group orders",
   "one row",
   "join"
  ],
  "max_chars": 24
 },
 "cover_at": "bug@two",
 "end_card": {
  "segment": "follow",
  "line1": "Follow",
  "line2": "{{@k4coding}}",
  "line3": "one bug, one diagram, daily"
 },
 "nodes": [
  {
   "id": "customers",
   "type": "table",
   "x": 270,
   "y": 774,
   "w": 400,
   "label": "customers",
   "rows": [
    "1 Asha",
    "2 Ravi"
   ],
   "start_visible": true,
   "row_h": 88,
   "row_size": 46,
   "gap": 20,
   "pad": 26
  },
  {
   "id": "orders",
   "type": "table",
   "x": 810,
   "y": 828,
   "w": 400,
   "label": "orders",
   "rows": [
    "#101 cid=1",
    "#102 cid=1",
    "#103 cid=2"
   ],
   "start_visible": true,
   "row_h": 88,
   "row_size": 46,
   "gap": 20,
   "pad": 26
  },
  {
   "id": "result",
   "type": "table",
   "x": 540,
   "y": 1268,
   "w": 640,
   "label": "result",
   "rows": [
    {
     "text": "Asha #101",
     "hidden": true
    },
    {
     "text": "Asha #102",
     "hidden": true
    },
    {
     "text": "Ravi #103",
     "hidden": true
    }
   ],
   "row_h": 88,
   "row_size": 46,
   "gap": 20,
   "pad": 26
  }
 ],
 "paths": [
  {
   "id": "p_a1",
   "points": [
    "customers.r0.right",
    "orders.r0.left"
   ]
  },
  {
   "id": "p_a2",
   "points": [
    "customers.r0.right",
    "orders.r1.left"
   ]
  }
 ],
 "code": [
  {
   "id": "l1",
   "x": 60,
   "y": 370,
   "text": "SELECT c.name FROM customers c",
   "start_visible": true
  },
  {
   "id": "l2",
   "x": 60,
   "y": 428,
   "text": "JOIN orders o ON {{o.cid = c.id}}",
   "start_visible": true
  },
  {
   "id": "l3",
   "x": 60,
   "y": 486,
   "text": "  FROM orders {{GROUP BY cid}}) o"
  }
 ],
 "timeline": [
  {
   "at": 0.15,
   "do": "show",
   "target": [
    "p_a1",
    "p_a2"
   ],
   "dur": 0.4
  },
  {
   "at": 0.2,
   "do": "move",
   "from": "customers.r0.right",
   "to": [
    "orders.r0.left",
    "orders.r1.left"
   ],
   "dur": 0.8
  },
  {
   "at": 0.9,
   "do": "show",
   "target": "result",
   "dur": 0.4
  },
  {
   "at": 1.0,
   "do": "move",
   "from": [
    "orders.r0.left",
    "orders.r1.left"
   ],
   "to": [
    "result.r0.top",
    "result.r1.top"
   ],
   "via": [
    [
     540,
     1040
    ]
   ],
   "dur": 0.8
  },
  {
   "at": 1.7,
   "do": "show",
   "target": [
    "result.r0",
    "result.r1"
   ],
   "dur": 0.35
  },
  {
   "at": 1.75,
   "do": "highlight",
   "target": [
    "result.r0",
    "result.r1"
   ],
   "dur": 0.3
  },
  {
   "at": "hook@One",
   "do": "pulse",
   "target": "customers.r0"
  },
  {
   "at": "hook@two",
   "do": "pulse",
   "target": [
    "result.r0",
    "result.r1"
   ]
  },
  {
   "at": "setup",
   "do": "unhighlight",
   "target": [
    "result.r0",
    "result.r1"
   ]
  },
  {
   "at": "setup",
   "do": "highlight",
   "target": "customers.r0"
  },
  {
   "at": "setup@customers",
   "do": "pulse",
   "target": "customers.r0"
  },
  {
   "at": "setup@She",
   "do": "move",
   "from": "customers.r0.right",
   "to": [
    "orders.r0.left",
    "orders.r1.left"
   ],
   "dur": 0.9
  },
  {
   "at": "setup@two",
   "do": "highlight",
   "target": [
    "orders.r0",
    "orders.r1"
   ]
  },
  {
   "at": "setup@orders",
   "do": "pulse",
   "target": [
    "orders.r0",
    "orders.r1"
   ]
  },
  {
   "at": "bug",
   "do": "move",
   "from": "customers.r0.right",
   "to": [
    "orders.r0.left",
    "orders.r1.left"
   ],
   "dur": 1.0
  },
  {
   "at": "bug@every",
   "do": "move",
   "from": [
    "orders.r0.left",
    "orders.r1.left"
   ],
   "to": [
    "result.r0.top",
    "result.r1.top"
   ],
   "via": [
    [
     540,
     1040
    ]
   ],
   "dur": 1.0
  },
  {
   "at": "bug@twice",
   "do": "highlight",
   "target": [
    "result.r0",
    "result.r1"
   ]
  },
  {
   "at": "bug@twice",
   "do": "pulse",
   "target": [
    "result.r0",
    "result.r1"
   ]
  },
  {
   "at": "bug@twice+0.3",
   "do": "move",
   "from": "customers.r1.right",
   "to": "orders.r2.left",
   "dur": 0.7
  },
  {
   "at": "+0.7",
   "do": "show",
   "target": "result.r2",
   "dur": 0.4
  },
  {
   "at": "bug@Count",
   "do": "swap",
   "target": "result:label",
   "text": "COUNT(Asha) = {{2}}"
  },
  {
   "at": "bug@now",
   "do": "pulse",
   "target": "result.r0"
  },
  {
   "at": "bug@two",
   "do": "pulse",
   "target": [
    "result.r0",
    "result.r1"
   ]
  },
  {
   "at": "bug@not",
   "do": "pulse",
   "target": "result"
  },
  {
   "at": "fix",
   "do": "unhighlight",
   "target": [
    "result.r0",
    "result.r1",
    "customers.r0",
    "orders.r0",
    "orders.r1"
   ]
  },
  {
   "at": "fix",
   "do": "swap",
   "target": "l2",
   "text": "JOIN (SELECT cid, COUNT(*) n"
  },
  {
   "at": "fix+0.3",
   "do": "show",
   "target": "l3"
  },
  {
   "at": "fix@group",
   "do": "highlight",
   "target": "orders"
  },
  {
   "at": "fix@group",
   "do": "swap",
   "target": "orders:label",
   "text": "{{GROUP BY}} cid"
  },
  {
   "at": "fix@customer",
   "do": "swap",
   "target": "orders.r0",
   "text": "cid=1 n={{2}}"
  },
  {
   "at": "fix@customer",
   "do": "swap",
   "target": "orders.r1",
   "text": "cid=2 n=1"
  },
  {
   "at": "fix@customer",
   "do": "hide",
   "target": "orders.r2",
   "dur": 0.4
  },
  {
   "at": "fix@first",
   "do": "pulse",
   "target": [
    "orders.r0",
    "orders.r1"
   ]
  },
  {
   "at": "fix@so",
   "do": "move",
   "from": "customers.r1.right",
   "to": "orders.r1.left",
   "dur": 0.8
  },
  {
   "at": "fix@one",
   "do": "hide",
   "target": "result.r2",
   "dur": 0.4
  },
  {
   "at": "fix@one",
   "do": "swap",
   "target": "result.r0",
   "text": "Asha n=2"
  },
  {
   "at": "fix@one",
   "do": "swap",
   "target": "result.r1",
   "text": "Ravi n=1"
  },
  {
   "at": "fix@one+0.2",
   "do": "move",
   "from": "customers.r0.right",
   "to": "orders.r0.left",
   "dur": 0.6
  },
  {
   "at": "+0.6",
   "do": "move",
   "from": "orders.r0.left",
   "to": "result.r0.top",
   "via": [
    [
     540,
     1040
    ]
   ],
   "dur": 0.6
  },
  {
   "at": "fix@Then",
   "do": "highlight",
   "target": "result.r0"
  },
  {
   "at": "fix@Then",
   "do": "swap",
   "target": "result:label",
   "text": "COUNT(Asha) = {{1}}"
  }
 ]
}
```
