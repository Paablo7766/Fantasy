# Contexto del algoritmo actual (v1.x)

Documento de referencia para el diseño **v2.0** del motor predictivo y de pujas. Describe únicamente el **cerebro analítico** y el **modelo de datos**; no cubre despliegue, proxies ni capas HTTP de presentación.

**Comandos CLI que materializan el estado:** `market`, `squads`, `trends`, `optimize`, `flip`, `needs`, `market-intel`, `plan`, `own-intel`, `clause-intel`. La fuente de verdad operativa es la salida JSON de `toolbox/*` cruzada con `context/SKILL.md`.

---

## 1. Diccionario de datos actual

### 1.1 Identidad y emparejamiento (persistente)

| Entidad / tabla | Campos | Uso analítico |
|-----------------|--------|----------------|
| **`player_links`** | `player_id`, `source`, `external_id`, `external_name`, `club`, `position`, `confidence`, `manual`, `updated_at` | Enlaces LALIGA ↔ fuente externa. `confidence ≥ 0.85` habilita señales scrapeadas en decisiones. |
| **`match_audits`** | `player_id`, `source`, `external_name`, `candidate_name`, `confidence`, `reason`, `created_at` | Emparejamientos dudosos (0.60–0.85) o ambiguos; no alimentan métricas automáticas. |
| **`price_snapshots`** | `player_id`, `day` (Europe/Madrid), `league_id`, `market_value`, `market_value_change`, `stored_at` | Histórico diario de valor LALIGA; motor `own_*` (ritmo, puja, señal). Mínimo **3 días** con deltas para pujas propias. |
| **`cash_ledgers`** | `league_id`, `team_id`, `manager_name`, `initial_budget_eur`, `premiums_eur`, `purchases_eur`, `clauses_eur`, `sales_eur`, `reconstructed_cash_eur`, `observed_cash_eur`, `balanced`, `gap_eur`, `ignored_events`, `events` (JSON), `fingerprint`, `updated_at` | Caja reconstruida por equipo; input de **puja de liga** y riesgo rival. |
| **`scraper_cache`** | Cuerpo HTTP cacheado por URL | Solo almacén de respuestas externas; no es feature store analítico. |

**Umbral global de matching:** `MATCH_THRESHOLD = 0.85`. Por debajo, AF no cuenta como motivo positivo en `market-intel`; titularidad/forma scrapeada no entra en `optimize` vía `trend_usable`.

---

### 1.2 Jugador — API LALIGA Fantasy (normalizado)

Campos de `normalize_player` / catálogo unificado (`catalog_from_documents`):

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `player_id` | string | ID maestro del jugador. |
| `player_team_id` | string | Instancia en plantilla de un equipo. |
| `name`, `nickname` | string | Identificación UI. |
| `position_id`, `position` | int / enum | `POR`, `DEF`, `MC`, `DEL`. |
| `club` | string | Equipo real. |
| `image_url` | URL | Desde catálogo `/competition/1/players`. |
| `market_value` | int € | Valor de mercado fantasy. |
| `market_value_change` | int € | Variación **ya aplicada** de la API (`marketValueChange` y alias). **Hoy siempre `null`**: ninguna respuesta de la API trae el campo (ver nota abajo). |
| `average_points` | float | Media de puntos fantasy en API. |
| `week_points` | float[] | Últimas **5** jornadas (`weekPoints` / `lastStats`). |
| `buyout_clause` | int € | Cláusula de rescisión. |
| `is_shielded` | bool | Jugador blindado (no clausulable). |
| `player_status` | string | Estado oficial (`injured`, `doubtful`, …). |
| `fitness` | string | Derivado de `player_status` (`lesionado`, `duda`, `disponible`). |
| `clause_lock` | objeto | `present`, `is_locked`, `expires_at`, `local_date`, `local_time`, `local_clock`, `timezone`, `epoch_ms`. Hora/minuto en Europe/Madrid. |

**Listing de mercado** (`normalize_listing`): además `market_id`, `sale_price`, `seller_team_id`, `seller_manager`, `bids[]` (`amount`, `team_id`, `manager_name`), `leading_bid`, `listing_expires_at`, `listing_expires_local_time`.

