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

const KIND_STYLE: Record<Kind, { label: string; className: string }> = {
  PUJA: { label: "Pujar", className: "bg-[#0297DE]/15 text-[#67C6F5]" },
  BUSCA: { label: "Buscar", className: "bg-white/[0.06] text-[#8B9EB0]" },
  VENDE: { label: "Vender", className: "bg-[#10B981]/15 text-[#6EE7B7]" },
  CLAUSULAZO: { label: "Cláusula", className: "bg-[#FC734D]/15 text-[#FFB4A0]" },
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

function leadLine(detail: string | null): string | null {
  if (!detail) return null;
  const line = detail.split(/(?<=\.)\s+/)[0]?.trim();
  if (!line) return null;
  return line.length > 96 ? `${line.slice(0, 93)}…` : line;
}

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
  const net = (rows: StrategyMove[]) => {
    const values = rows.map((move) => move.cashImpact).filter((value): value is number => value !== null);
    return values.length ? values.reduce((total, value) => total + value, 0) : null;
  };

  const verdict =
    desk === "estrategia"
      ? fichajes?.veredicto || (view.pointsTone === "up" ? "Hazlo ya" : view.headline || "Sin plan")
      : view.headline || view.label;
  const gain =
    typeof fichajes?.mejora_puntos_jornada === "number"
      ? signedPoints(fichajes.mejora_puntos_jornada)
      : view.pointsMove
        ? view.pointsMove.replace(" pts", "")
        : null;
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

  return (
    <div className="desk">
      <div className="desk-switch" role="tablist" aria-label="Mesas de recomendación">
        {views.map((item) => {
          const count =
            item.id === "estrategia" && planMoves.length
              ? planMoves.length
              : item.groups.reduce((total, group) => total + group.moves.length, 0);
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
              {count ? <span>{count}</span> : null}
            </button>
          );
        })}
      </div>

      <header className="rounded-2xl border border-white/[0.07] bg-[#07121A] p-4">
        <div className="flex items-end justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[9.5px] font-semibold uppercase tracking-[0.12em] text-[#8B9EB0]">Qué hace el plan</p>
            <p className="mt-1.5 truncate text-xl font-semibold leading-tight tracking-tight text-white">
              {loading && !plan ? "…" : verdict}
            </p>
            {refreshing ? <p className="mt-1 font-mono text-[11px] text-[#0297DE]">Actualizando</p> : null}
          </div>
          {gain && desk === "estrategia" ? (
            <div className="shrink-0 text-right">
              <p className={`font-mono text-2xl font-semibold leading-none tabular-nums ${gain.startsWith("−") || gain.startsWith("-") ? "text-[#FC734D]" : "text-[#0297DE]"}`}>
                {gain}
              </p>
              <p className="mt-1 text-[9.5px] font-semibold uppercase tracking-[0.12em] text-[#8B9EB0]">pts/jornada</p>
            </div>
          ) : null}
        </div>

        {desk === "estrategia" && (cashNow !== null || cashEnd !== null) ? (
          <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-xl border border-white/[0.05] bg-[#02070A]/60 p-2.5 font-mono text-xs tabular-nums">
            {cashNow !== null ? <span className="text-[#C5D4E2]">Inicial: {eurShort(cashNow)}</span> : null}
            {salesActions.length ? (
              <>
                <span className="text-[#4B6075]" aria-hidden="true">➔</span>
                <span className="text-[#10B981]">
                  Ventas ({salesActions.length}): +{eurShort(incomeTotal)}
                </span>
              </>
            ) : null}
            {buyActions.length ? (
              <>
                <span className="text-[#4B6075]" aria-hidden="true">➔</span>
                <span className="text-[#0297DE]">
                  Compras ({buyActions.length}): −{eurShort(spendTotal)}
                </span>
              </>
            ) : null}
            {cashEnd !== null ? (
              <>
                <span className="text-[#4B6075]" aria-hidden="true">➔</span>
                <span className={cashEnd < 0 ? "text-[#FC734D]" : "text-white"}>Final: {eurShort(cashEnd)}</span>
              </>
            ) : null}
          </div>
        ) : null}

        {desk === "estrategia" && lineDelta ? (
          <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[11px] tabular-nums">
            <span className="text-[9.5px] font-semibold uppercase tracking-[0.12em] text-[#8B9EB0]">Impacto</span>
            {lineDelta.map(({ line, delta }) => (
              <span key={line} className={Math.abs(delta) < 0.05 ? "text-[#4B6075]" : delta > 0 ? "text-[#0297DE]" : "text-[#FC734D]"}>
                {line} {Math.abs(delta) < 0.05 ? "=" : `${signedPoints(delta)} pts`}
              </span>
            ))}
          </div>
        ) : null}
      </header>

      {loading && !plan ? (
        <div className="desk-skel" aria-hidden="true" />
      ) : sales.length || buys.length ? (
        <div key={desk} className="flex flex-col gap-3">
          <OrderBook
            title="Fase 1 · Ejecutar hoy"
            moves={sales}
            total={net(sales)}
            laterIds={laterIds}
            openId={openId}
            onToggle={setOpenId}
            facts={facts}
            rivalsWithCash={rivalsWithCash}
          />
          <OrderBook
            title="Fase 2 · Compras y clausulazos"
            moves={buys}
            total={net(buys)}
            laterIds={laterIds}
            openId={openId}
            onToggle={setOpenId}
            facts={facts}
            rivalsWithCash={rivalsWithCash}
          />
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

function OrderBook({
  title,
  moves,
  total,
  laterIds,
  openId,
  onToggle,
  facts,
  rivalsWithCash,
}: {
  title: string;
  moves: StrategyMove[];
  total: number | null;
  laterIds: Set<string>;
  openId: string | null;
  onToggle: (id: string | null) => void;
  facts: PlayerIndex;
  rivalsWithCash: (amount: number | null) => number | null;
}) {
  if (!moves.length) return null;
  const operations = `${moves.length} ${moves.length === 1 ? "operación" : "operaciones"}`;
  return (
    <section className="overflow-hidden rounded-2xl border border-white/[0.07] bg-[#07121A]" aria-label={title}>
      <h2 className="flex items-center justify-between gap-2 border-b border-white/[0.05] px-3.5 py-2.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-[#8B9EB0]">
        <span>
          {title} <span className="whitespace-nowrap text-[#4B6075]">({operations})</span>
        </span>
        {total !== null ? (
          <span className={`shrink-0 font-mono text-[11px] normal-case tracking-normal tabular-nums ${total >= 0 ? "text-[#10B981]" : "text-[#F0F6FC]"}`}>
            {total >= 0 ? "+" : "−"}
            {eurShort(Math.abs(total))}
          </span>
        ) : null}
      </h2>
      <ul className="divide-y divide-white/[0.05]">
        {moves.map((move, index) => (
          <OrderRow
            key={move.id}
            move={move}
            index={index}
            later={laterIds.has(move.id)}
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

function OrderRow({
  move,
  index,
  later,
  open,
  onToggle,
  facts,
  rivalsWithCash,
}: {
  move: StrategyMove;
  index: number;
  later: boolean;
  open: boolean;
  onToggle: () => void;
  facts: PlayerIndex;
  rivalsWithCash: (amount: number | null) => number | null;
}) {
  const kind = kindOf(move.verb);
  const style = KIND_STYLE[kind];
  const info = kind === "BUSCA" ? null : factsFor(facts, move.playerId, move.title);
  const name = kind === "BUSCA" ? move.position || move.title : move.title;
  const amount = move.cashImpact === null ? null : Math.abs(move.cashImpact);

  const bits: string[] = [];
  if (kind === "VENDE") {
    const share = titularShare(info?.p_titular);
    if (share !== null) bits.push(`Titular ${Math.round(share * 100)}%`);
    if (typeof info?.tu_once_pierde_sin_el === "number") bits.push(`Impacto XI: −${points(Math.abs(info.tu_once_pierde_sin_el))} pts`);
    if (info?.prevision_7d_pct) bits.push(`Previsión 7d: ${info.prevision_7d_pct}`);
  } else if (kind === "CLAUSULAZO") {
    if (info?.owner) bits.push(`De: ${info.owner}`);
    if (typeof info?.valor_justo === "number") {
      bits.push(`Valor justo: ${eurShort(info.valor_justo)}`);
      if (amount) {
        const margin = (info.valor_justo / amount - 1) * 100;
        bits.push(`Margen ${margin >= 0 ? "+" : "−"}${Math.abs(Math.round(margin))}%`);
      }
    }
  } else if (kind === "PUJA") {
    if (typeof info?.market_value === "number") bits.push(`Valor: ${eurShort(info.market_value)}`);
    const cap = info?.puja_maxima ?? info?.max_bid ?? info?.own_max_bid ?? null;
    if (typeof cap === "number") bits.push(`Puja máx: ${eurShort(cap)}`);
    const rivals = rivalsWithCash(amount);
    if (rivals !== null) bits.push(`${rivals} ${rivals === 1 ? "rival" : "rivales"} con saldo`);
  }
  const preview = bits.length ? bits.join(" · ") : leadLine(move.detail);

  const ceiling = info?.own_ceiling_points ?? info?.af_ceiling_points ?? null;
  const sale = kind === "VENDE";
  return (
    <li className="row-in" style={{ animationDelay: `${index * 30}ms` }}>
      <button
        type="button"
        className="flex w-full items-center justify-between gap-3 px-3.5 py-2.5 text-left transition-colors hover:bg-white/[0.02]"
        onClick={onToggle}
        aria-expanded={open}
      >
        <span className="flex min-w-0 items-center gap-3">
          <PlayerAvatar
            player={{ name, image_url: move.imageUrl }}
            size="sm"
            className="!h-9 !w-9 !text-[10px] !ring-0 border border-white/[0.12]"
          />
          <span className="min-w-0">
            <span className="flex items-center gap-1.5">
              <span className="truncate text-sm font-medium text-white">{kind === "BUSCA" ? `Buscar ${name}` : name}</span>
              {move.position && kind !== "BUSCA" ? (
                <span className="shrink-0 text-[10px] uppercase text-[#8B9EB0]">{move.position.slice(0, 3)}</span>
              ) : null}
              <span className={`shrink-0 rounded px-1.5 py-0.5 font-mono text-[10px] uppercase ${style.className}`}>{style.label}</span>
              {later ? <span className="shrink-0 text-[10px] text-[#4B6075]">luego</span> : null}
            </span>
            {preview && !open ? <span className="mt-0.5 block truncate text-[11px] text-[#8B9EB0]">{preview}</span> : null}
          </span>
        </span>
        <span className="shrink-0 text-right font-mono tabular-nums">
          {move.cashLabel ? (
            <span className={`block text-[13px] font-semibold ${sale ? "text-[#10B981]" : "text-[#F0F6FC]"}`}>
              {sale ? "+" : ""}
              {move.cashLabel}
            </span>
          ) : null}
          {move.pointsLabel ? (
            <span className="block text-[11px] text-[#0297DE]">
              {move.pointsLabel}
              {typeof ceiling === "number" && ceiling > 10 ? <span className="ml-1 text-[#FC734D]">Techo {points(ceiling)}</span> : null}
            </span>
          ) : null}
        </span>
      </button>
      {open ? (
        <div className="border-t border-white/[0.05] bg-white/[0.015] px-3.5 py-3 pl-[3.6rem]">
          {bits.length ? <p className="mb-1.5 text-[11.5px] leading-4 text-[#8B9EB0]">{bits.join(" · ")}</p> : null}
          {move.detail ? <p className="text-[12.5px] leading-5 text-[#C5D4E2]">{move.detail}</p> : null}
          <Link href={move.href} className="mt-2 inline-flex text-xs font-medium text-[#0297DE]">
            Ver en {move.guide} →
          </Link>
        </div>
      ) : null}
    </li>
  );
}
