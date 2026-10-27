"use client";

import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AuctionV2Panel } from "@/components/AuctionV2Panel";
import { ErrorCard, Skeleton } from "@/components/Feedback";
import { ModelConfidenceBadge } from "@/components/ModelConfidenceBadge";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { bidCapLine, bidStory } from "@/lib/bidStory";
import { accel, eur, glass, pct, playerName } from "@/lib/format";
import { actionReason, actionTone, executableBid, isVetoed, marketAction } from "@/lib/marketAction";
import type { CatalogPlayer, JornadaClub, MarketDecision, MarketDecisionSummary, TrendsPayload } from "@/lib/types";

type Filter = "all" | "PUJAR" | "ESPERAR" | "NO";

const DIFFICULTY: Record<string, string> = {
  muy_facil: "muy fácil",
  facil: "fácil",
  media: "media",
  dificil: "difícil",
  muy_dificil: "muy difícil",
};

function difficultyLabel(key: string | null | undefined): string {
  if (!key) return "";
  return DIFFICULTY[key] || key.replace(/_/g, " ");
}

function budgetSupport(summary: MarketDecisionSummary): string {
  const markets = summary.markets_left;
  const day = summary.day_budget_eur;
  const spend = summary.plan_spend_eur;
  const leftover = summary.plan_cash_after_eur;
  if (typeof markets === "number" && markets > 1 && typeof day === "number") {
    const spent = typeof spend === "number" ? ` El plan de hoy gasta ${eur(spend)}` : "";
    const rest = typeof leftover === "number" ? ` y deja ${eur(leftover)}.` : ".";
    return ` Quedan ${markets} mercados hasta la jornada: hoy como mucho ${eur(day)}; el resto se guarda.${spent}${rest}`;
  }
  if (typeof spend === "number" && typeof leftover === "number") {
    return ` El plan de este mercado gasta ${eur(spend)} y deja ${eur(leftover)}.`;
  }
  return "";
}

function historySupport(summary: MarketDecisionSummary): string {
  const wars = summary.league_war_count ?? 0;
  const median = summary.league_median_premium;
  const priced = summary.league_priced_count ?? 0;
  const buys = summary.league_buy_count ?? 0;
  if (wars >= 3 && typeof median === "number") {
    return ` Cuando hay guerra, la compra ganadora queda un ${pct(median)} por encima del valor de ese día (${priced || wars} compras con valor guardado).`;
  }
  if (priced > 0) {
    return ` Historial: ${priced} compras con valor de ese día. Hacen falta 3 guerras de rivales que puedan pagar para fijar la sobrepuja.`;
  }
  if (buys > 0) {
    return ` Historial: ${buys} compras leídas, sin el valor de esos días no se mide la sobrepuja.`;
  }
  return " Sin historial de sobrepujas de la liga: la cifra es el precio justo, no lo que suele hacer falta para ganar.";
}

const OWNER_LABEL: Record<string, string> = {
  libre: "Libre",
  rival: "Rival",
  propio: "Propio",
};

function Sparkline({ points }: { points: Array<{ market_value?: number | null }> }) {
  const values = points
    .map((point) => point.market_value)
    .filter((value): value is number => typeof value === "number")
    .slice(-10);
  if (values.length < 2) return <span className="text-[11px] text-faint">sin serie</span>;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const width = 72;
  const height = 22;
  const coords = values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * width;
      const y = height - ((value - min) / span) * (height - 2) - 1;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg width={width} height={height} className="text-mint" aria-hidden="true">
      <polyline fill="none" stroke="currentColor" strokeWidth="1.4" points={coords} />
    </svg>
  );
}

function UniverseTable({ rows }: { rows: CatalogPlayer[] }) {
  return (
    <table className="table-dense table-sticky w-full min-w-[760px] text-left text-sm">
      <thead>
        <tr>
          <th>Jugador</th>
          <th>Dueño</th>
          <th className="text-right">Valor</th>
          <th className="text-right">Previsión</th>
          <th>Serie</th>
        </tr>
      </thead>
      <tbody>
        {rows.length ? (
          rows.map((player) => {
            const days = player.price_points?.length ?? 0;
            const forecast =
              days >= 3 && typeof player.own_predicted_delta === "number"
                ? accel(player.own_predicted_delta)
                : "sin previsión";
            return (
              <tr key={String(player.player_id)}>
                <td>
                  <div className="flex items-center gap-2.5">
                    <PlayerAvatar player={player} size="sm" />
                    <div className="min-w-0">
                      <div className="truncate font-medium tracking-tight">{playerName(player)}</div>
                      <div className="text-[11px] text-muted">
                        {player.position || ""}
                        {player.club ? ` · ${player.club}` : ""}
                      </div>
                    </div>
                  </div>
                </td>
                <td className="text-xs text-muted-strong">{OWNER_LABEL[player.owner || ""] || player.owner || "Libre"}</td>
                <td className="metric-value text-right text-sm">{eur(player.market_value)}</td>
                <td className="text-right">
                  <span className={`metric-value text-sm ${forecast === "sin previsión" ? "text-faint" : ""}`}>
                    {forecast}
                  </span>
                </td>
                <td>
                  <Sparkline points={player.price_points || []} />
                </td>
              </tr>
            );
          })
        ) : (
          <tr>
            <td className="!text-muted" colSpan={5}>
              Ningún jugador en este filtro. La serie sale de los días ya guardados; sin tres días no hay previsión.
            </td>
          </tr>
        )}
      </tbody>
    </table>
  );
}

