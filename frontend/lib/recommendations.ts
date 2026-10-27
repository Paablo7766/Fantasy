import { eurShort, jornadaEv, points } from "@/lib/format";
import type {
  Gap,
  MarketDecision,
  OptimizePayload,
  PlanAction,
  PlanClockEvent,
  PlanPayload,
  PlanPlayer,
  Player,
  SquadsPayload,
  TrendsPayload,
} from "@/lib/types";

/**
 * Pizarra de recomendaciones de Hoy.
 *
 * Cada frase sale de una cifra del plan, del mercado o del once. Si el dato no
 * está, la línea no se escribe: no se rellena con un ejemplo.
 */

const WEEKDAYS = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"] as const;

const POSITION_ONE: Record<string, string> = {
  POR: "portero",
  DEF: "defensa",
  MC: "medio",
  DEL: "delantero",
};

export type RecLane = "hoy" | "espera";

export type RecTone = "search" | "bid" | "sell-later" | "sell-now" | "clause" | "offer" | "watch";

export type RecCard = {
  id: string;
  lane: RecLane;
  tone: RecTone;
  title: string;
  detail: string;
  timing: string | null;
  fallback: string | null;
  amount: string | null;
  playerName: string | null;
  imageUrl: string | null;
  /** Silueta: todavía no hay un nombre al que fichar hoy. */
  mystery: boolean;
  badge: string | null;
  explain: string | null;
};

export type WindowCard = {
  id: string;
  name: string;
  imageUrl: string | null;
  position: string | null;
  amount: string | null;
  gain: string | null;
  manager: string | null;
  note: string | null;
  when: string;
  reach: "llega" | "falta" | "sin-caja" | null;
  shortfall: string | null;
};

export type RecommendationBoard = {
  status: string;
  narrative: string;
  impactTitle: string | null;
  pointsDelta: number | null;
  valueDelta: number | null;
  savedPoints: number | null;
  recommendedPoints: number | null;
  hoy: RecCard[];
  espera: RecCard[];
  offers: RecCard[];
  watches: RecCard[];
  windows: WindowCard[];
};

export type RecommendationInput = {
  plan: PlanPayload | null;
  optimize: OptimizePayload | null;
  trends: TrendsPayload | null;
  squads: SquadsPayload | null;
};

type Decision = MarketDecision & {
  bid_plan?: {
    how?: string | null;
    recommended_bid_eur?: number | null;
    reason?: string | null;
  } | null;
  snipe?: { fire_local_date?: string | null; fire_local_time?: string | null } | null;
};

type Indexed = Player & { player_id: string };

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function nameOf(row: { nickname?: string | null; name?: string | null } | null | undefined): string | null {
  return text(row?.nickname) || text(row?.name);
}

function posKey(value: unknown): string {
  return String(value || "").toUpperCase();
}

function positionWord(position: string | null | undefined): string {
  const key = posKey(position);
  return POSITION_ONE[key] || (key ? key.toLowerCase() : "jugador");
}

function joinOr(items: string[]): string {
  const unique = items.filter((item, index) => item && items.indexOf(item) === index);
  if (unique.length === 0) return "";
  if (unique.length === 1) return unique[0];
  return `${unique.slice(0, -1).join(", ")} o ${unique[unique.length - 1]}`;
}

/** Fecha de calendario (YYYY-MM-DD) a «vie 30/10», sin depender del reloj. */
export function weekdayStamp(date: string | null | undefined, time?: string | null): string | null {
  if (!date) return null;
  const [year, month, day] = date.split("-").map(Number);
  if (!year || !month || !day) return null;
  const weekday = WEEKDAYS[new Date(Date.UTC(year, month - 1, day)).getUTCDay()];
  const stamp = `${weekday} ${day}/${String(month).padStart(2, "0")}`;
  const clock = text(time)?.slice(0, 5);
  return clock ? `${stamp} a las ${clock}` : stamp;
}

