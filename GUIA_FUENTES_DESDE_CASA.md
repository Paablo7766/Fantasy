# Recuperar las fuentes que bloquean a Render

Render recibe 403 de analiticafantasy, FBref, Sofascore, Understat y Jornada Perfecta.
Desde tu casa sí responden, así que las descargas desde el PC y Render usa esa copia.

## Una sola vez

1. Instala Python 3.12 o superior y, en la carpeta del proyecto: `pip install -r requirements.txt`.
2. Crea un archivo `.env` en esa carpeta con **solo** estas dos líneas, copiando los valores
   de Render (servicio `fantasy-api` → Environment):

   ```
   SUPABASE_URL=...
   SUPABASE_KEY=...
   ```

   No hace falta nada de LaLiga: el script no la usa y no puede invalidar los tokens de Render.

## Cada vez que quieras refrescarlas (una vez al día basta)

```
python scripts/calentar_fuentes.py
```

Escribe `✓` o `✗` por fuente. Después pulsa la gota en la app: cuando Render reciba un
403 usará la copia guardada. Si el script dice que falta algo, te lo explica.
