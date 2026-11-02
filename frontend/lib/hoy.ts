import { eur, points } from "@/lib/format";
import type { PlanClockEvent, PlanPayload } from "@/lib/types";

/**
 * Derivaciones de la Home «Hoy». Todo sale de `/api/plan`: aquí no se inventa
 * ni una hora ni un importe. Lo que falta se marca como «sin dato».
 */

export type CountdownParts = {
  days: number;
  hours: number;
  minutes: number;
  seconds: number;
  totalMs: number;
  expired: boolean;
};

/** Resta pura para no depender del reloj del render (testeable con `nowMs`). */
export function countdownParts(targetMs: number | null, nowMs: number): CountdownParts | null {
  if (targetMs === null || !Number.isFinite(targetMs) || !Number.isFinite(nowMs)) return null;
  const diff = targetMs - nowMs;
  const totalSec = Math.floor(Math.abs(diff) / 1000);
  return {
    days: Math.floor(totalSec / 86400),
    hours: Math.floor((totalSec % 86400) / 3600),
    minutes: Math.floor((totalSec % 3600) / 60),
    seconds: totalSec % 60,
    totalMs: diff,
    expired: diff <= 0,
  };
}

export function two(value: number): string {
  return String(Math.max(0, Math.trunc(value))).padStart(2, "0");
}

/** HH:MM:SS puro. Los días se pintan aparte como insignia. */
export function countdownClock(parts: CountdownParts | null): string {
  if (!parts) return "--:--:--";
  return `${two(parts.hours)}:${two(parts.minutes)}:${two(parts.seconds)}`;
}

export const CLOCK_KIND: Record<string, { label: string; short: string }> = {
  clausulazo_cierra: { label: "Cierre de clausulazos", short: "Cierre" },
  inicio_jornada: { label: "Inicio de jornada", short: "Jornada" },
  desbloqueo: { label: "Desbloqueo de cláusula", short: "Desbloqueo" },
  snipe: { label: "Snipe de puja", short: "Snipe" },
};

export type TimedClockEvent = PlanClockEvent & {
  /** ms epoch del `at` en UTC; null si la API no trae hora. */
  ms: number | null;
  /** Texto local (Europe/Madrid) que ya calcula el backend. */
  localLabel: string;
  kindLabel: string;
  isPast: boolean;
};

export type ClockReport = {
  events: TimedClockEvent[];
  next: TimedClockEvent | null;
  upcoming: TimedClockEvent[];
  /** true cuando el último evento conocido ya pasó. */
  exhausted: boolean;
};

function localLabel(event: PlanClockEvent): string {
  const date = event.local_date || "";
  const time = event.local_time || event.local_clock?.slice(0, 5) || "";
  if (!date && !time) return "sin hora";
  const [, month, day] = date.split("-");
  if (!day) return time || "sin hora";
  return `${Number(day)}/${month} · ${time}`;
}

/**
 * Ordena el reloj del backend y separa lo que aún no ha pasado. Los eventos sin
 * `at` se conservan al final (informativos, nunca se usan como cuenta atrás).
 */
export function buildClockReport(plan: PlanPayload | null, nowMs: number): ClockReport {
  const raw = Array.isArray(plan?.clock) ? plan.clock : [];
  const events: TimedClockEvent[] = raw.map((event) => {
    const parsed = typeof event.at === "string" ? Date.parse(event.at) : Number.NaN;
    const ms = Number.isNaN(parsed) ? null : parsed;
    return {
      ...event,
      ms,
      localLabel: localLabel(event),
      kindLabel: CLOCK_KIND[event.kind || ""]?.short || "Evento",
      isPast: ms !== null ? ms <= nowMs : false,
    };
  });
  events.sort((a, b) => {
    if (a.ms === null && b.ms === null) return 0;
    if (a.ms === null) return 1;
    if (b.ms === null) return -1;
    return a.ms - b.ms;
  });
  const upcoming = events.filter((event) => event.ms !== null && event.ms > nowMs);
  return {
    events,
    next: upcoming[0] || null,
    upcoming,
    exhausted: events.length > 0 && upcoming.length === 0,
  };
}