/** 11,19M · 90,40M. Por debajo del millón se deja el formato corto en euros. */
export function boardMoney(value: number | null | undefined): string | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  const abs = Math.abs(value);
  if (abs >= 1_000_000) {
    return `${(value / 1_000_000).toLocaleString("es-ES", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}M`;
  }
  return eurShort(value);
}

function moneyBand(values: number[]): string | null {
  const millions = values.filter((value) => value > 0).map((value) => value / 1_000_000);
  if (millions.length === 0) return null;
  const low = Math.round(Math.min(...millions));
  const high = Math.round(Math.max(...millions));
  if (low <= 0 && high <= 0) return null;
  if (low === high) return boardMoney(Math.round(millions[0] * 1_000_000));
  return `${low}-${high}M`;
}

function signedPts(value: number | null): string | null {
  if (value === null || Math.abs(value) < 0.05) return null;
  const body = points(Math.abs(value));
  return `${value > 0 ? "+" : "−"}${body}`;
}

function rising(player: Player | null | undefined): boolean {
  if (!player) return false;
  const delta =
    num(player.measured_price_delta) ?? num(player.price_delta) ?? num(player.own_predicted_delta);
  return delta !== null && delta > 0;
}

function verbOf(row: Decision): string {
  return String(row.action || row.decision || "").toUpperCase();
}

function bidAmount(row: Decision, action: PlanAction | undefined): number | null {
  return (
    num(action?.amount_eur) ??
    num(row.bid_plan?.recommended_bid_eur) ??
    num(row.suggested_bid) ??
    num(row.bid_eur) ??
    num(row.sale_price)
  );
}

function playerPoints(row: Player | PlanPlayer | null | undefined): number | null {
  if (!row) return null;
  return jornadaEv(row as Player) ?? num((row as Player).jornada_ev) ?? num(row.expected_points);
}

function indexPlayers(input: RecommendationInput, decisions: Decision[]): Map<string, Indexed> {
  const map = new Map<string, Indexed>();
  const buckets: Array<Array<Player | null | undefined> | null | undefined> = [
    input.optimize?.xi,
    input.optimize?.benched,
    input.optimize?.excluded,
    input.optimize?.saved_lineup?.xi,
    input.squads?.self?.players as Player[] | undefined,
    input.squads?.sell as Player[] | undefined,
    decisions,
  ];
  for (const gap of input.optimize?.gaps || []) buckets.push(gap.options);
  for (const gap of input.optimize?.market_fills || []) buckets.push(gap.options);
  for (const gap of input.plan?.lineup?.gaps || []) buckets.push(gap.options);
  for (const bucket of buckets) {
    for (const row of bucket || []) {
      const id = text(row?.player_id);
      if (!id || !row) continue;
      const prev = map.get(id);
      map.set(id, { ...(prev || {}), ...row, player_id: id });
    }
  }
  return map;
}

function decisionsOf(input: RecommendationInput): Decision[] {
  const fromPlan = Array.isArray(input.plan?.decisions) ? input.plan.decisions : [];
  const fromTrends = Array.isArray(input.trends?.market_decisions) ? input.trends.market_decisions : [];
  const rows = (fromPlan.length ? fromPlan : fromTrends) as Decision[];
  return rows.filter((row) => text(row.player_id));
}

function gapsOf(input: RecommendationInput): Gap[] {
  const lined = input.plan?.lineup?.gaps;
  if (Array.isArray(lined) && lined.length) return lined;
  const fills = input.optimize?.market_fills;
  if (Array.isArray(fills) && fills.length) return fills;
  return Array.isArray(input.optimize?.gaps) ? input.optimize.gaps : [];
}

function closeStamp(plan: PlanPayload | null): string | null {
  const close = plan?.clause_market_close;
  return weekdayStamp(close?.local_date, close?.local_time) || weekdayFromIso(plan?.kickoff);
}

