#!/usr/bin/env bash
# AgentOps — start backend and open frontend

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$SCRIPT_DIR/backend"

echo "==> Installing dependencies..."
pip install -r "$BACKEND/requirements.txt" -q --break-system-packages

echo "==> Seeding database..."
cd "$BACKEND"
python seed.py

echo ""
echo "==> Starting AgentOps backend at http://localhost:8000"
echo "    API docs: http://localhost:8000/docs"
echo "    Frontend: open agentops/frontend/index.html in your browser"
echo ""
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
