# Caja real y comportamiento de puja

15 de noviembre de 2026. Solo lectura: los scripts `caja.py` y `pujas.py` leen `.cache` y escriben `caja_resultados.json` y `pujas_resultados.json` en esta carpeta. No se llamó a `needs_from_documents`. `books_from_activity` se ejecutó en memoria con el feed de hoy y no escribe nada.

Datos de partida, con dos cambios sobre lo previsto: el feed trae ya **149 ventas** (una del 15-nov a las 12:34) y el registro de subidas tiene **146 filas**, no 132. Sausor10 e iaaagocab sí aparecen en las fotos de cláusulas: casi no suben cláusulas (0,2 M cada uno).

## 1. Caja de cada rival

Hora de corte: 15-nov, 14:45. Libro desde 100 M con compras, ventas, premios y clausulazos (el cobro del vendedor se abona una sola vez: el feed nunca lo trae aparte).

| Equipo | Libro | Mín | Probable | Máx | Tabla 9-nov | Tabla − probable al 9-nov | Vivo hoy | Vivo − probable |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| floren romi | 108,5 | 102,0 | 105,7 | 109,1 | 85,0 | −6,0 | 101,2 | −4,5 |
| gerardo_vp | 119,8 | 99,2 | 102,8 | 106,2 | 10,1 | −0,8 | 94,3 | −8,5 |
| Naviis10 | 90,6 | 66,9 | 69,0 | 72,4 | 4,5 | +6,4 | 64,4 | −4,6 |
| Gon redon | 35,0 | 21,3 | 24,6 | 28,0 | 36,4 | −0,4 | 21,8 | −2,8 |
| Pedro Salcines Fc | 31,6 | 15,2 | 18,6 | 22,0 | 15,8 | +4,2 | 19,9 | +1,4 |
| iaaagocab | 13,6 | 13,5 | 13,5 | 16,8 | −4,2 | −8,7 | 13,6 | +0,1 |
| Sausor10 | 8,4 | 7,2 | 8,1 | 11,5 | 23,1 | −8,7 | 8,3 | +0,2 |
| PABS FC | 40,0 | 1,2 | 6,3 | 9,7 | −8,4 | +19,5 | 10,0 | +3,8 |
| pablooceballos | 6,9 | 0,4 | 0,4 | 3,4 | −8,6 | −8,6 | −3,2 | −3,6 |
| *paaabsnz (tú)* | 56,7 | 48,9 | 48,9 | 52,3 | 9,1 | −3,2 | 45,6 real | — |

Millones de euros. La tabla se compara con el probable en su propio corte (9-nov, 11:03:32). Así cada diferencia es de método y no de fechas.

**Cómo se forma el intervalo**

* **Subidas de cláusula.** Se rehacen desde las fotos diarias de cláusulas. Una subida que deja la cláusula justo en el valor de mercado del día es el suelo automático, porque la cláusula nunca baja del valor, y no cuesta nada. Pasa en 87 de las 146 filas del registro, todas iguales al valor al euro. Las que dejan la cláusula por encima del valor cuestan la mitad del aumento (regla 1:2). Las fotos del 25-oct y del 3-nov son copias de la del 24-oct. Usarlas hacía que una subida ya medida se «deshiciera» y se cobrara dos veces (Naviis10 pagaba 7,3 M dos veces), así que se descartan.
* **Vídeos.** El dinero de los vídeos se calibra con tu propia caja. Ojo: 4 de los 9 saldos propios guardados (`auditoria_lunes` del 3, 9, 10 y 12-nov) son de la ficha cacheada y cuadran con el libro de horas antes. Por ejemplo, el 10-nov marca el libro del 9-nov tras la venta. Se usan las dos fotos fiables más alejadas (6-nov 22:52 → 15-nov 14:45). El residual baja 2,20 M y tus subidas manuales detectadas suman 2,18 M: la tasa sale −0,03 al día, así que se fija en 0. Si las subidas automáticas costaran, la tasa tendría que ser 10 vídeos al día, cosa imposible. Eso confirma que son gratis.
* **Mínimo:** subidas al coste alto (aumento sobre la cláusula anterior, no sobre el valor), más un **gasto invisible de 3,3 M**, sin vídeos. Ese gasto se midió en tu equipo: el libro menos las subidas que ven las fotos da 48,9 M y tu caja real es 45,6 M. Las fotos empiezan el 24-oct y tienen un hueco del 26-oct al 1-nov; lo subido antes, o subido y vendido dentro del hueco, no aparece.
* **Probable:** libro menos subidas detectadas, con vídeos a la tasa calibrada (0).
* **Máximo:** libro menos subidas detectadas (son gasto demostrado) más los 34 vídeos posibles (3,4 M).
* **Suelos legales,** que solo suben el mínimo: antes de pagar una cláusula la caja cubría el importe, y al empezar una jornada con premio la caja era ≥ 0. El saque de la J12 se tomó de `matchday_snapshot_log` (sábado 7-nov, 14:00). Para J9–J11 se usó el sábado a las 14:00, que es el suelo menos exigente. `calendario_competiciones_2627.json` no sirve aquí: pone la J13 el 10-nov y empezó el 20. Con ese calendario, iaaagocab necesitaba un alza ficticia de 29 M.