function weekdayFromIso(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const parsed = Date.parse(iso);
  if (Number.isNaN(parsed)) return null;
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Madrid",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(parsed));
  const pick = (type: string) => parts.find((part) => part.type === type)?.value;
  const date = `${pick("year")}-${pick("month")}-${pick("day")}`;
  return weekdayStamp(date, pick("minute") ? `${pick("hour")}:${pick("minute")}` : null);
}

function clockByPlayer(clock: PlanClockEvent[]): Map<string, PlanClockEvent> {
  const map = new Map<string, PlanClockEvent>();
  for (const event of clock) {
    if (event.kind !== "desbloqueo" || event.is_self) continue;
    const id = text(event.player_id);
    if (!id || map.has(id)) continue;
    map.set(id, event);
  }
  return map;
}

function actionByPlayer(actions: PlanAction[]): Map<string, PlanAction> {
  const map = new Map<string, PlanAction>();
  for (const action of actions) {
    const id = text(action.player_id);
    if (!id || map.has(id)) continue;
    map.set(id, action);
  }
  return map;
}

export function buildRecommendations(input: RecommendationInput): RecommendationBoard {
  const plan = input.plan;
  const actions = (Array.isArray(plan?.actions) ? plan.actions : []).filter((row) => row && row.kind);
  const decisions = decisionsOf(input);
  const known = indexPlayers(input, decisions);
  const byAction = actionByPlayer(actions);
  const clock = Array.isArray(plan?.clock) ? plan.clock : [];
  const unlocks = clockByPlayer(clock);
  const cash = num(plan?.cash_eur) ?? num(input.squads?.self?.cash_eur);
  const savedIds = new Set(
    (input.optimize?.saved_lineup?.xi || plan?.lineup?.xi || [])
      .map((row) => text(row.player_id))
      .filter((id): id is string => Boolean(id)),
  );
  const recommendedIds = new Set(
    (plan?.lineup?.xi || input.optimize?.xi || [])
      .map((row) => text(row.player_id))
      .filter((id): id is string => Boolean(id)),
  );
  const inXi = (id: string | null) => Boolean(id && (savedIds.has(id) || recommendedIds.has(id)));

  const immediateIds = new Set(
    actions
      .filter((action) => action.kind === "pujar" && action.when !== "snipe" && action.eligible !== false)
      .map((action) => text(action.player_id))
      .filter((id): id is string => Boolean(id)),
  );

  const hoy: RecCard[] = [];
  const espera: RecCard[] = [];
  const seen = new Set<string>();

  const push = (card: RecCard) => {
    if (seen.has(card.id)) return;
    seen.add(card.id);
    (card.lane === "hoy" ? hoy : espera).push(card);
  };

  for (const action of actions) {
    if (action.kind !== "pujar" && action.kind !== "clausular" && action.kind !== "subir_clausula") continue;
    const id = text(action.player_id);
    const player = id ? known.get(id) : undefined;
    const label = nameOf(action) || nameOf(player) || "el jugador";
    const amount = num(action.amount_eur);
    const decision = id ? decisions.find((row) => row.player_id === id) : undefined;
    const replaced = nameOf(decision?.replaces);
    const gain = signedPts(num(action.points_delta) ?? num(decision?.points_delta));
    const later = action.when === "snipe";
    const blocked = action.eligible === false;
    if (action.kind === "pujar") {
      push({
        id: `bid-${id || label}`,
        lane: later ? "espera" : "hoy",
        tone: "bid",
        title: later ? `Programa la puja por ${label}` : `Puja por ${label}`,
        detail: [
          replaced ? `Sustituye a ${replaced}` : null,
          gain ? `${gain} pts por jornada en tu once` : null,
          blocked ? "Ahora mismo no entra: falta caja o ventana." : null,
        ]
          .filter(Boolean)
          .join(" · ") || text(action.detail) || "Mejora el once si entra al precio del plan.",
        timing: later
          ? action.when_local_time
            ? `se abre a las ${action.when_local_time}`
            : "se abre en el cierre"
          : "puja hoy: si esperas, puede salir del mercado",
        fallback: null,
        amount: boardMoney(amount),
        playerName: label,
        imageUrl: text(action.image_url) || text(player?.image_url),
        mystery: false,
        badge: null,
        explain: null,
      });
      continue;
    }
    push({
      id: `${action.kind}-${id || label}`,
      lane: "hoy",
      tone: "clause",
      title:
        action.kind === "clausular"
          ? `Paga la cláusula de ${label}`
          : `Sube la cláusula de ${label}`,
      detail: text(action.detail) || (blocked ? "No se puede ejecutar con la caja de hoy." : "Hay que confirmarlo antes de enviarlo."),
      timing: text(action.when_local_time) ? `a las ${action.when_local_time}` : "ahora",
      fallback: null,
      amount: boardMoney(amount ?? num(action.target_clause_eur)),
      playerName: label,
      imageUrl: text(action.image_url) || text(player?.image_url),
      mystery: false,
      badge: null,
      explain: null,
    });
  }

  const searchPositions = new Set<string>();
  const grouped = new Map<string, Decision[]>();
  for (const row of decisions) {
    const verb = verbOf(row);
    if (verb !== "ESPERAR" && verb !== "PUJAR") continue;
    if (row.is_vetoed) continue;
    const id = text(row.player_id);
    if (id && immediateIds.has(id)) continue;
    const delta = num(row.points_delta);
    const useful = (delta !== null && delta > 0.05) || Boolean(row.replaces);
    if (!useful) continue;
    const key = posKey(row.position) || "OTRO";
    const bucket = grouped.get(key) || [];
    bucket.push(row);
    grouped.set(key, bucket);
  }
  for (const gap of gapsOf(input)) {
    const key = posKey(gap.position);
    if (!key || (num(gap.missing) ?? 0) <= 0) continue;
    if (!grouped.has(key)) grouped.set(key, []);
  }

  const immediatePositions = new Set(
    actions
      .filter((action) => action.kind === "pujar" && action.when !== "snipe" && action.eligible !== false)
      .map((action) => posKey(action.position) || posKey(known.get(text(action.player_id) || "")?.position))
      .filter(Boolean),
  );
  const until = closeStamp(plan);
  for (const [position, rows] of grouped) {
    const ranked = [...rows].sort((a, b) => (num(b.points_delta) ?? num(b.jornada_ev) ?? 0) - (num(a.points_delta) ?? num(a.jornada_ev) ?? 0));
    if (ranked.length === 0 && immediatePositions.has(position)) continue;
    const best = ranked[0];
    const targetPts = best ? playerPoints(best) : null;
    const gain = best ? num(best.points_delta) : null;
    const word = positionWord(position);
    const prices = ranked
      .map((row) => num(row.sale_price) ?? num(row.market_value) ?? bidAmount(row, byAction.get(text(row.player_id) || "")))
      .filter((value): value is number => value !== null && value > 0);
    const fallback = fallbackLine(ranked, unlocks, cash, known);
    const open = ranked
      .map((row) => {
        const event = unlocks.get(text(row.player_id) || "");
        return event ? weekdayStamp(event.local_date, event.local_time || event.local_clock) : null;
      })
      .find((value): value is string => Boolean(value));
    searchPositions.add(position);
    push({
      id: `search-${position}`,
      lane: "espera",
      tone: "search",
      title: targetPts !== null ? `Buscamos un ${word} de ≈${points(targetPts)} pts` : `Buscamos un ${word}`,
      detail: signedPts(gain) ? `${signedPts(gain)} pts por jornada en tu once` : "Todavía no hay un nombre que mejore el once con una cifra.",
      timing: open && ranked.length === 1 ? `se abre el ${open}` : until ? `lo buscamos cada día hasta el ${until}` : "lo buscamos mientras siga en el mercado",
      fallback,
      amount: moneyBand(prices),
      playerName: null,
      imageUrl: null,
      mystery: true,
      badge: null,
      explain: null,
    });
  }

  const outgoing = collectOutgoing(input, decisions, actions, known, recommendedIds);
  const bidNames = hoy.filter((card) => card.tone === "bid").map((card) => card.playerName).filter((value): value is string => Boolean(value));
  const searchWords = [...searchPositions].map((position) => `el ${positionWord(position)}`);
  for (const row of outgoing) {
    const id = row.player.player_id;
    const label = nameOf(row.player) || "el jugador";
    const plays = savedIds.has(id) || (recommendedIds.has(id) && !row.leaves);
    const waitsForSearch = plays && searchWords.length > 0 && !row.forcedNow;
    const later = waitsForSearch || (rising(row.player) && !row.forcedNow);
    const pts = playerPoints(row.player);
    const compared = row.replacedBy ? `menos que ${row.replacedBy}` : null;
    const funds = !plays && bidNames.length ? `su dinero paga a ${joinOr(bidNames)}` : null;
    const risingNote = rising(row.player);
    const detail = plays
      ? [`Aporta ${pts !== null ? points(pts) : "s/d"} pts`, compared, risingNote ? "mientras, sigue subiendo" : null]
          .filter(Boolean)
          .join(", ")
          .replace(", mientras", " · mientras")
      : [
          row.leaves ? "Con los fichajes deja de ser titular" : "No juega en tu once",
          funds,
          risingNote ? "sigue subiendo" : null,
        ]
          .filter(Boolean)
          .join(" · ");
    const deadline = until ? `véndelo antes del ${until}` : "véndelo antes del cierre";
    push({
      id: `sell-${id}`,
      lane: later ? "espera" : "hoy",
      tone: later ? "sell-later" : "sell-now",
      title: later ? `Vende más adelante a ${label}` : `Pon en venta a ${label}`,
      detail,
      timing: waitsForSearch
        ? `cuando aparezca ${joinOr(searchWords)}`
        : risingNote
          ? `${deadline} · sigue subiendo`
          : deadline,
      fallback: null,
      amount: boardMoney(num(row.player.market_value) ?? num(row.player.sale_price)),
      playerName: label,
      imageUrl: text(row.player.image_url),
      mystery: false,
      badge: null,
      explain: null,
    });
  }

  const lineupDelta = num(plan?.lineup?.points_delta);
  if (lineupDelta !== null && lineupDelta > 0.05 && hoy.length === 0 && espera.length === 0) {
    push({
      id: "lineup",
      lane: "hoy",
      tone: "bid",
      title: "Alinea el once recomendado",
      detail: `${signedPts(lineupDelta)} pts si guardas el once del motor.`,
      timing: "antes del inicio de jornada",
      fallback: null,
      amount: "Gratis",
      playerName: null,
      imageUrl: null,
      mystery: false,
      badge: null,
      explain: null,
    });
  }

  const offers = offerCards(decisions, known, inXi, text(input.squads?.self?.team_id));
  const watches = watchCards(plan, known);
  const windows = windowCards(clock, decisions, known, cash, searchPositions);

  const pointsDelta = lineupDelta;
  const valueDelta = valueGap(hoy, espera, known, decisions);
  const savedPoints = num(plan?.lineup?.saved_points);
  const recommendedPoints = num(plan?.lineup?.expected_points);
  const narrative = writeNarrative(hoy, espera, pointsDelta);
  const status = writeStatus(hoy, espera);
  const impactTitle = impactCopy(pointsDelta);

  return {
    status,
    narrative,
    impactTitle,
    pointsDelta,
    valueDelta,
    savedPoints,
    recommendedPoints,
    hoy: hoy.slice(0, 6),
    espera: espera.slice(0, 8),
    offers,
    watches,
    windows,
  };
}

