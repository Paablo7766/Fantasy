# Titularidad: cuánto acierta, cuánto cuesta y qué tocar

_Generado por `analizar.py` el 2026-11-15 13:39. Cada número sale de `resultados.json`._

## Cómo se estima hoy

1. **Once probable.** FútbolFantasy (`data-probabilidad`) y Analítica Fantasy (`chance`). Se promedian; si alguna dice titular con pico ≥ 0,70, manda el pico. El 0,50 exacto de AF se tira si FF está en ≤ 0,25 o ≥ 0,75; si las dos dan ≤ 0,20, manda la menor.
2. **Sin once.** Logística de minutos: sesgo -0,747, temporada 0,375, minutos 2,311, recortada a [0,05, 0,95].
3. **Portero.** 0' en la última → 0,03; ≥ 45' → 0,95, salvo que el once diga claramente lo contrario.
4. **xP.** `p × xP_si_titular + (1 − p) × factor_banquillo × media_revulsivo`. El descuento de Copa/Europa no se aplica (`has_midweek_cup` llega en falso).

## Qué datos hay

- Actas con desglose: 186 jugadores, jornadas J5 (9), J6 (10), J7 (134), J8 (158), J9 (165), J10 (166), J11 (165), J12 (161). La mayoría empieza en la J7. Se mide J8–J12; 46 filas de esas jornadas no tienen acta previa y quedan fuera. Cohorte medible: 769 jugador-partido.
- Hora de saque: jornadas con menos de 10 partidos con hora: J11. 18 filas sin hora de saque usan la logística (no se les busca once).
- **Onces guardados antes del saque**: la caché del scraper conserva 30 previas de FútbolFantasy y 31 de Analítica Fantasy (jornadas J10, J11, J12), además del registro diario desde el 7 de noviembre. La probabilidad que entró sale del once en 408 filas y de la logística en 361.
- Histórico 24/25 y 25/26: 22.341 filas, 375 jugadores. Otra población: no se mezcla en las cifras de 26/27.
- Etiqueta: titular si jugó ≥ 45'. La logística reconstruida solo ve minutos desde la J7 (producción veía la temporada entera desde LaLiga); en las primeras jornadas medidas es una aproximación de lo que vio la app.

MAE base del xP recalculado hoy: **2,651** en 769 filas (referencia anterior 2,70; la J8 entra). La reconstrucción del xP coincide con la base: diferencia máxima 0,001 en 619 filas.
Contra el xP que la app guardó antes del saque (130 filas, J12): diferencia media absoluta 0,745, correlación 0,870, 55,4 % con más de 0,5 puntos de diferencia. El recálculo no reproduce lo publicado: el techo se refiere al xP recalculado.

## 1. Precisión actual

De quienes tenían p ≥ 0,50, **81,1 %** jugaron ≥ 45' (IC 77,8 %–84,1 %, 578 previstos). Al revés, de quienes jugaron ≥ 45', 88,8 % tenían p ≥ 0,50. Brier 0,153 [jugador 0,137, 0,171; partido 0,134, 0,175].

La cohorte solo ve a quien tiene acta. Hay 39 jornadas sin acta entre dos actas del mismo jugador (no convocado, lesión, sanción); 19 tenían p ≥ 0,50 por la logística. Contándolas como no titulares, la precisión baja a 78,6 %.

| Probabilidad | n | Precisión ≥ 0,50 | Sensibilidad | Precisión ≥ 0,70 | Brier |
|---|---:|---:|---:|---:|---:|
| Lo que entró (once o logística) | 769 | 81,1 % | 88,8 % | 85,7 % | 0,153 |
| Logística sola | 769 | 78,8 % | 89,6 % | 84,3 % | 0,164 |
| Once solo (filas con once) | 408 | 84,8 % | 92,7 % | 89,8 % | 0,132 |
| Logística en esas mismas filas | 408 | 80,5 % | 94,1 % | 86,9 % | 0,151 |

En el conjunto, lo que entró da Brier 0,153 frente a 0,164 de la logística sola (con la lectura actual del once oficial de AF, ver «Hallazgo»). Sin las filas de once oficial (725): 0,161 frente a 0,164, Δ -0,0034 [jugador -0,0111, 0,0047; partido -0,0114, 0,0047], sin separarse del ruido. El once se separa de la logística cuando están FF y AF a la vez (sección 5).

