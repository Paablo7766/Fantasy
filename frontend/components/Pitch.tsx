"use client";

import { useMemo, useState } from "react";
import { ErrorCard, Skeleton } from "@/components/Feedback";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { accel, eur, glass, jornadaEv, pct, playerName, points, projectedLineupPoints, titularShare } from "@/lib/format";
import type { Gap, OptimizePayload, Player, SquadsPayload } from "@/lib/types";

const ROW_Y: Record<string, number> = { DEL: 16, MC: 40, DEF: 66, POR: 88 };
const LINES = ["DEL", "MC", "DEF", "POR"] as const;
const LINE_LABEL: Record<string, string> = {
  DEL: "Delanteros",
  MC: "Medios",
  DEF: "Defensas",
  POR: "Portero",
};

type Token = Player & {
  gap?: boolean;
  label?: string;
  x: number;
  y: number;
};

function xFor(index: number, count: number): number {
  if (count <= 1) return 50;
  const margin = count >= 5 ? 12 : 18;
  return margin + (index * (100 - margin * 2)) / (count - 1);
}

export function layoutXi(players: Player[] | undefined, gaps: Gap[] | undefined): Token[] {
  const groups: Record<string, Array<Player & { gap?: boolean; label?: string }>> = {
    POR: [],
    DEF: [],
    MC: [],
    DEL: [],
  };
  for (const player of players || []) {
    if (player.position && groups[player.position]) groups[player.position].push(player);
  }
  for (const gap of gaps || []) {
    const count = Number(gap.missing) || 0;
    for (let index = 0; index < count; index += 1) {
      if (!gap.position || !groups[gap.position]) continue;
      groups[gap.position].push({
        gap: true,
        position: gap.position,
        label: `Falta 1 ${gap.position}`,
      });
    }
  }
  const placed: Token[] = [];
  for (const position of ["DEL", "MC", "DEF", "POR"]) {
    const line = groups[position].slice().sort((a, b) => {
      if (Boolean(a.gap) !== Boolean(b.gap)) return a.gap ? 1 : -1;
      return playerName(a).localeCompare(playerName(b), "es");
    });
    line.forEach((player, index) => {
      placed.push({ ...player, x: xFor(index, line.length), y: ROW_Y[position] });
    });
  }
  return placed;
}

function voidCopy(reasons: string[] | undefined): string {
  const labels: Record<string, string> = {
    empty_slot: "falta cerrar el once",
    negative_cash: "la caja es negativa",
  };
  const text = (reasons || []).map((reason) => labels[reason] || reason);
  return text.join(" · ") || "sin once completo";
}

function starterRing(value: number | null | undefined): string {
  const normalized = titularShare(value);
  const share = normalized !== null ? Math.max(0, Math.min(100, Math.round(normalized * 100))) : 0;
  return `conic-gradient(#f3e2b0 ${share}%, rgba(255,255,255,0.22) ${share}%)`;
}

function tokenKey(player: Token, index: number): string {
  return `${player.player_id || player.label || player.position}-${index}`;
}

function applySquadDelta(player: Player, deltas: Map<string, number>): Player {
  if (typeof player.price_delta === "number" || !player.player_id) return player;
  const delta = deltas.get(String(player.player_id));
  if (typeof delta !== "number") return player;
  return { ...player, price_delta: delta };
}

function priceMove(value: number | null | undefined): { text: string; tone: string } | null {
  if (typeof value !== "number") return null;
  return {
    text: `${accel(value)} €`,
    tone: value < 0 ? "text-coral" : value > 0 ? "text-mint" : "text-muted",
  };
}

/**
 * Δ de precio a pintar, con su procedencia.
 *
 * Prioriza el delta medido entre capturas propias (dato de LaLiga). Si no hay
 * dos capturas que restar, cae a la estimación de FútbolFantasy, pero se marca
 * con `≈` para no hacerla pasar por oficial: la API no publica
 * `marketValueChange` y antes se pintaba ese estimado como si lo fuera.
 */
