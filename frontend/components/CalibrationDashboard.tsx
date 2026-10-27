"use client";

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useDashboard } from "@/components/DashboardProvider";
import { ErrorCard, Skeleton } from "@/components/Feedback";
import { ModelConfidenceBadge } from "@/components/ModelConfidenceBadge";
import { endpoint, getJson } from "@/lib/api";
import { glass, pct, points } from "@/lib/format";
import type { CalibrationPayload } from "@/lib/types";

function Metric({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-xl bg-[color:var(--surface)] px-4 py-3">
      <p className="text-[11px] uppercase tracking-wide text-faint">{label}</p>
      <p className="metric-value mt-1 text-xl">{value}</p>
      {hint ? <p className="mt-1 text-xs text-muted">{hint}</p> : null}
    </div>
  );
}

function trendLabel(trend: string | null | undefined): string {
  if (trend === "improving") return "Mejora";
  if (trend === "worsening") return "Empeora";
  if (trend === "stable") return "Estable";
  return "Sin tendencia";
}

export function CalibrationDashboard() {
  const search = useSearchParams();
  const queryLeague = search.get("league");
  const query = search.toString();
  const calibracionHref = query ? `/calibracion?${query}` : "/calibracion";
  const { trends, load, busy, refresh } = useDashboard();
  const leagueForApi = trends?.league_id || queryLeague;
  const [payload, setPayload] = useState<CalibrationPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);

  const applyPayload = useCallback((data: CalibrationPayload | null | undefined) => {
    if (data && data.ok !== false) {
      setPayload(data);
      setFetchError(null);
      return true;
    }
    return false;
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function run() {
      setLoading(true);
      if (applyPayload(trends?.calibration ?? undefined)) {
        if (!cancelled) setLoading(false);
        return;
      }
      if (!trends && !busy) {
        await load();
      }
      if (cancelled) return;
      const embedded = trends?.calibration;
      if (applyPayload(embedded ?? undefined)) {
        setLoading(false);
        return;
      }
      try {
        const data = await getJson<CalibrationPayload>(endpoint("/api/calibration", leagueForApi));
        if (!cancelled) {
          applyPayload(data);
          setFetchError(null);
        }
      } catch (reason: unknown) {
        if (cancelled) return;
        const message = reason instanceof Error ? reason.message : "Sin datos.";
        setFetchError(message);
        const err =
          typeof reason === "object" && reason !== null && "payload" in reason
            ? (reason as { payload: CalibrationPayload }).payload
            : { ok: false, error: { message } };
        setPayload(err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void run();
    return () => {
      cancelled = true;
    };
  }, [applyPayload, busy, leagueForApi, load, trends, trends?.calibration]);

  if (loading && !payload) return <Skeleton title="Calibración" rows={10} />;
  if (!payload || payload.ok === false) {
    const hint =
      fetchError && /404|Not Found/i.test(fetchError)
        ? " El backend en el puerto 8000 no tiene la ruta nueva: reinicia con python run_dashboard.py (o uvicorn server:app --reload --port 8000)."
        : "";
    return (
      <ErrorCard
        title="Calibración"
        payload={payload || { error: { message: `Sin métricas.${hint}` } }}
        brief
      />
    );
  }

  const pointsBlock = payload.points;
  const crest = payload.sell_at_crest;
  const pujar = payload.pujar;
  const win = payload.win_probability;
  const jornadas = pointsBlock?.jornadas || [];
  const snapCount = payload.coverage?.price_snapshots ?? 0;
  const buyCount = payload.coverage?.activity_buys ?? 0;
  const emptyStore = snapCount === 0 && buyCount === 0;

  return (
    <div className="flex flex-col gap-6">
      <section className={glass("p-4 md:p-5")}>
        <p className="eyebrow">Calibración</p>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h2 className="section-title">Precisión del motor</h2>
          <ModelConfidenceBadge confidence={payload.engine_confidence} />
        </div>
        <p className="section-support mt-2">
          Cruce de snapshots E[pts], veredictos PUJAR guardados, señales SELL_AT_CREST y calibración de P(ganar) sobre
          compras históricas de la liga. Los datos vienen del mismo backend que Mercado (campo{" "}
          <code className="text-xs">calibration</code> en trends). El servidor guarda un snapshot de E[pts] al día
          y cruza puntos reales cuando ya están en plantilla; la confianza se recalcula sola (caché ~5 min).
        </p>
        {emptyStore ? (
          <p className="mt-3 rounded-lg border border-[color:var(--line)] bg-[color:var(--surface)] px-3 py-2 text-sm text-muted-strong">
            Sin histórico en la caché del backend. Abre <strong>Mercado</strong> una vez (sync de precios) y reinicia el
            tablero Python si acabas de actualizar:{" "}
            <code className="text-xs">python run_dashboard.py</code>. En la URL usa el id real de liga si puedes (
            {trends?.league_id ? (
              <code className="text-xs">?league={trends.league_id}</code>
            ) : (
              "p. ej. 018668579"
            )}
            ).
          </p>
        ) : null}
        {(payload.engine_confidence?.notes || []).length ? (
          <ul className="mt-3 list-disc pl-5 text-sm text-muted-strong">
            {(payload.engine_confidence?.notes || []).map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        ) : null}
      </section>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Metric
          label="MAE puntos (plantilla)"
          value={typeof pointsBlock?.overall_mae === "number" ? points(pointsBlock.overall_mae) : "—"}
          hint={`Tendencia: ${trendLabel(pointsBlock?.trend)}${
            typeof pointsBlock?.delta_mae_recent === "number"
              ? ` (Δ ${pointsBlock.delta_mae_recent > 0 ? "+" : ""}${pointsBlock.delta_mae_recent})`
              : ""
          }`}
        />
        <Metric
          label="Hit rate PUJAR"
          value={
            typeof pujar?.hit_rate_pct === "number"
              ? `${pujar.hit_rate_pct}%`
              : pujar?.pending
                ? "En curso"
                : "—"
          }
          hint={
            typeof pujar?.resolved === "number" && pujar.resolved > 0
              ? `${pujar.hits} aciertos · ${pujar.lost} perdidas · ${pujar.overbid} sobrepuja`
              : "Se rellena al guardar veredictos y cerrar mercados"
          }
        />
        <Metric
          label="SELL_AT_CREST"
          value={
            typeof crest?.accuracy_pct === "number" ? `${crest.accuracy_pct}%` : crest?.signals ? "0%" : "—"
          }
          hint={
            typeof crest?.signals === "number"
              ? `${crest.signals} señales · caída en ≤48h`
              : "Sin señales en price_snapshots"
          }
        />
        <Metric
          label="P(ganar) · Brier"
          value={typeof win?.brier === "number" ? win.brier.toFixed(3) : "—"}
          hint={
            typeof win?.samples === "number" && win.samples > 0
              ? `${win.samples} contrastes ganador/rival`
              : "Hacen falta compras con valor de referencia"
          }
        />
      </section>

      <section className={glass("p-4 md:p-5")}>
        <p className="eyebrow">Tendencia por jornada</p>
        <h3 className="section-title mt-1 text-[1.05rem]">E[pts] vs puntos reales</h3>
        {jornadas.length ? (
          <div className="mt-4 overflow-x-auto">
            <table className="table-dense w-full min-w-[520px] text-left text-sm">
              <thead>
                <tr>
                  <th>Jornada</th>
                  <th className="text-right">MAE</th>
                  <th className="text-right">Jugadores</th>
                  <th className="text-right">Rotura techo P90</th>
                </tr>
              </thead>
              <tbody>
                {jornadas.map((row) => (
                  <tr key={row.jornada_id}>
                    <td>J{row.jornada_id}</td>
                    <td className="metric-value text-right">{typeof row.mae === "number" ? points(row.mae) : "—"}</td>
                    <td className="text-right text-muted">{row.scored ?? "—"}</td>
                    <td className="text-right text-muted">
                      {typeof row.ceiling_break_rate === "number" ? pct(row.ceiling_break_rate) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="mt-3 text-sm text-muted">
            Aún no hay jornadas evaluadas. Ejecuta{" "}
            <code className="text-xs">python scripts/track_matchday.py --snapshot</code> antes del partido y{" "}
            <code className="text-xs">--evaluate</code> después.
          </p>
        )}
      </section>

      {win?.bins?.length ? (
        <section className={glass("p-4 md:p-5")}>
          <p className="eyebrow">Subastas</p>
          <h3 className="section-title mt-1 text-[1.05rem]">Calibración de P(ganar)</h3>
          <p className="section-support">Frecuencia observada frente a la predicción por deciles (compras reales).</p>
          <table className="table-dense mt-4 w-full min-w-[480px] text-left text-sm">
            <thead>
              <tr>
                <th>Bin predicho</th>
                <th className="text-right">N</th>
                <th className="text-right">Media pred.</th>
                <th className="text-right">Tasa real</th>
              </tr>
            </thead>
            <tbody>
              {win.bins.map((bin) => (
                <tr key={`${bin.lo}-${bin.hi}`}>
                  <td>
                    {pct(bin.lo ?? 0)} – {pct(bin.hi ?? 0)}
                  </td>
                  <td className="text-right">{bin.count}</td>
                  <td className="text-right">{typeof bin.mean_predicted === "number" ? pct(bin.mean_predicted) : "—"}</td>
                  <td className="text-right">{typeof bin.observed_rate === "number" ? pct(bin.observed_rate) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}

      <p className="text-xs text-faint">
        Cobertura: {snapCount} snapshots · {buyCount} compras · {payload.coverage?.matchday_jornadas ?? 0} jornadas
        evaluadas
        {payload.database ? ` · ${payload.database}` : ""}.{" "}
        <button
          type="button"
          className="text-info underline-offset-2 hover:underline"
          onClick={() => void refresh()}
        >
          Descargar datos
        </button>
        {" · "}
        <a href={calibracionHref} className="text-info underline-offset-2 hover:underline">
          Recargar
        </a>
      </p>
    </div>
  );
}
