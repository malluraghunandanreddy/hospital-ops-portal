#!/bin/sh
# Mac: start the DEMO with new made-up patients dated today (for showing the system).
# Deletes only the demo copy's data folder. Never use this on the hospital laptop.
cd "$(dirname "$0")" || exit 1
if [ -f data/sunrise.db ] && ! python3 -c "import sqlite3,sys; c=sqlite3.connect('data/sunrise.db'); r=c.execute(\"select value from settings where key='demo'\").fetchone(); sys.exit(0 if r and r[0]=='1' else 1)"; then
  echo "This copy holds real hospital data. Not deleting it."
  exit 1
fi
rm -rf data
exec python3 app/server.py
