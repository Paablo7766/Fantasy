import type { CashReconciliation, RivalFinancialTeam, RivalSquad } from "@/lib/types";

/**
 * Banda de liquidez calibrada de un rival.
 *
 * El backend reconstruye la caja como **cota superior** (``calculated_cash``) a
 * partir de los libros y la contrasta con el saldo que publica la API
 * (``observed_cash_eur``). El **grupo de control** decide qué cifra se defiende:
 *
 * - la cota sobraba → se aprieta al saldo observado más el margen contable, así
 *   que ``calibratedCash < cash``: ese es el descuento que hay que enseñar.
 * - la cota se quedaba corta → no se inventa dinero hacia arriba, pero la cifra
 *   defendible es la observada y el hueco se publica como ``arbitrage_eur``.
 *
 * ``temperature`` mide en ``(0, 1]`` cuánto cuadra la cota con el saldo
 * observado; cuanto más baja, más frágil es la cota. Si un dato falta se queda
 * en ``null`` y la interfaz no lo pinta: aquí no se inventa nada.
 */
export type LiquidityLevel = "alta" | "media" | "baja" | "sin_lectura";

export type LiquidityTone = "good" | "warn" | "bad" | "muted";

export type LiquidityRead = {
  /**
   * Cifra publicada de referencia, la que el rival «tenía» antes de calibrar:
   * la cota reconstruida (``calculated_cash``) o, si no viene, la caja plana.
   */
  cash: number | null;
  /** Cota calibrada contra el saldo observado: la cifra que se defiende. */
  calibratedCash: number | null;
  /** La cota se apretó: ``calibratedCash < cash`` (hubo descuento real). */
  tightened: boolean;
  /**
   * La cota se quedó corta y se sube al saldo observado. No es un descuento:
   * hay dinero que los libros no explican y se declara como arbitraje.
   */
  raised: boolean;
  /** Puja máxima con la cota calibrada. */
  bidLimit: number | null;
  /** Puja máxima sin calibrar (cota + deuda). */
  rawBidLimit: number | null;
  /** La puja baja al calibrar aunque la cifra publicada no cambie. */
  bidTightened: boolean;
  /** Margen de error detectado: caja observada fuera de los libros. */
  arbitrageEur: number | null;
  /** Confianza estadística de la cota, 0–1. */
  temperature: number | null;
  /** ``temperature`` en porcentaje entero, lista para pintar. */
  temperaturePct: number | null;
  level: LiquidityLevel;
  tone: LiquidityTone;
  /** Hay lectura de conciliación (termómetro) para este equipo. */
  calibrated: boolean;
  /** ``Reconciliation`` completa por si el desglose necesita más detalle. */
  reconciliation: CashReconciliation | null;
};

const TEMPERATURE_ALTA = 0.75;
const TEMPERATURE_MEDIA = 0.5;

