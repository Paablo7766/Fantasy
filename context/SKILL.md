# SKILL

Reglas operativas de LALIGA Fantasy para el cerebro. Lo que no está escrito aquí vale 0 hasta que se añada. No se improvisan baremos.

## Datos

Única fuente de estado de la liga: la caja de herramientas.

- Mercado del día: `python cli.py market --json`
- Plantillas, cláusulas y desbloqueos: `python cli.py squads --json`
- Titularidad, alertas, aceleración de precio y valor Transfermarkt: `python cli.py trends --json`
- Once óptimo: `python cli.py optimize --json`
- Fichajes especulativos: `python cli.py flip --json`
- Caja rivales / clausulazos: `python cli.py needs --json`
- Auditoría forense de caja rival (techo y gasto oculto): `python cli.py rival-intel --json`
- Ciclo completo (plan, sin envío): `python cli.py agent --json`
- Veredicto de mercado (pujar / esperar / no): `python cli.py market-intel --json`
- Plan de jornada (reloj, once, puja y cláusula, sin envío): `python cli.py plan --json`
- Señales propias (puja / Poisson / E[pts]): `python cli.py own-intel --json`

`trends` cruza el catálogo de la liga con Fútbol Fantasy, Sofascore, FBref, Transfermarkt, Understat, Jornada Perfecta y Analítica Fantasy, y además calcula el motor propio (`own_*`). `p_titular`, las alertas y las métricas de forma (`xg`, `xa`, pases clave, duelos, despejes, paradas, nota) son datos de esas fuentes. El bonus Relevo de 0 a 4 no viene en ese JSON y no se inventa. `matching_confidence` por debajo de 0.85 no es un emparejamiento automático.

Claves Analítica Fantasy en `trends` (solo si el scrape y el matching ≥ 0.85 las rellenan; si faltan, no se inventan):

- Por jugador: `af_price_delta`, `af_market_value`, `af_ideal_bid`, `af_max_bid`, `af_market_signal` (`up`/`down`), `af_signal_strength`, `af_predicted_delta`, `af_expected_points`, `af_ceiling_points`, `af_goal_probability`, `af_assist_probability`, `af_points_per_million`, `af_form`, `af_injury`, `af_suspension`, `af_set_pieces`, `af_calendar`, `af_recommendation_pct`, `af_titular_delta`.
- Listas: `af_prediction_rising`, `af_prediction_falling`, `af_oracle_points`, `af_oracle_chollos`, `af_in_form`.
- Status de fuentes: `sources.analiticafantasy_market`, `_prediction`, `_ideal_bid`, `_points`, `_oracle`, `_injured`, `_suspended`, `_form`, `_set_pieces`, `_calendar`.

Claves del motor propio en `trends` (histórico de precios LALIGA + Understat; sin inventar si faltan datos):

- Por jugador: `own_ideal_bid`, `own_max_bid`, `own_market_signal`, `own_signal_strength`, `own_predicted_delta`, `own_expected_points`, `own_ceiling_points`, `own_goal_probability`, `own_assist_probability`, `own_points_per_million`, `own_calendar`, `own_recommendation_pct`.
- Listas: `own_prediction_rising`, `own_prediction_falling`.
- Status: `sources.own_intel_snapshots`, `_bids`, `_signal`, `_points`, `_calendar`.
- Puja propia exige ≥ 3 días de `price_snapshots`; sin eso esos campos quedan ausentes.

AF es contraste. El XI lo decide `optimize`; la puja operativa de `flip` sigue siendo un euro por encima de la líder (o el precio de venta). `market-intel` prioriza `own_*` frente a `af_*`. `plan` dice cómo pujar: sin líder, el ideal ahora (el empate lo gana la primera puja); con líder, snipe al tope si no es overpay. La sobrepuja cuenta rivales con caja conocida, o con caja reconstruida, y esa posición floja. Si la caja es solo el techo del historial, sigue contando: es lo máximo que podrían tener. Si falta incluso ese techo, el riesgo es `unknown`.

El historial de la liga es `GET /api/v1/competition/1/leagues/{id}/activity/{page}` hasta una página vacía. Tipos que mueven dinero: 31 compra a LaLiga, 33 venta a LaLiga, 1 cláusula (el `user2Id` cobra), 6 y 12 y 20–24 primas. El id del movimiento es el del mánager, no el del equipo. Si el historial no trae presupuesto inicial y la caja propia observada deja un residual positivo, ese residual es el presupuesto de toda la liga. En un rival, `reconstructed_cash_eur` es un techo (`cash_is_ceiling`): subir la cláusula propia no está en el historial. Sin eventos, el residual no se inventa.