**Equipo / liga** (`normalize_squad`, seeds): `team_id`, `manager_id`, `manager_name`, `fantasy_team_name`, `rank`, `points`, `cash`, `is_self`, `players[]`.

#### Nota: `marketValueChange` no existe en la API (24-oct-2026)

Comprobado sobre los 116 cuerpos cacheados del proyecto, los 173 objetos
`playerMaster` y las 864 filas del catálogo de competición: **ninguna respuesta
de LaLiga trae `marketValueChange`** (ni `marketValueChange1`,
`dailyMarketValueChange` ni `marketChange`). El payload real de mercado trae
`marketValue`, `salePrice` y `expirationDate`; nada de variación. El fixture de
`tests/test_phase1.py` que la incluye es sintético.

Consecuencias, y cómo se comporta el motor ahora:

1. `_market_value_change` devuelve `null`, así que `market_value_change` queda
   `null` en catálogo y listados. Es lo correcto: no se inventa.
2. `price_snapshots.market_value_change` **solo** acepta el campo oficial. Antes
   caía a `price_delta` (la estimación de FútbolFantasy), y eso dejaba un
   histórico que parecía oficial y era de un tercero. Contrastado contra el
   dashboard: 135 de 135 coincidían con `ff_price_delta`, cero discrepancias.
3. `compute_price_kinematics_and_sell_signal` y `deltas_from_history` derivan el
   delta de la **diferencia de `market_value` entre capturas**, que es la verdad
   medida. La columna guardada solo se usa cuando no hay dos valores que restar.
   Con un hueco de varios días (p. ej. falta el 23), la diferencia es lo que de
   verdad pasó en el tramo, no un delta de un día.
4. El delta publicado es siempre **hacia atrás** (ya aplicado). Contrastado con
   el histórico: 442 coincidencias hacia atrás frente a **0 de 573** hacia
   delante. No anticipa el cierre de las 14:08, así que no hay arbitraje.
5. Tamaño real del movimiento (778 observaciones): mediana 1,24 %, p90 2,58 %,
   máximo 6,73 %, y **cero casos por encima del 10 %** (la banda del market
   maker). Aun siendo forward, no habría ventaja explotable.

---

### 1.3 Jugador — documento `trends` (enriquecido)

Cada fila en `trends.players[]` fusiona catálogo LALIGA + intel externa + motores AF/own.

#### Mercado y precio

| Campo | Origen típico |
|-------|----------------|
| `fantasy_price`, `sale_price`, `on_market` | API |
| `market_value_change`, `price_delta` | API → FF mercado (`diferencia1`) → fallback valor−venta |
| `price_direction` | `up` / `down` / `flat` según `price_delta` |
| `acceleration` | Fútbol Fantasy mercado (`data-aceleracion`) |
| `flip_candidate` | Lista rising/falling, `own_market_signal==up`, o `af_market_signal==up` |
| `transfermarkt_value_eur`, `gap_eur`, `value_ratio` | Transfermarkt / valor LALIGA |

#### Titularidad y disponibilidad

| Campo | Origen |
|-------|--------|
| `p_titular` | FF mercado → **once probable FF/AF** (pisa mercado) → fallback `week_points` |
| `p_titular_source` | `scraper` \| `week_points` |
| `lineup_status`, `lineup_source` | FF / AF alineaciones (`titular`, `suplente`, `duda`, `baja`, `fuera`) |
| `fitness`, `fitness_detail` | FF lesionados / JP / API |
| `sanction` | `{ yellow_cards, on_verge (≥4 amarillas), suspended }` |
| `af_injury`, `af_suspension` | Analítica Fantasy |

#### Forma (`form` dict) — prioridad Understat → FBref → Sofascore → Jornada Perfecta

