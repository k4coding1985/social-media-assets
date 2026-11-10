# Reel voiceover tool

Adds an AI voiceover and a quiet CC0 music bed to a silent 9:16 MP4.
Output is Instagram-Reels-valid (H.264 + AAC, loudness about -14 LUFS).

Default TTS voice: `en-IN-PrabhatNeural` (edge-tts). Fallback chain:
edge-tts → gTTS → piper → espeak-ng. Music is on by default; pass
`--no-music` for speech only. License notes are in `MUSIC_LICENSES.md`.

## Setup

ffmpeg and ffprobe must be on `PATH`. The script creates `tools/.venv`
and installs `requirements.txt` on first run if needed.

```bash
python3 -m venv tools/.venv
tools/.venv/bin/pip install -r tools/requirements.txt
```

## Usage

```bash
tools/.venv/bin/python tools/add_voiceover.py \
  -i posts/YYYY-MM-DD-HHMM-topic.mp4 \
  -o /tmp/reel-with-vo.mp4 \
  -t "Your 10 to 15 second voiceover script."
```

Speech only:

```bash
tools/.venv/bin/python tools/add_voiceover.py \
  -i in.mp4 -o out.mp4 --text-file script.txt --no-music
```

Optional flags: `--voice en-US-GuyNeural`, `--rate +5%`, `--music path/to/bed.mp3`.
