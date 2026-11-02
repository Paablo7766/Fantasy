import type { ApiRisk, ApiSourceUsage, ApiStability, ApiTimelinePoint, ApiUsagePayload } from "@/lib/types";

export type RateTone = "good" | "warn" | "bad";

/** Las mismas bandas que ``toolbox/api_meter.py``. Solo orientan, no son un cupo. */
export const RATE_STOPS = [
  { limit: 30, label: "bajo" },
  { limit: 60, label: "normal" },
  { limit: 100, label: "alto" },
  { limit: 160, label: "muy alto" },
] as const;

export function riskTone(level: string | undefined): RateTone {
  if (level === "alto") return "bad";
  if (level === "medio") return "warn";
  return "good";
}

export function riskLabel(level: string | undefined): string {
  if (level === "alto") return "Riesgo alto";
  if (level === "medio") return "Vigilar";
  if (level === "bajo") return "Sin riesgo";
  return "Sin datos";
}

export function riskBadge(level: string | undefined): string {
  const tone = riskTone(level);
  if (tone === "bad") return "badge badge--bad";
  if (tone === "warn") return "badge badge--warn";
  return "badge badge--good";
}

/** Posición 0–1 del marcador en la barra de ritmo, con tope en 160/min. */
export function ratePosition(perMinute: number | null | undefined): number {
  if (typeof perMinute !== "number" || !Number.isFinite(perMinute)) return 0;
  return Math.max(0, Math.min(1, perMinute / 160));
}

export function rateBandLabel(perMinute: number | null | undefined): string {
  if (typeof perMinute !== "number" || !Number.isFinite(perMinute)) return "sin lectura";
  for (const stop of RATE_STOPS) {
    if (perMinute < stop.limit) return stop.label;
  }
  return RATE_STOPS[RATE_STOPS.length - 1].label;
}

/** Escala de barras del histórico por minuto: relativa al pico de la ventana. */
export function timelineScale(timeline: ApiTimelinePoint[] | undefined): number {
  const peak = (timeline || []).reduce((max, point) => Math.max(max, point.calls || 0), 0);
  return Math.max(peak, 4);
}

export function maxSourceCalls(sources: ApiSourceUsage[] | undefined): number {
  const peak = (sources || []).reduce((max, row) => Math.max(max, row.calls_10m || 0), 0);
  return Math.max(peak, 1);
}

export function shortDuration(seconds: number | null | undefined): string {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds <= 0) return "ahora";
  if (seconds < 90) return `${Math.round(seconds)} s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)} h`;
  return `${Math.round(seconds / 86400)} d`;
}

export function perMinute(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${value.toLocaleString("es-ES", { maximumFractionDigits: 1 })}/min`;
}

/**
 * Lectura en una frase para el botón de la cabecera. Sin jerga: dice cuántas
 * llamadas van por minuto y si eso es mucho o poco.
 */
export function headlineChip(usage: ApiUsagePayload | null | undefined): string {
  if (!usage || usage.ok === false || !usage.rate) return "—";
  const value = usage.rate.per_minute;
  if (!value) return "en reposo";
  const rate = `${value.toLocaleString("es-ES", { maximumFractionDigits: 0 })}/min`;
  // Ritmo sano pero respuestas 5xx: el número engaña, así que se dice.
  if (usage.stability?.level === "warn" && (usage.stability.errors_10m || 0) > 0) {
    return `${rate} · fuente caída`;
  }
  return rate;
}

/** Tono del indicador: manda el bloqueo, después la inestabilidad, luego el ritmo. */
export function usageTone(usage: ApiUsagePayload | null | undefined): RateTone {
  const risk = riskTone(usage?.risk?.level);
  if (risk === "bad") return "bad";
  if (usage?.stability?.level === "warn" || risk === "warn") return "warn";
  return "good";
}

/** Motivos listos para pintar: los del motor y, si faltan, un resumen neutro. */
export function riskReasons(risk: ApiRisk | null | undefined): string[] {
  if (!risk) return [];
  if (risk.reasons?.length) return risk.reasons;
  return ["Sin llamadas registradas todavía en este proceso."];
}

/** Veredicto conjunto para el badge grande: un 5xx sostenido no es «sin riesgo». */
export function usageVerdict(usage: ApiUsagePayload | null | undefined): { label: string; badge: string } {
  const level = usage?.risk?.level;
  if (level === "alto") return { label: "Riesgo alto", badge: "badge badge--bad" };
  if (level === "medio") return { label: "Vigilar", badge: "badge badge--warn" };
  if (usage?.stability?.level === "warn") return { label: "Fuente inestable", badge: "badge badge--warn" };
  if (level === "bajo") return { label: "Sin riesgo", badge: "badge badge--good" };
  return { label: "Sin datos", badge: "badge badge--good" };
}

/** Etiqueta corta del estado de una fuente (429 gana a cualquier otro matiz). */
export function sourceState(row: ApiSourceUsage): { label: string; tone: RateTone } {
  if (row.rate_limited > 0) return { label: "429", tone: "bad" };
  if (row.auth > 0) return { label: "sesión", tone: "warn" };
  if ((row.errors_pending ?? row.errors) > 0) {
    return { label: `${row.errors_pending ?? row.errors} caída(s)`, tone: "warn" };
  }
  if ((row.recovered ?? 0) > 0) return { label: "resuelto", tone: "good" };
  if (row.calls_1m > 0) return { label: "activa", tone: "good" };
  if (row.calls > 0) return { label: "en pausa", tone: "good" };
  return { label: "sin uso", tone: "good" };
}

/** Mezcla de códigos HTTP en una línea legible: «200×12 · 502×4». */
export function statusMixLabel(mix: Record<string, number> | undefined): string {
  if (!mix) return "";
  return Object.entries(mix)
    .map(([code, count]) => `${code === "red" ? "red" : code}×${count}`)
    .join(" · ");
}

/** Tono de la estabilidad: un 5xx suelto no es alarma, pero se ve. */
export function stabilityTone(stability: ApiStability | null | undefined): RateTone {
  return stability?.level === "warn" ? "warn" : "good";
}