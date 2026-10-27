"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { endpoint, getJson } from "@/lib/api";
import { eur, points } from "@/lib/format";
import type { LeagueRacePayload, LeagueRaceRow } from "@/lib/types";

const MODE_TONE: Record<string, string> = {
  ventaja: "badge badge--good",
  remontada: "badge badge--warn",
  neutro: "badge",
  sin_tabla: "badge",
};

function thinLabel(positions: string[] | undefined): string | null {
  if (!positions?.length) return null;
  return positions.join(" · ");
}

function projection(row: LeagueRaceRow): string {
  const expected = row.projection?.expected_points;
  if (typeof expected !== "number") return "sin proyección";
  return `${points(expected)} pts`;
}

/** Contexto de liga: brecha, postura, huecos rivales y valor de negación. */
export function LeagueRacePanel() {
  const search = useSearchParams();
  const league = search.get("league");
  // Se guarda con la liga de la que salió: así «cargando» es una comparación,
  // no un estado que haya que sembrar desde el efecto.
  const [loaded, setLoaded] = useState<{ league: string | null; payload: LeagueRacePayload } | null>(null);
  const payload = loaded && loaded.league === league ? loaded.payload : null;
  const loading = payload === null;

  useEffect(() => {
    let cancelled = false;
    getJson<LeagueRacePayload>(endpoint("/api/league-race", league))
      .then((value) => {
        if (!cancelled) setLoaded({ league, payload: value });
      })
      .catch(() => {
        if (!cancelled) {
          setLoaded({ league, payload: { ok: false, error: { message: "Sin /api/league-race." } } });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [league]);

  const rivals = useMemo(() => (Array.isArray(payload?.rivals) ? payload!.rivals! : []), [payload]);
  const denial = useMemo(() => (Array.isArray(payload?.denial) ? payload!.denial! : []), [payload]);
  const thin = useMemo(
    () => rivals.filter((row) => (row.thin_positions || []).length > 0).slice(0, 6),
    [rivals],
  );

  if (loading && !payload) {
    return (
      <section className="rounded-2xl border border-[color:var(--line)] bg-[color:var(--surface)] p-4 md:p-5">
        <p className="eyebrow">Carrera de liga</p>
        <div className="mt-3 h-20 animate-pulse rounded-xl bg-white/5" />
      </section>
    );
  }

  if (!payload || payload.ok === false) {
    return null;
  }

  const mode = payload.mode;
  const mine = payload.my_projection;
  const league_avg = payload.league_projection;

  return (
    <section className="rounded-2xl border border-[color:var(--line)] bg-[color:var(--surface)] p-4 md:p-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <p className="eyebrow">Carrera de liga</p>
          <h2 className="section-title mt-1 text-[1.05rem]">
            {mode?.label || "Sin postura"} · {payload.headline || "sin brecha"}
          </h2>
          <p className="section-support">
            La postura cambia el once: en ventaja se protege el suelo; en remontada se busca techo.
          </p>
        </div>
        <span className={MODE_TONE[mode?.name || ""] || "badge"}>{mode?.name || "sin tabla"}</span>
      </div>

      <dl className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-3 py-2">
          <dt className="metric-label">Tu proyección</dt>
          <dd className="metric-value mt-0.5 text-lg">{projection({ projection: mine })}</dd>
          <dd className="text-[11px] text-muted">{mine?.formation || "formación s/d"}</dd>
        </div>
        <div className="rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-3 py-2">
          <dt className="metric-label">Media de la liga</dt>
          <dd className="metric-value mt-0.5 text-lg">
            {typeof league_avg === "number" ? `${points(league_avg)} pts` : "s/d"}
          </dd>
          <dd className="text-[11px] text-muted">proyección media de los rivales</dd>
        </div>
        <div className="rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-3 py-2">
          <dt className="metric-label">Brecha con el líder</dt>
          <dd className="metric-value mt-0.5 text-lg">
            {typeof mode?.gap_to_leader === "number"
              ? `${mode.gap_to_leader > 0 ? "+" : ""}${mode.gap_to_leader} pts`
              : "s/d"}
          </dd>
          <dd className="text-[11px] text-muted">{mode?.leader?.manager_name || "líder s/d"}</dd>
        </div>
        <div className="rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-3 py-2">
          <dt className="metric-label">Valor de negación</dt>
          <dd className="metric-value mt-0.5 text-lg">{denial.length}</dd>
          <dd className="text-[11px] text-muted">fichajes que le duelen a un rival directo</dd>
        </div>
      </dl>

      {thin.length ? (
        <div className="mt-5">
          <p className="eyebrow">Huecos que puedes atacar</p>
          <ul className="mt-2 grid gap-2 sm:grid-cols-2">
            {thin.map((row) => (
              <li
                key={String(row.team_id)}
                className="rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-3 py-2"
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate text-sm font-medium">{row.manager_name || row.fantasy_team_name || "Rival"}</span>
                  <span className="metric-value shrink-0 text-xs text-muted">{projection(row)}</span>
                </div>
                <p className="mt-0.5 text-[11px] text-gold">{thinLabel(row.thin_positions)}</p>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {denial.length ? (
        <div className="mt-5">
          <p className="eyebrow">No se lo dejes</p>
          <p className="section-support">Rivales con esa posición floja y caja para pagar el precio de salida.</p>
          <ul className="mt-2 divide-y divide-[color:var(--line)] rounded-xl border border-[color:var(--line)]">
            {denial.slice(0, 6).map((row) => (
              <li key={String(row.player_id)} className="flex items-baseline justify-between gap-3 px-3 py-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">
                    {row.nickname || row.name || "Jugador"}
                    {row.position ? <span className="ml-1.5 text-[11px] text-faint">{row.position}</span> : null}
                  </p>
                  <p className="truncate text-[11px] text-muted">{(row.managers || []).join(" · ")}</p>
                </div>
                <span className="metric-value shrink-0 text-xs text-muted">
                  {typeof row.sale_price === "number" ? eur(row.sale_price) : row.label || "s/d"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