function priceDeltaView(player: Player): { text: string; tone: string; title: string } | null {
  const measured =
    typeof player.measured_price_delta === "number" ? player.measured_price_delta : null;
  if (measured !== null) {
    const move = priceMove(measured);
    if (move) {
      return {
        ...move,
        title: "Δ medido entre dos capturas propias de LaLiga",
      };
    }
  }
  const estimate =
    typeof player.price_delta_estimated === "number"
      ? player.price_delta_estimated
      : typeof player.price_delta === "number"
        ? player.price_delta
        : null;
  if (estimate === null) return null;
  const move = priceMove(estimate);
  if (!move) return null;
  return {
    text: `≈ ${move.text}`,
    tone: move.tone,
    title: "Estimación de FútbolFantasy, no el valor oficial de LaLiga",
  };
}

function statusLabel(status: string | null | undefined): string | null {
  if (!status) return null;
  const folded = status.trim().toLowerCase();
  if (folded === "doubtful" || folded === "doubt" || folded === "duda") return "Duda";
  if (folded === "injured" || folded === "injury" || folded === "lesionado" || folded === "out" || folded === "baja") return "Lesión";
  if (folded === "suspended" || folded === "sanctioned" || folded === "sancionado") return "Sanción";
  return null;
}

function Silhouette() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden="true">
      <circle cx="12" cy="8" r="3" fill="none" stroke="currentColor" strokeWidth="1.6" strokeDasharray="2.2 1.6" />
      <path
        d="M6.5 19.2c.8-2.8 2.8-4.2 5.5-4.2s4.7 1.4 5.5 4.2"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

function TokenView({
  player,
  active,
  onSelect,
}: {
  player: Token;
  active: boolean;
  onSelect: () => void;
}) {
  if (player.gap) {
    const label = player.label || `Fichar ${player.position || ""}`.trim();
    return (
      <button
        type="button"
        className={active ? "token token-gap token--active" : "token token-gap"}
        data-token
        data-gap="true"
        data-position={player.position || ""}
        data-name={label}
        style={{ left: `${player.x}%`, top: `${player.y}%` }}
        title={label}
        aria-pressed={active}
        onClick={onSelect}
      >
        <div className="ring">
          <div className="avatar">
            <Silhouette />
          </div>
        </div>
        <div className="name">{label}</div>
        <div className="meta">hueco</div>
      </button>
    );
  }
  const name = playerName(player);
  const flag = statusLabel(player.player_status);
  const move = priceDeltaView(player);
  const estimated = player.p_titular_source === "week_points" ? " est." : "";
  const ev = jornadaEv(player);
  const ifStarts =
    typeof player.points_if_starts === "number"
      ? player.points_if_starts
      : typeof player.expected_points === "number" && typeof player.jornada_ev === "number"
        ? player.expected_points
        : null;
  const tooltipIfStarts =
    ifStarts !== null && ev !== null && Math.abs(ifStarts - ev) >= 0.35 ? ` · si titular ${points(ifStarts)}` : "";
  // La app oficial a veces marca el acumulado de 2 días. Se declara en el
  // tooltip para que un 519.675 € no parezca un error frente a 257.864 €.
  const windows = [
    ["1d", player.price_delta],
    ["2d", player.ff_price_delta_2],
    ["3d", player.ff_price_delta_3],
  ]
    .filter((entry): entry is [string, number] => typeof entry[1] === "number" && entry[1] !== 0)
    .map(([label, value]) => `${label} ${accel(value)} €`)
    .join(" · ");
  const tooltipWindows = windows ? ` · Δ ${windows}` : "";
  // Los dos deltas a la vez: el medido es el dato propio, el otro es de un
  // tercero. Juntos en el tooltip para que se puedan contrastar sin que la
  // tarjeta mezcle procedencias.
  const measured =
    typeof player.measured_price_delta === "number"
      ? ` · medido ${accel(player.measured_price_delta)} €`
      : " · sin 2ª captura";
  const tooltipDelta = `${measured}${move ? ` · est. ${accel(player.price_delta)} €` : ""}`;
  return (
    <button
      type="button"
      className={active ? "token token--active" : "token"}
      data-token
      data-position={player.position || ""}
      data-name={name}
      style={{ left: `${player.x}%`, top: `${player.y}%` }}
      title={`${name} · ${player.position || ""} · ${points(ev)} pts jornada · titular ${pct(player.p_titular)}${tooltipIfStarts}${estimated}${tooltipDelta}${tooltipWindows}`}
      aria-pressed={active}
      onClick={onSelect}
    >
      <div className="ring" style={{ background: starterRing(player.p_titular) }}>
        <PlayerAvatar player={player} />
      </div>
      <div className="name">{name}</div>
      <div className="meta">
        {points(ev)}
        {flag ? ` · ${flag}` : ""}
      </div>
      {move ? <div className={move.tone === "text-coral" ? "delta delta--down" : "delta delta--up"}>{move.text}</div> : null}
    </button>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-3 py-2.5">
      <p className="metric-label">{label}</p>
      <p className="metric-value mt-1 text-lg text-ink">{value}</p>
      {hint ? <p className="mt-0.5 truncate text-[11px] text-muted">{hint}</p> : null}
    </div>
  );
}

