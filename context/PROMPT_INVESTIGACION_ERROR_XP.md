# Prompt de investigación: cómo reducir el error del xP en LaLiga Fantasy

> Pega este documento entero a Argon. Está escrito para que no tenga que adivinar nada: qué es el sistema, qué hemos medido, qué ya falló y qué queremos que devuelva.

---

## 1. Tu papel

Eres un investigador de modelización deportiva y estadística aplicada. Quiero que encuentres **métodos realistas, ya probados en la práctica o en la literatura, y aplicables a mi caso** para reducir el error de predicción de puntos de LaLiga Fantasy. No quiero una lista genérica de "usa machine learning". Quiero saber **qué funciona de verdad, cuánto mejora y con qué datos**, distinguiendo la evidencia sólida de la especulación.

Sé escéptico. Si un método suena bien pero no hay evidencia de que mejore fuera de muestra con este volumen de datos, dilo. Una respuesta honesta de "esto probablemente no merece la pena" es más valiosa que una lista optimista.

## 2. Qué es el sistema

Aplicación local (Python, Windows) que ayuda a gestionar un equipo en **LaLiga Fantasy** (la oficial, temporada 2026-27). Para cada jugador calcula un **xP**: los puntos esperados en la próxima jornada. Ese número alimenta un optimizador (MILP) que elige el once y las operaciones de mercado bajo restricciones del juego (presupuesto, formación, límite de endeudamiento del 20 %, ofertas ±10 %, saldo negativo = 0 puntos).

El xP **no necesita ser exacto**: lo que más importa es **ordenar bien a los jugadores** y **acertar quién juega**. Aun así, queremos reducir el error del número.

### Cómo se calcula hoy (resumen)
- **Base de titular:** media ponderada de los puntos en partidos de ≥45', con más peso al reciente, encogida hacia un prior por puesto con `K=4`. Priors: portero 8,0, defensa 4,3, medio 4,8, delantero 5,8.
- **Factor de partido:** multiplicador según el λ de goles a favor/en contra de cada equipo (xG previo de Understat, ajustado por localía) y probabilidad de portería a cero. Rango aproximado 0,72–1,50.
- **Probabilidad de titular (`p_titular`):** logística sobre (fracción de partidos de titular de la temporada, minutos medios de las 3 últimas jornadas). Se reajusta sola con cada actualización.
- **xP publicado** = `p_titular × xP_si_titular + P(revulsivo) × media_suplente`.
- **Techo (P90):** `xP_si_titular + k · σ_jugador · √factor_partido`, con `k` = 1,5 (portero/defensa) y 1,85 (medio/delantero). No hay suelo.

## 3. Datos disponibles (y los que NO tenemos)

**Tenemos:**
- API de LaLiga Fantasy: por jugador, `lastStats` con las **últimas ~5-7 jornadas** (no toda la temporada): puntos totales, minutos y estadísticas por partido (`goals`, `goal_assist`, `total_scoring_att`, `offtarget_att_assist`, `pen_area_entries`, `ball_recovery`, `effective_clearance`, `saves`, `goals_conceded`, `yellow_card`, `red_card`, `won_contest`, `poss_lost_all`, `penalty_*`, `own_goals`). `marca_points` viene constante (−1): inútil.
- También `lastSeasonPoints` (total de la temporada anterior; solo ~60 % de los jugadores lo trae), `averagePoints`, `points`, `marketValue`, `playerStatus` (ok/injured/doubtful…).
- **Understat:** por partido y equipo (xG, xGA, PPDA, deep, resultado, fecha) de esta temporada; por jugador solo **totales de temporada** (xG, xA, tiros, pases clave, minutos), sin desglose por jornada.
- Calendario oficial (openfootball) con número de jornada.
- Integración con **The Odds API** ya escrita pero **sin clave activa** (hoy simula cuotas desde xG).

**No tenemos:**
- Histórico de temporadas anteriores a nivel de jugador-partido.
- Cuotas históricas (ni de partido ni de jugador).
- Alineaciones confirmadas pre-partido de forma automática y fiable.
- xG/xA por jugador y por partido.

Restricciones de despliegue: app local, Python con numpy/scipy (sin scikit-learn de momento), sin servidores propios; el acceso a red está restringido y cada fuente nueva requiere decisión mía. Preferimos fuentes **gratuitas o muy baratas**.

## 4. Lo que hemos medido (fiable, reproducible)

