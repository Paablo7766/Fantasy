import { MONTHS } from "@/lib/format";
import type { ClauseBoardPayload, ClauseBoardRow, ClauseLock, ClauseRow, NeedsPayload, SquadsPayload } from "@/lib/types";

export type GuidePhase = "cerrado" | "espera" | "oleada" | "abierto";

export type UnlockEntry = {
  player_id?: string | null;
  name?: string | null;
  nickname?: string | null;
  position?: string | null;
  manager_name?: string | null;
  fantasy_team_name?: string | null;
  buyout_clause_eur?: number | null;
  clause_multiple?: number | null;
  clause_rule?: string | null;
  is_open: boolean;
  local_date: string;
  local_time: string;
  at?: string | null;
  is_self?: boolean;
  /** Cláusula del último día guardado: si es menor, el rival la subió. */
  prev_clause_eur?: number | null;
  clause_delta_eur?: number | null;
  raised_today?: boolean;
  raised_since_photo?: boolean;
};

export type DateBucket = {
  local_date: string;
  label: string;
  count: number;
  open_count: number;
  locked_count: number;
  entries: UnlockEntry[];
  is_peak: boolean;
};

export type ProtectBrief = {
  player_id?: string | null;
  name?: string | null;
  nickname?: string | null;
  position?: string | null;
  buyout_clause_eur?: number | null;
  threat_count?: number | null;
  headline: string;
  detail: string;
  urgent: boolean;
};

export type OfferBrief = {
  player_id?: string | null;
  name?: string | null;
  nickname?: string | null;
  position?: string | null;
  club?: string | null;
  image_url?: string | null;
  manager_name?: string | null;
  buyout_clause_eur?: number | null;
  cash_after_eur?: number | null;
  points_delta?: number | null;
  decision?: string | null;
  reason?: string | null;
  rank: number;
};

export type AlertBrief = {
  player_id?: string | null;
  name?: string | null;
  nickname?: string | null;
  position?: string | null;
  manager_name?: string | null;
  buyout_clause_eur?: number | null;
  local_date?: string | null;
  local_time?: string | null;
  already_open?: boolean | null;
  we_can_pay?: boolean | null;
  eligible?: boolean | null;
  lacks_replacements?: boolean | null;
  lacks_liquidity?: boolean | null;
  motive: string;
};

export type RoadmapStepStatus = "done" | "now" | "next" | "blocked" | "na";

export type RoadmapStep = {
  id: "proteger" | "vigilar" | "elegir" | "ejecutar";
  order: number;
  title: string;
  subtitle: string;
  status: RoadmapStepStatus;
};

export type ChecklistItem = {
  id: string;
  label: string;
  detail?: string;
  done: boolean;
  priority: "critical" | "normal" | "info";
};

export type ClausePlanAction = {
  kind?: string | null;
  player_id?: string | null;
  name?: string | null;
  nickname?: string | null;
  position?: string | null;
  amount_eur?: number | null;
  cash_after_eur?: number | null;
  when?: string | null;
  detail?: string | null;
  eligible?: boolean | null;
  reason?: string | null;
  target_clause_eur?: number | null;
  points_delta?: number | null;
  manager_name?: string | null;
  window_open?: boolean | null;
};

export type Readiness = {
  score: number;
  label: string;
  detail: string;
};

export type ClausulazosGuideModel = {
  phase: GuidePhase;
  phase_title: string;
  phase_detail: string;
  cash_eur?: number | null;
  window_close_label?: string | null;
  window_close_at?: string | null;
  window_open: boolean | null;
  next_unlock_at?: string | null;
  next_unlock_label?: string | null;
  peak_date?: string | null;
  peak_count: number;
  locked_total: number;
  open_total: number;
  timeline: DateBucket[];
  protect: ProtectBrief[];
  offers: OfferBrief[];
  alerts: AlertBrief[];
  top_pick?: OfferBrief | null;
  fetched_at?: string | null;
  roadmap: RoadmapStep[];
  checklist: ChecklistItem[];
  readiness: Readiness;
  playbook: string[];
  clause_actions: ClausePlanAction[];
  upcoming_unlocks: UnlockEntry[];
};