function fallbackLine(
  rows: Decision[],
  unlocks: Map<string, PlanClockEvent>,
  cash: number | null,
  known: Map<string, Indexed>,
): string | null {
  const options = rows
    .map((row) => {
      const id = text(row.player_id) || "";
      const event = unlocks.get(id);
      const player = known.get(id) || row;
      const clause = num(player.buyout_clause) ?? num(event?.amount_eur);
      if (!event || clause === null) return null;
      return { row, event, clause, points: playerPoints(player) ?? 0 };
    })
    .filter((row): row is NonNullable<typeof row> => Boolean(row))
    .sort((a, b) => b.points - a.points);
  const pick = options[0];
  if (!pick) return null;
  const when = weekdayStamp(pick.event.local_date, pick.event.local_time || pick.event.local_clock);
  const label = nameOf(pick.row) || "el jugador";
  const money = boardMoney(pick.clause);
  const reach = cash === null ? null : cash >= pick.clause ? "te llega" : "no te llega";
  return ["Si no aparece:", label, when ? `cláusula el ${when}` : "cláusula", money, reach].filter(Boolean).join(" · ");
}

type LoosePlayer = {
  player_id?: string | null;
  name?: string | null;
  nickname?: string | null;
  image_url?: string | null;
  market_value?: number | null;
  sale_price?: number | null;
  position?: string | null;
  expected_points?: number | null;
  jornada_ev?: number | null;
  measured_price_delta?: number | null;
  price_delta?: number | null;
  own_predicted_delta?: number | null;
};

