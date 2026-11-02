"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { PlayerAvatar } from "@/components/ui/PlayerAvatar";
import { ClauseAdvisor } from "@/components/inicio/ClauseAdvisor";
import { SalesAdvisor } from "@/components/inicio/SalesAdvisor";
import { eurShort, jornadaEv, points, titularShare } from "@/lib/core/format";
import { signedPoints } from "@/lib/inicio/hoy";
import { factsFor, photoFor, type PhotoIndex, type PlayerIndex } from "@/lib/core/photoIndex";
import { buildStrategyViews, type StrategyMove, type StrategyView } from "@/lib/inicio/signingBoard";
import type { NeedsPayload, OptimizePayload, PlanFichajeAccion, PlanPayload, SquadsPayload, TrendsPayload } from "@/lib/types";

type Kind = "PUJA" | "BUSCA" | "VENDE" | "CLAUSULAZO" | "ESCAPARATE";

const KIND_LABEL: Record<Kind, string> = {
  PUJA: "Pujar",
  BUSCA: "Buscar en el mercado",
  VENDE: "Vender hoy",
  CLAUSULAZO: "Cláusula",
  ESCAPARATE: "Poner en escaparate",
};

function kindOf(verb: string): Kind {
  const value = verb.toLowerCase();
  if (value.includes("escaparate")) return "ESCAPARATE";
  if (value.includes("busca") || value.includes("buscar")) return "BUSCA";
  if (value.includes("vend") || value.includes("venta")) return "VENDE";
  if (value.includes("cláus") || value.includes("claus") || value.includes("rival") || value.includes("proteger") || value.includes("subir")) {
    return "CLAUSULAZO";
  }
  return "PUJA";
}

function moveFromAction(action: PlanFichajeAccion, index: number, photos: PhotoIndex): StrategyMove {
  const tipo = (action.tipo || "PUJA").toUpperCase();
  const condicional = action.momento === "condicional";
  const aceptar = (tipo === "VENDE" || tipo === "VENDER HOY") && !condicional;
  const escaparate = tipo === "ESCAPARATE";
  const verb = condicional
    ? "Vender solo si ganas la puja"
    : escaparate
    ? "Poner en escaparate"
    : aceptar
      ? "Vender hoy"
      : tipo === "BUSCA"
        ? "Buscar en el mercado"
        : tipo === "CLAUSULAZO"
          ? "Fichar de un rival"
          : "Pujar en el mercado";
  const amount = typeof action.euros === "number" ? Math.abs(action.euros) : null;
  const jornada = typeof action.jornada === "number" ? action.jornada : null;
  const income = aceptar;
  const impulso = (action.impulso || "").toUpperCase();
  const tag: StrategyMove["tag"] = escaparate
    ? "ESCAPARATE"
    : tipo === "VENDER HOY"
      ? "ACEPTAR"
      : impulso === "MUST-BUY"
        ? "MUST-BUY"
        : impulso === "CHOLLO"
          ? "CHOLLO"
          : null;
  return {
    id: `plan-${tipo}-${action.player_id || action.nombre || index}`,
    playerId: action.player_id || null,
    verb,
    title: tipo === "BUSCA" ? (action.posicion ? `un ${action.posicion}` : "un hueco") : action.nombre || "Jugador",
    position: action.posicion || null,
    imageUrl: photoFor(photos, action.player_id, action.nombre),
    cashImpact: escaparate || condicional || amount === null ? null : income ? amount : -amount,
    cashLabel: escaparate || condicional || amount === null ? null : eurShort(amount),
    cashTone: condicional ? "flat" : income ? "up" : "down",
    pointsImpact: jornada,
    pointsLabel: jornada === null ? null : `${points(jornada)} xP`,
    pointsTone: "flat",
    tag,
    forecastPct: typeof action.prevision_7d_pct === "number" ? action.prevision_7d_pct : null,
    later: action.momento === "luego" || condicional,
    detail: action.detalle || null,
    href: aceptar || escaparate || condicional ? "/equipo?tab=cartera" : tipo === "CLAUSULAZO" ? "/clausulas" : "/mercado",
    guide: aceptar || escaparate || condicional ? "Cartera" : tipo === "CLAUSULAZO" ? "Cláusulas" : "Mercado",
  };
}

