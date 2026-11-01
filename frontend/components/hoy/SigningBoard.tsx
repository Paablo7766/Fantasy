"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { eurShort, jornadaEv, points, titularShare } from "@/lib/format";
import { signedPoints } from "@/lib/hoy";
import { factsFor, photoFor, type PhotoIndex, type PlayerIndex } from "@/lib/photoIndex";
import { buildStrategyViews, type StrategyMove, type StrategyView } from "@/lib/signingBoard";
import type { NeedsPayload, OptimizePayload, PlanFichajeAccion, PlanPayload, SquadsPayload, TrendsPayload } from "@/lib/types";

type Kind = "PUJA" | "BUSCA" | "VENDE" | "CLAUSULAZO";

const KIND_LABEL: Record<Kind, string> = {
  PUJA: "Pujar",
  BUSCA: "Buscar en el mercado",
  VENDE: "Vender",
  CLAUSULAZO: "Pagar cláusula",
};

function kindOf(verb: string): Kind {
  const value = verb.toLowerCase();
  if (value.includes("busca") || value.includes("buscar")) return "BUSCA";
  if (value.includes("vend") || value.includes("venta")) return "VENDE";
  if (value.includes("cláus") || value.includes("claus") || value.includes("rival") || value.includes("proteger") || value.includes("subir")) {
    return "CLAUSULAZO";
  }
  return "PUJA";
}

function moveFromAction(action: PlanFichajeAccion, index: number, photos: PhotoIndex): StrategyMove {
  const tipo = (action.tipo || "PUJA").toUpperCase();
  const verb =
    tipo === "VENDE" ? "Poner en venta" : tipo === "BUSCA" ? "Buscar en el mercado" : tipo === "CLAUSULAZO" ? "Fichar de un rival" : "Pujar en el mercado";
  const amount = typeof action.euros === "number" ? Math.abs(action.euros) : null;
  const jornada = typeof action.jornada === "number" ? action.jornada : null;
  const income = tipo === "VENDE";
  return {
    id: `plan-${tipo}-${action.player_id || action.nombre || index}`,
    playerId: action.player_id || null,
    verb,
    title: tipo === "BUSCA" ? (action.posicion ? `un ${action.posicion}` : "un hueco") : action.nombre || "Jugador",
    position: action.posicion || null,
    imageUrl: photoFor(photos, action.player_id, action.nombre),
    cashImpact: amount === null ? null : income ? amount : -amount,
    cashLabel: amount === null ? null : eurShort(amount),
    cashTone: income ? "up" : "down",
    pointsImpact: jornada,
    pointsLabel: jornada === null ? null : `${points(jornada)} xP`,
    pointsTone: "flat",
    detail: action.detalle || null,
    href: tipo === "VENDE" ? "/equipo?tab=cartera" : tipo === "CLAUSULAZO" ? "/equipo?tab=clausulas" : "/mercado",
    guide: tipo === "VENDE" ? "Cartera" : tipo === "CLAUSULAZO" ? "Cláusulas" : "Mercado",
  };
}

const TAB_LABEL: Record<StrategyView["id"], string> = {
  estrategia: "Fichajes",
  clausulas: "Cláusulas",
  ventas: "Ventas",
};

const LINE_CODES: Record<string, string> = {
  POR: "POR",
  GK: "POR",
  PORTERO: "POR",
  DEF: "DEF",
  DF: "DEF",
  DEFENSA: "DEF",
  MC: "MC",
  MED: "MC",
  MID: "MC",
  MI: "MC",
  MEDIO: "MC",
  DEL: "DEL",
  DL: "DEL",
  FWD: "DEL",
  DELANTERO: "DEL",
};
const LINE_ORDER = ["POR", "DEF", "MC", "DEL"] as const;

function lineOf(position: string | null | undefined): string | null {
  return LINE_CODES[(position || "").toUpperCase()] || null;
}

function sumBy<T>(rows: T[], pick: (row: T) => [string | null, number | null]): Record<string, number> {
  const totals: Record<string, number> = {};
  for (const row of rows) {
    const [line, value] = pick(row);
    if (!line || value === null) continue;
    totals[line] = (totals[line] || 0) + value;
  }
  return totals;
}

