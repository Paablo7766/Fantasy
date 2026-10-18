# Backend FastAPI + Playwright. Chromium y sus librerías del sistema
# se instalan en la imagen para que los scrapers no fallen en Render.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt \
    && python -m playwright install --with-deps chromium

COPY . .

EXPOSE 8000

# Render inyecta PORT si lo cambias en el servicio. `exec` deja a uvicorn
# como proceso principal para que reciba la señal de apagado.
CMD ["sh", "-c", "exec uvicorn server:app --host 0.0.0.0 --port \"${PORT}\" --proxy-headers --forwarded-allow-ips='*'"]
