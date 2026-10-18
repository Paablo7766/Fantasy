"use client";

import { ErrorCard, Skeleton } from "@/components/Feedback";
import { eur, glass, initials, pct, playerName, points } from "@/lib/format";
import type { Gap, OptimizePayload, Player } from "@/lib/types";

const ROW_Y: Record<string, number> = { DEL: 22, MC: 36, DEF: 66, POR: 86 };

type Token = Player & {
  gap?: boolean;
  label?: string;
  x: number;
  y: number;
};

function xFor(index: number, count: number): number {
  if (count <= 1) return 50;
  const margin = count >= 5 ? 10 : 16;
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
  const share = typeof value === "number" ? Math.max(0, Math.min(100, Math.round(value * 100))) : 0;
  return `conic-gradient(#34d399 ${share}%, rgba(255,255,255,0.16) ${share}%)`;
}

function Silhouette() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden="true">
      <circle cx="12" cy="8" r="3" fill="none" stroke="currentColor" strokeWidth="1.6" strokeDasharray="2.2 1.6" />
      <path d="M6.5 19.2c.8-2.8 2.8-4.2 5.5-4.2s4.7 1.4 5.5 4.2" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

function TokenView({ player }: { player: Token }) {
  if (player.gap) {
    const label = player.label || `Fichar ${player.position || ""}`.trim();
    return (
      <div
        className="token token-gap"
        data-token
        data-gap="true"
        data-position={player.position || ""}
        data-name={label}
        style={{ left: `${player.x}%`, top: `${player.y}%` }}
        title={label}
      >
        <div className="ring">
          <div className="avatar">
            <Silhouette />
          </div>
        </div>
        <div className="name">{label}</div>
        <div className="meta">hueco</div>
      </div>
    );
  }
  const name = playerName(player);
  const status = player.player_status === "doubtful" ? " · duda" : "";
  const estimated = player.p_titular_source === "week_points" ? " est." : "";
  return (
    <div
      className="token"
      data-token
      data-position={player.position || ""}
      data-name={name}
      style={{ left: `${player.x}%`, top: `${player.y}%` }}
      title={`${name} · ${player.position || ""} · titular ${pct(player.p_titular)}${estimated}`}
    >
      <div className="ring" style={{ background: starterRing(player.p_titular) }}>
        <div className="avatar">{initials(name)}</div>
      </div>
      <div className="name">{name}</div>
      <div className="meta">
        {pct(player.p_titular)}
        {estimated}
        {status}
      </div>
    </div>
  );
}

function Chip({ player }: { player: Player }) {
  return (
    <span className="rounded-full border border-white/10 bg-black/20 px-3 py-1 text-xs">
      {player.position || ""} {playerName(player)} · {points(player.expected_points)}
    </span>
  );
}

