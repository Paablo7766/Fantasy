import { eurShort, points, stamp } from "@/lib/format";
import { signedPoints } from "@/lib/hoy";
import type {
  ClauseAlert,
  Gap,
  NeedsPayload,
  OptimizePayload,
  PlanAction,
  PlanPayload,
  PlanPlayer,
  PlanStrategy,
  PlanStrategyMove,
  Player,
  SquadsPayload,
  TrendsPayload,
} from "@/lib/types";

const POSITION: Record<string, string> = {
  POR: "portero",
  GK: "portero",
  DEF: "defensa",
  DF: "defensa",
  MED: "medio",
  MID: "medio",
  MC: "medio",
  MI: "medio",
  DEL: "delantero",
  DL: "delantero",
  FWD: "delantero",
};

export type MoveTone = "up" | "down" | "flat" | "none";

export type StrategyMove = {
  id: string;
  verb: string;
  title: string;
  position: string | null;
  imageUrl: string | null;
  /** Efecto en la caja. Negativo = sale dinero. */
  cashImpact: number | null;
  cashLabel: string | null;
  cashTone: MoveTone;
  /** Efecto en puntos, solo si la foto trae un delta o los puntos del jugador. */
  pointsImpact: number | null;
  pointsLabel: string | null;
  pointsTone: MoveTone;
  detail: string | null;
  href: string;
  guide: string;
};

export type StrategyGroup = {
  id: string;
  label: string;
  moves: StrategyMove[];
};

export type StrategyView = {
  id: "estrategia" | "clausulas" | "ventas";
  label: string;
  kicker: string;
  headline: string | null;
  sentence: string | null;
  pointsMove: string | null;
  pointsTone: MoveTone;
  cashMove: string | null;
  cashTone: MoveTone;
  groups: StrategyGroup[];
  savedPoints: string | null;
  recommendedPoints: string | null;
};

type Priced = {
  player_id?: string | null;
  sale_price?: number | null;
  market_value?: number | null;
};

