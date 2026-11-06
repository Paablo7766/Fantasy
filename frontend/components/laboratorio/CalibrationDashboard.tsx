"use client";

import { cachedJson, peekJson } from "@/lib/core/jsonCache";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useDashboard } from "@/components/DashboardProvider";
import { ErrorCard, Skeleton } from "@/components/ui/Feedback";
import { endpoint } from "@/lib/core/api";
import { points } from "@/lib/core/format";
import { TONE } from "@/components/ui/kit";
import type { CalibrationPayload } from "@/lib/types";

function payloadSeeded(embedded: CalibrationPayload | null | undefined, league: string | null): boolean {
  return Boolean(embedded || peekJson(endpoint("/api/calibration", league)));
}

export function CalibrationDashboard() {
  const search = useSearchParams();
  const queryLeague = search.get("league");
  const { trends, load, busy, refresh } = useDashboard();
  const leagueForApi = trends?.league_id || queryLeague;
  const [payload, setPayload] = useState<CalibrationPayload | null>(
    () => trends?.calibration ?? peekJson<CalibrationPayload>(endpoint("/api/calibration", leagueForApi)) ?? null,
  );
  const [loading, setLoading] = useState(() => !payloadSeeded(trends?.calibration, leagueForApi));
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
        const data = await cachedJson<CalibrationPayload>(endpoint("/api/calibration", leagueForApi));
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
  const stability = payload.plan_stability;
  const jornadas = pointsBlock?.jornadas || [];
  const snapCount = payload.coverage?.price_snapshots ?? 0;
  const buyCount = payload.coverage?.activity_buys ?? 0;
  const emptyStore = snapCount === 0 && buyCount === 0;

  const score = typeof payload.engine_confidence?.score === "number" ? payload.engine_confidence.score : null;
  const band = payload.engine_confidence?.band ?? null;
  const verdict =
    band === "alta"
      ? { label: "Te puedes fiar", text: "Sus previsiones han acertado lo suficiente como para seguirlas.", color: TONE.green }
      : band === "media"
        ? { label: "Fíate con cuidado", text: "Acierta a menudo, pero contrasta las decisiones grandes.", color: TONE.amber }
        : band === "baja"
          ? { label: "Aún no te fíes a ciegas", text: "Tiene pocos datos todavía: úsalo como orientación, no como verdad.", color: TONE.red }
          : { label: "Sin datos suficientes", text: "Hace falta jugar más jornadas para medir cuánto acierta.", color: TONE.gray };
  const maxMae = Math.max(1, ...jornadas.map((row) => (typeof row.mae === "number" ? row.mae : 0)));
  const trendWord: Record<string, string> = { improving: "mejorando", worsening: "empeorando", stable: "estable" };
  const trend = trendWord[String(pointsBlock?.trend)] ?? null;
  const cards: { title: string; value: string; text: string; color?: string }[] = [
    {
      title: "Puntos previstos",
      value: typeof pointsBlock?.overall_mae === "number" ? `± ${points(pointsBlock.overall_mae)} pts` : "—",
      text:
        typeof pointsBlock?.overall_mae === "number"
          ? `Es lo que falla de media por jugador y jornada${trend ? `, y va ${trend}` : ""}.`
          : "Se mide cuando termina una jornada.",
    },
    {
      title: "Pujas recomendadas",
      value: typeof pujar?.resolved === "number" && pujar.resolved > 0 ? `${pujar.hits ?? 0} de ${pujar.resolved}` : "—",
      text:
        typeof pujar?.resolved === "number" && pujar.resolved > 0
          ? `ganadas sin pagar de más${pujar.lost ? ` · ${pujar.lost} perdidas` : ""}${pujar.overbid ? ` · ${pujar.overbid} pagando de más` : ""}.`
          : "Aún no se ha cerrado ninguna puja que recomendara.",
      color: typeof pujar?.hit_rate_pct === "number" ? (pujar.hit_rate_pct >= 50 ? TONE.green : TONE.amber) : undefined,
    },
    {
      title: "Avisos de vender en máximo",
      value: typeof crest?.accuracy_pct === "number" ? `${Math.round(crest.accuracy_pct)} %` : "—",
      text:
        typeof crest?.signals === "number" && crest.signals > 0
          ? `de ${crest.signals} avisos acertaron: el precio cayó en las 48 h siguientes.`
          : "Todavía no ha dado ningún aviso de venta.",
      color: typeof crest?.accuracy_pct === "number" ? (crest.accuracy_pct >= 50 ? TONE.green : TONE.amber) : undefined,
    },
    {
      title: "Estabilidad del plan",
      value: typeof stability?.cambio_medio === "number" ? `${Math.round(stability.cambio_medio * 100)} %` : "—",
      text:
        typeof stability?.cambio_medio === "number"
          ? "de los objetivos cambia de un día para otro. Cuanto más bajo, más coherente."
          : "Hacen falta dos días de plan guardados.",
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      <section className="home-glass flex flex-wrap items-center gap-5 p-5">
        <span className="relative grid h-[5.5rem] w-[5.5rem] shrink-0 place-items-center">
          <svg viewBox="0 0 36 36" className="absolute inset-0 h-full w-full -rotate-90" aria-hidden="true">
            <circle cx="18" cy="18" r="15.5" fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="3" />
            <circle cx="18" cy="18" r="15.5" fill="none" stroke={verdict.color} strokeWidth="3" strokeLinecap="round" strokeDasharray={`${((score ?? 0) / 100) * 97.4} 97.4`} />
          </svg>
          <span className="text-center leading-none">
            <span className="block text-[1.6rem] font-semibold tabular-nums text-white">{score ?? "—"}</span>
            <span className="mt-0.5 block text-[10.5px] text-white/45">de 100</span>
          </span>
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-medium text-white/60">¿Me fío del modelo?</p>
          <p className="mt-1 text-[1.35rem] font-semibold leading-tight tracking-tight" style={{ color: verdict.color }}>
            {verdict.label}
          </p>
          <p className="mt-1 text-[13.5px] leading-snug text-white/60">{verdict.text}</p>
        </div>
        {emptyStore ? (
          <p className="w-full text-[12.5px] text-white/45">Todavía no hay histórico guardado. Se va llenando solo cada vez que se actualiza la foto.</p>
        ) : null}
      </section>

      <section className="grid gap-2.5 sm:grid-cols-2">
        {cards.map((card) => (
          <div key={card.title} className="home-glass p-4">
            <p className="text-[12.5px] font-medium text-white/55">{card.title}</p>
            <p className="mt-1.5 text-[1.5rem] font-semibold leading-none tabular-nums" style={{ color: card.color || "#fff" }}>
              {card.value}
            </p>
            <p className="mt-2 text-[12.5px] leading-snug text-white/50">{card.text}</p>
          </div>
        ))}
      </section>

      <section className="home-glass p-5">
        <p className="text-[13px] font-medium text-white/60">Jornada a jornada</p>
        <p className="mt-0.5 text-[12px] text-white/40">Puntos que falla de media por jugador. Barra más corta = mejor.</p>
        {jornadas.length ? (
          <ul className="mt-4 flex flex-col gap-3">
            {jornadas.map((row) => (
              <li key={row.jornada_id} className="!bg-transparent">
                <div className="flex items-baseline justify-between text-[13px]">
                  <span className="text-white/70">Jornada {row.jornada_id}</span>
                  <span className="tabular-nums text-white">
                    {typeof row.mae === "number" ? `± ${points(row.mae)} pts` : "—"}
                    <span className="ml-2 text-white/40">{row.scored ?? 0} jugadores</span>
                  </span>
                </div>
                <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-white/[0.07]">
                  <span className="block h-full rounded-full" style={{ width: `${typeof row.mae === "number" ? (row.mae / maxMae) * 100 : 0}%`, background: TONE.copper }} />
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-3 text-[13px] text-white/50">Aún no hay jornadas evaluadas.</p>
        )}
      </section>

      <p className="flex flex-wrap items-center justify-between gap-2 px-1 text-[12px] text-white/35">
        <span>
          Basado en {snapCount} fotos de precios, {buyCount} compras y {payload.coverage?.matchday_jornadas ?? 0} jornadas.
        </span>
        <button type="button" className="text-white/55 hover:text-white" onClick={() => void refresh()}>
          Actualizar datos
        </button>
      </p>
    </div>
  );
}
