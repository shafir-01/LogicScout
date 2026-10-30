#!/bin/sh
set -e
export PORT="${PORT:-8787}"
exec python scripts/serve.py