| Métrica | Significado |
|---------|-------------|
| `xg`, `xa` | Expected goals/assists (Understat manda) |
| `key_passes`, `duels_won`, `clearances`, `saves` | FBref / Sofascore |
| `minutes`, `starts`, `minutes_pct` | Tiempo de juego |
| `average_rating` / `rating` / `note` | Nota Sofascore o AF form |
| `jp_tip`, `jp_projected_points`, `jp_multiplier`, `jp_racha` | Jornada Perfecta |
| `source` | Cadena de fuentes que aportaron (`understat+fbref`, …) |
| `fdr`, `home`, `opponent`, `opponent_xg`, `opponent_xga` | Understat fixture |

#### Partido próximo (`fixture`)

`opponent`, `opponent_id`, `home`, `kickoff`, `fdr` (1–5), `opponent_xg`, `opponent_xga`.

#### Analítica Fantasy (`af_*`, solo si matching ≥ 0.85)

| Campo | Contenido |
|-------|-----------|
| `af_price_delta`, `af_market_value` | Mercado AF |
| `af_ideal_bid`, `af_max_bid` | Puja ideal/máxima AF |
| `af_market_signal`, `af_signal_strength`, `af_predicted_delta` | Predicción de mercado AF |
| `af_expected_points`, `af_ceiling_points` | Puntos jornada AF |
| `af_goal_probability`, `af_assist_probability` | Probabilidades AF |
| `af_points_per_million` | ROI puntos/€ |
| `af_form`, `af_set_pieces`, `af_calendar`, `af_recommendation_pct` | Forma, balón parado, calendario |
| `af_titular_delta` | Diferencia titularidad local vs AF mercado |
| `af_injury`, `af_suspension` | Estado médico/disciplinario |

Listas globales en `trends`: `af_prediction_rising/falling`, `af_oracle_points`, `af_oracle_chollos`, `af_in_form`.

#### Motor propio (`own_*`)

| Campo | Contenido |
|-------|-----------|
| `own_ideal_bid`, `own_max_bid` | Puja desde histórico `price_snapshots` + proyección |
| `own_market_signal`, `own_signal_strength`, `own_predicted_delta` | Señal de mercado propia |
| `own_expected_points`, `own_ceiling_points` | E[pts] OPTA simplificado + Poisson |
| `own_goal_probability`, `own_assist_probability` | P(gol/asist) condicionadas a titularidad |
| `own_points_per_million` | ROI |
| `own_calendar[]`, `own_recommendation_pct` | Calendario Poisson por club (λ local/visitante) |

Listas: `own_prediction_rising/falling`.

#### Metadatos de cruce

| Campo | Uso |
|-------|-----|
| `matching_confidence` | Mínimo de confianzas de fuentes enlazadas |
| `matches` | Mapa `source → { external_name, external_id, confidence, manual }` |

**Nota:** El documento `trends` **no** expone un `expected_points` OPTA agregado en raíz del jugador (solo vía `own_*`, `af_*` o cálculo ad hoc en `flip`/`optimize`). El campo `price_delta_3` aparece en reglas de venta pero **no se rellena** en el pipeline de ingesta actual.

#### Derivados en vista de plantilla propia (dashboard)

Sobre jugadores de `squads` cruzados con `trends`: `clause_multiple`, `is_at_risk`, `sell_signal`, `exposed_clause_rule` → filas `shield`, `sell`, `clause_rows`.

---

### 1.4 Mercado — decisiones (`market-intel`)

Por listing: `decision` (`PUJAR`|`ESPERAR`|`NO`), `score`, `primary_motive`, `motives[]`, `reasons[]`, `missing_inputs[]`, `price_band`, `bid_eur`, `ideal_bid`, `max_bid`, `suggested_bid`, `raise_to`, `bid_limit`, `league_bid`, `stretch_bid`, `league_bid_blocked`, `jornada_ev`, `points_roi`, `overbid`, `rival_bids`, `snipe`, comparativa XI (`replaces`, `points_delta`), `fixture`.

Resumen: `market_decision_summary` (conteos, `day_budget_eur`, `markets_left`, stats de guerras de liga).

---

### 1.5 Once óptimo (`optimize`)

Por jugador en `xi` / `benched` / `excluded`: `p_titular`, `expected_points` (OPTA+Relevo si existe), `relevo_bonus`, `objective`, `components` (`xg`, `xa`, `minutes_factor`, `fixture_factor`, `jp_factor`), `p_titular_source`, `excluded_reason`.

