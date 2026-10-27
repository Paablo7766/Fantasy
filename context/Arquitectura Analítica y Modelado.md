Arquitectura Analítica y Modelado Cuantitativo v2.0 para LaLiga Fantasy
El análisis de la arquitectura actual (v1.x) revela que las limitaciones operativas del sistema no provienen de carencias en la recolección de datos, sino de asunciones de linealidad e independencia estocástica en sus cuatro núcleos matemáticos: la estimación de tasas de gol (
λ), la proyección de puntos esperados (
E[Pts]), la determinación de precios de reserva en subastas (league_bid) y la detección cinemática de puntos de inflexión en el mercado (sell_signal). La transición hacia la versión 2.0 sustituye estas heurísticas estáticas por un marco unificado de inferencia bayesiana, procesos de Poisson bivariados con corrección de dependencia, simulación de eventos discretos truncados, teoría de subastas de primer precio bajo restricciones asimétricas de liquidez y filtrado diferencial de series temporales.   

Bloque 1: Integración de Mercados de Apuestas (Implied Probabilities) y Calendario v2.0
El motor actual (understat.py y own_intel.py) proyecta la dificultad del calendario utilizando medias agregadas de temporada de goles esperados (
xG y 
xGA) bajo una distribución de Poisson independiente con multiplicadores fijos de localía (1.08 y 0.95). Este enfoque ignora la información de consenso más eficiente del mercado financiero deportivo: las líneas de cierre y pre-partido de las casas de apuestas (sharp bookmakers como Pinnacle), las cuales ya descuentan bajas tácticas, motivación competitiva, clima y ajustes de emparejamiento.   

1.1 Arquitectura de Extracción y Presupuesto de Cuotas en Python
Para alimentar el módulo toolbox/scrapers.py sin incurrir en costes de infraestructura ni bloqueos por rate-limiting, el pipeline de ingesta v2.0 implementa una jerarquía de tres niveles con persistencia en la tabla existente scraper_cache.   

Nivel	Proveedor / Fuente	Identificador de Competición / Ruta	Mercados Extraídos	Límite Gratuito y Estrategia de Caché
Nivel 1 (Primario)	The Odds API (v4)	soccer_spain_la_liga (/v4/sports/soccer_spain_la_liga/odds)	h2h (1X2), totals (O/U 2.5), btts (Ambos Marcan)	
500 créditos/mes gratuitos. Coste: 1 crédito por mercado y región (regions=eu). Consultando 2 veces por jornada (48h y 2h antes del inicio de la jornada), el consumo mensual es de unos 24 créditos. 

Nivel 2 (Sharp / Tiempo Real)	SharpAPI	/odds/soccer (league=La Liga)	moneyline_3way, totals, asian_handicap (Pinnacle / Bet365)	
Nivel gratuito de 12 peticiones/minuto sin tarjeta de crédito con líneas de 2 casas de referencia (incluyendo Pinnacle). Ideal para refresco pre-cierre de mercado. 

Nivel 3 (Goleadores y Fallback)	Sofascore API Interna / OddsPortal	/api/v1/event/{event_id}/odds/1/all	1X2, O/U 2.5, BTTS y Cuotas a Goleador (Anytime Goalscorer)	
Sin coste de API key; aprovecha la sesión y el EntityResolver ya operativo para Sofascore en player_links con TTL de 6 horas en scraper_cache. 

1.2 Eliminación del Margen (De-Vigging) mediante el Método de Shin y Power
La suma de las probabilidades implícitas brutas de un mercado con 
n resultados mutuamente excluyentes supera la unidad debido al margen de la casa de apuestas (overround o vig), definido como 
B−1, donde 
B=∑ 
i=1
n
​
 b 
i
​
  y 
b 
i
​
 =1/O 
i
​
  representa el inverso de la cuota decimal 
O 
i
​
 . La normalización proporcional clásica (
p 
i
​
 =b 
i
​
 /B) asume que el margen se distribuye uniformemente entre todos los resultados, lo cual introduce un sesgo sistemático al sobreestimar la probabilidad de los resultados menos probables (favorite-longshot bias).   

Para limpiar las cuotas pre-partido en own_intel.py, el motor v2.0 implementa el Método de Shin (1992, 1993), el cual modela la formación de precios del operador asumiendo la presencia de una fracción 
z∈[0,1) de apostadores con información privilegiada (insiders) frente a una proporción 
(1−z) de volumen recreativo. Bajo el equilibrio de maximización de beneficios de Shin, la probabilidad real limpia 
p 
i
​
 (z) de cada resultado 
i∈{1,…,n} viene dada por la ecuación cuadrática cerrada en función de 
z:   

p 
i
​
 (z)= 
2(1−z)
z 
2
 + 
B
4(1−z)b 
i
2
​
 
​
 

​
 −z
​
 
El parámetro de asimetría informativa 
z es la única raíz en el intervalo abierto 
(0, 
n−1
B−1
​
 ) que satisface la condición de normalización axiomática:   

f(z)= 
i=1
∑
n
​
  
2(1−z)
z 
2
 + 
B
4(1−z)b 
i
2
​
 
​
 

​
 −z
​
 −1=0
Para mercados tripartitos (
n=3, como 1X2: Local, Empate, Visitante), 
z se resuelve numéricamente mediante el algoritmo de Brent (scipy.optimize.brentq) en menos de 15 iteraciones con tolerancia 
10 
−12
 . Para mercados binarios (
n=2, como Over/Under 2.5 o Ambos Marcan - BTTS), la identidad algebraica 
z 
2
 +4(1−z)b 
i
2
​
 /B

​
  degenera en una reducción lineal donde el método de Shin equivale exactamente al método aditivo (
z→0 en el límite simétrico). Por consiguiente, para mercados de dos resultados (
n=2) y cuotas de goleador, el motor v2.0 aplica el Método Potencial (Power Method), que resuelve el exponente único 
k>1 tal que:   

i=1
∑
n
​
 ( 
O 
i
​
 
1
​
 ) 
k
 =1⟹p 
i
pwr
​
 =b 
i
k
​
 
Este enfoque garantiza que todas las probabilidades transformadas permanezcan estrictamente acotadas en 
(0,1) y corrige con precisión el sesgo en mercados desbalanceados. La magnitud del error inducido por la normalización proporcional frente a los métodos no lineales se aprecia empíricamente al evaluar un mercado desbalanceado de goles (Over 2.5 a cuota 1.285 y Under 2.5 a cuota 3.60, cuyas probabilidades implícitas brutas del 77.8% y 27.8% suman 105.6%, reflejando un margen del 5.6%) junto con su respectivo mercado 1X2 cotizado en 1.675 / 4.61 / 4.14.   

Método de Eliminación de Vig	Supuesto Microeconómico	Cuota Justa Over 2.5	Cuota Justa Under 2.5	Cuotas Justas 1X2 (Local / Empate / Visitante)
Cuota Bruta (Pinnacle con Vig)	Precio de venta con margen del 5.6% incluido	1.285 (77.8%)	3.600 (27.8%)	
1.675 / 4.610 / 4.140 

Proporcional (Multiplicativo)	Margen repartido de forma uniforme sin corregir sesgo	1.357 (73.7%)	3.802 (26.3%)	
1.768 / 4.866 / 4.370 

Método de Shin (z = 5.7%)	Protección del operador frente a volumen informado (insiders)	1.333 (75.0%)	4.003 (25.0%)	
Convergencia intermedia hacia consenso sharp

[cite: 4]

Método Power (k = 1.107)	Escala logarítmica que penaliza la sobreapuesta al longshot	1.320 (75.8%)	4.127 (24.2%)	
1.726 / 5.040 / 4.498 

En el resultado menos probable (Under 2.5, proxy directo de partidos cerrados y de alta probabilidad de portería a cero), el método proporcional estima una cuota justa de 3.802, mientras que el método Power la sitúa en 4.127 y Shin en 4.003, lo que representa una divergencia de hasta el 9% en el precio real del suceso sobre el mismo mercado. Cuando la cuota máxima del partido es inferior a 3.45 (encuentros equilibrados sin favorito claro), todos los métodos convergen prácticamente al mismo valor, pero en duelos asimétricos de LaLiga (Real Madrid o Barcelona frente a equipos de zona baja), prescindir de Shin o Power distorsiona severamente la probabilidad extraída de portería a cero.   

1.3 Inversión de Cuotas a Tasas de Gol (
λ 
mkt
​
 ) y Probabilidad Exacta de Portería a Cero (
P(CS))
El fallo estructural del modelo de Poisson independiente utilizado en la v1.x radica en asumir que los goles del equipo local (
X) y visitante (
Y) son variables aleatorias independientes. En el análisis empírico de más de 40.000 partidos de las grandes ligas europeas (incluyendo LaLiga, Premier League, Serie A y Bundesliga), los marcadores reales presentan una agrupación pronunciada en resultados bajos que el supuesto de independencia es incapaz de capturar: los empates 0–0 ocurren entre el 8.2% y el 9.5% de las veces, mientras que un modelo de Poisson independiente con parámetros típicos (
λ 
H
​
 =1.45,λ 
A
​
 =1.10) predice apenas un 5.9%, incurriendo en una subestimación sistemática cercana al 35%. De forma análoga, los empates 1–1 se registran entre el 11.5% y el 13.2% de los encuentros frente al 9.4% estimado bajo independencia, al tiempo que las victorias mínimas por 1–0 y 0–1 resultan sobreestimadas entre un 8% y un 15%.   

Para extraer las tasas implícitas del mercado 
( 
λ
^
  
mkt,H
​
 , 
λ
^
  
mkt,A
​
 ) y la probabilidad real de Portería a Cero (
P(CS)) corrigiendo esta anomalía, se formula el modelo bivariado de Dixon-Coles (1997). La distribución conjunta de probabilidad para un marcador 
(x,y) se define como:   

P(X=x,Y=y∣λ 
H
​
 ,λ 
A
​
 ,ρ)=τ 
λ 
H
​
 ,λ 
A
​
 ,ρ
​
 (x,y)⋅ 
x!
λ 
H
x
​
 e 
−λ 
H
​
 
 
​
 ⋅ 
y!
λ 
A
y
​
 e 
−λ 
A
​
 
 
​
 
donde el factor de correlación de marcadores bajos 
τ 
λ 
H
​
 ,λ 
A
​
 ,ρ
​
 (x,y) modifica únicamente las cuatro celdas críticas del estado del partido:   

τ 
λ 
H
​
 ,λ 
A
​
 ,ρ
​
 (x,y)= 
⎩

⎨

⎧
​
  
1−λ 
H
​
 λ 
A
​
 ρ
1+λ 
H
​
 ρ
1+λ 
A
​
 ρ
1−ρ
1
​
  
si x=0,y=0
si x=0,y=1
si x=1,y=0
si x=1,y=1
en cualquier otro caso
​
 
Una propiedad matemática fundamental de la matriz 
τ 
λ 
H
​
 ,λ 
A
​
 ,ρ
​
 (x,y) es que preserva estrictamente las distribuciones marginales de Poisson. Al sumar sobre todos los goles posibles del equipo local 
x∈[0,∞) cuando el visitante anota 
y=0 goles, los términos dependientes de 
ρ se cancelan exactamente:   

P(CS 
H
​
 )=P(Y=0)= 
x=0
∑
∞
​
 P(X=x,Y=0)=e 
−λ 
A
​
 
 e 
−λ 
H
​
 
 [(1−λ 
H
​
 λ 
A
​
 ρ)+λ 
H
​
 (1+λ 
A
​
 ρ)+ 
x=2
∑
∞
​
  
x!
λ 
H
x
​
 
​
 ]=e 
−λ 
A
​
 
 
Sin embargo, aunque la expresión marginal 
P(Y=0)=e 
−λ 
A
​
 
  se mantiene intacta, el valor numérico de 
λ
^
  
mkt,A
​
  y 
λ
^
  
mkt,H
​
  obtenido al invertir las cuotas de apuestas cambia sustancialmente cuando se incluye 
ρ∈[−0.20,0.05] en el ajuste de la matriz 1X2, O/U 2.5 y BTTS. Dadas las probabilidades limpias del mercado 
p 
mkt
​
 =(P 
shin
​
 (H),P 
shin
​
 (D),P 
shin
​
 (A),P 
pwr
​
 (O2.5),P 
pwr
​
 (BTTS)), el motor resuelve el problema de optimización no lineal restringida:   

( 
λ
^
  
mkt,H
​
 , 
λ
^
  
mkt,A
​
 , 
ρ
^
​
 )=arg 
λ 
H
​
 ,λ 
A
​
 ,ρ
min
​
  

​
  
m∈{H,D,A}
∑
​
 w 
m
​
 (P 
DC
​
 (m)−P 
shin
​
 (m)) 
2
 +w 
O2.5
​
 (P 
DC
​
 (O2.5)−P 
pwr
​
 (O2.5)) 
2
 +w 
BTTS
​
 (P 
DC
​
 (BTTS)−P 
pwr
​
 (BTTS)) 
2
  

​
 
sujeto a la restricción de positividad celular 
max(− 
λ 
H
​
 
1
​
 ,− 
λ 
A
​
 
1
​
 )<ρ<min( 
λ 
H
​
 λ 
A
​
 
1
​
 ,1). Una vez convergido el optimizador, las probabilidades limpias de Portería a Cero a nivel de equipo son:   

P(CS 
local
​
 )=e 
− 
λ
^
  
mkt,A
​
 
 ,P(CS 
visitante
​
 )=e 
