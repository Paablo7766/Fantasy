"use client";

import { useMemo, useState } from "react";
import { gradeColor } from "@/components/mercado/MarketGrade";
import { PlayerCard } from "@/components/mercado/PlayerCard";
import { ACTION_VERDICT, auctionLabel, budgetLine, difficultyLabel, historyLine } from "@/components/mercado/shared";
import { Disclosure, Empty, Face, HeroStat, SectionHead, Skeleton, TONE, compact, money, parsePct, signedMoney, signedPct, toneOf } from "@/components/ui/kit";
import { photoFor, type PhotoIndex } from "@/lib/core/photoIndex";
import { errorMessage, playerName } from "@/lib/core/format";
import { executableBid, marketAction } from "@/lib/mercado/marketAction";
import type { AlertaClausula, CatalogPlayer, JornadaClub, MarketDecision, PlanFichajeAccion, PlanFichajes, TrendsPayload } from "@/lib/types";

type Source = "liga" | "rival" | "todos";

const SOURCES: { id: Source; label: string; empty: string }[] = [
  { id: "liga", label: "Liga", empty: "La liga no ofrece jugadores ahora mismo." },
  { id: "rival", label: "Rivales", empty: "Ningún rival vende jugadores ahora mismo." },
  { id: "todos", label: "Combinado", empty: "No hay jugadores en venta." },
];

const PLAN_TONE: Record<string, string> = {
  "Hazlo ya": TONE.green,
  Recomendable: TONE.blue,
  Opcional: TONE.gray,
};

const TIPO_TONE: Record<string, string> = {
  PUJA: TONE.green,
  CLAUSULAZO: TONE.copper,
  VENDE: TONE.red,
  "VENDER HOY": TONE.red,
  ESCAPARATE: TONE.blue,
  BUSCA: TONE.amber,
};

function decimal(value: number, digits = 1): string {
  return value.toLocaleString("es-ES", { maximumFractionDigits: digits });
}

