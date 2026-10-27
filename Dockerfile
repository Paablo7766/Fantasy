# Motor de scraping / orquestador de LALIGA Fantasy.
#
# Esta imagen es la única que debe correr con LALIGA_ENV=production: es la que
# abre sockets hacia LaLiga. El dashboard local sigue arrancando con
# `uvicorn server:app` en development (air-gap) y sin tocar la red.
#
# Imagen base ligera, sin compilador: todas las dependencias traen wheel para
# CPython 3.11 en linux/amd64.
FROM python:3.11-slim

# Sin .pyc ni salida bufferizada: los logs del refresco (que dura minutos) se
# ven en `docker compose logs -f` en cuanto se escriben.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# ca-certificates para httpx/curl_cffi y tzdata del sistema: la lógica de
# jornada y de cláusulas se calcula en Europe/Madrid. El paquete `tzdata` de
# pip también sirve, pero la imagen de Debian es la fuente canónica.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

# Dependencias en dos capas: cambiar el código no reinstala nada.
COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt \
    # curl_cffi no está en requirements.txt a propósito: en local (Windows)
    # no hace falta porque el air-gap nunca construye la sesión oficial.
    # En la imagen sí: sin él, net.py responde `missing_dependency` al primer
    # GET en producción.
    && python -m pip install "curl-cffi>=0.7.0,<1.0.0"

# Chromium es opcional. En una e2-micro (1 GB) no cabe junto al proceso de
# uvicorn: se deja fuera por defecto y se activa con
# `--build-arg INSTALL_BROWSER=1` en una instancia con más memoria.
# Los scrapers que usan httpx (FútbolFantasy, Jornada Perfecta, Analítica
# Fantasy, …) funcionan igual sin navegador.
ARG INSTALL_BROWSER=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN if [ "$INSTALL_BROWSER" = "1" ]; then \
        python -m playwright install --with-deps chromium; \
    fi

COPY . .

# La foto del tablero, la bitácora de red y el marcador del kill switch viven
# en /app/.cache (el ``project_root()/.cache`` por defecto), que en
# docker-compose.yml se monta como volumen para sobrevivir reinicios.
# **No** se define FANTASY_CACHE_DIR a propósito: toolbox/cache.py interpreta
# esa variable como «usa el almacén local» y desactivaría Supabase, que es
# justo la pieza que comparte el VPS con el dashboard de casa.

# Usuario sin privilegios, dueño de /app.
#
# No basta con crear .cache: varios módulos escriben junto al código
# (``market_offers_log.json``, ``ledger_adjustments.json`` y el ``.env`` que
# reescribe TokenManager al renovar el token cada 24 h). Con /app en manos de
# root, el primer refresco fallaría con PermissionError a mitad de pasada. El
# volumen de .cache se crea aquí para que Docker herede el propietario la
# primera vez que se monta.
RUN useradd --create-home --shell /usr/sbin/nologin fantasy \
    && mkdir -p /app/.cache \
    && chown -R fantasy:fantasy /app
USER fantasy

EXPOSE 8080

# Healthcheck sin curl: la raíz sirve static/index.html y no toca la red.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/',timeout=4)"

# `exec` deja a uvicorn como PID 1 para que reciba SIGTERM del runtime.
# Un solo worker: el estado del HumanPacer y del kill switch es de proceso;
# con dos workers habría dos cadencias y dos sesiones vivas a la vez.
CMD ["sh", "-c", "exec uvicorn server:app --host 0.0.0.0 --port \"${PORT:-8080}\" --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