Globales: `formation`, `counts`, `gaps`, `market_fills`, `objective`, `matchday_void`, `void_reasons`, `cash_eur`, `penalties` (λ infinito para huecos/caja negativa).

---

### 1.6 Rivales y caja (`needs`)

Por rival: `depth` por posición, `thin_positions`, `lacks_replacements`, `lacks_liquidity`, `cash_eur`, `cash_is_ceiling`, `clause_alerts[]`.

`history`: `war_count`, `median_premium`, `p75_premium`, `buy_count`, `priced_count`, `bomb_count`, `samples[]`, `cash[]`.

---

### 1.7 Histórico de actividad (eventos normalizados)

Por evento: `team_id`, `manager_id`, `kind` (`initial`|`premium`|`buy`|`clause`|`sell`), `amount_eur`, `player_id`, `at`, `activity_type_id` (31 compra, 33 venta, 1 cláusula, 6/12/20–24 primas).

---

## 2. Fuentes de extracción

### 2.1 API oficial LALIGA Fantasy (`toolbox/net.py` → `normalize.py`)

| Recurso | Ruta principal (competition id=1) | Datos obtenidos |
|---------|-----------------------------------|-----------------|
| Ligas del usuario | `/api/v1/competition/1/leagues` | `league_id`, nombre, `own_team_id` |
| Mercado del día | `/api/v1/competition/1/league/{id}/market` (+ fallbacks v3/v4) | Listings, pujas, precios, cierre |
| Clasificación / índice equipos | `/leagues/{id}/standing`, `/teams`, ranking v5 | Seeds: `team_id`, rank, puntos, plantilla embebida opcional |
| Plantilla por equipo | `/leagues/{id}/teams/{team_id}` | Jugadores, caja, cláusulas, candados |
| Actividad económica | `/leagues/{id}/activity/{page}` (paginado) | Movimientos tipados para ledgers y guerras |
| Catálogo jugadores | `/api/v1/competition/1/players` | Fotos oficiales |
| Once guardado (app) | `/teams/{team}/lineup` | Alineación guardada (no es recomendación del solver) |

TTL internos orientativos: mercado ~corto; plantillas ~minutos; actividad según refresh de `needs`.

---

### 2.2 Fútbol Fantasy (HTML)

| URL | Parser | Campos |
|-----|--------|--------|
| `…/analytics/laliga-fantasy/mercado` | `parse_market_board` | `p_titular`, `price_delta` (`diferencia1`), `acceleration`, posición, club |
| `…/laliga/lesionados` | `parse_fitness_board` | `fitness`, detalle |
| `…/laliga/sancionados` | `parse_sanction_board` | `suspended` |
| `…/laliga/apercibidos` | `parse_warning_board` | tarjetas amarillas, `on_verge` |
| `…/laliga/posibles-alineaciones` + `/partidos/{id}-…` | `fantasy_scraper` | Probabilidad titular, rol FF, lesión en ficha |

---

### 2.3 Analítica Fantasy (HTML / RSC embebido)

| URL | Datos |
|-----|-------|
| `…/fantasy-la-liga/mercado` | Valor, subida, titularidad |
| `…/fantasy-la-liga/puja-ideal` | `pujaIdeal`, `pujaMaxima`, expected points |
| `…/fantasy-la-liga/prediccion-de-mercado` | Señal up/down, delta predicho |
| `…/fantasy-la-liga/predicciones` | Puntos, techo, P(gol/asist), pts/M€ |
| `…/la-liga/jugadores-lesionados` / `…/sancionados` | Bajas |
| `…/oraculo-fantasy/la-liga` | Rankings oráculo |
| `…/la-liga/calendario-predictor` | Calendario con `recommendationPct`, dificultad, marcador |
| `…/la-liga/balon-parado` | Roles córners/penaltis/faltas |
| `…/jugadores-en-forma` (+ `/jornada-{n}`) | Media reciente, conteo señales |
| `…/la-liga/alineaciones-probables` | `lineupBlock`: chance, `esTitular` |