/**
 * El backend ya etiqueta el evento («Desbloqueo Foyth») y el tipo también
 * («Desbloqueo»). Se elige el más informativo para no repetir la palabra.
 */
export function eventTitle(event: TimedClockEvent): string {
  const label = (event.label || "").trim();
  if (!label) return event.kindLabel;
  if (!event.kindLabel || label.toLowerCase().startsWith(event.kindLabel.toLowerCase())) return label;
  return `${event.kindLabel} · ${label}`;
}

export type CheckTone = "ok" | "risk" | "blocker";

export type SurvivalCheck = {
  id: "caja" | "xi" | "clausulas" | "once";
  label: string;
  value: string;
  detail: string;
  tone: CheckTone;
};

export type SurvivalReport = {
  checks: SurvivalCheck[];
  blockers: SurvivalCheck[];
  risks: SurvivalCheck[];
  /** Bloqueo de jornada: la caja negativa o un XI incompleto valen cero puntos. */
  blocked: boolean;
  headline: string;
  detail: string;
};

const POSITIONS = new Set(["POR", "DEF", "MC", "DEL"]);

/**
 * Línea roja. Manda `plan.red_line` (cuenta huecos del solver y el once
 * guardado); la derivación local es solo la red de seguridad si no viene.
 */
export function buildSurvival(plan: PlanPayload | null): SurvivalReport {
  const red = plan?.red_line;
  if (red && Array.isArray(red.checks) && red.checks.length > 0) {
    const idFor = (key: string | undefined): SurvivalCheck["id"] =>
      key === "cash" ? "caja" : key === "xi" ? "xi" : "once";
    // El backend manda el check con su detalle; aquí solo se evita repetir la
    // misma cifra dos veces (valor a la derecha + detalle debajo).
    const detailFor = (key: string | undefined, status: string | undefined, raw: string): string => {
      if (key === "cash") {
        return status === "fail"
          ? "Caja negativa: el motor anula la jornada y la puntuación es cero."
          : "Ninguna compra puede dejar la caja en descubierto.";
      }
      if (key === "xi") {
        return status === "fail"
          ? "Faltan jugadores por posición: jornada incompleta = cero puntos."
          : "Las cuatro posiciones están cubiertas dentro del once.";
      }
      if (key === "lineup") {
        return status === "warn"
          ? "El once del motor suma puntos o cierra un hueco: guárdalo antes del cierre."
          : "Once guardado y recomendado coinciden, o el cambio no mejora puntos.";
      }
      return raw || "Sin cambios pendientes.";
    };
    const checks: SurvivalCheck[] = red.checks.map((check) => {
      const tone: CheckTone =
        check.status === "fail" ? "blocker" : check.status === "ok" ? "ok" : "risk";
      return {
        id: idFor(check.key),
        label: check.label || check.key || "Check",
        value:
          typeof check.value === "number"
            ? check.key === "cash"
              ? eur(check.value)
              : check.key === "xi"
                ? `${check.value}/11`
                : String(check.value)
            : check.key === "lineup"
              ? check.status === "warn"
                ? "Pendiente"
                : "Guardado"
              : check.detail || "s/d",
        detail: detailFor(check.key, check.status, check.detail || ""),
        tone,
      };
    });
    const blockers = checks.filter((check) => check.tone === "blocker");
    const risks = checks.filter((check) => check.tone === "risk");
    const blocked = red.status === "fail" || blockers.length > 0;
    return {
      checks,
      blockers,
      risks,
      blocked,
      headline: red.headline || (blocked ? "Jornada bloqueada · 0 puntos" : "Línea roja cubierta"),
      detail: blocked
        ? blockers.map((check) => check.label).join(" · ")
        : risks.length
          ? risks.map((check) => check.label).join(" · ")
          : "Caja sana, once completo y ninguna cláusula al alcance rival.",
    };
  }

  const cash = typeof plan?.cash_eur === "number" ? plan.cash_eur : null;
  const xi = Array.isArray(plan?.lineup?.xi) ? plan.lineup.xi : [];
  const valid = xi.filter((row) => row && POSITIONS.has(String(row.position || "").toUpperCase())).length;
  const protect = Array.isArray(plan?.protect) ? plan.protect : [];
  const exposed = protect.filter((row) => Number(row.threat_count || 0) > 0);
  const unfixable = exposed.filter(
    (row) =>
      Array.isArray(row.options) &&
      row.options.some((option) => option.kind === "subir_clausula" && option.eligible === false),
  );

  const checks: SurvivalCheck[] = [];

  if (cash === null) {
    checks.push({
      id: "caja",
      label: "Caja ≥ 0",
      value: "sin dato",
      detail: "El plan no trae la caja del equipo. No se puede firmar la supervivencia.",
      tone: "risk",
    });
  } else if (cash < 0) {
    checks.push({
      id: "caja",
      label: "Caja ≥ 0",
      value: eur(cash),
      detail: "Caja negativa: el motor anula la jornada y la puntuación es cero.",
      tone: "blocker",
    });
  } else {
    checks.push({
      id: "caja",
      label: "Caja ≥ 0",
      value: eur(cash),
      detail: "Saldo positivo. Ninguna compra puede dejar la caja en descubierto.",
      tone: "ok",
    });
  }

  if (xi.length === 0) {
    checks.push({
      id: "xi",
      label: "XI con 11 válidos",
      value: "sin once",
      detail: "El plan no devolvió la alineación recomendada. Verifica en Once antes del cierre.",
      tone: "risk",
    });
  } else if (valid < 11) {
    checks.push({
      id: "xi",
      label: "XI con 11 válidos",
      value: `${valid}/11`,
      detail: `Faltan ${11 - valid} jugador(es) por posición. Jornada incompleta = cero puntos.`,
      tone: "blocker",
    });
  } else {
    checks.push({
      id: "xi",
      label: "XI con 11 válidos",
      value: `${valid}/11`,
      detail: `Formación ${plan?.lineup?.formation || "s/d"} con las cuatro posiciones cubiertas.`,
      tone: "ok",
    });
  }

  if (exposed.length === 0) {
    checks.push({
      id: "clausulas",
      label: "Cláusulas expuestas",
      value: "0",
      detail: "Ningún rival con caja conocida llega a una cláusula tuya.",
      tone: "ok",
    });
  } else {
    const detail = unfixable.length
      ? `${unfixable.length} sin caja para subir la cláusula. Prioriza vender o blindar antes del cierre.`
      : "Hay caja para subir la cláusula del rival más rico. Revisa el importe antes del cierre.";
    checks.push({
      id: "clausulas",
      label: "Cláusulas expuestas",
      value: String(exposed.length),
      detail,
      // Una cláusula pagada no anula la jornada: es riesgo, nunca bloqueo de cero.
      tone: "risk",
    });
  }

  const blockers = checks.filter((check) => check.tone === "blocker");
  const risks = checks.filter((check) => check.tone === "risk");
  const blocked = blockers.some((check) => check.id === "caja" || check.id === "xi");

  return {
    checks,
    blockers,
    risks,
    blocked,
    headline: blocked ? "Jornada bloqueada · 0 puntos" : risks.length ? "Supervivencia con avisos" : "Supervivencia cubierta",
    detail: blocked
      ? blockers.map((check) => check.label).join(" · ")
      : risks.length
        ? risks.map((check) => check.label).join(" · ")
        : "Caja sana, once completo y ninguna cláusula al alcance rival.",
  };
}

/** Texto con signo para el delta de puntos (nunca inventa un 0). */
export function signedPoints(value: number | null | undefined): string | null {
  if (typeof value !== "number" || Number.isNaN(value)) return null;
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${points(Math.abs(value))}`;
}
