"use client";

import { cachedJson, peekJson } from "@/lib/core/jsonCache";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { useDashboard } from "@/components/DashboardProvider";
import { ErrorCard, Skeleton } from "@/components/ui/Feedback";
import { endpoint } from "@/lib/core/api";
import { glass } from "@/lib/core/format";
import type { ModelMatchRow, ModelReportPayload, ModelScorerRow, ModelShadowItem, ModelSourceRow } from "@/lib/types";

const TIME_FMT = new Intl.DateTimeFormat("es-ES", {
  weekday: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/Madrid",
});

function pc(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? `${Math.round(value * 100)}%` : "—";
}

function dec(value: number | null | undefined, digits = 2): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString("es-ES", { minimumFractionDigits: digits, maximumFractionDigits: digits })
    : "—";
}

function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "—" : TIME_FMT.format(date);
}

function Block({ eyebrow, title, support, children, aside }: { eyebrow: string; title: string; support?: ReactNode; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className={glass("min-w-0 p-4 md:p-5")}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="lab-eyebrow">{eyebrow}</p>
          <h2 className="lab-title mt-1">{title}</h2>
          {support ? <p className="lab-support mt-1.5 max-w-3xl">{support}</p> : null}
        </div>
        {aside}
      </div>
      <div className="mt-4 min-w-0">{children}</div>
    </section>
  );
}

const STATE_BADGE: Record<string, { cls: string; label: string }> = {
  ok: { cls: "badge badge--good", label: "OK" },
  respaldo: { cls: "badge badge--warn", label: "Respaldo" },
  fallo: { cls: "badge badge--bad", label: "Falla" },
};

function Sources({ rows }: { rows: ModelSourceRow[] }) {
  if (!rows.length) return <p className="text-sm text-white/50">El tablero aún no trae el estado de las fuentes.</p>;
  return (
    <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
      {rows.map((row) => {
        const badge = STATE_BADGE[row.state] ?? { cls: "badge", label: row.state };
        return (
          <li key={row.id} className="min-w-0 rounded-2xl bg-white/[0.045] px-3.5 py-3">
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-sm font-medium text-white">{row.label}</span>
              <span className={badge.cls}>{badge.label}</span>
            </div>
            <p className="mt-1 truncate text-[11.5px] text-faint" title={row.detail || undefined}>
              {row.detail ||
                [row.source ? `vía ${row.source}` : null, typeof row.count === "number" ? `${row.count} registros` : null].filter(Boolean).join(" · ") ||
                "—"}
            </p>
          </li>
        );
      })}
    </ul>
  );
}

