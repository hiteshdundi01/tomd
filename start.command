#!/usr/bin/env bash
# TOMD — Convert Anything to Markdown (macOS/Linux launcher)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "  ============================================"
echo "   TOMD — Convert Anything to Markdown"
echo "  ============================================"
echo ""

# Activate virtual environment
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
else
    echo "  ❌  Virtual environment not found."
    echo "  Run:  uv venv .venv && uv pip install -e ."
    exit 1
fi

echo "  Starting server at http://127.0.0.1:8000"
echo "  Press Ctrl+C to stop."
echo ""

# Open browser after a short delay (macOS: open, Linux: xdg-open)
(sleep 2 && open "http://127.0.0.1:8000" 2>/dev/null || xdg-open "http://127.0.0.1:8000" 2>/dev/null) &

# Start the server
python -m tomd.web.app
