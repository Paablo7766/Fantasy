"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useDashboard } from "@/components/DashboardProvider";
import { apiUrl, endpoint, getJson } from "@/lib/api";
import { buildNetworkReport } from "@/lib/networkReport";
import {
  headlineChip,
  maxSourceCalls,
  perMinute,
  rateBandLabel,
  ratePosition,
  riskReasons,
  shortDuration,
  sourceState,
  stabilityTone,
  statusMixLabel,
  timelineScale,
  usageTone,
  usageVerdict,
} from "@/lib/apiUsage";
import { elapsedLabel } from "@/lib/format";
import { refreshNetworkNote } from "@/lib/refreshStatus";
import type { ApiSourceUsage, ApiUsagePayload, NetworkDiagnosticsPayload, RefreshStatusPayload } from "@/lib/types";

/**
 * Sin auto-recarga: ni ``setInterval`` ni ``revalidateOnFocus``. El medidor se
 * lee al abrir el diálogo y cuando el usuario pulsa «Recargar». El endpoint es
 * RAM y no cuesta peticiones, pero el refresco tampoco debe ser invisible.
 */
function toneText(tone: string): string {
  if (tone === "bad") return "text-coral";
  if (tone === "warn") return "text-gold";
  return "text-mint";
}

function toneBg(tone: string): string {
  if (tone === "bad") return "bg-coral";
  if (tone === "warn") return "bg-gold";
  return "bg-mint";
}

type CopyState = "idle" | "loading" | "done" | "error";

/**
 * Copia al portapapeles la bitácora persistente de red en Markdown.
 * El panel mide RAM (mismo proceso); la auditoría necesita el fichero.
 */
function CopyNetworkReportButton() {
  const [state, setState] = useState<CopyState>("idle");
  const timer = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, []);

  const flash = (next: CopyState) => {
    setState(next);
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setState("idle"), 2200);
  };

  const copy = async () => {
    if (state === "loading") return;
    setState("loading");
    try {
      const payload = await getJson<NetworkDiagnosticsPayload>(apiUrl("/api/diagnostics/network"));
      const text = buildNetworkReport(payload);
      if (!navigator.clipboard?.writeText) throw new Error("El navegador no permite el portapapeles.");
      await navigator.clipboard.writeText(text);
      flash("done");
    } catch {
      flash("error");
    }
  };

  const label =
    state === "done" ? "¡Copiado!" : state === "error" ? "No se pudo copiar" : state === "loading" ? "Copiando…" : "Copiar reporte para IA";

  return (
    <button
      type="button"
      className="btn btn-secondary !px-2.5 !py-1 text-xs"
      onClick={() => void copy()}
      disabled={state === "loading"}
      title="Copia la bitácora .cache/network_logs.jsonl como Markdown para pegarla en una IA"
      aria-live="polite"
    >
      <span className={state === "done" ? "text-mint" : state === "error" ? "text-coral" : undefined}>{label}</span>
    </button>
  );
}

function Stat({
  label,
  value,
  hint,
  tone = "text-ink",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: string;
}) {
  return (
    <div className="rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-3 py-2.5">
      <p className="metric-label">{label}</p>
      <p className={`metric-value mt-1 text-lg ${tone}`}>{value}</p>
      {hint ? <p className="mt-0.5 text-[11px] leading-4 text-faint">{hint}</p> : null}
    </div>
  );
}

function RateGauge({ perMinuteValue }: { perMinuteValue: number }) {
  const position = ratePosition(perMinuteValue);
  return (
    <div className="mt-3">
      <div className="speedo" role="img" aria-label={`${perMinute(perMinuteValue)} de ritmo actual`}>
        <span className="speedo__seg speedo__seg--good" />
        <span className="speedo__seg speedo__seg--calm" />
        <span className="speedo__seg speedo__seg--warn" />
        <span className="speedo__seg speedo__seg--bad" />
        <span className="speedo__marker" style={{ left: `${position * 100}%` }} />
      </div>
      <div className="mt-1.5 flex justify-between text-[10px] font-semibold uppercase tracking-[0.08em] text-faint">
        <span>0</span>
        <span>30 bajo</span>
        <span>60 normal</span>
        <span>100 alto</span>
        <span>160+</span>
      </div>
    </div>
  );
}