const TAG_STYLE: Record<NonNullable<StrategyMove["tag"]>, string> = {
  "MUST-BUY": "bg-[#FF7A3D]/20 text-[#FFB48A]",
  CHOLLO: "bg-[#10B981]/15 text-[#34D399]",
  ACEPTAR: "bg-[#FC734D]/15 text-[#FFA088]",
  ESCAPARATE: "border border-dashed border-[#F59E0B]/70 bg-[#F59E0B]/10 text-[#F5B544]",
};

function pctText(value: number): string {
  return `${value >= 0 ? "+" : "−"}${Math.abs(value).toLocaleString("es-ES", { maximumFractionDigits: 0 })}%`;
}

function tagLabel(move: StrategyMove): string | null {
  if (!move.tag) return null;
  if (move.tag === "CHOLLO") return typeof move.forecastPct === "number" ? `ESPECULAR ${pctText(move.forecastPct)}` : "CHOLLO";
  if (move.tag === "ACEPTAR") return "ACEPTAR OFERTA";
  return move.tag;
}

function Tag({ move }: { move: StrategyMove }) {
  const label = tagLabel(move);
  if (!label || !move.tag) return null;
  return (
    <span className={`inline-flex shrink-0 items-center rounded-md px-1.5 py-0.5 text-[10.5px] font-semibold tracking-wide ${TAG_STYLE[move.tag]}`}>
      {label}
    </span>
  );
}

