"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useDashboard } from "@/components/DashboardProvider";
import { ErrorCard, Skeleton } from "@/components/ui/Feedback";
import { endpoint, getJson } from "@/lib/core/api";
import { glass } from "@/lib/core/format";
import type { PreviaEvalRow, PreviaMatch, PreviaPayload, PreviaPick } from "@/lib/types";

const TIME_FMT = new Intl.DateTimeFormat("es-ES", {
  weekday: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/Madrid",
});

function dec(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("es-ES", { minimumFractionDigits: 1, maximumFractionDigits: 2 }) : "—";
}

function when(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : TIME_FMT.format(date);
}

function PickRow({ pick }: { pick: PreviaPick }) {
  return (
    <li className="flex items-center justify-between gap-3 py-1.5">
      <span className="min-w-0">
        <span className="block truncate text-[14px] font-medium text-white">
          {pick.name ?? "Jugador"}
          {pick.mine ? <span className="badge badge--good ml-2 !py-0 text-[10px]">Tuyo</span> : null}
          {pick.on_market ? <span className="badge badge--warn ml-2 !py-0 text-[10px]">Mercado</span> : null}
        </span>
        <span className="block truncate text-[11.5px] text-faint">
          {[pick.position, pick.club, `media ${dec(pick.mean)}`, `juega ${Math.round(pick.availability * 100)}%`].filter(Boolean).join(" · ")}
        </span>
      </span>
      <span className="shrink-0 font-mono text-[15px] font-semibold tabular-nums text-white">{dec(pick.score)}</span>
    </li>
  );
}

function Group({ title, tone, picks, note }: { title: string; tone: string; picks: PreviaPick[]; note?: string }) {
  if (!picks.length) return null;
  return (
    <div className="mt-3">
      <p className={`text-[11px] font-semibold uppercase tracking-wide ${tone}`}>
        {title}
        {note ? <span className="ml-2 font-normal normal-case tracking-normal text-faint">{note}</span> : null}
      </p>
      <ul className="divide-y divide-white/[0.05]">
        {picks.map((pick) => (
          <PickRow key={String(pick.player_id ?? pick.name)} pick={pick} />
        ))}
      </ul>
    </div>
  );
}

function MatchCard({ match }: { match: PreviaMatch }) {
  const [open, setOpen] = useState(false);
  const extra = match.bajas.length + match.mine.length + match.market_buys.length;
  return (
    <li className={glass("min-w-0 p-4")}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-[15px] font-semibold text-white">
            {match.home} <span className="text-faint">–</span> {match.away}
          </h3>
          <p className="mt-0.5 text-[11.5px] text-faint">
            {[when(match.kickoff), match.lambda_home && match.lambda_away ? `goles ${dec(match.lambda_home)} – ${dec(match.lambda_away)}` : "rival neutro"]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
      </div>
      <Group title="TOP" tone="text-mint" picks={match.top} />
      <Group title="Apuesta" tone="text-gold" picks={match.apuesta} note="experimental" />
      <Group title="No recomendable" tone="text-coral" picks={match.no_recomendable} />
      {extra > 0 ? (
        <>
          <button type="button" aria-expanded={open} onClick={() => setOpen((value) => !value)} className="mt-3 text-[12.5px] font-medium text-white/60 hover:text-white">
            {open ? "Ocultar" : `Más: bajas, tus jugadores y mercado (${extra})`}
          </button>
          {open ? (
            <div className="row-in">
              <Group title="Bajas" tone="text-white/50" picks={match.bajas} />
              <Group title="Tus jugadores" tone="text-white/50" picks={match.mine} />
              <Group title="Fichables en el mercado" tone="text-white/50" picks={match.market_buys} />
            </div>
          ) : null}
        </>
      ) : null}
    </li>
  );
}

const CATS = [
  { id: "top", label: "TOP" },
  { id: "naive_top", label: "Solo media" },
  { id: "apuesta", label: "Apuesta" },
  { id: "no_recomendable", label: "No recom." },
] as const;

function Evaluation({ rows }: { rows: PreviaEvalRow[] }) {
  return (
    <section className={glass("min-w-0 p-4 md:p-5")}>
      <p className="eyebrow">Evaluación</p>
      <h2 className="section-title mt-1 !text-[1.15rem]">Puntos reales de cada edición</h2>
      <p className="section-support mt-1.5">Media de puntos que sacaron las elecciones congeladas. El TOP tiene que ganar a «Solo media» para fiarse.</p>
      {rows.length ? (
        <div className="mt-4 overflow-x-auto rounded-xl border border-[color:var(--line)]">
          <table className="table-dense w-full min-w-[420px] text-left text-sm">
            <thead>
              <tr>
                <th>Jornada</th>
                {CATS.map((cat) => (
                  <th key={cat.id} className="text-right">
                    {cat.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.jornada}-${row.edition}`}>
                  <td className="font-medium">
                    J{row.jornada} <span className="text-faint">{row.edition}</span>
                  </td>
                  {CATS.map((cat) => (
                    <td key={cat.id} className="text-right font-mono tabular-nums">
                      {dec(row[cat.id].mean)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="mt-4 text-sm text-muted">Aún no hay ediciones evaluadas. La primera se mide cuando acabe la jornada congelada.</p>
      )}
    </section>
  );
}

export function PreviaPanel() {
  const search = useSearchParams();
  const { trends, state: dash } = useDashboard();
  const league = trends?.league_id || search.get("league");
  const [payload, setPayload] = useState<PreviaPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const stamp = dash.trends ? (dash.trends as { dashboard_at?: string }).dashboard_at ?? null : null;

  useEffect(() => {
    let cancelled = false;
    async function run() {
      setLoading(true);
      try {
        const data = await getJson<PreviaPayload>(endpoint("/api/laboratorio/previa", league));
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

  if (loading && !payload) return <Skeleton title="Previa" rows={6} />;
  if (!payload || payload.ok === false || !payload.live) {
    return <ErrorCard title="Previa de la jornada" payload={payload || { error: { message: "Sin previa." } }} brief />;
  }

  const live = payload.live;
  const frozen = (payload.editions ?? []).find((edition) => edition.edition === live.edition);

  return (
    <div className="flex min-w-0 flex-col gap-5" data-ui="previa">
      <section className={glass("min-w-0 p-4 md:p-5")}>
        <p className="eyebrow">En pruebas · J{live.jornada ?? "?"} · edición del {live.edition}</p>
        <h2 className="section-title mt-1 !text-[1.15rem]">Quién puntúa en cada partido</h2>
        <p className="section-support mt-1.5">
          Regla: media de la temporada × si juega × rival. En el backtest J3–J11 el TOP sacó 6,65 pts por jugador frente a 5,81 de quedarse con los de mejor media.
        </p>
        <p className="mt-2 text-[12.5px] text-white/55">
          {frozen
            ? `Edición guardada el ${when(frozen.generated_at)}: ya no cambia, así se puede medir después.`
            : live.frozen_eligible
              ? "Se guardará con esta foto."
              : "La foto es antigua: se muestra en vivo pero no se guarda. Actualiza desde Inicio."}
        </p>
      </section>

      {live.matches.length ? (
        <ul className="grid min-w-0 gap-4 lg:grid-cols-2">
          {live.matches.map((match) => (
            <MatchCard key={match.match_key} match={match} />
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted">Esta foto no trae partidos ni calendario. Actualiza desde Inicio.</p>
      )}

      <Evaluation rows={payload.evaluation ?? []} />
    </div>
  );
}
