"use client";

import { useMemo, useState } from "react";
import { gradeColor } from "@/components/mercado/MarketGrade";
import { PlayerCard } from "@/components/mercado/PlayerCard";
import { GuardarrailRuina, PlanGuardarrailNota } from "@/components/mercado/GuardarrailRuina";
import { LiquidacionBlock, ParonBlock, PlanBlock } from "@/components/mercado/PlanSections";
import { ACTION_VERDICT, auctionLabel, budgetLine, difficultyLabel, historyLine } from "@/components/mercado/shared";
import { Disclosure, Empty, Face, HeroStat, SectionHead, Skeleton, TONE, cleanText, compact, money, parsePct, projected7d, signedMoney, signedPct, toneOf } from "@/components/ui/kit";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { photoFor, type PhotoIndex } from "@/lib/core/photoIndex";
import { errorMessage, playerName } from "@/lib/core/format";
import { executableBid, marketAction, planBids } from "@/lib/mercado/marketAction";
import { Crest } from "@/components/ui/Crest";
import type { AlertaClausula, CatalogPlayer, JornadaClub, MarketDecision, PlanFichajes, TrendsPayload } from "@/lib/types";

type Source = "liga" | "rival" | "todos";

const SOURCES: { id: Source; label: string; empty: string }[] = [
  { id: "liga", label: "Liga", empty: "La liga no ofrece jugadores ahora mismo." },
  { id: "rival", label: "Rivales", empty: "Ningún rival vende jugadores ahora mismo." },
  { id: "todos", label: "Combinado", empty: "No hay jugadores en venta." },
];

function decimal(value: number, digits = 1): string {
  return value.toLocaleString("es-ES", { maximumFractionDigits: digits });
}

/** Tesela del mercado: foto, nota, precio, tendencia y veredicto de un vistazo. */
function Tile({ player, photo, index, planBid, onOpen }: { player: MarketDecision; photo: string | null; index: number; planBid: number | null; onOpen: () => void }) {
  const name = playerName(player);
  const action = marketAction(player);
  const verdict = ACTION_VERDICT[action];
  // Una sola puja por jugador: la del plan si es objetivo; si no, la del motor; si no, la ideal del tramo.
  const tramoIdeal = typeof player.puja_tramo?.ideal_eur === "number" ? player.puja_tramo.ideal_eur : null;
  const bid = planBid ?? (action === "PUJAR" ? executableBid(player) : null) ?? tramoIdeal;
  const bidLabel = planBid !== null ? "Puja del plan" : bid !== null ? (action === "PUJAR" ? "Puja" : "Puja ideal") : "Valor";
  const trend = parsePct(player.prevision_7d_pct);
  const note = typeof player.nota_mercado === "number" ? player.nota_mercado : null;
  const accent = note === null ? TONE.gray : gradeColor(note);
  const xp = typeof player.jornada_ev === "number" ? player.jornada_ev : player.expected_points;
  const heat = auctionLabel(player);
  return (
    <li className="row-in" style={{ animationDelay: `${Math.min(index, 16) * 25}ms` }}>
      <button type="button" onClick={onOpen} aria-label={`Ver ficha de ${name}`} className="mk-tile h-full w-full">
        <span
          className="relative flex flex-col items-center px-3 pb-3 pt-4"
          style={{ background: `radial-gradient(90% 80% at 50% 0%, ${accent}33, transparent 70%)` }}
        >
          {note !== null ? (
            <span
              className="absolute right-2.5 top-2.5 grid h-8 min-w-8 place-items-center rounded-full px-1.5 text-[12.5px] font-semibold tabular-nums"
              style={{ color: accent, background: `${accent}22`, boxShadow: `inset 0 0 0 1px ${accent}77` }}
            >
              {decimal(note)}
            </span>
          ) : null}
          {player.offer_source === "rival" ? (
            <span className="absolute left-2.5 top-2.5 rounded-full bg-[#F59E0B]/15 px-2 py-0.5 text-[10.5px] font-semibold text-[#F59E0B]">
              Rival
            </span>
          ) : null}
          <Face name={name} src={photo} size={68} ring={action === "PUJAR" ? TONE.green : undefined} />
          <span className="mt-2 block w-full truncate text-center text-[14.5px] font-semibold text-white">{name}</span>
          <span className="block w-full truncate text-center text-[11.5px] text-white/45">
            {[player.position, player.club].filter(Boolean).join(" · ")}
          </span>
          {heat ? (
            <span className="mt-1.5 inline-flex items-center rounded-full bg-[#F59E0B]/15 px-2 py-0.5 text-[10.5px] font-semibold text-[#F59E0B]">
              {heat}
            </span>
          ) : null}
          <StatusBadge status={player.official_status || player.player_status} />
        </span>
        <span className="mt-auto flex items-end justify-between gap-2 border-t border-white/[0.06] px-3 py-2.5">
          <span className="min-w-0">
            <span className="block text-[10.5px] text-white/40">{bidLabel}</span>
            <span className="block truncate text-[15px] font-semibold tabular-nums text-white">{money(bid ?? player.market_value ?? player.sale_price)}</span>
          </span>
          <span className="shrink-0 text-right">
            <span className="block text-[10.5px] tabular-nums text-white/40">{typeof xp === "number" ? `${decimal(xp)} pts` : ""}</span>
            <span className="block text-[12.5px] font-semibold tabular-nums" style={{ color: toneOf(trend) }}>
              {trend === null ? "—" : signedPct(trend)}
            </span>
          </span>
        </span>
        <span className="flex items-center justify-center gap-1.5 py-1.5 text-[11.5px] font-semibold" style={{ color: verdict.color, background: `${verdict.color}14` }}>
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: verdict.color }} aria-hidden="true" />
          {verdict.label}
        </span>
      </button>
    </li>
  );
}

