# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Un único usuario: el propietario del proyecto, que juega a LaLiga Fantasy y quiere ganar su liga. Usa la app sobre todo desde el móvil, en ventanas de decisión cortas (mercado diario, cierre de jornada, cláusulas), y también en escritorio para revisar con calma. Conoce el juego a fondo; no necesita explicaciones básicas.

## Product Purpose
App web mobile-first que cruza datos en tiempo real, la contabilidad de los rivales y un optimizador MILP para decidir qué fichar, vender, clausular y alinear. Éxito = ganar la liga con decisiones mejores y más rápidas que las de los rivales y que la herramienta de referencia (La Pizarra del Míster).

## Positioning
Combina la caja real de los rivales (quién puede pagar una cláusula), una proyección propia de puntos esperados (xP) y un solver que tiene en cuenta liquidez y calendario. Una herramienta pública genérica no ve la liga concreta del usuario.

## Operating Context
Se usa a diario, con picos antes del cierre de mercado y de cada jornada. La información cambia por foto de datos (jornada, mercado, cuotas, onces). Las decisiones tienen plazos y reglas oficiales (endeudamiento 20 %, ofertas ±10 %, clausulazo, saldo negativo = 0 puntos).

## Capabilities and Constraints
- Frontend Next.js 16 (App Router), React 19, Tailwind v4 vía `@theme`, sin librería UI externa; kit propio en `frontend/components/ui/kit.tsx`.
- Backend Python/FastAPI con motor MILP; despliegue en Vercel (los errores de tipos rompen el build: ejecutar `tsc` antes de subir).
- Pantallas: Inicio, Equipo, Mercado, Cláusulas, Liga y Laboratorio (fuera del menú principal).
- Reglas del proyecto: cualquier rival o club mostrado lleva su escudo; las cifras en tipografía mono con `tabular-nums`; listas como tabla limpia, sin píldoras de color (el color solo señala cambios).
- Trabajo directo en `main`.

## Brand Commitments
Estética sobria y densa, estilo app financiera móvil de gama alta (Revolut Ultra / Robinhood Gold), nada infantil. Hoy el aspecto real es negro profundo con tarjetas gris oscuro y un hero naranja brasa; el azul `#0297DE` de la versión "Cyber-Ocean" queda como acento de datos. Tipografía Inter, cifras en JetBrains Mono. El detalle vive en `DESIGN.md`.

## Evidence on Hand
Datos reales de la liga del usuario vía backend; documentación en `CONTEXTO_ALGORITMO_ACTUAL.md` y en `docs/`. No hay testimonios ni usuarios externos.

## Product Principles
1. Decisión rápida: lo accionable primero, el detalle a un toque.
2. Cada dato tiene una única casa; sin duplicados entre pantallas.
3. Honestidad con la incertidumbre: se muestra cuándo una cifra es estimación.
4. El móvil manda: pulgar, una mano, poco desplazamiento.
5. Densidad con orden: mucha información, jerarquía clara, color solo cuando significa algo.

## Accessibility & Inclusion
Sin requisito formal. Contraste suficiente sobre fondo oscuro y respeto de `prefers-reduced-motion`.
