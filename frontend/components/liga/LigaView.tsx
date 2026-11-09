"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { endpoint, getJson } from "@/lib/core/api";
import { playerName, points, stamp } from "@/lib/core/format";
import { applyLiquidity, financialIndex, liquidityRead } from "@/lib/liga/liquidity";
import { enrichSquadsPayload } from "@/lib/liga/squadEnrich";
import { squadHoldings, squadPatrimonio, squadTotals } from "@/lib/liga/squadTotals";
import { photoFor, type PhotoIndex } from "@/lib/core/photoIndex";
import { clauseThreats } from "@/lib/liga/threats";
import type { ActivityEvent, LeagueEdge, LeagueFormPayload, LeagueRacePayload, RivalIntelPayload, RivalPlayer, RivalSquad, SquadsPayload, TrendsPayload } from "@/lib/types";
import { Chevron, Disclosure, Empty, Face, Fact, HeroStat, Skeleton, TONE, cleanText, compact, forecastHint, money, parsePct, signedMoney, signedPct, toneOf } from "@/components/ui/kit";
import { ThreatRadar } from "./ThreatRadar";
import { FormCard } from "./FormCard";
import { HeadToHeadCard } from "./HeadToHeadCard";
import { POS_LABEL, POS_ORDER, rivalLabel } from "./dashboard/shared";

type Sort = "rank" | "cash" | "value" | "delta";
type Tab = "clasificacion" | "duelo" | "forma" | "alertas";

const SORTS: { id: Sort; label: string }[] = [
  { id: "rank", label: "Puesto" },
  { id: "cash", label: "Caja" },
  { id: "value", label: "Patrimonio" },
  { id: "delta", label: "Hoy" },
];

const MODE: Record<string, { label: string; color: string; text: string }> = {
  ventaja: { label: "Vas por delante", color: TONE.green, text: "Tu once busca puntos seguros: titulares fijos antes que apuestas." },
  remontada: { label: "Toca remontar", color: TONE.copper, text: "Tu once busca techo: jugadores capaces de dar muchos puntos aunque sean más arriesgados." },
  neutro: { label: "Carrera igualada", color: TONE.blue, text: "Ni ventaja ni remontada: el once equilibra suelo y techo." },
};

const STYLE: Record<string, { label: string; color: string }> = {
  agresivo: { label: "Puja fuerte", color: TONE.red },
  moderado: { label: "Puja normal", color: TONE.amber },
  conservador: { label: "Puja justo", color: TONE.green },
};

const MEDAL = ["#F5C451", "#C9D1D9", "#D98E5B"];

/**
 * Última respuesta buena de cada endpoint: al volver a Liga se enseña al
 * instante y se refresca por detrás, en vez de esperar otra vez al servidor.
 */
const jsonCache = new Map<string, unknown>();