function AlertaRow({ alerta }: { alerta: AlertaClausula }) {
  const defend = alerta.tono !== "verde";
  const tone = defend ? TONE.red : TONE.green;
  return (
    <li className="flex items-start gap-3 py-2.5">
      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full" style={{ color: tone, background: `${tone}1c` }} aria-hidden="true">
        {defend ? (
          <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.7">
            <path d="M10 2.5 4 5v4.5c0 3.6 2.5 6.6 6 8 3.5-1.4 6-4.4 6-8V5l-6-2.5Z" strokeLinejoin="round" />
          </svg>
        ) : (
          <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.7">
            <circle cx="10" cy="10" r="6.5" />
            <circle cx="10" cy="10" r="2.5" />
          </svg>
        )}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[13px] font-semibold" style={{ color: tone }}>
          {defend ? `Protege a ${alerta.nombre || "tu jugador"}` : `Oportunidad: ${alerta.nombre || "jugador"}`}
        </span>
        <span className="mt-0.5 block text-[13px] leading-snug text-white/65">{cleanText(alerta.mensaje)}</span>
      </span>
    </li>
  );
}

function AlertasClausulaBlock({ plan }: { plan: PlanFichajes | null | undefined }) {
  const alertas = Array.isArray(plan?.alertas_clausulas) ? plan.alertas_clausulas : [];
  if (!alertas.length) return null;
  const rojas = alertas.filter((alerta) => alerta.tono === "rojo").length;
  const verdes = alertas.length - rojas;
  return (
    <Disclosure
      title="Cláusulas"
      meta={
        <span>
          {rojas ? <span style={{ color: TONE.red }}>{rojas} {rojas === 1 ? "riesgo" : "riesgos"}</span> : null}
          {rojas && verdes ? <span className="text-white/35"> · </span> : null}
          {verdes ? <span style={{ color: TONE.green }}>{verdes} {verdes === 1 ? "oportunidad" : "oportunidades"}</span> : null}
        </span>
      }
    >
      <ul className="divide-y divide-white/[0.05]">
        {alertas.map((alerta, index) => (
          <AlertaRow key={`${alerta.tipo}-${alerta.player_id || alerta.nombre}-${index}`} alerta={alerta} />
        ))}
      </ul>
    </Disclosure>
  );
}

