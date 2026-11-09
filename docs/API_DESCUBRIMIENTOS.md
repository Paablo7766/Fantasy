# Descubrimientos de la API de LaLiga Fantasy

Fecha de la lectura: 9 nov 2026. Cuerpos más recientes en caché: 4 nov 2026 (actividad hasta el 3 nov). Cero peticiones de red. El marcador `.cache/kill_switch.json` sigue disparado (503 el 5 nov, sobre `api/v4/leagues/7/market`) y no se ha tocado.

La lectura la hace `tools/api_discovery.py`. Recorre `.cache/bodies` y `.cache/scraper_bodies`, clasifica cada JSON por su forma y une el árbol de claves. El detalle con ejemplos redactados queda en `.cache/scratchpad/api_discovery/` (gitignored). Este documento no copia nombres de mánager, avatares ni el `token` de la ficha de liga.

Los tests del clasificador y del redactado están en `tests/test_api_discovery.py`.

## 1. Qué hay guardado, y de qué endpoint sale

La liga de la cuenta tiene 10 mánager (`managersNumber` y 10 filas por foto de clasificación). Las 20 fichas de plantilla son dos tandas de esos 10 equipos. La actividad está duplicada en disco (580 filas, 290 ids distintos): los conteos de abajo son los distintos.

| Forma | Ficheros | Qué es | Antigüedad |
|---|---|---|---|
| Liga | 2 | `GET /api/v1/competition/1/leagues` | 15 oct y 4 nov |
| Mercado | 2 | `GET /api/v1/competition/1/league/{liga}/market` | 15 oct y 4 nov. 105 anuncios en total |
| Clasificación | 2 | `GET .../leagues/{liga}/standing` | 15 oct y 4 nov |
| Plantilla | 20 | `GET .../leagues/{liga}/teams/{equipo}` | 15 oct a 4 nov |
| Actividad | 3 | `GET .../leagues/{liga}/activity/{página}` | eventos del 13 oct al 3 nov. La URL guardada termina en `/activity/1` |
| Catálogo | 1 | `GET /api/v1/competition/1/players` | 4 nov. 881 fichas |
| Alineación | 2 | `GET .../teams/{equipo}/lineup` | solo el equipo propio, 15 oct y 4 nov |
| Catálogo de tipos | 1 | cuerpo sin URL guardada | 20 oct. 33 tipos oficiales, con la frase en español |
| Caja suelta | 1 | `{teamMoney, teamInvestment}` sin URL | 20 oct |

No hay un documento de `news` en la caché. Las rutas de noticias del código son el plan B cuando la actividad paginada no devuelve nada; en estas fotos ganó la actividad. Tampoco hay cabeceras (ETag, Cache-Control, rate-limit): el cliente guarda el cuerpo y la bitácora solo apunta método, status, duración y ruta.

Fuera de esta API, la misma caché tiene cuotas, Understat y listas de estadística. No son LaLiga Fantasy y no entran en el inventario de abajo.

## 2. Árbol de cada respuesta

Los campos que el normalizador ya se queda están en el apartado 3, marcados «sí». Aquí va la forma real, con el hueco de relleno entre paréntesis.

### Mercado (`discr` parte el anuncio en dos)

Los 105 anuncios están `status = on_sale`. Ninguno trae `bids`, `offers` ni un importe de puja ajena.

`marketPlayerLeague` (26). Venta de la liga. Claves: `id`, `discr`, `status`, `leagueId`, `leagueType`, `expirationDate`, `numberOfBids`, `salePrice`, `playerMaster`. Sin vendedor.

`marketPlayerTeam` (79). Venta de un mánager. Lo anterior, más `numberOfOffers`, `directOffer`, `playerTeam` y `sellerTeam`.

`playerMaster` del anuncio: `id`, `name`, `nickname`, `slug`, `positionId`, `position` (texto, incluye «Entrenador»), `playerStatus`, `teamId`, `marketValue`, `averagePoints`, `points`, `lastSeasonPoints` (53 de 105), `images.transparent.256x256`. No trae `lastStats` ni ningún campo `*change*` / `*trend*`.