export function MarketTable({
  trends,
  loading = false,
}: {
  trends: TrendsPayload | null;
  loading?: boolean;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const [view, setView] = useState<"fichajes" | "universo">("fichajes");
  const [owner, setOwner] = useState<"all" | "libre" | "rival" | "propio">("all");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const search = useSearchParams();
  const calibracionHref = search.toString() ? `/calibracion?${search.toString()}` : "/calibracion";

  const decisions = useMemo(() => {
    if (!trends || trends.ok === false) return [] as MarketDecision[];
    return Array.isArray(trends.market_decisions) ? trends.market_decisions : [];
  }, [trends]);

  const filtered = useMemo(() => {
    if (filter === "all") return decisions;
    return decisions.filter((row) => marketAction(row) === filter);
  }, [decisions, filter]);

  const catalogRows = useMemo(() => {
    const catalog = Array.isArray(trends?.catalog) ? trends.catalog : [];
    const needle = query.trim().toLowerCase();
    return catalog.filter((player) => {
      if (owner !== "all" && (player.owner || "libre") !== owner) return false;
      if (!needle) return true;
      const haystack = `${player.nickname || ""} ${player.name || ""} ${player.club || ""}`.toLowerCase();
      return haystack.includes(needle);
    });
  }, [trends, owner, query]);

  if (loading && (!trends || trends.ok === false)) return <Skeleton title="Mercado" rows={8} />;
  if (!trends || trends.ok === false) {
    return <ErrorCard title="Mercado" payload={trends || { error: { message: "Sin lectura de mercado." } }} brief />;
  }

  const summary = trends.market_decision_summary || {};
  const board = (Array.isArray(trends.jornada_board) ? trends.jornada_board : []).filter(
    (club) => (club.market_count ?? 0) > 0,
  );
  const picks = decisions
    .filter((row) => marketAction(row) === "PUJAR" && typeof executableBid(row) === "number")
    .slice(0, 4);
  const ligaRows = filtered.filter((row) => row.offer_source === "liga");
  const rivalRows = filtered.filter((row) => row.offer_source === "rival");
  const ownRows = filtered.filter((row) => row.offer_source === "propio");
  const sections = [
    { title: "Oferta de la liga", rows: ligaRows, empty: "La liga no tiene fichajes en este filtro." },
    { title: "Oferta de rivales", rows: rivalRows, empty: "Ningún rival tiene un jugador a la venta en este filtro." },
    ...(ownRows.length
      ? [{ title: "Tus ventas", rows: ownRows, empty: "" }]
      : []),
  ];
  const pujar = summary.pujar ?? 0;
  const esperar = summary.esperar ?? 0;
  const no = summary.no ?? 0;

  return (
    <article className={glass("flex max-h-[920px] flex-col p-4 md:p-5")}>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="eyebrow">Analizador de mercado</p>
          <h2 className="section-title mt-1">
            <span className="metric-value text-mint">{pujar}</span>
            <span className="ml-2">pujar</span>
            <span className="mx-2 text-faint">·</span>
            <span className="metric-value text-warn">{esperar}</span>
            <span className="ml-2 text-base font-normal text-muted-strong">esperar</span>
            <span className="mx-2 text-faint">·</span>
            <span className="metric-value text-muted">{no}</span>
            <span className="ml-2 text-base font-normal text-muted">no</span>
          </h2>
          <p className="section-support">
            {summary.liga ?? ligaRows.length} a la venta por la liga · {summary.rival ?? rivalRows.length} de rivales · te
            quedan {eur(summary.cash_eur ?? trends.cash_eur)}. Pulsa una puja para ver por qué.
            {budgetSupport(summary)}
            {historySupport(summary)}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ModelConfidenceBadge confidence={trends.engine_confidence} href={calibracionHref} compact />
          <div className="seg">
            {(
              [
                ["fichajes", "Fichajes"],
                ["universo", "Universo"],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => setView(key)}
                className={view === key ? "seg__btn seg__btn--active" : "seg__btn"}
              >
                {label}
              </button>
            ))}
          </div>
          {view === "universo" ? (
            <>
              <div className="seg">
                {(
                  [
                    ["all", "Todos"],
                    ["libre", "Libre"],
                    ["rival", "Rival"],
                    ["propio", "Propio"],
                  ] as const
                ).map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setOwner(key)}
                    className={owner === key ? "seg__btn seg__btn--active" : "seg__btn"}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Buscar jugador"
                className="h-8 w-40 rounded-lg border border-[color:var(--line-strong)] bg-[color:var(--surface-strong)] px-2.5 text-xs text-ink outline-none placeholder:text-faint"
              />
            </>
          ) : (
            <div className="seg">
              {(
                [
                  ["all", "Todos"],
                  ["PUJAR", "Pujar"],
                  ["ESPERAR", "Esperar"],
                  ["NO", "No"],
                ] as const
              ).map(([key, label]) => {
                const active = filter === key;
                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setFilter(key)}
                    className={active ? "seg__btn seg__btn--active" : "seg__btn"}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>

      <div className="scroll-thin min-h-0 flex-1 overflow-auto">
        {view === "universo" ? (
          <UniverseTable rows={catalogRows} />
        ) : (
          <>
        <JornadaStrip clubs={board} />
        {picks.length ? (
          <ul className="mb-4 grid gap-2 md:grid-cols-2">
            {picks.map((player) => (
              <PickCard
                key={`pick-${player.player_id}`}
                player={player}
                open={selectedId === String(player.player_id)}
                onOpen={() =>
                  setSelectedId((current) => (current === String(player.player_id) ? null : String(player.player_id)))
                }
              />
            ))}
          </ul>
        ) : null}
        <table className="table-dense table-sticky w-full min-w-[640px] text-left text-sm">
          <thead>
            <tr>
              <th>Jugador</th>
              <th>Qué hacer</th>
              <th className="text-right">Cuánto</th>
              <th>Por qué</th>
            </tr>
          </thead>
          <tbody>
            {sections.map((section) => (
              <Fragment key={section.title}>
                <tr>
                  <td colSpan={4} className="!bg-[color:var(--surface-strong)] !py-2 text-xs font-semibold tracking-wide text-muted-strong">
                    {section.title}
                    <span className="ml-2 font-normal text-faint">{section.rows.length}</span>
                  </td>
                </tr>
                {section.rows.length ? (
                  section.rows.map((player) => {
                const id = String(player.player_id);
                const open = selectedId === id;
                const story = bidStory(player);
                const glance = story.glance;
                const cap = bidCapLine(player);
                const action = marketAction(player);
                const reason = actionReason(player, story.motive);
                const bid = executableBid(player);
                const titular =
                  typeof player.p_titular === "number" && !glance.startsWith("Titular")
                    ? `Titular ${pct(player.p_titular)}`
                    : "";
                return (
                  <tr
                    key={`${action}-${player.player_id}`}
                    className={open ? "row-link row-link--open" : "row-link"}
                    onClick={() => setSelectedId((current) => (current === id ? null : id))}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        setSelectedId((current) => (current === id ? null : id));
                      }
                    }}
                    tabIndex={0}
                    role="button"
                    aria-expanded={open}
                    aria-label={`Explicación de ${playerName(player)}`}
                  >
                    <td>
                      <div className="flex items-center gap-2.5">
                        <PlayerAvatar player={player} size="sm" />
                        <div className="min-w-0">
                          <div className="truncate font-medium tracking-tight">{playerName(player)}</div>
                          <div className="text-[11px] text-muted">
                            {player.position || ""}
                            {player.club ? (
                              <>
                                <span className="text-faint"> · </span>
                                {player.club}
                              </>
                            ) : null}
                            {player.offer_source === "rival" ? (
                              <span className="text-warn">
                                {" "}
                                · {player.seller_manager || "rival"}
                              </span>
                            ) : null}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td>
                      <span className={actionTone(action)}>{action}</span>
                      <span className="mt-1 block text-[11px] text-muted">
                        {reason}
                        {isVetoed(player) ? <span className="text-faint"> · veto</span> : null}
                      </span>
                    </td>
                    <td className="text-right">
                      <span className="metric-value text-sm">
                        {typeof bid === "number" ? eur(bid) : "Sin puja"}
                      </span>
                      {typeof player.optimal_bid_eur === "number" &&
                      typeof player.suggested_bid === "number" &&
                      player.optimal_bid_eur !== player.suggested_bid &&
                      !isVetoed(player) ? (
                        <span className="mt-0.5 block text-[11px] text-faint">operativa {eur(player.suggested_bid)}</span>
                      ) : null}
                      {cap ? <span className="mt-0.5 block text-[11px] text-muted">{cap}</span> : null}
                      <AuctionV2Panel player={player} variant="compact" />
                    </td>
                    <td>
                      <span className="block text-[13px] leading-5 text-ink">{glance}</span>
                      {titular ? <span className="mt-0.5 block text-[11px] text-muted">{titular}</span> : null}
                      <span className="mt-0.5 block text-[11px] text-info">Ver por qué</span>
                    </td>
                  </tr>
                    );
                  })
                ) : (
                  <tr>
                    <td className="!text-muted" colSpan={4}>
                      {section.empty}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
          </>
        )}
      </div>
      <BidSheet player={decisions.find((row) => String(row.player_id) === selectedId) || null} onClose={() => setSelectedId(null)} />
    </article>
  );
}

function JornadaStrip({ clubs }: { clubs: JornadaClub[] }) {
  return (
    <div className="mb-4">
      <p className="eyebrow">Equipos de estos fichajes</p>
      {clubs.length ? (
        <ul className="mt-2 flex gap-2 overflow-x-auto pb-1">
          {clubs.map((club) => {
            const home = club.is_home === true ? "casa" : club.is_home === false ? "fuera" : "";
            const tone =
              (club.recommendation_pct ?? 0) >= 72
                ? "fixture fixture--good"
                : (club.recommendation_pct ?? 0) <= 38
                  ? "fixture fixture--bad"
                  : "fixture";
            return (
              <li key={club.club || club.opponent || "club"} className={tone}>
                <div className="truncate text-sm font-medium text-ink">{club.club}</div>
                <div className="mt-0.5 truncate text-[11px] text-muted">
                  {home ? `${home} · ` : ""}
                  {club.opponent || "rival s/d"}
                  {club.predicted_score ? ` · ${club.predicted_score}` : ""}
                </div>
                <div className="mt-1 text-[11px]">
                  {typeof club.recommendation_pct === "number" ? `${Math.round(club.recommendation_pct)}%` : "s/d"}
                  {club.difficulty ? ` · ${difficultyLabel(club.difficulty)}` : ""}
                  {club.market_count ? ` · ${club.market_count} en mercado` : ""}
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-muted">Estos fichajes no traen calendario contrastado.</p>
      )}
    </div>
  );
}

function PickCard({
  player,
  open,
  onOpen,
}: {
  player: MarketDecision;
  open: boolean;
  onOpen: () => void;
}) {
  const story = bidStory(player);
  const action = marketAction(player);
  const reason = actionReason(player, story.motive);
  const bid = executableBid(player);
  const fixture = player.fixture;
  const home = fixture?.is_home === true ? "casa" : fixture?.is_home === false ? "fuera" : "";
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        aria-expanded={open}
        className={`w-full rounded-xl border px-3 py-2.5 text-left ${
          open
            ? "border-[color:var(--mint)] bg-[color:var(--mint-soft)]"
            : "border-[color:var(--line)] bg-[color:var(--surface-strong)]"
        }`}
      >
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate font-medium">{playerName(player)}</span>
          <span className={`shrink-0 ${actionTone(action)}`}>{action}</span>
        </div>
        <p className="mt-1 text-[11px] text-muted">
          {player.offer_source === "rival"
            ? `Rival${player.seller_manager ? ` · ${player.seller_manager}` : ""}`
            : player.offer_source === "propio"
              ? "Tu venta"
              : "Liga"}
          {" · "}
          {player.position}
          {player.club ? ` · ${player.club}` : ""}
          {fixture?.opponent ? ` · ${home ? `${home} vs ` : ""}${fixture.opponent}` : ""}
          {fixture?.difficulty ? ` · ${difficultyLabel(fixture.difficulty)}` : ""}
        </p>
        <p className="mt-1.5 text-sm">
          {typeof bid === "number" ? (
            <>
              {typeof player.optimal_bid_eur === "number" ? "Óptima v2" : "Puja"}{" "}
              <span className="metric-value text-gold">{eur(bid)}</span>
            </>
          ) : (
            <span className="text-coral">Sin puja</span>
          )}
          {typeof player.win_probability === "number" ? (
            <span className="text-muted">
              {" "}
              · P(ganar) {Math.round(player.win_probability * (player.win_probability <= 1 ? 100 : 1))}%
            </span>
          ) : null}
          {typeof player.raise_to === "number" ? (
            <span className="text-muted"> · máximo {eur(player.raise_to)}</span>
          ) : null}
        </p>
        <AuctionV2Panel player={player} variant="compact" />
        <p className="mt-1 text-[11px] leading-4 text-muted">{reason || story.glance}</p>
        <p className="mt-1 text-[11px] text-info">Ver por qué</p>
      </button>
    </li>
  );
}

function BidSheet({ player, onClose }: { player: MarketDecision | null; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const story = player ? bidStory(player) : null;

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (player && !dialog.open) dialog.showModal();
    if (!player && dialog.open) dialog.close();
  }, [player]);

  return (
    <dialog
      ref={ref}
      className="bid-dialog"
      onClose={onClose}
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
    >
      {player && story ? (
        <div className="bid-dialog__body">
          <div className="flex items-start justify-between gap-3">
            <div className="flex min-w-0 items-center gap-3">
              <PlayerAvatar player={player} size="sm" />
              <div className="min-w-0">
                <p className="eyebrow">Por qué esta puja</p>
                <h3 className="truncate text-lg font-semibold tracking-tight">{playerName(player)}</h3>
                <p className="text-[12px] text-muted">
                  {player.position || ""}
                  {player.club ? ` · ${player.club}` : ""}
                  {player.offer_source === "rival" ? ` · venta de ${player.seller_manager || "un rival"}` : ""}
                  {player.offer_source === "liga" ? " · mercado de la liga" : ""}
                  {player.offer_source === "propio" ? " · tu venta" : ""}
                </p>
              </div>
            </div>
            <button type="button" className="btn btn-secondary shrink-0" onClick={onClose}>
              Cerrar
            </button>
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <span className={actionTone(marketAction(player))}>{marketAction(player)}</span>
            <span className="text-sm text-muted-strong">{actionReason(player, story.motive)}</span>
            {isVetoed(player) ? <span className="badge badge--bad">Veto del motor</span> : null}
          </div>
          <p className="mt-3 text-[15px] font-medium leading-6 text-ink">{story.headline}</p>

          <section className="mt-4 rounded-xl bg-[color:var(--gold-soft)] px-3.5 py-3">
            <p className="eyebrow">Qué hacer</p>
            <p className="mt-1.5 text-sm leading-6 text-ink">{story.action}</p>
          </section>

          <AuctionV2Panel player={player} variant="full" />

          {story.reasons.length ? (
            <section className="mt-5">
              <p className="eyebrow">Los datos</p>
              <ul className="mt-2 space-y-2">
                {story.reasons.map((reason) => (
                  <li key={reason} className="text-sm leading-6 text-muted-strong">
                    {reason}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {story.theory ? (
            <section className="mt-5">
              <p className="eyebrow">La teoría</p>
              <p className="mt-2 text-sm leading-6 text-ink">{story.theory}</p>
            </section>
          ) : null}

          {story.facts.length ? (
            <section className="mt-5">
              <p className="eyebrow">Las cifras</p>
              <dl className="mt-2 grid grid-cols-2 gap-2">
                {story.facts.map((fact) => (
                  <div key={fact.label} className="rounded-lg bg-[color:var(--surface-strong)] px-3 py-2">
                    <dt className="text-[11px] text-faint">{fact.label}</dt>
                    <dd className="metric-value mt-0.5 text-sm">{fact.value}</dd>
                    <dd className="mt-0.5 text-[11px] leading-4 text-muted">{fact.note}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ) : null}

          {(player.rival_bids || []).length ? (
            <section className="mt-5">
              <p className="eyebrow">Pujas ya hechas</p>
              <ul className="mt-2 space-y-1.5">
                {player.rival_bids?.map((bid) => (
                  <li key={`${bid.team_id}-${bid.amount}`} className="flex justify-between text-sm">
                    <span>{bid.own ? "Tú" : bid.manager_name || "Rival"}</span>
                    <span className="metric-value">{eur(bid.amount)}</span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {story.gaps.length ? (
            <section className="mt-5">
              <p className="eyebrow">Qué no entra en la cuenta</p>
              <ul className="mt-2 space-y-1.5">
                {story.gaps.map((gap) => (
                  <li key={gap} className="text-[13px] leading-5 text-muted">
                    {gap}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>
      ) : null}
    </dialog>
  );
}