---

### 2.4 Estadística de rendimiento

| Fuente | Endpoint / página | Métricas |
|--------|-------------------|----------|
| **Understat** | `getLeagueData/La_liga/{season}` | xG, xA, minutos, fixtures, xG/xGA equipos → **FDR** |
| **FBref** | 5 tablas La Liga (shooting, passing, defense, keepers, playing time) | xG, xA, pases clave, duelos, despejes, paradas, minutos |
| **Sofascore** | `api/v1/unique-tournament/8/season/{season}/top-players/overall` (configurable) | xG, xA, rating, minutos, duelos, … |
| **Jornada Perfecta** | `…/mercado/?competition=laliga` (`marketCaching` JSON) | tip, multiplicador, racha, injured/doubt |
| **Transfermarkt** | API búsqueda jugadores (rate limit 2 req/3s) | Valor de mercado real € (muestra priorizada ~24 jugadores “con señal”) |

Prioridad en `form`: **Understat** → FBref → Sofascore → JP (solo rellena huecos).

---

### 2.5 Fuentes expertas (opcionales, `experts.py`)

Don Qui (AF), alineaciones El Bielsa (Predicted11), menciones Azteca — **no** entran en puntuación OPTA ni en `market-intel`; enriquecimiento cualitativo con matching ≥ 0.85.

---

### 2.6 Datos generados internamente (no scrape)

| Proceso | Salida |
|---------|--------|
| `persist_and_apply_own_intel` | Upsert diario en `price_snapshots` + campos `own_*` |
| `books_from_activity` | Ledgers + histórico de primas de compra |
| `EntityResolver` | Escritura `player_links` / `match_audits` |
| Caché JSON `phase3://optimize/{hash}` | Resultado ILP reciente (120 s) |

---

## 3. Reglas de negocio vigentes (formalización)

### 3.1 Puntuación OPTA esperada (motor `analyzer.expected_opta_points`)

Solo modela **gol** y **asistencia** desde xG/xA; no modela penaltis, tarjetas ni portería a cero salvo en el motor `own_intel` (Poisson).

Para posición \(p \in \{\mathrm{POR},\mathrm{DEF},\mathrm{MC},\mathrm{DEL}\}\):

\[
\text{base} = xG \cdot g_p + xA \cdot 3
\]

con \(g_{\mathrm{POR}}=g_{\mathrm{DEF}}=6\), \(g_{\mathrm{MC}}=5\), \(g_{\mathrm{DEL}}=4\).

**Factor minutos** \(m \in [0.4, 1]\):

- Si `minutes_pct ≥ 0.6` → \(m = 1\).
- Si no: \(m = \max(0.4, \text{share}/0.6)\) con share = minutos/(90×titularidades) o `minutes_pct`.

**Factor partido** (Understat): `fixture_mult = FDR_POINTS_MULT[fdr] × (1.05 si local)`.

**Jornada Perfecta:** `total *= jp_multiplier` si ≠ 1.

**Bonus Relevo:** entero \(b \in [0,4]\) solo si viene en datos; **no se infiere**.

**Objetivo de jornada (ILP):**

\[
\text{objective} = w_p \cdot p_{\text{titular}} \cdot w_e \cdot (\text{base\_ajustada} + b)
\]

con \(w_p = w_e = 1\) por defecto. Si \(p_{\text{titular}}\) es null → objective = 0 (el jugador puede entrar solo para completar 11).

**Titularidad** (cascada):