`playerTeam` (solo venta de mánager): `playerTeamId`, `buyoutClause`, `buyoutClauseLockedEndTime`, `isShielded`, `manager`.

`sellerTeam`: `id`, `manager`, `managerId`, `teamValue` (79/79), `teamPoints`, `teamMoney` (entero en 6, `null` en 73).

`expirationDate` viene en los 105. En la venta de la liga la hora de los ejemplos es las 14:08. En la venta de mánager es otra hora del mismo día.

### Plantilla

Raíz, en los 10 equipos: `id`, `manager`, `managerId`, `players`, `playersNumber`, `loanedPlayers` (lista vacía en los 20 ficheros), `startingWeek`, `banned` (siempre false), `teamValue` (siempre entero), `teamPoints`, `position` (en una de las dos tandas).

`teamMoney` es entero solo en el equipo propio (las dos tandas). En los otros nueve es `null`. La clasificación repite el mismo patrón: `team.teamMoney` es `null` en las 20 filas.

Cada jugador (285 filas, contando las dos tandas): `playerTeamId`, `buyoutClause`, `buyoutClauseLockedEndTime` (285/285), `isShielded` (siempre false), `manager`, `managerId`, y a veces `playerMarket` (80 filas: `id`, `salePrice`, `expirationDate`, `numberOfOffers`, `directOffer`). Un solo `directOffer: true`.

`playerMaster`: `id`, `name`, `nickname`, `slug`, `positionId`, `playerStatus` (`ok` 266, `injured` 12, `doubtful` 7), `marketValue`, `averagePoints`, `points`, `lastSeasonPoints` (174 con valor, 111 a null), `team` (id, name, slug, badges), `images.transparent.256x256`, `lastStats[]`.

Cada jornada de `lastStats` (1.297 filas): `weekNumber`, `totalPoints`, `isInIdealFormation` (31 true, 1.266 false), `stats`. Cada acción es `[cantidad, puntos]` y aparece en las 1.297 jornadas: `mins_played`, `goals`, `goal_assist`, `offtarget_att_assist`, `pen_area_entries`, `penalty_won`, `penalty_save`, `saves`, `effective_clearance`, `penalty_failed`, `own_goals`, `goals_conceded`, `yellow_card`, `second_yellow_card`, `red_card`, `total_scoring_att`, `won_contest`, `ball_recovery`, `poss_lost_all`, `penalty_conceded`, `marca_points`.

No hay `marketValueChange` ni ningún alias de variación.

### Catálogo

Ficha plana, 881 jugadores: `id`, `nickname`, `teamId`, `positionId` (string), `playerStatus`, `marketValue` (string), `averagePoints`, `points`, `image`, `lastSeasonPoints` (string, 495/881), `weekPoints[]` de `{weekNumber, points}` (5.134 jornadas). Estados: `ok` 528, `out_of_league` 285, `injured` 56, `doubtful` 6, `suspended` 6. Sin nombre largo, sin slug, sin cláusula, sin `lastStats`, sin variación de precio.

### Clasificación

Por fila: `position`, `previousPosition`, `points`, `team`. El `team` trae `id`, `manager`, `managerId`, `teamValue`, `teamPoints`, `banned`, `isAdmin`, `managerWarned`, `teamMoney` (null). Una tanda tiene `points` de temporada (70 a 153). La otra tiene `points` a 0 en los 10 equipos.

### Liga

`id`, `name`, `description`, `access` (`private`), `premium` (false), `isDuplicated`, `isSecondRound`, `managersNumber` (10), `type`, `config`, `team`, `token`.

`config.features.buyoutClause` es true. `config.premiumFeatures` deja en false capitán, banquillo, formaciones, entrenador, 11 ideal y cesiones. Aun así `premiumConfigurations` trae los parámetros por si se activaran: cesión de 1 jornada, máximo 3, `minPercentage` 0,25, y premio de 11 ideal de 100.000. El equipo propio dentro de esta ficha sí trae `money` entero, `playersNumber`, `teamValue`, `canPunctuate`, `position`.

El campo `token` existe. No se usa y no se reproduce aquí.

