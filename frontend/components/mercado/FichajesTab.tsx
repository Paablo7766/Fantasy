"use client";

import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { GradeBadge } from "@/components/MarketGrade";
import { BidSheet } from "@/components/mercado/BidSheet";
import { ACTION_VERDICT, budgetLine, difficultyLabel, historyLine, winShare } from "@/components/mercado/shared";
import {
  Disclosure,
  Empty,
  Face,
  HeroStat,
  SectionHead,
  Skeleton,
  TONE,
  Verdict,
  compact,
  money,
  parsePct,
  signedPct,
  toneOf,
} from "@/components/equipo/ui";
import { photoFor, type PhotoIndex } from "@/lib/photoIndex";
import { errorMessage, playerName } from "@/lib/format";
import { actionReason, executableBid, marketAction, type MarketAction } from "@/lib/marketAction";
import type { JornadaClub, MarketDecision, PlanFichajeAccion, PlanFichajes, TrendsPayload } from "@/lib/types";

type ActionFilter = "all" | MarketAction;

const ACTION_FILTERS: { id: ActionFilter; label: string }[] = [
  { id: "all", label: "Todos" },
  { id: "PUJAR", label: "Pujar" },
  { id: "ESPERAR", label: "Esperar" },
  { id: "NO", label: "No" },
];

const SOURCES = [
  { id: "liga", title: "Oferta de la liga", empty: "La liga no tiene fichajes en este filtro." },
  { id: "rival", title: "Venta de rivales", empty: "Ningún rival vende en este filtro." },
  { id: "propio", title: "Tus ventas", empty: "" },
] as const;

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
        {typeof accion.euros === "number" ? (
          <span className="block text-[14.5px] font-semibold tabular-nums text-white">{money(accion.euros)}</span>
        ) : null}
        <span className={`block text-[11px] font-semibold uppercase tracking-wide ${hoy ? "text-[#FFC08A]" : "text-white/35"}`}>
          {hoy ? "hoy" : accion.momento === "radar" ? "radar" : "luego"}
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
    <Disclosure
      title="Tu plan de fichajes"
      defaultOpen={acciones.length > 0}
      meta={<span style={{ color: PLAN_TONE[veredicto] || TONE.gray }}>{veredicto}</span>}
    >
      <div className="grid grid-cols-3 gap-2">
        <HeroStat
          value={typeof gain === "number" && gain > 0 ? `+${decimal(gain)}` : "0"}
          label="pts en el once"
          tone={typeof gain === "number" && gain > 0 ? TONE.green : undefined}
        />
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

function PickCard({ player, photo, onOpen }: { player: MarketDecision; photo: string | null; onOpen: () => void }) {
  const bid = executableBid(player);
  // La puja que se pinta es la smart: su probabilidad manda sobre la del modelo v2.
  const win = winShare(typeof player.smart_bid_success_pct === "number" ? player.smart_bid_success_pct : player.win_probability);
  const name = playerName(player);
  return (
    <li className="w-[15.5rem] shrink-0">
      <button
        type="button"
        onClick={onOpen}
        className="home-glass flex h-full w-full flex-col gap-3 p-4 text-left transition-colors duration-200 ease-out hover:bg-white/[0.06]"
      >
        <span className="flex items-center gap-3">
          <Face name={name} src={photo} size={44} ring={TONE.green} />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[15px] font-medium text-white">{name}</span>
            <span className="block truncate text-[12px] text-white/45">
              {[player.position, player.club].filter(Boolean).join(" · ")}
            </span>
          </span>
          {typeof player.nota_mercado === "number" ? <GradeBadge note={player.nota_mercado} /> : null}
        </span>
        <span className="flex items-end justify-between gap-2">
          <span>
            <span className="block text-[11.5px] text-white/45">Puja</span>
            <span className="block text-[1.35rem] font-semibold leading-tight tabular-nums text-white">{money(bid)}</span>
          </span>
          {win !== null ? (
            <span className="text-right">
              <span className="block text-[11.5px] text-white/45">P(ganar)</span>
              <span className="block text-[15px] font-semibold tabular-nums" style={{ color: win >= 0.7 ? TONE.green : win >= 0.4 ? TONE.amber : TONE.red }}>
                {Math.round(win * 100)}%
              </span>
            </span>
          ) : null}
        </span>
        {win !== null ? (
          <span className="block h-1 overflow-hidden rounded-full bg-white/[0.08]" aria-hidden="true">
            <span
              className="block h-full rounded-full"
              style={{ width: `${Math.round(win * 100)}%`, background: "linear-gradient(90deg,#FF6A2B,#FFC08A)" }}
            />
          </span>
        ) : null}
        {player.frase_mercado ? <span className="line-clamp-2 text-[12.5px] leading-snug text-white/55">{player.frase_mercado}</span> : null}
      </button>
    </li>
  );
}

