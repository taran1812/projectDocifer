#!/bin/bash
set -e

# Install uv if not present
if ! command -v uv &>/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

# Backend deps
cd /workspace
uv sync --project backend

# Frontend deps
cd /workspace/frontend
npm ci

echo ""
echo "Setup complete."
echo "Set OPENAI_API_KEY before starting the backend:"
echo "  export OPENAI_API_KEY=sk-..."
echo ""
echo "Start backend:  cd /workspace && uv run --project backend uvicorn docifer_backend.main:app --reload --host 0.0.0.0 --port 8000"
echo "Start frontend: cd /workspace/frontend && npm run dev -- --host"