function text(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function money(value: unknown): number | null {
  if (typeof value !== "number" || Number.isNaN(value)) return null;
  return value;
}

function labelOf(row: { nickname?: string | null; name?: string | null } | null | undefined): string | null {
  return text(row?.nickname) || text(row?.name);
}

function positionLabel(code: string | null | undefined): string | null {
  const raw = text(code);
  if (!raw) return null;
  return POSITION[raw.toUpperCase()] || raw;
}

function priceOf(row: Priced | null | undefined): number | null {
  if (!row) return null;
  return money(row.sale_price) ?? money(row.market_value);
}

function remember(index: Map<string, number>, row: Priced | null | undefined) {
  const id = text(row?.player_id);
  const price = priceOf(row);
  if (!id || price === null || index.has(id)) return;
  index.set(id, price);
}

function pointsOf(row: { jornada_ev?: number | null; expected_points?: number | null } | null | undefined): number | null {
  if (!row) return null;
  return money(row.jornada_ev) ?? money(row.expected_points);
}

function toneOf(value: number | null): MoveTone {
  if (value === null) return "none";
  if (value > 0.05) return "up";
  if (value < -0.05) return "down";
  return "flat";
}

function signedMoney(value: number): string {
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${eurShort(Math.abs(value))}`;
}

function spend(value: number | null): { impact: number | null; label: string | null; tone: MoveTone } {
  if (value === null) return { impact: null, label: null, tone: "none" };
  return { impact: -Math.abs(value), label: `−${eurShort(Math.abs(value))}`, tone: "down" };
}

function income(value: number | null): { impact: number | null; label: string | null; tone: MoveTone } {
  if (value === null) return { impact: null, label: null, tone: "none" };
  return { impact: Math.abs(value), label: `+${eurShort(Math.abs(value))}`, tone: "up" };
}

function deltaPts(value: number | null): { impact: number | null; label: string | null; tone: MoveTone } {
  if (value === null) return { impact: null, label: null, tone: "none" };
  const signed = signedPoints(value);
  return { impact: value, label: signed ? `${signed} pts` : null, tone: toneOf(value) };
}

function plainPts(value: number | null): { impact: number | null; label: string | null; tone: MoveTone } {
  if (value === null) return { impact: null, label: null, tone: "none" };
  return { impact: null, label: `${points(value)} pts`, tone: "flat" };
}

function sumImpacts(moves: StrategyMove[], key: "cashImpact" | "pointsImpact"): number | null {
  const values = moves.map((move) => move[key]).filter((value): value is number => value !== null);
  if (!values.length) return null;
  return values.reduce((total, value) => total + value, 0);
}

function priceIndex(
  plan: PlanPayload | null,
  optimize: OptimizePayload | null,
  squads: SquadsPayload | null,
  trends: TrendsPayload | null,
): Map<string, number> {
  const index = new Map<string, number>();
  const buckets: Array<Priced[] | null | undefined> = [
    trends?.market?.listings,
    trends?.flips,
    plan?.decisions,
    optimize?.xi,
    optimize?.benched,
    optimize?.excluded,
    optimize?.saved_lineup?.xi,
    squads?.self?.players,
    squads?.sell,
  ];
  for (const bucket of buckets) {
    for (const row of bucket || []) remember(index, row);
  }
  return index;
}

function gapsOf(plan: PlanPayload | null, optimize: OptimizePayload | null): Gap[] {
  const lineup = plan?.lineup as { gaps?: Gap[] } | undefined;
  if (Array.isArray(lineup?.gaps) && lineup.gaps.length) return lineup.gaps.filter(Boolean);
  if (Array.isArray(optimize?.market_fills) && optimize.market_fills.length) return optimize.market_fills;
  return (optimize?.gaps || []).filter(Boolean);
}

function planActions(plan: PlanPayload | null): PlanAction[] {
  const prioritized = Array.isArray(plan?.priority_actions) ? plan.priority_actions : [];
  if (prioritized.length) return prioritized;
  return Array.isArray(plan?.actions) ? plan.actions : [];
}

function byPoints(left: StrategyMove, right: StrategyMove): number {
  return (right.pointsImpact ?? -1) - (left.pointsImpact ?? -1);
}

function bids(plan: PlanPayload | null): StrategyMove[] {
  return planActions(plan)
    .filter((action) => action.kind === "pujar" && action.when !== "snipe" && action.bid_how !== "snipe" && action.eligible !== false)
    .map((action, index) => {
      const title = labelOf(action);
      if (!title) return null;
      const cash = spend(money(action.amount_eur));
      const pts = deltaPts(money(action.points_delta));
      const move: StrategyMove = {
        id: `bid-${action.player_id || index}`,
        verb: "Pujar en el mercado",
        title,
        position: positionLabel(action.position),
        imageUrl: text(action.image_url),
        cashImpact: cash.impact,
        cashLabel: cash.label,
        cashTone: cash.tone,
        pointsImpact: pts.impact,
        pointsLabel: pts.label,
        pointsTone: pts.tone,
        detail: text(action.manager_name) ? `Sale de ${action.manager_name}` : "Listing del mercado",
        href: "/mercado",
        guide: "Abrir mercado",
      };
      return move;
    })
    .filter((move): move is StrategyMove => Boolean(move))
    .sort(byPoints);
}

function rivalBuys(plan: PlanPayload | null): StrategyMove[] {
  return planActions(plan)
    .filter((action) => action.kind === "clausular" && action.eligible !== false)
    .map((action, index) => {
      const title = labelOf(action);
      if (!title) return null;
      const cash = spend(money(action.amount_eur));
      const pts = deltaPts(money(action.points_delta));
      const manager = text(action.manager_name);
      const move: StrategyMove = {
        id: `rival-${action.player_id || index}`,
        verb: "Fichar de un rival",
        title,
        position: positionLabel(action.position),
        imageUrl: text(action.image_url),
        cashImpact: cash.impact,
        cashLabel: cash.label,
        cashTone: cash.tone,
        pointsImpact: pts.impact,
        pointsLabel: pts.label,
        pointsTone: pts.tone,
        detail: manager ? `Cláusula de ${manager}` : "Cláusula de un rival",
        href: "/equipo?tab=clausulas",
        guide: "Abrir cláusulas",
      };
      return move;
    })
    .filter((move): move is StrategyMove => Boolean(move))
    .sort(byPoints);
}

function raises(plan: PlanPayload | null): StrategyMove[] {
  return planActions(plan)
    .filter((action) => action.kind === "subir_clausula" && action.eligible !== false)
    .map((action, index) => {
      const title = labelOf(action);
      if (!title) return null;
      const cash = spend(money(action.amount_eur));
      const target = money(action.target_clause_eur);
      const move: StrategyMove = {
        id: `raise-${action.player_id || index}`,
        verb: "Subir cláusula",
        title,
        position: positionLabel(action.position),
        imageUrl: text(action.image_url),
        cashImpact: cash.impact,
        cashLabel: cash.label,
        cashTone: cash.tone,
        pointsImpact: null,
        pointsLabel: null,
        pointsTone: "none",
        detail: target !== null ? `La dejas en ${eurShort(target)}` : "Fuera del alcance del rival",
        href: "/equipo?tab=clausulas",
        guide: "Abrir cláusulas",
      };
      return move;
    })
    .filter((move): move is StrategyMove => Boolean(move));
}

function searches(plan: PlanPayload | null, optimize: OptimizePayload | null, needs: NeedsPayload | null): StrategyMove[] {
  const kickoff = text(plan?.kickoff);
  const cash = money(plan?.cash_eur);
  return gapsOf(plan, optimize)
    .map((gap, index) => {
      const position = positionLabel(gap.position);
      if (!position) return null;
      const options = (gap.options || []) as Player[];
      const prices = options.map((row) => priceOf(row)).filter((value): value is number => value !== null);
      const best = options.reduce<number | null>((top, row) => {
        const pts = pointsOf(row);
        if (pts === null) return top;
        return top === null || pts > top ? pts : top;
      }, null);
      const band =
        prices.length === 0 ? null : Math.min(...prices) === Math.max(...prices) ? eurShort(Math.min(...prices)) : `${eurShort(Math.min(...prices))} – ${eurShort(Math.max(...prices))}`;
      const reserve = reserveLine(needs?.clause_alerts, gap.position, cash);
      const bits = [band ? `Banda ${band}` : null, kickoff ? `Hasta ${stamp(kickoff)}` : null, reserve].filter((line): line is string => Boolean(line));
      const shown = plainPts(best);
      const move: StrategyMove = {
        id: `search-${gap.position || index}`,
        verb: "Buscar en el mercado",
        title: `Un ${position}${best !== null ? ` de ${points(best)} pts` : ""}`,
        position,
        imageUrl: null,
        cashImpact: null,
        cashLabel: band,
        cashTone: "flat",
        pointsImpact: null,
        pointsLabel: shown.label,
        pointsTone: shown.tone,
        detail: bits.filter((line) => line !== `Banda ${band}`).join(" · ") || null,
        href: "/mercado",
        guide: "Abrir mercado",
      };
      return move;
    })
    .filter((move): move is StrategyMove => Boolean(move))
    .slice(0, 2);
}

function reserveLine(alerts: ClauseAlert[] | undefined, position: string | undefined, cash: number | null): string | null {
  const code = text(position)?.toUpperCase();
  if (!code) return null;
  const matches = (alerts || []).filter((row) => text(row.position)?.toUpperCase() === code && labelOf(row) && money(row.buyout_clause_eur) !== null);
  if (!matches.length) return null;
  const pick = matches.slice().sort((a, b) => (money(a.buyout_clause_eur) || 0) - (money(b.buyout_clause_eur) || 0))[0];
  const clause = money(pick.buyout_clause_eur) as number;
  const cover = cash === null ? "" : cash >= clause ? ", la caja llega" : `, faltan ${eurShort(clause - cash)}`;
  return `Si no aparece: ${labelOf(pick)} por ${eurShort(clause)}${cover}`;
}

function sales(plan: PlanPayload | null, prices: Map<string, number>, squads: SquadsPayload | null): StrategyMove[] {
  const xi = new Set((plan?.lineup?.xi || []).map((row) => text(row.player_id)).filter((id): id is string => Boolean(id)));
  const fromLeaves = (plan?.lineup?.leaves || []).map((row, index) => saleMove(row, index, prices, "Sale del once recomendado"));
  const signaled = (squads?.sell || [])
    .filter((row) => {
      const id = text(row.player_id);
      return id && !xi.has(id) && row.sell_signal !== false;
    })
    .map((row, index) => saleMove(row, index + 100, prices, "Señal de venta y no está en el once"));
  const seen = new Set<string>();
  return [...fromLeaves, ...signaled]
    .filter((move): move is StrategyMove => {
      if (!move || seen.has(move.id)) return false;
      seen.add(move.id);
      return true;
    })
    .sort((left, right) => (right.cashImpact ?? 0) - (left.cashImpact ?? 0));
}

function saleMove(
  row: PlanPlayer & Priced & { image_url?: string | null; jornada_ev?: number | null },
  index: number,
  prices: Map<string, number>,
  detail: string,
): StrategyMove | null {
  const title = labelOf(row);
  const id = text(row.player_id);
  if (!title) return null;
  const price = (id ? prices.get(id) : undefined) ?? priceOf(row);
  const cash = income(price ?? null);
  const pts = plainPts(pointsOf(row));
  return {
    id: `sell-${id || index}`,
    verb: "Poner en venta",
    title,
    position: positionLabel(row.position),
    imageUrl: text(row.image_url),
    cashImpact: cash.impact,
    cashLabel: cash.label,
    cashTone: cash.tone,
    pointsImpact: null,
    pointsLabel: pts.label,
    pointsTone: pts.tone,
    detail,
    href: "/equipo?tab=cartera",
    guide: "Abrir cartera",
  };
}

function shields(plan: PlanPayload | null, optimize: OptimizePayload | null): StrategyMove[] {
  const xi = new Set(
    [...(plan?.lineup?.xi || []), ...(optimize?.xi || [])]
      .map((row) => text(row.player_id))
      .filter((id): id is string => Boolean(id)),
  );
  return (plan?.protect || [])
    .filter((row) => {
      const id = text(row.player_id);
      const clause = money(row.buyout_clause_eur);
      const rivalCash = money(row.top_rival?.cash_eur);
      return Boolean(id && xi.has(id) && clause !== null && rivalCash !== null && rivalCash >= clause);
    })
    .sort((left, right) => (money(left.buyout_clause_eur) || 0) - (money(right.buyout_clause_eur) || 0))
    .slice(0, 2)
    .map((row, index) => {
      const clause = money(row.buyout_clause_eur) as number;
      const rival = text(row.top_rival?.manager_name);
      const raise = (row.options || []).find((option) => option.kind === "subir_clausula" && option.eligible);
      const cost = spend(money(raise?.amount_eur));
      return {
        id: `shield-${row.player_id || index}`,
        verb: "No dejar la cláusula",
        title: labelOf(row) || "Titular",
        position: positionLabel(row.position),
        imageUrl: text(row.image_url),
        cashImpact: cost.impact,
        cashLabel: cost.label ?? eurShort(clause),
        cashTone: cost.label ? cost.tone : "flat",
        pointsImpact: null,
        pointsLabel: null,
        pointsTone: "none" as MoveTone,
        detail: [rival ? `${rival} puede pagarla` : null, `Cláusula ${eurShort(clause)}`].filter(Boolean).join(" · "),
        href: "/equipo?tab=clausulas",
        guide: "Abrir cláusulas",
      };
    });
}

function meters(moves: StrategyMove[], pointsFallback: number | null): Pick<StrategyView, "pointsMove" | "pointsTone" | "cashMove" | "cashTone"> {
  const cash = sumImpacts(moves, "cashImpact");
  const pointsSum = sumImpacts(moves, "pointsImpact");
  const pointsValue = pointsFallback !== null ? pointsFallback : pointsSum;
  return {
    pointsMove: pointsValue === null ? null : `${signedPoints(pointsValue)} pts`,
    pointsTone: toneOf(pointsValue),
    cashMove: cash === null ? null : signedMoney(cash),
    cashTone: toneOf(cash),
  };
}

function sentenceFrom(parts: Array<string | null>): string | null {
  const lines = parts.filter((part): part is string => Boolean(part));
  return lines.length ? lines.join(" ") : null;
}

function strategyTitle(row: PlanStrategy, index: number): string {
  const rank = row.rank ?? index + 1;
  const delta = money(row.points_delta);
  const name = rank === 1 ? "Mejor plan" : `Alternativa ${rank}`;
  return delta !== null ? `${name} · ${signedPoints(delta)} pts` : name;
}

function namesOf(moves: PlanStrategyMove[] | undefined, kind: "vender" | "ficha"): string[] {
  return (moves || [])
    .filter((move) => (kind === "vender" ? move.kind === "vender" : move.kind !== "vender"))
    .map((move) => labelOf(move))
    .filter((name): name is string => Boolean(name));
}

function planSentence(row: PlanStrategy | undefined): string | null {
  if (!row) return null;
  const delta = money(row.points_delta);
  const sells = namesOf(row.moves, "vender");
  const buys = namesOf(row.moves, "ficha");
  const value = money(row.value_delta_eur);
  return sentenceFrom([
    delta !== null ? `El once sube ${signedPoints(delta)} pts.` : null,
    sells.length ? `Vende a ${sells.join(", ")}.` : null,
    buys.length ? `Ficha a ${buys.join(", ")}.` : null,
    value !== null && Math.abs(value) >= 100_000
      ? `El valor de la plantilla ${value < 0 ? "baja" : "sube"} ${eurShort(Math.abs(value))}.`
      : null,
  ]);
}

function strategyMoves(row: PlanStrategy, planIndex: number): StrategyMove[] {
  return (row.moves || [])
    .map((move, index) => strategyMove(move, planIndex, index))
    .filter((move): move is StrategyMove => Boolean(move));
}

function strategyMove(row: PlanStrategyMove, planIndex: number, index: number): StrategyMove | null {
  const title = labelOf(row);
  if (!title) return null;
  const kind = text(row.kind);
  const amount = money(row.amount_eur);
  const cash = kind === "vender" ? income(amount) : spend(amount);
  const swap = money(row.points_delta);
  const pts = kind === "vender" || swap === null ? plainPts(money(row.points_in_xi) ?? money(row.jornada_ev)) : deltaPts(swap);
  const manager = text(row.manager_name);
  const replaces = text(row.replaces_name);
  const replacedBy = text(row.replaced_by_name);
  const verb = kind === "vender" ? "Poner en venta" : kind === "clausular" ? "Fichar de un rival" : "Pujar en el mercado";
  const href = kind === "pujar" ? "/mercado" : kind === "vender" ? "/equipo?tab=cartera" : "/equipo?tab=clausulas";
  const guide = kind === "pujar" ? "Abrir mercado" : kind === "vender" ? "Abrir cartera" : "Abrir cláusulas";
  const where =
    kind === "clausular"
      ? manager
        ? `Cláusula de ${manager}`
        : "Cláusula de un rival"
      : kind === "pujar"
        ? manager
          ? `Sale de ${manager}`
          : "Listing del mercado"
        : null;
  const detail =
    kind === "vender"
      ? sentenceFrom([replacedBy ? `Sale del once: entra ${replacedBy}` : "Ingreso si alguien la compra", where])
      : sentenceFrom([replaces ? `Juega en lugar de ${replaces}` : null, where]);
  return {
    id: `plan-${planIndex}-${kind || "mov"}-${text(row.player_id) || index}`,
    verb,
    title,
    position: positionLabel(row.position),
    imageUrl: text(row.image_url),
    cashImpact: cash.impact,
    cashLabel: cash.label,
    cashTone: cash.tone,
    pointsImpact: pts.impact,
    pointsLabel: pts.label,
    pointsTone: pts.tone,
    detail,
    href,
    guide,
  };
}

export function buildStrategyViews(
  plan: PlanPayload | null,
  optimize: OptimizePayload | null,
  squads: SquadsPayload | null,
  trends: TrendsPayload | null,
  needs: NeedsPayload | null,
): StrategyView[] {
  const prices = priceIndex(plan, optimize, squads, trends);
  const saved = money(plan?.lineup?.saved_points);
  const recommended = money(plan?.lineup?.expected_points);
  const foot = {
    savedPoints: saved === null ? null : points(saved),
    recommendedPoints: recommended === null ? null : points(recommended),
  };

  const found = (plan?.strategies || []).filter((row) => (row.moves || []).length);
  const strategyGroups = found.map((row, index) => ({
    id: text(row.id) || `s${index + 1}`,
    label: strategyTitle(row, index),
    moves: strategyMoves(row, index),
  })).filter((group) => group.moves.length);
  const best = found[0];
  const bestDelta = money(best?.points_delta);
  const planMeters = meters(strategyGroups[0]?.moves || [], bestDelta);
  const topSales = sales(plan, prices, squads);

  const pay = rivalBuys(plan).slice(0, 2);
  const shield = shields(plan, optimize);
  const raise = raises(plan).filter((move) => !shield.some((row) => row.title === move.title)).slice(0, 1);
  const clauseMoves = [...pay, ...raise, ...shield].slice(0, 4);
  const clauseMeters = meters(clauseMoves, null);

  const saleMoves = topSales.slice(0, 3);
  const saleMeters = meters(saleMoves, null);

  const status = text(plan?.mode?.label);

  return [
    {
      id: "estrategia",
      label: "Estrategia",
      kicker: "Plan de fichajes",
      headline: best
        ? bestDelta !== null
          ? `Mejora el once ${signedPoints(bestDelta)} pts`
          : `Once a ${points(money(best.expected_points) ?? recommended)}`
        : status,
      sentence: planSentence(best),
      ...planMeters,
      groups: strategyGroups,
      savedPoints: saved === null ? null : points(saved),
      recommendedPoints: money(best?.expected_points) !== null ? points(money(best?.expected_points)) : foot.recommendedPoints,
    },
    {
      id: "clausulas",
      label: "Clausulazos",
      kicker: "Cláusulas",
      headline: pay[0] ? `Pagar a ${pay[0].title}` : shield[0] ? `Proteger a ${shield[0].title}` : null,
      sentence: sentenceFrom([
        pay[0]?.pointsLabel ? `${pay[0].title} mueve ${pay[0].pointsLabel}.` : null,
        pay[0]?.cashLabel ? `Cuesta ${pay[0].cashLabel.replace("−", "")}.` : null,
        shield[0] ? `${shield[0].title}: ${shield[0].detail}.` : null,
      ]),
      ...clauseMeters,
      groups: [
        { id: "pagar", label: "Pagar", moves: pay },
        { id: "proteger", label: "Proteger", moves: [...raise, ...shield] },
      ].filter((group) => group.moves.length),
      savedPoints: null,
      recommendedPoints: null,
    },
    {
      id: "ventas",
      label: "Ventas",
      kicker: "Ventas",
      headline: saleMoves[0] ? `Vender a ${saleMoves[0].title}` : null,
      sentence: sentenceFrom([
        saleMoves.length ? "Solo quien sale del once o ya no juega, por el dinero que entra." : null,
        saleMeters.cashMove ? `Esas ventas suman ${saleMeters.cashMove} de caja.` : null,
      ]),
      ...saleMeters,
      groups: [{ id: "vender", label: "Poner en venta", moves: saleMoves }].filter((group) => group.moves.length),
      savedPoints: null,
      recommendedPoints: null,
    },
  ];
}
