import { eur, points } from "@/lib/format";
import type { PlanAction, PlanClockEvent, PlanPayload, PlanPriorityAction } from "@/lib/types";

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

/**
 * Oleada: varios eventos que caen en el mismo minuto. La API manda 136
 * desbloqueos sueltos; agrupados se leen de un vistazo sin perder ninguno.
 */
export type ClockWave = {
  key: string;
  ms: number;
  kind: string;
  kindLabel: string;
  title: string;
  localLabel: string;
  count: number;
  /** Nombres de los jugadores de la oleada (sin repetir). */
  names: string[];
  /** Mánagers implicados, por orden de aparición. */
  managers: string[];
};

export function buildClockWaves(clock: ClockReport): ClockWave[] {
  const buckets = new Map<string, ClockWave>();
  for (const event of clock.upcoming) {
    if (event.ms === null) continue;
    const kind = event.kind || "evento";
    // Se agrupa por minuto: 9 desbloqueos a las 14:08 se leen como una oleada.
    const minute = Math.floor(event.ms / 60_000);
    const key = `${kind}-${minute}`;
    const existing = buckets.get(key);
    const player = (event.nickname || event.name || "").trim();
    const manager = (event.manager_name || "").trim();
    if (existing) {
      existing.count += 1;
      if (player && !existing.names.includes(player)) existing.names.push(player);
      if (manager && !existing.managers.includes(manager)) existing.managers.push(manager);
      continue;
    }
    buckets.set(key, {
      key,
      ms: event.ms,
      kind,
      kindLabel: event.kindLabel,
      title: event.label || event.kindLabel,
      localLabel: event.localLabel,
      count: 1,
      names: player ? [player] : [],
      managers: manager ? [manager] : [],
    });
  }
  const waves = Array.from(buckets.values()).sort((a, b) => a.ms - b.ms);
  return waves.map((wave) => {
    const solo = wave.count === 1;
    const manager = wave.managers.length === 1 ? wave.managers[0] : null;
    if (wave.kind === "desbloqueo") {
      return {
        ...wave,
        title: solo
          ? wave.title
          : manager
            ? `${wave.count} desbloqueos · ${manager}`
            : `${wave.count} desbloqueos`,
      };
    }
    return { ...wave, title: solo ? wave.title : `${wave.count} · ${wave.kindLabel.toLowerCase()}` };
  });
}

/** Resumen de lo que llega en las próximas 48 h (mismo corte que el backend). */
export function clockOutlook(clock: ClockReport, nowMs: number): { unlocks: number; windows: number } {
  const horizon = nowMs + 48 * 3_600_000;
  const soon = clock.upcoming.filter((event) => event.ms !== null && event.ms <= horizon);
  const windows = new Set(soon.map((event) => `${event.kind}-${Math.floor((event.ms as number) / 60_000)}`));
  return { unlocks: soon.length, windows: windows.size };
}

/** Exposición real de la plantilla: cláusulas que un rival puede pagar hoy. */
export type ExposureReport = {
  count: number;
  total: number;
  /** La cláusula más barata: la que antes cae. */
  cheapest: { name: string; clause: number; threats: number } | null;
  /** Máximo de rivales con caja para pagar una cláusula propia. */
  threats: number;
};

