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

`Dockerfile` y `render.yaml` se mantienen por si más adelante vuelves a un despliegue en la nube.