type Outgoing = {
  player: Indexed;
  replacedBy: string | null;
  leaves: boolean;
  forcedNow: boolean;
};

function collectOutgoing(
  input: RecommendationInput,
  decisions: Decision[],
  actions: PlanAction[],
  known: Map<string, Indexed>,
  recommendedIds: Set<string>,
): Outgoing[] {
  const rows = new Map<string, Outgoing>();
  const put = (
    id: string | null,
    patch: { player?: LoosePlayer | null; replacedBy?: string | null; leaves?: boolean; forcedNow?: boolean },
  ) => {
    if (!id) return;
    const player = known.get(id) || (patch.player ? ({ ...patch.player, player_id: id } as Indexed) : null);
    if (!player) return;
    const prev = rows.get(id);
    rows.set(id, {
      player,
      replacedBy: patch.replacedBy ?? prev?.replacedBy ?? null,
      leaves: patch.leaves ?? prev?.leaves ?? false,
      forcedNow: patch.forcedNow ?? prev?.forcedNow ?? false,
    });
  };

  for (const row of decisions) {
    const replaced = text(row.replaces?.player_id);
    if (!replaced) continue;
    put(replaced, { replacedBy: nameOf(row), player: null });
  }
  for (const row of input.plan?.lineup?.leaves || []) {
    put(text(row.player_id), { leaves: true, player: row });
  }
  for (const action of actions) {
    if (action.kind !== "vender" && action.kind !== "vender_emergencia") continue;
    put(text(action.player_id), {
      leaves: true,
      forcedNow: action.kind === "vender_emergencia" || action.when === "ahora",
      player: action,
    });
  }
  for (const row of input.squads?.sell || []) {
    const id = text(row.player_id);
    if (!id || recommendedIds.has(id)) continue;
    put(id, { leaves: true, player: row as LoosePlayer });
  }
  return [...rows.values()];
}