type PlanSlice = {
  ok?: boolean;
  cash_eur?: number | null;
  fetched_at?: string | null;
  clause_market_close?: { at?: string | null; local_date?: string; local_time?: string } | null;
  protect?: Array<Record<string, unknown>>;
  clause_offers?: Array<Record<string, unknown>>;
  actions?: ClausePlanAction[];
};

type ClauseAlertRow = {
  player_id?: string | null;
  name?: string | null;
  nickname?: string | null;
  position?: string | null;
  manager_name?: string | null;
  buyout_clause_eur?: number | null;
  alert_local_date?: string | null;
  alert_local_time?: string | null;
  already_open?: boolean | null;
  we_can_pay?: boolean | null;
  eligible?: boolean | null;
  lacks_replacements?: boolean | null;
  lacks_liquidity?: boolean | null;
  clause_lock?: ClauseLock | null;
};

function parseAt(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? null : ms;
}

function dateLabel(localDate: string, count: number, isPeak: boolean): string {
  const parts = localDate.split("-");
  const day = Number(parts[2]);
  const month = MONTHS[Number(parts[1]) - 1] || parts[1];
  const year = parts[0];
  const key = isPeak && count >= 3 ? " · día clave" : "";
  return `${day} ${month} ${year} · ${count} jugador${count === 1 ? "" : "es"}${key}`;
}

function lockAt(lock: ClauseLock | null | undefined): string | null {
  if (!lock) return null;
  return lock.expires_at || null;
}

function entryFromClause(row: ClauseRow | ClauseBoardRow, isSelf: boolean): UnlockEntry | null {
  const lock = row.clause_lock;
  if (!lock || lock.present !== true || !lock.local_date || !lock.local_time) return null;
  if (row.is_shielded) return null;
  const isOpen = lock.is_locked === false;
  const board = row as ClauseBoardRow;
  return {
    player_id: row.player_id,
    name: row.name,
    nickname: row.nickname,
    position: row.position,
    manager_name: row.manager_name,
    fantasy_team_name: row.fantasy_team_name,
    buyout_clause_eur: row.buyout_clause_eur,
    clause_multiple: row.clause_multiple,
    clause_rule: row.clause_rule,
    is_open: isOpen,
    local_date: lock.local_date,
    local_time: lock.local_time,
    at: lockAt(lock),
    is_self: isSelf,
    prev_clause_eur: board.prev_clause_eur ?? null,
    clause_delta_eur: board.clause_delta_eur ?? null,
    raised_today: board.raised_today === true,
    raised_since_photo: board.raised_since_photo === true,
  };
}

/**
 * Todos los desbloqueos de la liga: los tuyos y los de cualquier rival.
 *
 * ``board`` es opcional y manda cuando está: ``/api/clause-board`` publica
 * **todas** las cláusulas rivales, mientras que ``squads.clauses`` solo trae
 * las que cumplen la regla de oro (A/B). Sin él, la guía vuelve al filtro
 * antiguo, que deja fuera a la mayoría de la liga.
 */
function collectUnlocks(squads: SquadsPayload | null, board?: ClauseBoardPayload | null): UnlockEntry[] {
  const out: UnlockEntry[] = [];
  const selfPlayers = squads?.self?.players || [];
  for (const player of selfPlayers) {
    const row = entryFromClause(
      {
        player_id: player.player_id,
        name: player.name,
        nickname: player.nickname,
        position: player.position,
        manager_name: squads?.self?.manager_name,
        fantasy_team_name: squads?.self?.fantasy_team_name,
        buyout_clause_eur: player.buyout_clause,
        clause_lock: player.clause_lock,
        is_shielded: player.is_shielded ?? undefined,
      },
      true,
    );
    if (row) out.push(row);
  }
  const rivals: Array<ClauseRow | ClauseBoardRow> =
    board?.ok !== false && board?.rows?.length ? board.rows : squads?.clauses || [];
  for (const row of rivals) {
    const mapped = entryFromClause(row, false);
    if (mapped) out.push(mapped);
  }
  out.sort((a, b) => {
    const da = `${a.local_date}T${a.local_time}`;
    const db = `${b.local_date}T${b.local_time}`;
    if (da !== db) return da.localeCompare(db);
    return String(a.player_id).localeCompare(String(b.player_id));
  });
  return out;
}