### Alineación (solo la propia)

`id`, `updatedAt`, `team` (`id`, `teamValue`, `teamPoints`), `formation`. La formación tiene `goalkeeper`, `defender`, `midfield`, `striker`, `bench`, `coach` (vacío) y `tacticalFormation` (tres enteros). Cada pieza repite la ficha del jugador, con cláusula, `playerMarket` si está en venta, `weekPoints` suelto de la última jornada e `isInIdealFormation` también en la raíz del jugador.

### Actividad

Por evento: `id`, `activityTypeId`, `createdAt`, `user1Id`, y según el tipo `amount`, `playerMasterId`, `user2Id`, `weekNumber`. Nada más. No hay texto libre ni array de pujas.

## 3. Qué leemos y qué se queda en el JSON

«Sí» significa que `normalize.py`, `league_history.py`, `player_history.py` o el motor xP se quedan el campo. «Parcial» significa que se guarda en crudo o en un log y no llega a la decisión o a la pantalla. «No» significa que ninguna de esas capas lo lee.

El núcleo que ya entra y no hace falta repetir fila a fila: id de jugador, nombre, apodo, puesto, club, valor, media, puntos por jornada (`totalPoints` / `weekPoints`, recortados a 5 en la ficha de plantilla), cláusula y su candado en la plantilla, caja del propio, vendedor, precio de venta, cierre del anuncio, `numberOfBids` / `numberOfOffers`, `directOffer`, valor de plantilla del vendedor, y de la actividad el tipo, el importe, los dos usuarios cuando vienen, el jugador y la fecha.

