# USER

Plantilla de riesgo y gobernanza. Los números en `COMPLETAR` bloquean el gasto silencioso: mientras sigan así, `--execute` no puede mover dinero.

## Cuenta

- alias: COMPLETAR
- league_id: COMPLETAR
- zona_horaria: Europe/Madrid
- horizonte_patrimonio_dias: 7

## Umbrales

- reserva_caja_eur: COMPLETAR
- puja_silenciosa_max_eur: COMPLETAR
- puja_silenciosa_max_pct_caja: COMPLETAR
- suelo_venta_eur: COMPLETAR
- clausula_max_sin_preguntar_eur: 0

`clausula_max_sin_preguntar_eur` permanece en 0. Pagar o subir una cláusula no entra en el silencio.

## Qué hace `--execute` solo

Estas operaciones pueden ejecutarse sin Telegram cuando el flag está presente y todas las condiciones se cumplen:

| Operación | Condición para el silencio |
| --- | --- |
| Alineación | Once con 11 jugadores, formación de `context/SKILL.md`, y un portero. No cambia el saldo. |
| Puja nueva o al alza | Importe `<= puja_silenciosa_max_eur` y `<= puja_silenciosa_max_pct_caja` de la caja, y la caja restante `>= reserva_caja_eur`. |
| Cancelar puja propia | Siempre, si el flag está presente. Libera caja. |

Si un umbral es `COMPLETAR`, esa fila no es silenciosa.

## Qué exige Telegram

Hace falta un sí explícito en el chat `TELEGRAM_CHAT_ID` antes de ejecutar:

- Pagar la cláusula de un rival, por cualquier importe.
- Subir la cláusula de un jugador propio.
- Poner a la venta o aceptar una oferta.
- Cualquier puja por encima de los umbrales silenciosos.
- Cualquier orden que pueda dejar la caja en negativo en el momento de ejecutarse o en el cierre de jornada.
- Cualquier orden cuando falten menos de 60 minutos para el inicio de la jornada y el XI aún no está cerrado con 11.

La propuesta incluye jugador, importe, caja resultante, hora de desbloqueo si aplica, y el valor esperado que justifica el gasto. Sin ese sí, la orden queda en `context/MEMORY.md` como pendiente y no se envía a la API.

## Silencio operativo

- Ventana en la que no se envían mensajes de rutina: COMPLETAR (ejemplo: 23:30-07:30 Europe/Madrid).
- Un bloqueo de cláusula que vence dentro de esa ventana sí se notifica: es irreversible y tiene hora exacta.