function Timeline({ usage }: { usage: ApiUsagePayload }) {
  const points = usage.timeline || [];
  const scale = timelineScale(points);
  return (
    <div className="mt-2 rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] p-3">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-sm font-semibold text-ink">Últimos 12 minutos</p>
        <span className="text-[11px] text-faint">llamadas por minuto</span>
      </div>
      <div className="mt-2 flex h-16 items-end gap-1">
        {points.map((point) => {
          const height = Math.max(3, Math.round((point.calls / scale) * 100));
          return (
            <div key={point.minutes_ago} className="group relative flex h-full flex-1 items-end">
              <span
                className={`w-full rounded-t-[3px] ${point.calls > 0 ? "bg-mint/70" : "bg-[color:var(--line)]"}`}
                style={{ height: `${height}%` }}
                title={`${point.label}: ${point.calls} llamadas`}
              />
            </div>
          );
        })}
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-faint">
        <span>hace 12 min</span>
        <span>ahora</span>
      </div>
    </div>
  );
}

function SourceRow({ row, peak }: { row: ApiSourceUsage; peak: number }) {
  const state = sourceState(row);
  const width = Math.max(2, Math.round(((row.calls_10m || 0) / peak) * 100));
  return (
    <li className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 px-3 py-2.5">
      <div className="min-w-0">
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate text-sm font-medium text-ink">{row.label}</span>
          <span className="font-mono text-xs tabular-nums text-muted">
            {row.calls_10m} / 10 min · {row.calls_1m} / min
          </span>
        </div>
        <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-[color:var(--line)]">
          <div
            className={`h-full rounded-full ${toneBg(state.tone)}`}
            style={{ width: `${width}%`, opacity: state.tone === "good" ? 0.55 : 0.9 }}
          />
        </div>
        {row.budget_per_minute ? (
          <p className="mt-1 text-[10.5px] text-faint">
            Cupo público ~{Math.round(row.budget_per_minute)}/min
            {typeof row.utilization_pct === "number" ? ` · usando ${row.utilization_pct} %` : ""}
          </p>
        ) : null}
        {row.not_found > 0 ? (
          <p className="mt-0.5 text-[10.5px] text-faint">
            {row.not_found} 404 al probar endpoints de respaldo (no es un fallo)
          </p>
        ) : null}
        {(row.recovered ?? 0) > 0 ? (
          <p className="mt-0.5 text-[10.5px] text-faint">
            {row.recovered} 5xx que el siguiente intento resolvió
          </p>
        ) : null}
      </div>
      <div className="flex flex-col items-end gap-1">
        <span className={state.tone === "good" ? "badge badge--good" : `badge badge--${state.tone === "bad" ? "bad" : "warn"}`}>
          {state.label}
        </span>
        {row.avg_ms ? <span className="font-mono text-[10px] text-faint">{Math.round(row.avg_ms)} ms</span> : null}
      </div>
    </li>
  );
}

/**
 * Qué está haciendo la descarga **ahora mismo**: fase, tiempo y llamadas.
 *
 * Sin esto, durante media hora el usuario solo tenía «Actualizando…» y el
 * contador de llamadas quieto (el medidor solo se leía al abrir el diálogo).
 * Este bloque se alimenta del latido del backend, que es RAM pura.
 */