La prima de una compra solo se calcula con el `price_snapshot` de ese jugador en el día del movimiento (fecha de `createdAt`, Europe/Madrid). Hasta un 2 % de diferencia cabe en el movimiento del valor después del cierre y no es guerra. Por encima del 100 % es un disparo y no entra en la puja. Hacen falta al menos 3 guerras de rivales que puedan pagar el precio de salida. La puja de liga es el precio de salida por (1 + mediana de esas guerras). Si al menos la mitad de esas guerras cae en un millón redondo o en una centena de millar, la puja sube al siguiente escalón de 100.000 € más el mayor extra observado (0–100 €) y 1 €. `stretch_bid` usa el percentil 75 con la misma regla. Si esa cifra pasa el techo de valor o la caja, no se recomienda: `league_bid_blocked`. Sin esas 3 guerras, la puja no cambia.

## Caja rival (`rival-intel`)

`rival-intel` publica la caja rival como **banda**, no como cifra única: el vídeo diario (+100.000 €) no deja rastro en la API y no se puede leer, solo acotar. Se le cobran las compras y cláusulas pagadas, se le abonan ventas y primas, y se le descuentan las subidas de cláusula que el tablón no publica. Sobre ese libro se abre la ventana de anuncios:

- `cash_floor_eur` — el libro **sin** vídeos, o con los mínimos que el propio historial demuestra (ver más abajo).
- `cash_expected_eur` — el libro con la tasa de vídeo calibrada con **tu** caja (`config.own_ad_rate_pct`). Es el punto medio razonable, no una cota.
- `calculated_cash` — el libro con **todos** los vídeos posibles: la cota superior de siempre.
- `cash_band_eur` — el ancho de la banda, que es exactamente `días × 100.000` cuando no hay suelo forzado. `max_bid_limit` sigue siendo `calculated_cash + deuda`; `floor_bid_limit` y `expected_bid_limit` son las otras dos lecturas.

La ventana de anuncios no se toma del `.env` cuando el tablón puede fecharla mejor. `config.league_start_source` dice de dónde sale: `alta` (tipo 9 en el historial), `actividad` (el primer movimiento fechado: no puede haber fichajes antes de que exista la liga) o `configuracion` (último recurso, `LEAGUE_START_DATE`). Un equipo que entró más tarde devenga desde su alta (`ad_bounds.team_start_day`), no desde el nacimiento de la liga.

El **suelo** (`ad_bounds.min_ad_eur`) no es siempre 0. El juego anula la jornada si el saldo es negativo al inicio y lo publica como tipo 8, así que un cierre negativo del libro solo se explica con publicidad cobrada: el déficit se redondea al alza a múltiplos de 100.000 y se publica como mínimo obligado (`forced_by_balance`). Es una lectura conservadora: basta **un** aviso de saldo negativo en todo el historial para desactivar el suelo (suelo 0), porque el aviso prueba que ese equipo puede operar bajo cero. El mínimo se mide a cierre de día, no intradía.

La tasa propia es el único punto de calibración real: `p = (tu_caja_observada − tu_libro_documentado) / (días × 100.000)`, acotada a `[0, 1]`. Se calcula sobre asientos documentados, sin el gasto oculto estimado (sería circular). Si sale negativa hay gasto propio sin registrar y se avisa; si sale por encima de 1 hay ingresos sin registrar.

Los tres parámetros que la liga puede cambiar sin tocar código se leen de `os.getenv` y, si la variable no está, del `.env` del proyecto. Una errata cae al fallback: nunca rompe la cota.

| Variable | Efecto | Fallback |
|---|---|---|
| `LEAGUE_START_DATE` | Primer día de liga; mueve el devengo de anuncios cuando el tablón no puede fechar el arranque (`days_elapsed`) | `2026-08-01` |
| `CLAUSE_INCREASE_MULTIPLIER` | Fracción del incremento que cuesta subir una cláusula; válido en `(0, 1]` | `0.20` |
| `STARTING_CLAUSE_MULTIPLIER` | Cláusula base de un jugador del reparto ≈ `valor de mercado × factor` | `1.5` |
| `CASH_THERMOMETER_TAU` | Escala del termómetro: el hueco relativo que baja la temperatura a `1/e` | `0.10` |
| `CASH_ARBITRAGE_BAND` | Hueco relativo que se considera ruido de medición, no fuga | `0.02` |
| `CASH_UNCERTAINTY_FLOOR_EUR` | Suelo de `σ_cash` en la barrera bayesiana de la puja | `150000` |