function buildTimeline(entries: UnlockEntry[]): { timeline: DateBucket[]; peak_date?: string; peak_count: number } {
  const byDate = new Map<string, UnlockEntry[]>();
  for (const entry of entries) {
    const list = byDate.get(entry.local_date) || [];
    list.push(entry);
    byDate.set(entry.local_date, list);
  }
  let peak_date: string | undefined;
  let peak_count = 0;
  for (const [date, list] of byDate) {
    if (list.length > peak_count) {
      peak_count = list.length;
      peak_date = date;
    }
  }
  const timeline: DateBucket[] = [...byDate.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([local_date, list]) => {
      const open_count = list.filter((item) => item.is_open).length;
      const locked_count = list.length - open_count;
      const is_peak = local_date === peak_date && peak_count >= 3;
      return {
        local_date,
        label: dateLabel(local_date, list.length, is_peak),
        count: list.length,
        open_count,
        locked_count,
        entries: list,
        is_peak,
      };
    });
  return { timeline, peak_date, peak_count };
}

function protectBrief(row: Record<string, unknown>): ProtectBrief {
  const options = Array.isArray(row.options) ? row.options : [];
  const subir = options.find((item) => typeof item === "object" && item && (item as { kind?: string }).kind === "subir_clausula") as
    | { amount_eur?: number; target_clause_eur?: number; eligible?: boolean }
    | undefined;
  const threats = typeof row.threat_count === "number" ? row.threat_count : 0;
  const clause = typeof row.buyout_clause_eur === "number" ? row.buyout_clause_eur : null;
  let headline = "Revisar defensa";
  let detail = "Hay rivales con caja que cubren la cláusula.";
  if (subir?.eligible && typeof subir.amount_eur === "number" && typeof subir.target_clause_eur === "number") {
    headline = `Subir cláusula · coste ${subir.amount_eur.toLocaleString("es-ES")} €`;
    detail = `Quedaría en ${subir.target_clause_eur.toLocaleString("es-ES")} € (regla 1:2). Confirma en la app.`;
  } else if (subir && subir.eligible === false) {
    headline = "No cabe subir sin romper caja";
    detail = "Vender o blindar si el rival puede pagar al desbloqueo.";
  }
  return {
    player_id: row.player_id as string | null,
    name: row.name as string | null,
    nickname: row.nickname as string | null,
    position: row.position as string | null,
    buyout_clause_eur: clause,
    threat_count: threats,
    headline,
    detail,
    urgent: threats >= 2 || (typeof clause === "number" && clause > 0 && threats > 0),
  };
}

function offerBrief(row: Record<string, unknown>, rank: number): OfferBrief {
  return {
    player_id: row.player_id as string | null,
    name: row.name as string | null,
    nickname: row.nickname as string | null,
    position: row.position as string | null,
    club: row.club as string | null,
    image_url: row.image_url as string | null,
    manager_name: row.manager_name as string | null,
    buyout_clause_eur: row.buyout_clause_eur as number | null,
    cash_after_eur: row.cash_after_eur as number | null,
    points_delta: row.points_delta as number | null,
    decision: row.decision as string | null,
    reason: row.reason as string | null,
    rank,
  };
}

function alertMotive(row: ClauseAlertRow): string {
  const parts: string[] = [];
  if (row.lacks_replacements) parts.push("sin recambio en plantilla");
  if (row.lacks_liquidity) parts.push("sin liquidez");
  if (!parts.length) parts.push("rival en riesgo de clausulazo");
  return parts.join(" · ");
}

export function offerReasonLabel(reason: string | null | undefined): string | null {
  if (!reason) return null;
  const map: Record<string, string> = {
    entra_en_el_xi: "Entra en el XI optimizado",
    hay_un_delta_mejor: "Hay otro clausulazo con más puntos",
    no_entra_en_el_xi: "No mejora el once",
    ventana_cerrada: "Ventana cerrada",
    caja_insuficiente: "Caja insuficiente",
  };
  return map[reason] || reason.replace(/_/g, " ");
}

