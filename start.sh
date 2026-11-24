#!/bin/sh
cd "$(dirname "$0")/backend" && python3 -m venv .venv 2>/dev/null; . .venv/bin/activate && pip install -q -r requirements.txt
(sleep 2; python3 -m webbrowser http://127.0.0.1:8000) &
uvicorn main:app --port 8000