/** Tesela del mercado: foto, nota, precio, tendencia y veredicto de un vistazo. */
function Tile({ player, photo, index, onOpen }: { player: MarketDecision; photo: string | null; index: number; onOpen: () => void }) {
  const name = playerName(player);
  const action = marketAction(player);
  const verdict = ACTION_VERDICT[action];
  const bid = executableBid(player);
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
            <span className="absolute left-2.5 top-2.5 rounded-full bg-[#F59E0B]/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[#F59E0B]">
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
        </span>
        <span className="mt-auto flex items-end justify-between gap-2 border-t border-white/[0.06] px-3 py-2.5">
          <span className="min-w-0">
            <span className="block text-[10.5px] text-white/40">{typeof bid === "number" ? (heat ? "Tu tope" : "Puja") : "Valor"}</span>
            <span className="block truncate text-[15px] font-semibold tabular-nums text-white">{money(typeof bid === "number" ? bid : player.market_value ?? player.sale_price)}</span>
          </span>
          <span className="shrink-0 text-right">
            <span className="block text-[10.5px] tabular-nums text-white/40">{typeof xp === "number" ? `${decimal(xp)} pts` : ""}</span>
            <span className="block text-[12.5px] font-semibold tabular-nums" style={{ color: toneOf(trend) }}>
              {trend === null ? "—" : `${trend >= 0 ? "↗" : "↘"} ${signedPct(trend)}`}
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

function PlanRow({ accion }: { accion: PlanFichajeAccion }) {
  const tipo = accion.tipo || "PUJA";
  const color = TIPO_TONE[tipo] || TONE.gray;
  const hoy = accion.momento === "hoy";
  return (
    <li className="flex items-center gap-3 border-b border-white/[0.06] py-2.5 last:border-b-0">
      <span className="w-[5.5rem] shrink-0 text-[11px] font-semibold uppercase tracking-wide" style={{ color }}>
        {tipo}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[14.5px] font-medium text-white">{accion.nombre || "Jugador"}</span>
        <span className="block truncate text-[12px] tabular-nums text-white/45">
          {[
            accion.posicion,
            typeof accion.jornada === "number" ? `${decimal(accion.jornada)} pts` : "",
            typeof accion.mejora_neta === "number" ? `${accion.mejora_neta > 0 ? "+" : ""}${decimal(accion.mejora_neta)} xP netos` : "",
          ]
            .filter(Boolean)
            .join(" · ")}
        </span>
      </span>
      <span className="shrink-0 text-right">
        {typeof accion.euros === "number" ? <span className="block text-[14.5px] font-semibold tabular-nums text-white">{money(accion.euros)}</span> : null}
        <span className={`block text-[11px] font-semibold uppercase tracking-wide ${hoy ? "text-[#FFC08A]" : "text-white/35"}`}>
          {hoy ? "hoy" : accion.momento === "radar" ? "radar" : accion.momento === "condicional" ? "condicional" : "luego"}
        </span>
      </span>
    </li>
  );
}

function AlertaRow({ alerta }: { alerta: AlertaClausula }) {
  const tone = alerta.tono === "verde" ? TONE.green : TONE.red;
  return (
    <li className="border-b border-white/[0.06] py-2.5 last:border-b-0">
      <p className="text-[13.5px] leading-snug" style={{ color: tone }}>
        {alerta.mensaje}
      </p>
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
      title="Escudo y francotirador"
      meta={
        <span>
          {rojas ? <span style={{ color: TONE.red }}>{rojas} en riesgo</span> : null}
          {rojas && verdes ? <span className="text-white/35"> · </span> : null}
          {verdes ? <span style={{ color: TONE.green }}>{verdes} a tiro</span> : null}
        </span>
      }
    >
      <ul>
        {alertas.map((alerta, index) => (
          <AlertaRow key={`${alerta.tipo}-${alerta.player_id || alerta.nombre}-${index}`} alerta={alerta} />
        ))}
      </ul>
    </Disclosure>
  );
}

function PlanBlock({ plan }: { plan: PlanFichajes | null | undefined }) {
  const acciones = Array.isArray(plan?.acciones) ? plan.acciones : [];
  const radar = Array.isArray(plan?.en_radar) ? plan.en_radar : [];
  const veredicto = plan?.veredicto || "Opcional";
  const gain = plan?.mejora_puntos_jornada;
  return (
    <Disclosure title="Tu plan de fichajes" meta={<span style={{ color: PLAN_TONE[veredicto] || TONE.gray }}>{veredicto}</span>}>
      <div className="grid grid-cols-3 gap-2">
        <HeroStat value={typeof gain === "number" && gain > 0 ? `+${decimal(gain)}` : "0"} label="pts en el once" tone={typeof gain === "number" && gain > 0 ? TONE.green : undefined} />
        <HeroStat value={`${plan?.nota ?? 0}/10`} label="nota del plan" tone="#FFC08A" />
        <HeroStat value={compact(plan?.saldo_al_final)} label="saldo al final" tone={toneOf(plan?.saldo_al_final)} />
      </div>
      {acciones.length ? (
        <ul className="mt-3">
          {acciones.map((accion, index) => (
            <PlanRow key={`${accion.tipo}-${accion.player_id || accion.nombre}-${index}`} accion={accion} />
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-[13.5px] text-white/50">Hoy el mercado no mejora el once. Ninguna operación merece la caja.</p>
      )}
      {radar.length ? (
        <div className="mt-3 border-t border-white/[0.06] pt-3">
          <p className="text-[12px] font-medium text-white/45">En el radar · no pujar hoy</p>
          <ul className="mt-1">
            {radar.map((accion, index) => (
              <PlanRow key={`radar-${accion.player_id || accion.nombre}-${index}`} accion={accion} />
            ))}
          </ul>
        </div>
      ) : null}
    </Disclosure>
  );
}

function TradingBlock({ plan }: { plan: PlanFichajes | null | undefined }) {
  const trading = plan?.trading;
  const operaciones = Array.isArray(trading?.operaciones) ? trading.operaciones : [];
  if (!trading?.activo || !operaciones.length) return null;
  return (
    <Disclosure
      title="Operaciones especulativas"
      meta={<span style={{ color: TONE.green }}>{`+${compact(trading.ganancia_esperada)} esperados`}</span>}
    >
      <p className="text-[12.5px] text-white/50">
        No tocan tu once. Compra hoy y vende el viernes por la mañana, antes del cierre.
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
                {[typeof op.pct === "number" ? `+${decimal(op.pct)}% a 7 días` : "", op.cierre].filter(Boolean).join(" · ")}
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

const FASE_TEXTO: Record<string, { title: string; text: string; color: string }> = {
  APALANCAMIENTO: {
    title: "Apalancamiento",
    text: "Quedan 3 días o más. Los que no entran en el once son posiciones de trading: se mantienen salvo que la oferta pague el valor.",
    color: TONE.green,
  },
  ESCAPARATE: {
    title: "Escaparate",
    text: "Ponlos a la venta hoy. La oferta de LaLiga cambia cada día (valor ±10 %): se acepta la que pague el valor.",
    color: TONE.copper,
  },
  LIQUIDACION: {
    title: "Liquidación",
    text: "Último día. Vende con la oferta que haya: deja 11 y el saldo en positivo antes del primer partido.",
    color: TONE.red,
  },
};

function LiquidacionBlock({ plan }: { plan: PlanFichajes | null | undefined }) {
  const liq = plan?.liquidacion;
  const sobrantes = Array.isArray(liq?.sobrantes) ? liq.sobrantes : [];
  if (!liq?.activo || !sobrantes.length || !liq.fase) return null;
  const fase = FASE_TEXTO[liq.fase] ?? { title: liq.fase, text: "", color: TONE.gray };
  return (
    <Disclosure
      title={`Salida del #12 en adelante · ${fase.title}`}
      meta={<span style={{ color: fase.color }}>{`${sobrantes.length} fuera del once`}</span>}
    >
      <p className="text-[12.5px] text-white/50">
        {fase.text}
        {typeof liq.saldo_tras_liquidar === "number" ? ` Vendiéndolos todos acabas con ${money(liq.saldo_tras_liquidar)}` : ""}
        {typeof liq.saldo_peor_caso === "number" && money(liq.saldo_peor_caso) !== money(liq.saldo_tras_liquidar)
          ? ` (${money(liq.saldo_peor_caso)} si LaLiga paga un 10 % menos).`
          : typeof liq.saldo_tras_liquidar === "number"
            ? "."
            : ""}
        {typeof liq.deficit_eur === "number" && liq.deficit_eur > 0
          ? ` Aun así faltan ${compact(liq.deficit_eur)}: habrá que vender a alguien del once.`
          : ""}
      </p>
      <ul className="mt-2">
        {sobrantes.map((item, index) => (
          <li key={`liq-${item.player_id || item.nombre}-${index}`} className="flex items-center gap-3 border-b border-white/[0.06] py-2.5 last:border-b-0">
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[14.5px] font-medium text-white">
                {[item.nombre || "Jugador", item.position].filter(Boolean).join(" · ")}
              </span>
              <span className="block text-[12px] text-white/45">{item.etiqueta || item.motivo}</span>
            </span>
            <span className="shrink-0 text-right">
              <span className="block text-[11px] font-semibold uppercase tracking-wider" style={{ color: fase.color }}>
                {item.accion}
              </span>
              {typeof item.oferta_eur === "number" ? (
                <span className="block text-[13px] tabular-nums text-white">{`Oferta ${money(item.oferta_eur)}`}</span>
              ) : typeof item.valor === "number" ? (
                <span className="block text-[13px] tabular-nums text-white/60">{`Valor ${money(item.valor)}`}</span>
              ) : null}
            </span>
          </li>
        ))}
      </ul>
    </Disclosure>
  );
}

function FixtureList({ clubs }: { clubs: JornadaClub[] }) {
  if (!clubs.length) return <p className="text-[13.5px] text-white/50">Estos fichajes no traen calendario contrastado.</p>;
  return (
    <ul>
      {clubs.map((club) => {
        const share = typeof club.recommendation_pct === "number" ? club.recommendation_pct : null;
        const color = share === null ? TONE.gray : share >= 72 ? TONE.green : share <= 38 ? TONE.red : TONE.amber;
        const home = club.is_home === true ? "casa" : club.is_home === false ? "fuera" : "";
        return (
          <li key={club.club || club.opponent || "club"} className="flex items-center gap-3 border-b border-white/[0.06] py-2.5 last:border-b-0">
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[14.5px] font-medium text-white">{club.club}</span>
              <span className="block truncate text-[12px] text-white/45">
                {[home, `vs ${club.opponent || "s/d"}`, club.predicted_score, difficultyLabel(club.difficulty)].filter(Boolean).join(" · ")}
              </span>
            </span>
            <span className="shrink-0 text-right">
              <span className="block text-[15px] font-semibold tabular-nums" style={{ color }}>
                {share === null ? "s/d" : `${Math.round(share)}%`}
              </span>
              <span className="block text-[11.5px] text-white/40">{club.market_count} en mercado</span>
            </span>
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
  const budget = budgetLine(summary);
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
          <HeroStat value={summary.day_budget_eur != null ? compact(summary.day_budget_eur) : "—"} label="Tope hoy" tone="#FFC08A" />
          <HeroStat value={summary.plan_cash_after_eur != null ? compact(summary.plan_cash_after_eur) : "—"} label="Te queda" tone={toneOf(summary.plan_cash_after_eur)} />
        </div>
      </section>

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
              <Tile key={String(player.player_id)} player={player} photo={photo(player)} index={index} onOpen={() => setSelectedId(String(player.player_id))} />
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
      <PlanBlock plan={trends.plan_fichajes} />
      <TradingBlock plan={trends.plan_fichajes} />
      <LiquidacionBlock plan={trends.plan_fichajes} />

      <Disclosure title="Calendario de estos fichajes" meta={`${board.length} equipos`}>
        <FixtureList clubs={board} />
      </Disclosure>

      <p className="px-1 text-[12px] leading-relaxed text-white/40">{historyLine(summary)}</p>

      <PlayerCard player={selected} photo={selected ? photo(selected) : null} onClose={() => setSelectedId(null)} />
    </div>
  );
}