function playerLabel(row: { nickname?: string | null; name?: string | null }): string {
  return row.nickname || row.name || "jugador";
}

function buildRoadmap(
  phase: GuidePhase,
  protect: ProtectBrief[],
  top_pick: OfferBrief | null,
  window_open: boolean | null,
  locked_total: number,
): RoadmapStep[] {
  const urgentProtect = protect.filter((row) => row.urgent).length;
  const protegerStatus: RoadmapStepStatus =
    window_open === false
      ? urgentProtect > 0
        ? "blocked"
        : "done"
      : urgentProtect > 0
        ? "now"
        : protect.length > 0
          ? "next"
          : "done";

  const vigilarStatus: RoadmapStepStatus =
    window_open === false
      ? "na"
      : locked_total > 0
        ? phase === "oleada" || phase === "espera"
          ? "now"
          : "next"
        : "done";

  const elegirStatus: RoadmapStepStatus =
    window_open === false
      ? "na"
      : top_pick
        ? top_pick.decision === "PAGAR"
          ? "done"
          : "next"
        : locked_total > 0
          ? "next"
          : "blocked";

  const ejecutarStatus: RoadmapStepStatus =
    window_open === false
      ? "blocked"
      : top_pick?.decision === "PAGAR"
        ? "now"
        : top_pick
          ? "next"
          : locked_total === 0
            ? "blocked"
            : "next";

  return [
    {
      id: "proteger",
      order: 1,
      title: "Protege lo tuyo",
      subtitle: "Sube cláusula o vende antes del desbloqueo rival",
      status: protegerStatus,
    },
    {
      id: "vigilar",
      order: 2,
      title: "Vigila el calendario",
      subtitle: "Horas exactas (Europe/Madrid) de cada candado",
      status: vigilarStatus,
    },
    {
      id: "elegir",
      order: 3,
      title: "Elige el fichaje",
      subtitle: "Mejor delta de puntos sin dejar la caja en negativo",
      status: elegirStatus,
    },
    {
      id: "ejecutar",
      order: 4,
      title: "Ejecuta en la app",
      subtitle: "Clausular → confirmar explícitamente",
      status: ejecutarStatus,
    },
  ];
}