function useJson<T>(path: string, league: string | null): T | null {
  const key = endpoint(path, league);
  const [loaded, setLoaded] = useState<{ key: string; payload: T } | null>(() => (jsonCache.has(key) ? { key, payload: jsonCache.get(key) as T } : null));
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      // Un 502/504 suele ser el backend reiniciándose o un arranque en frío:
      // se reintenta dos veces antes de rendirse.
      for (let attempt = 0; ; attempt += 1) {
        try {
          const payload = await getJson<T>(key);
          jsonCache.set(key, payload);
          if (!cancelled) setLoaded({ key, payload });
          return;
        } catch (reason: unknown) {
          if (attempt < 2 && !cancelled) {
            await new Promise((resolve) => setTimeout(resolve, 1500 * (attempt + 1)));
            continue;
          }
          if (cancelled || jsonCache.has(key)) return; // si hay copia buena, se queda esa
          // Se conserva el motivo (HTTP 500, sin conexión…) para poder enseñarlo.
          const sent = (reason as { payload?: unknown } | null)?.payload;
          const message = reason instanceof Error ? reason.message : "Sin respuesta";
          setLoaded({ key, payload: (sent && typeof sent === "object" ? sent : { ok: false, error: { message } }) as T });
          return;
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [key]);
  if (loaded && loaded.key === key) return loaded.payload;
  return jsonCache.has(key) ? (jsonCache.get(key) as T) : null;
}

function cashOf(squad: RivalSquad): number | null {
  const read = liquidityRead(squad);
  return read.calibratedCash ?? read.cash ?? squad.cash_eur ?? null;
}

function sortValue(squad: RivalSquad, sort: Sort): number {
  if (sort === "cash") return cashOf(squad) ?? -Infinity;
  if (sort === "value") return squadPatrimonio(squad) ?? -Infinity;
  if (sort === "delta") return squadTotals(squad).price_delta_day ?? -Infinity;
  return -(typeof squad.rank === "number" ? squad.rank : 999);
}

function RankBadge({ rank, self }: { rank: number | null | undefined; self: boolean }) {
  const medal = typeof rank === "number" && rank <= 3 ? MEDAL[rank - 1] : null;
  return (
    <span
      className="grid h-10 w-10 shrink-0 place-items-center rounded-full text-[15px] font-semibold tabular-nums"
      style={{
        color: self ? "#0b0b0b" : medal || "rgba(255,255,255,0.8)",
        background: self ? "#fff" : medal ? `${medal}1f` : "rgba(255,255,255,0.06)",
      }}
    >
      {typeof rank === "number" ? rank : "—"}
    </span>
  );
}

function Tag({ label, color }: { label: string; color: string }) {
  return (
    <span className="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium" style={{ color, background: `${color}1a` }}>
      {label}
    </span>
  );
}

function ManagerRow({
  squad,
  self,
  ownPoints,
  sort,
  index,
  onOpen,
}: {
  squad: RivalSquad;
  self: boolean;
  ownPoints: number | null;
  sort: Sort;
  index: number;
  onOpen: () => void;
}) {
  const name = rivalLabel(squad);
  const cash = cashOf(squad);
  const team = squad.fantasy_team_name && squad.fantasy_team_name !== name ? squad.fantasy_team_name : null;
  const gap = !self && typeof squad.points === "number" && ownPoints !== null ? squad.points - ownPoints : null;
  const style = !self && squad.bid_profile && squad.bid_profile.style !== "sin_datos" ? STYLE[squad.bid_profile.style] : null;
  const delta = squadTotals(squad).price_delta_day;
  const right =
    sort === "cash"
      ? { value: money(cash), label: "caja", tone: cash !== null && cash < 0 ? TONE.red : "#fff" }
      : sort === "value"
        ? { value: money(squadPatrimonio(squad)), label: "patrimonio", tone: "#fff" }
        : sort === "delta"
          ? { value: signedMoney(delta), label: "hoy", tone: toneOf(delta) }
          : { value: typeof squad.points === "number" ? `${squad.points}` : "—", label: "puntos", tone: "#fff" };
  return (
    <li className="row-in" style={{ animationDelay: `${Math.min(index, 14) * 30}ms` }}>
      <button type="button" onClick={onOpen} className="flex w-full items-center gap-3 px-3.5 py-3 text-left">
        <RankBadge rank={squad.rank} self={self} />
        <span className="min-w-0 flex-1">
          <span className="flex min-w-0 items-center gap-2">
            <span className="truncate text-[15px] font-medium leading-tight text-white">{name}</span>
            {self ? <Tag label="Tú" color="#FFC08A" /> : null}
            {cash !== null && cash < 0 ? <Tag label="En negativo" color={TONE.red} /> : null}
          </span>
          <span className="mt-0.5 block truncate text-[12.5px] text-white/45">
            {[
              team,
              sort !== "cash" ? `Caja ${compact(cash)}` : null,
              gap !== null ? (gap === 0 ? "empatado contigo" : `${gap > 0 ? "+" : "−"}${Math.abs(gap)} pts contigo`) : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </span>
          {style ? (
            <span className="mt-1.5 flex">
              <Tag
                label={`${style.label}${typeof squad.bid_profile?.typical_premium_pct === "number" ? ` · ${signedPct(squad.bid_profile.typical_premium_pct, 0)}` : ""}`}
                color={style.color}
              />
            </span>
          ) : null}
        </span>
        <span className="shrink-0 text-right">
          <span className="block text-[16px] font-semibold tabular-nums" style={{ color: right.tone }}>
            {right.value}
          </span>
          <span className="block text-[11px] text-white/40">{right.label}</span>
        </span>
        <svg viewBox="0 0 16 16" className="h-4 w-4 shrink-0 text-white/30" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
          <path d="m6 4 4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
    </li>
  );
}

/* ── Ficha del rival ────────────────────────────────────────────────────── */

type SheetTab = "plantilla" | "movimientos";

const EVENT_TEXT: Record<string, string> = {
  buy: "Fichó a",
  clause: "Clausuló a",
  sell: "Vendió a",
  premium: "Premio de jornada",
};

function eventLine(event: ActivityEvent): string {
  const head = EVENT_TEXT[String(event.kind)] || cleanText(event.label) || "Movimiento";
  return event.kind === "premium" || !event.player_name ? head : `${head} ${event.player_name}`;
}

function SquadPlayer({ player, photos }: { player: RivalPlayer; photos: PhotoIndex }) {
  const [open, setOpen] = useState(false);
  const name = playerName(player);
  const trend = parsePct(player.prevision_7d_pct);
  const lock = player.clause_lock;
  return (
    <li className="rounded-2xl bg-[#1c1c1e]">
      <button type="button" aria-expanded={open} onClick={() => setOpen((value) => !value)} className="flex w-full items-center gap-3 px-3 py-2.5 text-left">
        <Face name={name} src={player.image_url || photoFor(photos, player.player_id, name)} size={36} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[14px] font-medium text-white">{name}</span>
          <span className="block truncate text-[12px] text-white/45">
            {[player.club, player.is_shielded ? "Blindado" : lock?.is_locked ? "Con candado" : `Cláusula ${money(player.buyout_clause)}`].filter(Boolean).join(" · ")}
          </span>
        </span>
        <span className="shrink-0 text-right">
          <span className="block text-[14px] font-semibold tabular-nums text-white">{money(player.market_value)}</span>
          {trend !== null ? (
            <span className="block text-[11.5px] tabular-nums" style={{ color: toneOf(trend) }}>
              {forecastHint(player.market_value, trend)?.replace("→ ", "")}
            </span>
          ) : null}
        </span>
        <Chevron open={open} />
      </button>
      {open ? (
        <div className="row-in grid grid-cols-3 gap-3 border-t border-white/[0.05] px-3 pb-3 pt-2.5">
          <Fact label="Pagó" value={money(player.cost_eur)} hint={player.acquired_at ? stamp(player.acquired_at) : undefined} />
          <Fact label="Ganancia" value={signedMoney(player.gain_eur)} tone={toneOf(player.gain_eur)} hint={typeof player.roi === "number" ? signedPct(player.roi * 100) : undefined} />
          <Fact label="Cláusula" value={money(player.buyout_clause)} hint={lock?.is_locked ? `Abre ${lock.local_time || lock.local_date || ""}` : player.is_shielded ? "Blindado" : "Abierta"} />
        </div>
      ) : null}
    </li>
  );
}

function RivalDialog({
  squad,
  self,
  photos,
  onClose,
}: {
  squad: RivalSquad | null;
  self: boolean;
  photos: PhotoIndex;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [tab, setTab] = useState<SheetTab>("plantilla");
  const teamId = squad?.team_id != null ? String(squad.team_id) : null;
  const [shown, setShown] = useState(teamId);
  if (shown !== teamId) {
    setShown(teamId);
    setTab("plantilla");
  }

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (squad && !dialog.open) {
      dialog.showModal();
      dialog.scrollTop = 0;
    }
    if (!squad && dialog.open) dialog.close();
  }, [squad]);

  const body = (() => {
    if (!squad) return null;
    const name = rivalLabel(squad);
    const read = liquidityRead(squad);
    const cash = cashOf(squad);
    const holdings = squadHoldings(squad);
    const players = squad.players || [];
    const groups = POS_ORDER.map((pos) => ({
      pos,
      rows: players.filter((player) => String(player.position || "").toUpperCase() === pos).sort((a, b) => (b.market_value ?? 0) - (a.market_value ?? 0)),
    })).filter((group) => group.rows.length);
    const events = squad.activity_profile?.recent_events || [];
    const style = squad.bid_profile && squad.bid_profile.style !== "sin_datos" ? STYLE[squad.bid_profile.style] : null;
    return (
      <article className="flex flex-col gap-2.5 p-2.5 sm:p-3">
        <span className="mx-auto mt-0.5 h-1 w-10 rounded-full bg-white/20 sm:hidden" aria-hidden="true" />
        <header className="relative overflow-hidden rounded-[1.75rem] px-4 pb-4 pt-5" style={{ background: "radial-gradient(ellipse 120% 90% at 50% 0%, rgba(255,122,61,0.35), rgba(255,122,61,0.08) 45%, transparent 75%), #111" }}>
          <button
            type="button"
            onClick={onClose}
            aria-label="Cerrar"
            className="absolute right-3 top-3 grid h-9 w-9 place-items-center rounded-full bg-black/30 text-white/70 outline-none backdrop-blur-md transition-colors hover:text-white"
          >
            <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
              <path d="M4 4l8 8M12 4l-8 8" strokeLinecap="round" />
            </svg>
          </button>
          <div className="flex items-center gap-3.5 pr-10">
            <RankBadge rank={squad.rank} self={self} />
            <div className="min-w-0">
              <h2 className="truncate text-[1.35rem] font-semibold leading-tight tracking-tight text-white">{name}</h2>
              <p className="mt-0.5 truncate text-[13px] text-white/55">
                {[squad.fantasy_team_name !== name ? squad.fantasy_team_name : null, typeof squad.points === "number" ? `${squad.points} puntos` : null].filter(Boolean).join(" · ")}
              </p>
            </div>
          </div>
          {style ? (
            <p className="mt-3 text-[12.5px] text-white/60">
              <Tag label={style.label} color={style.color} />
              {typeof squad.bid_profile?.typical_premium_pct === "number" ? (
                <span className="ml-2">Suele pagar un {signedPct(squad.bid_profile.typical_premium_pct, 0)} sobre el valor</span>
              ) : null}
            </p>
          ) : null}
          {squad.dinero_caliente ? (
            <p className="mt-3 rounded-xl bg-[#FF6B3D]/10 px-3 py-2 text-[12.5px] leading-snug text-[#FFB08A]">{squad.dinero_caliente.aviso}</p>
          ) : null}
          {squad.huella ? (
            <div className="mt-3 flex flex-col gap-1.5 text-[12.5px] text-white/60">
              {squad.huella.cola ? (
                <p>
                  <Tag label={squad.huella.cola.etiqueta} color="#FFC08A" />
                  <span className="ml-2">en {squad.huella.cola.n_compras} compras</span>
                </p>
              ) : null}
              {squad.huella.ventanas_clausulazo?.length ? (
                <p>
                  Clausula hacia las <span className="text-white/80">{squad.huella.ventanas_clausulazo.join(" / ")}</span>
                </p>
              ) : null}
              {(squad.huella.ofertas_humanas || []).map((oferta) => (
                <p key={oferta.market_id || oferta.player_id}>
                  <Tag label={oferta.etiqueta} color={TONE.red} />
                  <span className="ml-2">
                    {oferta.nombre} · {oferta.offer_count} ofertas
                  </span>
                </p>
              ))}
            </div>
          ) : null}
          <div className="mt-4 grid grid-cols-3 gap-2">
            <HeroStat value={compact(cash)} label="Caja" tone={cash !== null && cash < 0 ? TONE.red : undefined} />
            <HeroStat value={compact(read.bidLimit)} label="Puja máxima" tone="#FFC08A" />
            <HeroStat value={compact(holdings.gain_eur, true)} label="Ganancia" tone={toneOf(holdings.gain_eur)} />
          </div>
          {read.tightened || (read.arbitrageEur ?? 0) > 0 ? (
            <p className="mt-3 text-[11.5px] leading-snug text-white/40">
              {(read.arbitrageEur ?? 0) > 0
                ? "Tiene más caja de la que explican sus movimientos: la cifra es la que publica la liga."
                : "La caja está ajustada con su saldo real: es lo que de verdad puede gastar."}
            </p>
          ) : null}
        </header>

        <div className="desk-switch !grid-cols-2 !max-w-none" role="tablist" aria-label="Qué ver del rival">
          {(
            [
              ["plantilla", `Plantilla · ${players.length}`],
              ["movimientos", "Movimientos"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={tab === id}
              className={tab === id ? "desk-switch__btn desk-switch__btn--on" : "desk-switch__btn"}
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
        </div>

        {tab === "plantilla" ? (
          groups.length ? (
            groups.map((group) => (
              <section key={group.pos} className="rounded-[1.5rem] bg-[#141414] p-3">
                <p className="mb-2 px-1 text-[12.5px] font-semibold text-white/70">
                  {POS_LABEL[group.pos] || group.pos} <span className="font-normal text-white/35">{group.rows.length}</span>
                </p>
                <ul className="flex flex-col gap-1.5">
                  {group.rows.map((player) => (
                    <SquadPlayer key={String(player.player_id)} player={player} photos={photos} />
                  ))}
                </ul>
              </section>
            ))
          ) : (
            <p className="rounded-[1.5rem] bg-[#141414] p-4 text-[13.5px] text-white/50">Esta plantilla no trae jugadores.</p>
          )
        ) : (
          <section className="rounded-[1.5rem] bg-[#141414] p-4">
            <div className="grid grid-cols-3 gap-3">
              <Fact label="Ha gastado" value={money((squad.activity_profile?.purchases_eur ?? 0) + (squad.activity_profile?.clauses_eur ?? 0) || null)} />
              <Fact label="Ha vendido" value={money(squad.activity_profile?.sales_eur)} tone={TONE.green} />
              <Fact label="Ganado vendiendo" value={signedMoney(squad.activity_profile?.realized_gain_eur)} tone={toneOf(squad.activity_profile?.realized_gain_eur)} />
            </div>
            {events.length ? (
              <ul className="mt-4 divide-y divide-white/[0.05]">
                {events.map((event, index) => {
                  const incoming = typeof event.signed_eur === "number" ? event.signed_eur > 0 : event.kind === "sell" || event.kind === "premium";
                  const color = incoming ? TONE.green : TONE.red;
                  return (
                    <li key={`${event.at}-${event.kind}-${index}`} className="flex items-center gap-3 py-2.5">
                      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-[13px] font-semibold" style={{ color, background: `${color}1a` }} aria-hidden="true">
                        {incoming ? "↓" : "↑"}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[14px] text-white">{eventLine(event)}</span>
                        <span className="block text-[12px] text-white/40">{stamp(event.at) || "Sin fecha"}</span>
                      </span>
                      <span className="shrink-0 text-[14px] font-medium tabular-nums" style={{ color }}>
                        {typeof event.signed_eur === "number" ? signedMoney(event.signed_eur) : money(event.amount_eur)}
                      </span>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="mt-4 text-[13px] text-white/45">Sin movimientos sincronizados para este mánager.</p>
            )}
          </section>
        )}
      </article>
    );
  })();

  return (
    <dialog
      ref={ref}
      className="mk-card"
      onClose={onClose}
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
    >
      {body}
    </dialog>
  );
}

/* ── Vista ──────────────────────────────────────────────────────────────── */

export function LigaView({
  squads,
  trends,
  photos,
  loading,
}: {
  squads: SquadsPayload | null;
  trends: TrendsPayload | null;
  photos: PhotoIndex;
  loading: boolean;
}) {
  const league = useSearchParams().get("league");
  const race = useJson<LeagueRacePayload>("/api/league-race", league);
  const rivalIntel = useJson<RivalIntelPayload>("/api/rival-intel", league);
  const form = useJson<LeagueFormPayload>("/api/league-form", league);
  const [sort, setSort] = useState<Sort>("rank");
  const [tab, setTab] = useState<Tab>("clasificacion");
  const [selected, setSelected] = useState<string | null>(null);

  const view = useMemo(() => enrichSquadsPayload(squads, trends), [squads, trends]);
  const financials = useMemo(() => financialIndex(rivalIntel?.ok === false ? null : rivalIntel?.teams), [rivalIntel]);
  const all = useMemo(() => {
    const rows = (view?.rivals || []).map((row) => applyLiquidity(row, financials.get(String(row.team_id)))).filter((row): row is RivalSquad => row !== null);
    const own = applyLiquidity(view?.self, view?.self ? financials.get(String(view.self.team_id)) : null);
    return { rows: own ? [...rows, own] : rows, own };
  }, [view, financials]);
  const sorted = useMemo(() => all.rows.slice().sort((a, b) => sortValue(b, sort) - sortValue(a, sort)), [all, sort]);

  const mode = race && race.ok !== false ? race.mode : null;
  const ownRank = mode?.own_rank ?? all.own?.rank ?? null;
  // Si la carrera no responde, el de arriba y el de abajo salen de la
  // clasificación, que ya está en las plantillas.
  const standingEdge = (offset: -1 | 1): LeagueEdge | null => {
    const own = all.own;
    if (!own || typeof own.points !== "number") return null;
    const ranked = all.rows.filter((row) => typeof row.points === "number").sort((a, b) => (b.points as number) - (a.points as number));
    const index = ranked.findIndex((row) => String(row.team_id) === String(own.team_id));
    const other = index >= 0 ? ranked[index + offset] : undefined;
    if (!other || typeof other.points !== "number") return null;
    return { team_id: String(other.team_id), manager_name: rivalLabel(other), rank: other.rank ?? null, points: other.points, edge_points: own.points - other.points };
  };
  const above = mode?.above ?? standingEdge(-1);
  const below = mode?.below ?? standingEdge(1);
  const mine = race && race.ok !== false ? race.my_projection : null;

  // El cara a cara solo depende de /api/league-race. Las plantillas llegan
  // después de trends/optimize/needs (y el solver corre en cada GET de squads),
  // así que no se esperan: el duelo sale en cuanto responde la carrera.
  const headToHeadCard =
    race && race.ok !== false ? (
      <HeadToHeadCard
        mine={mine}
        rivals={race.rivals || []}
        defaultId={String((ownRank === 1 ? below : above)?.team_id ?? "") || null}
        photos={photos}
      />
    ) : null;

  if (loading && !squads) {
    return (
      <div className="flex min-w-0 flex-col gap-4">
        {headToHeadCard}
        <Skeleton />
      </div>
    );
  }
  if (!view || view.ok === false || !all.rows.length) {
    return <Empty title="Sin clasificación" detail="Pulsa Actualizar para leer las plantillas de tu liga." />;
  }

  const ownId = all.own?.team_id != null ? String(all.own.team_id) : null;
  const ownPoints = mode?.own_points ?? all.own?.points ?? null;
  const leaderGap = typeof mode?.gap_to_leader === "number" ? mode.gap_to_leader : null;
  const posture = mode ? MODE[mode.name] : null;
  const leagueAvg = race && race.ok !== false ? race.league_projection : null;
  const thin = race && race.ok !== false ? (race.rivals || []).filter((row) => (row.thin_positions || []).length).slice(0, 6) : [];
  const denial = race && race.ok !== false ? (race.denial || []).slice(0, 6) : [];
  const selectedSquad = selected ? all.rows.find((row) => String(row.team_id) === selected) || null : null;

  const gapLine = (() => {
    if (ownRank === 1) {
      return below && typeof below.edge_points === "number" ? `Líder con ${Math.abs(below.edge_points)} pts sobre ${below.manager_name || "el 2º"}` : "Vas líder";
    }
    if (leaderGap !== null) {
      const behind = Math.abs(leaderGap);
      return `A ${behind} pts del líder${mode?.leader?.manager_name ? `, ${mode.leader.manager_name}` : ""}`;
    }
    return null;
  })();

  const threatCount = clauseThreats(all.own, all.rows).length;
  const alertCount = threatCount + thin.length + denial.length;
  const tabs: { id: Tab; label: string; badge?: number }[] = [
    { id: "clasificacion", label: "Tabla" },
    { id: "duelo", label: "Duelo" },
    { id: "forma", label: "Forma" },
    { id: "alertas", label: "Alertas", badge: alertCount || undefined },
  ];
  const activeTab = tabs.some((item) => item.id === tab) ? tab : "clasificacion";
  const projTop = Math.max(mine?.expected_points ?? 0, typeof leagueAvg === "number" ? leagueAvg : 0, 1);

  return (
    <div className="grid gap-5 min-[1100px]:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] min-[1100px]:items-start">
      <aside className="flex min-w-0 flex-col gap-3 min-[1100px]:sticky min-[1100px]:top-4">
        <section className="home-feature" aria-label="Tu posición en la liga">
          <div className="relative flex items-center justify-between gap-3">
            <p className="text-[13px] font-medium text-white/60">Tu posición</p>
            {posture ? (
              <span className="rounded-full bg-black/30 px-3 py-1.5 text-[12px] font-semibold backdrop-blur-md" style={{ color: posture.color }}>
                {posture.label}
              </span>
            ) : null}
          </div>
          <p className="relative mt-2 flex items-baseline gap-2 tabular-nums">
            <span className="text-[3.25rem] font-semibold leading-none tracking-[-0.045em] text-white">{typeof ownRank === "number" ? `${ownRank}º` : "—"}</span>
            <span className="text-base font-medium text-white/60">de {all.rows.length}</span>
          </p>
          {gapLine ? <p className="relative mt-2 text-[13.5px] text-white/60">{gapLine}</p> : null}
          <div className="relative mt-5 grid grid-cols-3 gap-2.5">
            <HeroStat value={typeof ownPoints === "number" ? String(ownPoints) : "—"} label="Tus puntos" />
            <HeroStat
              value={above && typeof above.edge_points === "number" ? `${Math.abs(above.edge_points)}` : "—"}
              label={above?.manager_name ? `Hasta ${above.manager_name}` : "Al de arriba"}
              tone={TONE.copper}
            />
            <HeroStat
              value={below && typeof below.edge_points === "number" ? `${Math.abs(below.edge_points)}` : "—"}
              label={below?.manager_name ? `Sobre ${below.manager_name}` : "Al de abajo"}
              tone={TONE.green}
            />
          </div>

          {typeof mine?.expected_points === "number" ? (
            <div className="relative mt-5 border-t border-white/[0.08] pt-4">
              <p className="text-[11.5px] font-medium uppercase tracking-[0.08em] text-white/40">Próxima jornada</p>
              <div className="mt-3 flex flex-col gap-2.5">
                {[
                  { label: "Tu once", value: mine.expected_points, color: "#FFC08A" },
                  { label: "Media de la liga", value: typeof leagueAvg === "number" ? leagueAvg : null, color: "rgba(255,255,255,0.4)" },
                ].map((row) => (
                  <div key={row.label}>
                    <div className="flex items-baseline justify-between text-[13px]">
                      <span className="text-white/65">{row.label}</span>
                      <span className="font-semibold tabular-nums text-white">{row.value !== null ? `${points(row.value)} pts` : "—"}</span>
                    </div>
                    <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-white/[0.07]">
                      <span className="block h-full rounded-full transition-[width] duration-700 ease-out" style={{ width: `${row.value !== null ? (row.value / projTop) * 100 : 0}%`, background: row.color }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {posture ? <p className="relative mt-4 text-[12.5px] leading-snug text-white/45">{posture.text}</p> : null}
        </section>

        {race === null ? (
          <p className="px-1 text-[12px] text-white/35">Calculando la carrera de liga…</p>
        ) : race.ok === false ? (
          <p className="px-1 text-[12px] leading-relaxed text-white/35">
            La carrera de liga no ha respondido: {race.error?.message || race.message || "sin detalle"}. Sin ella no hay proyección ni cara a cara.
          </p>
        ) : null}
      </aside>

      <section className="flex min-w-0 flex-col gap-3" aria-label="Liga">
        <div className="desk-switch !max-w-none" style={{ gridTemplateColumns: `repeat(${tabs.length}, minmax(0, 1fr))` }} role="tablist" aria-label="Secciones de la liga">
          {tabs.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={activeTab === item.id}
              className={activeTab === item.id ? "desk-switch__btn desk-switch__btn--on" : "desk-switch__btn"}
              onClick={() => setTab(item.id)}
            >
              <span className="truncate">{item.label}</span>
              {item.badge ? (
                <span
                  className="ml-1.5 grid h-[18px] min-w-[18px] shrink-0 place-items-center rounded-full px-1 text-[10.5px] font-semibold tabular-nums"
                  style={activeTab === item.id ? { background: "#120c09", color: "#fff" } : { background: `${TONE.amber}2a`, color: TONE.amber }}
                >
                  {item.badge}
                </span>
              ) : null}
            </button>
          ))}
        </div>

        <div key={activeTab} className="row-in flex min-w-0 flex-col gap-3" role="tabpanel">
          {activeTab === "clasificacion" ? (
            <>
              <div className="eq-scroll -mx-1 px-1" role="toolbar" aria-label="Ordenar la clasificación">
                {SORTS.map((item) => (
                  <button key={item.id} type="button" aria-pressed={sort === item.id} onClick={() => setSort(item.id)} className={sort === item.id ? "eq-chip eq-chip--on" : "eq-chip"}>
                    {item.label}
                  </button>
                ))}
              </div>
              <ul className="home-glass divide-y divide-white/[0.05] overflow-hidden">
                {sorted.map((squad, index) => (
                  <ManagerRow
                    key={String(squad.team_id)}
                    squad={squad}
                    self={ownId !== null && String(squad.team_id) === ownId}
                    ownPoints={typeof ownPoints === "number" ? ownPoints : null}
                    sort={sort}
                    index={index}
                    onOpen={() => setSelected(String(squad.team_id))}
                  />
                ))}
              </ul>
              <p className="px-1 text-[12px] leading-relaxed text-white/35">
                Toca un mánager para ver su plantilla y sus movimientos. La caja de cada rival se reconstruye con sus movimientos; el detalle está en Laboratorio → Rivales.
              </p>
            </>
          ) : null}

          {activeTab === "duelo" ? (
            race === null ? (
              <>
                <p className="px-1 text-[13px] text-white/50">Calculando el once de cada rival… la primera vez tras una actualización puede tardar hasta un minuto.</p>
                <Skeleton />
              </>
            ) : race.ok === false ? (
              <Empty title="Cara a cara no disponible" detail={`La carrera de liga no ha respondido: ${race.error?.message || race.message || "sin detalle"}.`} />
            ) : !(race.rivals || []).length ? (
              <Empty title="Sin rivales proyectados" detail="Pulsa Actualizar para calcular los onces de tus rivales." />
            ) : (
              headToHeadCard
            )
          ) : null}

          {activeTab === "forma" ? form === null ? <Skeleton /> : <FormCard form={form} above={above} below={below} /> : null}

          {activeTab === "alertas" ? (
            alertCount ? (
              <>
                <ThreatRadar own={all.own} rivals={all.rows} photos={photos} />
                {thin.length || denial.length ? (
                  <Disclosure title="Dónde puedes hacer daño" meta={`${thin.length + denial.length}`} defaultOpen>
                    {thin.length ? (
                      <>
                        <p className="text-[12.5px] text-white/45">Rivales con líneas flojas: si fichas lo que necesitan, les cuesta más.</p>
                        <ul className="mt-2 divide-y divide-white/[0.05]">
                          {thin.map((row) => (
                            <li key={String(row.team_id)} className="flex items-center justify-between gap-3 py-2.5">
                              <span className="min-w-0 truncate text-[14px] text-white">{row.manager_name || row.fantasy_team_name || "Rival"}</span>
                              <span className="flex shrink-0 gap-1">
                                {(row.thin_positions || []).map((pos) => (
                                  <Tag key={pos} label={pos} color={TONE.amber} />
                                ))}
                              </span>
                            </li>
                          ))}
                        </ul>
                      </>
                    ) : null}
                    {denial.length ? (
                      <div className={thin.length ? "mt-4 border-t border-white/[0.06] pt-3" : ""}>
                        <p className="text-[12.5px] text-white/45">En venta y justo lo que necesita un rival con caja para pagarlo.</p>
                        <ul className="mt-2 divide-y divide-white/[0.05]">
                          {denial.map((row) => {
                            const name = row.nickname || row.name || "Jugador";
                            return (
                              <li key={String(row.player_id)} className="flex items-center gap-2.5 py-2.5">
                                <Face name={name} src={photoFor(photos, row.player_id, name)} size={32} />
                                <span className="min-w-0 flex-1">
                                  <span className="block truncate text-[14px] text-white">
                                    {name}
                                    {row.position ? <span className="text-white/40"> · {row.position}</span> : null}
                                  </span>
                                  <span className="block truncate text-[12px] text-white/45">Lo quiere {(row.managers || []).join(", ")}</span>
                                </span>
                                <span className="shrink-0 text-[14px] font-medium tabular-nums text-white">{money(row.sale_price)}</span>
                              </li>
                            );
                          })}
                        </ul>
                      </div>
                    ) : null}
                  </Disclosure>
                ) : null}
              </>
            ) : (
              <Empty title="Todo tranquilo" detail="Ningún jugador tuyo está al alcance de un clausulazo y no hay rivales con líneas flojas que aprovechar." />
            )
          ) : null}
        </div>
      </section>

      <RivalDialog squad={selectedSquad} self={selected !== null && selected === ownId} photos={photos} onClose={() => setSelected(null)} />
    </div>
  );
}