| Campo | Endpoint | Lo usamos | Ejemplo | Qué es | Valor si se usa |
|---|---|---|---|---|---|
| `playerStatus` | mercado (`playerMaster`) | no en el anuncio; sí en catálogo y plantilla | `ok` | Estado oficial, también `injured`, `doubtful`, `suspended` | El anuncio puede traer la baja y el normalizador del mercado no la copia. El catálogo sí la tiene, así que no se pierde si el catálogo va en el mismo refresco |
| `averagePoints`, `points` | mercado | no en el anuncio; sí `averagePoints` en plantilla y catálogo | `1.75`, `14` | Media y puntos de temporada | Atajo para valorar un anuncio sin cruzar el catálogo |
| `lastSeasonPoints` | plantilla, mercado, catálogo | no | `211` en catálogo, a veces null | Puntos del año pasado | Valorar a quien no ha jugado esta temporada. Hoy el matching se queda sin esa cifra |
| `slug` | plantilla y mercado | no | `unai-simon` no; el catálogo ni lo trae | Identificador estable de texto | Cruzar con Fútbol Fantasy / Analítica sin depender del nombre |
| `images.transparent.256x256` | plantilla y mercado | parcial | URL de foto | Foto oficial | La foto se resuelve por el catálogo (`image`), no por esta ruta. El anuncio de mercado no tiene `image` plano: su foto depende de ese cruce |
| `position` (texto) | mercado | no; se usa `positionId` | `Entrenador` | Puesto en texto. El 5 es el entrenador | Ya filtramos el `positionId` 5. El texto solo confirma el descarte |
| `discr` | mercado | no | `marketPlayerLeague` | Separa venta de la liga y venta de mánager | Hoy se infiere por la ausencia de `seller_team_id`. El campo lo dice explícito |
| `status` | mercado | no | `on_sale` | Estado del anuncio | En estas fotos no hay otro valor. Serviría para no tratar como abierto un anuncio ya resuelto, el día que la API lo mande |
| `playerTeam.buyoutClause` | mercado, venta de mánager | no | entero | Cláusula del jugador que está en venta | El candado sí se recupera (la búsqueda baja al objeto anidado). El importe de la cláusula del anuncio no pasa al listado |
| `sellerTeam.teamMoney` | mercado | no | null en 73 de 79 | Caja del vendedor | Casi siempre null. No da para una pantalla de «cuánto le queda» |
| `sellerTeam.teamPoints` | mercado | no | `0` | Puntos del vendedor en esa foto | La clasificación ya trae los puntos del equipo |
| `numberOfBids` | venta de la liga | sí, como recuento | `0` | Cuántas pujas lleva, sin importes ni nombres | La cifra ya se guarda. La pantalla puede enseñar el calor de la subasta; el precio de cada puja no está |
| `numberOfOffers` | venta de mánager | sí, como recuento | `1` | Ofertas recibidas, sin importes | Igual que arriba |
| `directOffer` | venta de mánager | parcial | `false` (1 true en plantilla) | La venta es trato cerrado, no subasta | Se persiste en el log de anuncios. No cambia la puja |
| `teamValue` | plantilla y clasificación | parcial (solo el del vendedor, en el anuncio) | entero en los 10 equipos | Valor de la plantilla rival | La pantalla de Liga puede enseñarlo. Hoy la semilla de clasificación no lo copia |
| `teamMoney` | plantilla y clasificación | sí cuando viene | entero solo en el propio; null en los 9 rivales | Caja | La API no publica la caja rival. La caja reconstruida sigue siendo el único camino, y es un techo |
| `playersNumber` | plantilla y liga | no | `13` | Tamaño de plantilla | Se puede contar el array. El campo evita un descuadre si `loanedPlayers` dejara de venir vacío |
| `loanedPlayers` | plantilla | no | `[]` | Cesiones | Vacío, y la liga tiene las cesiones desactivadas. No hay nada que mostrar |
| `startingWeek` | plantilla | no | `"9"` | Jornada de alta del equipo | Fecha de entrada, útil para no contarle premios de antes |
| `banned`, `managerWarned`, `isAdmin` | clasificación | no | `false`, `false`, `true` en un equipo | Moderación y admin | Casi constantes. Sirven de alerta el día que cambien, no de ranking |
| `previousPosition` | clasificación | no | `-1` o el puesto anterior | Puesto de la jornada previa | Flecha de subida o bajada en Liga |
| `points` a 0 en una tanda | clasificación | sí, tal cual | `0` en los 10 de una foto | Puntos | Una de las dos fotos guardadas trae la temporada a cero. Hay que no pisar una clasificación buena con esa tanda |
| `lastStats[].stats` | plantilla y alineación | parcial | `[90, 2]` en minutos | Cantidad y puntos de cada acción | El xP los lee de la caché cruda (`player_history` → `xp2`). No van en el jugador normalizado ni hay un acta en pantalla |
| `isInIdealFormation` | plantilla y alineación | no | `false` | Estuvo en el 11 ideal de esa jornada | No es la titularidad. 31 de 1.297 jornadas. Meterlo como `p_titular` empeoraría el modelo |
| `playerMaster.points` | plantilla | no; se usan las jornadas | `27` | Suma de temporada | El catálogo ya trae la misma suma |
| `config.premiumFeatures` | liga | no | capitán, banquillo, 11 ideal y cesiones en false | Reglamento de esta liga | Confirma que capitán y banquillo no puntúan. El premio de 100.000 del 11 ideal está en la config y la feature está apagada |
| `team.money` de la ficha de liga | liga | no por esta vía; el propio sí entra por la plantilla | entero | Caja propia | Segunda fuente de la misma cifra. Los rivales no están en esta ficha |
| `token` | liga | no | (no se copia) | Secreto de la liga | No leerlo, no loguearlo, no enseñarlo |
| Tipos 2, 3, 4, 5, 10–30 | actividad | no, y no han salido en esta liga | ver catálogo | Cesión, blindaje, denuncias, premios, altas de admin | El 4 (blindaje) es el único que cambiaría una decisión el día que aparezca. El parser lo tira |
| `weekNumber` | actividad tipo 6 | parcial | `11` | Jornada del premio | El importe entra como prima. La jornada no queda en el evento canónico |

## 4. Hipótesis