− 
λ
^
  
mkt,H
​
 
 
1.4 Modelo Híbrido Bayesiano (Market Prior + Rolling xG con Decaimiento Exponencial)
Para evitar depender exclusivamente de las cuotas (especialmente al inicio de la semana cuando la liquidez del mercado es baja) o exclusivamente del 
xG acumulado de temporada, el sistema v2.0 modela la tasa de goles verdadera de cada equipo mediante una combinación bayesiana en el espacio logarítmico (equivalente a una distribución conjugada Gamma-Poisson donde la media posterior es una media geométrica ponderada por la precisión de cada fuente).   

Primero, en lugar de la media aritmética simple de toda la temporada de Understat, se calcula la tasa de creación ofensiva y concesión defensiva sobre una ventana móvil ponderada exponencialmente (EWMA) de los últimos 
W=5 partidos, anclada con un regresor a la media de la temporada para evitar sobreajuste por varianza de muestras pequeñas. Para un equipo 
i que se enfrenta al rival 
j, sean 
{xG 
i,k
​
 } 
k=1
5
​
  y 
{xGA 
j,k
​
 } 
k=1
5
​
  sus registros en las últimas 5 jornadas, ordenados desde el más reciente (
k=1) hasta el más antiguo (
k=5). Se definen los pesos de decaimiento temporal de Dixon-Coles 
ω 
k
​
 =exp(−ξ⋅(k−1)) con tasa de olvido 
ξ=0.25 por jornada:   

xG

  
i
(5)
​
 = 
∑ 
k=1
5
​
 ω 
k
​
 
∑ 
k=1
5
​
 ω 
k
​
 ⋅ 
xG

  
i,k
adj
​
 
​
 ,donde  
xG

  
i,k
adj
​
 =xG 
i,k
​
 ⋅( 
xGA
  
rival(i,k)
​
 
xG
  
liga
​
 
​
 )
El ajuste 
xG
  
liga
​
 / 
xGA
  
rival(i,k)
​
  normaliza el 
xG producido en cada uno de los últimos 5 partidos según la fortaleza defensiva del oponente al que se enfrentó en dicha jornada. A continuación, se combina la forma reciente de 5 partidos (
θ 
rec
​
 =0.60) con la línea base de la temporada (
θ 
sea
​
 =0.40) para obtener el estimador estadístico puro 
λ
^
  
stat,H
​
  y 
λ
^
  
stat,A
​
 :   

λ
^
  
stat,H
​
 =γ 
home
​
 ⋅ 
xG
  
liga
​
 
(θ 
rec
​
  
xG

  
H
(5)
​
 +θ 
sea
​
  
xG
  
H
​
 )⋅(θ 
rec
​
  
xGA

  
A
(5)
​
 +θ 
sea
​
  
xGA
  
A
​
 )
​
 
λ
^
  
stat,A
​
 =γ 
away
​
 ⋅ 
xG
  
liga
​
 
(θ 
rec
​
  
xG

  
A
(5)
​
 +θ 
sea
​
  
xG
  
A
​
 )⋅(θ 
rec
​
  
xGA

  
H
(5)
​
 +θ 
sea
​
  
xGA
  
H
​
 )
​
 
donde 
γ 
home
​
 =1.08 y 
γ 
away
​
 =0.95 corresponden a los factores de campo ya calibrados en la base de código actual.   

Finalmente, la actualización bayesiana fusiona la distribución a priori del mercado de apuestas (
λ
^
  
mkt
​
 ) con la verosimilitud estadística (
λ
^
  
stat
​
 ) en función del tiempo restante hasta el inicio del partido (
Δt 
kickoff
​
  en horas). Dado que la eficiencia informativa del mercado de apuestas aumenta monótonamente a medida que se acerca el cierre de líneas (Closing Line), el peso del mercado 
w 
mkt
​
 (Δt) sigue una función logística inversa:   

w 
mkt
​
 (Δt 
kickoff
​
 )=w 
min
​
 +(w 
max
​
 −w 
min
​
 )⋅exp(− 
72
max(0,Δt 
kickoff
​
 )
​
 )
con 
w 
min
​
 =0.55 (a más de 5 días del partido) y 
w 
max
​
 =0.82 (en las horas previas al inicio de la jornada). Los parámetros finales 
λ 
local
​
  y 
λ 
visitante
​
  que alimentan tanto own_calendar[] como el motor de puntos esperados son:

λ 
local
​
 =( 
λ
^
  
mkt,H
​
 ) 
w 
mkt
​
 
 ⋅( 
λ
^
  
stat,H
​
 ) 
1−w 
mkt
​
 
 ,λ 
visitante
​
 =( 
λ
^
  
mkt,A
​
 ) 
w 
mkt
​
 
 ⋅( 
λ
^
  
stat,A
​
 ) 
1−w 
mkt
​
 
 
De igual modo, si se dispone de la cuota a goleador en cualquier momento (Anytime Goalscorer, 
O 
AG,i
​
 ) para el jugador 
i, su probabilidad limpia de anotar al menos un gol es 
P 
mkt
​
 (G 
i
​
 ≥1)=(1/O 
AG,i
​
 ) 
k 
AG
​
 
 , de donde se despeja la intensidad goleadora individual implícita en el mercado 
λ 
mkt,G,i
​
 =−ln(1−P 
mkt
​
 (G 
i
​
 ≥1)), que se combina con su 
xG individual mediante el mismo ponderador 
w 
mkt
​
 .

1.5 Implementación en Python (toolbox/own_intel.py y toolbox/understat.py)
Python
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np
from scipy.optimize import brentq, minimize
from scipy.stats import poisson


@dataclass
class MatchMarketProjection:
    lambda_home: float
    lambda_away: float
    rho_dc: float
    p_home_win: float
    p_draw: float
    p_away_win: float
    p_cs_home: float
    p_cs_away: float
    recommendation_pct_home: int
    recommendation_pct_away: int


def devig_shin_3way(odds_1x2: Tuple[float, float, float]) -> Tuple[np.ndarray, float]:
    """
    Limpia el overround de un mercado 1X2 aplicando el modelo de H.S. Shin (1993).
    Resuelve la proporción de trading informado z mediante el método de Brent.
    """
    odds = np.asarray(odds_1x2, dtype=np.float64)
    if np.any(odds <= 1.0):
        raise ValueError("Las cuotas decimales deben ser estrictamente mayores que 1.0.")
    
    b = 1.0 / odds
    booksum = float(np.sum(b))
    if booksum <= 1.0 + 1e-9:
        return b / booksum, 0.0

    def shin_probs(z: float) -> np.ndarray:
        return (np.sqrt(z**2 + 4.0 * (1.0 - z) * (b**2) / booksum) - z) / (2.0 * (1.0 - z))

    def objective(z: float) -> float:
        return float(np.sum(shin_probs(z)) - 1.0)

    z_upper = min(0.49, (booksum - 1.0) / (len(odds) - 1.0) - 1e-9)
    try:
        z_star = float(brentq(objective, 1e-12, max(1e-6, z_upper), xtol=1e-12))
        p_clean = shin_probs(z_star)
    except Exception:
        z_star = 0.0
        p_clean = b / booksum

    p_clean /= np.sum(p_clean)
    return p_clean, z_star


def devig_power_2way(odds_pair: Tuple[float, float]) -> np.ndarray:
    """
    Limpia el overround de mercados binarios (Over/Under 2.5, BTTS) usando Power Method,
    evitando la degeneración aditiva de Shin en n=2 y corrigiendo el longshot bias.
    """
    odds = np.asarray(odds_pair, dtype=np.float64)
    b = 1.0 / odds
    if np.sum(b) <= 1.0 + 1e-9:
        return b / np.sum(b)

    def objective(k: float) -> float:
        return float(np.sum(np.power(b, k)) - 1.0)

    try:
        k_star = float(brentq(objective, 1.0, 5.0, xtol=1e-12))
        p_clean = np.power(b, k_star)
    except Exception:
        p_clean = b / np.sum(b)

    return p_clean / np.sum(p_clean)


def _dixon_coles_grid(lh: float, la: float, rho: float, max_goals: int = 10) -> np.ndarray:
    """Construye la matriz conjunta de probabilidad de marcador exacto bajo Dixon-Coles."""
    goals = np.arange(max_goals)
    pmf_h = poisson.pmf(goals, lh)
    pmf_a = poisson.pmf(goals, la)
    grid = np.outer(pmf_h, pmf_a)

    # Aplicación vectorizada de la función tau(x, y) en las 4 esquinas inferiores
    grid[0, 0] *= (1.0 - lh * la * rho)
    grid[0, 1] *= (1.0 + lh * rho)
    grid[1, 0] *= (1.0 + la * rho)
    grid[1, 1] *= (1.0 - rho)

    grid = np.clip(grid, 0.0, None)
    total = np.sum(grid)
    return grid / total if total > 0 else grid


def invert_market_to_dixon_coles(
    odds_1x2: Tuple[float, float, float],
    odds_ou25: Optional[Tuple[float, float]] = None,
    odds_btts: Optional[Tuple[float, float]] = None,
) -> Tuple[float, float, float]:
    """
    Invierte las probabilidades limpias del mercado (1X2 + O/U 2.5 + BTTS)
    para obtener (lambda_mkt_home, lambda_mkt_away, rho_dc).
    """
    p_1x2, _ = devig_shin_3way(odds_1x2)
    p_h_target, p_d_target, p_a_target = p_1x2[0], p_1x2[1], p_1x2[2]

    p_o25_target = devig_power_2way(odds_ou25)[0] if odds_ou25 else None
    p_btts_target = devig_power_2way(odds_btts)[0] if odds_btts else None

    idx_grid = np.add.outer(np.arange(10), np.arange(10))
    over25_mask = idx_grid >= 3

    def loss_fn(params: np.ndarray) -> float:
        lh, la, rho = float(params[0]), float(params[1]), float(params[2])
        # Restricción de viabilidad de tau
        if 1.0 - lh * la * rho <= 1e-4 or 1.0 + lh * rho <= 1e-4 or 1.0 + la * rho <= 1e-4:
            return 1e4

        grid = _dixon_coles_grid(lh, la, rho, max_goals=10)
        ph = float(np.sum(np.tril(grid, -1)))
        pd = float(np.sum(np.diag(grid)))
        pa = float(np.sum(np.triu(grid, 1)))

        err = 1.5 * ((ph - p_h_target) ** 2 + (pd - p_d_target) ** 2 + (pa - p_a_target) ** 2)
        if p_o25_target is not None:
            po25 = float(np.sum(grid[over25_mask]))
            err += 2.0 * ((po25 - p_o25_target) ** 2)
        if p_btts_target is not None:
            pbtts = float(np.sum(grid[1:, 1:]))
            err += 1.2 * ((pbtts - p_btts_target) ** 2)
        else:
            # Regularización suave de rho hacia el prior empírico de LaLiga (-0.08)
            err += 0.05 * ((rho - (-0.08)) ** 2)
        return err

    res = minimize(
        loss_fn,
        x0=np.array([1.45, 1.10, -0.06]),
        bounds=[(0.15, 4.80), (0.15, 4.80), (-0.22, 0.12)],
        method="L-BFGS-B",
    )
    return float(res.x[0]), float(res.x[1]), float(res.x[2])


def compute_rolling_xg_rates(
    home_last5_xg: List[float],
    home_last5_opp_xga_avg: List[float],
    home_last5_xga: List[float],
    home_last5_opp_xg_avg: List[float],
    away_last5_xg: List[float],
    away_last5_opp_xga_avg: List[float],
    away_last5_xga: List[float],
    away_last5_opp_xg_avg: List[float],
    season_home_xg: float,
    season_home_xga: float,
    season_away_xg: float,
    season_away_xga: float,
    league_avg_xg: float = 1.32,
    xi_decay: float = 0.25,
) -> Tuple[float, float]:
    """
    Calcula (lambda_stat_home, lambda_stat_away) combinando una ventana móvil EWMA
    de 5 partidos ajustada por dificultad de oponente con la base de la temporada.
    """
    def _ewma_adjusted(metric_seq: List[float], opp_baseline_seq: List[float], fallback: float) -> float:
        if not metric_seq or len(metric_seq) != len(opp_baseline_seq):
            return fallback
        n = len(metric_seq)
        # El índice 0 es el partido más reciente, índice n-1 el más antiguo
        weights = np.exp(-xi_decay * np.arange(n))
        adj_vals = [
            m * (league_avg_xg / max(0.5, opp_b))
            for m, opp_b in zip(metric_seq, opp_baseline_seq)
        ]
        return float(np.sum(weights * np.asarray(adj_vals)) / np.sum(weights))

    h_xg_5 = _ewma_adjusted(home_last5_xg, home_last5_opp_xga_avg, season_home_xg)
    h_xga_5 = _ewma_adjusted(home_last5_xga, home_last5_opp_xg_avg, season_home_xga)
    a_xg_5 = _ewma_adjusted(away_last5_xg, away_last5_opp_xga_avg, season_away_xg)
    a_xga_5 = _ewma_adjusted(away_last5_xga, away_last5_opp_xg_avg, season_away_xga)

    h_atk = 0.60 * h_xg_5 + 0.40 * season_home_xg
    h_def = 0.60 * h_xga_5 + 0.40 * season_home_xga
    a_atk = 0.60 * a_xg_5 + 0.40 * season_away_xg
    a_def = 0.60 * a_xga_5 + 0.40 * season_away_xga

    lambda_stat_h = 1.08 * (h_atk * a_def) / max(0.6, league_avg_xg)
    lambda_stat_a = 0.95 * (a_atk * h_def) / max(0.6, league_avg_xg)
    return float(np.clip(lambda_stat_h, 0.2, 4.5)), float(np.clip(lambda_stat_a, 0.2, 4.5))