function LiveStrip({ status, refreshing }: { status: RefreshStatusPayload | null; refreshing: boolean }) {
  if (!refreshing && !status) return null;
  const running = status?.running === true;
  const failed = status?.running === false && status?.result_ok === false;
  const sources = status?.by_source || [];
  const note = refreshNetworkNote(status);
  return (
    <section
      className="mt-4 rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] p-3"
      aria-live="polite"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-ink">
          {failed ? "La última descarga falló" : running ? "Descarga en curso" : "Última descarga"}
        </h3>
        <span className="font-mono text-[11px] text-muted">
          {typeof status?.elapsed_seconds === "number" ? elapsedLabel(status.elapsed_seconds) : "—"}
        </span>
      </div>
      <p className="mt-1 text-xs leading-5 text-muted">
        {failed
          ? status?.error?.message || "El backend no terminó la foto. La anterior sigue en pantalla."
          : running
            ? `${status?.phase_label || "Trabajando"}${
                status?.current_label ? ` · pidiendo ${status.current_label}` : ""
              }`
            : "Terminada. Los datos de arriba ya son los nuevos."}
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-faint">
        <span className="font-mono tabular-nums">
          {status?.calls ?? 0} llamada{(status?.calls ?? 0) === 1 ? "" : "s"} en esta pasada
        </span>
        {(status?.cache_hits ?? 0) > 0 ? (
          <span className="font-mono tabular-nums">{status?.cache_hits ?? 0} de caché</span>
        ) : null}
        {typeof status?.in_flight === "number" && status.in_flight > 0 ? (
          <span className="font-mono tabular-nums">{status.in_flight} en vuelo</span>
        ) : null}
        {status?.tier ? <span>foto {status.tier === "core" ? "rápida" : "completa"}</span> : null}
      </div>
      {note ? (
        <p className="mt-2 rounded-lg border border-[color:var(--line)] px-2 py-1.5 text-[11px] leading-4 text-muted">
          {note}
        </p>
      ) : null}
      {sources.length ? (
        <ul className="mt-2 flex flex-wrap gap-1.5">
          {sources.slice(0, 6).map((row) => (
            <li
              key={row.id}
              className="rounded-full border border-[color:var(--line)] px-2 py-0.5 font-mono text-[10.5px] text-muted"
            >
              {row.label} {row.calls > 0 ? row.calls : `${row.cache_hits ?? 0} caché`}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

export function ApiUsagePanel() {
  const search = useSearchParams();
  const league = search.get("league");
  const { refreshing, refreshStatus } = useDashboard();
  const [open, setOpen] = useState(false);
  const [usage, setUsage] = useState<ApiUsagePayload | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  const pull = useCallback(async () => {
    try {
      const payload = await getJson<ApiUsagePayload>(endpoint("/api/api-usage", league));
      setUsage(payload);
      setFailed(payload.ok === false ? payload.error?.message || "El medidor no respondió." : null);
    } catch (reason) {
      setFailed(reason instanceof Error ? reason.message : "El medidor no respondió.");
    }
  }, [league]);

  // Tres disparadores de lectura, todos gratis (RAM):
  //  1. al montar,
  //  2. mientras hay una descarga en curso —sin esto el número no se movía
  //    nunca durante la pasada, que es justo cuando el usuario lo mira—,
  //  3. mientras el diálogo está abierto, para ver el ritmo en directo.
  // El endpoint es RAM y no sale a Internet, así que sondearlo no gasta cupo.
  // La primera lectura va por temporizador y no en el cuerpo del efecto: un
  // setState síncrono ahí encadena renders.
  useEffect(() => {
    let cancelled = false;
    const run = () => {
      if (!cancelled) void pull();
    };
    const first = window.setTimeout(run, 0);
    const interval = !open && !refreshing ? null : window.setInterval(run, 4000);
    return () => {
      cancelled = true;
      window.clearTimeout(first);
      if (interval !== null) window.clearInterval(interval);
    };
  }, [open, refreshing, pull]);

  const risk = usage?.risk;
  const rate = usage?.rate;
  const tone = usageTone(usage);
  const verdict = usageVerdict(usage);
  const peak = maxSourceCalls(usage?.sources);
  const sources = usage?.sources || [];

  return (
    <>
      <button
        type="button"
        className="btn btn-secondary inline-flex"
        onClick={() => setOpen(true)}
        title="Llamadas que está haciendo el panel ahora mismo, por fuente"
        aria-haspopup="dialog"
      >
        <span className={`inline-flex items-center gap-1.5 font-semibold ${toneText(tone)}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${refreshing ? "bg-mint animate-pulse" : toneBg(tone)}`} aria-hidden="true" />
          <span className="hidden sm:inline">Llamadas</span>
        </span>
        <span className="font-mono tabular-nums">{headlineChip(usage)}</span>
      </button>

      <dialog
        ref={dialogRef}
        className="bid-dialog data-health-dialog"
        onClose={() => setOpen(false)}
        onClick={(event) => {
          if (event.target === dialogRef.current) setOpen(false);
        }}
      >
        <div className="bid-dialog__body max-h-[min(88vh,760px)] overflow-y-auto">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="eyebrow">Ritmo de llamadas</p>
              <h2 className="section-title mt-1">¿Cuántas peticiones estoy haciendo?</h2>
              <p className="section-support mt-1">
                Cuenta real de este proceso, por fuente. Los aciertos de caché no gastan petición y van aparte.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                className="btn btn-secondary !px-2.5 !py-1 text-xs"
                onClick={() => void pull()}
                title="Vuelve a leer los contadores. No sale a Internet."
              >
                Recargar
              </button>
              <CopyNetworkReportButton />
              <button type="button" className="btn btn-secondary !px-2.5 !py-1 text-xs" onClick={() => setOpen(false)}>
                Cerrar
              </button>
            </div>
          </div>

          {failed && !usage ? (
            <p className="mt-6 text-sm text-coral">{failed}</p>
          ) : !usage?.ok ? (
            <p className="mt-6 text-sm text-muted">Leyendo contadores…</p>
          ) : (
            <>
              <LiveStrip status={refreshStatus} refreshing={refreshing} />
              <section className="mt-5 rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] p-4">
                <div className="flex flex-wrap items-baseline gap-3">
                  <span className={verdict.badge}>{verdict.label}</span>
                  <span className="font-mono text-3xl font-semibold tracking-[-0.04em] text-ink">
                    {perMinute(rate?.per_minute)}
                  </span>
                  <span className="text-sm text-muted">
                    ahora mismo · banda {rateBandLabel(rate?.per_minute)}
                  </span>
                  <span className="ml-auto font-mono text-sm text-muted" title="100 = margen completo; baja con 429, reintentos y ráfagas">
                    Margen {risk?.score ?? "—"}%
                  </span>
                </div>
                <RateGauge perMinuteValue={rate?.per_minute ?? 0} />
                <p className="mt-3 text-sm font-medium leading-6 text-ink">{risk?.headline}</p>
                <p className="mt-1 text-xs leading-5 text-muted">{risk?.advice}</p>
                <ul className="mt-2 space-y-1">
                  {riskReasons(risk).map((line) => (
                    <li key={line} className="text-xs leading-5 text-muted">
                      · {line}
                    </li>
                  ))}
                </ul>
              </section>

              <section className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Stat label="Último minuto" value={String(rate?.calls_1m ?? 0)} hint="llamadas reales" />
                <Stat label="Últimos 10 min" value={String(rate?.calls_10m ?? 0)} hint={perMinute(rate?.per_minute_10m)} />
                <Stat
                  label="Simultáneas"
                  value={String(usage.in_flight?.now ?? 0)}
                  hint={`pico 1 min: ${usage.in_flight?.peak_1m ?? 0}`}
                  tone={(usage.in_flight?.peak_1m ?? 0) >= 6 ? "text-gold" : "text-ink"}
                />
                <Stat
                  label="429 en 10 min"
                  value={String(usage.windows?.[1]?.rate_limited ?? 0)}
                  hint={`${usage.windows?.[1]?.retries ?? 0} reintentos`}
                  tone={(usage.windows?.[1]?.rate_limited ?? 0) > 0 ? "text-coral" : "text-ink"}
                />
              </section>

              <section className="mt-4 rounded-xl border border-[color:var(--line)] bg-[color:var(--surface)] p-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h3 className="text-sm font-semibold text-ink">Estabilidad de la fuente</h3>
                  <span className={`text-[11px] font-semibold ${toneText(stabilityTone(usage.stability))}`}>
                    {usage.stability?.level === "warn" ? "Vigilar" : "Correcta"}
                  </span>
                </div>
                <p className="mt-1 text-xs leading-5 text-muted">{usage.stability?.headline}</p>
                {statusMixLabel(usage.stability?.status_mix) ? (
                  <p className="mt-1 font-mono text-[11px] text-faint">
                    {statusMixLabel(usage.stability?.status_mix)}
                  </p>
                ) : null}
                <p className="mt-1.5 text-[11px] leading-5 text-faint">{usage.stability?.note}</p>
              </section>

              <Timeline usage={usage} />

              <section className="mt-4">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h3 className="text-sm font-semibold text-ink">Reparto por fuente</h3>
                  <span className="text-[11px] text-faint">
                    {usage.totals?.calls ?? 0} llamadas desde el arranque ({shortDuration(usage.uptime_seconds)})
                  </span>
                </div>
                {sources.length === 0 ? (
                  <p className="mt-2 text-sm leading-6 text-muted">
                    Aún no ha salido ninguna petición desde este arranque. Pulsa Actualizar y vuelve aquí: el
                    contador se llena con las llamadas reales.
                  </p>
                ) : (
                  <ul className="mt-2 divide-y divide-[color:var(--line)] overflow-hidden rounded-xl border border-[color:var(--line)]">
                    {sources.map((row) => (
                      <SourceRow key={row.id} row={row} peak={peak} />
                    ))}
                  </ul>
                )}
              </section>

              <section className="mt-4 rounded-xl border border-[color:var(--line)] bg-[color:var(--surface)] p-3">
                <h3 className="text-sm font-semibold text-ink">Cómo se lee este número</h3>
                <ul className="mt-1.5 space-y-1 text-[11.5px] leading-5 text-muted">
                  {(risk?.rules || []).map((line) => (
                    <li key={line}>· {line}</li>
                  ))}
                  {(usage.notes || []).map((line) => (
                    <li key={line}>· {line}</li>
                  ))}
                </ul>
                <p className="mt-2 text-[11px] leading-5 text-faint">{usage.scope}</p>
              </section>
            </>
          )}
        </div>
      </dialog>
    </>
  );
}
