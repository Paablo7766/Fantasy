# SKILL

Reglas operativas de LALIGA Fantasy para el cerebro. Lo que no está escrito aquí vale 0 hasta que se añada. No se improvisan baremos.

## Datos

Única fuente de estado de la liga: la caja de herramientas.

- Mercado del día: `python cli.py market --json`
- Plantillas, cláusulas y desbloqueos: `python cli.py squads --json`
- Titularidad, alertas, aceleración de precio y valor Transfermarkt: `python cli.py trends --json`
- `optimize`, `flip`, `needs` y `agent` están reservados. Si responden `not_implemented`, no se sustituyen por un cálculo oral.

`trends` cruza el catálogo de la liga con Fútbol Fantasy, Sofascore, FBref y Transfermarkt. `p_titular`, las alertas y las métricas de forma (`xg`, `xa`, pases clave, duelos, despejes, paradas, nota) son datos de esas fuentes. El bonus Relevo de 0 a 4 no viene en ese JSON y no se inventa. `matching_confidence` por debajo de 0.85 no es un emparejamiento automático.

`squads` normaliza `buyoutClauseLockedEndTime` (y alias equivalentes del JSON) a `Europe/Madrid` con fecha, hora y minuto. La interfaz del juego oculta el minuto; el JSON no. Una cláusula sigue bloqueada mientras `clause_lock.is_locked` sea verdadero. Si `present` es falso, la API no envió marca de tiempo: no se inventa una hora.

## Puntuación de jornada

La puntuación de un jugador es la suma de los eventos OPTA de esta tabla más un bonus de rendimiento entero de 0 a 4 concedido por el criterio de Relevo. El bonus es un dato externo. No se deduce de los goles ni de una escala de nota inventada.

| Evento | Puntos |
| --- | --- |
| Gol de portero o defensa | +6 |
| Gol de centrocampista | +5 |
| Gol de delantero | +4 |
| Asistencia | +3 |
| Portería a cero, portero, con al menos 60 minutos | +4 |
| Portería a cero, defensa, con al menos 60 minutos | +3 |
| Portería a cero, centrocampista, con al menos 60 minutos | +2 |
| Portería a cero, delantero, con al menos 60 minutos | +1 |
| Penalti parado | +5 |
| Penalti fallado | -2 |
| Penalti cometido | -2 |
| Tarjeta amarilla | -1 |
| Tarjeta roja | -3 |
| Bonus de rendimiento Relevo | entero de 0 a 4 |

Posiciones: POR, DEF, MC, DEL. Un evento de otra posición no se reinterpreta. Un evento que no esté en la tabla no suma ni resta.

## Alineación válida

El XI tiene exactamente 11 jugadores, uno de ellos portero, en una de estas formaciones:

- 3-4-3
- 3-5-2
- 4-3-3
- 4-4-2
- 4-5-1
- 5-3-2
- 5-4-1

La formación cuenta solo a los jugadores de campo. 4-3-3 es 1 portero, 4 defensas, 3 centrocampistas y 3 delanteros.

## Regla crítica de jornada

La jornada completa puntúa 0 si, en su inicio, se cumple cualquiera de estas condiciones:

- El XI tiene menos de 11 jugadores.
- El saldo de caja es negativo.

El cero es de toda la jornada, no del jugador que falta. Antes de una puja, una venta o una cláusula, recalcular la caja en el cierre. Si el resultado puede ser negativo, la acción no es elegible y el plan tiene que dejar un XI de 11.

## Lectura del mercado

- El precio de venta, la puja líder y la caja son enteros en euros, tal como vienen en el JSON.
- El desbloqueo de una cláusula se agenda por `local_date` y `local_time` (hora y minuto), no por el día natural a secas.
- Un jugador blindado (`is_shielded` verdadero) no se trata como comprable por cláusula.
