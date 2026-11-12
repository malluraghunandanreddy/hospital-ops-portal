#!/bin/sh
# Mac / Linux: double-click (Mac) or run ./start.command
cd "$(dirname "$0")" || exit 1
exec python3 app/server.py