export function buildExposure(plan: PlanPayload | null): ExposureReport {
  const rows = Array.isArray(plan?.protect) ? plan.protect : [];
  const exposed = rows
    .filter((row) => Number(row.threat_count || 0) > 0)
    .map((row) => ({
      name: row.nickname || row.name || "Jugador",
      clause: typeof row.buyout_clause_eur === "number" ? row.buyout_clause_eur : Number.POSITIVE_INFINITY,
      threats: Number(row.threat_count || 0),
    }));
  exposed.sort((a, b) => a.clause - b.clause);
  const cheapest = exposed[0];
  return {
    count: exposed.length,
    total: rows.length,
    cheapest:
      cheapest && Number.isFinite(cheapest.clause)
        ? { name: cheapest.name, clause: cheapest.clause, threats: cheapest.threats }
        : null,
    threats: exposed.reduce((max, row) => Math.max(max, row.threats), 0),
  };
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

const ACTION_LABEL: Record<string, string> = {
  alinear: "Alinear XI",
  pujar: "Pujar",
  clausular: "Pagar cláusula",
  subir_clausula: "Subir cláusula",
  vender: "Vender",
  blindar: "Blindar",
  cerrar_hueco: "Cerrar hueco",
  vender_emergencia: "Venta obligatoria",
};

/** Acciones de once: no cuestan dinero y se miden en puntos, no en euros. */
export const LINEUP_KINDS = new Set(["alinear", "cerrar_hueco", "vender_emergencia"]);

const OVERBID_LABEL: Record<string, string> = {
  high: "Sobreuja alta",
  medium: "Sobreuja media",
  low: "Sin sobreuja",
  unknown: "Sobreuja sin dato",
};

export type ActionRisk = "high" | "medium" | "low" | "unknown" | null;

export type ActionCard = {
  key: string;
  kind: string;
  verb: string;
  title: string;
  playerName: string | null;
  playerId: string | null;
  position: string | null;
  imageUrl: string | null;
  amount: number | null;
  /** Importe ya formateado por el motor (`cost_label`) o el que derive el front. */
  costLabel: string | null;
  cashAfter: number | null;
  whenLabel: string;
  whenTone: "now" | "later" | "unknown";
  detail: string;
  risk: ActionRisk;
  riskLabel: string | null;
  pointsDelta: number | null;
  requiresConfirmation: boolean;
  eligible: boolean;
  blockedReason: string | null;
  copyValue: string | null;
  copyLabel: string | null;
  href: string;
  /** Qué se hace, en una frase del backend (`priority_actions.what`). */
  what: string | null;
  /** Qué pasa si no lo haces (`priority_actions.ignore`). */
  ignore: string | null;
  verdict: "HAZLO" | "NO" | null;
  rank: number | null;
  /** Acción de once (alinear, cerrar hueco, venta obligatoria). */
  isLineup: boolean;
  /** Excepción de supervivencia: se ejecuta aunque el movimiento reste puntos. */
  isSurvival: boolean;
};

const INELIGIBLE_REASON: Record<string, string> = {
  caja_insuficiente: "No hay caja para este movimiento.",
  ventana_cerrada: "La ventana de clausulazos está cerrada.",
  hueco_por_cerrar: "Tapa el hueco en el mercado antes de guardar el once.",
  hueco_sin_oferta: "No hay fichaje en el mercado para ese hueco.",
  caja_negativa: "La caja está en rojo: el motor anula la jornada.",
  resta_puntos: "Este cambio baja los puntos esperados del once.",
};

const HREF_BY_KIND: Record<string, string> = {
  alinear: "/once",
  pujar: "/mercado",
  clausular: "/clausulazos",
  subir_clausula: "/clausulazos",
  vender: "/cartera",
  blindar: "/clausulazos",
  cerrar_hueco: "/mercado",
  vender_emergencia: "/cartera",
};

/**
 * Las tarjetas de la home. `plan.priority_actions` ya trae what / cost / when /
 * ignore y el veredicto HAZLO/NO: se usa tal cual. Sin él se cae a `actions`
 * (misma derivación, sin las frases del motor).
 */
export function buildActionCards(plan: PlanPayload | null, limit = 4): ActionCard[] {
  const prioritized = Array.isArray(plan?.priority_actions) ? plan.priority_actions : [];
  const actions: PlanAction[] = prioritized.length
    ? prioritized
    : Array.isArray(plan?.actions)
      ? plan.actions
      : [];
  const lineupDelta =
    typeof plan?.lineup?.points_delta === "number" ? plan.lineup.points_delta : null;
  const order = actions
    .map((action, index) => ({ action, index }))
    .sort((left, right) => {
      const leftBlocked = left.action.eligible === false ? 1 : 0;
      const rightBlocked = right.action.eligible === false ? 1 : 0;
      return leftBlocked - rightBlocked || left.index - right.index;
    });

  return order.slice(0, Math.max(0, limit)).map(({ action, index }) => {
    const priority = action as PlanPriorityAction;
    const kind = action.kind || "accion";
    const name = action.nickname || action.name || null;
    const verb = ACTION_LABEL[kind] || kind;
    const when = action.when === "snipe" ? "snipe" : action.when === "ahora" ? "ahora" : "sin hora";
    const whenLabel =
      typeof priority.when_label === "string" && priority.when_label.trim()
        ? priority.when_label
        : when === "snipe"
          ? action.when_local_time
            ? `Snipe ${action.when_local_time}`
            : "Snipe sin hora"
          : when === "ahora"
            ? "Ahora"
            : "Sin ventana";
    const risk = (action.overbid_status as ActionRisk) ?? null;
    const isLineup = LINEUP_KINDS.has(kind);
    // Alinear no cuesta dinero: el importe útil es el delta de puntos del XI.
    const pointsDelta = kind === "alinear"
      ? lineupDelta
      : typeof action.points_delta === "number"
        ? action.points_delta
        : null;
    const copyable =
      (kind === "pujar" || kind === "clausular" || kind === "subir_clausula") &&
      typeof action.amount_eur === "number";
    const verdict = priority.verdict === "HAZLO" || priority.verdict === "NO" ? priority.verdict : null;
    return {
      key: `${kind}-${action.player_id || index}-${index}`,
      kind,
      verb,
      title: typeof priority.what === "string" && priority.what.trim() ? priority.what : name ? `${verb} · ${name}` : verb,
      playerName: name,
      playerId: action.player_id || null,
      position: action.position || null,
      imageUrl: action.image_url || null,
      amount: kind === "alinear" ? null : typeof action.amount_eur === "number" ? action.amount_eur : null,
      costLabel:
        typeof priority.cost_label === "string" && priority.cost_label.trim()
          ? priority.cost_label
          : isLineup
            ? "Gratis"
            : null,
      cashAfter: typeof action.cash_after_eur === "number" ? action.cash_after_eur : null,
      whenLabel,
      whenTone: when === "ahora" ? "now" : when === "snipe" ? "later" : "unknown",
      detail: action.detail || "",
      risk,
      riskLabel: risk ? OVERBID_LABEL[risk] || risk : null,
      pointsDelta,
      requiresConfirmation: action.requires_confirmation === true,
      eligible: action.eligible !== false,
      blockedReason:
        typeof priority.blocked_reason === "string" && priority.blocked_reason.trim()
          ? priority.blocked_reason
          : action.eligible === false
            ? INELIGIBLE_REASON[action.reason || ""] || "Acción no ejecutable."
            : null,
      copyValue: copyable ? String(action.amount_eur) : null,
      copyLabel: copyable
        ? kind === "pujar"
          ? "Copiar puja"
          : kind === "clausular"
            ? "Copiar cláusula"
            : "Copiar subida"
        : null,
      href: HREF_BY_KIND[kind] || "/mercado",
      what: typeof priority.what === "string" && priority.what.trim() ? priority.what : null,
      ignore: typeof priority.ignore === "string" && priority.ignore.trim() ? priority.ignore : null,
      verdict,
      rank: typeof priority.rank === "number" ? priority.rank : null,
      isLineup,
      isSurvival: kind === "cerrar_hueco" || kind === "vender_emergencia",
    };
  });
}

/** Texto con signo para el delta de puntos (nunca inventa un 0). */
export function signedPoints(value: number | null | undefined): string | null {
  if (typeof value !== "number" || Number.isNaN(value)) return null;
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${points(Math.abs(value))}`;
}

/** Etiqueta corta del evento, con el jugador cuando lo hay. */
export function clockEventDetail(event: TimedClockEvent): string {
  const parts = [event.localLabel];
  if (event.manager_name) parts.push(event.manager_name);
  if (typeof event.amount_eur === "number") parts.push(eur(event.amount_eur));
  return parts.join(" · ");
}

/**
 * Ventana de decisión. A 60 min del siguiente cierre se prepara la orden; a 10
 * min solo se ejecuta. No es una hora inventada: sale del `at` del backend.
 */
export type DeadlineMode = {
  phase: "t10" | "t60" | "normal" | "none";
  label: string;
  detail: string;
  /** ms hasta el evento; null si no hay evento con hora. */
  ms: number | null;
  event: TimedClockEvent | null;
};

export function buildDeadlineMode(clock: ClockReport, nowMs: number = Date.now()): DeadlineMode {
  const next = clock.next;
  if (!next || next.ms === null) {
    return {
      phase: "none",
      label: "Sin cierre a la vista",
      detail: "La API no trae horas: el plan no inventa una cuenta atrás.",
      ms: null,
      event: null,
    };
  }
  const ms = next.ms - nowMs;
  const minutes = Math.max(0, Math.floor(ms / 60_000));
  if (ms <= 10 * 60_000) {
    return {
      phase: "t10",
      label: "T-10 · ejecuta o suelta",
      detail: `Quedan ${minutes} min para ${next.label || next.kindLabel}. Solo movimientos ya decididos.`,
      ms,
      event: next,
    };
  }
  if (ms <= 60 * 60_000) {
    return {
      phase: "t60",
      label: "T-60 · prepara la orden",
      detail: `Quedan ${minutes} min para ${next.label || next.kindLabel}. Deja caja y once listos.`,
      ms,
      event: next,
    };
  }
  return {
    phase: "normal",
    label: "Fuera de ventana crítica",
    detail: `Siguiente hito en ${Math.floor(ms / 3_600_000)} h. Es momento de planificar, no de improvisar.`,
    ms,
    event: next,
  };
}

/** Postura de liga (ventaja / remontada / neutro) aplicada al plan. */
export function postureCopy(plan: PlanPayload | null): { label: string; headline: string; gap: string | null } | null {
  const mode = plan?.mode;
  if (!mode || !mode.name) return null;
  const gap = mode.gap_to_leader;
  return {
    label: mode.label || mode.name,
    headline: mode.headline || "",
    gap:
      typeof gap === "number"
        ? gap > 0
          ? `${gap} pts por delante del líder`
          : gap === 0
            ? "Empate con el líder"
            : `${Math.abs(gap)} pts por detrás del líder`
        : null,
  };
}