function buildChecklist(
  protect: ProtectBrief[],
  top_pick: OfferBrief | null,
  window_open: boolean | null,
  cash_eur: number | null | undefined,
  clause_actions: ClausePlanAction[],
): ChecklistItem[] {
  const items: ChecklistItem[] = [];
  const urgent = protect.filter((row) => row.urgent);
  for (const row of urgent.slice(0, 3)) {
    const subir = clause_actions.find(
      (action) => action.kind === "subir_clausula" && action.player_id === row.player_id && action.eligible,
    );
    items.push({
      id: `protect-${row.player_id}`,
      label: `Blindar a ${playerLabel(row)}`,
      detail: subir
        ? `Subir cláusula (~${subir.amount_eur?.toLocaleString("es-ES")} €) antes de que abra`
        : row.headline,
      done: false,
      priority: "critical",
    });
  }
  if (!urgent.length && protect.length) {
    items.push({
      id: "protect-ok",
      label: "Plantilla sin amenazas urgentes",
      detail: "Ningún rival con caja conocida cubre tus cláusulas desbloqueadas.",
      done: true,
      priority: "info",
    });
  }

  items.push({
    id: "window",
    label:
      window_open === false
        ? "Ventana de clausulazos cerrada"
        : window_open === true
          ? "Ventana abierta — puedes pagar cláusulas desbloqueadas"
          : "Sin hora de cierre (falta saque de jornada)",
    detail: "El mercado cierra 24 h antes del primer partido de la jornada.",
    done: window_open === true,
    priority: window_open === false ? "critical" : "normal",
  });

  if (top_pick) {
    const clause = top_pick.buyout_clause_eur;
    const canPay =
      typeof cash_eur === "number" && typeof clause === "number" ? cash_eur >= clause : false;
    items.push({
      id: "target",
      label: `Objetivo #1: ${playerLabel(top_pick)}`,
      detail:
        typeof clause === "number"
          ? `Cláusula ${clause.toLocaleString("es-ES")} € · caja después ${top_pick.cash_after_eur?.toLocaleString("es-ES") ?? "?"} €`
          : undefined,
      done: top_pick.decision === "PAGAR" && canPay,
      priority: "critical",
    });
  } else if (window_open !== false) {
    items.push({
      id: "target-none",
      label: "Sin clausulazo rentable ahora",
      detail: "Espera desbloqueos o revisa rivales con cláusula baja.",
      done: false,
      priority: "normal",
    });
  }

  const payAction = clause_actions.find((action) => action.kind === "clausular" && action.eligible);
  items.push({
    id: "confirm",
    label: payAction ? `Confirmar clausulazo de ${playerLabel(payAction)} en la app` : "Sin clausulazo pendiente de confirmar",
    detail: "La app exige un sí explícito; aquí solo se recomienda.",
    done: false,
    priority: payAction ? "critical" : "info",
  });

  items.push({
    id: "xi-caja",
    label: "Caja ≥ 0 y once de 11 al inicio de jornada",
    detail: "Si la caja queda negativa o faltan jugadores, la jornada puntúa 0 entera.",
    done:
      typeof top_pick?.cash_after_eur === "number"
        ? top_pick.cash_after_eur >= 0
        : typeof cash_eur === "number"
          ? cash_eur >= 0
          : false,
    priority: "critical",
  });

  const order = { critical: 0, normal: 1, info: 2 };
  items.sort((a, b) => order[a.priority] - order[b.priority] || Number(a.done) - Number(b.done));
  return items;
}

function buildReadiness(checklist: ChecklistItem[], window_open: boolean | null): Readiness {
  if (window_open === false) {
    return {
      score: 0,
      label: "Fuera de ventana",
      detail: "Usa mercado diario y alineación. Vuelve aquí antes del próximo cierre (24 h antes del saque).",
    };
  }
  const tracked = checklist.filter((item) => item.priority !== "info");
  const done = tracked.filter((item) => item.done).length;
  const score = tracked.length ? Math.round((done / tracked.length) * 100) : 50;
  const pendingCritical = checklist.filter((item) => item.priority === "critical" && !item.done);
  if (pendingCritical.length === 0 && score >= 80) {
    return {
      score: Math.max(score, 85),
      label: "Listo para actuar",
      detail: "Tienes objetivo, caja y ventana alineados. Solo falta ejecutar en la app si toca.",
    };
  }
  if (pendingCritical.some((item) => item.id.startsWith("protect"))) {
    return {
      score: Math.min(score, 45),
      label: "Protege antes de fichar",
      detail: "Hay rivales que pueden clausularte. Sube cláusula o vende antes de ir a por el rival.",
    };
  }
  return {
    score,
    label: score >= 60 ? "Casi preparado" : "Preparación incompleta",
    detail: pendingCritical[0]?.detail || pendingCritical[0]?.label || "Revisa la checklist y el calendario.",
  };
}

function buildPlaybook(
  phase: GuidePhase,
  window_open: boolean | null,
  peak_date: string | undefined,
  peak_count: number,
  top_pick: OfferBrief | null,
  next_unlock_label: string | null,
): string[] {
  if (window_open === false) {
    return [
      "Mercado de cláusulas cerrado hasta la próxima jornada.",
      "Prioriza mercado diario, snipes y alinear el once de 11.",
      "Antes del próximo saque, vuelve a esta guía: el cierre es 24 h antes.",
    ];
  }
  const lines: string[] = [
    "Las horas de desbloqueo vienen de la API (Europe/Madrid); la app oculta el minuto pero el JSON no.",
    "Subir cláusula cuesta la mitad del incremento (regla 1:2), redondeando al alza.",
  ];
  if (phase === "oleada" && peak_date) {
    lines.unshift(
      `Día clave: ${peak_count} desbloqueos. Ten la app lista y la caja libre ese día.`,
      "Antes de la oleada: sube cláusulas marcadas como urgentes.",
    );
  } else if (phase === "espera" && next_unlock_label) {
    lines.unshift(`Próximo candado: ${next_unlock_label}. No gastes la caja en pujas si reservas el clausulazo.`);
  }
  if (top_pick?.decision === "PAGAR") {
    lines.push(
      `Al abrir (o ya): clausular a ${playerLabel(top_pick)} por ${top_pick.buyout_clause_eur?.toLocaleString("es-ES") ?? "?"} €.`,
      "Tras confirmar, recalcula caja y comprueba que el once sigue siendo de 11 jugadores.",
    );
  }
  return lines;
}

