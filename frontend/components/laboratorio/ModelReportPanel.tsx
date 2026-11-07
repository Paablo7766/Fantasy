"use client";

import { cachedJson, peekJson } from "@/lib/core/jsonCache";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useDashboard } from "@/components/DashboardProvider";
import { ErrorCard, Skeleton } from "@/components/ui/Feedback";
import { endpoint } from "@/lib/core/api";
import { HeroStat, TONE } from "@/components/ui/kit";
import type { ModelMatchRow, ModelReportPayload, ModelScoreRow, ModelScorerRow, ModelShadowItem, ModelSourceRow } from "@/lib/types";

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

const STATE: Record<string, { color: string; label: string }> = {
  ok: { color: TONE.green, label: "Funciona" },
  respaldo: { color: TONE.amber, label: "Usa un respaldo" },
  fallo: { color: TONE.red, label: "No responde" },
};

/** «sin_cuotas_de_goleador» → «Sin cuotas de goleador». */
function humanize(text: string | null | undefined): string {
  if (!text) return "";
  const clean = /^[a-z0-9_]+$/.test(text) ? text.replace(/_/g, " ") : text;
  return clean.charAt(0).toUpperCase() + clean.slice(1);
}

function Sources({ rows }: { rows: ModelSourceRow[] }) {
  if (!rows.length) return <p className="home-glass px-4 py-6 text-center text-[13.5px] text-white/50">La foto aún no trae el estado de las fuentes.</p>;
  const order: Record<string, number> = { fallo: 0, respaldo: 1, ok: 2 };
  const sorted = rows.slice().sort((x, y) => (order[x.state] ?? 3) - (order[y.state] ?? 3));
  return (
    <ul className="home-glass overflow-hidden">
      {sorted.map((row, i) => {
        const st = STATE[row.state] ?? { color: TONE.gray, label: row.state };
        const detail =
          row.state === "ok"
            ? [row.source ? `vía ${row.source}` : null, typeof row.count === "number" ? `${row.count} datos` : null].filter(Boolean).join(" · ")
            : humanize(row.detail);
        return (
          <li key={row.id} className="row-in flex items-center gap-3 px-4 py-3" style={{ animationDelay: `${i * 20}ms` }}>
            <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: st.color, boxShadow: `0 0 10px ${st.color}66` }} aria-hidden="true" />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[14.5px] font-medium text-white">{row.label}</span>
              {detail ? (
                <span className="block truncate text-[12px] text-white/45" title={detail}>
                  {detail}
                </span>
              ) : null}
            </span>
            <span className="shrink-0 text-[12.5px] font-medium" style={{ color: st.color }}>
              {st.label}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

const VERDICT: Record<ModelScoreRow["verdict"], { color: string; label: string }> = {
  mejor: { color: TONE.green, label: "Acierta más" },
  peor: { color: TONE.red, label: "Acierta menos" },
  pocos_datos: { color: TONE.amber, label: "Pocos datos" },
  sin_medir: { color: TONE.gray, label: "Sin medir aún" },
};

function Scoreboard({ rows }: { rows: ModelScoreRow[] }) {
  if (!rows.length) return <p className="home-glass px-4 py-6 text-center text-[13.5px] text-white/50">Aún no hay nada guardado que comparar.</p>;
  return (
    <ul className="flex flex-col gap-2.5">
      {rows.map((row, i) => {
        const v = VERDICT[row.verdict] ?? VERDICT.sin_medir;
        return (
          <li key={row.id} className="home-glass row-in p-4" style={{ animationDelay: `${i * 25}ms` }}>
            <div className="flex items-start justify-between gap-3">
              <p className="text-[14.5px] font-medium text-white">{row.label}</p>
              <span className="shrink-0 text-[12px] font-medium" style={{ color: v.color }}>
                {v.label}
              </span>
            </div>
            <p className="mt-2 text-[1.15rem] font-semibold tabular-nums text-white">{row.value}</p>
            {row.baseline ? <p className="text-[12.5px] text-white/55">{row.baseline}</p> : null}
            <p className="mt-2 text-[12px] leading-snug text-white/45">{row.measure}</p>
            {row.note ? <p className="mt-1 text-[12px] leading-snug text-white/45">{row.note}</p> : null}
            <p className="mt-1.5 text-[11.5px] text-white/35">{row.n} casos</p>
          </li>
        );
      })}
    </ul>
  );
}

function Matches({ rows }: { rows: ModelMatchRow[] }) {
  if (!rows.length) {
    return <p className="home-glass px-4 py-6 text-center text-[13.5px] text-white/50">Sin partidos en esta foto. Actualiza desde Inicio.</p>;
  }
  return (
    <ul className="grid gap-2.5 md:grid-cols-2">
      {rows.map((m, i) => {
        const home = m.home?.club ?? "?";
        const away = m.away?.club ?? "?";
        const probs = m.market ? [m.market.p_home ?? 0, m.market.p_draw ?? 0, m.market.p_away ?? 0] : null;
        const goals = m.market ? [m.market.lambda_home, m.market.lambda_away] : [m.home?.lambda_for, m.away?.lambda_for];
        return (
          <li key={m.match_key} className="home-glass row-in p-4" style={{ animationDelay: `${i * 25}ms` }}>
            <div className="flex items-baseline justify-between gap-2">
              <span className="min-w-0 truncate text-[14.5px] font-medium text-white">
                {home} <span className="text-white/35">–</span> {away}
              </span>
              <span className="shrink-0 text-[12px] text-white/45">{when(m.kickoff)}</span>
            </div>
            {probs ? (
              <>
                <div className="mt-3 flex h-2 overflow-hidden rounded-full bg-white/[0.07]" aria-hidden="true">
                  <span style={{ width: `${probs[0] * 100}%`, background: TONE.copper }} />
                  <span style={{ width: `${probs[1] * 100}%`, background: "rgba(255,255,255,0.25)" }} />
                  <span style={{ width: `${probs[2] * 100}%`, background: TONE.blue }} />
                </div>
                <div className="mt-1.5 flex justify-between gap-2 text-[12px] tabular-nums text-white/55">
                  <span style={{ color: TONE.copper }}>Local {pc(probs[0])}</span>
                  <span>Empate {pc(probs[1])}</span>
                  <span style={{ color: TONE.blue }}>Visitante {pc(probs[2])}</span>
                </div>
              </>
            ) : (
              <p className="mt-3 text-[12px] text-white/40">Sin cuotas de apuestas todavía</p>
            )}
            <p className="mt-2 text-[12.5px] text-white/50">
              Goles esperados{" "}
              <span className="font-semibold tabular-nums text-white">
                {dec(goals[0], 1)} – {dec(goals[1], 1)}
              </span>
              {" · "}portería a cero {pc(m.home?.p_cs)} / {pc(m.away?.p_cs)}
            </p>
          </li>
        );
      })}
    </ul>
  );
}

function Scorers({ rows, listed }: { rows: ModelScorerRow[]; listed: number }) {
  const [onlyMine, setOnlyMine] = useState(false);
  if (!listed) return <p className="home-glass px-4 py-6 text-center text-[13.5px] text-white/50">Aún no hay cuotas de goleador guardadas. Llegan con la próxima actualización.</p>;
  const shown = (onlyMine ? rows.filter((r) => r.mine) : rows).slice(0, 20);
  return (
    <div className="flex flex-col gap-2">
      <div className="flex gap-1.5">
        <button type="button" className={!onlyMine ? "eq-chip eq-chip--on" : "eq-chip"} onClick={() => setOnlyMine(false)}>
          Todos
        </button>
        <button type="button" className={onlyMine ? "eq-chip eq-chip--on" : "eq-chip"} onClick={() => setOnlyMine(true)}>
          Mis jugadores
        </button>
      </div>
      <ul className="home-glass overflow-hidden">
        {shown.map((r) => (
          <li key={`${r.match_key}-${r.player_id}`} className="flex items-center gap-3 px-4 py-3">
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[14.5px] font-medium text-white">
                {r.name}
                {r.mine ? <span className="ml-2 text-[12px] text-[#FF9A5A]">Tuyo</span> : null}
              </span>
              <span className="block truncate text-[12px] text-white/45">{r.club ?? ""}</span>
            </span>
            <span className="shrink-0 text-right text-[12.5px] text-white/55">
              <span className="block">
                Casas <span className="font-semibold text-white">{pc(r.market_p)}</span>
              </span>
              <span className="block">Tu modelo {pc(r.own_p)}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Trials({ items, history }: { items: ModelShadowItem[]; history: NonNullable<ModelReportPayload["history"]> }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-3 gap-2.5">
        <HeroStat value={String(history.jornadas.length)} label="jornadas guardadas" />
        <HeroStat value={String(history.jornadas.filter((j) => j.evaluated > 0).length)} label="ya comparadas" />
        <HeroStat value={String(history.odds_matches)} label="partidos con cuotas" />
      </div>
      <ul className="flex flex-col gap-2.5">
        {items.map((item) => (
          <li key={item.id} className="home-glass p-4">
            <div className="flex items-start justify-between gap-3">
              <p className="text-[14.5px] font-medium text-white">{item.label}</p>
              <span className="shrink-0 rounded-full bg-[#F59E0B]/15 px-2.5 py-0.5 text-[11.5px] font-medium text-[#F59E0B]">{item.state}</span>
            </div>
            <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/[0.07]" aria-hidden="true">
              <div className="h-full rounded-full bg-[#FF7A3D]" style={{ width: `${Math.max(3, Math.round(item.progress * 100))}%` }} />
            </div>
            <p className="mt-2 text-[12.5px] text-white/55">{item.progress_text}</p>
            <details className="mt-1.5">
              <summary className="cursor-pointer text-[12px] text-white/40">Regla para darlo por bueno</summary>
              <p className="mt-1 text-[12px] leading-snug text-white/45">{item.rule}</p>
            </details>
          </li>
        ))}
      </ul>
    </div>
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
      <button type="button" className="shrink-0 rounded-full bg-white px-4 py-2 text-[13.5px] font-semibold text-[#120c09] hover:bg-[#ffe9dc] disabled:opacity-50" onClick={() => void copy()} disabled={!text} data-ui="copy-model-report">
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

type View = "marcador" | "fuentes" | "partidos" | "goleadores" | "pruebas";

const VIEWS: { id: View; label: string; hint: string }[] = [
  { id: "marcador", label: "Marcador", hint: "Cuánto acierta cada fuente frente a lo que pasó de verdad. Con pocos casos la cifra es orientativa." },
  { id: "fuentes", label: "Fuentes", hint: "Cada dato que usa la app y si hoy ha llegado bien. «Respaldo» = la fuente principal falló y se usa otra." },
  { id: "partidos", label: "Partidos", hint: "Qué dicen las casas de apuestas de cada partido de la jornada y cuántos goles se esperan." },
  { id: "goleadores", label: "Goleadores", hint: "Probabilidad de marcar según las casas frente a la de tu modelo. Solo se compara: aún no cambia tu once." },
  { id: "pruebas", label: "En pruebas", hint: "Mejoras que se están midiendo antes de usarlas, y cuánto falta para darlas por buenas." },
];

export function ModelReportPanel() {
  const [view, setView] = useState<View>("marcador");
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
  const count = (state: string) => sources.filter((src) => src.state === state).length;
  const bad = count("fallo");
  const backup = count("respaldo");
  const headline =
    bad + backup === 0
      ? "Todos los datos llegan bien"
      : bad
        ? `${bad} fuente${bad === 1 ? " no responde" : "s no responden"}`
        : `${backup} fuente${backup === 1 ? "" : "s"} con respaldo`;
  const current = VIEWS.find((v) => v.id === view)!;

  return (
    <div className="flex min-w-0 flex-col gap-4" data-ui="model-report">
      <section className="home-glass flex min-w-0 flex-wrap items-center justify-between gap-4 p-5">
        <div className="min-w-0">
          <p className="text-[13px] font-medium text-white/60">
            Jornada {payload.jornada ?? "?"} · foto del {when(payload.dashboard_at)}
          </p>
          <p className="mt-1 text-[1.35rem] font-semibold leading-tight tracking-tight text-white">{headline}</p>
          <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[12.5px]">
            <span style={{ color: TONE.green }}>● {count("ok")} funcionan</span>
            {backup ? <span style={{ color: TONE.amber }}>● {backup} con respaldo</span> : null}
            {bad ? <span style={{ color: TONE.red }}>● {bad} caídas</span> : null}
          </p>
        </div>
        <CopyReport text={payload.text} />
      </section>

      <div className="eq-scroll -mx-1 flex gap-1.5 px-1" role="tablist" aria-label="Vistas del modelo">
        {VIEWS.map((v) => (
          <button key={v.id} type="button" role="tab" aria-selected={view === v.id} className={view === v.id ? "eq-chip eq-chip--on" : "eq-chip"} onClick={() => setView(v.id)}>
            {v.label}
          </button>
        ))}
      </div>
      <p className="-mt-1 px-1 text-[13px] text-white/50">{current.hint}</p>

      <div key={view} className="row-in min-w-0">
        {view === "marcador" ? (
          <Scoreboard rows={payload.scoreboard ?? []} />
        ) : view === "fuentes" ? (
          <Sources rows={sources} />
        ) : view === "partidos" ? (
          <Matches rows={payload.matches ?? []} />
        ) : view === "goleadores" ? (
          <Scorers rows={payload.scorers?.rows ?? []} listed={payload.scorers?.listed ?? 0} />
        ) : (
          <Trials items={payload.shadow ?? []} history={payload.history ?? { jornadas: [], odds_days: 0, odds_matches: 0, scorer_rows: 0 }} />
        )}
      </div>
    </div>
  );
}
