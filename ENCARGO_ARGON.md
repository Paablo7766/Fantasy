# Encargo para Argon: mejorar la predicción de puntos y el once óptimo

## Objetivo
Predecir mejor los puntos de cada jugador de LaLiga Fantasy para elegir cada jornada el mejor once posible dentro de mi presupuesto, formación y reglas, y maximizar los puntos totales.

## Contexto del proyecto (ya construido)
- App con xP (puntos esperados) en `toolbox/engine/xp2.py`, llamado desde `toolbox/opta_points_v2.py`. Fuente única de xP: `own_intel.own_expected_points`.
- Backtest walk-forward: `scripts/backtest_xp.py` (usa solo jornadas anteriores a la que se predice). Error medio (MAE) de referencia en producción: **2,70** (J8–J11).
- Optimizador del once: MILP. Reglas oficiales: endeudamiento 20 %, ofertas ±10 %, clausulazo, saldo negativo = 0 puntos.
- Datos: actas por jugador con `[cantidad, puntos]` por acción, cuotas, calendario, histórico de temporadas pasadas (24/25 y 25/26).

## Lo que ya sabemos (no repetir)
- Sabiendo el once real, el error baja de 2,70 a 2,32 y la correlación sube de 0,42 a 0,62. **La titularidad es el mayor margen.**
- No ayudan: tiros en vez de goles, media J1–J6, tendencia de precio, multiplicador de ataque por rival, minutos dado titular.
- **Gradient FC descartado** (10 nov 2026): 119 partidos J1–J12 con tiros, pases clave, minutos y más; todas las variables empeoran el MAE (+0,01 a +0,10). No volver a probar con menos de ~25 jornadas.
- Con ~12 jornadas, las variables por jugador (xG, tiros) son ruido.

## Qué investigar, por orden de prioridad
1. **Titularidad.** Cruzar varias fuentes de probabilidad de titular (FútbolFantasy, AF, ruedas de prensa, lesionados, sancionados), medir cuál acierta más y combinarlas. Reajustar al salir los onces oficiales. Contar rotación por Champions, selecciones y acumulación de tarjetas.
2. **Puntos que no son goles.** Suelo (minutos, valoración de cronistas, acciones), portería a cero desde cuotas y probabilidad de victoria, penaltis, córners y faltas directas.
3. **Optimización del once.** Maximizar puntos esperados con presupuesto, formación y endeudamiento del 20 %. Incluir el riesgo (un once con varios dudosos), el calendario de las próximas jornadas y el mercado (precio, clausulazo, ofertas, sobrepuja real).
4. **Medición.** Toda mejora entra solo si baja el MAE de 2,70 en jornadas no vistas. Con intervalo de confianza. Lo que no mejore se descarta.

## Qué no hacer
- Añadir más fuentes de estadísticas de jugador.
- Fórmulas más sofisticadas sin datos nuevos de titularidad.
- Tocar producción sin backtest y sin `tsc` previo al push. Trabajar siempre en `main`.

## Entregable
Un informe corto con: qué fuentes de titularidad existen y cuál acierta más, qué mejora medida del MAE y de los puntos del once, y qué se propone implementar, ordenado por impacto.