function num(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function firstNumber(...values: Array<number | null | undefined>): number | null {
  for (const value of values) {
    const parsed = num(value);
    if (parsed !== null) return parsed;
  }
  return null;
}

export function temperatureLevel(temperature: number | null | undefined): LiquidityLevel {
  const value = num(temperature);
  if (value === null) return "sin_lectura";
  if (value >= TEMPERATURE_ALTA) return "alta";
  if (value >= TEMPERATURE_MEDIA) return "media";
  return "baja";
}

export function temperatureTone(level: LiquidityLevel): LiquidityTone {
  if (level === "alta") return "good";
  if (level === "media") return "warn";
  if (level === "baja") return "bad";
  return "muted";
}

/** Etiqueta corta del termómetro: lo que el usuario lee, no el número crudo. */
export function temperatureLabel(level: LiquidityLevel): string {
  if (level === "alta") return "Cota segura";
  if (level === "media") return "Cota justa";
  if (level === "baja") return "Cota frágil";
  return "Sin lectura";
}

/**
 * Clases semánticas de Tailwind para texto, badge y barra del termómetro.
 *
 * Verde/esmeralda para cotas bien calibradas; ámbar y naranja según se apaga la
 * confianza, de modo que el color cuente lo mismo que el número.
 */
export function temperatureClasses(level: LiquidityLevel): {
  text: string;
  badge: string;
  bar: string;
} {
  if (level === "alta") {
    return { text: "text-mint", badge: "badge badge--good", bar: "bg-mint" };
  }
  if (level === "media") {
    return { text: "text-gold", badge: "badge badge--warn", bar: "bg-gold" };
  }
  if (level === "baja") {
    return { text: "text-warn", badge: "badge badge--warn", bar: "bg-warn/70" };
  }
  return { text: "text-muted", badge: "badge", bar: "bg-[color:var(--line-strong)]" };
}

/**
 * Resuelve la banda de un rival combinando el perfil de plantillas con la
 * auditoría de caja (``/api/rival-intel``). Los campos del perfil mandan: si el
 * backend ya los publica en ``/api/squads`` no hace falta la tabla auxiliar.
 */
export function liquidityRead(
  squad: RivalSquad | null | undefined,
  team?: RivalFinancialTeam | null,
): LiquidityRead {
  const reconciliation =
    (squad?.reconciliation as CashReconciliation | null | undefined) ?? team?.reconciliation ?? null;
  // ``squads.cash_eur`` es el saldo que publica la API cuando existe, no la
  // cota; la cifra que se aprieta es ``calculated_cash``. Comparar contra la
  // observada pintaría «calibrado» justo cuando la cota se quedó corta.
  const calculated = firstNumber(squad?.calculated_cash, team?.calculated_cash);
  const observed = firstNumber(
    reconciliation?.observed_cash_eur,
    squad?.cash_eur,
  );
  const cash = calculated ?? firstNumber(squad?.cash_eur);
  const calibratedCash = firstNumber(squad?.risk_adjusted_cash, team?.risk_adjusted_cash, cash);
  const debt = firstNumber(squad?.debt_limit_eur, team?.debt_limit_eur) ?? 0;
  const rawBidLimit = firstNumber(
    squad?.max_bid_limit,
    team?.max_bid_limit,
    cash === null ? null : Math.max(0, cash + debt),
  );
  const bidLimit = firstNumber(
    squad?.risk_adjusted_bid_limit,
    team?.risk_adjusted_bid_limit,
    calibratedCash === null ? null : Math.max(0, calibratedCash + debt),
    rawBidLimit,
  );
  const arbitrageEur = firstNumber(squad?.arbitrage_eur, reconciliation?.arbitrage_eur);
  const temperature = firstNumber(squad?.temperature, reconciliation?.temperature);

  const level = temperatureLevel(temperature);
  // La cota se aprieta cuando queda por debajo de la reconstruida. Si además
  // queda por debajo de la observada, el backend no lo permite (nunca inventa
  // una cota bajo un hecho): eso sería un bug, no un descuento.
  const tightened =
    cash !== null &&
    calibratedCash !== null &&
    calibratedCash < cash &&
    (observed === null || calibratedCash >= observed);
  const raised =
    (cash !== null && calibratedCash !== null && calibratedCash > cash) ||
    (observed !== null && cash !== null && observed > cash);
  const bidTightened = rawBidLimit !== null && bidLimit !== null && bidLimit < rawBidLimit;

  return {
    cash,
    calibratedCash,
    tightened,
    raised,
    bidLimit,
    rawBidLimit,
    bidTightened,
    arbitrageEur,
    temperature,
    temperaturePct: temperature === null ? null : Math.round(temperature * 100),
    level,
    tone: temperatureTone(level),
    calibrated: temperature !== null || tightened || bidTightened,
    reconciliation,
  };
}

/**
 * Copia la banda calibrada al perfil de plantilla.
 *
 * La foto de plantillas puede no traer todavía los campos nuevos (caché vieja)
 * mientras que la auditoría de caja sí los publica. Sin esta fusión la tarjeta
 * pintaría la caja plana y el descuento del grupo de control no se vería.
 */
export function applyLiquidity(
  squad: RivalSquad | null | undefined,
  team?: RivalFinancialTeam | null,
): RivalSquad | null {
  if (!squad) return null;
  // Sin auditoría de caja no hay nada que fusionar; si la hay, se recalcula
  // siempre para que la cota y la referencia tachada salgan de la misma fuente.
  if (!team) return squad;
  const read = liquidityRead(squad, team);
  return {
    ...squad,
    risk_adjusted_cash: read.calibratedCash,
    calculated_cash: squad.calculated_cash ?? team?.calculated_cash ?? null,
    risk_adjusted_bid_limit: read.bidLimit,
    max_bid_limit: squad.max_bid_limit ?? read.rawBidLimit,
    debt_limit_eur: squad.debt_limit_eur ?? team?.debt_limit_eur ?? null,
    cash_is_upper_bound: squad.cash_is_upper_bound ?? team?.cash_is_upper_bound ?? null,
    temperature: read.temperature,
    arbitrage_eur: read.arbitrageEur,
    reconciliation: squad.reconciliation ?? team?.reconciliation ?? null,
  };
}

/** Índice ``team_id → equipo auditado`` para cruzar con las plantillas. */
export function financialIndex(
  teams: Record<string, RivalFinancialTeam> | null | undefined,
): Map<string, RivalFinancialTeam> {
  const map = new Map<string, RivalFinancialTeam>();
  if (!teams) return map;
  for (const [key, team] of Object.entries(teams)) {
    if (!team || typeof team !== "object") continue;
    map.set(String(team.team_id ?? key), team);
  }
  return map;
}