/** Frase corta de la fila: en escaparate explica por qué se lista y cuándo vender. */
function showcaseNote(move: StrategyMove): string | null {
  if (typeof move.forecastPct === "number" && move.forecastPct > 0) {
    return `Sube ${pctText(move.forecastPct)} · Ponlo en venta hoy para recibir oferta de LaLiga, vende el jueves/viernes`;
  }
  return move.detail;
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
  const radar = useMemo(() => fichajes?.en_radar || [], [fichajes?.en_radar]);
  const audit = useMemo(() => plan?.auditoria_ventas || [], [plan?.auditoria_ventas]);
  const planMoves = useMemo(() => actions.map((action, index) => moveFromAction(action, index, photos)), [actions, photos]);
  const usePlan = desk === "estrategia" && planMoves.length > 0;

  // Pestaña Ventas: lo auditado más las ventas de la vista y del plan que la auditoría no trae.
  // El contador y la lista salen de aquí, así que siempre coinciden.
  const ventasExtra = useMemo(() => {
    const audited = new Set(audit.map((row) => row.player_id));
    const seen = new Set(audit.map((row) => row.nombre.toLowerCase()));
    const fromView = views.find((item) => item.id === "ventas")?.groups.flatMap((group) => group.moves) || [];
    const fromPlan = planMoves.filter((move) => {
      const kind = kindOf(move.verb);
      return kind === "VENDE" || kind === "ESCAPARATE";
    });
    const rows: StrategyMove[] = [];
    for (const move of [...fromView, ...fromPlan]) {
      const key = move.title.toLowerCase();
      if ((move.playerId && audited.has(move.playerId)) || seen.has(key)) continue;
      seen.add(key);
      rows.push(move.imageUrl ? move : { ...move, imageUrl: photoFor(photos, move.playerId, move.title) });
    }
    return rows;
  }, [views, audit, planMoves, photos]);
  const salesCount = audit.length + ventasExtra.length;

  const listed = (desk === "ventas" ? ventasExtra : usePlan ? planMoves : view.groups.flatMap((group) => group.moves)).map((move) =>
    move.imageUrl ? move : { ...move, imageUrl: photoFor(photos, move.playerId, move.title) },
  );

  const sales = listed.filter((move) => kindOf(move.verb) === "VENDE");
  const showcase = listed.filter((move) => kindOf(move.verb) === "ESCAPARATE");
  const buys = listed.filter((move) => {
    const kind = kindOf(move.verb);
    return kind !== "VENDE" && kind !== "ESCAPARATE";
  });
  const laterIds = new Set(
    usePlan
      ? actions
          .map((action, index) => (action.momento === "luego" || action.momento === "condicional" ? planMoves[index].id : null))
          .filter((id): id is string => id !== null)
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

  const advisor = desk === "ventas" && audit.length > 0;
  const clauseData = plan?.asesor_clausulas;
  const clauseCount = (clauseData?.proteger.length ?? 0) + (clauseData?.clausulazos.length ?? 0);
  const clauseAdvisor = desk === "clausulas" && clauseData != null && clauseCount > 0;
  const total = advisor ? salesCount : clauseAdvisor ? clauseCount : sales.length + showcase.length + buys.length;
  const today = [...sales, ...buys].filter((move) => !laterIds.has(move.id));
  const later = [...sales, ...buys].filter((move) => laterIds.has(move.id));

  // Tira del solver: lo que el motor está aplicando hoy al plan.
  const exempt = (move: StrategyMove) => move.tag === "MUST-BUY" || move.tag === "CHOLLO";
  const drain = Math.max(0, buyActions.filter((move) => !exempt(move)).reduce((sum, move) => sum + Math.abs(move.cashImpact || 0), 0) - incomeTotal);
  const dias = fichajes?.dias_al_cierre;
  const peaje = fichajes?.penalizacion_liquidez;
  const solverBits: string[] = [];
  if (desk === "estrategia" && fichajes) {
    if (fichajes.modo_liquidez === "ALL-IN") {
      solverBits.push("Modo all-in", "filtro de liquidez apagado");
    } else if (typeof dias === "number") {
      solverBits.push(`Faltan ${dias.toLocaleString("es-ES", { maximumFractionDigits: 1 })}d`);
      if (typeof peaje === "number") {
        solverBits.push(`Peaje liquidez: ${peaje.toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} pts/M€`);
      }
      if (buyActions.length) solverBits.push(`Drenaje neto: ≈${eurShort(drain)}`);
    }
  }
  const sectioned = usePlan;
  const hasBreakdown = desk === "estrategia" && (cashNow !== null || cashEnd !== null || lineDelta);

  return (
    <div className="desk">
      <div className="px-1">
        <h2 className="truncate text-[1.6rem] font-semibold leading-tight tracking-tight text-white">
          {loading && !plan ? "…" : verdict}
        </h2>
        <p className="mt-1 text-[14px] text-white/50">
          {refreshing ? "Actualizando…" : total ? `${total} ${total === 1 ? "movimiento" : "movimientos"}` : "Sin movimientos"}
        </p>
        {solverBits.length ? (
          <p className="mt-3 inline-flex max-w-full flex-wrap items-center gap-x-2 gap-y-0.5 rounded-2xl border border-white/[0.07] bg-white/[0.04] px-3 py-1.5 text-[12px] tabular-nums text-white/60">
            {solverBits.map((bit, index) => (
              <span key={bit} className="inline-flex items-center gap-2">
                {index > 0 ? <span className="text-white/20" aria-hidden="true">·</span> : null}
                {bit}
              </span>
            ))}
          </p>
        ) : null}
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
              {(item.id === "ventas" ? salesCount : item.id === "clausulas" ? clauseCount : 0) > 0 ? (
                <span className={`ml-1.5 text-[12px] tabular-nums ${active ? "text-[#120C09]/60" : "text-white/35"}`}>
                  {item.id === "ventas" ? salesCount : clauseCount}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>

      {loading && !plan ? (
        <div className="desk-skel" aria-hidden="true" />
      ) : clauseAdvisor && clauseData ? (
        <div key={desk}>
          <ClauseAdvisor data={clauseData} photos={photos} />
        </div>
      ) : advisor ? (
        <div key={desk}>
          <SalesAdvisor rows={audit} summary={plan?.resumen_ventas} photos={photos} />
          {ventasExtra.length ? (
            <div className="mt-6">
              <MoveList
                title="Otras ventas del plan"
                moves={ventasExtra}
                index0={audit.length}
                featured={false}
                openId={openId}
                onToggle={setOpenId}
                facts={facts}
                rivalsWithCash={rivalsWithCash}
              />
            </div>
          ) : null}
        </div>
      ) : total ? (
        <div key={desk} className="flex flex-col gap-6">
          <MoveList
            title={sectioned ? "Ejecutar hoy" : null}
            moves={today}
            index0={0}
            featured
            openId={openId}
            onToggle={setOpenId}
            facts={facts}
            rivalsWithCash={rivalsWithCash}
          />
          <MoveList
            title="Preparar liquidez · escaparate"
            moves={showcase}
            index0={today.length}
            featured={false}
            openId={openId}
            onToggle={setOpenId}
            facts={facts}
            rivalsWithCash={rivalsWithCash}
          />
          <MoveList
            title="Fase 2 · luego"
            moves={later}
            index0={today.length + showcase.length}
            featured={false}
            openId={openId}
            onToggle={setOpenId}
            facts={facts}
            rivalsWithCash={rivalsWithCash}
          />

          {desk === "estrategia" && radar.length ? <RadarList rows={radar} photos={photos} penalty={peaje ?? null} /> : null}

          {hasBreakdown ? (
            <div>
              <button
                type="button"
                onClick={() => setShowBreakdown((value) => !value)}
                aria-expanded={showBreakdown}
                className="flex w-full items-center justify-between px-1 py-1 text-[14px] font-medium text-white/50 transition-colors hover:text-white"
              >
                Desglose del plan
                <Chevron open={showBreakdown} />
              </button>
              {showBreakdown ? (
                <dl className="row-in mt-2 divide-y divide-white/[0.05] home-glass px-4 text-[14px] tabular-nums">
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
      ) : desk === "estrategia" && radar.length ? (
        <RadarList rows={radar} photos={photos} penalty={peaje ?? null} />
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

function RadarList({ rows, photos, penalty }: { rows: PlanFichajeAccion[]; photos: PhotoIndex; penalty: number | null }) {
  const [open, setOpen] = useState(false);
  return (
    <section className="home-glass overflow-hidden" aria-label="En el radar">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-4 py-3.5 text-left"
      >
        <span className="min-w-0">
          <span className="block text-[15px] font-medium text-white">En el radar · No pujar hoy</span>
          <span className="mt-0.5 block text-[13px] text-white/50">
            {rows.length} {rows.length === 1 ? "jugador descartado" : "jugadores descartados"} por el peaje
          </span>
        </span>
        <Chevron open={open} />
      </button>
      {open ? (
        <ul className="row-in divide-y divide-white/[0.06] border-t border-white/[0.06]">
          {rows.map((row, index) => {
            const name = row.nombre || "Jugador";
            const gain = typeof row.mejora_neta === "number" ? row.mejora_neta : null;
            const euros = typeof row.euros === "number" ? row.euros : null;
            const toll = penalty !== null && euros !== null ? (penalty * euros) / 1_000_000 : null;
            const missing = toll !== null && gain !== null ? Math.max(0, toll - gain) : null;
            return (
              <li key={`${row.player_id || name}-${index}`} className="flex items-center gap-3 px-4 py-3">
                <PlayerAvatar
                  player={{ name, image_url: photoFor(photos, row.player_id, name) }}
                  size="sm"
                  className="!h-10 !w-10 !text-[10px] !ring-0"
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[15px] font-medium text-white">{name}</span>
                  <span className="mt-0.5 block text-[12.5px] leading-4 text-white/50">
                    {gain !== null ? `Mejora +${points(gain)} xP` : "En el radar"}
                    {toll !== null ? ` · peaje ≈${points(toll)} pts` : ""}
                  </span>
                </span>
                <span className="shrink-0 text-right">
                  {euros !== null ? <span className="block text-[14px] font-medium tabular-nums text-white">{eurShort(euros)}</span> : null}
                  {missing !== null && missing > 0.04 ? (
                    <span className="block text-[12px] tabular-nums text-[#F5B544]">faltan {points(missing)} pts</span>
                  ) : null}
                </span>
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}

function Chevron({ open, dark }: { open: boolean; dark?: boolean }) {
  return (
    <svg
      viewBox="0 0 16 16"
      className={`h-4 w-4 shrink-0 ${dark ? "text-[#120C09]" : "text-white/35"} transition-transform duration-200 ${open ? "rotate-180" : ""}`}
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
      <dt className="text-white/50">{label}</dt>
      <dd className={`font-medium ${tone || "text-white"}`}>{value}</dd>
    </div>
  );
}

type FactRows = [string, string][];

function factRows(
  kind: Kind,
  move: StrategyMove,
  info: ReturnType<typeof factsFor>,
  rivalsWithCash: (amount: number | null) => number | null,
): FactRows {
  const amount = move.cashImpact === null ? null : Math.abs(move.cashImpact);
  const rows: FactRows = [];
  if (kind === "VENDE" || kind === "ESCAPARATE") {
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
  return rows;
}

type RowProps = {
  move: StrategyMove;
  index: number;
  open: boolean;
  onToggle: () => void;
  facts: PlayerIndex;
  rivalsWithCash: (amount: number | null) => number | null;
};

function Expanded({ rows, move }: { rows: FactRows; move: StrategyMove }) {
  return (
    <div className="row-in">
      {rows.length ? (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
          {rows.map(([label, value]) => (
            <div key={label} className="min-w-0">
              <dt className="truncate text-[12.5px] text-white/50">{label}</dt>
              <dd className="mt-0.5 truncate text-[15px] font-medium tabular-nums text-white">{value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {move.detail ? <p className="mt-3 text-[14px] leading-5 text-white/55">{move.detail}</p> : null}
      <Link href={move.href} className="mt-3 inline-flex text-[14px] font-medium text-[#FF9A5A]">
        Ver en {move.guide} →
      </Link>
    </div>
  );
}

function MoveList({
  title,
  moves,
  index0,
  featured,
  openId,
  onToggle,
  facts,
  rivalsWithCash,
}: {
  title: string | null;
  moves: StrategyMove[];
  index0: number;
  featured: boolean;
  openId: string | null;
  onToggle: (id: string | null) => void;
  facts: PlayerIndex;
  rivalsWithCash: (amount: number | null) => number | null;
}) {
  if (!moves.length) return null;
  const lead = featured ? moves[0] : null;
  const rest = featured ? moves.slice(1) : moves;
  const common = (move: StrategyMove, index: number): RowProps => ({
    move,
    index: index0 + index,
    open: openId === move.id,
    onToggle: () => onToggle(openId === move.id ? null : move.id),
    facts,
    rivalsWithCash,
  });
  return (
    <section aria-label={title || "Movimientos"} className="flex flex-col gap-2.5">
      {title ? <h3 className="px-1 text-[14px] font-medium text-white/50">{title}</h3> : null}
      {lead ? <FeaturedMove {...common(lead, 0)} /> : null}
      {rest.map((move, index) => (
        <MoveCard key={move.id} {...common(move, index + (featured ? 1 : 0))} />
      ))}
    </section>
  );
}

function FeaturedMove({ move, index, open, onToggle, facts, rivalsWithCash }: RowProps) {
  const kind = kindOf(move.verb);
  const info = kind === "BUSCA" ? null : factsFor(facts, move.playerId, move.title);
  const name = kind === "BUSCA" ? move.position || move.title : move.title;
  const sale = kind === "VENDE";
  const rows = factRows(kind, move, info, rivalsWithCash);
  return (
    <article className="home-feature row-in" style={{ animationDelay: `${index * 30}ms` }}>
      <div className="relative flex items-start justify-between gap-4">
        <div className="min-w-0">
          {move.tag ? (
            <Tag move={move} />
          ) : (
            <span className="inline-flex rounded-full bg-[#FF7A3D]/20 px-2.5 py-1 text-[11.5px] font-medium text-[#FFB48A]">Prioridad</span>
          )}
          <h4 className="mt-3 truncate text-[1.65rem] font-semibold leading-tight tracking-tight text-white">
            {kind === "BUSCA" ? `Buscar ${name}` : name}
          </h4>
          <p className="mt-0.5 text-[14px] text-white/55">
            {KIND_LABEL[kind]}
            {move.position && kind !== "BUSCA" ? ` · ${move.position.slice(0, 3).toUpperCase()}` : ""}
          </p>
          {move.cashLabel ? (
            <p className={`mt-3 text-[1.35rem] font-semibold tabular-nums ${sale ? "text-[#34D399]" : "text-white"}`}>
              {sale ? "+" : ""}
              {move.cashLabel}
            </p>
          ) : null}
        </div>
        <span className="shrink-0 rounded-full bg-gradient-to-br from-[#FF9A5A] to-[#FF7A3D]/10 p-[3px] shadow-[0_0_32px_rgba(255,122,61,0.45)]">
          <PlayerAvatar player={{ name, image_url: move.imageUrl }} size="sm" className="!h-[5.25rem] !w-[5.25rem] !text-[18px] !ring-0 border-[3px] border-[#120C09]" />
        </span>
      </div>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="relative mt-4 inline-flex h-10 items-center gap-2 rounded-full bg-white px-5 text-[14px] font-semibold text-[#120C09] transition-transform duration-200 active:scale-95"
      >
        {open ? "Ocultar" : "Ver detalle"}
        <Chevron open={open} dark />
      </button>
      {open ? (
        <div className="relative mt-4 border-t border-white/[0.08] pt-4">
          <Expanded rows={rows} move={move} />
        </div>
      ) : null}
    </article>
  );
}

function MoveCard({ move, index, open, onToggle, facts, rivalsWithCash }: RowProps) {
  const kind = kindOf(move.verb);
  const info = kind === "BUSCA" ? null : factsFor(facts, move.playerId, move.title);
  const name = kind === "BUSCA" ? move.position || move.title : move.title;
  const sale = kind === "VENDE";
  const rows = factRows(kind, move, info, rivalsWithCash);
  return (
    <div className="home-glass row-in" style={{ animationDelay: `${index * 30}ms` }}>
      <button type="button" className="flex w-full items-center gap-3.5 p-3.5 text-left" onClick={onToggle} aria-expanded={open}>
        <span className="shrink-0 rounded-full bg-gradient-to-br from-white/30 to-white/5 p-[2px]">
          <PlayerAvatar player={{ name, image_url: move.imageUrl }} size="sm" className="!h-11 !w-11 !text-[11px] !ring-0 border-2 border-[#120C09]" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[16px] font-medium leading-tight text-white">{kind === "BUSCA" ? `Buscar ${name}` : name}</span>
          {kind === "ESCAPARATE" ? (
            <span className="mt-1 block">
              <Tag move={move} />
              <span className="mt-1.5 block text-[12.5px] leading-4 text-white/50">{showcaseNote(move)}</span>
            </span>
          ) : (
            <span className="mt-0.5 flex items-center gap-1.5 text-[13.5px] text-white/50">
              <Tag move={move} />
              <span className="truncate">
                {KIND_LABEL[kind]}
                {move.position && kind !== "BUSCA" ? ` · ${move.position.slice(0, 3).toUpperCase()}` : ""}
              </span>
            </span>
          )}
        </span>
        <span className={`shrink-0 text-[16px] font-semibold tabular-nums ${sale ? "text-[#34D399]" : "text-white"}`}>
          {move.cashLabel ? `${sale ? "+" : ""}${move.cashLabel}` : ""}
        </span>
        <Chevron open={open} />
      </button>
      {open ? (
        <div className="border-t border-white/[0.06] px-4 pb-4 pt-3.5">
          <Expanded rows={rows} move={move} />
        </div>
      ) : null}
    </div>
  );
}
