/**
 * Plan previo de clausulazos: qué hacer **antes** de que abra el primer candado.
 *
 * El motor de ``/api/plan`` solo propone clausulazos sobre jugadores **ya
 * desbloqueados** (``_pay_candidates`` exige ``is_locked === false``), así que
 * entre jornadas ``clause_offers`` va vacío y la guía se queda sin decir nada.
 * Este módulo cubre ese hueco con datos que sí están en la app:
 *
 * - ``/api/clause-board`` → todos los desbloqueos rivales con hora al segundo.
 * - ``/api/squads``       → tu plantilla, cláusulas y caja.
 * - ``/api/optimize``     → valor de jornada de cada jugador y tu once.
 *
 * No inventa cifras: cruza esas tres fuentes y ordena la jugada. La decisión de
 * pagar sigue siendo del usuario en la app oficial (aquí no se envía nada).
 */
import type {
  ClauseBoardPayload,
  ClauseLock,
  ClauseRow,
  OptimizePayload,
  PlanPayload,
  PlanProtectRow,
  Player,
  SquadsPayload,
} from "@/lib/types";
import { eur, multiple, playerName, points } from "@/lib/format";

export type RaidPhase = "cerrado" | "espera" | "oleada" | "abierto";

export type RaidStepStatus = "done" | "now" | "next" | "blocked";

export type RaidMove = {
  player_id: string | null;
  name: string | null;
  nickname: string | null;
  position: string | null;
  club: string | null;
  image_url: string | null;
  manager_name: string | null;
  /** Cláusula a pagar (lo que sale de tu caja). */
  clause_eur: number;
  /** Valor de mercado del jugador, si la lectura lo trae. */
  market_value_eur: number | null;
  multiple: number | null;
  /** Puntos que aporta al XI = EV del que entra − EV del que sale. */
  gain_pts: number | null;
  /** Valor de jornada del jugador rival, si la lectura lo trae. */
  ev: number | null;
  /** Quién sale del once para que entre (si su posición es la más débil). */
  replaces: Player | null;
  /** Sobreprecio frente al valor de mercado. */
  premium_eur: number | null;
  /** Caja restante si solo se hace esta compra (sin vender antes). */
  cash_after_entry_eur: number;
  /** Caja restante si se paga después de la venta previa. */
  cash_after_sale_eur: number | null;
  /** Momento exacto, tal y como lo publica la API (Europe/Madrid). */
  run_at: string | null;
  local_date: string | null;
  local_time: string | null;
  /** Etiqueta tipo ``14:08:16``. */
  second_label: string | null;
  /** Cuántos candados del rival abren en el mismo minuto. */
  rivals_watching: number | null;
  /** Minuto poco concurrido: más fácil llegar el primero. */
  preferred: boolean;
  blocked_reason: string | null;
  note: string | null;
};

export type RaidSell = {
  player_id: string | null;
  name: string | null;
  nickname: string | null;
  position: string | null;
  image_url: string | null;
  market_value_eur: number | null;
  clause_eur: number | null;
  /** ¿Entra en el once óptimo? Si no, es banquillo y no resta puntos. */
  in_xi: boolean;
  ev: number | null;
  /** Rivales con caja que cubren su cláusula. */
  rivals: number | null;
  richest: string | null;
  reason: string;
};

export type RaidExecution = {
  order: number;
  clock: string;
  title: string;
  detail: string;
  cash_after_eur: number | null;
  tone: "gold" | "mint" | "coral" | "muted";
  target?: { nickname: string | null; clause_eur: number; premium_eur: number | null } | null;
};

export type RaidStep = {
  id: string;
  order: number;
  title: string;
  subtitle: string;
  status: RaidStepStatus;
  detail: string;
};