**Qué ensancha más el intervalo.** Los vídeos (3,4 M) y el gasto invisible (3,3 M), casi a partes iguales. El coste alto añade hasta 1,8 M (gerardo_vp, PABS FC). Los suelos lo estrechan entre 1 y 4 M en pablooceballos, iaaagocab, Sausor10 y gerardo_vp. Hay una incertidumbre mayor fuera del intervalo: el exceso de cláusula sobre el valor de los jugadores del reparto (7,6 a 27,6 M por equipo) no tiene base conocida. En tu equipo ese exceso es de 24,2 M y solo faltan 3,3 M, así que casi todo es la cláusula inicial y no subidas. Por eso no entra.

**Pujas ganadas frente a la caja.** De 108 cierres con compra, 89 los cubría ya el mínimo, 2 el probable y 17 ni el máximo: en esos usaron crédito o hay un ingreso que no se ve. Los mayores huecos sobre el máximo son PABS FC el 7-nov (38,5 M con ≤ 8,0 M de caja), gerardo_vp el 1 y el 3-nov (34 M cada uno), iaaagocab el 4-nov (28 M) y Naviis10 el 1-nov (26 M). No hay valor de equipo de aquellos días, así que no se puede decir si cabían en el 20 %.

### Diferencia euro a euro

**Contra `cash_ledgers` (91,2 M, 9-nov).** Los asientos coinciden uno a uno con el feed. La diferencia de cada equipo es exactamente:

> tabla − probable = **−8,8 M** (inicial de 91,2 en vez de 100) **+ subidas no restadas** − suelos no aplicados

Las subidas no restadas son PABS FC 28,3, Naviis10 15,2, Pedro Salcines 13,0, Gon redon 8,4, gerardo_vp 8,0, tú 5,6, floren romi 2,8 y el resto ≤ 0,5 M. Los suelos no aplicados son −0,4 en pablooceballos y −0,1 en iaaagocab. En total: −88,0 M de inicial, +82,0 M de subidas, −0,5 M de suelos y residual 0 en los diez equipos. Hasta hoy la tabla ha dejado de ver además los movimientos posteriores: +100,9 M de gerardo_vp, +77,3 M de Naviis10, +39,7 M de PABS FC, +38,7 M tuyos y −23,5 M de Sausor10, más 0 a 9 M de subidas nuevas por equipo.

**Contra `books_from_activity` en memoria hoy.** Usa el mismo libro, el mismo inicial de 100 M y los mismos suelos en todos los equipos salvo en dos. La diferencia es toda de subidas: `hidden_costs_from_log` resta el `cost_eur` guardado. Ese coste está al 20 % del aumento y no al 50 %, incluye las 87 subidas automáticas y no encadena ni descarta las fotos copiadas. Por eso unas veces resta de más (gerardo_vp −8,5, Naviis10 −4,6, floren romi −4,5) y otras de menos (PABS FC +3,8, Pedro Salcines +1,4). Tus 45,6 M son el saldo observado.

## 2. Cómo pujan

**Muestra.** 68 de 152 compras tienen valor conocido antes del cierre de las 14:08. Las fotos se guardan por la tarde, así que el valor es casi siempre el de la víspera (mediana de 16 h de antigüedad). Solo 5 tienen foto del mismo día guardada antes del cierre. Las 55 que usa hoy `collect_activity_buys` son fotos del mismo día, pero guardadas después del cierre. Las 84 restantes no tienen foto previa: 14–18 de octubre (antes de las fotos), 24-oct, 28-oct a 1-nov (hueco), 3–4, 10, 13 y 14-nov. Quedan fuera de la prima.

**Prima del ganador** (precio / valor previo − 1):

