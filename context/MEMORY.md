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