function Matches({ rows }: { rows: ModelMatchRow[] }) {
  if (!rows.length) {
    return <p className="text-sm text-white/50">Sin calendario propio en esta foto (sin xG no hay goles esperados). Actualiza desde Inicio.</p>;
  }
  return (
    <div className="overflow-x-auto rounded-2xl border border-white/[0.07]">
      <table className="table-dense w-full min-w-[720px] text-left text-sm">
        <thead>
          <tr>
            <th>Partido</th>
            <th>Hora</th>
            <th className="text-right">Mercado 1 · X · 2</th>
            <th className="text-right">Goles mercado</th>
            <th className="text-right">Goles modelo</th>
            <th className="text-right">Peso mercado</th>
            <th className="text-right">Port. a cero</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((m) => (
            <tr key={m.match_key}>
              <td className="font-medium">
                {m.home?.club ?? "?"} <span className="text-faint">–</span> {m.away?.club ?? "?"}
              </td>
              <td className="whitespace-nowrap text-white/50">{when(m.kickoff)}</td>
              <td className="text-right font-mono tabular-nums">
                {m.market ? `${pc(m.market.p_home)} · ${pc(m.market.p_draw)} · ${pc(m.market.p_away)}` : <span className="text-faint">sin cuotas</span>}
              </td>
              <td className="text-right font-mono tabular-nums">
                {m.market ? `${dec(m.market.lambda_home, 1)} – ${dec(m.market.lambda_away, 1)}` : "—"}
              </td>
              <td className="text-right font-mono tabular-nums">
                {dec(m.home?.lambda_for, 1)} – {dec(m.away?.lambda_for, 1)}
              </td>
              <td className="text-right font-mono tabular-nums text-white/50">{m.market ? pc(m.market_weight) : "0%"}</td>
              <td className="text-right font-mono tabular-nums text-white/50">
                {pc(m.home?.p_cs)} / {pc(m.away?.p_cs)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Scorers({ rows, linked, listed }: { rows: ModelScorerRow[]; linked: number; listed: number }) {
  const [onlyMine, setOnlyMine] = useState(false);
  if (!listed) return <p className="text-sm text-white/50">Todavía no hay cuotas de goleador guardadas. Llegan con la próxima actualización.</p>;
  const shown = (onlyMine ? rows.filter((r) => r.mine) : rows).slice(0, 30);
  return (
    <>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-white/50">
          {linked} de {listed} goleadores de bet365 enlazados con jugadores de tu liga.
        </p>
        <label className="flex cursor-pointer items-center gap-2 text-xs text-white/50">
          <input type="checkbox" checked={onlyMine} onChange={(e) => setOnlyMine(e.target.checked)} />
          Solo mi plantilla
        </label>
      </div>
      <div className="overflow-x-auto rounded-2xl border border-white/[0.07]">
        <table className="table-dense w-full min-w-[560px] text-left text-sm">
          <thead>
            <tr>
              <th>Jugador</th>
              <th className="text-right">Cuota</th>
              <th className="text-right">P(gol) mercado</th>
              <th className="text-right">P(gol) modelo</th>
              <th className="text-right">Diferencia</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => {
              const big = typeof r.gap === "number" && Math.abs(r.gap) >= 0.1;
              return (
                <tr key={`${r.match_key}-${r.player_id}`}>
                  <td>
                    <span className="font-medium">{r.name}</span>
                    {r.mine ? <span className="badge badge--good ml-2 !py-0 text-[10px]">Tuyo</span> : null}
                    <span className="block text-[11px] text-faint">{r.club ?? ""}</span>
                  </td>
                  <td className="text-right font-mono tabular-nums">{dec(r.price)}</td>
                  <td className="text-right font-mono tabular-nums">{pc(r.market_p)}</td>
                  <td className="text-right font-mono tabular-nums">{pc(r.own_p)}</td>
                  <td className={`text-right font-mono tabular-nums ${big ? (r.gap! > 0 ? "text-mint" : "text-coral") : "text-white/50"}`}>
                    {typeof r.gap === "number" ? `${r.gap > 0 ? "+" : ""}${Math.round(r.gap * 100)} pp` : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

function History({ data }: { data: NonNullable<ModelReportPayload["history"]> }) {
  return (
    <>
      <div className="mb-3 grid gap-2 sm:grid-cols-3">
        <Stat label="Partidos con cuotas" value={String(data.odds_matches)} hint={`${data.odds_days} días guardados`} />
        <Stat label="Filas de goleador" value={String(data.scorer_rows)} hint="bet365, una por jugador y día" />
        <Stat label="Jornadas con xP" value={String(data.jornadas.length)} hint={`${data.jornadas.filter((j) => j.evaluated > 0).length} ya evaluadas`} />
      </div>
      {data.jornadas.length ? (
        <div className="overflow-x-auto rounded-2xl border border-white/[0.07]">
          <table className="table-dense w-full min-w-[480px] text-left text-sm">
            <thead>
              <tr>
                <th>Jornada</th>
                <th className="text-right">Jugadores</th>
                <th className="text-right">Evaluados</th>
                <th className="text-right">Error medio</th>
                <th className="text-right">Días guardados</th>
              </tr>
            </thead>
            <tbody>
              {data.jornadas.map((j) => (
                <tr key={j.jornada}>
                  <td className="font-medium">J{j.jornada}</td>
                  <td className="text-right font-mono tabular-nums">{j.players}</td>
                  <td className="text-right font-mono tabular-nums">{j.evaluated || <span className="text-faint">pendiente</span>}</td>
                  <td className="text-right font-mono tabular-nums">{j.mae !== null && j.mae !== undefined ? `${dec(j.mae, 1)} pts` : "—"}</td>
                  <td className="text-right font-mono tabular-nums">{j.days_logged}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-2xl bg-white/[0.045] px-4 py-3">
      <p className="text-[11px] uppercase tracking-wide text-faint">{label}</p>
      <p className="metric-value mt-1 text-xl">{value}</p>
      {hint ? <p className="mt-1 text-xs text-white/50">{hint}</p> : null}
    </div>
  );
}

function Shadow({ items }: { items: ModelShadowItem[] }) {
  return (
    <ul className="grid gap-3 md:grid-cols-2">
      {items.map((item) => (
        <li key={item.id} className="rounded-2xl bg-white/[0.045] px-4 py-3.5">
          <div className="flex items-start justify-between gap-3">
            <p className="text-sm font-medium text-white">{item.label}</p>
            <span className="badge badge--warn shrink-0">{item.state}</span>
          </div>
          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/[0.07]" aria-hidden="true">
            <div className="h-full rounded-full bg-[#FF7A3D]" style={{ width: `${Math.max(3, Math.round(item.progress * 100))}%` }} />
          </div>
          <p className="mt-2 text-xs text-white/50">{item.progress_text}</p>
          <p className="mt-1.5 text-[11.5px] leading-5 text-faint">{item.rule}</p>
        </li>
      ))}
    </ul>
  );
}

/** Copia el informe entero en texto plano para pegarlo en una conversación. */
function CopyReport({ text }: { text: string | undefined }) {
  const [state, setState] = useState<"idle" | "ok" | "manual">("idle");
  const copy = useCallback(async () => {
    if (!text) return;
    let ok = false;
    try {
      // Algunos navegadores dejan la promesa colgada esperando un permiso.
      await Promise.race([
        navigator.clipboard.writeText(text),
        new Promise((_, reject) => window.setTimeout(() => reject(new Error("timeout")), 1500)),
      ]);
      ok = true;
    } catch {
      const area = document.createElement("textarea");
      area.value = text;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      try {
        ok = document.execCommand("copy");
      } catch {
        ok = false;
      }
      area.remove();
    }
    setState(ok ? "ok" : "manual");
    if (ok) window.setTimeout(() => setState("idle"), 2500);
  }, [text]);
  return (
    <div className="flex w-full min-w-0 flex-col items-start gap-2 sm:w-auto sm:items-end">
      <button type="button" className="btn btn-primary shrink-0" onClick={() => void copy()} disabled={!text} data-ui="copy-model-report">
        {state === "ok" ? "Copiado ✓" : "Copiar informe para Claude"}
      </button>
      {state === "manual" ? (
        <div className="w-full sm:w-[28rem]">
          <p className="mb-1 text-xs text-gold">El navegador no deja copiar solo: el texto ya está seleccionado, pulsa Ctrl+C (⌘C en Mac).</p>
          <textarea
            readOnly
            autoFocus
            value={text}
            onFocus={(event) => event.currentTarget.select()}
            className="h-40 w-full rounded-lg border border-white/[0.07] bg-black/30 p-2 font-mono text-[11px] text-white/80"
            data-ui="copy-model-report-text"
          />
        </div>
      ) : null}
    </div>
  );
}

export function ModelReportPanel() {
  const search = useSearchParams();
  const { trends, state: dash } = useDashboard();
  const league = trends?.league_id || search.get("league");
  const [payload, setPayload] = useState<ModelReportPayload | null>(() => peekJson<ModelReportPayload>(endpoint("/api/laboratorio/modelo", league)) ?? null);
  const [loading, setLoading] = useState(() => !peekJson(endpoint("/api/laboratorio/modelo", league)));
  const stamp = dash.trends ? (dash.trends as { dashboard_at?: string }).dashboard_at ?? null : null;

  useEffect(() => {
    let cancelled = false;
    async function run() {
      setLoading(true);
      try {
        const data = await cachedJson<ModelReportPayload>(endpoint("/api/laboratorio/modelo", league));
        if (!cancelled) setPayload(data);
      } catch (reason: unknown) {
        if (cancelled) return;
        const message = reason instanceof Error ? reason.message : "Sin datos.";
        const hint = /404|Not Found/i.test(message) ? " El backend no tiene la ruta nueva: reinícialo." : "";
        setPayload({ ok: false, error: { message: `${message}${hint}` } });
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void run();
    return () => {
      cancelled = true;
    };
  }, [league, stamp]);

  if (loading && !payload) return <Skeleton title="Modelo" rows={6} />;
  if (!payload || payload.ok === false) return <ErrorCard title="Informe del modelo" payload={payload || { error: { message: "Sin informe." } }} brief />;

  const sources = payload.sources ?? [];
  const problems = sources.filter((s) => s.state !== "ok").length;

  return (
    <div className="flex min-w-0 flex-col gap-5" data-ui="model-report">
      <section className={glass("flex min-w-0 flex-wrap items-center justify-between gap-4 p-4 md:p-5")}>
        <div className="min-w-0">
          <p className="lab-eyebrow">Estado del modelo · J{payload.jornada ?? "?"}</p>
          <h2 className="lab-title mt-1">
            {problems === 0 ? "Todas las fuentes clave responden" : `${problems} fuente${problems === 1 ? "" : "s"} con respaldo o fallo`}
          </h2>
          <p className="lab-support mt-1.5">
            Foto del {when(payload.dashboard_at)}. El botón copia todo este informe en texto para pegármelo en el chat y que tenga el contexto.
          </p>
        </div>
        <CopyReport text={payload.text} />
      </section>

      <Block eyebrow="1 · Fuentes" title="De dónde sale cada dato" support="«Respaldo» significa que la fuente principal cayó y el dato viene de otra, ajustada a la misma escala.">
        <Sources rows={sources} />
      </Block>

      <Block
        eyebrow="2 · Próxima jornada"
        title="Mercado frente a modelo"
        support="Las cuotas de Pinnacle se convierten en probabilidades y goles esperados. Tu xP usa la mezcla: el mercado pesa del 55 % (a una semana) al 82 % (justo antes del partido)."
      >
        <Matches rows={payload.matches ?? []} />
      </Block>

      <Block
        eyebrow="3 · Goleadores · en pruebas"
        title="¿Quién marca? bet365 frente a tu modelo"
        support="Probabilidad de marcar sin el margen de la casa. Solo se mide: no toca tu xP ni el once hasta cumplir la regla de abajo."
      >
        <Scorers rows={payload.scorers?.rows ?? []} linked={payload.scorers?.linked ?? 0} listed={payload.scorers?.listed ?? 0} />
      </Block>

      <Block eyebrow="4 · Histórico" title="Lo que se ha guardado" support="Cada día se congela la previsión de cada jugador y las cuotas. Cuando acaba la jornada se compara con los puntos reales.">
        <History data={payload.history ?? { jornadas: [], odds_days: 0, odds_matches: 0, scorer_rows: 0 }} />
      </Block>

      <Block eyebrow="5 · En pruebas" title="Qué falta para fiarse" support="Cada cambio tiene su regla fijada de antemano. Nada de esto decide una compra hasta cumplirla.">
        <Shadow items={payload.shadow ?? []} />
      </Block>
    </div>
  );
}