export type RaidPlanModel = {
  phase: RaidPhase;
  phase_title: string;
  phase_detail: string;
  cash_eur: number;
  /** Reserva mínima de seguridad para no quedarse sin poder pujar. */
  reserve_eur: number;
  /** Caja disponible para clausulazos = caja − reserva. */
  budget_eur: number;
  lineup_ev: number | null;
  /** Puntos que aporta la mejor jugada. */
  best_gain_pts: number | null;
  /** El plan completo no cabe en caja sin dejar el once cojo. */
  needsBiggerSale: boolean;
  sell: RaidSell | null;
  moves: RaidMove[];
  /** Orden recomendado de desbloqueos (los que caben en caja). */
  best: RaidMove | null;
  roadmap: RaidStep[];
  executions: RaidExecution[];
  warnings: string[];
  next_unlock_at: string | null;
  window_close_at: string | null;
  fetched_at: string | null;
};

const RESERVE_MIN_EUR = 1_000_000;

function titularShare(value: number | null | undefined): number {
  if (typeof value !== "number" || Number.isNaN(value)) return 1;
  const share = value > 1 ? value / 100 : value;
  if (share <= 0 || share > 1) return 1;
  return share;
}

function jornadaEv(player: Player | null | undefined): number | null {
  if (!player) return null;
  if (typeof player.jornada_ev === "number" && !Number.isNaN(player.jornada_ev)) return player.jornada_ev;
  if (typeof player.expected_points !== "number" || Number.isNaN(player.expected_points)) return null;
  return player.expected_points * titularShare(player.p_titular);
}

function parseMs(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? null : ms;
}

function lockKey(lock: ClauseLock | null | undefined): string | null {
  if (!lock?.local_date || !lock?.local_time) return null;
  return `${lock.local_date} ${lock.local_time}`;
}