function offerCards(
  decisions: Decision[],
  known: Map<string, Indexed>,
  inXi: (id: string | null) => boolean,
  selfTeamId: string | null,
): RecCard[] {
  const cards: RecCard[] = [];
  for (const row of decisions) {
    const id = text(row.player_id);
    if (!id) continue;
    const own =
      row.offer_source === "propio" ||
      (selfTeamId !== null && row.seller_team_id === selfTeamId) ||
      (row.offer_source === "liga" && inXi(id));
    if (!own) continue;
    const bid = num(row.leading_bid) ?? (row.offer_source === "propio" || row.offer_source === "liga" ? num(row.sale_price) : null);
    if (bid === null) continue;
    const player = known.get(id) || row;
    const label = nameOf(player) || "el jugador";
    const market = num(player.market_value);
    const below = market !== null && bid <= market * 1.01;
    const playing = inXi(id);
    if (!playing && !below) continue;
    const pts = playerPoints(player);
    const from = row.offer_source === "liga" ? " de LaLiga" : text(row.seller_manager) ? ` de ${row.seller_manager}` : "";
    cards.push({
      id: `offer-${id}`,
      lane: "hoy",
      tone: "offer",
      title: `No aceptes la oferta${from} por ${label} (${boardMoney(bid)})`,
      detail: "",
      timing: null,
      fallback: null,
      amount: boardMoney(bid),
      playerName: label,
      imageUrl: text(player.image_url),
      mystery: false,
      badge: "RECOMENDABLE",
      explain: playing
        ? `Es de tu once${pts !== null ? ` (≈${points(pts)} pts por jornada)` : ""} y el plan no lo vende: con lo que hay en el mercado no compensa.`
        : text(row.action_reason) || "La oferta no supera el valor de tenerlo.",
    });
  }
  return cards.slice(0, 4);
}

