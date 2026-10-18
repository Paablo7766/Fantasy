@echo off
REM Arranca el API FastAPI en todas las interfaces (necesario para Cloudflare Tunnel).
cd /d "%~dp0"
uvicorn server:app --host 0.0.0.0 --port 8000