function secondLabel(lock: ClauseLock | null | undefined): string | null {
  if (!lock) return null;
  if (lock.local_clock) return lock.local_clock.length >= 8 ? lock.local_clock.slice(0, 8) : lock.local_clock;
  const ms = parseMs(lock.expires_at);
  if (ms === null) return lock.local_time || null;
  return new Intl.DateTimeFormat("es-ES", {
    timeZone: "Europe/Madrid",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(ms);
}

function compareClause(a: RaidMove, b: RaidMove): number {
  if ((a.gain_pts ?? -Infinity) !== (b.gain_pts ?? -Infinity)) return (b.gain_pts ?? -Infinity) - (a.gain_pts ?? -Infinity);
  if ((a.multiple ?? Infinity) !== (b.multiple ?? Infinity)) return (a.multiple ?? Infinity) - (b.multiple ?? Infinity);
  return a.clause_eur - b.clause_eur;
}

function clauseOrder(a: RaidMove, b: RaidMove): number {
  const da = a.local_date && a.local_time ? `${a.local_date} ${a.local_time}` : "";
  const db = b.local_date && b.local_time ? `${b.local_date} ${b.local_time}` : "";
  if (da !== db) return da.localeCompare(db);
  return a.clause_eur - b.clause_eur;
}

export type RaidInputs = {
  plan: PlanPayload | null;
  squads: SquadsPayload | null;
  board: ClauseBoardPayload | null;
  optimize: OptimizePayload | null;
  nowMs?: number;
};

export function buildRaidPlan({ plan, squads, board, optimize, nowMs = Date.now() }: RaidInputs): RaidPlanModel | null {
  if (!squads?.self) return null;
  const self = squads.self;
  const cash =
    typeof plan?.cash_eur === "number" ? plan.cash_eur : typeof self.cash_eur === "number" ? self.cash_eur : 0;
  const reserve = cash > 0 ? Math.min(RESERVE_MIN_EUR, cash) : 0;
  const budget = Math.max(0, cash - reserve);

  const xi = Array.isArray(optimize?.xi) ? optimize!.xi! : [];
  const xiIds = new Set(xi.map((row) => String(row.player_id)));
  const lineupEv = typeof optimize?.expected_points === "number" ? optimize.expected_points : null;

  // Posición más débil de mi once: a quién sustituiría un fichaje por puesto.
  const weakestByPosition = new Map<string, { player: Player; ev: number }>();
  for (const row of xi) {
    const ev = jornadaEv(row);
    if (ev === null || !row.position) continue;
    const current = weakestByPosition.get(row.position);
    if (!current || ev < current.ev) weakestByPosition.set(row.position, { player: row, ev });
  }

  // Mi plantilla por id: el tablero rival trae ``average_points`` de mercado,
  // pero los míos salen de ``/api/squads`` con su EV de jornada.
  const selfById = new Map<string, Player>();
  for (const player of self.players || []) {
    if (player.player_id !== undefined && player.player_id !== null) selfById.set(String(player.player_id), player);
  }

  // --- Tablero rival: solo desbloqueos futuros y no blindados ---------------
  const rows: ClauseRow[] = board?.ok !== false && board?.rows?.length ? board.rows : (squads.clauses || []);
  const upcoming = rows.filter((row) => {
    const lock = row.clause_lock;
    if (!lock?.present || lock.is_locked === false) return false;
    if (row.is_shielded) return false;
    const ms = parseMs(lock.expires_at) ?? parseMs(`${lock.local_date}T${lock.local_time}:00`);
    return ms !== null && ms > nowMs;
  });

  const windows = new Map<string, { rivals: number; rows: ClauseRow[] }>();
  for (const row of upcoming) {
    const key = lockKey(row.clause_lock);
    if (!key) continue;
    const current = windows.get(key);
    if (current) current.rivals += 1;
    else windows.set(key, { rivals: 1, rows: [row] });
  }
  const rarest = windows.size ? Math.min(...[...windows.values()].map((value) => value.rivals)) : null;
  const biggest = windows.size ? Math.max(...[...windows.values()].map((value) => value.rivals)) : 0;

  // --- Candidatos: todos, con o sin caja, para que se vea el precio real ---
  const moves: RaidMove[] = [];
  for (const row of upcoming) {
    const clause = typeof row.buyout_clause_eur === "number" ? row.buyout_clause_eur : null;
    if (clause === null || clause <= 0) continue;
    const marketValue = typeof row.market_value === "number" && row.market_value > 0 ? row.market_value : null;
    const weakest = row.position ? weakestByPosition.get(row.position) : undefined;
    const ev = typeof row.average_points === "number" && row.average_points > 0 ? row.average_points : null;
    const rivals = windows.get(lockKey(row.clause_lock) ?? "")?.rivals ?? null;
    const affordable = clause <= Math.max(0, cash - reserve);
    moves.push({
      player_id: row.player_id ? String(row.player_id) : null,
      name: row.name ?? null,
      nickname: row.nickname ?? null,
      position: row.position ?? null,
      club: row.club ?? null,
      image_url: row.image_url ?? null,
      manager_name: row.manager_name ?? null,
      clause_eur: clause,
      market_value_eur: marketValue,
      multiple: typeof row.clause_multiple === "number" ? row.clause_multiple : null,
      ev,
      gain_pts: ev !== null && weakest ? ev - weakest.ev : null,
      replaces: weakest?.player ?? null,
      premium_eur: marketValue !== null ? clause - marketValue : null,
      cash_after_entry_eur: cash - clause,
      cash_after_sale_eur: null,
      run_at: row.clause_lock?.expires_at ?? null,
      local_date: row.clause_lock?.local_date ?? null,
      local_time: row.clause_lock?.local_time ?? null,
      second_label: secondLabel(row.clause_lock),
      rivals_watching: rivals,
      preferred: affordable && rivals !== null && rarest !== null && rivals === rarest,
      blocked_reason: affordable ? null : `faltan ${eur(clause - (cash - reserve))} de caja libre`,
      note:
        marketValue !== null && clause <= marketValue
          ? "por debajo de su valor de mercado"
          : marketValue !== null && clause / marketValue < 1.4
            ? "múltiplo bajo frente a valor"
            : null,
    });
  }
  moves.sort(compareClause);

  // --- Venta previa ---------------------------------------------------------
  const protectRows: PlanProtectRow[] = Array.isArray(plan?.protect) ? plan!.protect! : [];
  const protectById = new Map<string, PlanProtectRow>();
  for (const row of protectRows) if (row.player_id) protectById.set(String(row.player_id), row);

  const sellable: RaidSell[] = [];
  for (const player of self.players || []) {
    const id = String(player.player_id);
    if (xiIds.has(id)) continue; // el once no se toca: vender ahí resta puntos
    const protect = protectById.get(id);
    sellable.push({
      player_id: id,
      name: player.name ?? null,
      nickname: player.nickname ?? null,
      position: player.position ?? null,
      image_url: player.image_url ?? null,
      market_value_eur: typeof player.market_value === "number" ? player.market_value : null,
      clause_eur: typeof player.buyout_clause === "number" ? player.buyout_clause : null,
      in_xi: false,
      ev: jornadaEv(player),
      rivals: typeof protect?.threat_count === "number" ? protect.threat_count : null,
      richest: protect?.top_rival?.manager_name ?? null,
      reason: "Banquillo: no puntúa esta jornada y libera caja sin tocar el once.",
    });
  }
  sellable.sort((a, b) => {
    const ma = a.market_value_eur ?? 0;
    const mb = b.market_value_eur ?? 0;
    if (mb !== ma) return mb - ma;
    return (b.rivals ?? 0) - (a.rivals ?? 0);
  });
  const sell = sellable[0] ?? null;
  const sellValue = sell?.market_value_eur ?? 0;
  const cashAfterSale = cash + sellValue;

  // Caja en cada paso presupuestario: ahora y después de la venta.
  for (const move of moves) {
    move.cash_after_sale_eur = cashAfterSale - move.clause_eur;
  }
  const affordable = moves
    .filter((move) => move.cash_after_sale_eur !== null && move.cash_after_sale_eur >= 0)
    .sort(compareClause);

  // Si lo mejor está fuera de alcance, el plan honesto es vender a alguien del
  // once: se calcula qué caja da esa venta para marcar el objetivo.
  const topByPoints = moves
    .filter((move) => move.gain_pts !== null)
    .sort((a, b) => (b.gain_pts ?? 0) - (a.gain_pts ?? 0))[0];
  const outOfReach = affordable.length === 0 && topByPoints?.gain_pts !== null;
  const xiSellable = [...xi]
    .filter((row) => typeof row.market_value === "number" && (row.market_value ?? 0) > 0)
    .sort((a, b) => (a.market_value ?? 0) - (b.market_value ?? 0))[0];
  const xiSell = xiSellable
    ? {
        player_id: xiSellable.player_id ? String(xiSellable.player_id) : null,
        name: xiSellable.name ?? null,
        nickname: xiSellable.nickname ?? null,
        position: xiSellable.position ?? null,
        image_url: xiSellable.image_url ?? null,
        market_value_eur: typeof xiSellable.market_value === "number" ? xiSellable.market_value : null,
        clause_eur: null,
        in_xi: true,
        ev: jornadaEv(xiSellable),
        rivals: null,
        richest: null,
        reason: "Está en el once: venderlo deja hueco que hay que rellenar con el fichaje.",
      }
    : null;
  const best = affordable[0] ?? null;

  // --- Fase ----------------------------------------------------------------
  const closeAt = plan?.clause_market_close?.at ?? null;
  const closeMs = parseMs(closeAt);
  const unlockMs = upcoming
    .map((row) => parseMs(row.clause_lock?.expires_at) ?? parseMs(`${row.clause_lock?.local_date}T${row.clause_lock?.local_time}:00`))
    .filter((ms): ms is number => ms !== null);
  const nextUnlockMs = unlockMs.length ? Math.min(...unlockMs) : null;
  const nextUnlockAt = nextUnlockMs !== null ? new Date(nextUnlockMs).toISOString() : null;

  let phase: RaidPhase = upcoming.length ? (biggest >= 3 ? "oleada" : "espera") : "abierto";
  if (closeMs !== null && nowMs >= closeMs) phase = "cerrado";

  const phaseTitle =
    phase === "cerrado"
      ? "Ventana cerrada: deja la jugada montada"
      : phase === "oleada"
        ? `Oleada con ${biggest} candados en el mismo minuto`
        : phase === "espera"
          ? "Todo bloqueado: plan antes de que abran"
          : "Hay candados abiertos ahora";

  const phaseDetail =
    phase === "cerrado"
      ? "El mercado de cláusulas cerró 24 h antes del saque. Ahora toca vender y tener la caja lista para la siguiente ventana."
      : nextUnlockMs !== null
        ? "Las horas son las que publica la API, con segundos: ese es el momento exacto al que hay que llegar."
        : "Sin candados futuros en esta lectura.";

  // --- Roadmap -------------------------------------------------------------
  const roadmap: RaidStep[] = [
    {
      id: "vender",
      order: 1,
      title: sell ? `Vende a ${playerName(sell)}` : "Sin venta necesaria",
      subtitle: sell
        ? `${eur(sell.market_value_eur)} al mercado · banquillo, no resta puntos`
        : "Tu caja ya cubre la mejor jugada",
      status: sell ? (phase === "cerrado" ? "next" : "now") : "done",
      detail: sell
        ? `Su valor son ${eur(sell.market_value_eur)} y no entra en el once óptimo. Venderlo lleva la caja a ${eur(cash + sellValue)}.`
        : "Ningún suplente con valor relevante: tu caja disponible es la actual.",
    },
    {
      id: "vigilar",
      order: 2,
      title: best ? `Vigila a ${playerName(best)}` : "Vigila el tablero",
      subtitle: best
        ? `Candado ${best.local_date ?? "s/d"} · ${best.second_label ?? best.local_time ?? "s/d"}`
        : "Sin candidato que quepa en caja",
      status: best ? "next" : "blocked",
      detail: best
        ? `Cláusula ${eur(best.clause_eur)}${best.multiple !== null ? ` · ${multiple(best.multiple)}` : ""} frente a un valor de mercado de ${eur(best.market_value_eur)}. Si el rival la sube antes del desbloqueo, el precio cambia: vuelve a leer el tablero la víspera.`
        : "Ningún desbloqueo futuro cabe en tu caja ni siquiera después de la venta previa.",
    },
    {
      id: "ejecutar",
      order: 3,
      title: best ? `Paga a ${playerName(best)}` : "Sin clausulazo viable",
      subtitle: best
        ? `${best.second_label ?? best.local_time ?? "al abrir"} en punto, desde la app oficial`
        : "Solo mercado diario",
      status: best ? (best.preferred ? "now" : "next") : "blocked",
      detail: best
        ? `Caja después ${eur(best.cash_after_sale_eur)}${best.gain_pts !== null ? ` · +${points(best.gain_pts)} pts de jornada al XI` : ""}${best.note ? ` · ${best.note}` : ""}.`
        : "Nada rentable con la caja actual: sube cláusulas propias y espera mejores precios.",
    },
    {
      id: "seguro",
      order: 4,
      title: "Comprueba la red line",
      subtitle: "Caja ≥ 0 y once de 11 antes del saque",
      status: "next",
      detail: "Después de pagar, revisa que la caja no queda negativa y que el once guardado junta 11 jugadores. Si falla, la jornada puntúa 0.",
    },
  ];

  // --- Guion del día clave --------------------------------------------------
  // Cada jugada se presupuesta **por separado**: son alternativas, no una
  // cadena. Sumarlas daría una caja irreal (−9 M€) que no se va a gastar.
  const executions: RaidExecution[] = [];
  let order = 1;
  if (sell && typeof sell.market_value_eur === "number") {
    executions.push({
      order: order++,
      clock: "Antes del día clave",
      title: `Vender ${playerName(sell)} en el mercado`,
      detail: `${eur(sell.market_value_eur)} al mercado diario. Si lo pones el mismo día, deja precio para que salga antes del minuto del candado.`,
      cash_after_eur: cashAfterSale,
      tone: "muted",
      target: null,
    });
  }
  const script = [
    ...affordable.filter((move) => move.player_id === best?.player_id),
    ...affordable.filter((move) => move.player_id !== best?.player_id).slice(0, 3),
  ].sort(clauseOrder);
  for (const move of script) {
    const after: number | null = cashAfterSale - move.clause_eur;
    executions.push({
      order: order++,
      clock: `${move.local_date ?? "s/d"} · ${move.second_label ?? move.local_time ?? "s/d"}`,
      title: `Clausular a ${playerName(move)}`,
      detail:
        move.player_id !== null && best?.player_id === move.player_id
          ? `Jugada principal. Caja después: ${eur(after)} (ya contada la venta).`
          : `Alternativa. Caja después: ${eur(after)} (ya contada la venta).`,
      cash_after_eur: after,
      tone: best?.player_id === move.player_id ? "gold" : "mint",
      target: { nickname: move.nickname, clause_eur: move.clause_eur, premium_eur: move.premium_eur },
    });
  }
  if (!executions.length && outOfReach && topByPoints) {
    const target = topByPoints;
    const cashNeeded = cashAfterSale - target.clause_eur;
    executions.push({
      order: order++,
      clock: `Objetivo: ${target.local_date ?? "s/d"} · ${target.second_label ?? target.local_time ?? "s/d"}`,
      title: `Llegar a ${playerName(target)}`,
      detail: xiSell
        ? `${playerName(target)} aporta +${points(target.gain_pts)} pts de jornada, pero su cláusula son ${eur(target.clause_eur)}. Falta caja: ${xiSell.market_value_eur !== null ? `vendiendo a ${playerName(xiSell)} (${eur(xiSell.market_value_eur)}, está en el once) ` : ""}la caja quedaría en ${eur(cashNeeded)}. Sacar a alguien del once resta puntos: solo vale si el que entra los compensa.`
        : `${playerName(target)} son ${eur(target.clause_eur)} y no hay caja para llegar.`,
      cash_after_eur: cashNeeded,
      tone: "coral",
      target: { nickname: target.nickname, clause_eur: target.clause_eur, premium_eur: target.premium_eur },
    });
  }
  if (!executions.length) {
    executions.push({
      order: 1,
      clock: "Sin acción",
      title: "Ningún clausulazo cabe en caja",
      detail: "Libera caja con ventas o espera a que los rivales bajen cláusulas.",
      cash_after_eur: cash,
      tone: "coral",
      target: null,
    });
  }

  // --- Avisos ---------------------------------------------------------------
  const warnings: string[] = [];
  if (best && best.cash_after_entry_eur < 0 && !sell) {
    warnings.push("La compra deja la caja en negativo: vende algo antes o la jornada puntúa 0.");
  }
  // Solo los precios de las jugadas que de verdad entran en el guion.
    for (const move of affordable.slice(0, 3)) {    if (move.premium_eur !== null && move.premium_eur > 0) {
      warnings.push(`${playerName(move)} se paga ${eur(move.premium_eur)} por encima de su valor de mercado.`);
    }
  }
  const blockedPremium = moves
    .filter((move) => move.blocked_reason !== null && (move.gain_pts ?? 0) > (best?.gain_pts ?? 0))
    .slice(0, 1);
  for (const move of blockedPremium) {
    warnings.push(`Mejor jugador sobre el papel: ${playerName(move)} (+${points(move.gain_pts)} pts de jornada), pero sus ${eur(move.clause_eur)} no caben ni vendiendo.`);
  }
  if (sell?.rivals !== null && sell && (sell.rivals ?? 0) > 0) {
    warnings.push(`${playerName(sell)} tiene ${sell.rivals} rival(es) que cubren su cláusula: si tardas, puede volar antes de que lo vendas.`);
  }

  return {
    phase,
    phase_title: phaseTitle,
    phase_detail: phaseDetail,
    cash_eur: cash,
    reserve_eur: reserve,
    budget_eur: budget,
    lineup_ev: lineupEv,
    best_gain_pts: best?.gain_pts ?? null,
    needsBiggerSale: outOfReach,
    sell,
    moves: moves.slice(0, 12),
    best,
    roadmap,
    executions,
    warnings,
    next_unlock_at: nextUnlockAt,
    window_close_at: closeAt,
    fetched_at: plan?.fetched_at ?? null,
  };
}