function PlayerSheet({
  player,
  onClose,
}: {
  player: Token;
  onClose: () => void;
}) {
  if (player.gap) {
    return (
      <div className="callout">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="eyebrow text-coral">Hueco</p>
            <h3 className="mt-1 text-lg font-semibold tracking-tight">{player.label || `Falta ${player.position}`}</h3>
            <p className="mt-1 text-sm text-muted">Esta plaza no tiene titular en la plantilla.</p>
          </div>
          <button type="button" className="btn btn-secondary !px-2.5 !py-1 text-xs" onClick={onClose}>
            Cerrar
          </button>
        </div>
      </div>
    );
  }
  const name = playerName(player);
  const flag = statusLabel(player.player_status);
  const normalized = titularShare(player.p_titular);
  const share = normalized !== null ? Math.max(0, Math.min(100, Math.round(normalized * 100))) : 0;
  const ev = jornadaEv(player);
  const ifStarts =
    typeof player.points_if_starts === "number"
      ? player.points_if_starts
      : typeof player.expected_points === "number" && typeof player.jornada_ev === "number"
        ? player.expected_points
        : null;
  return (
    <div className="rounded-2xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] p-4">
      <div className="flex items-start gap-3">
        <div className="h-14 w-14 shrink-0 overflow-hidden rounded-2xl ring-1 ring-ink/10">
          <PlayerAvatar player={player} className="!h-14 !w-14 !rounded-2xl !text-sm" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="eyebrow">{player.position || "Jugador"}</p>
              <h3 className="truncate text-lg font-semibold tracking-tight">{name}</h3>
              <p className="truncate text-sm text-muted">{player.club || "Club sin dato"}</p>
            </div>
            <button type="button" className="btn btn-secondary shrink-0 !px-2.5 !py-1 text-xs" onClick={onClose}>
              Cerrar
            </button>
          </div>
        </div>
      </div>
      <div className="mt-4 grid grid-cols-3 gap-3">
        <div>
          <p className="metric-label">Jornada</p>
          <p className="metric-value mt-1 text-2xl text-gold">{points(ev)}</p>
          {ifStarts !== null && ev !== null && Math.abs(ifStarts - ev) >= 0.35 ? (
            <p className="mt-0.5 text-[11px] text-muted">Si titular: {points(ifStarts)}</p>
          ) : null}
        </div>
        <div>
          <p className="metric-label">Titular</p>
          <p className="metric-value mt-1 text-2xl text-ink">{pct(player.p_titular)}</p>
        </div>
        <div>
          <p className="metric-label">Precio hoy</p>
          <p className={`metric-value mt-1 text-2xl ${priceDeltaView(player)?.tone || "text-muted"}`}>
            {priceDeltaView(player)?.text || "s/d"}
          </p>
          {priceDeltaView(player)?.text.startsWith("≈") ? (
            <p className="mt-1 text-[10px] leading-tight text-muted">
              estimación de FútbolFantasy
            </p>
          ) : priceDeltaView(player) ? (
            <p className="mt-1 text-[10px] leading-tight text-muted">medido entre capturas</p>
          ) : null}
        </div>
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-ink/10">
        <div className="h-full rounded-full bg-mint" style={{ width: `${share}%` }} />
      </div>
      <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
        {flag ? <span className="badge badge--warn">{flag}</span> : <span className="badge badge--good">Disponible</span>}
        {player.p_titular_source === "week_points" ? <span className="badge badge--warn">Titularidad estimada</span> : null}
      </div>
    </div>
  );
}