export function SigningBoard({
  plan,
  optimize,
  squads,
  trends,
  needs,
  loading,
  refreshing,
  photos,
  facts,
}: {
  plan: PlanPayload | null;
  optimize: OptimizePayload | null;
  squads: SquadsPayload | null;
  trends: TrendsPayload | null;
  needs: NeedsPayload | null;
  loading: boolean;
  refreshing: boolean;
  photos: PhotoIndex;
  facts: PlayerIndex;
  photoLine?: string;
}) {
  const views = useMemo(
    () => buildStrategyViews(plan, optimize, squads, trends, needs),
    [plan, optimize, squads, trends, needs],
  );
  const [desk, setDesk] = useState<StrategyView["id"]>("estrategia");
  const [openId, setOpenId] = useState<string | null>(null);
  const [showBreakdown, setShowBreakdown] = useState(false);
  const view = views.find((item) => item.id === desk) ?? views[0];
  const fichajes = plan?.plan_fichajes;
  const actions = useMemo(() => fichajes?.acciones || [], [fichajes?.acciones]);
  const planMoves = useMemo(() => actions.map((action, index) => moveFromAction(action, index, photos)), [actions, photos]);
  const usePlan = desk === "estrategia" && planMoves.length > 0;
  const listed = (usePlan ? planMoves : view.groups.flatMap((group) => group.moves)).map((move) =>
    move.imageUrl ? move : { ...move, imageUrl: photoFor(photos, move.playerId, move.title) },
  );

  const sales = listed.filter((move) => kindOf(move.verb) === "VENDE");
  const buys = listed.filter((move) => kindOf(move.verb) !== "VENDE");
  const laterIds = new Set(
    usePlan
      ? actions.map((action, index) => (action.momento === "luego" ? planMoves[index].id : null)).filter((id): id is string => id !== null)
      : [],
  );

  const verdict =
    desk === "estrategia"
      ? fichajes?.veredicto || (view.pointsTone === "up" ? "Hazlo ya" : view.headline || "Sin plan")
      : view.headline || view.label;
  const cashNow = typeof plan?.cash_eur === "number" ? plan.cash_eur : null;
  const cashEnd = typeof fichajes?.saldo_al_final === "number" ? fichajes.saldo_al_final : null;

  const salesActions = usePlan ? sales : [];
  const buyActions = usePlan ? buys.filter((move) => kindOf(move.verb) !== "BUSCA") : [];
  const incomeTotal = salesActions.reduce((total, move) => total + Math.abs(move.cashImpact || 0), 0);
  const spendTotal = buyActions.reduce((total, move) => total + Math.abs(move.cashImpact || 0), 0);

  // Qué líneas mejoran: el once que propone el plan frente al once que tienes guardado.
  const lineDelta = useMemo(() => {
    const next = fichajes?.once;
    const current = optimize?.saved_lineup?.xi?.length ? optimize.saved_lineup.xi : optimize?.xi;
    if (!next?.length || !current?.length) return null;
    const after = sumBy(next, (row) => [lineOf(row.posicion), typeof row.jornada === "number" ? row.jornada : null]);
    const before = sumBy(current, (row) => [lineOf(row.position), jornadaEv(row)]);
    return LINE_ORDER.map((line) => ({ line, delta: (after[line] || 0) - (before[line] || 0) }));
  }, [fichajes?.once, optimize]);

  const rivalsWithCash = (amount: number | null) => {
    if (amount === null || !squads?.rivals?.length) return null;
    return squads.rivals.filter((rival) => typeof rival.cash_eur === "number" && rival.cash_eur >= amount).length;
  };

  const total = sales.length + buys.length;
  const today = [...sales, ...buys].filter((move) => !laterIds.has(move.id));
  const later = [...sales, ...buys].filter((move) => laterIds.has(move.id));
  const hasBreakdown = desk === "estrategia" && (cashNow !== null || cashEnd !== null || lineDelta);

  return (
    <div className="desk">
      <div className="px-1">
        <h2 className="truncate text-[1.6rem] font-semibold leading-tight tracking-tight text-white">
          {loading && !plan ? "…" : verdict}
        </h2>
        <p className="mt-1 text-[14px] text-[#8B9EB0]">
          {refreshing ? "Actualizando…" : total ? `${total} ${total === 1 ? "movimiento" : "movimientos"}` : "Sin movimientos"}
        </p>
      </div>

      <div className="desk-switch" role="tablist" aria-label="Mesas de recomendación">
        {views.map((item) => {
          const active = item.id === view.id;
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={active}
              className={active ? "desk-switch__btn desk-switch__btn--on" : "desk-switch__btn"}
              onClick={() => {
                setDesk(item.id);
                setOpenId(null);
              }}
            >
              {TAB_LABEL[item.id]}
            </button>
          );
        })}
      </div>

      {loading && !plan ? (
        <div className="desk-skel" aria-hidden="true" />
      ) : total ? (
        <div key={desk} className="flex flex-col gap-6">
          <MoveList
            title={later.length ? "Para hoy" : null}
            moves={today}
            index0={0}
            openId={openId}
            onToggle={setOpenId}
            facts={facts}
            rivalsWithCash={rivalsWithCash}
          />
          <MoveList
            title="Más adelante"
            moves={later}
            index0={today.length}
            openId={openId}
            onToggle={setOpenId}
            facts={facts}
            rivalsWithCash={rivalsWithCash}
          />

          {hasBreakdown ? (
            <div>
              <button
                type="button"
                onClick={() => setShowBreakdown((value) => !value)}
                aria-expanded={showBreakdown}
                className="flex w-full items-center justify-between px-1 py-1 text-[14px] font-medium text-[#8B9EB0] transition-colors hover:text-white"
              >
                Desglose del plan
                <Chevron open={showBreakdown} />
              </button>
              {showBreakdown ? (
                <dl className="row-in mt-2 divide-y divide-white/[0.05] rounded-3xl bg-white/[0.035] px-4 text-[14px] tabular-nums">
                  {cashNow !== null ? <Line label="Saldo inicial" value={eurShort(cashNow)} /> : null}
                  {salesActions.length ? (
                    <Line label={`Ventas (${salesActions.length})`} value={`+${eurShort(incomeTotal)}`} tone="text-[#34D399]" />
                  ) : null}
                  {buyActions.length ? <Line label={`Compras (${buyActions.length})`} value={`−${eurShort(spendTotal)}`} /> : null}
                  {cashEnd !== null ? (
                    <Line label="Saldo final" value={eurShort(cashEnd)} tone={cashEnd < 0 ? "text-[#FC734D]" : undefined} />
                  ) : null}
                  {lineDelta
                    ? lineDelta
                        .filter(({ delta }) => Math.abs(delta) >= 0.05)
                        .map(({ line, delta }) => (
                          <Line
                            key={line}
                            label={`Puntos ${line}`}
                            value={`${signedPoints(delta)} pts`}
                            tone={delta > 0 ? "text-[#0297DE]" : "text-[#FC734D]"}
                          />
                        ))
                    : null}
                </dl>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : (
        <p className="desk-empty">
          {view.id === "estrategia"
            ? "Con esta foto no hay un fichaje que suba los puntos del once."
            : "Esta foto no deja un movimiento en esta mesa."}
        </p>
      )}
    </div>
  );
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      viewBox="0 0 16 16"
      className={`h-4 w-4 shrink-0 text-[#4B6075] transition-transform duration-200 ${open ? "rotate-180" : ""}`}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      aria-hidden="true"
    >
      <path d="M4 6.2 8 10l4-3.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Line({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex items-center justify-between py-3">
      <dt className="text-[#8B9EB0]">{label}</dt>
      <dd className={`font-medium ${tone || "text-white"}`}>{value}</dd>
    </div>
  );
}

function MoveList({
  title,
  moves,
  index0,
  openId,
  onToggle,
  facts,
  rivalsWithCash,
}: {
  title: string | null;
  moves: StrategyMove[];
  index0: number;
  openId: string | null;
  onToggle: (id: string | null) => void;
  facts: PlayerIndex;
  rivalsWithCash: (amount: number | null) => number | null;
}) {
  if (!moves.length) return null;
  return (
    <section aria-label={title || "Movimientos"}>
      {title ? <h3 className="mb-2 px-1 text-[14px] font-medium text-[#8B9EB0]">{title}</h3> : null}
      <ul className="overflow-hidden rounded-3xl bg-white/[0.035]">
        {moves.map((move, index) => (
          <MoveRow
            key={move.id}
            move={move}
            index={index0 + index}
            first={index === 0}
            open={openId === move.id}
            onToggle={() => onToggle(openId === move.id ? null : move.id)}
            facts={facts}
            rivalsWithCash={rivalsWithCash}
          />
        ))}
      </ul>
    </section>
  );
}

function MoveRow({
  move,
  index,
  first,
  open,
  onToggle,
  facts,
  rivalsWithCash,
}: {
  move: StrategyMove;
  index: number;
  first: boolean;
  open: boolean;
  onToggle: () => void;
  facts: PlayerIndex;
  rivalsWithCash: (amount: number | null) => number | null;
}) {
  const kind = kindOf(move.verb);
  const info = kind === "BUSCA" ? null : factsFor(facts, move.playerId, move.title);
  const name = kind === "BUSCA" ? move.position || move.title : move.title;
  const amount = move.cashImpact === null ? null : Math.abs(move.cashImpact);
  const sale = kind === "VENDE";

  const rows: [string, string][] = [];
  if (kind === "VENDE") {
    const share = titularShare(info?.p_titular);
    if (share !== null) rows.push(["Titular", `${Math.round(share * 100)}%`]);
    if (typeof info?.tu_once_pierde_sin_el === "number") rows.push(["Impacto en tu once", `−${points(Math.abs(info.tu_once_pierde_sin_el))} pts`]);
    if (info?.prevision_7d_pct) rows.push(["Previsión a 7 días", info.prevision_7d_pct]);
  } else if (kind === "CLAUSULAZO") {
    if (info?.owner) rows.push(["Propietario", info.owner]);
    if (typeof info?.valor_justo === "number") {
      rows.push(["Valor justo", eurShort(info.valor_justo)]);
      if (amount) {
        const margin = (info.valor_justo / amount - 1) * 100;
        rows.push(["Margen", `${margin >= 0 ? "+" : "−"}${Math.abs(Math.round(margin))}%`]);
      }
    }
  } else if (kind === "PUJA") {
    if (typeof info?.market_value === "number") rows.push(["Valor de mercado", eurShort(info.market_value)]);
    const cap = info?.puja_maxima ?? info?.max_bid ?? info?.own_max_bid ?? null;
    if (typeof cap === "number") rows.push(["Puja máxima", eurShort(cap)]);
    const rivals = rivalsWithCash(amount);
    if (rivals !== null) rows.push(["Rivales con saldo", String(rivals)]);
  }
  if (move.pointsImpact !== null) rows.push(["Puntos esperados", `${points(move.pointsImpact)} xP`]);
  const ceiling = info?.own_ceiling_points ?? info?.af_ceiling_points ?? null;
  if (typeof ceiling === "number" && ceiling > 10) rows.push(["Techo", `${points(ceiling)} pts`]);

  return (
    <li className="row-in" style={{ animationDelay: `${index * 30}ms` }}>
      {first ? null : <div className="ml-[4.5rem] mr-4 h-px bg-white/[0.06]" />}
      <button
        type="button"
        className="flex w-full items-center gap-3.5 px-4 py-3.5 text-left transition-colors hover:bg-white/[0.02]"
        onClick={onToggle}
        aria-expanded={open}
      >
        <PlayerAvatar player={{ name, image_url: move.imageUrl }} size="sm" className="!h-11 !w-11 !text-[11px] !ring-0" />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[16px] font-medium leading-tight text-white">
            {kind === "BUSCA" ? `Buscar ${name}` : name}
          </span>
          <span className="mt-0.5 block truncate text-[13.5px] text-[#8B9EB0]">
            {KIND_LABEL[kind]}
            {move.position && kind !== "BUSCA" ? ` · ${move.position.slice(0, 3).toUpperCase()}` : ""}
          </span>
        </span>
        <span className={`shrink-0 text-[16px] font-medium tabular-nums ${sale ? "text-[#34D399]" : "text-white"}`}>
          {move.cashLabel ? `${sale ? "+" : ""}${move.cashLabel}` : ""}
        </span>
        <Chevron open={open} />
      </button>
      {open ? (
        <div className="px-4 pb-4 pl-[4.5rem]">
          {rows.length ? (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
              {rows.map(([label, value]) => (
                <div key={label} className="min-w-0">
                  <dt className="truncate text-[12.5px] text-[#8B9EB0]">{label}</dt>
                  <dd className="mt-0.5 truncate text-[15px] font-medium tabular-nums text-white">{value}</dd>
                </div>
              ))}
            </dl>
          ) : null}
          {move.detail ? <p className="mt-3 text-[14px] leading-5 text-[#8B9EB0]">{move.detail}</p> : null}
          <Link href={move.href} className="mt-3 inline-flex text-[14px] font-medium text-[#0297DE]">
            Ver en {move.guide}
          </Link>
        </div>
      ) : null}
    </li>
  );
}
