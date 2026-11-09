#!/bin/bash
# Koç PDF Pro'yu başlatır (zaten çalışıyorsa yalnızca tarayıcıda açar).
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT=5055
URL="http://127.0.0.1:$PORT/"
if curl -s -o /dev/null -m 2 "${URL}api/status"; then
  open "$URL"
  exit 0
fi
if [ ! -x "$DIR/.venv/bin/python" ]; then
  echo "Python ortamı kuruluyor…"
  python3 -m venv "$DIR/.venv" && "$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"
fi
mkdir -p "$HOME/Library/Logs"
cd "$DIR"
nohup "$DIR/.venv/bin/python" -W ignore "$DIR/app.py" >> "$HOME/Library/Logs/PDFStudyo.log" 2>&1 &