| | n | P25 | Mediana | P75 | Al valor | > +10 % | > +50 % |
|---|---:|---:|---:|---:|---:|---:|---:|
| Todas | 68 | 0 % | +11 % | +49 % | 35 % | 51 % | 25 % |
| Rivales | 59 | 0 % | +10 % | +52 % | 37 % | 51 % | 27 % |
| Tuyas | 9 | +5 % | +29 % | +41 % | 22 % | 56 % | 11 % |
| < 1 M | 16 | 0 % | +18 % | +205 % | 44 % | 50 % | 38 % |
| 1–5 M | 24 | 0 % | +35 % | +81 % | 38 % | 63 % | 42 % |
| ≥ 5 M | 28 | 0 % | +9 % | +20 % | 29 % | 43 % | 4 % |
| DEF / MC / DEL / POR | 24 / 12 / 16 / 4 | | +28 / +21 / 0 / +23 % | | | | |

Por día de la semana no se puede afirmar nada: hay celdas de 2 y 3 compras (jueves +48 % con n = 13, lunes +2 % con n = 20).

**Lo que deforma ver solo al ganador.** No se puede medir con `bid_count`, porque el registro de anuncios empezó el 10-nov y solo cuatro compras tienen recuento: tres con 0 pujas vistas la víspera y una con una. El recuento es además un mínimo, porque se guarda la tarde anterior. Hay dos cotas:

1. El 35 % de los ganadores pagó el valor exacto. En esas subastas nadie pujó por encima.
2. De los 23 anuncios de LaLiga que cerraron el 11 y el 12-nov con foto previa, **se vendieron 4**. En los otros 19 una puja al valor habría ganado. La curva solo ve subastas en las que alguien compró. Para un anuncio cualquiera, P(ganar al valor) ronda el 88 % (19 + ⅓ de 4, sobre 23); la curva dice 33 %. La curva solo vale para jugadores que otro también quiere.

**Qué acompaña a un precio alto** (Spearman con la prima, sin regresión):

* La subida del valor publicada la víspera es la señal más clara: ρ = +0,58 (n = 28, solo desde el 3-nov). Jugadores que bajaban, −1 % de mediana; que subían, +52 % a +87 %.
* Puntos recientes: +0,28 (n = 23). xP previo: +0,02 (n = 23), nada.
* Valor: −0,20. El tramo de 1–5 M es el más caro.
* Rivales con caja para cubrir el precio: +0,33, pero va con el valor (a un jugador barato lo cubre cualquiera).
* El libro justo no encarece la puja. Con crédito, mediana +9,5 % (n = 13); con caja de sobra, +13,5 % (n = 46).

**Rivales en dos líneas** (perfil con ≥ 8 compras con valor; IC 95 % de la mediana por remuestreo):

* **pablooceballos** (8 de 24): la mitad al valor exacto, mediana +4 % (−2 a +27 %), ninguna por encima de +50 %. Algo más en jugadores de < 1 M (+18 %, n = 4).
  5 compras por encima de su caja probable; 7 clausulazos pagados y 7 sufridos. Con crédito no paga más.
* **Gon redon** (9 de 16): mediana +12 % (−1 a +52 %). En 1–5 M paga +42 % (n = 4); en ≥ 5 M, el valor (n = 5).
  El que más clausulazos paga (17) y sufre (17); 4 compras por encima de su caja.
* **PABS FC** (10 de 16): mediana +13 % (0 a +86 %), pero en defensas +89 % (n = 4), con una a +156 %.
  3 compras por encima de su caja. Cuando va justo, paga el valor (n = 3).
* **gerardo_vp** (10 de 17): mediana +10 % (−2 a +80 %), y el 30 % de sus compras pasa de +50 %. Delanteros +39 % (n = 4).
  Es el que más compra por encima de su caja (6) y el único que paga más con crédito (+19 % frente a +1,5 %, n = 4/6). Casi no clausula (2).
* **iaaagocab** (8 de 16): 5 de 8 al valor exacto y las otras 3 por encima de +50 % (un portero de < 1 M a +362 %). Mediana 0 % (0 a +355 %).
  4 compras por encima de su caja, 5 clausulazos.
* **Naviis10** (8 de 23): mediana +6,5 % (0 a +63 %), la mitad al valor; centrocampistas +38 % (n = 2).
  4 compras por encima de su caja; 5 clausulazos pagados y 8 sufridos.
* **floren romi, Pedro Salcines Fc, Sausor10**: solo 2 compras con valor cada uno. No da para un perfil: +100 %/+185 %, +84 %/+94 % y +26 %/+27 %. Usan mucho el clausulazo (10, 8 y 6 pagados).