function collectClauseActions(plan: PlanSlice | null): ClausePlanAction[] {
  const raw = plan?.actions || [];
  return raw.filter((action) => action.kind === "clausular" || action.kind === "subir_clausula");
}

function upcomingUnlocks(entries: UnlockEntry[], nowMs: number, limit = 5): UnlockEntry[] {
  return entries
    .filter((entry) => {
      if (entry.is_open) return false;
      const ms = parseAt(entry.at) ?? Date.parse(`${entry.local_date}T${entry.local_time}:00`);
      return !Number.isNaN(ms) && ms > nowMs;
    })
    .slice(0, limit);
}

export function buildClausulazosGuide(
  plan: PlanSlice | null,
  squads: SquadsPayload | null,
  needs: NeedsPayload | null,
  nowMs: number = Date.now(),
  board: ClauseBoardPayload | null = null,
): ClausulazosGuideModel {
  const entries = collectUnlocks(squads, board);
  const { timeline, peak_date, peak_count } = buildTimeline(entries);
  const locked_total = entries.filter((item) => !item.is_open).length;
  const open_total = entries.filter((item) => item.is_open).length;

  const closeAt = parseAt(plan?.clause_market_close?.at);
  const window_open = closeAt === null ? null : nowMs < closeAt;
  const window_close_label =
    plan?.clause_market_close?.local_date && plan?.clause_market_close?.local_time
      ? `${plan.clause_market_close.local_date} ${plan.clause_market_close.local_time}`
      : null;

  let next_unlock_at: string | null = null;
  let next_unlock_label: string | null = null;
  for (const entry of entries) {
    if (entry.is_open) continue;
    const ms = parseAt(entry.at) ?? Date.parse(`${entry.local_date}T${entry.local_time}:00`);
    if (Number.isNaN(ms) || ms <= nowMs) continue;
    next_unlock_at = entry.at || new Date(ms).toISOString();
    next_unlock_label = `${entry.local_date} ${entry.local_time} · ${entry.nickname || entry.name || "jugador"}`;
    break;
  }

  let phase: GuidePhase = "abierto";
  let phase_title = "Mercado de cláusulas abierto";
  let phase_detail = "Puedes pagar cláusulas desbloqueadas hasta el cierre (24 h antes del saque).";

  if (window_open === false) {
    phase = "cerrado";
    phase_title = "Ventana de clausulazos cerrada";
    phase_detail = "Ya pasó el cierre de 24 h antes de la jornada. Solo mercado diario y alineación.";
  } else if (locked_total > 0 && peak_date && peak_count >= 5) {
    const untilPeak = entries.filter((item) => !item.is_open && item.local_date === peak_date).length;
    if (untilPeak >= Math.max(3, Math.floor(peak_count * 0.5))) {
      phase = "oleada";
      phase_title = `Oleada el ${dateLabel(peak_date, peak_count, true).split(" · ")[0]}`;
      phase_detail = `${peak_count} desbloqueos ese día. Antes: sube tus cláusulas vulnerables y ten la caja lista.`;
    } else {
      phase = "espera";
      phase_title = "Aún hay candados";
      phase_detail = `${locked_total} jugador${locked_total === 1 ? "" : "es"} siguen bloqueados. La guía se actualiza sola al refrescar.`;
    }
  } else if (locked_total > 0) {
    phase = "espera";
    phase_title = "Esperando desbloqueos";
    phase_detail = next_unlock_label
      ? `Próximo: ${next_unlock_label}.`
      : "Revisa el calendario; las horas vienen de la API (Europe/Madrid).";
  }

  const protectRows = (plan?.protect || []).map((row) => protectBrief(row as Record<string, unknown>));
  protectRows.sort((a, b) => (b.threat_count || 0) - (a.threat_count || 0));

  const offersRaw = [...(plan?.clause_offers || [])] as Array<Record<string, unknown>>;
  offersRaw.sort((a, b) => {
    const da = typeof a.points_delta === "number" ? a.points_delta : 0;
    const db = typeof b.points_delta === "number" ? b.points_delta : 0;
    if (db !== da) return db - da;
    return String(a.player_id).localeCompare(String(b.player_id));
  });
  const offers = offersRaw.map((row, index) => offerBrief(row, index + 1));
  const top_pick = offers.find((row) => row.decision === "PAGAR") || offers[0] || null;

  const alertsRaw = (needs as NeedsPayload & { clause_alerts?: ClauseAlertRow[] })?.clause_alerts || [];
  const alerts: AlertBrief[] = alertsRaw
    .filter((row) => row.eligible || row.we_can_pay || row.already_open)
    .map((row) => ({
      player_id: row.player_id,
      name: row.name,
      nickname: row.nickname,
      position: row.position,
      manager_name: row.manager_name,
      buyout_clause_eur: row.buyout_clause_eur,
      local_date: row.alert_local_date || row.clause_lock?.local_date,
      local_time: row.alert_local_time || row.clause_lock?.local_time,
      already_open: row.already_open,
      we_can_pay: row.we_can_pay,
      eligible: row.eligible,
      lacks_replacements: row.lacks_replacements,
      lacks_liquidity: row.lacks_liquidity,
      motive: alertMotive(row),
    }))
    .sort((a, b) => {
      const openA = a.already_open ? 0 : 1;
      const openB = b.already_open ? 0 : 1;
      if (openA !== openB) return openA - openB;
      const da = `${a.local_date || ""}T${a.local_time || ""}`;
      const db = `${b.local_date || ""}T${b.local_time || ""}`;
      return da.localeCompare(db);
    });

  const clause_actions = collectClauseActions(plan);
  const checklist = buildChecklist(protectRows, top_pick, window_open, plan?.cash_eur, clause_actions);
  const readiness = buildReadiness(checklist, window_open);
  const roadmap = buildRoadmap(phase, protectRows, top_pick, window_open, locked_total);
  const playbook = buildPlaybook(phase, window_open, peak_date, peak_count, top_pick, next_unlock_label);
  const upcoming = upcomingUnlocks(entries, nowMs);

  return {
    phase,
    phase_title,
    phase_detail,
    cash_eur: plan?.cash_eur,
    window_close_label,
    window_close_at: plan?.clause_market_close?.at ?? null,
    window_open,
    next_unlock_at,
    next_unlock_label,
    peak_date,
    peak_count,
    locked_total,
    open_total,
    timeline,
    protect: protectRows,
    offers,
    alerts,
    top_pick,
    fetched_at: plan?.fetched_at,
    roadmap,
    checklist,
    readiness,
    playbook,
    clause_actions,
    upcoming_unlocks: upcoming,
  };
}

export function formatCountdown(targetMs: number | null, nowMs: number): string | null {
  if (targetMs === null || !Number.isFinite(targetMs)) return null;
  const diff = targetMs - nowMs;
  if (diff <= 0) return "ya debería estar abierto · refresca";
  const totalSec = Math.floor(diff / 1000);
  const days = Math.floor(totalSec / 86400);
  const hours = Math.floor((totalSec % 86400) / 3600);
  const mins = Math.floor((totalSec % 3600) / 60);
  const secs = totalSec % 60;
  if (days > 0) return `${days}d ${hours}h ${mins}m`;
  if (hours > 0) return `${hours}h ${mins}m ${secs}s`;
  return `${mins}m ${secs}s`;
}