function TradingBlock({ plan }: { plan: PlanFichajes | null | undefined }) {
  const trading = plan?.trading;
  const operaciones = Array.isArray(trading?.operaciones) ? trading.operaciones : [];
  if (!trading?.activo || !operaciones.length) return null;
  return (
    <Disclosure
      title="Compra para revender"
      meta={<span style={{ color: TONE.green }}>{`+${compact(trading.ganancia_esperada)} esperados`}</span>}
    >
      <p className="text-[12.5px] text-white/50">
        No tocan tu once: compras hoy y vendes el viernes por la mañana, antes del cierre.
        {typeof trading.usa_deuda === "number" && trading.usa_deuda > 0
          ? ` Usan ${compact(trading.usa_deuda)} de deuda: el viernes tienes que acabar en positivo.`
          : ""}
      </p>
      <ul className="mt-2">
        {operaciones.map((op, index) => (
          <li key={`trading-${op.player_id || op.nombre}-${index}`} className="flex items-center gap-3 border-b border-white/[0.06] py-2.5 last:border-b-0">
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[14.5px] font-medium text-white">{op.nombre || "Jugador"}</span>
              <span className="block truncate text-[12px] tabular-nums text-white/45">
                {[typeof op.pct === "number" ? `${typeof op.euros === "number" ? `vendes ~${money(projected7d(op.euros, op.pct))} · ` : ""}+${decimal(op.pct)}% a 7 días` : "", op.cierre].filter(Boolean).join(" · ")}
              </span>
            </span>
            <span className="shrink-0 text-right">
              {typeof op.euros === "number" ? <span className="block text-[14.5px] font-semibold tabular-nums text-white">{money(op.euros)}</span> : null}
              <span className="block text-[11px] font-semibold tabular-nums text-[#7FE0A8]">{`+${compact(op.ganancia_esperada)}`}</span>
            </span>
          </li>
        ))}
      </ul>
    </Disclosure>
  );
}

