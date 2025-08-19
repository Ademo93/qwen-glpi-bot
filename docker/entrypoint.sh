#!/usr/bin/env bash
set -euo pipefail

# Attendre Ollama
echo "[entrypoint] Waiting for ollama at ${OLLAMA_BASE_URL:-http://ollama:11434} ..."
for i in {1..60}; do
  if curl -sSf "${OLLAMA_BASE_URL:-http://ollama:11434}/api/tags" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

# Tirer le modèle si besoin (best-effort)
echo "[entrypoint] Ensuring model ${MODEL_NAME:-qwen2.5:1.5b-instruct} is present..."
curl -sS -X POST "${OLLAMA_BASE_URL:-http://ollama:11434}/api/pull" -d "{\"name\":\"${MODEL_NAME:-qwen2.5:1.5b-instruct}\"}" || true

# Lancer l'app
exec python app.py
