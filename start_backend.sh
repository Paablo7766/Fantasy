#!/usr/bin/env bash
# Arranca el API FastAPI en todas las interfaces (necesario para Cloudflare Tunnel).
set -euo pipefail
cd "$(dirname "$0")"
exec uvicorn server:app --host 0.0.0.0 --port 8000