function watchCards(plan: PlanPayload | null, known: Map<string, Indexed>): RecCard[] {
  const rows = Array.isArray(plan?.protect) ? plan.protect : [];
  return rows
    .filter((row) => (num(row.threat_count) ?? 0) > 0)
    .slice(0, 4)
    .map((row) => {
      const id = text(row.player_id) || nameOf(row) || "jugador";
      const player = known.get(text(row.player_id) || "") || row;
      const label = nameOf(row) || "el jugador";
      const clause = num(row.buyout_clause_eur);
      const threats = num(row.threat_count) ?? 0;
      const rival = text(row.top_rival?.manager_name);
      return {
        id: `watch-${id}`,
        lane: "hoy" as const,
        tone: "watch" as const,
        title: clause !== null ? `No la dejes en ${boardMoney(clause)}` : `No la dejes al alcance de un rival`,
        detail: "",
        timing: null,
        fallback: null,
        amount: boardMoney(clause),
        playerName: label,
        imageUrl: text(player.image_url),
        mystery: false,
        badge: "RECOMENDABLE",
        explain: `${threats === 1 ? "Un rival llega" : `${threats} rivales llegan`} a su cláusula${
          clause !== null ? ` (${boardMoney(clause)})` : ""
        }${rival ? `. El más holgado es ${rival}` : ""}. No la dejes así si puedes subirla o vender antes.`,
      };
    });
}

function windowCards(
  clock: PlanClockEvent[],
  decisions: Decision[],
  known: Map<string, Indexed>,
  cash: number | null,
  searchPositions: Set<string>,
): WindowCard[] {
  const byId = new Map(decisions.map((row) => [text(row.player_id), row]));
  const cards: WindowCard[] = [];
  for (const event of clock) {
    if (event.kind !== "desbloqueo" || event.is_self) continue;
    const id = text(event.player_id);
    if (!id) continue;
    const decision = byId.get(id);
    const player = known.get(id) || decision;
    const position = posKey(player?.position || decision?.position);
    const delta = num(decision?.points_delta);
    const wanted = searchPositions.has(position) || (delta !== null && delta > 0.05);
    if (!wanted) continue;
    const amount = num(event.amount_eur) ?? num(player?.buyout_clause);
    const when = weekdayStamp(event.local_date, event.local_time || event.local_clock);
    if (!when) continue;
    let reach: WindowCard["reach"] = null;
    let shortfall: string | null = null;
    if (cash !== null && amount !== null) {
      if (cash >= amount) reach = "llega";
      else {
        reach = "falta";
        shortfall = boardMoney(amount - cash);
      }
    } else if (amount !== null) {
      reach = "sin-caja";
    }
    const gain = signedPts(delta);
    cards.push({
      id: `window-${id}`,
      name: nameOf(event) || nameOf(player) || "Jugador",
      imageUrl: text(player?.image_url),
      position: position || null,
      amount: boardMoney(amount),
      gain: gain ? `${gain} pts por jornada` : null,
      manager: text(event.manager_name),
      note: searchPositions.has(position) ? `plan B del ${positionWord(position)}` : delta !== null && delta > 0 ? "mejora el once" : null,
      when: `se abre el ${when}`,
      reach,
      shortfall,
    });
  }
  cards.sort((a, b) => (a.reach === "llega" ? 0 : 1) - (b.reach === "llega" ? 0 : 1));
  return cards.slice(0, 6);
}