def build_hybrid_match_projection(
    lambda_stat_h: float,
    lambda_stat_a: float,
    odds_1x2: Optional[Tuple[float, float, float]] = None,
    odds_ou25: Optional[Tuple[float, float]] = None,
    odds_btts: Optional[Tuple[float, float]] = None,
    hours_to_kickoff: float = 48.0,
) -> MatchMarketProjection:
    """
    Fusión Bayesiana Log-Lineal (Gamma-Poisson) entre el prior de casas de apuestas
    y la verosimilitud estadística rolling xG.
    """
    if odds_1x2 is not None:
        lh_mkt, la_mkt, rho_dc = invert_market_to_dixon_coles(odds_1x2, odds_ou25, odds_btts)
        w_mkt = 0.55 + (0.82 - 0.55) * math.exp(-max(0.0, hours_to_kickoff) / 72.0)
        lh_final = math.exp(w_mkt * math.log(lh_mkt) + (1.0 - w_mkt) * math.log(lambda_stat_h))
        la_final = math.exp(w_mkt * math.log(la_mkt) + (1.0 - w_mkt) * math.log(lambda_stat_a))
    else:
        lh_final, la_final, rho_dc = lambda_stat_h, lambda_stat_a, -0.08

    grid = _dixon_coles_grid(lh_final, la_final, rho_dc, max_goals=10)
    p_home = float(np.sum(np.tril(grid, -1)))
    p_draw = float(np.sum(np.diag(grid)))
    p_away = float(np.sum(np.triu(grid, 1)))

    # Por preservación marginal de Dixon-Coles, P(Y=0) = exp(-la_final) y P(X=0) = exp(-lh_final)
    p_cs_home = math.exp(-la_final)
    p_cs_away = math.exp(-lh_final)

    goal_diff_h = lh_final - la_final
    rec_h = int(round(100.0 * (p_home + 0.45 * p_draw) + np.clip(4.0 * goal_diff_h, -10.0, 15.0)))
    rec_a = int(round(100.0 * (p_away + 0.45 * p_draw) + np.clip(-4.0 * goal_diff_h, -10.0, 15.0)))

    return MatchMarketProjection(
        lambda_home=lh_final,
        lambda_away=la_final,
        rho_dc=rho_dc,
        p_home_win=p_home,
        p_draw=p_draw,
        p_away_win=p_away,
        p_cs_home=p_cs_home,
        p_cs_away=p_cs_away,
        recommendation_pct_home=int(np.clip(rec_h, 1, 99)),
        recommendation_pct_away=int(np.clip(rec_a, 1, 99)),
    )
Bloque 2: Motor Avanzado de Puntos Esperados 
E[Pts] (Simulación Monte Carlo y OPTA Completo)
El método analyzer.expected_opta_points de la versión v1.x reduce la valoración de un jugador a la expresión lineal 
base=xG⋅g 
p
​
 +xA⋅3, multiplicada por factores heurísticos. Esta simplificación omite más del 60% de la varianza de puntos en LaLiga Fantasy: ignora los puntos por tiempo de juego, las porterías a cero, los goles encajados, las paradas, los bonos de volumen ofensivo y defensivo por tramos discretos, las penalizaciones por pérdidas de balón y el bonus algorítmico de rendimiento individual (0 a 4 puntos).   

2.1 Matriz Oficial de Puntuación OPTA y el Operador de Escalón de Poisson 
Ψ(μ,k)
En el reglamento oficial de LaLiga Fantasy, las acciones de acumulación (paradas, despejes, recuperaciones, regates, tiros a puerta, llegadas al área, goles encajados y pérdidas de balón) no otorgan fracciones de punto continuas, sino que puntúan mediante funciones escalón (
⌊X/k⌋) cada 
k eventos registrados en el partido.   

Vector / Métrica OPTA	POR	DEF	MC	DEL	Condición / Escalón (k)
Minutos en campo (< 60m / >= 60m)	+1 / +2	+1 / +2	+1 / +2	+1 / +2	
Umbral discontinuo en minuto 60 

Gol anotado	+6	+6	+5	+4	
Por cada gol (k = 1) 

Asistencia (de Gol / Sin Gol)	+3 / +1	+3 / +1	+3 / +1	+3 / +1	
Pase de gol vs ocasión clara generada 

Portería a Cero (Clean Sheet)	+4	+3	+2	+1	
Exige jugar 60 minutos o más 

Paradas realizadas	+1	0	0	0	
Cada k = 2 paradas realizadas 

Penalti Parado / Provocado	+5 / +2	0 / +2	0 / +2	0 / +2	
Evento directo por penalti 

Despejes / Balones Recuperados	+1 / +1	+1 / +1	+1 / +1	+1 / +1	
Cada k = 3 despejes / cada k = 5 recup. 

Tiros a puerta / Regates / Área	+1	+1	+1	+1	
Cada k = 2 eventos en cada métrica 

Goles encajados	-2	-2	-1	-1	
Cada k = 2 goles encajados en campo 

Pérdidas de balón	-1	-1	-1	-1	
Cada k = 8 (POR/DEF), k = 10 (MC), k = 12 (DEL) 

Amarilla / Doble Amarilla / Roja	-1 / -1 / -3	-1 / -1 / -3	-1 / -1 / -3	-1 / -1 / -3	
Penalización disciplinaria directa 

Penalti Cometido / Fallado	-2 / -2	-2 / -2	-2 / -2	-2 / -2	
Por penalti cometido o errado 

Bonus Valoración OPTA / Relevo	0 a +4	0 a +4	0 a +4	0 a +4	
Tramos de rendimiento general 

Si una métrica de conteo 
X sigue un proceso de Poisson con media esperada 
μ durante el tiempo en campo del jugador, aproximar el valor esperado del escalón mediante 
E[⌊X/k⌋]≈μ/k introduce un error positivo severo igual a 
E[(Xmodk)/k]. Por ejemplo, si un defensa promedia 
μ=1.8 despejes por partido y el juego otorga +1 punto cada 
k=3 despejes, la aproximación lineal asigna 
1.8/3=0.60 puntos, cuando el valor esperado exacto de la función escalón es apenas 0.27 puntos (un error del +122%).   

Sea 
X∼Poisson(μ). Se define el Operador de Escalón de Poisson 
Ψ(μ,k) como la esperanza matemática exacta de puntos por acumulación cada 
k eventos:

Ψ(μ,k)=E[⌊ 
k
X
​
 ⌋]= 
m=1
∑
∞
​
 P(X≥m⋅k)= 
m=1
∑
∞
​
 (1−e 
−μ
  
j=0
∑
mk−1
​
  
j!
μ 
j
 
​
 )= 
m=1
∑
∞
​
  
Γ(mk)
γ(mk,μ)
​
 
donde 
γ(s,μ)/Γ(s) es la función gamma incompleta inferior regularizada, computable de forma vectorizada e instantánea en Python mediante scipy.special.gammainc(m * k, mu) truncando la serie en 
m 
max
​
 =6 (donde la masa residual es 
<10 
−9
 ).   

2.2 Modelo de Mezcla de Minutos, Rotación Europea y Riesgo de Quinta Amarilla (on_verge)
El motor v1.x aplica un multiplicador truncado 
m∈[0.4,1.0] y multiplica el total linealmente por p_titular. En la realidad del reglamento OPTA, el minuto 60 es una barrera discontinua crítica: cruzar el umbral de 
M 
i
​
 ≥60 minutos otorga +2 puntos en lugar de +1 y habilita el cobro del bono de Portería a Cero (+4 POR, +3 DEF, +2 MC, +1 DEL). Un jugador que entra de suplente en el minuto 65 tiene 0% de probabilidad de cobrar portería a cero aunque su equipo no encaje goles.   

En la arquitectura v2.0, la distribución del tiempo de juego 
M 
i
​
 ∈[0,90] del jugador 
i en la jornada actual se descompone en un modelo de mezcla de tres estados mutuamente excluyentes condicionados a su disponibilidad médica: el estado de inactividad total (
M 
i
​
 =0) con probabilidad 
p 
0,i
​
 =1−p 
start,i
eff
​
 −p 
sub,i
eff
​
 ; el estado de titularidad (
M 
i
​
 ∣start) con probabilidad efectiva 
p 
start,i
eff
​
 ; y el estado de suplencia utilizada (
M 
i
​
 ∣sub<60) con probabilidad 
p 
sub,i
eff
​
 .

Penalización por Densidad de Calendario (Rotación UEFA) y Riesgo de Sanción (on_verge)
Sea 
p 
titular,i
​
 ∈[0,1] la probabilidad base extraída del scraper (FútbolFantasy / Analítica Fantasy). Si el club del jugador disputa competición intersemanal (Champions League, Europa League, Conference League o Copa del Rey) dentro de una ventana de 
Δd 
rest
​
 ≤4 días respecto al partido de liga, y la alineación no es aún el once confirmado del primer partido de la jornada, la probabilidad efectiva de titularidad se atenúa según el índice de fatigabilidad posicional 
ρ 
p
​
  (
ρ 
POR
​
 =0.02, 
ρ 
DEF
​
 =0.14, 
ρ 
MC
​
 =0.18, 
ρ 
DEL
​
 =0.16):   

p 
start,i
eff
​
 =p 
titular,i
​
 ⋅[1−ρ 
p
​
 ⋅exp(−0.45⋅max(0,Δd 
rest
​
 −2))⋅I(has_midweek_cup)]
Para un jugador de campo (
p

=POR) que no sale de titular, la probabilidad de entrar desde el banquillo se modela a partir de su cuota histórica de apariciones (minutes_pct y starts en form):   

p 
sub,i
eff
​
 =(1−p 
start,i
eff
​
 )⋅clip(0.65⋅p 
titular,i
​
 +0.25⋅minutes_pct 
i
​
 ,0.0,0.75)
Condicionado a ser titular, los minutos jugados siguen una distribución truncada con media 
μ 
M∣start,i
​
 =clip( 
max(1,starts 
i
​
 )
minutes 
i
​
 
​
 ,55.0,90.0) y desviación típica 
σ 
M
​
 =11.5 minutos. Si el jugador está apercibido de quinta amarilla (sanction.on_verge == True), los entrenadores tienden a sustituirlo preventivamente entre el minuto 60 y 75 si el partido está resuelto, reduciendo 
μ 
M∣start,i
​
  en 
ΔM 
verge
​
 =4.5 minutos. Por tanto, la probabilidad condicional de que un titular supere el umbral de 60 minutos es:   