**Tú.** Tus 9 compras con valor salen a +29 % de mediana (0,4 a +48 %), por encima de cualquier rival con perfil. De tus pujas no hay ninguna fila con tu oferta y el precio ganador a la vez. Las 6 «perdidas» de `market_decision_snapshots` traen lo que pagó el ganador, pero no lo que ofertaste. Las 3 filas con `own_bid` son ofertas de LaLiga por tu jugador 2300 (`offer_source = liga`), no pujas. La segunda oferta no consta en ningún sitio, así que no se puede saber cuánto pagaste de más sobre ella.

## 3. Probabilidad de ganar fuera de muestra

Entrena con 45 compras que cerraron hasta el 2-nov y evalúa con 23 del 5 al 12-nov. Cada subasta de prueba se puntúa en 13 primas (0 % a +100 %, con +4,7 % y +12 %); «gana» si la prima iguala o supera la del ganador.

| Regla | Brier | Frente a la curva global reajustada |
|---|---:|---|
| Ingenua: +4,7 % gana siempre | 0,345 | +0,138 (IC +0,04 a +0,24) |
| Ingenua: +12 % gana siempre | 0,328 | +0,121 (+0,09 a +0,15) |
| App, curva global reajustada | 0,207 | — |
| Nueva, por tramo de precio | 0,199 | −0,008 (−0,017 a +0,001) |
| App, cadena tramo → sube hoy | 0,199 | igual que por tramo: «sube hoy» no existe antes del 3-nov |
| *Código 14-nov global (dentro de muestra)* | *0,200* | *−0,007* |
| *Código 14-nov por tramo (dentro de muestra)* | *0,189* | *−0,018; usa estas mismas subastas* |

Separar por si la subasta iba competida no se puede: no hay `bid_count` en el tramo de entrenamiento.

Con las pujas fijas, en la prueba +4,7 % habría ganado 10 de 23 (43 %, IC 26–63 %); la curva reajustada decía 33 %. +12 % habría ganado 12 de 23 (52 %, 33–71 %); la curva decía 51 %.

Calibración por cubos (las 23 subastas aparecen en cada cubo):

| Cubo de probabilidad | 0,2–0,4 | 0,4–0,6 | 0,6–0,8 | 0,8–1,0 |
|---|---:|---:|---:|---:|
| Global reajustada: dice / real (IC) | 0,33 / 0,40 (0,31–0,50) | 0,53 / 0,52 (0,42–0,62) | 0,68 / **0,84** (0,75–0,90) | 0,80 / 0,96 (0,79–0,99) |
| Por tramo: dice / real (IC) | 0,33 / 0,40 (0,31–0,50) | 0,53 / 0,51 (0,41–0,61) | 0,69 / **0,81** (0,70–0,88) | 0,83 / **1,00** (0,91–1,00) |

Los intervalos usan pares prima × subasta, que no son independientes, así que son más estrechos de lo que deberían.

**Lectura.** Cualquier curva gana de lejos a suponer que la puja fija gana: el error baja un 40 %. Partir por tramo mejora 0,008 de Brier, pero el intervalo toca el cero con 23 subastas. Las dos curvas se quedan cortas por arriba: con primas de +30 % o más, en noviembre se ganó más de lo que dicen.

Repitiendo solo con compras de rivales (40 de entrenamiento y 19 de prueba) sale lo mismo: 0,211 frente a 0,203.

## 4. Recomendación (sin implementar)

**Una sola función de caja rival, `caja_rival(equipo, instante) → {mín, probable, máx}`, la misma para pujas y cláusulas.** Tiene tres partes:

1. **El cálculo.** Libro desde 100 M, subidas sacadas de fotos sin copias, encadenadas y solo las que dejan la cláusula por encima del valor, a 1:2, más los suelos legales con el saque real. Sustituye a `books_from_activity` + `hidden_costs_from_log` (20 %, con automáticas y copias) y al primer campo que encuentra `clause_advisor._caja_rival` entre `dineroEstimado`, `saldo`, `cash_eur` y `reconstructed_cash_eur`. Hoy esas fuentes discrepan hasta 8,5 M en un mismo rival.
2. **No guardar 91,2 M.** `cash_ledgers` debe guardar el inicial de 100 M y las tres cifras. El 91,2 M resta 8,8 M a cada rival y la tabla además no resta 82 M de subidas.
3. **Una sola curva para elegir cualquier puja:** la curva por tramo que ya usa `signing_plan._esperado`. Debe usarse también donde hoy manda una prima fija: la puja de la Pizarra (+4,7 %), el techo del +10 % fuera del plan y el umbral del +12 % de ventas. Mejora a la global por poco y sin significación, pero no lo hace peor y es la que ya existe. Las primas fijas son claramente peores. Se puede volver a medir con más pujas a partir de unas 60 subastas de prueba con recuento de pujas, cuando `market_listing_log` tenga unas semanas.