export function Pitch({
  optimize,
  squads = null,
  loading = false,
}: {
  optimize: OptimizePayload | null;
  squads?: SquadsPayload | null;
  loading?: boolean;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const deltas = useMemo(() => {
    const map = new Map<string, number>();
    for (const player of squads?.self?.players || []) {
      if (player.player_id && typeof player.price_delta === "number") {
        map.set(String(player.player_id), player.price_delta);
      }
    }
    return map;
  }, [squads]);

  const xi = (optimize && optimize.ok !== false && Array.isArray(optimize.xi) ? optimize.xi : []).map((player) =>
    applySquadDelta(player, deltas),
  );
  const gaps = optimize && Array.isArray(optimize.gaps) ? optimize.gaps : [];
  const placed = useMemo(() => layoutXi(xi, gaps), [xi, gaps]);

  if (loading && !optimize) return <Skeleton title="Alineación" rows={8} />;
  if (!optimize || optimize.ok === false) {
    return <ErrorCard title="Alineación" payload={optimize || { error: { message: "Sin once calculado." } }} brief />;
  }

  const counts = optimize.partial ? optimize.eligible_counts || optimize.counts || {} : optimize.counts || {};
  const countLine = LINES.map((pos) => `${pos} ${counts[pos] ?? 0}`).join(" · ");
  const title = optimize.partial ? "Mejor once posible" : "Once óptimo";
  const bench = (Array.isArray(optimize.benched) ? optimize.benched : []).map((player) => applySquadDelta(player, deltas));
  const excluded = Array.isArray(optimize.excluded) ? optimize.excluded : [];
  const fills = Array.isArray(optimize.market_fills) ? optimize.market_fills : [];
  const saved = optimize.saved_lineup && optimize.saved_lineup.ok ? optimize.saved_lineup : null;
  const savedIds = new Set((saved?.xi || []).map((player) => String(player.player_id)));
  const recommendedIds = new Set(xi.filter((player) => player.player_id).map((player) => String(player.player_id)));
  const sameXi =
    Boolean(saved) && savedIds.size > 0 && savedIds.size === recommendedIds.size && [...savedIds].every((id) => recommendedIds.has(id));
  const enters = xi.filter((player) => player.player_id && !savedIds.has(String(player.player_id)));
  const leaves = (saved?.xi || []).filter((player) => player.player_id && !recommendedIds.has(String(player.player_id)));

  const real = placed.filter((player) => !player.gap);
  const starterValues = real.map((player) => titularShare(player.p_titular)).filter((value): value is number => value !== null);
  const starterAvg = starterValues.length ? starterValues.reduce((sum, value) => sum + value, 0) / starterValues.length : null;
  const doubts = real.filter((player) => statusLabel(player.player_status)).length;
  const gapCount = placed.filter((player) => player.gap).length;
  const lineupEv =
    projectedLineupPoints(xi) ?? (typeof optimize.expected_points === "number" ? optimize.expected_points : null);
  const maxPoints = real.reduce((max, player) => Math.max(max, jornadaEv(player) ?? 0), 0);
  const active = placed.find((player, index) => tokenKey(player, index) === selected) || null;

  const linePoints = (position: string) =>
    real.filter((player) => player.position === position).reduce((sum, player) => sum + (jornadaEv(player) ?? 0), 0);

  return (
    <article className={glass("p-4 md:p-5")}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="eyebrow">Alineación</p>
          <h2 className="section-title mt-1">
            {title}
            {optimize.formation ? (
              <span className="metric-value ml-2 align-middle text-[0.95em] text-gold">{optimize.formation}</span>
            ) : null}
          </h2>
          <p className="section-support">
            {optimize.manager_name || "Tu plantilla"} · {countLine}
          </p>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="Proyección" value={points(lineupEv)} hint="valor esperado del once" />
        <Stat label="Titularidad" value={pct(starterAvg)} hint="media del once" />
        <Stat label="Alertas" value={String(doubts)} hint={doubts ? "duda, lesión o sanción" : "sin avisos"} />
        <Stat label="Huecos" value={String(gapCount)} hint={gapCount ? "plazas por cubrir" : "once cerrado"} />
      </div>

      {optimize.matchday_void ? (
        <p className="callout mt-4">
          Jornada a 0 · {voidCopy(optimize.void_reasons)}. El borde discontinuo marca el fichaje que falta.
        </p>
      ) : null}

      <div className="mt-5 grid items-start gap-5 lg:grid-cols-[minmax(280px,400px)_minmax(0,1fr)]">
        <div className="lg:sticky lg:top-24">
          <div className="flex justify-center">
            <div className="pitch">
              <svg viewBox="0 0 68 105" preserveAspectRatio="none" aria-hidden="true">
                <g fill="none" stroke="rgba(255,255,255,0.78)" strokeWidth="0.4">
                  <rect x="1.2" y="1.2" width="65.6" height="102.6" rx="0.6" />
                  <line x1="1.2" y1="52.5" x2="66.8" y2="52.5" />
                  <circle cx="34" cy="52.5" r="9.15" />
                  <circle cx="34" cy="52.5" r="0.55" fill="rgba(255,255,255,0.78)" stroke="none" />
                  <rect x="13.84" y="1.2" width="40.32" height="16.5" />
                  <rect x="24.84" y="1.2" width="18.32" height="5.5" />
                  <rect x="13.84" y="87.3" width="40.32" height="16.5" />
                  <rect x="24.84" y="98.3" width="18.32" height="5.5" />
                  <path d="M24.8 17.7a9.2 9.2 0 0 0 18.4 0" />
                  <path d="M24.8 87.3a9.2 9.2 0 0 1 18.4 0" />
                  <circle cx="34" cy="12" r="0.5" fill="rgba(255,255,255,0.78)" stroke="none" />
                  <circle cx="34" cy="93" r="0.5" fill="rgba(255,255,255,0.78)" stroke="none" />
                </g>
              </svg>
              <div className="pitch-xi">
                {placed.map((player, index) => {
                  const key = tokenKey(player, index);
                  return (
                    <TokenView
                      key={key}
                      player={player}
                      active={selected === key}
                      onSelect={() => setSelected((current) => (current === key ? null : key))}
                    />
                  );
                })}
              </div>
            </div>
          </div>
          <p className="mt-2 text-center text-[11px] text-faint">El aro dorado es la probabilidad de ser titular.</p>
        </div>

        <div className="min-w-0 space-y-4">
          {active ? <PlayerSheet player={active} onClose={() => setSelected(null)} /> : null}

          {LINES.map((position) => {
            const line = placed.filter((player) => player.position === position);
            if (!line.length) return null;
            return (
              <section key={position}>
                <div className="mb-1.5 flex items-baseline justify-between gap-3">
                  <p className="eyebrow">{LINE_LABEL[position]}</p>
                  <p className="metric-value text-xs text-gold">{points(linePoints(position))} pts</p>
                </div>
                <ul className="overflow-hidden rounded-xl border border-[color:var(--line)]">
                  {line.map((player) => {
                    const index = placed.indexOf(player);
                    const key = tokenKey(player, index);
                    const name = player.gap ? player.label || "Hueco" : playerName(player);
                    const width =
                      !player.gap && maxPoints > 0 && jornadaEv(player) !== null
                        ? Math.max(8, Math.round(((jornadaEv(player) ?? 0) / maxPoints) * 100))
                        : 0;
                    return (
                      <li key={key} className="border-b border-[color:var(--line)] last:border-b-0">
                        <button
                          type="button"
                          className={
                            selected === key
                              ? "flex w-full items-center gap-3 bg-[color:var(--gold-soft)] px-3 py-2.5 text-left"
                              : "flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors hover:bg-ink/[0.03]"
                          }
                          onClick={() => setSelected((current) => (current === key ? null : key))}
                        >
                          <span className="w-9 shrink-0">
                            {player.gap ? (
                              <span className="grid h-9 w-9 place-items-center rounded-full border border-dashed border-coral/50 text-coral">
                                <Silhouette />
                              </span>
                            ) : (
                              <PlayerAvatar player={player} size="sm" />
                            )}
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm font-medium">{name}</span>
                            <span className="mt-1 block h-1 overflow-hidden rounded-full bg-ink/10">
                              <span className="block h-full rounded-full bg-mint/80" style={{ width: `${width}%` }} />
                            </span>
                          </span>
                          <span className="shrink-0 text-right">
                            <span className="metric-value block text-sm text-gold">
                              {player.gap ? "—" : points(jornadaEv(player))}
                            </span>
                            <span className="block text-[11px] text-muted">{player.gap ? "hueco" : pct(player.p_titular)}</span>
                            {!player.gap && priceDeltaView(player) ? (
                              <span
                                className={`metric-value block text-[11px] ${priceDeltaView(player)!.tone}`}
                                title={priceDeltaView(player)!.title}
                              >
                                {priceDeltaView(player)!.text}
                              </span>
                            ) : null}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </section>
            );
          })}

          {fills.length ? (
            <div className="space-y-3">
              <p className="eyebrow">Qué fichar para cerrar el once</p>
              {fills.map((gap, index) => {
                const options = Array.isArray(gap.options) ? gap.options : [];
                return (
                  <div key={`${gap.position}-${index}`} className="callout">
                    <p className="text-sm font-medium">{gap.label || `Falta ${gap.missing} ${gap.position}`}</p>
                    <ul className="mt-1">
                      {options.length ? (
                        options.map((option) => (
                          <li key={String(option.player_id)} className="flex items-center justify-between gap-3 py-1.5 text-sm">
                            <span className="truncate">
                              {playerName(option)}
                              {option.club ? <span className="text-muted"> · {option.club}</span> : null}
                            </span>
                            <span className="metric-value shrink-0 text-xs">{eur(option.sale_price)}</span>
                          </li>
                        ))
                      ) : (
                        <li className="py-1 text-sm opacity-80">Nadie de esa posición tiene precio en el mercado.</li>
                      )}
                    </ul>
                  </div>
                );
              })}
            </div>
          ) : null}

          {saved ? (
            <div className="rounded-2xl border border-[color:var(--line)] p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="eyebrow">Alineación de la app</p>
                <span className={sameXi ? "badge badge--good" : "badge badge--warn"}>
                  {sameXi ? "Coincide" : "Distinta"}
                </span>
              </div>
              <p className="mt-2 text-sm text-ink">
                <span className="metric-value text-gold">{saved.formation || "sin formación"}</span>
              </p>
              {!sameXi && (enters.length || leaves.length) ? (
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  <div>
                    <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-mint">Entran</p>
                    <p className="mt-1 text-sm leading-6">{enters.length ? enters.map((player) => playerName(player)).join(", ") : "—"}</p>
                  </div>
                  <div>
                    <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-coral">Salen</p>
                    <p className="mt-1 text-sm leading-6">{leaves.length ? leaves.map((player) => playerName(player)).join(", ") : "—"}</p>
                  </div>
                </div>
              ) : null}
            </div>
          ) : (
            <p className="text-xs text-faint">La API no devolvió la alineación guardada en la app.</p>
          )}

          {bench.length ? (
            <div>
              <p className="eyebrow mb-2">Banquillo</p>
              <ul className="grid gap-2 sm:grid-cols-2">
                {bench.map((player) => (
                  <li
                    key={String(player.player_id)}
                    className="flex items-center gap-2.5 rounded-xl border border-[color:var(--line)] px-2.5 py-2"
                  >
                    <PlayerAvatar player={player} size="sm" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">{playerName(player)}</span>
                      <span className="text-[11px] text-muted">{player.position || ""}</span>
                    </span>
                    <span className="text-right">
                      <span className="metric-value block text-xs text-gold">{points(jornadaEv(player))}</span>
                      {priceDeltaView(player) ? (
                        <span
                          className={`metric-value block text-[11px] ${priceDeltaView(player)!.tone}`}
                          title={priceDeltaView(player)!.title}
                        >
                          {priceDeltaView(player)!.text}
                        </span>
                      ) : null}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {excluded.length ? (
            <p className="text-xs leading-5 text-muted">
              Fuera del once:{" "}
              {excluded
                .slice(0, 8)
                .map((player) => `${playerName(player)} (${player.excluded_reason || "fuera"})`)
                .join(" · ")}
            </p>
          ) : null}

          {optimize.calibration_note ? (
            <details className="text-xs text-muted">
              <summary className="cursor-pointer text-muted-strong transition-colors hover:text-ink">
                Cómo se calculan los puntos
              </summary>
              <p className="mt-2 leading-5">{optimize.calibration_note}</p>
            </details>
          ) : null}
        </div>
      </div>
    </article>
  );
}