export function Pitch({
  optimize,
  loading = false,
}: {
  optimize: OptimizePayload | null;
  loading?: boolean;
}) {
  if (loading && !optimize) return <Skeleton title="Alineación" />;
  if (!optimize || optimize.ok === false) {
    return <ErrorCard title="Alineación" payload={optimize || { error: { message: "Sin once calculado." } }} brief />;
  }
  const xi = Array.isArray(optimize.xi) ? optimize.xi : [];
  const gaps = Array.isArray(optimize.gaps) ? optimize.gaps : [];
  const placed = layoutXi(xi, gaps);
  const counts = optimize.partial ? optimize.eligible_counts || optimize.counts || {} : optimize.counts || {};
  const countLine = ["POR", "DEF", "MC", "DEL"].map((pos) => `${pos} ${counts[pos] ?? 0}`).join(" · ");
  const title = optimize.partial ? "Mejor once posible" : "Once óptimo recomendado";
  const bench = Array.isArray(optimize.benched) ? optimize.benched : [];
  const excluded = Array.isArray(optimize.excluded) ? optimize.excluded : [];
  const fills = Array.isArray(optimize.market_fills) ? optimize.market_fills : [];
  const saved = optimize.saved_lineup && optimize.saved_lineup.ok ? optimize.saved_lineup : null;
  const savedIds = new Set((saved?.xi || []).map((player) => String(player.player_id)));
  const recommendedIds = new Set(xi.filter((player) => player.player_id).map((player) => String(player.player_id)));
  const sameXi =
    Boolean(saved) && savedIds.size > 0 && savedIds.size === recommendedIds.size && [...savedIds].every((id) => recommendedIds.has(id));
  const savedNames = saved ? (saved.xi || []).map((player) => playerName(player)).join(", ") : "";

  return (
    <article className={glass("p-4 md:p-5")}>
      <div className="mb-4 flex items-end justify-between gap-3 px-1">
        <div>
          <p className="text-[11px] uppercase tracking-[0.18em] text-white/40">Alineación</p>
          <h2 className="text-xl font-medium">
            {title} {optimize.formation || ""}
          </h2>
          <p className="mt-1 text-xs text-white/45">
            {optimize.manager_name || "Tu plantilla"} · {countLine}
          </p>
        </div>
        <p className="text-right font-mono text-sm text-gold">
          {points(optimize.expected_points)}
          <span className="block text-[10px] uppercase tracking-[0.14em] text-white/40">pts proyectados</span>
        </p>
      </div>
      {optimize.matchday_void ? (
        <p className="mb-3 rounded-2xl border border-rose-300/30 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">
          Jornada a 0 · {voidCopy(optimize.void_reasons)}. Las siluetas con borde discontinuo son los fichajes que faltan.
        </p>
      ) : null}
      <div className="pitch">
        <svg viewBox="0 0 68 105" preserveAspectRatio="none" aria-hidden="true">
          <g fill="none" stroke="rgba(255,255,255,0.72)" strokeWidth="0.45">
            <rect x="1.2" y="1.2" width="65.6" height="102.6" rx="0.4" />
            <line x1="1.2" y1="52.5" x2="66.8" y2="52.5" />
            <circle cx="34" cy="52.5" r="9.15" />
            <circle cx="34" cy="52.5" r="0.6" fill="rgba(255,255,255,0.72)" stroke="none" />
            <rect x="13.84" y="1.2" width="40.32" height="16.5" />
            <rect x="24.84" y="1.2" width="18.32" height="5.5" />
            <rect x="13.84" y="87.3" width="40.32" height="16.5" />
            <rect x="24.84" y="98.3" width="18.32" height="5.5" />
            <circle cx="34" cy="12.5" r="0.55" fill="rgba(255,255,255,0.72)" stroke="none" />
            <circle cx="34" cy="93.5" r="0.55" fill="rgba(255,255,255,0.72)" stroke="none" />
          </g>
        </svg>
        <div className="pitch-xi">
          {placed.map((player, index) => (
            <TokenView key={`${player.player_id || player.label || player.position}-${index}`} player={player} />
          ))}
        </div>
      </div>
      {fills.length ? (
        <div className="mt-4 space-y-2">
          <p className="text-[11px] uppercase tracking-[0.16em] text-white/40">Qué fichar para cerrar el once</p>
          {fills.map((gap, index) => {
            const options = Array.isArray(gap.options) ? gap.options : [];
            return (
              <div key={`${gap.position}-${index}`} className="rounded-2xl border border-rose-300/30 bg-rose-400/5 p-4">
                <p className="text-sm text-rose-200">{gap.label || `Falta ${gap.missing} ${gap.position}`}</p>
                <ul className="mt-1">
                  {options.length ? (
                    options.map((option) => (
                      <li key={String(option.player_id)} className="flex items-center justify-between gap-3 py-1 text-sm">
                        <span className="truncate">{playerName(option)}</span>
                        <span className="font-mono text-xs text-rose-200">{eur(option.sale_price)}</span>
                      </li>
                    ))
                  ) : (
                    <li className="py-1 text-sm text-white/45">Nadie de esa posición tiene precio en el mercado.</li>
                  )}
                </ul>
              </div>
            );
          })}
        </div>
      ) : null}
      {saved ? (
        <div className="mt-4 rounded-2xl border border-white/10 bg-white/[0.03] p-3">
          <p className="text-[11px] uppercase tracking-[0.16em] text-white/40">Alineación guardada en la App</p>
          <p className="mt-1 text-sm">
            {saved.formation || "sin formación"} · {savedNames}
          </p>
          <p className="mt-1 text-xs text-white/45">
            {sameXi ? "Coincide con el once recomendado." : "Distinta del once recomendado por la IA."}
          </p>
        </div>
      ) : (
        <p className="mt-4 text-xs text-white/40">La API no devolvió la alineación guardada en la app.</p>
      )}
      {bench.length ? (
        <div className="mt-4">
          <p className="mb-2 text-[11px] uppercase tracking-[0.16em] text-white/40">Banquillo</p>
          <div className="flex flex-wrap gap-2">
            {bench.map((player) => (
              <Chip key={String(player.player_id)} player={player} />
            ))}
          </div>
        </div>
      ) : null}
      {excluded.length ? (
        <p className="mt-3 text-xs text-white/45">
          Fuera del once:{" "}
          {excluded
            .slice(0, 8)
            .map((player) => `${playerName(player)} (${player.excluded_reason || "fuera"})`)
            .join(" · ")}
        </p>
      ) : null}
      {optimize.calibration_note ? (
        <details className="mt-4 text-xs text-white/45">
          <summary className="cursor-pointer text-white/55">Cómo se calculan los puntos</summary>
          <p className="mt-2 leading-5">{optimize.calibration_note}</p>
        </details>
      ) : null}
    </article>
  );
}