Sin las jornadas con que se ajustaron los pesos (queda J8, J12): precisión 80,0 %, Brier 0,161 (logística sola 0,170).

Tramo alto (p ≥ 0,80, el que entra en el once): 314 filas, 89,5 % titulares (IC 85,6 %–92,4 %); 11 no jugaron y 22 jugaron 1–44'.

Calibración de lo que entró (tramos con n < 30 no se leen):

| Tramo | n | p media | Frecuencia | IC |
|---|---:|---:|---:|---|
| [0,0, 0,2) | 50 | 0,04 | 2,0 % | 0,4 %–10,5 % |
| [0,2, 0,4) | 95 | 0,32 | 31,6 % | 23,1 %–41,5 % |
| [0,4, 0,6) | 137 | 0,49 | 62,8 % | 54,4 %–70,4 % |
| [0,6, 0,8) | 173 | 0,70 | 75,1 % | 68,2 %–81,0 % |
| [0,8, 1,0] | 314 | 0,87 | 89,5 % | 85,6 %–92,4 % |

Por puesto:

| Puesto | n | Precisión ≥ 0,50 | Brier |
|---|---:|---:|---:|
| DF | 265 | 83,3 % | 0,148 |
| DL | 163 | 76,8 % | 0,167 |
| MC | 271 | 78,8 % | 0,183 |
| PT | 70 | 94,7 % | 0,030 |

Por jornada:

| Jornada | n | Precisión ≥ 0,50 | Brier |
|---|---:|---:|---:|
| J8 | 122 | 73,5 % | 0,194 |
| J9 | 160 | 76,7 % | 0,187 |
| J10 | 165 | 84,8 % | 0,135 |
| J11 | 163 | 83,6 % | 0,125 |
| J12 | 159 | 84,4 % | 0,136 |

**Fuga medida** (capturas guardadas después del saque de ese partido, 211 filas, jornadas J10, J12): precisión 89,4 %, sensibilidad 95,4 %, Brier 0,091; quien fue titular tenía de media p = 0,82. Tras el saque las fuentes no suben a los titulares: los hunden. Es el mecanismo del fallo del 46 %. Clubes, tramos y antelación están en el JSON.

## 2. Los dos techos

Mismo xP condicional, solo cambia p (619 filas con xP 2.0; 150 sin acta de titular previa quedan fuera, sin imputar).

- **Estructural** (media de |xP(p) − xP(realidad)|, no depende de si marcó): **1,302 [jugador 1,190, 1,419; partido 1,150, 1,462]** puntos por jugador y partido.
- **Realizada** (MAE con p menos MAE con la realidad): 0,350 [jugador 0,238, 0,472; partido 0,265, 0,440]. MAE con p 2,672, con el oráculo 2,321.
- Contra la logística sola en las mismas filas: MAE 2,732; Δ (lo que entró − logística) -0,060 [jugador -0,106, -0,014; partido -0,111, -0,013].
- Filas en que el corte 0,50 acierta: 499, MAE 2,605. Falla: 120, MAE 2,947.

| Fallo | n | Puntos estructurales | Cuota del total |
|---|---:|---:|---:|
| Previsto titular, jugó 0' | 34 | 95,4 | 11,8 % |
| Previsto titular, jugó 1–44' (minutos, no once) | 69 | 218,4 | 27,1 % |
| Previsto suplente, jugó ≥ 45' | 17 | 31,4 | 3,9 % |

Un once perfecto recuperaría 126,8 de 805,7 puntos estructurales (15,7 %), 0,205 por jugador y partido. El resto es la probabilidad intermedia de los aciertos y la banda de 1–44'.

## 3. Las causas que más puntos cuestan

