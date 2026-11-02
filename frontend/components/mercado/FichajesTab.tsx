"use client";

import { useMemo, useState } from "react";
import { gradeColor } from "@/components/MarketGrade";
import { PlayerCard } from "@/components/mercado/PlayerCard";
import { ACTION_VERDICT, budgetLine, difficultyLabel, historyLine } from "@/components/mercado/shared";
import { Disclosure, Empty, Face, HeroStat, Skeleton, TONE, compact, money, parsePct, signedPct, toneOf } from "@/components/equipo/ui";
import { photoFor, type PhotoIndex } from "@/lib/photoIndex";
import { errorMessage, playerName } from "@/lib/format";
import { executableBid, marketAction, type MarketAction } from "@/lib/marketAction";
import type { JornadaClub, MarketDecision, PlanFichajeAccion, PlanFichajes, TrendsPayload } from "@/lib/types";

type Filter = "all" | MarketAction | "rival";

const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "Todos" },
  { id: "PUJAR", label: "Pujar" },
  { id: "ESPERAR", label: "Esperar" },
  { id: "NO", label: "No" },
  { id: "rival", label: "De rivales" },
];

const ORDER: Record<MarketAction, number> = { PUJAR: 0, ESPERAR: 1, NO: 2 };

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
        </span>
        <span className="mt-auto flex items-end justify-between gap-2 border-t border-white/[0.06] px-3 py-2.5">
          <span className="min-w-0">
            <span className="block text-[10.5px] text-white/40">{typeof bid === "number" ? "Puja" : "Valor"}</span>
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

export function FichajesTab({ trends, photos, loading }: { trends: TrendsPayload | null; photos: PhotoIndex; loading: boolean }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const decisions = useMemo(() => {
    if (!trends || trends.ok === false) return [] as MarketDecision[];
    const rows = Array.isArray(trends.market_decisions) ? trends.market_decisions : [];
    // Primero lo que hay que pujar, y dentro de cada grupo la mejor nota.
    return [...rows].sort(
      (a, b) => ORDER[marketAction(a)] - ORDER[marketAction(b)] || (b.nota_mercado ?? -1) - (a.nota_mercado ?? -1),
    );
  }, [trends]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return decisions.filter((row) => {
      if (filter === "rival" && row.offer_source !== "rival") return false;
      if (filter !== "all" && filter !== "rival" && marketAction(row) !== filter) return false;
      if (!needle) return true;
      return `${row.nickname || ""} ${row.name || ""} ${row.club || ""}`.toLowerCase().includes(needle);
    });
  }, [decisions, filter, query]);

  if (loading && (!trends || trends.ok === false)) return <Skeleton />;
  if (!trends || trends.ok === false) {
    return <Empty title="Sin lectura de mercado" detail={trends ? errorMessage(trends) : "Pulsa Actualizar para leer el mercado de tu liga."} />;
  }

  const summary = trends.market_decision_summary || {};
  const photo = (player: MarketDecision) => player.image_url || photoFor(photos, String(player.player_id), playerName(player));
  const board = (Array.isArray(trends.jornada_board) ? trends.jornada_board : []).filter((club) => (club.market_count ?? 0) > 0);
  const counts: Record<Filter, number> = {
    all: decisions.length,
    PUJAR: decisions.filter((row) => marketAction(row) === "PUJAR").length,
    ESPERAR: decisions.filter((row) => marketAction(row) === "ESPERAR").length,
    NO: decisions.filter((row) => marketAction(row) === "NO").length,
    rival: decisions.filter((row) => row.offer_source === "rival").length,
  };
  const budget = budgetLine(summary);
  const selected = decisions.find((row) => String(row.player_id) === selectedId) || null;

  return (
    <div className="flex flex-col gap-5">
      <section className="home-hero" aria-label="Resumen del mercado">
        <div className="flex items-end justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[13px] font-medium text-white/60">Mercado de hoy</p>
            <p className="mt-1 text-[2.4rem] font-semibold leading-none tabular-nums text-white">
              {counts.PUJAR}
              <span className="ml-2 text-[1rem] font-medium text-white/60">{counts.PUJAR === 1 ? "puja recomendada" : "pujas recomendadas"}</span>
            </p>
          </div>
          <span className="shrink-0 text-[12.5px] tabular-nums text-white/55">{decisions.length} en venta</span>
        </div>
        <div className="mt-4 grid grid-cols-3 gap-2">
          <HeroStat value={compact(summary.cash_eur ?? trends.cash_eur)} label="caja" />
          <HeroStat value={summary.day_budget_eur != null ? compact(summary.day_budget_eur) : "—"} label="tope hoy" tone="#FFC08A" />
          <HeroStat value={summary.plan_cash_after_eur != null ? compact(summary.plan_cash_after_eur) : "—"} label="te queda" tone={toneOf(summary.plan_cash_after_eur)} />
        </div>
        {budget ? <p className="mt-3 text-[12.5px] leading-snug text-white/55">{budget}</p> : null}
      </section>

      <section className="flex flex-col gap-3">
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Buscar jugador o equipo"
          aria-label="Buscar jugador o equipo"
          className="h-11 w-full rounded-2xl border border-white/[0.08] bg-white/[0.04] px-4 text-[14px] text-white outline-none transition-colors duration-200 ease-out placeholder:text-white/30 focus:border-[#FF9A5A]/60"
        />
        <div className="eq-scroll">
          {FILTERS.map((item) =>
            item.id === "rival" && !counts.rival ? null : (
              <button
                key={item.id}
                type="button"
                aria-pressed={filter === item.id}
                onClick={() => setFilter(item.id)}
                className={filter === item.id ? "eq-chip eq-chip--on" : "eq-chip"}
              >
                {item.label}
                <span className="tabular-nums opacity-60">{counts[item.id]}</span>
              </button>
            ),
          )}
        </div>
        {filtered.length ? (
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {filtered.map((player, index) => (
              <Tile key={String(player.player_id)} player={player} photo={photo(player)} index={index} onOpen={() => setSelectedId(String(player.player_id))} />
            ))}
          </ul>
        ) : (
          <p className="px-1 py-6 text-center text-[13.5px] text-white/45">Nadie en este filtro.</p>
        )}
      </section>

      <PlanBlock plan={trends.plan_fichajes} />

      <Disclosure title="Calendario de estos fichajes" meta={`${board.length} equipos`}>
        <FixtureList clubs={board} />
      </Disclosure>

      <p className="px-1 text-[12px] leading-relaxed text-white/40">{historyLine(summary)}</p>

      <PlayerCard player={selected} photo={selected ? photo(selected) : null} onClose={() => setSelectedId(null)} />
    </div>
  );
}