| Pregunta | Veredicto | Evidencia |
|---|---|---|
| ¿Quién sale en el próximo mercado, o cuándo rota el lote? | NO | Los 105 anuncios están `on_sale`. No hay lote futuro, ni cola, ni campo de rotación. `expirationDate` es el cierre de este anuncio, no el alta del siguiente |
| ¿Precio exacto pagado, cláusula, venta, y quién y cuándo? | SÍ, una vez resuelto | La actividad trae el importe. Tipo 31: compra a LaLiga (113 eventos, mediana 8,5 M). Tipo 33: venta a LaLiga (100, mediana 8,3 M). Tipo 1: compra a otro mánager, que en este juego es el clausulazo (37, mediana 12,5 M), con `user1Id` comprador y `user2Id` vendedor. El catálogo oficial de tipos no tiene una fila que diga «cláusula»: el texto del tipo 1 es «ha comprado al jugador de #user2Id# por #amount#€». El código lo etiqueta `clause` y el texto oficial dice «compra». Son la misma operación. Tipo 31 y 33 no traen al otro mánager porque el otro lado es la casa |
| ¿Pujas de los rivales mientras el anuncio está abierto? | NO el importe; SÍ el recuento | 0 anuncios con array de pujas. La venta de la liga trae `numberOfBids`. La venta de mánager trae `numberOfOffers`. Ningún nombre, ningún importe hasta que la actividad publica al ganador |
| ¿Serie de valor y variación diaria dentro de la API? | NO | Cero claves `change`, `trend` o `percent` en mercado (105), plantilla (285) y catálogo (881). Sigue vigente la nota del 24 oct en `CONTEXTO_ALGORITMO_ACTUAL.md`: la variación se mide restando `price_snapshots`. La mediana de `salePrice / marketValue` en los anuncios es 1,0, con una cola baja hasta 0,91: el precio del anuncio no es un histórico |
| ¿Hora de cierre de cada puja y de desbloqueo de cláusula? | SÍ | `expirationDate` en los 105 anuncios. Las de la liga, a las 14:08. `buyoutClauseLockedEndTime` en los 285 jugadores de plantilla y en los 79 `playerTeam` de anuncios de mánager. `isShielded` viene y está siempre a false |
| ¿Plantilla rival: valor, caja, deuda, tamaño, cláusulas, ofertas? | PARCIAL | Valor, tamaño, cláusulas y candados: sí. Caja rival: null en clasificación y en las 18 fichas que no son la propia. Deuda: no hay campo. Ofertas: solo el recuento dentro de cada anuncio, no un total por equipo. `loanedPlayers` vacío |
| ¿Puntos por acción, partidos, forma, lesión, probabilidad de titular? | PARCIAL | Acciones y sus puntos: sí, en `lastStats.stats` de la plantilla, y el xP ya los lee de la caché. Lesión y duda: `playerStatus`. Sanción: el catálogo trae 6 `suspended`; estas plantillas no traen ninguna. Partidos jugados: se cuentan las jornadas con minutos. Probabilidad de titular y once probable: no están en esta API. `isInIdealFormation` no es esa probabilidad |
| ¿Calendario, localía, cuotas, dificultad? | NO en esta API | Ningún cuerpo de LaLiga trae rival, localía ni cuota. Esas piezas siguen viviendo en Understat y en el proveedor de cuotas |
| ¿Tipos de actividad? | SÍ el catálogo; PARCIAL lo observado | El catálogo oficial tiene 33 tipos (tabla de abajo). En esta liga, del 13 oct al 3 nov, solo salen cinco: 1, 6, 9, 31 y 33 |
| ¿Cabeceras para peticiones condicionales? | NO VERIFICABLE | No se guardan. Hace falta un GET y leer las cabeceras dentro del cliente que ya existe. No se ha hecho: el kill switch está marcado |
| ¿La actividad puede ir más atrás de lo que guardamos? | PARCIAL | El código pide páginas hasta una vacía, con tope 40. Lo guardado termina en la página 1 y el evento más viejo es del 13 oct, con 10 altas (tipo 9), una por mánager. Eso encaja con el inicio de la liga, no con un historial cortado. La página 2 no está en caché: confirmar que viene vacía sería un GET. Hacia delante, la caché se queda en el 3 nov |
| ¿Query params (`limit`, `page`, `since`)? | NO en el cliente | La única query que construye `net.py` para LaLiga es `x-lang=es`. La página de actividad va en el path. No hay `since` ni `limit` en el código. No se han probado otros |