1. Scrape con matching usable.
2. `p_titular` en roster API.
3. Fallback: \(p_{\text{titular}} = \min(1,\ 0.2 \times \#\{\text{jornadas en } week\_points \text{ con puntos} > 0\})\) (máx. 5 jornadas).

**Elegibilidad XI:** excluido si lesión/sanción (`player_status` API manda sobre scrape).

---

### 3.2 Once óptimo (ILP PuLP)

- Maximizar \(\sum \text{objective}_i x_i\) con exactamente 11 jugadores y una formación válida (7 esquemas: 3-4-3 … 5-4-1).
- **Anulación de jornada:** si elegibles < 11, caja < 0, o imposible cubrir formación → `matchday_void`, objective = 0; se devuelve mejor **parcial** + `gaps` + `market_fills` (listings más baratos por hueco).
- Penalización de huecos no cubiertos en heurística parcial: coste proxy \(10^{12}\) € por slot sin oferta en mercado.

---

### 3.3 Señal de venta (`sell_signal`)

Subida previa si `acceleration > 0` **o** `price_delta_3 > 0` (campo hoy **no poblado** en ingesta).

Venta si:

- Subida previa y delta oficial del día ≤ 0, **o**
- `price_delta_3 > 0` y `acceleration ≤ 0`.

Delta oficial (`official_price_delta`): `market_value_change` → `price_delta` FF → `market_value − sale_price`.

---

### 3.4 Riesgo de cláusula propia

| Regla | Condición |
|-------|-----------|
| **`is_at_risk`** | `buyout_clause / market_value ≤ 1.25` |
| **Regla A (chollo)** | `average_points ≥ 3` y múltiplo ≤ **1.6** |
| **Regla B (media-alta)** | `average_points ≥ 6` y múltiplo ≤ **2.2** (A gana si ambas) |

Clausulazos rivales (`bidding`): rival directo (|rank − rank_propio| ≤ 3), posición al mínimo (`POR≥1, DEF≥3, MC≥3, DEL≥1`), sin recambio asequible o sin liquidez → alertas agendadas por `clause_lock.local_date/time`.

**Subida de cláusula propia:** coste = \(\lceil (target - current) / 2 \rceil\) € (regla 1:2 del juego).

---

### 3.5 Flip / fichaje especulativo (`flip`)

Elegible si: caja post-puja ≥ 0, XI no anulado, no en plantilla, disponible, mercado no cerrado, y señal especulativa:

- `acceleration > 0`, o `own_market_signal == up`, o `af_market_signal == up`, o `flip_candidate`.

Puja operativa: **`leading_bid + 1`** o `sale_price`. Snipe: **8 s** antes de `listing_expires_at`.

---

### 3.6 Motor propio de mercado (`own_intel`)

**Histórico:** deltas diarios desde `price_snapshots` (ventana 14 días).

**Ritmo** (`project_rate`): mediana de deltas recientes; si outlier del día (>2.5× media) o cambio de signo brusco → usar media.

**Horizonte:** `days = markets_until_kickoff` (días civiles Madrid hasta partido; default 3 sin fixture).

**Puja ideal / máxima** (`compute_bids`):

- Subida (`rate > 0`):  
  `ideal_raw = price + rate × (days/2)`  
  `max_raw = price + rate×min(days,5) + rate×0.75×max(0,days−5)`  
- Bajada: ideal = price; máx = price + 0.5×|rate|×days.

Ajuste ±10% del precio según pts vs media de jornada y distancia al máximo histórico; atenuado en jugadores >40M / >80M.

**Señal:** `predicted_delta ≈ today_delta` ajustado por fitness y `(form_score−5)×20k`; strength = |predicted| / mediana(|rates|).

**E[pts] own:** Poisson por gol/asist/CS con λ derivados de xG/xA jugador y λ equipo/rival; techo = percentil 90 de simulaciones; incluye `minor` por posición y mult FDR/local.

---

### 3.7 Decisión de mercado (`market-intel`)

**Vetos → NO:** en plantilla, listing propio, lesión/sanción, caja, XI inválido, mercado cerrado.

**Banda de precio** (`price_band`): techo ideal/máx cascada `own_*` → `af_*`; compare con `bid_eur` (líder+1 o venta).

**Score** (componentes presentes suman pesos):

| Componente | Peso |
|------------|------|
| Flip / aceleración / own / AF up | +3 (AF atenuado) |
| Puntos jornada (ROI ≥ 0.5 pts/M€) | +2 × min(ROI/2, 2) |
| Hueco XI / mejora XI | +2.5 / +2 × min(Δpts/2, 2) |
| Calendario favorable (rec ≥ 60) | +1 × rec/100 |
| Calendario duro (rec ≤ 35) | −1 |
| Chollo / justo / overpay | +1.5 / +0.5 / −2 |
| Señal bajista | −2.5 |

**Motivo fuerte:** flip, puntos, hueco o mejora XI. Calendario o precio solos → ESPERAR (`senal_debil`).

**Veredicto:**

- **PUJAR:** motivo fuerte + banda bargain/fair/unknown (con salvaguardas matching) + puja factible.
- **ESPERAR:** overpay, snipe futuro, presupuesto día agotado, techo/caja.
- **NO:** veto, bajista sin contrapeso, sin motivo.

**Presupuesto diario:** si quedan \(N\) mercados hasta saque de jornada → hoy `cash // N`; hueco XI puede gastar hasta caja completa.

**Puja sugerida** (`economic_bid` + `apply_league_clearing`):

- Techo estricto = min(`own_max`, `af_max` usable).
- Sin líder: max(ideal, league_bid) si cabe.
- Con líder + snipe: min(techo, max(líder+1, league_bid)).
- **Puja de liga:** ver §3.8.

**Riesgo sobrepuja** (`overbid_risk`): cuenta rivales con `cash_eur` conocida ≥ ideal y posición floja; sin cajas → `unknown`.

---

### 3.8 Puja de liga (guerras históricas)

Para compras tipo 31 con snapshot del **mismo día** (Madrid):

- Prima \( \pi = (amount - ref) / ref \).
- Ignorar si \( \pi ≤ 2\% \) (drift post-cierre).
- Descartar bombas \( \pi > 100\% \).

Con ≥ **3** guerras de equipos que **podían pagar** el precio de salida:

- `league_bid = sale × (1 + median(π))` con redondeo a centenas de miles si estilo redondo + nudge 0–100 € + 1 €.
- `stretch_bid` usa percentil 75.
- Bloqueo si supera techo de valor o caja (`league_bid_blocked`).

**Caja rival:** `reconstructed = initial + premiums − purchases − clauses + sales`; presupuesto inicial inferido del residual de caja propia si falta en historial (aplicado a toda la liga; en rivales es **techo**). Los parámetros de riesgo (`LEAGUE_START_DATE`, `CLAUSE_INCREASE_MULTIPLIER`, `STARTING_CLAUSE_MULTIPLIER`) y del termómetro (`CASH_THERMOMETER_TAU`, `CASH_ARBITRAGE_BAND`, `CASH_UNCERTAINTY_FLOOR_EUR`) se leen del `.env` con fallback. El hueco contra la caja observada no se tapa: se publica como `arbitrage_eur` y la cota se aprieta a `tight_ceiling_eur` cuando sobra.

---

### 3.9 Calendario

**AF:** scrape calendario predictor.

**Own:** Poisson — λ propio y rival desde xG/xGA Understat; local ×1.08/0.95;  
`recommendation_pct = round(100×(P_win + 0.45×P_draw) + clip(4×E[goal_diff], −10, 15))`.

**jornada_board:** ordena clubes por `own_calendar` o `af_calendar` (primera celda).

---

### 3.10 Clausulazos recomendados (`clause-intel`)

Simula añadir jugador rival desbloqueado: `solve_lineup` con caja − cláusula; **PAGAR** si maximiza Δ objective del XI vs baseline y entra al once. Protección propia: rivales con cash y jugadores expuestos en tu XI.

---

## 4. Puntos ciegos (variables críticas no registradas o submodeladas)

### 4.1 Rendimiento futbolístico

| Laguna | Impacto |
|--------|---------|
| **Cuotas de apuestas / probabilidades de mercado** | No hay 1X2, O/U, handicaps ni closing lines; el calendario own usa solo xG Understat. |
| **xG por partido / rolling** | xG/xA son agregados de temporada; no hay forma reciente (5 partidos) unificada en feature store. |
| **Eventos OPTA no modelados en analyzer** | Portería a cero, penaltis, tarjetas, paradas no entran en `expected_opta_points` (solo en Poisson own parcialmente CS). |
| **Bonus Relevo** | No scrapeado; sin él, E[pts] OPTA está sesgada a la baja para titulares fuertes. |
| **Minutos esperados del próximo partido** | Solo proxy `p_titular` × factor minutos histórico; no minutos proyectados por partido. |
| **Estado táctico** | Sin rotaciones, copas, europeo, densidad calendario real (solo conteo días hasta partido). |
| **Presión defensiva / PPDA / tiros** | FBref parcial; no integrado en objetivo ni en own Poisson más allá de xGA rival. |
| **Emparejamientos posicionales** | No hay match-up defensa vs delantero rival. |

### 4.2 Mercado y comportamiento de managers

| Laguna | Impacto |
|--------|---------|
| **`price_delta_3` / ventanas multi-día** | Definido en `sell_signal` pero **nunca calculado** en `trends`. |
| **Historial de pujas por jugador/rival** | Solo pujas visibles en listing actual; no serie temporal de bids. |
| **Intención / watchlists rivales** | No observables. |
| **Elasticidad precio-demanda** | Proyección lineal/mediana; sin modelo de participación en subasta. |
| **Primas intradía post-14:08** | Solo drift 2% en guerras; no modelo de cierre diario oficial vs mercado secundario. |
| **Listings propios rivales (precio psicológico)** | Parcialmente vía `offer_source`; sin perfil de vendedor. |
| **Transfermarkt** | Muestra ~24 jugadores; resto sin valor real comparativo. |

### 4.3 Modelo de rivales (v2.0 objetivo explícito)

| Laguna | Impacto |
|--------|---------|
| **Función de reacción de puja** | `overbid_risk` es conteo binario, no probabilidad de sobrepuja. |
| **Caja rival incierta** | Muchos rivales sin `cash_eur`; reconstrucción es techo, no distribución. |
| **Objetivos rivales** | No se modelan necesidades de puntos vs mercado vs bloqueo. |
| **Coordinación / guerras multi-jugador** | Presupuesto día reparte PUJAR propios; no simula competencia simultánea. |

### 4.4 Calidad de datos y gobernanza

| Laguna | Impacto |
|--------|---------|
| **Incertidumbre de matching** | Binario 0.85; no propaga varianza a E[pts] ni pujas. |
| **Desalineación temporal** | Fuentes con TTL distintos (30 min – 24 h); sin timestamp por campo. |
| **OPTA vs AF vs own** | Tres escalas de “puntos esperados” sin calibración cruzada en producción. |
| **Expertos (Don Qui, Bielsa)** | No cuantificados en decisiones automáticas. |

### 4.5 Implicaciones directas para v2.0

1. **Unificar feature store** con timestamps, ventanas rolling y cuotas donde existan.  
2. **Completar o eliminar** `price_delta_3`; alimentar ventas con histórico real de snapshots.  
3. **Modelo de subasta** explícito: priors de rival + historial `activity` + caja posterior (distribución).  
4. **Calibración probabilística** OPTA ↔ Poisson own ↔ AF (backtesting por jornada).  
5. **Incorporar mercado de apuestas** como prior de goles/resultado, no solo xG Understat.  
6. **Relevo y eventos raros** como capa opcional con fuente dedicada o inferencia acotada.

---

## Referencias de código

| Área | Módulos principales |
|------|---------------------|
| XI / OPTA / cláusula / venta | `toolbox/analyzer.py` |
| Ingesta y `trends` | `toolbox/scrapers.py`, `toolbox/fantasy_scraper.py`, `toolbox/analitica_fantasy.py` |
| Motor propio | `toolbox/own_intel.py` |
| Mercado | `toolbox/market_intel.py`, `toolbox/bid_war.py`, `toolbox/bidding.py` |
| Historial liga | `toolbox/league_history.py` |
| Fixtures / FDR | `toolbox/understat.py` |
| Normalización API | `toolbox/normalize.py` |
| Reglas operativas | `context/SKILL.md` |
| Persistencia analítica | `scripts/init_supabase.sql`, `toolbox/cache.py` |

---

*Generado para planificación v2.0 — refleja el estado del repositorio en la revisión de arquitectura analítica.*
