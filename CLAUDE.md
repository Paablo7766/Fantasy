# LaLiga Fantasy Quant

App web mobile-first para ganar una liga privada de LaLiga Fantasy: cruza datos de la API oficial y de fuentes externas, la caja real de los rivales, una proyección propia de puntos esperados (xP) y un optimizador MILP que decide qué fichar, vender, clausular y alinear. Un único usuario (el propietario). Hablarle en español, sin explicar lo básico del juego.

Referencias (leer solo la que toque, no copiarlas aquí):
- `PRODUCT.md`: usuarios, propósito y restricciones.
- `DESIGN.md`: sistema visual completo.
- `CONTEXTO_ALGORITMO_ACTUAL.md`: diccionario de datos y cerebro analítico.
- `context/SKILL.md`: comandos CLI y fuente de verdad operativa.
- `frontend/AGENTS.md`: este Next.js tiene cambios incompatibles; consultar `frontend/node_modules/next/dist/docs/` antes de tocar APIs de Next.

## Mapa del código

| Dónde | Qué hay |
|---|---|
| `server.py` | Backend FastAPI (raíz). |
| `cli.py` | Comandos: `market`, `squads`, `trends`, `optimize`, `flip`, `needs`, `market-intel`, `plan`, `own-intel`, `clause-intel`. |
| `toolbox/` | Lógica de dominio: scrapers, caché, emparejamiento, `own_intel`, mercado, cláusulas, plan. |
| `toolbox/engine/` | Motor: `xp2.py` (xP 2.0), `p_titular_model.py` (titularidad), `signing_plan.py`, `clause_advisor.py`, `reglamento.py`, `paron*.py`, `guardarrail_ruina.py`, `liquidacion.py`. |
| `scripts/` | Backtests, ablaciones, auditorías, cargas a Supabase. |
| `investigacion/` | Análisis de solo lectura (`titularidad/`, `caja_pujas/`, `auditoria_consejos/`). No toca producción. |
| `tests/` | pytest (~125 ficheros). |
| `frontend/` | Next.js 16 (App Router), React 19, Tailwind v4 con `@theme`. Pantallas en `app/(panel)`, componentes por dominio en `components/` (`inicio`, `equipo`, `mercado`, `clausulas`, `liga`, `laboratorio`), kit propio en `components/ui/kit.tsx`. |

Pantallas: Inicio, Equipo, Mercado, Cláusulas, Liga y Laboratorio (fuera del menú).

## Comandos

```bash
# Backend (raíz, con .venv)
.venv/Scripts/python.exe -m uvicorn server:app --host 0.0.0.0 --port 8000
.venv/Scripts/python.exe -m pytest tests -q

# Frontend
npm --prefix frontend run dev
npx --prefix frontend tsc --noEmit -p frontend   # OBLIGATORIO antes de push
npm --prefix frontend run lint
```

`.claude/launch.json` define los servidores `backend` y `frontend` para `preview_start`.

## Reglas de trabajo

- **Commit y push directos a `main`**, sin ramas.
- **`tsc` antes de cada push**: `next dev` no detecta errores de tipos y Vercel sí rompe el build.
- No tocar `toolbox/` ni `scripts/` desde `investigacion/`: allí solo se lee caché, sin red ni reajuste de pesos.
- `.cache/` no llega a producción; lo que deba llegar va por Supabase.
- No commitear secretos (`.env*`, tokens de LaLiga, `REMOTE_REFRESH_TOKEN`).
- Hora de referencia: Europe/Madrid. Al comparar `stored_at` con un saque, pasar ambos a Madrid.
- Al medir un modelo, filtrar señales por `stored_at` anterior al saque: la fuga de datos es el fallo más caro de este proyecto.

## Reglas oficiales de LaLiga Fantasy (no se rompen)

- Endeudamiento máximo del 20 %.
- Ofertas entre ±10 % del valor.
- Clausulazo con sus plazos y blindaje.
- Saldo negativo = 0 puntos.
- Caja inicial real: 100 M€. El «91,2 M inferido» es un residual contaminado; `cash_ledgers` subestima a los rivales.

## Modelo xP

- **Fuente única**: `own_intel.own_expected_points`. Lo antiguo (legacy) está eliminado; no reintroducirlo.
- Fórmula: `xP = p × xP_si_titular + (1−p) × factor_banquillo × media_revulsivo`. Producción es `xp2.py`; base de referencia ~2,70 de MAE (J8–J12).
- Titularidad: cascada once publicado (FF/AF) → logística de minutos → regla del portero.
- **Descartado, no repetir sin ≥15–25 jornadas más**: eventos/xG, Gradient FC, minutos dado titular, ablación del 10-nov (nada entra), efectos de club (fuga del offset).
- Ante cualquier cambio del xP: medir contra el backtest antes de dejarlo.

## Reglas de UI

- Estética real: negro profundo (`#02070a`), tarjetas gris oscuro y hero naranja brasa (`#ff7a3d`). El azul `#0297DE` ("Cyber-Ocean") es solo acento de datos.
- Tipografía Inter; cifras en JetBrains Mono con `tabular-nums`.
- Listas como tabla limpia, **sin píldoras de color**: el color solo señala cambios.
- Todo club o rival mostrado lleva su **escudo** (Crest).
- Mobile-first: comprobar siempre en móvil y escritorio, no dar por bueno solo por el código.

## Cómo trabajar aquí

- Una señal o cambio por commit, para poder revertir.
- Si algo afecta a dinero (pujas, crédito, cláusulas), comprobar que respeta las reglas oficiales y que el plan no cuenta una puja como ganada.
- Informar de lo no verificado; no afirmar que un número mejora sin intervalo o backtest.
- Memoria persistente del proyecto en `~/.claude/projects/.../memory/` (índice `MEMORY.md`): consultarla antes de re-investigar algo que ya se midió.
