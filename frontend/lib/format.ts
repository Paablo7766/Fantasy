import type { ApiError, ClauseLock, Player } from "@/lib/types";

export const MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

export function eur(value: number | null | undefined): string {
  if (typeof value !== "number") return "s/d";
  return new Intl.NumberFormat("es-ES", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(value);
}

/** Importe compacto para celdas estrechas: 8,57 M€ · 940 mil € · 320 €. */
export function eurShort(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "s/d";
  const abs = Math.abs(value);
  if (abs >= 1_000_000) {
    return `${(value / 1_000_000).toLocaleString("es-ES", { maximumFractionDigits: 2 })} M€`;
  }
  if (abs >= 1_000) return `${Math.round(value / 1_000).toLocaleString("es-ES")} mil €`;
  return `${Math.round(value).toLocaleString("es-ES")} €`;
}

export function points(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "s/d";
  return value.toLocaleString("es-ES", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

type LineupRow = {
  jornada_ev?: number | null;
  expected_points?: number | null;
  p_titular?: number | null;
};

/** Probabilidad de titular en escala 0–1 (acepta 0–100 de fuentes legacy). */
export function titularShare(value: number | null | undefined): number | null {
  if (typeof value !== "number" || Number.isNaN(value)) return null;
  let share = value;
  if (share > 1) {
    if (share > 100) return null;
    share /= 100;
  }
  if (share < 0 || share > 1) return null;
  return share;
}

/** Valor esperado de la jornada para un jugador del once. */
export function jornadaEv(row: LineupRow | null | undefined): number | null {
  if (!row) return null;
  if (typeof row.jornada_ev === "number" && !Number.isNaN(row.jornada_ev)) return row.jornada_ev;
  if (typeof row.expected_points !== "number" || Number.isNaN(row.expected_points)) return null;
  const share = titularShare(row.p_titular) ?? 1;
  return row.expected_points * share;
}

/** E[pts] del once: suma de ``jornada_ev`` por jugador. */
export function projectedLineupPoints(xi: LineupRow[] | null | undefined): number | null {
  if (!Array.isArray(xi) || xi.length === 0) return null;
  let total = 0;
  let found = false;
  for (const row of xi) {
    const ev = jornadaEv(row);
    if (ev === null) continue;
    total += ev;
    found = true;
  }
  return found ? Math.round(total * 10) / 10 : null;
}

export function pct(value: number | null | undefined): string {
  const share = titularShare(value);
  if (share === null) return "s/d";
  return `${Math.round(share * 100)}%`;
}

export function multiple(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "s/d";
  return `${value.toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}×`;
}

export function accel(value: number | null | undefined): string {
  if (typeof value !== "number") return "s/d";
  const sign = value > 0 ? "+" : "";
  return sign + value.toLocaleString("es-ES");
}

/** Δ del día con signo y símbolo € (sumas de plantilla). */
export function deltaEur(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "s/d";
  const sign = value > 0 ? "+" : "";
  return (
    sign +
    new Intl.NumberFormat("es-ES", {
      style: "currency",
      currency: "EUR",
      maximumFractionDigits: 0,
    }).format(value)
  );
}

export function deltaTone(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "text-muted";
  if (value < 0) return "text-coral";
  if (value > 0) return "text-mint";
  return "text-muted";
}

export function playerName(player: Player | null | undefined): string {
  return player?.nickname || player?.name || "Jugador";
}

export function initials(name: string): string {
  const parts = String(name || "?").split(/\s+/).filter(Boolean);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function stamp(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return String(iso);
  return new Intl.DateTimeFormat("es-ES", {
    timeZone: "Europe/Madrid",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

/** Edad relativa de una marca local (ms epoch), p. ej. copia en localStorage. */
export function relativeAgo(ts: number | null | undefined): string {
  if (typeof ts !== "number" || !Number.isFinite(ts)) return "";
  return durationAgo(Date.now() - ts);
}

/** Edad ya medida en segundos (``photo_age_seconds`` del backend). Función pura. */
export function durationAgo(seconds: number | null | undefined): string {
  if (typeof seconds !== "number" || !Number.isFinite(seconds)) return "";
  const sec = Math.max(0, Math.round(seconds));
  if (sec < 45) return "ahora";
  if (sec < 3600) {
    const min = Math.max(1, Math.round(sec / 60));
    return `hace ${min} min`;
  }
  if (sec < 86400) {
    const hours = Math.max(1, Math.round(sec / 3600));
    return `hace ${hours} h`;
  }
  const days = Math.max(1, Math.round(sec / 86400));
  return `hace ${days} d`;
}

/**
 * Duración «de reloj» de una descarga en curso: ``4 min 12 s``. A diferencia de
 * ``durationAgo`` no redondea a la unidad grande, porque aquí interesa ver que
 * el cronómetro corre aunque la fase no cambie.
 */
export function elapsedLabel(seconds: number | null | undefined): string {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return "—";
  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) return `${hours} h ${String(minutes).padStart(2, "0")} min`;
  if (minutes > 0) return `${minutes} min ${String(secs).padStart(2, "0")} s`;
  return `${secs} s`;
}

/**
 * Edad de la foto **en vivo**: ``photo_age_seconds`` es una foto del instante en
 * que el backend respondió; si la interfaz la pinta tal cual, se queda congelada
 * en «hace 2 min» durante horas y el usuario cree que el dato es más nuevo de lo
 * que es. Aquí se suma el tiempo transcurrido desde la lectura.
 */
export function liveAge(photoAgeSeconds: number | null | undefined, readAtMs: number, nowMs: number): number | null {
  if (typeof photoAgeSeconds !== "number" || !Number.isFinite(photoAgeSeconds)) return null;
  if (!readAtMs || !nowMs || nowMs < readAtMs) return photoAgeSeconds;
  return photoAgeSeconds + (nowMs - readAtMs) / 1000;
}

/**
 * Edad calculada desde el sello absoluto de captura (``last_updated``).
 *
 * Es la forma preferida cuando el documento trae su propia marca: no hace falta
 * recordar cuándo se leyó, así que no hay estado ni refs que puedan quedar
 * desfasados y el valor es correcto incluso tras un ``reload``.
 */
export function ageFromStamp(iso: string | null | undefined, nowMs: number): number | null {
  if (!iso || !nowMs) return null;
  const parsed = Date.parse(iso);
  if (Number.isNaN(parsed)) return null;
  return Math.max(0, (nowMs - parsed) / 1000);
}

export function clockLabel(lock: ClauseLock | null | undefined): string {
  if (!lock || lock.present !== true || !lock.local_date || !lock.local_time) {
    return "Sin marca de la API";
  }
  const [, month, day] = String(lock.local_date).split("-");
  const monthName = MONTHS[Number(month) - 1] || month;
  const time = lock.local_clock || lock.local_time;
  const year = String(lock.local_date).split("-")[0];
  return `${Number(day)} ${monthName} ${year} · ${time}`;
}

export function glass(extra = ""): string {
  return `card ${extra}`;
}

export function errorMessage(payload: ApiError | null | undefined): string {
  return payload?.error?.message || payload?.message || "No se pudo cargar este bloque.";
}

export function cashClass(value: number | null | undefined): string {
  if (typeof value !== "number") return "text-muted";
  return value < 0 ? "text-coral" : "text-mint";
}

/** Rentabilidad como porcentaje (0,12 → +12 %). */
export function roiPct(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "s/d";
  const sign = value > 0 ? "+" : "";
  return `${sign}${(value * 100).toLocaleString("es-ES", { maximumFractionDigits: 1 })} %`;
}