- Las primas se leen del `amount` y, si no viene, de la prosa con regex (`recibido`, `abonado`, `ingresado`, `€`). Una fila sin importe creíble no suma.
- Cláusula base por jugador de hoy: precio pagado si hay compra en el historial (31 o 1); si no, `buyPrice`/`initialClause` del JSON; si tampoco, `valor de mercado × STARTING_CLAUSE_MULTIPLIER`. La subida se cobra a `incremento × CLAUSE_INCREASE_MULTIPLIER`. Ese 0,20 es deliberadamente más barato que el 1:2 de la app: cobrar menos deja más caja al rival y mantiene la cota.
- `hidden_expenses_log.json` guarda el gasto medido por el diff diario. Un jugador vendido sigue descontando (agujero fantasma). Si sigue en plantilla, se cobra una sola vez: el mayor de diff y estimación retroactiva.
- `ledger_adjustments.json` ancla la caja a un valor con fecha. Desde el ancla solo cuentan las variaciones posteriores y el gasto diario fechado después; la estimación retroactiva (sin fecha) no se suma para no contar dos veces lo que el asiento ya resume. El día del ancla no devenga anuncio.
- `confidence` es `high` con plantilla y cláusulas completas, `medium` si falta alguna cláusula o el historial, `low` si la plantilla no cargó.

### Termómetro de control

`reconciliation` compara la cota con el saldo que publica la API. El hueco (`gap_eur = calculated_cash − observed_cash_eur`) tiene dos lecturas y ninguna reescribe la contabilidad a mano:

- `gap_eur < 0` — la cota se queda corta: hay dinero que los libros no explican. `covers_observed` es falso, `arbitrage_eur` publica el sobrante que no cabe en la banda de ruido y se añade un aviso. Hay que revisar los asientos; la cifra no se sube para taparlo.
- `gap_eur > 0` — la cota cubre. `tight_ceiling_eur` la aprieta al saldo publicado más el margen (`suelo + banda + anuncios devengados desde la foto`) y `slack_eur` dice cuánto se recortó.

`temperature = exp(−|hueco| / (tau · referencia))` en `(0, 1]` es la lectura del termómetro: 1 cuando cota y saldo cuadran. `posterior_sigma_eur = max(suelo, |hueco|)` es la `σ_cash` de la barrera `Φ((B − C)/σ)` que usa la puja, y `cover_probability = Φ(hueco/σ)` la probabilidad de que la cota siga cubriendo la caja real. `risk_adjusted_cash` y `risk_adjusted_bid_limit` son la cota calibrada y su poder de puja, y nunca bajan de `cash_floor_eur`: un rival no puede tener menos que lo que su propio libro demuestra. `max_bid_limit` sigue siendo `calculated_cash + deuda` para no cambiar el contrato publicado.

## Decisión de mercado (`market-intel`)

Solo analiza y recomienda. No envía pujas. Cada listing del mercado del día recibe `PUJAR`, `ESPERAR` o `NO`. Campos ausentes no se inventan: suman 0 al score y van en `missing_inputs`.

Vetos → `NO`: ya en plantilla, listing propio, lesión/sanción, caja insuficiente, XI anulado, mercado cerrado. Si `matching_confidence` &lt; 0.85, las señales AF no cuentan como motivo positivo (sí la aceleración LALIGA y las señales `own_*`).

Cascada de techo (`price_band`): `own_ideal_bid`/`own_max_bid` → `af_*` → unknown. `bid_eur <= ideal` → bargain; `ideal < bid <= max` → fair; `bid > max` → overpay.

Cascada de puntos: `own_expected_points` → `af_expected_points` → `expected_points` OPTA.

Cascada de flip: aceleración LALIGA → `own_market_signal` / `own_predicted_delta` → AF (solo si matching usable).

Cascada de calendario: `own_calendar` / `own_recommendation_pct` → AF.

Motivos positivos (solo con dato presente): flip, puntos de jornada (ROI pts/M), hueco del XI (`optimize.gaps` / `market_fills`), calendario favorable.

Veredicto:

- `PUJAR` — sin veto, banda bargain/fair/unknown, y al menos un motivo fuerte (flip, puntos, hueco o mejora real del XI). Si el snipe está en ventana (`inside_window`), también. Si `suggested_bid` es nulo porque el líder ya supera el techo, pasa a `ESPERAR`.
- `ESPERAR` — motivo fuerte pero overpay, o snipe futuro (`status=hidden`), o solo señal débil (calendario/precio sin flip/puntos/hueco).
- `NO` — veto, señal bajista sin hueco/puntos, o sin motivo.