function FixtureList({ clubs }: { clubs: JornadaClub[] }) {
  return (
    <ul className="divide-y divide-white/[0.05]">
      {clubs.map((club) => {
        const share = typeof club.recommendation_pct === "number" ? club.recommendation_pct : null;
        const color = share === null ? TONE.gray : share >= 72 ? TONE.green : share <= 38 ? TONE.red : TONE.amber;
        const diff = difficultyLabel(club.difficulty);
        return (
          <li key={club.club || club.opponent || "club"} className="py-3">
            <div className="flex items-center gap-3">
              <Crest club={club.club} size={28} />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[14.5px] font-medium text-white">{club.club}</span>
                <span className="flex items-center gap-1.5 truncate text-[12px] text-white/45">
                  {club.is_home === true ? "En casa" : club.is_home === false ? "Fuera" : "Partido"} contra <Crest club={club.opponent} size={14} />{club.opponent || "—"}
                  {club.predicted_score ? ` · ${club.predicted_score}` : ""}
                  {diff ? ` · ${diff.charAt(0).toUpperCase()}${diff.slice(1)}` : ""}
                </span>
              </span>
              <span className="shrink-0 text-right">
                <span className="block text-[15px] font-semibold tabular-nums" style={{ color }}>
                  {share === null ? "—" : `${Math.round(share)}%`}
                </span>
                <span className="block text-[11px] text-white/40">
                  {club.market_count} en venta
                </span>
              </span>
            </div>
            {share !== null ? (
              <span className="mt-2 block h-1 overflow-hidden rounded-full bg-white/[0.06]">
                <span className="block h-full rounded-full" style={{ width: `${Math.max(4, Math.min(100, share))}%`, background: color }} />
              </span>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

const OWNER_TAG: Record<string, { label: string; color: string }> = {
  libre: { label: "Libre", color: TONE.green },
  rival: { label: "De un rival", color: TONE.amber },
  propio: { label: "Tuyo", color: TONE.blue },
};

/** Jugadores que coinciden con la búsqueda pero no están en venta hoy. */
function CatalogMatches({ rows, photos }: { rows: CatalogPlayer[]; photos: PhotoIndex }) {
  if (!rows.length) return null;
  return (
    <section className="flex flex-col gap-3" aria-label="Fuera del mercado">
      <SectionHead title="Fuera del mercado" meta={`${rows.length}`} />
      <ul className="home-glass overflow-hidden">
        {rows.map((player, index) => {
          const name = playerName(player);
          const tag = OWNER_TAG[player.owner || "libre"] || OWNER_TAG.libre;
          const forecast = (player.price_points?.length ?? 0) >= 3 ? player.own_predicted_delta : null;
          return (
            <li key={String(player.player_id)} className="row-in" style={{ animationDelay: `${Math.min(index, 10) * 25}ms` }}>
              <span className="flex min-h-[3.75rem] items-center gap-3 px-3.5 py-2.5">
                <Face name={name} src={player.image_url || photoFor(photos, String(player.player_id), name)} size={40} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[14.5px] font-medium text-white">{name}</span>
                  <span className="block truncate text-[12px] text-white/45">
                    {[player.position, player.club].filter(Boolean).join(" · ")}
                    <span style={{ color: tag.color }}> · {tag.label}</span>
                  </span>
                </span>
                <span className="shrink-0 text-right">
                  <span className="block text-[14.5px] font-semibold tabular-nums text-white">{money(player.market_value)}</span>
                  <span className="block text-[12px] tabular-nums" style={{ color: toneOf(forecast) }}>
                    {typeof forecast === "number" ? `${signedMoney(forecast)} hoy` : ""}
                  </span>
                </span>
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export function HoyTab({ trends, photos, loading }: { trends: TrendsPayload | null; photos: PhotoIndex; loading: boolean }) {
  const [source, setSource] = useState<Source>("liga");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const decisions = useMemo(() => {
    if (!trends || trends.ok === false) return [] as MarketDecision[];
    const rows = Array.isArray(trends.market_decisions) ? trends.market_decisions : [];
    // Tus propias ventas no se compran: solo liga y rivales, de mejor a peor nota.
    return rows
      .filter((row) => (row.offer_source || "liga") !== "propio")
      .sort((a, b) => (b.nota_mercado ?? -1) - (a.nota_mercado ?? -1));
  }, [trends]);

  const outside = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (needle.length < 2 || !trends || trends.ok === false) return [] as CatalogPlayer[];
    const onSale = new Set(decisions.map((row) => String(row.player_id)));
    const catalog = Array.isArray(trends.catalog) ? trends.catalog : [];
    return catalog
      .filter((player) => !onSale.has(String(player.player_id)))
      .filter((player) => `${player.nickname || ""} ${player.name || ""} ${player.club || ""}`.toLowerCase().includes(needle))
      .sort((a, b) => (b.market_value ?? 0) - (a.market_value ?? 0))
      .slice(0, 12);
  }, [decisions, query, trends]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return decisions.filter((row) => {
      if (source !== "todos" && (row.offer_source || "liga") !== source) return false;
      if (!needle) return true;
      return `${row.nickname || ""} ${row.name || ""} ${row.club || ""}`.toLowerCase().includes(needle);
    });
  }, [decisions, source, query]);

  if (loading && (!trends || trends.ok === false)) return <Skeleton />;
  if (!trends || trends.ok === false) {
    return <Empty title="Sin lectura de mercado" detail={trends ? errorMessage(trends) : "Pulsa Actualizar para leer el mercado de tu liga."} />;
  }

  const summary = trends.market_decision_summary || {};
  const photo = (player: MarketDecision) => player.image_url || photoFor(photos, String(player.player_id), playerName(player));
  const board = (Array.isArray(trends.jornada_board) ? trends.jornada_board : []).filter((club) => (club.market_count ?? 0) > 0);
  const counts: Record<Source, number> = {
    liga: decisions.filter((row) => (row.offer_source || "liga") === "liga").length,
    rival: decisions.filter((row) => row.offer_source === "rival").length,
    todos: decisions.length,
  };
  const pujar = decisions.filter((row) => marketAction(row) === "PUJAR").length;
  const empty = SOURCES.find((item) => item.id === source)?.empty || "";
  // Con plan de fichajes, la cabecera habla con su voz: lo que invierte y con qué lo paga.
  const fichajes = trends.plan_fichajes ?? null;
  const presupuesto = fichajes?.presupuesto ?? null;
  const gastoPlan = presupuesto ? presupuesto.gasto_pujas + presupuesto.gasto_clausulas : 0;
  const saldoFinal = typeof fichajes?.saldo_al_final === "number" ? fichajes.saldo_al_final : null;
  const creditoPlan = Math.max(presupuesto?.credito_paron ?? 0, saldoFinal !== null && saldoFinal < 0 ? -saldoFinal : 0);
  const budget =
    gastoPlan > 0
      ? `El plan invierte ${compact(gastoPlan)}${creditoPlan > 0 ? `, ${compact(creditoPlan)} con el crédito del 20 % (la puja admite deuda; vende antes del ${fichajes?.paron?.ruta_salida?.dia_venta || "saque"})` : " con tu caja"}.`
      : budgetLine(summary);
  const bids = planBids(fichajes);
  const selected = decisions.find((row) => String(row.player_id) === selectedId) || null;

  return (
    <div className="flex flex-col gap-5">
      <section className="home-feature" aria-label="Resumen del mercado">
        <div className="relative flex items-center justify-between gap-3">
          <p className="text-[13px] font-medium text-white/60">Mercado de hoy</p>
          <p className="text-[12px] tabular-nums text-white/45">{decisions.length} en venta</p>
        </div>
        <p className="relative mt-2 flex items-baseline gap-2 tabular-nums">
          <span className="text-[3rem] font-semibold leading-none tracking-[-0.045em] text-white">{pujar}</span>
          <span className="text-base font-medium text-white/60">{pujar === 1 ? "puja recomendada" : "pujas recomendadas"}</span>
        </p>
        {budget ? <p className="relative mt-2 text-[13px] leading-snug text-white/55">{budget}</p> : null}
        <div className="relative mt-5 grid grid-cols-3 gap-2.5">
          <HeroStat value={compact(summary.cash_eur ?? trends.cash_eur)} label="Caja" />
          {gastoPlan > 0 ? (
            <>
              <HeroStat value={compact(gastoPlan)} label="Invierte el plan" tone="#FFC08A" />
              <HeroStat value={saldoFinal !== null ? compact(saldoFinal) : "—"} label="Saldo tras el plan" tone={toneOf(saldoFinal)} />
            </>
          ) : (
            <>
              <HeroStat value={summary.day_budget_eur != null ? compact(summary.day_budget_eur) : "—"} label="Tope hoy" tone="#FFC08A" />
              <HeroStat value={summary.plan_cash_after_eur != null ? compact(summary.plan_cash_after_eur) : "—"} label="Te queda" tone={toneOf(summary.plan_cash_after_eur)} />
            </>
          )}
        </div>
      </section>

      <GuardarrailRuina data={trends.guardarrail_ruina} modo="mercado" />

      <section className="flex flex-col gap-3">
        <div className="desk-switch" role="tablist" aria-label="Quién vende">
          {SOURCES.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={source === item.id}
              onClick={() => setSource(item.id)}
              className={source === item.id ? "desk-switch__btn desk-switch__btn--on" : "desk-switch__btn"}
            >
              {item.label}
              <span className="ml-1.5 tabular-nums opacity-60">{counts[item.id]}</span>
            </button>
          ))}
        </div>
        <label className="relative block">
          <span className="sr-only">Buscar jugador o equipo</span>
          <svg viewBox="0 0 20 20" className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-white/35" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <circle cx="9" cy="9" r="5.5" />
            <path d="m13.5 13.5 3 3" strokeLinecap="round" />
          </svg>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Buscar cualquier jugador o equipo"
            className="h-12 w-full rounded-full bg-[#1c1c1e] pl-11 pr-4 text-[14px] text-white outline-none transition-shadow duration-200 placeholder:text-white/35 focus-visible:outline-none focus:shadow-[inset_0_0_0_1px_rgba(255,154,90,0.6)]"
          />
        </label>
        {filtered.length ? (
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {filtered.map((player, index) => (
              <Tile key={String(player.player_id)} player={player} photo={photo(player)} index={index} planBid={bids.get(String(player.player_id)) ?? null} onOpen={() => setSelectedId(String(player.player_id))} />
            ))}
          </ul>
        ) : (
          <p className="px-1 py-6 text-center text-[13.5px] text-white/45">
            {query ? (outside.length ? "Nadie en venta coincide con la búsqueda." : "Nadie coincide con la búsqueda.") : empty}
          </p>
        )}
      </section>

      <CatalogMatches rows={outside} photos={photos} />

      <AlertasClausulaBlock plan={trends.plan_fichajes} />
      <PlanGuardarrailNota plan={trends.plan_fichajes?.guardarrail_ruina} />
      <PlanBlock plan={trends.plan_fichajes} photos={photos} />
      <ParonBlock plan={trends.plan_fichajes} photos={photos} />
      <TradingBlock plan={trends.plan_fichajes} />
      <LiquidacionBlock plan={trends.plan_fichajes} photos={photos} />

      {board.length ? (
        <Disclosure title="Calendario" meta={`${board.length} ${board.length === 1 ? "equipo" : "equipos"}`}>
          <p className="mb-1 text-[12.5px] text-white/45">Próximo partido de cada equipo con jugadores en venta. El porcentaje indica lo favorable que es el partido para sus jugadores (victoria, empate y diferencia de goles esperada).</p>
          <FixtureList clubs={board} />
        </Disclosure>
      ) : null}

      <p className="px-1 text-[12px] leading-relaxed text-white/40">{historyLine(summary)}</p>

      <PlayerCard player={selected} planBid={selected ? (bids.get(String(selected.player_id)) ?? null) : null} photo={selected ? photo(selected) : null} cash={summary.cash_eur ?? trends.cash_eur} fetchedAt={trends.fetched_at} onClose={() => setSelectedId(null)} />
    </div>
  );
}
