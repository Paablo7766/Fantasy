# MEMORY

Bitácora persistente. Se añade al final. No se reescriben entradas cerradas. Una entrada es un hecho del ciclo o una auditoría; las previsiones que aún no ocurrieron viven en el plan, no como resultado.

## Formato

```text
## YYYY-MM-DD HH:MM Europe/Madrid · jornada N · ciclo

- liga: <id>
- hechos: <comando JSON, cifra, hora de desbloqueo si aplica>
- supuestos: <lo que no vino en el JSON>
- plan: <acción, euros, puntos esperados, caja resultante>
- gobierno: silencio | telegram pendiente | rechazada
- ejecutado: no | sí · <id de orden>
```

Auditoría, cuando la jornada ya tiene puntos reales:

```text
## AUDITORÍA YYYY-MM-DD · jornada N

- previsto: <puntos esperados y variación de patrimonio>
- realizado: <puntos y patrimonio observados>
- error: <realizado - previsto>
- causa: <dato que faltaba o regla mal aplicada>
- corrección: <qué cambia en el siguiente ciclo>
```

## Registro

_Sin ciclos todavía._

## AUDITORÍA 2026-11-07 18:30 Europe/Madrid · jornada última

- previsto: 69.75 puntos del XI
- realizado: 79.0 (último weekPoints de cada titular)
- error: 9.25
- causa: la serie oficial no trae número de jornada; se usa el último weekPoints de cada titular
- corrección: no se cambian los pesos del solver en este ciclo
- auditoria-xi:69.75:79.0:2206,2384,2418,2680,2703,2713,2933,3023,3082,3090,3260
