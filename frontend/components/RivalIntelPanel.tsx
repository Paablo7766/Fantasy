"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { endpoint, getJson } from "@/lib/api";
import { eur, eurShort } from "@/lib/format";
import { liquidityRead, temperatureClasses } from "@/lib/liquidity";
import type { RivalFinancialTeam, RivalIntelPayload } from "@/lib/types";

const CONFIDENCE_LABEL: Record<string, string> = {
  high: "alta",
  medium: "media",
  low: "baja",
};

const CONFIDENCE_TONE: Record<string, string> = {
  high: "badge badge--good",
  medium: "badge badge--warn",
  low: "badge badge--bad",
};

const BASIS_LABEL: Record<string, string> = {
  fichado: "precio de fichaje",
  valor_mercado: "valor de mercado",
  campo_oculto: "campo oculto",
  snapshot: "captura",
};

function nameOf(team: RivalFinancialTeam): string {
  return team.manager_name || team.fantasy_team_name || "Rival";
}

function TeamRow({
  team,
  open,
  onToggle,
}: {
  team: RivalFinancialTeam;
  open: boolean;
  onToggle: () => void;
}) {
  const hidden = team.detected_hidden_expenses || [];
  const expenses = team.hidden_expenses_eur ?? 0;
  const read = liquidityRead(null, team);
  const tone = temperatureClasses(read.level);
  return (
    <>
      <tr className={hidden.length ? "row-link row-link--open" : ""}>
        <td>
          <button type="button" onClick={onToggle} className="flex w-full items-center gap-2 text-left">
            <span className="metric-value w-5 shrink-0 text-[11px] text-faint">
              {typeof team.rank === "number" ? team.rank : "—"}
            </span>
            <span className="min-w-0">
              <span className="block truncate font-medium tracking-tight">{nameOf(team)}</span>
              <span className="block truncate text-[11px] text-muted">
                {team.is_self ? "Tú" : `${team.players ?? "?"} jugadores`}
                {hidden.length ? ` · ${hidden.length} gastos fuera de libro` : ""}
              </span>
            </span>
          </button>
        </td>
        <td className="text-right">
          <span className={`metric-value text-sm ${tone.text}`}>
            {eurShort(team.cash_expected_eur ?? read.calibratedCash)}
          </span>
          {typeof team.cash_floor_eur === "number" && typeof team.calculated_cash === "number" ? (
            <span className="mt-0.5 block text-[10.5px] text-faint">
              banda {eurShort(team.cash_floor_eur)} – {eurShort(team.calculated_cash)}
              {typeof team.ad_bounds?.own_rate_pct === "number"
                ? ` · vídeo ${team.ad_bounds.own_rate_pct} %`
                : ""}
            </span>
          ) : read.tightened ? (
            <span className="mt-0.5 block text-[10.5px] text-faint">
              <s className="decoration-[color:var(--line-strong)]">{eurShort(team.calculated_cash)}</s> ·{" "}
              <span className={tone.text}>calibrada</span>
            </span>
          ) : team.cash_is_upper_bound ? (
            <span className="mt-0.5 block text-[10.5px] text-warn">cota superior</span>
          ) : null}
        </td>
        <td className="text-right">
          <span className={`metric-value text-sm ${expenses ? "text-coral" : "text-faint"}`}>
            {expenses ? eurShort(expenses) : "—"}
          </span>
          {hidden.length ? <span className="mt-0.5 block text-[10.5px] text-faint">detectado</span> : null}
        </td>
        <td className="text-right">
          <span className={`metric-value text-sm ${tone.text}`}>{eurShort(read.bidLimit)}</span>
          {read.bidTightened ? (
            <span className="mt-0.5 block text-[10.5px] text-faint">
              <s className="decoration-[color:var(--line-strong)]">{eurShort(team.max_bid_limit)}</s> calibrada
            </span>
          ) : null}
        </td>
        <td>
          <span className={CONFIDENCE_TONE[team.confidence || ""] || "badge"}>
            {CONFIDENCE_LABEL[team.confidence || ""] || team.confidence || "s/d"}
          </span>
        </td>
      </tr>
      {open ? (
        <tr>
          <td colSpan={5} className="bg-[color:var(--surface-strong)]">
            <div className="grid gap-3 px-1 py-2 md:grid-cols-2">
              <div>
                <p className="eyebrow">Reconstrucción de caja</p>
                <dl className="mt-1.5 space-y-1 text-[11.5px]">
                  {(
                    [
                      ["Presupuesto inicial", team.breakdown?.initial_budget_eur],
                      ["Primas", team.breakdown?.premiums_eur],
                      ["Ventas", team.breakdown?.sales_eur],
                      ["Compras", team.breakdown?.purchases_eur],
                      ["Cláusulas", team.breakdown?.clauses_eur],
                      ["Subidas de cláusula", team.breakdown?.clause_raises_eur],
                      ["Ingresos publicidad", team.breakdown?.ad_revenue_eur],
                    ] as const
                  )
                    .filter(([, value]) => typeof value === "number")
                    .map(([label, value]) => (
                      <div key={label} className="flex items-baseline justify-between gap-3">
                        <dt className="text-muted">{label}</dt>
                        <dd className="metric-value text-ink">{eur(value)}</dd>
                      </div>
                    ))}
                  {team.breakdown?.ad_days ? (
                    <p className="text-[10.5px] text-faint">
                      Publicidad calculada sobre {team.breakdown.ad_days} días.
                    </p>
                  ) : null}
                </dl>
                {team.ad_bounds ? (
                  <div className="mt-2 space-y-1 border-t border-[color:var(--line)] pt-2 text-[11px] leading-4 text-muted">
                    <p className="flex items-baseline justify-between gap-3">
                      <span className="text-faint">Caja por día de vídeo</span>
                      <span className="metric-value text-ink">
                        {eurShort(team.cash_floor_eur)} – {eurShort(team.calculated_cash)}
                      </span>
                    </p>
                    <p className="flex items-baseline justify-between gap-3">
                      <span className="text-faint">Vídeo diario (banda)</span>
                      <span className="metric-value text-ink">
                        {eurShort(team.ad_bounds.min_ad_eur)} – {eurShort(team.ad_bounds.max_ad_eur)}
                      </span>
                    </p>
                    <p className="text-faint">
                      {team.ad_bounds.days ?? 0} días posibles · esperado{" "}
                      {eurShort(team.ad_bounds.expected_ad_eur)}
                      {typeof team.ad_bounds.own_rate_pct === "number"
                        ? ` · tu tasa ${team.ad_bounds.own_rate_pct} %`
                        : " · sin tasa propia calibrada"}
                      .
                    </p>
                    {team.ad_bounds.forced_by_balance ? (
                      <p className="text-warn">
                        El libro queda en {eurShort(team.ad_bounds.lowest_book_balance_eur)}: sin vídeos no se
                        explica, así que el suelo son {eurShort(team.ad_bounds.min_ad_eur)}.
                      </p>
                    ) : null}
                    {team.ad_bounds.no_score_reasons?.length ? (
                      <p className="text-faint">
                        Sin puntuar por {team.ad_bounds.no_score_reasons.join(", ")}.
                      </p>
                    ) : null}
                    {team.ad_bounds.team_start_day ? (
                      <p className="text-faint">Entró en la liga el {team.ad_bounds.team_start_day}.</p>
                    ) : null}
                  </div>
                ) : null}
                {team.reconciliation ? (
                  <div className="mt-2 space-y-1 text-[11px] leading-4 text-muted">
                    <p>
                      Caja observada {eurShort(team.reconciliation.observed_cash_eur)}
                      {typeof team.reconciliation.gap_eur === "number"
                        ? ` · hueco ${eurShort(team.reconciliation.gap_eur)}`
                        : ""}
                      {team.reconciliation.underestimated ? " · la reconstrucción se queda corta" : ""}
                      {team.reconciliation.covers_observed ? " · cubre lo observado" : ""}.
                    </p>
                    {read.temperaturePct !== null ? (
                      <p className="flex flex-wrap items-center gap-1.5">
                        <span className="text-faint">Termómetro</span>
                        <span className="h-1.5 w-16 overflow-hidden rounded-full bg-[color:var(--line)]">
                          <span
                            className={`block h-full rounded-full ${tone.bar}`}
                            style={{ width: `${Math.max(3, Math.min(100, read.temperaturePct))}%` }}
                          />
                        </span>
                        <span className={`metric-value ${tone.text}`}>{read.temperaturePct} %</span>
                        {typeof team.reconciliation.arbitrage_eur === "number" &&
                        team.reconciliation.arbitrage_eur > 0 ? (
                          <span className="text-coral">
                            · {eurShort(team.reconciliation.arbitrage_eur)} sin explicar
                          </span>
                        ) : null}
                      </p>
                    ) : null}
                    {read.tightened ? (
                      <p className="text-[10.5px] leading-4 text-faint">
                        La cota sobraba: se aprieta de {eur(team.calculated_cash)} a {eur(read.calibratedCash)} (
                        {eurShort(Math.max(0, (team.calculated_cash ?? 0) - (read.calibratedCash ?? 0)))} de descuento).
                      </p>
                    ) : null}
                  </div>
                ) : null}
              </div>
              <div>
                <p className="eyebrow">Gastos fuera de los libros</p>
                {hidden.length ? (
                  <ul className="mt-1.5 divide-y divide-[color:var(--line)] rounded-xl border border-[color:var(--line)]">
                    {hidden.map((row, index) => (
                      <li key={`${row.player_id}-${index}`} className="flex items-baseline justify-between gap-3 px-2.5 py-1.5">
                        <div className="min-w-0">
                          <p className="truncate text-[12px] font-medium">{row.name || "Jugador"}</p>
                          <p className="truncate text-[10.5px] text-muted">
                            {row.position || "—"} · subida de cláusula ·{" "}
                            {BASIS_LABEL[row.basis || ""] || row.basis || "sin base"}
                            {row.source ? ` · ${row.source}` : ""}
                          </p>
                        </div>
                        <span className="metric-value shrink-0 text-[12px] text-coral">{eurShort(row.cost_eur)}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-1.5 text-[11.5px] leading-4 text-muted">
                    Sin subidas de cláusula detectadas para este equipo. La caja calculada se toma como cota superior.
                  </p>
                )}
              </div>
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}

/**
 * Auditoría de caja rival: qué puede pagar cada manager como máximo y cuánto
 * gastó fuera de los libros. Lee ``/api/rival-intel``, que reconstruye desde
 * los libros de la liga y no descarga nada.
 */
export function RivalIntelPanel() {
  const search = useSearchParams();
  const league = search.get("league");
  const [loaded, setLoaded] = useState<{ league: string | null; payload: RivalIntelPayload } | null>(null);
  const [openTeam, setOpenTeam] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getJson<RivalIntelPayload>(endpoint("/api/rival-intel", league))
      .then((payload) => {
        if (!cancelled) setLoaded({ league, payload });
      })
      .catch(() => {
        if (!cancelled) setLoaded({ league, payload: { ok: false, error: { message: "Sin /api/rival-intel." } } });
      });
    return () => {
      cancelled = true;
    };
  }, [league]);

  const payload = loaded && loaded.league === league ? loaded.payload : null;
  const teams = useMemo(() => {
    const rows = payload?.teams ? Object.values(payload.teams) : [];
    return rows.slice().sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99));
  }, [payload]);

  if (payload === null) {
    return (
      <section className="card p-4 md:p-5">
        <p className="eyebrow">Caja forense</p>
        <div className="mt-3 h-24 animate-pulse rounded-xl bg-black/5" />
      </section>
    );
  }

  if (payload.ok === false) {
    return (
      <section className="card p-4 md:p-5">
        <p className="eyebrow">Caja forense</p>
        <h2 className="section-title mt-1 text-[1.05rem]">Sin auditoría de caja</h2>
        <p className="section-support">
          {payload.error?.message || "El endpoint no devolvió la reconstrucción."} Hace falta la foto con los libros de
          la liga; pulsa Actualizar y vuelve a esta pantalla.
        </p>
      </section>
    );
  }

  const totalHidden = teams.reduce((sum, team) => sum + (team.hidden_expenses_eur || 0), 0);
  const capped = teams.filter((team) => team.cash_is_upper_bound).length;
  const calibrated = teams.filter((team) => liquidityRead(null, team).tightened).length;
  const richest = teams.reduce<RivalFinancialTeam | null>((best, team) => {
    if (team.is_self) return best;
    const cash = team.cash_expected_eur ?? liquidityRead(null, team).calibratedCash ?? 0;
    const bestCash = best
      ? best.cash_expected_eur ?? liquidityRead(null, best).calibratedCash ?? 0
      : -1;
    return !best || cash > bestCash ? team : best;
  }, null);

  return (
    <section className="card p-4 md:p-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <p className="eyebrow">Caja forense</p>
          <h2 className="section-title mt-1 text-[1.05rem]">
            {teams.length} equipos reconstruidos
            {totalHidden ? (
              <>
                <span className="mx-2 text-faint">·</span>
                <span className="metric-value text-coral">{eurShort(totalHidden)}</span> fuera de libro
              </>
            ) : null}
          </h2>
          <p className="section-support">
            Presupuesto inicial, primas, ventas, compras, cláusulas y publicidad, con la cota superior de lo que puede
            pujar cada rival. El vídeo diario no deja rastro en la API: la caja se publica como banda entre el mínimo
            demostrable y el máximo posible, con tu tasa de vídeo como punto medio.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <div className="min-w-[7rem] rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-3 py-2">
            <p className="metric-label">Días de ventana</p>
            <p className="metric-value mt-0.5 text-[15px]">{payload.days_elapsed ?? "s/d"}</p>
            <p className="text-[10px] text-faint">
              {eurShort(payload.ad_revenue_per_team_eur)} de tope de publicidad
            </p>
          </div>
          <div className="min-w-[7rem] rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-3 py-2">
            <p className="metric-label">Cota superior</p>
            <p className="metric-value mt-0.5 text-[15px]">{capped}</p>
            <p className="text-[10px] text-faint">equipos con caja techo</p>
          </div>
          <div className="min-w-[8rem] rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-3 py-2">
            <p className="metric-label">Banda de vídeo</p>
            <p className="metric-value mt-0.5 text-[15px]">
              {typeof payload.config?.own_ad_rate_pct === "number"
                ? `${payload.config.own_ad_rate_pct} %`
                : "s/d"}
            </p>
            <p className="text-[10px] text-faint">
              tu tasa · {eurShort(payload.ad_revenue_per_team_eur)} de tope
            </p>
          </div>
          <div className="min-w-[7rem] rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-3 py-2">
            <p className="metric-label">Calibradas</p>
            <p className="metric-value mt-0.5 text-[15px] text-mint">{calibrated}</p>
            <p className="text-[10px] text-faint">cota apretada por control</p>
          </div>
          <div className="min-w-[8rem] rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-3 py-2">
            <p className="metric-label">Rival más rico</p>
            <p className="metric-value mt-0.5 truncate text-[15px]">{richest ? nameOf(richest) : "s/d"}</p>
            <p className="text-[10px] text-faint">
              {richest
                ? eurShort(richest.cash_expected_eur ?? liquidityRead(null, richest).calibratedCash)
                : "sin datos"}
            </p>
          </div>
        </div>
      </div>

      {(payload.warnings || []).length ? (
        <ul className="mt-3 rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-3 py-2 text-[11px] leading-4 text-warn">
          {(payload.warnings || []).map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : null}

      <div className="mt-3 overflow-x-auto rounded-xl border border-[color:var(--line)]">
        <table className="table-dense w-full min-w-[720px] text-left text-sm">
          <thead>
            <tr>
              <th>Manager</th>
              <th className="text-right">Caja esperada</th>
              <th className="text-right">Gasto oculto</th>
              <th className="text-right">Puja máxima</th>
              <th>Confianza</th>
            </tr>
          </thead>
          <tbody>
            {teams.map((team) => {
              const id = String(team.team_id ?? "");
              return (
                <TeamRow
                  key={id}
                  team={team}
                  open={openTeam === id}
                  onToggle={() => setOpenTeam((current) => (current === id ? null : id))}
                />
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="mt-2 text-[11px] text-faint">
        Fuente <span className="font-mono">/api/rival-intel</span> · {payload.days_elapsed ?? 0} días de ventana ·{" "}
        {(payload.activity?.event_count ?? 0)} eventos de liga leídos. El vídeo diario (+100.000 €) no lo publica la
        API: la caja se da como banda entre lo demostrable y el máximo, y la columna central usa tu tasa de vídeo.
      </p>
    </section>
  );
}