function DecisionRow({
  player,
  photo,
  index,
  onOpen,
}: {
  player: MarketDecision;
  photo: string | null;
  index: number;
  onOpen: () => void;
}) {
  const name = playerName(player);
  const action = marketAction(player);
  const verdict = ACTION_VERDICT[action];
  const bid = executableBid(player);
  const trend = parsePct(player.prevision_7d_pct);
  const reason = actionReason(player);
  return (
    <li className="row-in border-b border-white/[0.06] last:border-b-0" style={{ animationDelay: `${Math.min(index, 12) * 30}ms` }}>
      <button
        type="button"
        onClick={onOpen}
        aria-label={`Por qué: ${name}`}
        className="flex min-h-[4rem] w-full items-center gap-3 px-4 py-3 text-left transition-colors duration-200 ease-out hover:bg-white/[0.02]"
      >
        <Face name={name} src={photo} size={42} ring={action === "PUJAR" ? TONE.green : undefined} />
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1.5">
            <span className="truncate text-[15px] font-medium leading-tight text-white">{name}</span>
            {typeof player.nota_mercado === "number" ? <GradeBadge note={player.nota_mercado} /> : null}
          </span>
          <span className="mt-0.5 block truncate text-[12.5px] text-white/45">
            {player.position || "—"}
            {player.club ? ` · ${player.club}` : ""}
            {player.offer_source === "rival" ? <span style={{ color: TONE.amber }}> · {player.seller_manager || "rival"}</span> : null}
            {player.venta_forzada_rival ? <span style={{ color: TONE.red }}> · venta obligada</span> : null}
          </span>
          {reason || player.frase_mercado ? (
            <span className="mt-0.5 block truncate text-[12px] text-white/40">{player.frase_mercado || reason}</span>
          ) : null}
        </span>
        <span className="shrink-0 text-right">
          <span className="block text-[15px] font-semibold tabular-nums text-white">{typeof bid === "number" ? money(bid) : money(player.market_value)}</span>
          <span className="mt-0.5 flex items-center justify-end gap-2">
            {trend !== null ? (
              <span className="text-[12px] font-medium tabular-nums" style={{ color: toneOf(trend) }}>
                {signedPct(trend)}
              </span>
            ) : null}
            <Verdict {...verdict} />
          </span>
        </span>
      </button>
    </li>
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
  const [filter, setFilter] = useState<ActionFilter>("all");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const search = useSearchParams();
  const calibracionHref = search.toString() ? `/calibracion?${search.toString()}` : "/calibracion";

  const decisions = useMemo(() => {
    if (!trends || trends.ok === false) return [] as MarketDecision[];
    return Array.isArray(trends.market_decisions) ? trends.market_decisions : [];
  }, [trends]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return decisions.filter((row) => {
      if (filter !== "all" && marketAction(row) !== filter) return false;
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
  const open = (player: MarketDecision) => setSelectedId(String(player.player_id));
  const picks = decisions.filter((row) => marketAction(row) === "PUJAR" && typeof executableBid(row) === "number").slice(0, 6);
  const board = (Array.isArray(trends.jornada_board) ? trends.jornada_board : []).filter((club) => (club.market_count ?? 0) > 0);
  const counts: Record<ActionFilter, number> = {
    all: decisions.length,
    PUJAR: summary.pujar ?? decisions.filter((row) => marketAction(row) === "PUJAR").length,
    ESPERAR: summary.esperar ?? decisions.filter((row) => marketAction(row) === "ESPERAR").length,
    NO: summary.no ?? decisions.filter((row) => marketAction(row) === "NO").length,
  };
  const budget = budgetLine(summary);
  const selected = decisions.find((row) => String(row.player_id) === selectedId) || null;
  const confidence = trends.engine_confidence;

  return (
    <div className="flex flex-col gap-5">
      <section className="home-hero" aria-label="Resumen del mercado">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[13px] font-medium text-white/60">Hoy en el mercado</p>
            <p className="mt-1 text-[2.6rem] font-semibold leading-none tabular-nums text-white">
              {counts.PUJAR}
              <span className="ml-2 text-[1.1rem] font-medium text-white/60">{counts.PUJAR === 1 ? "puja" : "pujas"}</span>
            </p>
          </div>
          {confidence && confidence.band !== "unknown" ? (
            <Link
              href={calibracionHref}
              className="shrink-0 rounded-full bg-black/25 px-3 py-1.5 text-[12px] font-medium text-white/70 no-underline transition-colors hover:text-white"
            >
              Motor {typeof confidence.score === "number" ? `${confidence.score}/100` : confidence.band}
            </Link>
          ) : null}
        </div>
        <div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <HeroStat value={compact(summary.cash_eur ?? trends.cash_eur)} label="caja" />
          <HeroStat value={summary.day_budget_eur != null ? compact(summary.day_budget_eur) : "—"} label="tope hoy" tone="#FFC08A" />
          <HeroStat value={summary.plan_spend_eur != null ? compact(summary.plan_spend_eur) : "—"} label="el plan gasta" />
          <HeroStat
            value={summary.plan_cash_after_eur != null ? compact(summary.plan_cash_after_eur) : "—"}
            label="te queda"
            tone={toneOf(summary.plan_cash_after_eur)}
          />
        </div>
        <p className="mt-4 text-[12.5px] leading-snug text-white/55">
          {summary.liga ?? 0} de la liga · {summary.rival ?? 0} de rivales · {counts.ESPERAR} a esperar
          {budget ? `. ${budget}` : "."}
        </p>
      </section>

      {picks.length ? (
        <section className="flex flex-col gap-3">
          <SectionHead title="Mejores pujas" meta={`${picks.length}`} />
          <ul className="eq-scroll -mx-1 px-1 pb-1">
            {picks.map((player) => (
              <PickCard key={`pick-${player.player_id}`} player={player} photo={photo(player)} onOpen={() => open(player)} />
            ))}
          </ul>
        </section>
      ) : null}

      <PlanBlock plan={trends.plan_fichajes} />

      <section className="flex flex-col gap-3">
        <SectionHead title="Todo el mercado" meta={`${filtered.length} jugadores`} />
        <div className="eq-scroll">
          {ACTION_FILTERS.map((item) => (
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
          ))}
        </div>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Buscar jugador o equipo"
          aria-label="Buscar jugador o equipo"
          className="h-11 w-full rounded-2xl border border-white/[0.08] bg-white/[0.04] px-4 text-[14px] text-white outline-none transition-colors duration-200 ease-out placeholder:text-white/30 focus:border-[#FF9A5A]/60"
        />
        {SOURCES.map((source) => {
          const rows = filtered.filter((row) => (row.offer_source || "liga") === source.id);
          if (!rows.length && source.id === "propio") return null;
          return (
            <div key={source.id} className="flex flex-col gap-2">
              <p className="px-1 text-[13px] font-medium text-white/55">
                {source.title} <span className="tabular-nums text-white/35">{rows.length}</span>
              </p>
              {rows.length ? (
                <ul className="home-glass overflow-hidden">
                  {rows.map((player, index) => (
                    <DecisionRow
                      key={`${source.id}-${player.player_id}`}
                      player={player}
                      photo={photo(player)}
                      index={index}
                      onOpen={() => open(player)}
                    />
                  ))}
                </ul>
              ) : (
                <p className="px-1 text-[13px] text-white/40">{source.empty}</p>
              )}
            </div>
          );
        })}
      </section>

      <Disclosure title="Calendario de estos fichajes" meta={`${board.length} equipos`}>
        <FixtureList clubs={board} />
      </Disclosure>

      <p className="px-1 text-[12px] leading-relaxed text-white/40">{historyLine(summary)}</p>

      <BidSheet player={selected} photo={selected ? photo(selected) : null} onClose={() => setSelectedId(null)} />
    </div>
  );
}