51 fallos del corte 0,50 en 526 filas (banda 1–44' aparte: 93). Una causa por fallo, en orden.

| Causa | Fallos | Puntos | Cuota | Tasa de fallo con / sin | ¿Se separa del ruido? |
|---|---:|---:|---:|---|---|
| roja o doble amarilla en el acta anterior | 0 | 0 | 0,0 % | — / 9,7 % | — |
| 5.ª/10.ª/15.ª amarilla cerrada en la jornada anterior | — | — | — | no medible | — |
| portero que no jugó la anterior | 0 | 0 | 0,0 % | — / 9,7 % | — |
| recién llegado (menos de 3 partidos previos) | 4 | 12,3 | 9,7 % | 11,1 % / 9,3 % | no (harían falta más de 100 jornadas) |
| vuelta tras un 0' siendo titular en al menos la mitad de lo anterior | 4 | 4,5 | 3,5 % | 16,0 % / 9,4 % | no (harían falta ~79 jornadas) |
| Europa o Copa en los 4 días previos | 14 | 40,7 | 32,1 % | 10,5 % / 9,4 % | no (harían falta más de 100 jornadas) |
| descanso de 3 días o menos | 5 | 13,2 | 10,4 % | 11,7 % / 8,9 % | no (harían falta ~57 jornadas) |
| descanso de 10 días o más (vuelta de parón) | 7 | 23,3 | 18,4 % | 11,7 % / 9,5 % | no (harían falta más de 100 jornadas) |
| sin causa conocida | 17 | 32,9 | 25,9 % | 9,7 % / — | — |

Tres primeras por puntos: Europa o Copa en los 4 días previos, descanso de 10 días o más (vuelta de parón), descanso de 3 días o menos.
- No medible: las actas guardadas empiezan en la J7 y no se puede contar la amarilla acumulada desde la J1.
- En 26/27 las actas de la mayoría empiezan en la J7: antes de la J10 todo jugador tiene menos de 3 partidos previos. Solo se mide desde la J10.
- Las actas de 26/27 no traen «estado»: la vuelta de lesión no está en los datos (0 filas).
- Cambio de entrenador: no hay dato.
- El club es el del partido (actas), no el actual.

## 4. Señales: qué mejora y qué no

Referencia: la probabilidad de producción. Una señal solo mejora si el Brier baja con intervalo fuera de cero en la muestra grande **y**, congelada, baja el MAE del xP en 26/27.

| Señal | Activa (hist. / 26/27) | Δ Brier muestra grande | Δ MAE xP 26/27 | ¿Mejora? |
|---|---|---|---|---|
| descanso 3 o menos | 1.953 / 231 | -0,0010 [jugador -0,0014, -0,0007; partido -0,0013, -0,0007] | -0,006 [jugador -0,026, 0,014; partido -0,024, 0,011] | no (~53 jornadas para salir del ruido) |
| recien llegado | 1.250 / 67 | -0,0004 [jugador -0,0007, -0,0001; partido -0,0006, -0,0002] | 0,001 [jugador -0,012, 0,014; partido -0,015, 0,016] | no |
| sancion conocida | — / 0 | — | — | no |
| europa o copa 4 dias | — / 237 | -0,0009 [jugador -0,0028, 0,0009; partido -0,0023, 0,0006] | 0,006 [jugador -0,006, 0,017; partido -0,002, 0,015] | no (~13 jornadas para salir del ruido) |
| racha, k=5, J−1, hueco, rotación, reemplazo (11 nov, citado) | — | -0,0206 en 24/25+25/26 | 0,0212 de Brier en 26/27 | no |
| eventos/xG, Gradient FC, minutos dado titular y la ablación del 10 de noviembre: descartadas antes, no se repiten | — | — | — | no |

Regla ingenua (1 si el anterior tuvo ≥ 45'): en el histórico Brier 0,240 (0/1) y 0,218 (recortada) frente a 0,176; en 26/27 0,268 y 0,244 frente a 0,153.
Regla del portero (Δ Brier con regla menos sin ella): histórico -0,0343 [jugador -0,0506, -0,0183; partido -0,0431, -0,0253]; 26/27 fuera de J9–J11 -0,0407 [jugador -0,0802, 0,0045; partido -0,0802, 0,0071].

- descanso 3 o menos: Histórico: descanso entre partidos de LaLiga. 26/27: calendario con Europa y Copa.
- recien llegado: Histórico: menos de 3 filas previas en la temporada, que incluye el arranque de liga (J2–J3) además de fichajes. 26/27: solo desde la J10, porque las actas de la mayoría empiezan en la J7.
- sancion conocida: Solo roja o doble amarilla del acta anterior; la 5.ª/10.ª/15.ª amarilla no es medible (tarjetas desde la J7). Sin muestra histórica. El sancionado no tiene acta la jornada siguiente, así que la cohorte casi nunca lo ve: ver «huecos».
- europa o copa 4 dias: Solo hay calendario de 26/27: se ajusta con jornadas anteriores de 26/27 y la muestra es corta.

## 5. Fuentes de once

Filas con FF y AF antes del saque: 237, 24 partidos, jornadas J10, J11, J12. Mínimo para declarar ganador: 200 filas y 4 partidos.

| Fuente | Brier | Precisión ≥ 0,50 | Δ Brier vs logística |
|---|---:|---:|---|
| ff sola | 0,129 | 84,3 % | -0,0210 [jugador -0,0417, -0,0014; partido -0,0412, -0,0023] |
| af sola | 0,121 | 84,3 % | -0,0281 [jugador -0,0500, -0,0093; partido -0,0605, -0,0013] |
| media | 0,120 | 86,3 % | -0,0295 [jugador -0,0506, -0,0098; partido -0,0573, -0,0062] |
| pico si titular produccion | 0,117 | 85,3 % | -0,0323 [jugador -0,0526, -0,0134; partido -0,0567, -0,0107] |
| logistica | 0,150 | 80,7 % | — |
| combinacion preescrita | 0,144 | 80,7 % | -0,0058 [jugador -0,0141, 0,0015; partido -0,0144, 0,0011] |

Ganador: **pico si titular produccion**.

Diagnóstico, fuera de la elección: AF sola con la lectura de antes del arreglo (30 filas de página con once oficial) daba Brier 0,202; con la lectura actual, 0,121.

## Hallazgo (arreglado): el once oficial de AF entraba como p = 0

AF, ~1 h antes del saque, publica el once oficial: chance = 0 para todos y esTitular verdadero en los 22. Antes del arreglo el parser lo leía como p = 0 y estado «duda»; ahora lee esTitular como 1/0 (`_af_official_xi`).

Filas cuya p salió de una de esas páginas: 44 (4 partidos, jornadas J10, J11); 28 eran titulares oficiales y la lectura antigua les daba de media p = 0,51.

| Lectura | Brier | Precisión ≥ 0,50 | Sensibilidad |
|---|---:|---:|---:|
| Antes del arreglo (chance = 0) | 0,273 | 89,5 % | 60,7 % |
| Ahora (esTitular como 1/0) | 0,027 | 93,3 % | 100,0 % |

Δ Brier (ahora − antes) -0,2455 [jugador -0,3678, -0,1357; partido -0,3154, -0,1100]. Δ MAE del xP -0,907 [jugador -1,704, -0,116; partido -1,573, -0,421] en 36 filas con xP 2.0.
Producción descarta solo los partidos ya empezados; entre la publicación del once oficial y el saque lee estas páginas. La alineación se bloquea en el primer partido de la jornada, así que pesa sobre todo en ese partido y en el mercado de esas horas.

## Qué implementar, con qué ganancia y qué no tocar

- Arreglado: la lectura del once oficial de AF (chance = 0 con esTitular) pasa a leer esTitular como 1/0. Δ Brier -0,2455 en 44 filas, Δ MAE del xP -0,907. Es un fallo de lectura, no una señal nueva.
- Ninguna señal nueva pasa los dos filtros (Brier en la muestra grande y MAE del xP en 26/27). No se implementa ninguna.
- Techo disponible: un once perfecto ahorraría 0,205 puntos estructurales por jugador y partido (de 1,302 totales). Es el margen máximo de cualquier mejora de titularidad.
- Fuente: la mezcla de producción (pico si titular) es la que mejor puntúa y se separa de la logística. No cambiarla.
- Guardar el once antes de cada saque (FF y AF por partido, con hora) es lo que hace medible todo lo anterior: hoy solo hay 3 jornadas reconstruibles desde la caché (J10, J11, J12).
- No tocar: pesos de la logística, regla del portero, ajustes por club y las señales del 11 de noviembre.