### Catálogo oficial de tipos, y cuántos hemos visto

Conteos distintos (la caché trae cada evento dos veces). Importe: mínimo, mediana y máximo de las filas, en euros.

| Id | Texto oficial | Vistos | Importe (min / mediana / max) | Qué hace el parser |
|---|---|---|---|---|
| 1 | Compra a otro mánager («de #user2Id# por #amount#€») | 37 | 0,91 M / 12,5 M / 48,5 M | `clause`. Trae comprador y vendedor |
| 2 | Cesión | 0 | — | se tira. La feature está apagada |
| 3 | Fin de cesión | 0 | — | se tira |
| 4 | Blindaje | 0 | — | se tira. Es el tipo que faltaría si alguien blinda |
| 5 | Expulsión tras denuncia | 0 | — | se tira |
| 6 | Premio de jornada | 30 | 1,0 M / 4,0 M / 6,5 M | `premium`. Trae `weekNumber` |
| 7 | No puntúa: alineación incompleta | 0 | — | el motor de rivales lo conoce; esta liga no lo ha emitido |
| 8 | No puntúa: saldo negativo (el texto oficial dice «salgo») | 0 | — | igual |
| 9 | Alta en la liga | 10 | sin importe | marcador de alta. Una por mánager |
| 10 | Abandono | 0 | — | se tira |
| 11 | Nuevo administrador | 0 | — | se tira |
| 12 | Premio del 11 ideal | 0 | — | el código lo trataría como prima. La feature está apagada |
| 13–19 | Activar capitán, banquillo, formaciones, entrenador, 11 ideal, cesiones, premium | 0 | — | se tiran |
| 20 | Otra recompensa de 11 ideal | 0 | — | el código lo tiene como prima |
| 21 | Ajuste de venta | 0 | — | prima, si apareciera |
| 22 | Actualización de puntos | 0 | — | prima |
| 23 | Rectificación de cálculo | 0 | — | prima |
| 24 | Otro ajuste | 0 | — | prima |
| 25–30 | Desactivar las mismas features | 0 | — | se tiran |
| 31 | Compra a LaLiga | 113 | 0,55 M / 8,5 M / 90 M | `buy`. Sin vendedor |
| 32 | No puntúa: alineación incorrecta | 0 | — | el motor de rivales lo conoce |
| 33 | Venta a LaLiga | 100 | 0,50 M / 8,3 M / 92,6 M | `sell` |

## 5. Dónde esto choca con `CONTEXTO_ALGORITMO_ACTUAL.md`

La nota del 24 oct sobre `marketValueChange` sigue siendo verdad en la caché del 4 nov: el campo no está.

El diccionario del apartado 1.2 describe el anuncio con `bids[]` (`amount`, `team_id`, `manager_name`). El normalizador acepta ese array. La API, en 105 anuncios, no lo manda. El recuento (`numberOfBids` / `numberOfOffers`) es lo que hay. Tratar `bids` como dato real inflaría una puja con importes que no existen.

El mismo diccionario lista `cash` en el equipo. En el cable, `teamMoney` solo viene relleno en el equipo propio. En los rivales es null. La caja reconstruida no es un duplicado de un campo que ya tengamos: es el sustituto de un campo vacío. Eso ya lo dice `league_history.py`; el diccionario del contexto no.

`week_points` de la ficha de plantilla se queda con las últimas 5 jornadas. El catálogo guarda la serie que traiga `weekPoints` sin ese recorte. Hoy esa serie es corta (unas 6 jornadas de media), así que la diferencia aún no es grande. El desglose por acción no entra en `week_points`: vive solo en la caché cruda.

El 12 % y el 4,7 % no son la misma prima. `auction_intel.PRIMA_PUJA` es 1,047. `sales_audit.SOBREPRECIO_RIVAL_PCT` es 12 y sirve para no vender un titular a un rival, no para calcular la puja de compra. La API no trae un porcentaje de sobrepuja. Calibrarlo es cruzar el `amount` del tipo 31 con el `marketValue` del mismo día, que es lo que ya midió el informe de fase 2 (mediana observada cerca del 5,7 % en la banda sana, n=30).

El premio de 100.000 de `premiumConfigurations.ideal.reward` no es el premio por punto de jornada. El premio de jornada es el tipo 6 (mediana 4 M, coherente con del orden de 100.000 por punto de una jornada). El de 100.000 del 11 ideal está definido y la feature está en false: esta liga no lo paga. Encaja con el capitán y el banquillo apagados.

## 6. Rutas hermanas

No se ha pedido ninguna. El kill switch está marcado y la fase 3 pedía un OK previo.

No propongo repetir rutas que el propio código ya retiró porque contestan 5xx (`/api/v3/.../market`, `/api/v4/leagues`, el host `api-fantasy`). Un 5xx dispara el kill switch y mata la pasada.

Candidatas, una petición cada una, parando en 401, 403 o 429 sin reintento. Las cuatro primeras son las que de verdad cierran un hueco. El resto es conjetura y no las ejecutaría sin un motivo nuevo.

| # | Ruta | Por qué | Si sale 404 |
|---|---|---|---|
| 1 | `GET /api/v1/competition/1/league/{liga}/market/{marketId}` | El anuncio trae el recuento y no las pujas. El detalle de un id que ya tenemos es el único sitio razonable donde podrían venir | se anota y se sigue |
| 2 | `GET /api/v1/competition/1/players/{id}` con un id público del catálogo | La colección existe; la ficha puede traer el estado o las jornadas que la lista no trae | igual |
| 3 | `GET /api/v1/competition/1/leagues/{liga}/activity/2` | Misma ruta que ya paginamos. Confirma si detrás de la página 1 hay más temporada | una lista vacía cierra la hipótesis |
| 4 | `GET /api/v1/competition/1/matches` | El calendario no está en ningún cuerpo actual. Es el hermano obvio de `/players` | no pruebo un segundo nombre (`/fixtures`, `/calendar`) en la misma pasada |
| 5 | `GET /api/v1/competition/1/leagues/{liga}/news` | Ya está en el código como respaldo y no tenemos ni un cuerpo | — |
| 6 | `GET /api/v1/competition/1/teams` | Índice de clubes reales, paralelo a `/players` | — |

Para las cabeceras no hace falta una ruta nueva: un solo GET del mercado vivo, leyendo `ETag`, `Last-Modified`, `Cache-Control` y cualquier `RateLimit-*` o `Retry-After` dentro de `LaligaClient._send`, sin imprimir `Authorization`. Eso es una sexta petición, aparte de las hermanas.

Presupuesto si se autoriza todo lo de arriba: 6 GET. Presupuesto de esta pasada: 0.

El marcador del 5 nov apunta a `api/v4/leagues/7/market` (el id 7 es el de los tests, y esa ruta v4 es de las que el código ya considera muertas). Un proceso nuevo no recarga ese fichero: `kill_switch_tripped()` solo mira la memoria, aunque el comentario de `server.py` diga que el fichero bloquea el refresco siguiente. No he borrado el marcador ni he comprobado si el host vivo sigue respondiendo.

## 7. Oportunidades, ordenadas por valor frente a coste y riesgo

Ninguna pide tráfico nuevo salvo la 8. El riesgo de ban de las siete primeras es nulo: leen caché que ya tenemos.

| # | Dato | De dónde | Pantalla | Esfuerzo | Riesgo |
|---|---|---|---|---|---|
| 1 | Precio real de la puja ganadora y del clausulazo, con día y rival | actividad 31 y 1, cruzada con `price_snapshots` del mismo día | Mercado (calibrar la prima) y Laboratorio | bajo: el evento ya está parseado; falta la tabla y la mediana por rival | de tipos, bajo. De datos: el tipo 1 es una compra a otro mánager; si se cuenta también como compra de mercado se duplica con el 31 |
| 2 | Reloj de cláusula que se abre hoy | `buyoutClauseLockedEndTime`, ya normalizado en la plantilla | Cláusulas y Hoy | bajo, es una alerta sobre un campo que ya existe | bajo. El candado del anuncio está anidado en `playerTeam` y el buscador ya baja ahí |
| 3 | Lesión o sanción del anuncio | `playerMaster.playerStatus` del mercado, que el listado tira; el catálogo ya trae `suspended` | Mercado y Equipo | bajo: copiar el campo al anuncio y no dejar que una foto vieja de plantilla lo pise | un `suspended` del catálogo y un `ok` de una plantilla de hace días pueden contradecirse. Manda la foto más nueva |
| 4 | Valor de plantilla de cada rival | `teamValue` de la clasificación, hoy solo se lee en el vendedor del anuncio | Liga | bajo | bajo. No rellenar la caja: `teamMoney` rival es null y enseñarlo como cero sería mentira |
| 5 | Puesto que gana o pierde el rival | `previousPosition` | Liga | bajo | una tanda guardada trae `points` a 0. No usarla como «ha perdido el liderato» |
| 6 | Calor de la subasta | `numberOfBids` y `numberOfOffers`, ya guardados | Mercado | bajo si la ficha aún no lo enseña | bajo. El recuento no es el importe |
| 7 | Blindaje el día que exista | tipo 4, hoy descartado por el parser | Cláusulas | bajo | cero mientras no aparezca. Cuando aparezca, un jugador blindado deja de ser objetivo |
| 8 | GET condicional | cabeceras del mercado vivo | Laboratorio (ahorro de tráfico) | bajo, pero es la única fila con red | un 401, 403, 429 o 5xx dispara el kill switch. Por eso no va en esta pasada |
| 9 | Próximo lote del mercado | no está en la API | Mercado | alto, y sería un modelo, no un campo | el informe de fase 2 ya midió que rotar al que sube no cubre la prima. Construir el predictor antes de tener el lote es el riesgo de producto |
| 10 | `isInIdealFormation` como titularidad | plantilla | Equipo | — | no hacerlo. 31 de 1.297 jornadas, y no es el once probable |

## 8. Qué haría el producto con esto

La prima de puja se puede dejar de asumir. Cada compra a LaLiga (tipo 31) es el precio que de verdad ganó la subasta, con hora. Cruzada con el valor de ese día sale la prima real de esta liga, en conjunto y por rival. El 4,7 % del código y el 12 % de la regla de venta se comparan contra esa mediana, no al revés. Hace falta el valor del mismo día: sin `price_snapshots` de esa fecha la prima no se separa del movimiento de las 14:08.

El clausulazo ya tiene precio, comprador y vendedor (tipo 1). La pantalla de Cláusulas puede enseñar «X pagó la cláusula de este jugador el día D» sin scrapear nada más. El mismo historial dice a quién le compramos caro y a quién le vendemos barato a la liga (tipo 33, a menudo por debajo del valor: la cola de `salePrice / marketValue` baja hasta 0,91, y el tipo 33 es el importe cobrado).

El detector de cláusulas que se abren sale del candado que ya parseamos. La alerta es de producto: quién deja de estar blindado por tiempo antes del cierre de hoy. No hay un segundo campo escondido.

La baja oficial llega en `playerStatus` antes de que el precio se mueva, porque el precio no trae variación. Copiar el estado al anuncio, y quedarse el `suspended` del catálogo, es la alerta de lesión. No hay probabilidad de titular en esta API: seguir con el modelo propio de minutos es lo que la propia fase 2 ya dejó ganar al «jugó el último».

El próximo mercado no se puede leer. Se podría, más adelante, modelar quién pone la liga en venta a partir de los tipos 33 y de los anuncios `marketPlayerLeague` de días previos. Eso es un proyecto de predicción con los huecos que el informe de fase 2 ya marcó (precio del día siguiente a cada jornada), no un campo que estemos tirando.

## 9. Qué queda sin hacer

Cero cambios de producción. Cero GET. Las cuatro rutas hermanas y la lectura de cabeceras esperan un OK, y esperan que se decida qué hacer con el marcador del 5 nov antes de abrir un socket.
