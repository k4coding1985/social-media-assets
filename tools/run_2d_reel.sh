#!/bin/bash
# Render the Instagram + Facebook variants of a 2D explainer Reel spec, then QA both.
#   tools/run_2d_reel.sh path/to/spec.json OUT_DIR
set -euo pipefail
SPEC="$1"; OUT="$2"; HERE="$(cd "$(dirname "$0")" && pwd)"
CB="${CB_PYTHON:-/workspace/ingress/work/tts2/cbvenv/bin/python}"   # venv with chatterbox-tts + torch + pillow + soundfile
QA_PY="${QA_PYTHON:-python3}"                                       # python with faster-whisper
START=$(date +%s)
"$CB" "$HERE/render_2d_reel.py" "$SPEC" --out-dir "$OUT" --preview 2>&1 | grep '^\[2d\]\|^{' 
if "$CB" -c "import json,sys; sys.exit(0 if 'facebook' in json.load(open('$SPEC')).get('variants',{}) else 1)"; then
  "$CB" "$HERE/render_2d_reel.py" "$SPEC" --out-dir "$OUT" --variant facebook --preview 2>&1 | grep '^\[2d\]\|^{'
fi
SLUG=$("$CB" -c "import json; print(json.load(open('$SPEC')).get('slug','reel'))")
"$QA_PY" "$HERE/qa_2d_reel.py" "$OUT/$SLUG.mp4" --spec "$SPEC" | grep -v '"heard"'
[ -f "$OUT/$SLUG-facebook.mp4" ] && "$QA_PY" "$HERE/qa_2d_reel.py" "$OUT/$SLUG-facebook.mp4" --spec "$SPEC" --variant facebook | grep -v '"heard"'
echo "ALL OK in $(( $(date +%s) - START ))s"