Backtest hacia delante (`scripts/backtest_xp.py`): se predice cada jugador solo con jornadas anteriores y se compara con sus puntos reales. **Jornadas 9–11, 334 filas** con al menos 2 partidos previos.

| Medida | Valor |
|---|---|
| Error absoluto medio (MAE) del xP publicado | **3,12 – 3,16** puntos |
| RMSE | ≈ 3,99 – 4,05 |
| Sesgo (predicción − real) | −0,43 (era −0,69 antes del último ajuste) |
| Modelo tonto: predecir siempre la media global | MAE 3,40 |
| Modelo ingenuo: media de todos sus partidos | MAE 3,17 |
| Modelo ingenuo: media de los partidos jugados | MAE 3,26 |

**Ruido intrínseco:** en titulares reales (≥45', n≈231), la desviación típica de los puntos por jornada es ≈ 3,8 (portero), 4,0–4,2 (defensa), 3,4–3,6 (medio), 4,4–4,6 (delantero). Media real de titulares: portero ≈ 8,3, defensa ≈ 5,0, medio ≈ 4,9, delantero ≈ 6,4.

**Error por puesto en titulares (MAE):** medio ≈ 2,7 · portero ≈ 2,9 · defensa ≈ 3,4 · delantero ≈ 3,6.

**Capacidad de ordenar:** correlación de Spearman por jornada ≈ 0,26. De los 10 jugadores que el modelo pone arriba, **2,7 de cada 10** están realmente entre los 10 mejores (al azar: 0,7). Esos 10 hacen de media **7,1 puntos** frente a 4,3 del grupo. El modelo ingenuo "media de todos sus partidos" saca 6,7: la ventaja sobre mirar medias es modesta.

**Probabilidad de titular (el error dominante):** la tasa real de titular es 69 %. La versión antigua tenía Brier 0,201 y estaba mal calibrada (decía 22 % cuando la frecuencia real era 44 %; decía 89 % cuando era 82 %). La logística actual (validación dejando una jornada fuera) tiene Brier ≈ 0,180; acierto de titular ≈ 72,8 % frente a 69,2 % de "siempre titular". **Sigue siendo la mayor fuente de error.**

**Rival:** conocer al rival (λ real de xG previo) baja el MAE solo ≈ 0,009 y el RMSE ≈ 0,016. Un grid de pesos por puesto ganaba ≈ 0,03 de MAE pero solo en la muestra donde se buscó; no lo adoptamos.

**Techo (P90):** lo superan un 13,1 % de los titulares (objetivo 10 %). Por puesto: defensa 22 %, portero 11 %, delantero 8 %, medio 7 %. Recalibrar `k` por puesto con validación dejando una jornada fuera da 12,7 %: la cola es inestable entre jornadas.

## 5. Lo que YA probamos y NO funcionó (no lo repitas sin una razón nueva)

Validación: dejar una jornada fuera, 279 titulares, jornadas 8–11.

- **Regresión ridge sobre el residuo con eventos por 90'** (goles, asistencias, tiros, pases clave, entradas al área, recuperaciones, despejes, pérdidas, duelos ganados): todas las combinaciones **empeoran** el MAE (3,16 → 3,25–3,58). Con ~5 partidos por jugador hay más ruido que señal.
- **Ajustar K con datos:** el MAE es plano entre K=4 y K=16 (3,15–3,16). K=4 ya vale.
- **Priors estimados con las otras jornadas** en lugar de fijos: bajan el sesgo (−0,46 → −0,14) pero suben el MAE (3,16 → 3,18).
- **Decaimiento del EWMA** entre 0,1 y 0,5: indistinguible.
- **`lastSeasonPoints` como señal:** débil e inconsistente por puesto (negativa en portero/defensa).
- **Escala global (×1,19)** para anular el sesgo: sube el MAE (3,12 → 3,18).

**Limitación central de todos estos experimentos:** solo ~5 jornadas por jugador y 3 jornadas de prueba. Puede que métodos que fallan aquí funcionen con varias temporadas. Eso es justo lo que quiero que evalúes.

## 6. Lo que quiero que investigues

Prioriza por **ganancia esperada ÷ coste** y por **viabilidad real con mis datos**. Cubre al menos estos ejes:

1. **Probabilidad de titular / minutos esperados** (mi mayor error). ¿Qué señales y modelos predicen mejor la titularidad? Alineaciones probables publicadas, calendario europeo y descansos, patrones de rotación por entrenador, lesiones y sanciones, minutos recientes con decaimiento, tipo de partido. ¿Qué precisión se logra en la práctica y de qué fuentes (gratuitas) sale?
2. **Modelo de puntos por componentes.** Descomponer los puntos del Fantasy en sus fuentes (minutos, goles, asistencias, portería a cero, paradas, tarjetas, bonus) y modelar cada una con la distribución adecuada (Poisson, binomial, jerárquico bayesiano) en lugar de promediar puntos. ¿Cuánta mejora real da frente a una media encogida? ¿Qué enfoque (modelos jerárquicos bayesianos, Empirical Bayes, partial pooling por puesto/equipo) funciona con poco historial por jugador?
3. **Fuentes externas de señal.** Cuotas de casas de apuestas (partido y, sobre todo, mercados de jugador: marcar en cualquier momento, asistir, tarjetas, tiros), xG/xA por partido y por jugador, datos de posesión o tiros. ¿Cuánto añade cada una sobre lo que ya tenemos? ¿Qué fuentes son gratuitas o baratas y legales de usar?
4. **Qué ha hecho la comunidad de Fantasy Premier League y similares.** Modelos publicados (FPL Review, Fantasy Football Hub, LiveFPL, repos abiertos, papers) y sus errores reportados. ¿Qué MAE/R² por jugador-jornada consiguen los mejores? Es mi **techo realista de referencia**.
5. **Estimación del suelo de ruido.** Dado que la desviación de los puntos por jornada es ≈ 3,4–4,6, ¿cuál es el MAE mínimo alcanzable de forma teórica o empírica? Quiero saber cuánto margen queda de verdad.
6. **Predicción de distribución, no solo de media.** Cuantiles o distribuciones (P10, P50, P90) bien calibradas por puesto, con colas asimétricas (los defensas están sesgados a la derecha por portería a cero y goles). ¿Qué métodos son estables con poca muestra?
7. **Métricas correctas.** Para elegir plantilla, ¿qué debo optimizar y reportar: MAE de puntos, calidad del ranking (Spearman, NDCG, acierto del top-N), o puntos reales del once elegido? ¿Cómo evitar engañarme con tan poca muestra (intervalos de confianza, bootstrap)?
8. **Datos a empezar a guardar ya** para poder validar dentro de 10–15 jornadas lo que hoy no se puede probar.

## 7. Qué debes devolver

Un informe con esta estructura, en español:

1. **Resumen ejecutivo (≤ 10 líneas):** cuánto error es reducible de verdad y por qué vías.
2. **Tabla priorizada de métodos.** Para cada uno:
   - Qué es, en una frase.
   - **Ganancia esperada** (en MAE/RMSE, Brier o calidad del ranking) y **de dónde sale esa cifra** (paper, repo, experimento publicado, o estimación tuya marcada claramente como tal).
   - **Datos necesarios** y si los tengo (sección 3).
   - **Coste y dificultad** de implementarlo en Python local (numpy/scipy).
   - **Riesgo de sobreajuste** con mi volumen de datos.
   - **Evidencia:** sólida / media / débil / especulativa.
3. **Fuentes de datos recomendadas:** nombre, qué aporta, gratuito o de pago, límites, legalidad de uso, formato.
4. **Plan por fases** (qué hacer ya, qué en 1 mes, qué en 3 meses), con el criterio de validación de cada fase.
5. **Qué NO merece la pena hacer** y por qué (incluye lo que ya probamos si encuentras razones para pensar que funcionaría con otro enfoque o más datos).
6. **Preguntas abiertas** que no se pueden contestar sin más datos.

## 8. Reglas de rigor

- **Cita las fuentes** (título, autores o repositorio, año). Si no puedes verificar una cifra, dilo.
- **Separa hechos de estimaciones.** Marca cada cifra como "publicada", "calculada por mí" o "intuición".
- **No inventes resultados** ni asumas que un método funciona porque suena razonable.
- **Ten en cuenta mi tamaño de muestra.** Con ~5 jornadas de historial por jugador y un backtest de 3 jornadas, desconfía de cualquier mejora menor a ≈ 0,05 de MAE.
- **Prioriza lo aplicable.** Un método con +2 % de mejora que puedo implementar mañana vale más que uno con +10 % que necesita datos que no existen.
- Si algo de este documento te parece mal planteado (una métrica, una conclusión), **dímelo**.

## 9. Criterio de éxito

Al terminar quiero poder decidir con datos: **qué dos o tres cosas hago primero, qué datos empiezo a guardar hoy, y cuánto error espero quitar de forma realista** (con un rango, no una promesa).