function valueGap(hoy: RecCard[], espera: RecCard[], known: Map<string, Indexed>, decisions: Decision[]): number | null {
  let incoming = 0;
  let outgoing = 0;
  let seenIn = false;
  let seenOut = false;
  for (const card of [...hoy, ...espera]) {
    if (card.tone === "bid" && card.playerName) {
      const match = decisions.find((row) => nameOf(row) === card.playerName);
      const value = num(match?.market_value);
      if (value !== null) {
        incoming += value;
        seenIn = true;
      }
    }
    if ((card.tone === "sell-now" || card.tone === "sell-later") && card.id.startsWith("sell-")) {
      const player = known.get(card.id.slice(5));
      const value = num(player?.market_value);
      if (value !== null) {
        outgoing += value;
        seenOut = true;
      }
    }
  }
  if (!seenIn || !seenOut) return null;
  return incoming - outgoing;
}

function writeStatus(hoy: RecCard[], espera: RecCard[]): string {
  const searching = espera.some((card) => card.tone === "search");
  const sellingLater = espera.some((card) => card.tone === "sell-later" || card.tone === "sell-now");
  const bidding = hoy.some((card) => card.tone === "bid");
  if (searching && (sellingLater || bidding)) return "EN BÚSQUEDA · VENDES CUANDO APAREZCA";
  if (searching) return "EN BÚSQUEDA";
  if (bidding && sellingLater) return "HOY SE PUJA · EL RESTO ESPERA";
  if (bidding) return "HOY SE PUJA";
  if (hoy.some((card) => card.tone === "sell-now") || sellingLater) return "TOCA VENDER";
  return "SIN MOVIMIENTO URGENTE";
}

function writeNarrative(hoy: RecCard[], espera: RecCard[], delta: number | null): string {
  const bids = hoy.filter((card) => card.tone === "bid" && card.playerName).map((card) => card.playerName as string);
  const sells = [...hoy, ...espera]
    .filter((card) => card.tone === "sell-now" || card.tone === "sell-later")
    .map((card) => card.playerName)
    .filter((name): name is string => Boolean(name));
  const searches = espera.filter((card) => card.tone === "search").map((card) => card.title.replace(/^Buscamos /, ""));
  const parts: string[] = [];
  const gain = signedPts(delta);
  if (gain && delta !== null && delta > 0) parts.push(`Tu equipo mejora ${gain} pts por jornada.`);
  else if (delta !== null && delta < -0.05) parts.push(`Tu equipo baja ${points(Math.abs(delta))} pts por jornada.`);
  if (sells.length) parts.push(`Vende a ${joinOr(sells)}.`);
  if (bids.length) parts.push(`Puja hoy por ${joinOr(bids)}: si esperas, puede salir del mercado.`);
  if (searches.length) parts.push(`Sigue buscando ${joinOr(searches)}.`);
  if (!parts.length) return "Con la foto de hoy el motor no tiene una compra, una venta ni una búsqueda que cambie el once.";
  return parts.join(" ");
}

function impactCopy(delta: number | null): string | null {
  if (delta === null) return null;
  if (delta >= 3) return "Mejora mucho tu equipo";
  if (delta >= 1) return "Mejora tu equipo";
  if (delta > 0.05) return "Mejora un poco tu equipo";
  if (delta < -0.05) return "Este plan resta puntos";
  return "El once no cambia";
}
