# LALIGA Fantasy

Tablero de solo lectura sobre la API de LALIGA Fantasy. El frontend Next.js vive en `frontend/`; el backend FastAPI está en la raíz (`server.py`).

## Despliegue a Coste Cero (Local + Vercel)

El frontend se despliega en **Vercel** (plan gratuito). El backend **no** se hospeda en la nube: se ejecuta en tu PC y se expone a Internet con un túnel de Cloudflare, sin coste de servidor.

### Requisitos

- Python con las dependencias de `requirements.txt` (y el entorno virtual activado).
- [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/) instalado en el PATH.
- Proyecto Next.js (`frontend/`) ya desplegado en Vercel.

### Pasos

1. **Arrancar el backend** en la raíz del proyecto:

   - Windows: `start_backend.bat`
   - macOS / Linux: `chmod +x start_backend.sh && ./start_backend.sh`

   Equivale a `uvicorn server:app --host 0.0.0.0 --port 8000`.

2. **Exponer el puerto con Cloudflare Tunnel** en otra terminal:

   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```

   Anota la URL HTTPS que imprime (algo como `https://xxxx.trycloudflare.com`).

3. **Configurar Vercel**: en el proyecto del frontend, define la variable de entorno

   ```text
   NEXT_PUBLIC_API_URL=https://xxxx.trycloudflare.com
   ```

   con la URL del paso 2, y vuelve a desplegar (o invalida el build) para que el cliente la use.

Cada vez que reinicies el túnel rápido (`--url`), Cloudflare puede asignar un dominio distinto: actualiza `NEXT_PUBLIC_API_URL` en Vercel con la nueva URL.

### Vercel + Render (backend en la nube)

Si el frontend está en **Vercel** y el API en **Render** (`render.yaml`):

1. **Render** (servicio `fantasy-api`): define `LALIGA_ACCESS_TOKEN`, `LALIGA_REFRESH_TOKEN`, `LEAGUE_ID` y un secreto **`REMOTE_REFRESH_TOKEN`** (cadena larga aleatoria). `LALIGA_ENV=production` ya va en el blueprint.
2. **Vercel** (proyecto `frontend/`):
   - `NEXT_PUBLIC_API_URL` = URL del servicio Render, **sin** `/api` al final (p. ej. `https://fantasy-api.onrender.com`).
   - **`REMOTE_REFRESH_TOKEN`** = el **mismo** valor que en Render (variable de servidor, **no** pública). El proxy de Next la envía en `POST /api/plan/refresh` hacia Render.
3. Vuelve a desplegar frontend y backend tras cambiar variables.

El botón **Actualizar** usa `?async=1`: Render responde **202** al momento y la barra avanza con `GET /api/refresh-status`. Así Vercel no corta la descarga (en plan Hobby el proxy serverless no aguanta un POST de media hora).

Si la barra desaparece al instante y ves **«Sin actualizar»**, suele faltar `REMOTE_REFRESH_TOKEN` en Vercel o no coincide con Render (401), o `NEXT_PUBLIC_API_URL` apunta a un backend caído.

`Dockerfile` y `render.yaml` documentan el despliegue en Render; el túnel Cloudflare sigue siendo la opción sin servidor de pago.