P(M 
i
​
 ≥60∣start)={ 
0.985
Φ( 
σ 
M
​
 
μ 
M∣start,i
​
 −4.5⋅I(on_verge 
i
​
 )−60.0
​
 )
​
  
si p 
i
​
 =POR
si p 
i
​
 ∈{DEF,MC,DEL}
​
 
La fracción esperada de partido de 90 minutos que el jugador estará sobre el césped (
τ 
i
​
 =E[M 
i
​
 ]/90) y sus puntos esperados por tiempo de juego (
E[Pts 
min,i
​
 ]) quedan definidos exactamente como:   

τ 
i
​
 = 
90.0
p 
start,i
eff
​
 ⋅(μ 
M∣start,i
​
 −4.5⋅I(on_verge 
i
​
 ))+p 
sub,i
eff
​
 ⋅22.0
​
 
E[Pts 
min,i
​
 ]=p 
start,i
eff
​
 [1+P(M 
i
​
 ≥60∣start)]+p 
sub,i
eff
​
 ⋅1.0
Adicionalmente, cuando sanction.on_verge == True, para valoraciones de mercado y optimización multi-jornada (horizonte 
H≥2), el valor esperado de la jornada siguiente (
t+1) sufre un descuento de supervivencia por sanción igual a 
(1−p 
start,i
eff
​
 ⋅p 
yc,i
​
 ), donde 
p 
yc,i
​
  es la probabilidad de recibir tarjeta amarilla en la jornada actual 
t.   

2.3 Ecuación Maestra Desglosada por Posición
Sea 
λ 
own
​
  la tasa de goles esperados del equipo del jugador y 
λ 
opp
​
  la tasa de goles esperados del equipo rival, obtenidas ambas del modelo híbrido del Bloque 1. Se definen el multiplicador de contexto ofensivo 
Φ 
atk
​
 =λ 
own
​
 / 
xG
  
own
​
  y el multiplicador de exigencia defensiva 
Φ 
def
​
 =λ 
opp
​
 / 
xGA
  
own
​
 . Todas las métricas por 90 minutos del diccionario form (xg, xa, key_passes, duels_won, clearances, saves) se escalan por la fracción esperada de minutos 
τ 
i
​
  y el contexto del partido:   

1. Porteros (POR) y Defensas (DEF)
El rendimiento esperado combina el cobro condicional de la Portería a Cero, la penalización escalonada por cada 2 goles encajados, el volumen de paradas (exclusivo de POR) y los bonos defensivos de despejes y recuperaciones:   

E[Pts 
CS,i
​
 ]=c 
CS,p
​
 ⋅p 
start,i
eff
​
 ⋅P(M 
i
​
 ≥60∣start)⋅P(CS 
own
​
 )
donde 
c 
CS,POR
​
 =4, 
c 
CS,DEF
​
 =3 (y para centrocampistas/delanteros 
c 
CS,MC
​
 =2, 
c 
CS,DEL
​
 =1).   

La penalización por goles encajados mientras el jugador está en el campo depende de la tasa efectiva de goles rivales recibidos 
λ 
opp,i
​
 =λ 
opp
​
 ⋅τ 
i
​
  con coeficiente 
c 
GC,p
​
 =−2 para POR/DEF y 
c 
GC,p
​
 =−1 para MC/DEL:   

E[Pts 
GC,i
​
 ]=c 
GC,p
​
 ⋅Ψ(λ 
opp
​
 ⋅τ 
i
​
 ,2)
Para los Porteros (POR), el número esperado de paradas 
μ 
saves,i
​
  no es constante, sino proporcional al volumen ofensivo proyectado del rival (
λ 
opp
​
 ). Si el portero promedia 
s 
90,i
​
  paradas por 90 minutos y existe una probabilidad de penalti en contra 
p 
pen_opp
​
 ≈0.14⋅(λ 
opp
​
 /1.32) con tasa histórica de parada de penalti 
p 
save_pen
​
 ≈0.22 (+5 puntos por penalti detenido):   

μ 
saves,i
​
 =s 
90,i
​
 ⋅(Φ 
def
​
 ) 
0.65
 ⋅τ 
i
​
 
E[Pts 
keeper,i
​
 ]=1.0⋅Ψ(μ 
saves,i
​
 ,2)+5.0⋅(p 
start,i
eff
​
 ⋅p 
pen_opp
​
 ⋅p 
save_pen
​
 )
Para Defensas (DEF) (y extensible a toda la plantilla), el bono defensivo captura despejes (clearances, +1 cada 3) y balones recuperados (+1 cada 5, estimados desde duels_won y recuperaciones de FBref/Sofascore a razón de 
μ 
rec,90
​
 ≈0.85⋅duels_won 
90
​
  cuando el dato específico de recuperaciones no esté segregado):   

E[Pts 
def_vol,i
​
 ]=1.0⋅Ψ(clearances 
90,i
​
 ⋅Φ 
def
0.50
​
 ⋅τ 
i
​
 ,3)+1.0⋅Ψ(recoveries 
90,i
​
 ⋅Φ 
def
0.35
​
 ⋅τ 
i
​
 ,5)
2. Centrocampistas (MC) y Delanteros (DEL)
La producción ofensiva modela goles (
λ 
G,i
​
 ), asistencias de gol (
λ 
A,i
​
 ), asistencias sin gol (pases clave que generan ocasión manifiesta sin terminar en gol, valorados en +1 punto), penaltis provocados/fallados y los tres bonos de ataque cada 
k=2 eventos (tiros a puerta, regates completados y llegadas al área):   

λ 
G,i
​
 =xG 
90,i
​
 ⋅Φ 
atk
​
 ⋅τ 
i
​
 ,λ 
A,i
​
 =xA 
90,i
​
 ⋅Φ 
atk
​
 ⋅τ 
i
​
 
Dado que cada pase clave (key_passes) que no se convierte en gol tiene una probabilidad 
θ 
clear_chance
​
 ≈0.28 de ser catalogado por OPTA como "asistencia sin gol" (+1 punto):   

E[Pts 
direct_atk,i
​
 ]=g 
p
​
 ⋅λ 
G,i
​
 +3.0⋅λ 
A,i
​
 +1.0⋅θ 
clear_chance
​
 ⋅max(0,key_passes 
90,i
​
 ⋅Φ 
atk
​
 ⋅τ 
i
​
 −λ 
A,i
​
 )
con 
g 
POR
​
 =g 
DEF
​
 =6, 
g 
MC
​
 =5 y 
g 
DEL
​
 =4. Si el jugador figura en af_set_pieces como lanzador principal de penaltis, se añade el diferencial de eficiencia de penalti y se descuenta el riesgo de penalti fallado (-2 puntos con probabilidad 0.22 por lanzamiento).   

Los bonos de volumen de ataque y la penalización por pérdidas de balón (losses, con divisor 
k 
loss,p
​
 ∈{8,8,10,12} para POR, DEF, MC, DEL respectivamente) se expresan mediante 
Ψ:   

E[Pts 
atk_vol,i
​
 ]=Ψ(μ 
sot,i
​
 ,2)+Ψ(μ 
dribbles,i
​
 ,2)+Ψ(μ 
box_touches,i
​
 ,2)
E[Pts 
losses,i
​
 ]=−1.0⋅Ψ(μ 
losses,90,i
​
 ⋅τ 
i
​
 ,k 
loss,p
​
 )
(Nota de ingeniería de datos: cuando el scraper de FBref/Sofascore en form solo entregue xg, key_passes y duels_won sin desglosar regates o pérdidas exactas, el motor aplica priores empíricos posicionales calibrados en LaLiga: 
μ 
sot,90
​
 ≈2.6⋅xG 
90
​
 +0.25, 
μ 
drib,90
​
 ≈0.28⋅duels_won 
90
​
  para MC/DEL, y 
μ 
losses,90
​
 ≈μ 
loss_base,p
​
 +1.4⋅key_passes 
90
​
 +0.9⋅duels_won 
90
​
 , donde 
μ 
loss_base
​
 =(5.2,9.8,11.4,10.6) para POR, DEF, MC, DEL).   

2.4 Inferencia Analítica del Bonus de Valoración OPTA / Nota Sofascore (0 a 4 Puntos)
El sistema de puntuación de LaLiga Fantasy asigna entre 0 y 4 puntos adicionales en función de un índice algorítmico neto de rendimiento individual por partido (identificado en la base de código como relevo_bonus o tramo de valoración OPTA). En la versión v1.x, si este valor no viene precargado, se asume 0, introduciendo un sesgo a la baja de hasta -2.5 puntos por jornada en jugadores de alto impacto como Pedri, Bellingham o Valverde.   

En la versión 2.0, cuando relevo_bonus no está explícito, se modela una variable latente continua de rendimiento en el partido 
R 
i
∗
​
 ∼N(μ 
R,i
​
 ,σ 
R
2
​
 ) anclada en la nota media de Sofascore (form.average_rating o af_form), ajustada por la dominancia esperada de su equipo (
λ 
own
​
 −λ 
opp
​
 ) y la densidad neta de duelos y pases clave por 90 minutos:   

μ 
R,i
​
 =r 
base,i
​
 +0.14⋅(λ 
own
​
 −λ 
opp
​
 )+0.06⋅(key_passes 
90,i
​
 − 
kp
​
  
p
​
 )+0.03⋅(duels_won 
90,i
​
 − 
dw
  
p
​
 )
donde 
r 
base,i
​
  es form.average_rating (con fallback a 
6.75+0.08⋅(average_points 
i
​
 −4.0) si falta la nota de Sofascore) y 
σ 
R
​
 =0.42 es la volatilidad intrapartido de la calificación. La asignación de los puntos extra 
B 
i
​
 ∈{0,1,2,3,4} responde a un modelo Ordered Probit definido sobre cuatro umbrales de corte 
κ=(κ 
1
​
 ,κ 
2
​
 ,κ 
3
​
 ,κ 
4
​
 )=(6.75,7.10,7.45,7.90). Utilizando la propiedad de que para toda variable discreta no negativa 
E[B]=∑ 
m=1
4
​
 P(B≥m), el bonus esperado condicionado a jugar es:

E[Bonus 
OPTA,i
​
 ]=(p 
start,i
eff
​
 +p 
sub,i
eff
​
 )⋅ 
m=1
∑
4
​
 [1−Φ( 
σ 
R
​
 
κ 
m
​
 −μ 
R,i
​
 +0.35⋅I(sub)
​
 )]
2.5 Simulación Monte Carlo Vectorizada para own_expected_points y own_ceiling_points
Para poblar tanto analyzer.expected_opta_points (valor esperado exacto determinista para el solver ILP PuLP) como own_ceiling_points (percentil 90 de la distribución de puntos del jugador requerido por own_intel.py), el código v2.0 proporciona la evaluación analítica cerrada en 
O(1) y un simulador Monte Carlo vectorizado de 
N 
sim
​
 =4,000 trayectorias correlacionadas.   

Python
from __future__ import annotations
import math
from typing import Any, Dict, Optional
import numpy as np
from scipy.special import gammainc
from scipy.stats import norm

# Coeficientes oficiales LaLiga Fantasy OPTA
GOAL_PTS = {"POR": 6.0, "DEF": 6.0, "MC": 5.0, "DEL": 4.0}
CS_PTS = {"POR": 4.0, "DEF": 3.0, "MC": 2.0, "DEL": 1.0}
GC_PTS_PER_2 = {"POR": -2.0, "DEF": -2.0, "MC": -1.0, "DEL": -1.0}
LOSS_DIVISOR = {"POR": 8, "DEF": 8, "MC": 10, "DEL": 12}
BASE_LOSSES_90 = {"POR": 5.2, "DEF": 9.8, "MC": 11.4, "DEL": 10.6}
UEFA_FATIGUE_RHO = {"POR": 0.02, "DEF": 0.14, "MC": 0.18, "DEL": 0.16}
PROBIT_THRESHOLDS = np.array([6.75, 7.10, 7.45, 7.90], dtype=np.float64)


def poisson_step_expectation(mu: float, k: int, max_steps: int = 6) -> float:
    """
    Calcula exactamente E[floor(X / k)] para X ~ Poisson(mu) usando la función
    gamma incompleta inferior regularizada: sum_{m=1}^M P(X >= m*k).
    """
    if mu <= 1e-6 or k <= 0:
        return 0.0
    m_vals = np.arange(1, max_steps + 1, dtype=np.float64) * k
    return float(np.sum(gammainc(m_vals, mu)))


def infer_opta_performance_bonus(
    avg_rating: float,
    lambda_own: float,
    lambda_opp: float,
    key_passes_90: float,
    duels_won_90: float,
    p_start_eff: float,
    p_sub_eff: float,
) -> float:
    """
    Infiere el Bonus de Valoración OPTA / Relevo (0 a 4 puntos) mediante un modelo
    Ordered Probit sobre la nota latente esperada del jugador en el partido.
    """
    mu_r = (
        avg_rating
        + 0.14 * (lambda_own - lambda_opp)
        + 0.06 * (key_passes_90 - 1.0)
        + 0.03 * (duels_won_90 - 4.0)
    )
    sigma_r = 0.42
    # Probabilidad de superar cada uno de los 4 umbrales siendo titular vs suplente
    p_exceed_start = 1.0 - norm.cdf((PROBIT_THRESHOLDS - mu_r) / sigma_r)
    p_exceed_sub = 1.0 - norm.cdf((PROBIT_THRESHOLDS - (mu_r - 0.35)) / sigma_r)
    
    e_bonus_start = float(np.sum(p_exceed_start))
    e_bonus_sub = float(np.sum(p_exceed_sub))
    return p_start_eff * e_bonus_start + p_sub_eff * e_bonus_sub


def compute_expected_opta_points_v2(
    player: Dict[str, Any],
    lambda_own: float = 1.35,
    lambda_opp: float = 1.25,
    p_cs_own: Optional[float] = None,
    has_midweek_cup: bool = False,
    days_rest: int = 6,
    run_monte_carlo: bool = True,
    n_sims: int = 4000,
) -> Dict[str, float]:
    """
    Motor v2.0 de Puntos Esperados (E[Pts]) y Techo (P90) para analyzer.py y own_intel.py.
    Sustituye la ecuación lineal xG/xA por el desglose OPTA completo y ajuste de rotación.
    """
    pos = str(player.get("position", "MC")).upper()
    if pos not in GOAL_PTS:
        pos = "MC"

    # 1. Elegibilidad médica y disciplinaria estricta
    status = str(player.get("player_status", "ok")).lower()
    sanction = player.get("sanction") or {}
    if status in {"injured", "suspended", "out"} or sanction.get("suspended") or player.get("af_suspension"):
        return {
            "expected_points": 0.0,
            "ceiling_points": 0.0,
            "p_start_eff": 0.0,
            "expected_minutes": 0.0,
            "inferred_bonus": 0.0,
            "next_match_survival": 1.0,
        }

    form = player.get("form") or {}
    p_titular_raw = float(player.get("p_titular") or 0.5)
    on_verge = bool(sanction.get("on_verge", False))

    # 2. Modelo de Mezcla de Minutos y Penalización por Rotación Europea
    rho_fatigue = UEFA_FATIGUE_RHO[pos]
    cup_penalty = (
        rho_fatigue * math.exp(-0.45 * max(0, days_rest - 2))
        if has_midweek_cup and days_rest <= 4
        else 0.0
    )
    p_start_eff = float(np.clip(p_titular_raw * (1.0 - cup_penalty), 0.0, 1.0))

    minutes_total = float(form.get("minutes") or 0.0)
    starts_count = float(form.get("starts") or 0.0)
    minutes_pct = float(form.get("minutes_pct") or p_titular_raw)

    if pos == "POR":
        p_sub_eff = 0.0
        mu_m_start = 90.0
        p_60_given_start = 0.985
    else:
        p_sub_eff = (1.0 - p_start_eff) * float(np.clip(0.65 * p_titular_raw + 0.25 * minutes_pct, 0.0, 0.75))
        raw_m_start = (minutes_total / starts_count) if starts_count >= 2 else (68.0 + 18.0 * minutes_pct)
        mu_m_start = float(np.clip(raw_m_start, 55.0, 90.0))
        eff_m_start = mu_m_start - (4.5 if on_verge else 0.0)
        p_60_given_start = float(norm.cdf((eff_m_start - 60.0) / 11.5))

    expected_minutes = p_start_eff * (mu_m_start - (4.5 if on_verge else 0.0)) + p_sub_eff * 22.0
    tau = expected_minutes / 90.0
    if tau <= 0.01:
        return {
            "expected_points": 0.0,
            "ceiling_points": 0.0,
            "p_start_eff": 0.0,
            "expected_minutes": 0.0,
            "inferred_bonus": 0.0,
            "next_match_survival": 1.0,
        }

    # Puntos por tiempo en campo (<60m: +1, >=60m: +2)
    pts_minutes = p_start_eff * (1.0 + p_60_given_start) + p_sub_eff * 1.0

    # 3. Normalización de tasas por 90 minutos y contexto de partido
    nineties_hist = max(1.5, minutes_total / 90.0) if minutes_total > 0 else 1.0
    # Si form.xg viene acumulado de temporada, pasamos a per-90; si ya es per-90 (<1.2), lo respetamos
    raw_xg = float(form.get("xg") or 0.0)
    raw_xa = float(form.get("xa") or 0.0)
    xg_90 = (raw_xg / nineties_hist) if (minutes_total >= 180 and raw_xg > 1.2) else raw_xg
    xa_90 = (raw_xa / nineties_hist) if (minutes_total >= 180 and raw_xa > 1.2) else raw_xa

    phi_atk = float(np.clip(lambda_own / 1.32, 0.45, 2.40))
    phi_def = float(np.clip(lambda_opp / 1.32, 0.45, 2.40))

    # 4. Impacto Ofensivo Directo y Volumen
    lam_g = xg_90 * phi_atk * tau
    lam_a = xa_90 * phi_atk * tau

    raw_kp = float(form.get("key_passes") or 0.0)
    kp_90 = (raw_kp / nineties_hist) if (minutes_total >= 180 and raw_kp > 4.0) else raw_kp
    lam_kp = kp_90 * phi_atk * tau
    pts_direct_atk = (
        GOAL_PTS[pos] * lam_g
        + 3.0 * lam_a
        + 0.28 * max(0.0, lam_kp - lam_a)
    )

    raw_duels = float(form.get("duels_won") or 0.0)
    duels_90 = (raw_duels / nineties_hist) if (minutes_total >= 180 and raw_duels > 12.0) else raw_duels

    # Volumen ofensivo escalonado (k=2)
    mu_sot = (2.6 * xg_90 + (0.25 if pos in {"MC", "DEL"} else 0.05)) * phi_atk * tau
    mu_drib = (0.28 * duels_90 if pos in {"MC", "DEL"} else 0.08 * duels_90) * tau
    mu_box = (1.8 * xg_90 + 0.9 * xa_90) * phi_atk * tau
    pts_atk_vol = (
        poisson_step_expectation(mu_sot, 2)
        + poisson_step_expectation(mu_drib, 2)
        + poisson_step_expectation(mu_box, 2)
    )

    # 5. Portería a Cero, Goles Encajados, Paradas y Volumen Defensivo
    p_cs = p_cs_own if p_cs_own is not None else math.exp(-lambda_opp)
    pts_cs = CS_PTS[pos] * p_start_eff * p_60_given_start * p_cs
    pts_gc = GC_PTS_PER_2[pos] * poisson_step_expectation(lambda_opp * tau, 2)

    pts_saves = 0.0
    if pos == "POR":
        raw_saves = float(form.get("saves") or 2.8)
        saves_90 = (raw_saves / nineties_hist) if (minutes_total >= 180 and raw_saves > 8.0) else raw_saves
        mu_saves = saves_90 * (phi_def ** 0.65) * tau
        p_pen_saved = p_start_eff * (0.14 * phi_def) * 0.22
        pts_saves = poisson_step_expectation(mu_saves, 2) + 5.0 * p_pen_saved

    raw_clr = float(form.get("clearances") or (3.2 if pos == "DEF" else 0.8))
    clr_90 = (raw_clr / nineties_hist) if (minutes_total >= 180 and raw_clr > 10.0) else raw_clr
    rec_90 = max(1.5, 0.85 * duels_90)
    pts_def_vol = (
        poisson_step_expectation(clr_90 * (phi_def ** 0.50) * tau, 3)
        + poisson_step_expectation(rec_90 * (phi_def ** 0.35) * tau, 5)
    )

    # 6. Penalizaciones por Pérdidas de Balón y Disciplina (Tarjetas)
    losses_90 = BASE_LOSSES_90[pos] + 1.4 * kp_90 + 0.9 * duels_90
    pts_losses = -1.0 * poisson_step_expectation(losses_90 * tau, LOSS_DIVISOR[pos])

    # Probabilidad de amarilla condicionada a posición y volumen de duelos
    p_yc_base = {"POR": 0.04, "DEF": 0.22, "MC": 0.19, "DEL": 0.12}[pos]
    p_yc = float(np.clip(p_yc_base * (phi_def ** 0.3) * tau, 0.02, 0.45))
    p_rc = 0.012 * tau if pos == "DEF" else 0.006 * tau
    pts_cards = -1.0 * p_yc - 3.0 * p_rc

    # 7. Inferencia del Bonus Relevo / Tramo Valoración OPTA (0 a 4)
    explicit_bonus = player.get("relevo_bonus")
    if explicit_bonus is not None:
        inferred_bonus = float(explicit_bonus) * (p_start_eff + p_sub_eff)
    else:
        avg_points = float(player.get("average_points") or 4.0)
        avg_rating = float(form.get("average_rating") or form.get("rating") or (6.75 + 0.08 * (avg_points - 4.0)))
        inferred_bonus = infer_opta_performance_bonus(
            avg_rating=avg_rating,
            lambda_own=lambda_own,
            lambda_opp=lambda_opp,
            key_passes_90=kp_90,
            duels_won_90=duels_90,
            p_start_eff=p_start_eff,
            p_sub_eff=p_sub_eff,
        )

    expected_pts = (
        pts_minutes
        + pts_direct_atk
        + pts_atk_vol
        + pts_cs
        + pts_gc
        + pts_saves
        + pts_def_vol
        + pts_losses
        + pts_cards
        + inferred_bonus
    )

    # Multiplicador suave de Jornada Perfecta solo si aporta convicción extrema
    jp_mult = float(form.get("jp_multiplier") or 1.0)
    if jp_mult != 1.0:
        expected_pts *= (1.0 + 0.35 * (jp_mult - 1.0))

    # 8. Cálculo de Techo (Percentil 90) mediante Simulación Monte Carlo Vectorizada
    if run_monte_carlo:
        rng = np.random.default_rng(seed=abs(hash(str(player.get("player_id", "0")))) % (2**32))
        u_play = rng.random(n_sims)
        is_starter = u_play < p_start_eff
        is_sub = (~is_starter) & (u_play < (p_start_eff + p_sub_eff))
        active = is_starter | is_sub

        # Simulación de eventos condicionada a participación
        plays_60 = is_starter & (rng.random(n_sims) < p_60_given_start)
        sim_pts = np.where(plays_60, 2.0, np.where(active, 1.0, 0.0))

        # Goles, asistencias y goles encajados del partido
        opp_goals = rng.poisson(lambda_opp, size=n_sims)
        cs_achieved = plays_60 & (opp_goals == 0)
        sim_pts += np.where(cs_achieved, CS_PTS[pos], 0.0)
        sim_pts += np.where(active, GC_PTS_PER_2[pos] * (opp_goals // 2), 0.0)

        tau_cond = max(0.25, tau / max(1e-4, p_start_eff + p_sub_eff))
        g_sim = rng.poisson(xg_90 * phi_atk * tau_cond, size=n_sims)
        a_sim = rng.poisson(xa_90 * phi_atk * tau_cond, size=n_sims)
        sim_pts += np.where(active, GOAL_PTS[pos] * g_sim + 3.0 * a_sim, 0.0)

        # Ruido de volumen + bonus OPTA correlacionado con goles/CS
        vol_mean = (pts_atk_vol + pts_saves + pts_def_vol + pts_losses + pts_cards + inferred_bonus) / max(
            1e-4, p_start_eff + p_sub_eff
        )
        vol_noise = rng.normal(loc=vol_mean, scale=1.65, size=n_sims)
        sim_pts += np.where(active, np.round(vol_noise + 0.8 * (g_sim > 0) + 0.5 * cs_achieved), 0.0)
        ceiling_pts = float(np.percentile(sim_pts, 90))
    else:
        ceiling_pts = expected_pts * 1.65 + 2.0

    next_match_survival = 1.0 - (p_start_eff * p_yc) if on_verge else 1.0

    return {
        "expected_points": round(max(0.0, expected_pts), 3),
        "ceiling_points": round(max(expected_pts, ceiling_pts), 2),
        "p_start_eff": round(p_start_eff, 4),
        "expected_minutes": round(expected_minutes, 1),
        "inferred_bonus": round(inferred_bonus, 3),
        "next_match_survival": round(next_match_survival, 4),
    }
Bloque 3: Teoría de Subastas y Modelo Predictivo de Sobrepujas Rivales (bid_war v2.0)
La regla operativa actual en league_history.py y bid_war.py calcula league_bid = sale * (1 + median_premium) agregando de forma homogénea todas las compras históricas de la liga y bloqueando la operación (league_bid_blocked) si supera el techo estático min(own_max, af_max). Desde la perspectiva de la Teoría de Subastas (Auction Theory), el mercado diario de LaLiga Fantasy es una Subasta de Primer Precio en Sobre Cerrado con Restricciones Presupuestarias Asimétricas y Valores Privados Afiliados (First-Price Sealed-Bid Auction with Asymmetric Budget Constraints, Che & Gale, 1998; Krishna, 2009).   

En este juego, la distribución de pujas de un rival 
j no es estacionaria ni idéntica a la media de la liga: depende no linealmente de su liquidez disponible 
C 
j
​
  (reconstructed_cash_eur en cash_ledgers) y de su déficit estructural en la posición 
p (thin_positions y lacks_replacements en needs).   

3.1 Perfilado Jerárquico de Agresividad por Manager Rival (
α 
j
​
 )
A partir de los eventos históricos de compra (activity_type_id == 31 en books_from_activity) cruzados con price_snapshots del mismo día en Madrid, cada adjudicación histórica 
k∈{1,…,n 
j
​
 } realizada por el manager rival 
j con puja ganadora 
B 
j,k
​
  sobre un jugador de valor de referencia 
V 
ref,k
​
 =max(sale_price 
k
​
 ,market_value 
k
​
 ) genera una prima relativa observada:   

π 
j,k
​
 = 
V 
ref,k
​
 
B 
j,k
​
 −V 
ref,k
​
 
​
 
Dado que 
π 
j,k
​
 >0 presenta asimetría positiva derecha (muchas compras con primas del 3%–12% y colas pesadas del 25%–60% en guerras por titulares), se modela el logaritmo de la prima condicionada al ratio de liquidez del rival en ese instante 
L 
j,k
​
 =ln(1+ 
V 
ref,k
​
 
C 
j,k
​
 
​
 ) y a su urgencia posicional 
U 
j,k
​
 ∈{0,1,2}:

y 
j,k
​
 =ln(max(π 
j,k
​
 ,0.005))=α 
j
​
 +β 
L
​
 ⋅L 
j,k
​
 +β 
U
​
 ⋅U 
j,k
​
 +ε 
j,k
​
 ,ε 
j,k
​
 ∼N(0,σ 
j
2
​
 )
En esta formulación estructural, el parámetro 
β 
L
​
 >0 captura la elasticidad riqueza-sobrepuja, reflejando cómo un rival que acumula abundante liquidez respecto al precio del jugador incrementa agresivamente su prima debido a la caída en su coste marginal de capital. Simultáneamente, el coeficiente 
β 
U
​
 >0 cuantifica la prima de urgencia posicional, tomando el valor 
U 
j,k
​
 =2 cuando la posición presenta un hueco vacío en su once titular, 
U 
j,k
​
 =1 cuando la demarcación figura en thin_positions sin suplentes de garantía, y 
U 
j,k
​
 =0 cuando la línea está completamente cubierta.   

Para evitar estimaciones ruidosas cuando un rival lleva pocas compras registradas en la temporada (
n 
j
​
 <5), el perfil de agresividad intrínseco 
α
^
  
j
​
  y su dispersión 
σ
^
  
j
​
  se estiman mediante Contracción Bayesiana Empírica (Empirical Bayes / James-Stein Shrinkage) hacia el prior global de la liga 
(μ 
0
​
 ,σ 
0
2
​
 ):

α
^
  
j
​
 = 
n 
j
​
 +κ 
eb
​
 
n 
j
​
 
​
 ⋅ 
r
ˉ
  
j
​
 + 
n 
j
​
 +κ 
eb
​
 
κ 
eb
​
 
​
 ⋅μ 
0
​
 , 
σ
^
  
j
​
 = 
n 
j
​
 +κ 
eb
​
 
n 
j
​
 
​
 s 
j
2
​
 + 
n 
j
​
 +κ 
eb
​
 
κ 
eb
​
 
​
 σ 
0
2
​
 

​
 
donde 
r
ˉ
  
j
​
 = 
n 
j
​
 
1
​
 ∑ 
k=1
n 
j
​
 
​
 (y 
j,k
​
 −β 
L
​
 L 
j,k
​
 −β 
U
​
 U 
j,k
​
 ) es el residuo medio del manager 
j, y 
κ 
eb
​
 =3.0 es la constante de regularización (equivalente al umbral mínimo de 3 guerras definido en la v1.x).   

3.2 Formulación de la Probabilidad de Victoria de Puja 
P(Win∣B)
Sea un jugador en el mercado de posición 
p, precio de referencia 
V 
ref
​
  y calidad proyectada 
Q 
i
​
 =E[Pts 
i
​
 ]. El agente decisor se enfrenta a 
K rivales en la liga. Para cada rival 
j∈{1,…,K}, el evento de que su puja 
B 
j
​
  sea inferior a la puja propia 
B depende de dos componentes: su probabilidad de entrar en la subasta (
θ 
j,p
​
 ) y su distribución acumulada de puja truncada por su techo de caja (
F 
j
​
 (B∣C 
j
​
 ,U 
j,p
​
 )).   

1. Probabilidad de Participación (
θ 
j,p
​
 )
Si el rival 
j ya aparece en la lista de pujas activas del listing (j in listing.bids), se sabe con certeza que participa: 
θ 
j,p
​
 =1.0. Si el rival es el vendedor (j == seller_team_id) o su caja reconstruida es inferior al mínimo legal de puja (
C 
j
​
 <B 
min
​
 ), no puede participar: 
θ 
j,p
​
 =0.0. En caso contrario, la probabilidad latente de que el rival 
j decida pujar en los últimos minutos (incluyendo snipes) viene dada por una función logística calibrada sobre sus necesidades (needs):   

θ 
j,p
​
 =sigmoid(−2.20+1.65⋅I(gap_XI 
j,p
​
 )+0.95⋅I(p∈thin_positions 
j
​
 )+0.60⋅I(lacks_replacements 
j
​
 )+0.22⋅(Q 
i
​
 −4.5)+0.35⋅ln(max(0.1, 
V 
ref
​
 
C 
j
​
 
​
 )))
2. Distribución Acumulada de Puja del Rival Truncada por Liquidez (
F 
j
​
 (B∣C 
j
​
 ,U 
j,p
​
 ))
Condicionado a que el rival 
j puja, la media logarítmica de su prima para este activo específico es:

μ 
j,i
​
 = 
α
^
  
j
​
 +β 
L
​
 ln(1+ 
V 
ref
​
 
C 
j
​
 
​
 )+β 
U
​
 U 
j,p
​
 +β 
Q
​
 ⋅max(0,Q 
i
​
 −6.0)
Para cualquier puja propia 
B>V 
ref
​
 , la prima equivalente es 
π(B)=(B−V 
ref
​
 )/V 
ref
​
 . Sin embargo, ningún rival puede pujar por encima de su liquidez real 
C 
j
​
 . En cash_ledgers, si balanced == True y cash_is_ceiling == True, 
C 
j
​
  es una cota superior dura (
F 
j
​
 (B)=1 para todo 
B>C 
j
​
 ). Si existe incertidumbre contable (gap_eur != 0), se modela el techo presupuestario mediante una barrera probabilística suave 
S(B;C 
j
​
 ,σ 
cash,j
​
 )=Φ( 
σ 
cash,j
​
 
B−C 
j
​
 
​
 ), donde 
σ 
cash,j
​
 =max(CASH_UNCERTAINTY_FLOOR_EUR,∣gap_eur 
j
​
 ∣). La función de distribución acumulada (CDF) de la puja del rival 
j resulta:   

F 
j
​
 (B∣C 
j
​
 ,U 
j,p
​
 )=1−[1−Φ( 
σ
^
  
j
​
 
ln(max(π(B),10 
−4
 ))−μ 
j,i
​
 
​
 )]⋅[1−Φ( 
σ 
cash,j
​
 
B−C 
j
​
 
​
 )]
(Si el rival 
j ya tiene una puja registrada en el mercado con importe visible o consta que el líder actual tiene puja 
B 
leader
​
 , se trunca inferiormente la distribución en 
B 
leader
​
 ).

3. Probabilidad Conjunta de Victoria (
P(Win∣B))
Por estadística de orden de 
K competidores independientes condicionados a las características del activo, la puja propia 
B gana la subasta si y solo si supera a la puja máxima de todos los rivales activos y al precio mínimo requerido 
B 
min
​
 =max(sale_price,leading_bid+1):   

P(Win∣B)=I(B≥B 
min
​
 )⋅ 
j=1
∏
K
​
 [(1−θ 
j,p
​
 )+θ 
j,p
​
 ⋅F 
j
​
 (B∣C 
j
​
 ,U 
j,p
​
 )]
3.3 Cálculo de la Puja Óptima Realista (
B 
∗
 ) según la Intención Estratégica
En una subasta de primer precio, pujar el valor intrínseco completo (
B=V 
val
​
 ) genera un excedente neto nulo (
V 
val
​
 −B=0). El problema de decisión racional consiste en encontrar la puja 
B 
∗
  que maximiza la Utilidad Esperada Ajustada por Liquidez:   

B 
∗
 =arg 
B∈[B 
min
​
 ,C 
propia
​
 ]
max
​
 U(B)=(V 
val
​
 −B)⋅P(Win∣B)
Derivando respecto a 
B e igualando a cero (Condición de Primer Orden, FOC), la puja óptima satisface la ecuación implícita de sombreado (bid shading):   

B 
∗
 =V 
val
​
 − 
∂B
∂P(Win∣B 
∗
 )
​
 
P(Win∣B 
∗
 )
​
 
La clave cuantitativa que diferencia una operación especulativa de un fichaje estructural reside en cómo se construye matemáticamente la valoración interna 
V 
val
​
  antes de optimizar 
B 
∗
 :

Caso 1: Compra por Especulación (Flip a 3–5 días)
El objetivo único de un flip es capturar apreciación de capital a corto plazo antes del inicio de la jornada (o en una ventana de 
H=min(markets_until_kickoff,5) días) y revender al sistema o a un rival. No existe ganancia de puntos en el XI propio. Sea 
E[ΔV 
t+d
​
 ] la variación diaria proyectada en el día 
t+d con factor de decaimiento de impulso 
γ=0.82, y sea 
σ 
ΔV
​
  la desviación estándar de los deltas recientes del jugador. La valoración intrínseca máxima especulativa 
V 
val
flip
​
  descuenta el riesgo de cola (VaR al 85%, 
z 
0.85
​
 =1.036) y el coste de oportunidad de inmovilizar capital (
λ 
lock
​
 =0.004 diario):   

V 
val
flip
​
 =V 
market,t
​
 + 
d=1
∑
H
​
 γ 
d−1
 E[ΔV 
t+d
​
 ]−1.036⋅σ 
ΔV
​
  
H

​
 −λ 
lock
​
 ⋅H⋅V 
market,t
​
 
En modo Flip, la restricción es estricta: si 
V 
val
flip
​
 ≤B 
min
​
  o si en el óptimo 
U(B 
flip
∗
​
 )<Profit 
min
​
  (ej. 120.000 € de beneficio neto esperado ponderado por probabilidad), la orden se descarta inmediatamente (NO / ESPERAR).

Caso 2: Compra Estructural (Titular Clave / Estrella Escasa)
Cuando el jugador entra en el once titular óptimo (points_delta > 0 o cubre un hueco vacío replaces == None en solve_lineup), su valor para el equipo propio supera ampliamente su cotización oficial 
V 
market,t
​
  porque genera dividendos de puntos durante un horizonte de planificación de 
W 
jornadas
​
  (por ejemplo, 
W=6 jornadas) y priva a los rivales directos de adquirirlo (bloqueo estratégico).   

La construcción de esta valoración estructural articula tres mecanismos económicos acoplados:

Valoración Terminal de Rescate (
V 
terminal
​
 ): definida como el valor de mercado esperado al cierre de la ventana de corto plazo, 
V 
terminal
​
 =V 
market,t
​
 +∑ 
d=1
3
​
 γ 
d−1
 E[ΔV 
t+d
​
 ].

Precio Sombra de la Caja Propia (
λ 
shadow
​
 ): mide cuántos puntos por jornada y por millón de euros rinde la mejor alternativa libre en el mercado (own_points_per_million mediano de los titulares disponibles, típicamente 
λ 
shadow
​
 ≈0.45 pts/M€), ajustado por la ratio de abundancia de liquidez del manager respecto a la liga 
(C 
propia
​
 / 
C
  
liga
​
 ) 
−0.45
 .   

Multiplicador de Escasez de Mercado (
Ω 
scarcity
​
 (p,Q 
i
​
 )): sea 
N 
free
​
 (p,Q 
i
​
 ) el número total de jugadores libres en toda la liga (en catalog_from_documents que no pertenecen a ningún equipo en squads) de la misma posición 
p con 
E[Pts]≥0.90⋅Q 
i
​
 ; el factor de escasez crece exponencialmente a medida que 
N 
free
​
 →0:   

Ω 
scarcity
​
 (p,Q 
i
​
 )=1.0+0.85⋅exp(−0.35⋅N 
free
​
 (p,Q 
i
​
 ))+0.50⋅I(hueco_vac 
ı
ˊ
 o_XI 
p
​
 )
La valoración intrínseca estructural 
V 
val
struct
​
  convierte el diferencial de puntos 
ΔE[Pts] 
XI
​
  en euros equivalentes ajustados por escasez:

V 
val
struct
​
 =V 
terminal
​
 +( 
λ 
shadow
​
 
ΔE[Pts] 
XI
​
 ⋅W 
jornadas
​
 
​
 ⋅10 
6
 )⋅Ω 
scarcity
​
 (p,Q 
i
​
 )
Al introducir 
V 
val
struct
​
  en el optimizador 
argmax 
B
​
 (V 
val
struct
​
 −B)P(Win∣B), si un rival 
j con alta urgencia tiene un techo de caja conocido 
C 
j
​
 =14200000 € y la valoración estructural propia es 
V 
val
struct
​
 =18000000 €, la derivada 
∂B
∂P(Win∣B)
​
  experimenta un pico justo en 
B=C 
j
​
 +δ, haciendo que el optimizador sitúe automáticamente 
B 
∗
  ligeramente por encima de 14.200.000 € para eliminar por completo al rival por knock-out presupuestario (Cash-Ceiling Sniping) sin desperdiciar el resto del excedente de valoración.   

3.4 Implementación en Python (toolbox/bid_war.py y toolbox/league_history.py)
Python
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Any, Dict, List
import numpy as np
from scipy.optimize import minimize_scalar
from scipy.stats import norm


@dataclass
class RivalProfile:
    team_id: str
    manager_name: str
    alpha_aggressiveness: float
    sigma_dispersion: float
    cash_eur: float
    cash_uncertainty_eur: float
    thin_positions: List[str]
    xi_gaps: List[str]
    lacks_replacements: bool
    already_bidding: bool = False


@dataclass
class OptimalBidResult:
    intent: str                      # "FLIP" | "STRUCTURAL"
    intrinsic_valuation_eur: int
    optimal_bid_eur: int
    win_probability: float
    expected_surplus_eur: int
    rival_knockout_targets: List[str]
    decision: str                    # "PUJAR" | "ESPERAR" | "NO"


def fit_rival_profiles_eb(
    activity_buys: List[Dict[str, Any]],
    rivals_state: List[Dict[str, Any]],
    beta_liquidity: float = 0.18,
    beta_urgency: float = 0.25,
    eb_shrinkage_k: float = 3.0,
) -> Dict[str, RivalProfile]:
    """
    Ajusta el perfil de sobrepuja (alpha_j, sigma_j) de cada rival desde activity_type_id == 31
    usando Empirical Bayes (contracción hacia el prior de la liga).
    """
    residuals_by_team: Dict[str, List[float]] = {}
    all_residuals: List[float] = []

    for ev in activity_buys:
        team_id = str(ev.get("team_id", ""))
        amount = float(ev.get("amount_eur") or 0.0)
        ref_val = float(ev.get("reference_value_eur") or ev.get("market_value") or 0.0)
        if amount <= 0 or ref_val <= 0:
            continue
        premium = (amount - ref_val) / ref_val
        if premium <= 0.005 or premium > 1.20:
            continue

        cash_at_buy = float(ev.get("cash_at_event_eur") or ref_val * 1.5)
        urgency = float(ev.get("positional_urgency") or 0.0)
        liq_ratio = math.log(1.0 + max(0.0, cash_at_buy / ref_val))

        y_obs = math.log(premium)
        res = y_obs - beta_liquidity * liq_ratio - beta_urgency * urgency
        residuals_by_team.setdefault(team_id, []).append(res)
        all_residuals.append(res)

    # Prior global de la liga (fallback a mediana ~8.5% de prima -> ln(0.085) = -2.465)
    mu_0 = float(np.mean(all_residuals)) if len(all_residuals) >= 5 else -2.465
    sigma_0 = float(np.std(all_residuals)) if len(all_residuals) >= 5 else 0.55
    sigma_0 = float(np.clip(sigma_0, 0.30, 0.95))

    profiles: Dict[str, RivalProfile] = {}
    for r in rivals_state:
        t_id = str(r.get("team_id", ""))
        samples = residuals_by_team.get(t_id, [])
        n_j = len(samples)
        if n_j > 0:
            r_bar = float(np.mean(samples))
            s_sq = float(np.var(samples)) if n_j > 1 else sigma_0**2
            alpha_j = (n_j / (n_j + eb_shrinkage_k)) * r_bar + (eb_shrinkage_k / (n_j + eb_shrinkage_k)) * mu_0
            sigma_j = math.sqrt(
                (n_j / (n_j + eb_shrinkage_k)) * s_sq + (eb_shrinkage_k / (n_j + eb_shrinkage_k)) * (sigma_0**2)
            )
        else:
            alpha_j, sigma_j = mu_0, sigma_0

        cash_val = float(r.get("reconstructed_cash_eur") or r.get("cash_eur") or 0.0)
        gap_val = abs(float(r.get("gap_eur") or 0.0))
        uncertainty = max(120_000.0, gap_val) if r.get("balanced", True) else max(600_000.0, gap_val)

        profiles[t_id] = RivalProfile(
            team_id=t_id,
            manager_name=str(r.get("manager_name", t_id)),
            alpha_aggressiveness=alpha_j,
            sigma_dispersion=float(np.clip(sigma_j, 0.25, 0.90)),
            cash_eur=max(0.0, cash_val),
            cash_uncertainty_eur=uncertainty,
            thin_positions=list(r.get("thin_positions") or []),
            xi_gaps=list(r.get("xi_gaps") or []),
            lacks_replacements=bool(r.get("lacks_replacements", False)),
            already_bidding=bool(r.get("already_bidding", False)),
        )
    return profiles


def probability_of_winning_bid(
    bid_eur: float,
    v_ref: float,
    min_legal_bid: float,
    position: str,
    expected_pts: float,
    rivals: List[RivalProfile],
    beta_liquidity: float = 0.18,
    beta_urgency: float = 0.25,
) -> float:
    """
    Calcula P(Win | B) frente a los K rivales modelando su probabilidad de entrada (theta_j)
    y su distribución de puja Log-Normal truncada por su techo de liquidez (C_j).
    """
    if bid_eur < min_legal_bid:
        return 0.0

    premium_b = max(1e-4, (bid_eur - v_ref) / max(1.0, v_ref))
    log_prem_b = math.log(premium_b)
    p_win_all = 1.0

    for rv in rivals:
        if rv.cash_eur + 2.0 * rv.cash_uncertainty_eur < min_legal_bid and not rv.already_bidding:
            continue

        # 1. Probabilidad de participación theta_{j,p}
        has_gap = 1.0 if position in rv.xi_gaps else 0.0
        is_thin = 1.0 if position in rv.thin_positions else 0.0
        no_rep = 1.0 if rv.lacks_replacements else 0.0
        urgency_level = 2.0 if has_gap else (1.0 if is_thin else 0.0)
        cash_ratio = max(0.05, rv.cash_eur / max(1.0, v_ref))

        if rv.already_bidding:
            theta_j = 1.0
        else:
            logit = (
                -2.20
                + 1.65 * has_gap
                + 0.95 * is_thin
                + 0.60 * no_rep
                + 0.22 * (expected_pts - 4.5)
                + 0.35 * math.log(cash_ratio)
            )
            theta_j = 1.0 / (1.0 + math.exp(-logit))

        # 2. CDF condicional de la puja del rival F_j(B | C_j, U_{j,p})
        liq_term = math.log(1.0 + cash_ratio)
        star_boost = 0.10 * max(0.0, expected_pts - 6.0)
        mu_ji = rv.alpha_aggressiveness + beta_liquidity * liq_term + beta_urgency * urgency_level + star_boost

        # Probabilidad por apetito de valoración
        cdf_valuation = float(norm.cdf((log_prem_b - mu_ji) / rv.sigma_dispersion))
        # Probabilidad de que la puja propia supere el techo físico de caja del rival (Knock-out)
        cdf_budget_ceiling = float(norm.cdf((bid_eur - rv.cash_eur) / rv.cash_uncertainty_eur))

        # El rival pierde si la puja propia supera su valoración O supera su caja disponible
        f_j = 1.0 - (1.0 - cdf_valuation) * (1.0 - cdf_budget_ceiling)
        p_beat_rival = (1.0 - theta_j) + theta_j * f_j
        p_win_all *= p_beat_rival

    return float(np.clip(p_win_all, 0.0, 1.0))


def _apply_psychological_anti_cluster_nudge(raw_bid: float, max_budget: float) -> int:
    """
    Evita números redondos (múltiplos de 100k o 50k) donde se agrupan las pujas humanas,
    añadiendo un desplazamiento asimétrico determinista de +1,109 € a +2,411 €.
    """
    rounded_50k = math.ceil(raw_bid / 50_000.0) * 50_000.0
    if abs(rounded_50k - raw_bid) <= 12_000.0:
        cand = rounded_50k + 2_411.0
    else:
        cand = raw_bid + 1_109.0
    return int(min(max_budget, max(raw_bid, cand)))


def solve_optimal_bid_v2(
    market_value: float,
    sale_price: float,
    leading_bid: float,
    own_cash_eur: float,
    position: str,
    expected_pts: float,
    points_delta_xi: float,
    populates_empty_slot: bool,
    free_tier_peers_count: int,
    projected_daily_deltas: List[float],
    delta_volatility: float,
    rivals: List[RivalProfile],
    median_league_ppm: float = 0.45,
    planning_horizon_weeks: int = 6,
) -> OptimalBidResult:
    """
    Calcula la Puja Óptima Realista B* resolviendo max_B (V_val - B) * P(Win | B),
    distinguiendo entre Compra por Especulación (FLIP) y Compra Estructural (STRUCTURAL).
    """
    v_ref = max(market_value, sale_price)
    min_legal_bid = max(sale_price, leading_bid + 1.0 if leading_bid > 0 else sale_price)

    if own_cash_eur < min_legal_bid:
        return OptimalBidResult("NONE", 0, 0, 0.0, 0, [], "NO")

    # 1. Determinación del modo estratégico y valoración intrínseca V_val
    is_structural = populates_empty_slot or (points_delta_xi >= 0.45)
    h_days = min(len(projected_daily_deltas), 5)
    gamma = 0.82
    expected_capital_gain = sum((gamma ** d) * projected_daily_deltas[d] for d in range(h_days))

    if not is_structural:
        intent = "FLIP"
        risk_penalty = 1.036 * delta_volatility * math.sqrt(max(1, h_days))
        lockup_cost = 0.004 * max(1, h_days) * market_value
        v_val = market_value + expected_capital_gain - risk_penalty - lockup_cost
        min_required_surplus = 120_000.0
        min_win_prob = 0.25
    else:
        intent = "STRUCTURAL"
        short_gain = sum((gamma ** d) * projected_daily_deltas[d] for d in range(min(3, h_days)))
        v_terminal = market_value + short_gain

        # Multiplicador de escasez en el catálogo libre de la liga
        scarcity_mult = (
            1.0
            + 0.85 * math.exp(-0.35 * max(0, free_tier_peers_count))
            + (0.50 if populates_empty_slot else 0.0)
        )
        # Ajuste del precio sombra de la liquidez según abundancia de caja propia
        avg_rival_cash = float(np.mean([r.cash_eur for r in rivals])) if rivals else own_cash_eur
        cash_abundance = float(np.clip(own_cash_eur / max(1_000_000.0, avg_rival_cash), 0.5, 2.0))
        shadow_ppm = max(0.20, median_league_ppm * (cash_abundance ** -0.45))

        effective_delta_pts = max(points_delta_xi, expected_pts if populates_empty_slot else 0.5)
        structural_premium_eur = ((effective_delta_pts * planning_horizon_weeks) / shadow_ppm) * 1_000_000.0
        v_val = v_terminal + structural_premium_eur * scarcity_mult
        min_required_surplus = 50_000.0
        min_win_prob = 0.35

    upper_bound = min(own_cash_eur, v_val)
    if upper_bound <= min_legal_bid:
        return OptimalBidResult(intent, int(v_val), int(min_legal_bid), 0.0, 0, [], "ESPERAR")

    # 2. Optimización numérica de Utilidad Esperada + evaluación en puntos de Knock-out de caja rival
    def neg_expected_utility(b: float) -> float:
        p_w = probability_of_winning_bid(b, v_ref, min_legal_bid, position, expected_pts, rivals)
        return -((v_val - b) * p_w)

    res = minimize_scalar(neg_expected_utility, bounds=(min_legal_bid, upper_bound), method="bounded")
    best_b = float(res.x)
    best_eu = -float(res.fun)

    # Inspección explícita de techos de caja de rivales urgentes (Cash-Ceiling Knock-out)
    knockouts: List[str] = []
    for rv in rivals:
        if position in rv.xi_gaps or position in rv.thin_positions or rv.already_bidding:
            ko_bid = rv.cash_eur + 3_500.0
            if min_legal_bid <= ko_bid <= upper_bound:
                eu_ko = -neg_expected_utility(ko_bid)
                if eu_ko >= best_eu * 0.97:
                    best_b = ko_bid
                    best_eu = eu_ko
                    knockouts.append(rv.manager_name)

    final_bid = _apply_psychological_anti_cluster_nudge(best_b, own_cash_eur)
    final_p_win = probability_of_winning_bid(final_bid, v_ref, min_legal_bid, position, expected_pts, rivals)
    expected_surplus = int(round((v_val - final_bid) * final_p_win))

    if expected_surplus >= min_required_surplus and final_p_win >= min_win_prob:
        decision = "PUJAR"
    elif v_val > min_legal_bid:
        decision = "ESPERAR"
    else:
        decision = "NO"

    return OptimalBidResult(
        intent=intent,
        intrinsic_valuation_eur=int(round(v_val)),
        optimal_bid_eur=final_bid,
        win_probability=round(final_p_win, 4),
        expected_surplus_eur=expected_surplus,
        rival_knockout_targets=knockouts,
        decision=decision,
    )
Bloque 4: Dinámica de Precios y Detección Cinemática de Picos (sell_signal v2.0)
En la arquitectura v1.x, la regla de venta en analyzer.py presenta dos fallos críticos: primero, referencia el campo price_delta_3 (acumulado de 3 días), pero dicho campo jamás se calcula ni se inyecta desde la tabla price_snapshots; segundo, las condiciones lógicas de disparo (official_price_delta <= 0 o acceleration <= 0) son indicadores retrasados (lagging indicators). Esperar a que la variación oficial del día sea menor o igual a 0 implica vender entre 24 y 48 horas después de que el activo haya superado su punto de inflexión, perdiendo el último tramo de liquidez alcista y sufriendo la primera caída de valor.   

4.1 Cinemática Continua del Ciclo de Precio y Derivadas de Orden Superior
El algoritmo oficial de valoración de mercado de LaLiga Fantasy actualiza los precios diariamente (en torno a las 14:00–14:08 Europe/Madrid) aplicando un filtro autorregresivo suavizado sobre el balance neto global de compras, pujas y ventas de todos los managers de la plataforma. Como consecuencia de esta inercia algorítmica, la trayectoria del cambio diario de precio 
ΔV 
t
​
 =V 
t
​
 −V 
t−1
​
  (market_value_change) no salta abruptamente de +350.000 € a -150.000 € en un día (salvo lesión grave súbita), sino que describe una campana cuasi-gaussiana (equivalente a una curva logística en el precio acumulado 
V 
t
​
 ).   

Sea 
{V 
t−K
​
 ,…,V 
t−1
​
 ,V 
t
​
 } la serie temporal de valores de mercado diarios extraída de price_snapshots para el jugador 
i en los últimos 
K=14 días (ordenados cronológicamente por day en zona horaria Europe/Madrid), y sea 
ΔV 
k
​
 =market_value_change 
k
​
 =V 
k
​
 −V 
k−1
​
  la primera diferencia diaria. El estado cinemático del activo en el día 
t queda completamente caracterizado por las siguientes cuatro magnitudes diferenciales discretas:   

Magnitud Cinemática	Campo en trends	Expresión en Diferencias Finitas	Interpretación Física en el Ciclo de Mercado
Impulso Acumulado de 3 Días	price_delta_3	V_t - V_{t-3} = dV_t + dV_{t-1} + dV_{t-2}	
Confirma la existencia de una tendencia previa real sobre la ventana mínima de 3 días de price_snapshots. 

Velocidad Instantánea y Suavizada	price_delta_1 / velocity_ema3	v_t = dV_t y (3*dV_t + 2*dV_{t-1} + dV_{t-2}) / 6	Tasa actual de apreciación diaria y filtro de media móvil ponderada frente a ruido puntual.
Aceleración Diaria y Relativa	acceleration	a_t = dV_t - dV_{t-1}	
Segunda derivada del precio; se vuelve negativa exactamente al cruzar el punto de inflexión de la subida. 

Sobreaceleración (Jerk)	jerk	j_t = a_t - a_{t-1} = dV_t - 2*dV_{t-1} + dV_{t-2}	Tercera derivada del precio; mide la concavidad y la violencia con la que se está frenando la demanda compradora.
4.2 Índice de Agotamiento Relativo (
REI 
t
​
 ) y Predicción del Horizonte de Cruce por Cero (
τ
^
  
zero
​
 )
Para detectar el pico exacto de la campana mientras el jugador todavía está subiendo de precio (
ΔV 
t
​
 >0), pero cuando la demanda compradora ya se ha agotado y la inversión bajista es inminente en las siguientes 24–48 horas, se formulan dos invariantes adimensionales:

1. Índice de Agotamiento Relativo (Relative Exhaustion Index, 
REI 
t
​
 )
Sea 
ΔV 
max
(7)
​
 =max 
m∈{0,…,6}
​
 ΔV 
t−m
​
  la velocidad máxima diaria alcanzada por el jugador durante la ola alcista de los últimos 7 días. Cuando 
ΔV 
max
(7)
​
 >0 y 
ΔV 
t
​
 >0, el índice 
REI 
t
​
 ∈[0,1] cuantifica qué fracción de la potencia máxima de subida se ha disipado ya:   

REI 
t
​
 =1− 
ΔV 
max
(7)
​
 
ΔV 
t
​
 
​
 
En la fase de expansión de la ola, 
ΔV 
t
​
 =ΔV 
max
(7)
​
 ⟹REI 
t
​
 =0. En cuanto la subida diaria empieza a frenarse tras alcanzar el vértice de la campana (
ΔV 
t
​
 <ΔV 
t−1
​
 ⟹a 
t
​
 <0), 
REI 
t
​
  crece hacia 1.

2. Predictor Cinemático de Tiempo hasta el Cruce por Cero (
τ
^
  
zero
​
 )
Expandiendo la velocidad de precio 
v(t+τ) en serie de Taylor alrededor del día actual 
t bajo régimen de desaceleración (
v 
t
​
 >0 y 
a 
eff,t
​
 <0), donde 
a 
eff,t
​
 =0.65a 
t
​
 +0.35a 
t−1
​
 +0.25min(0,j 
t
​
 ) incorpora el tirón bajista de la tercera derivada:

v(t+τ)≈v 
t
​
 +a 
eff,t
​
 ⋅τ=0⟹ 
τ
^
  
zero
​
 =− 
a 
eff,t
​
 
ΔV 
t
​
 
​
 (medido en d 
ı
ˊ
 as hasta ΔV≤0)
Esta ecuación proporciona una lectura física directa: si un jugador subió ayer +220.000 € (
ΔV 
t−1
​
 ) y hoy sube +110.000 € (
ΔV 
t
​
 >0), en la versión v1.x la velocidad sigue siendo positiva y no se detecta el agotamiento inminente. En la versión v2.0, 
a 
t
​
 =−110000 €/día y 
τ
^
  
zero
​
 ≈1.0 día (24 horas). El motor predice matemáticamente que al día siguiente la variación cruzará a 
≤0 € y activa la señal de venta en la cresta exacta del valor de mercado, asegurando el precio máximo posible.   

4.3 Regla de Decisión sell_signal v2.0
El motor clasifica el estado de venta de cada activo en plantilla dentro de cuatro regímenes operativos mutuamente excluyentes que alimentan tanto el booleano sell_signal como el nuevo campo descriptivo sell_signal_status en el dashboard.   

Estado (sell_signal_status)	Booleano sell_signal	Condición Matemática de Activación	Acción Operativa Recomendada
SELL_AT_CREST	True	price_delta_3 > 0 y dV_t > 0 y a_t < 0 y 0 < tau_zero <= 2.0 y (REI_t >= 0.38 o (a_{t-1} < 0 y REI_t >= 0.25))	Venta Anticipada en el Pico: Liquidar 24–48h antes de que el cambio diario perfore cero, capturando el máximo de la campana.
SELL_CONFIRMED_REVERSAL	True	(prev_delta_3 > 0 o max_v_7 >= Umbral_ola) y dV_t <= 0	
Venta por Inversión Consumada: El activo ya agotó su ciclo alcista y ha entrado en depreciación neta hoy. 

HOLD_RISING	False	dV_t > 0 y (a_t >= 0 o tau_zero > 2.0)	Mantener en Subida: La ola alcista conserva tracción suficiente para seguir revalorizando el activo al menos 48h más.
HOLD_STABLE	False	dV_t <= 0 y prev_delta_3 <= 0 y max_v_7 < Umbral_ola	
Mantener / Sin Señal de Pico: Activo en rango lateral o suelo sin subida especulativa previa que liquidar. 

4.4 Implementación en Python del Pipeline de price_snapshots y sell_signal v2.0 (toolbox/own_intel.py y toolbox/analyzer.py)
Python
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import numpy as np


@dataclass
class PriceKinematicsResult:
    price_delta_1: int               # Delta oficial de hoy (v_t)
    price_delta_3: int               # Acumulado exacto de 3 días (reparado desde price_snapshots)
    price_delta_7: int               # Acumulado de 7 días
    velocity_ema3: float             # Velocidad suavizada
    acceleration: int                # Segunda derivada discreta (a_t = v_t - v_{t-1})
    relative_acceleration: float     # Aceleración relativa normalizada
    jerk: int                        # Tercera derivada (j_t = a_t - a_{t-1})
    relative_exhaustion_index: float # REI_t in [0, 1]: fracción de caída desde el pico de la ola
    days_to_zero_crossing: float     # Horizonte predicho (en días) hasta que delta <= 0
    sell_signal: bool                # Flag booleano compatible con el dashboard actual
    sell_signal_status: str          # "SELL_AT_CREST" | "SELL_CONFIRMED_REVERSAL" | "HOLD_RISING" | "HOLD_STABLE"
    predicted_next_delta: int        # Proyección cinemática de mañana para own_predicted_delta


def compute_price_kinematics_and_sell_signal(
    snapshots: List[Dict[str, Any]],
    current_market_value: int,
    official_today_delta: Optional[int] = None,
    scraper_acceleration: Optional[float] = None,
) -> PriceKinematicsResult:
    """
    Procesa la serie histórica de `price_snapshots` (últimos 14 días ordenados por `day` ascendente)
    para poblar `price_delta_3` y ejecutar el detector anticipado de picos (`sell_signal v2.0`).

    Parámetros:
    -----------
    snapshots : List[Dict[str, Any]]
        Filas de la tabla `price_snapshots` para un `player_id`, con claves `day`, `market_value`,
        `market_value_change`. Pueden venir desordenadas; la función las ordena por `day`.
    """
    # 1. Ordenación cronológica estricta por día (Europe/Madrid)
    sorted_snaps = sorted(snapshots, key=lambda x: str(x.get("day", "")))
    deltas: List[int] = []

    for idx, snap in enumerate(sorted_snaps):
        mv_change = snap.get("market_value_change")
        if mv_change is not None:
            deltas.append(int(mv_change))
        elif idx > 0:
            prev_mv = int(sorted_snaps[idx - 1].get("market_value") or current_market_value)
            curr_mv = int(snap.get("market_value") or current_market_value)
            deltas.append(curr_mv - prev_mv)

    # Si existe un delta oficial del día más fresco en el catálogo en vivo no volcado aún
    if official_today_delta is not None and (not deltas or deltas[-1] != int(official_today_delta)):
        deltas.append(int(official_today_delta))

    if not deltas:
        deltas = [0]

    # Relleno defensivo al inicio si el jugador tiene menos de 4 días en snapshots
    while len(deltas) < 4:
        deltas.insert(0, deltas[0])

    # 2. Derivadas discretas exactas y ventana móvil de 3 y 7 días
    v_t = deltas[-1]
    v_t1 = deltas[-2]
    v_t2 = deltas[-3]

    price_delta_3 = int(v_t + v_t1 + v_t2)
    price_delta_7 = int(sum(deltas[-7:]))

    vel_ema3 = float((3.0 * v_t + 2.0 * v_t1 + 1.0 * v_t2) / 6.0)
    a_t = int(v_t - v_t1)
    a_t1 = int(v_t1 - v_t2)
    j_t = int(a_t - a_t1)

    denom_rel = max(abs(v_t1), 10_000)
    rel_acc = float(a_t / denom_rel)

    # 3. Análisis de la ola alcista en ventana de 7 días e Índice de Agotamiento Relativo (REI)
    window_7 = deltas[-7:]
    max_v_7 = max(window_7)
    prev_delta_3 = int(v_t1 + v_t2 + deltas[-4])

    # Umbral de ola significativa: al menos 30k € o el 0.8% del valor del jugador en su pico diario
    min_wave_peak = max(30_000, int(0.008 * max(current_market_value, 1_000_000)))
    in_significant_wave = (max_v_7 >= min_wave_peak) or (price_delta_3 >= min_wave_peak * 2)

    if max_v_7 > 0 and v_t > 0:
        rei_t = float(np.clip(1.0 - (v_t / float(max_v_7)), 0.0, 1.0))
    elif max_v_7 > 0 and v_t <= 0:
        rei_t = 1.0
    else:
        rei_t = 0.0

    # 4. Predicción cinemática del cruce por cero (tau_zero en días)
    # Integración de la aceleración suavizada y la curvatura negativa (jerk)
    a_eff = 0.65 * float(a_t) + 0.35 * float(a_t1) + 0.25 * float(min(0, j_t))
    if scraper_acceleration is not None and scraper_acceleration < 0 and a_eff >= 0:
        # Si FútbolFantasy reporta data-aceleracion negativa intradía antes del cierre
        a_eff = -0.35 * float(max(abs(v_t), 20_000))

    if v_t > 0 and a_eff < -1_000.0:
        days_to_zero = float(-v_t / a_eff)
    elif v_t <= 0:
        days_to_zero = 0.0
    else:
        days_to_zero = 99.0

    # Proyección del delta de mañana (Taylor truncado)
    pred_next_delta = int(round(v_t + 0.70 * a_t + 0.20 * min(0, j_t)))

    # 5. Lógica de disparo de `sell_signal v2.0`
    # Caso A: Detección anticipada en la cresta exacta de la campana (24-48h antes de caer)
    is_crest_exhaustion = (
        in_significant_wave
        and v_t > 0
        and price_delta_3 > 0
        and a_t < 0
        and (0.0 < days_to_zero <= 2.0)
        and (rei_t >= 0.38 or (a_t1 < 0 and rei_t >= 0.25))
    )

    # Caso B: Reversión ya consumada (el jugador subía en los días previos y hoy ya cae o se frena a 0)
    had_prior_rise = (prev_delta_3 > 0) or (max_v_7 >= min_wave_peak)
    is_confirmed_reversal = had_prior_rise and (v_t <= 0)

    if is_crest_exhaustion:
        sell_flag = True
        status = "SELL_AT_CREST"
    elif is_confirmed_reversal:
        sell_flag = True
        status = "SELL_CONFIRMED_REVERSAL"
    elif v_t > 0:
        sell_flag = False
        status = "HOLD_RISING"
    else:
        sell_flag = False
        status = "HOLD_STABLE"

    return PriceKinematicsResult(
        price_delta_1=v_t,
        price_delta_3=price_delta_3,
        price_delta_7=price_delta_7,
        velocity_ema3=round(vel_ema3, 1),
        acceleration=a_t,
        relative_acceleration=round(rel_acc, 4),
        jerk=j_t,
        relative_exhaustion_index=round(rei_t, 4),
        days_to_zero_crossing=round(days_to_zero, 2),
        sell_signal=sell_flag,
        sell_signal_status=status,
        predicted_next_delta=pred_next_delta,
    )
Hoja de Ruta de Refactorización Directa por Fichero
Para ejecutar la migración en el entorno de producción sin romper los contratos JSON que consumen los comandos CLI (trends, optimize, market-intel, own-intel, needs, flip), la integración debe seguir este orden secuencial de dependencias:   

[The Odds API / SharpAPI / Sofascore]       [Understat / FBref Rolling 5]
│                                        │
▼                                        ▼
devig_shin_3way()                        compute_rolling_xg_rates()
devig_power_2way()                                 │
│                                        │
└──────────────► build_hybrid_match_projection() ◄─────────┐
(own_intel.py: lambda_H, lambda_A, P(CS)) │
│                         │
▼                         │
[price_snapshots (14d)]          compute_expected_opta_points_v2()          │
│                      (analyzer.py: E[Pts], P90, Rotación UEFA)  │
▼                                       │                         │
compute_price_kinematics_and_sell_signal()        ▼                         │
(own_intel.py / analyzer.py: REI_t, tau_0) ──► solve_optimal_bid_v2() ◄─────┘
(bid_war.py / market_intel.py)
▲
│
[cash_ledgers + activity_type_id == 31] ──────► fit_rival_profiles_eb()
(league_history.py)

Orden	Módulo en Repositorio	Funciones a Sustituir / Refactorizar	Nuevos Campos Expuestos en el Contrato JSON
Paso 1	toolbox/understat.py y toolbox/scrapers.py	
Añadir cliente ligero para The Odds API / SharpAPI cacheado en scraper_cache y extraer ventana móvil de los últimos 5 partidos (compute_rolling_xg_rates). 

En fixture: lambda_home, lambda_away, p_cs_home, p_cs_away, odds_1x2, market_weight.
Paso 2	toolbox/own_intel.py	
Integrar build_hybrid_match_projection en la generación de own_calendar[] y ejecutar compute_price_kinematics_and_sell_signal dentro de persist_and_apply_own_intel leyendo los últimos 14 días de price_snapshots. 

En trends.players[]: poblar finalmente price_delta_3, price_delta_7, relative_exhaustion_index, days_to_zero_crossing y sell_signal_status. 

Paso 3	toolbox/analyzer.py	
Reemplazar expected_opta_points por compute_expected_opta_points_v2 y sustituir la regla booleana antigua de sell_signal por la salida cinemática de PriceKinematicsResult. 

En optimize: p_start_eff, expected_minutes, inferred_bonus y next_match_survival (para penalizar apercibidos en planificación). 

Paso 4	toolbox/league_history.py y toolbox/bid_war.py	
Sustituir la mediana simple de books_from_activity por fit_rival_profiles_eb y reemplazar economic_bid + apply_league_clearing en toolbox/market_intel.py por solve_optimal_bid_v2. 

En market-intel: optimal_bid_eur, win_probability, intrinsic_valuation_eur, expected_surplus_eur y rival_knockout_targets[].