Las pujas del día no se evalúan como si cada una tuviera la caja entera. Tras el veredicto individual se ordenan por score y se asigna el saldo. El horizonte es el saque de la jornada: el día (Europe/Madrid) con más clubes del catálogo que aún tienen partido, y el primer silbato de ese día. Un partido entre semana de dos clubes no agota el presupuesto. Si quedan N mercados diarios hasta ese saque (`markets_until_kickoff`), el presupuesto de hoy es `caja // N`. Un hueco de XI puede usar más, hasta la caja, porque el cero de jornada manda. El resto de `PUJAR` que no cabe pasa a `ESPERAR` (`caja_otros_mercados` si N>1, `caja_otras_pujas` si este es el último mercado). Sin saque conocido no se reserva para mercados futuros: solo se evita gastar la misma caja dos veces.

Orden: PUJAR → ESPERAR → NO; dentro, por score (pesos solo sobre componentes presentes). El dashboard expone `market_decisions`, `market_decision_summary` y `jornada_board` en `/api/trends`.

`jornada_board` ordena clubes por la celda de calendario presente: `own_calendar` y, si el matching es usable, `af_calendar`. Un club sin celda no entra. No se promedia un porcentaje que no vino.

Comparación con el once: el titular más flojo de la misma posición, y solo si mercado y titular comparten fuente (`own_expected_points` o `af_expected_points`). Si el de mercado no mejora y el único motivo fuerte eran los puntos, no es `PUJAR`. Un delta que no se puede calcular queda ausente.

Puja para llevártelo (`suggested_bid`): el techo sin pérdida es el mínimo de `own_max_bid` y `af_max_bid` cuando ambos existen (AF solo con matching usable). Por encima de ese mínimo no se recomienda subir, aunque la otra fuente llegue más alto (`aggressive_ceiling`). Sin líder, la puja de apertura es el ideal si cabe bajo ese techo. Si hay puja de liga y cabe bajo el techo y la caja, la apertura es la mayor entre el ideal y esa puja. Con líder y cierre conocido, el snipe es la mayor entre líder+1 y la puja de liga, sin pasar el techo: líder+1 pierde contra quien cierra en redondo. Sin techo y sin puja de liga, solo líder+1 o el precio de venta, y no se sube más. `rival_bids` son las pujas que ya trae el JSON; una puja que todavía no se ha hecho no se inventa. Si para ir primero ya hace falta más que el techo, el veredicto pasa a `ESPERAR`. Si la puja de liga pasa el techo, se muestra y no se recomienda.

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
- `offer_source`: `liga` si el listing no trae `seller_team_id`; `rival` si el vendedor es otro equipo; `propio` si es el tuyo. No se inventa un vendedor que el JSON no trae.
- El desbloqueo de una cláusula se agenda por `local_date` y `local_time` (hora y minuto), no por el día natural a secas.
- Un jugador blindado (`is_shielded` verdadero) no se trata como comprable por cláusula.

## Radar cuantitativo (`quant-radar`)

Value Investing puro: no mira a los rivales ni la puja de la liga. `GET /api/market/quant-radar?limit=12` sirve la foto guardada y el catálogo cacheado; ningún camino sale a la red (`sources.network = none`). La implementación vive en `toolbox/quant_valuation.py`.

- **Coste por punto** = `market_value / median_points`. La mediana sale de la serie completa de `weekPoints` (no de las últimas 5). Sin serie se usa `averagePoints` y se marca `points_source = averagePoints`: no es rendimiento real y no puede ser «infravalorado».
- **Referencia** = mediana de coste por punto de su posición, calculada solo con jugadores de serie real y `games >= 3`. `discount_vs_position = 1 - coste / referencia`. Infravalorado exige ≥ 30 % de descuento y una mediana de al menos el 60 % de la de su posición: barato por barato no es una ganga.
- **Blank rate** = proporción de jornadas con ≤ 2 puntos. Por encima del 40 % el activo es `TOXICO` aunque esté barato; entre el 30 % y el 40 % se marca «volatilidad» pero puede comprarse.
- **Smart money** = `acceleration > 0` y `price_delta > 0` (hoy sube más de lo que subió ayer). Sin `acceleration` el campo es `null`, no `false`. Las señales de la liga mandan sobre la tabla global de FútbolFantasy para el mismo `player_id`.
- **Nota (0–100)** = 55 % valor (puntos por millón ajustados por supervivencia contra la referencia de posición) + 25 % descuento + 20 % momentum. Sin `acceleration` el momentum vale 0,5 (neutro): no premia ni castiga.
- Veredictos: `COMPRAR` (fichable, con muestra, blank rate sano e infravalorado), `VIGILAR` (fichable y con dinero acelerando, pero precio en línea), `TOXICO`, `MERCADO`, `NO_FICHABLE` (propio, lesión, sin venta), `SIN_MUESTRA`.
- Solo es fichable lo libre o lo anunciado en el mercado. `effective_price` es el precio de venta si existe, no la tasación. Un jugador propio nunca es una compra.

