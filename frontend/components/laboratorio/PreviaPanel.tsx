"use client";

import { cachedJson, peekJson } from "@/lib/core/jsonCache";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useDashboard } from "@/components/DashboardProvider";
import { ErrorCard, Skeleton } from "@/components/ui/Feedback";
import { endpoint } from "@/lib/core/api";
import { HeroStat } from "@/components/ui/kit";
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
          {pick.mine ? <span className="ml-2 text-[12px] font-medium text-[#FF9A5A]">Tuyo</span> : null}
          {pick.on_market ? <span className="ml-2 text-[12px] font-medium text-[#F59E0B]">En mercado</span> : null}
        </span>
        <span className="block truncate text-[12px] text-white/45">
          {[pick.position, pick.club, `media ${dec(pick.mean)}`, `juega el ${Math.round(pick.availability * 100)} %`].filter(Boolean).join(" · ")}
        </span>
      </span>
      <span className="shrink-0 text-right">
        <span className="block text-[15px] font-semibold tabular-nums text-white">{dec(pick.score)}</span>
        <span className="block text-[11px] text-white/40">pts previstos</span>
      </span>
    </li>
  );
}

function Group({ title, tone, picks, note }: { title: string; tone: string; picks: PreviaPick[]; note?: string }) {
  if (!picks.length) return null;
  return (
    <div className="mt-3">
      <p className={`text-[12.5px] font-semibold ${tone}`}>
        {title}
        {note ? <span className="ml-2 font-normal text-white/40">{note}</span> : null}
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
    <li className="home-glass min-w-0 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-[15px] font-semibold text-white">
            {match.home} <span className="text-white/35">–</span> {match.away}
          </h3>
          <p className="mt-0.5 text-[12px] text-white/45">
            {[when(match.kickoff), match.lambda_home && match.lambda_away ? `goles esperados ${dec(match.lambda_home)} – ${dec(match.lambda_away)}` : "sin cuotas"]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
      </div>
      <Group title="Los mejores" tone="text-[#10B981]" picks={match.top} />
      <Group title="Sorpresa posible" tone="text-[#F59E0B]" picks={match.apuesta} note="en pruebas" />
      <Group title="Mejor evitar" tone="text-[#FC734D]" picks={match.no_recomendable} />
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

function Evaluation({ rows }: { rows: PreviaEvalRow[] }) {
  if (!rows.length) {
    return (
      <p className="home-glass px-4 py-6 text-center text-[13.5px] text-white/50">
        Aún no hay ninguna jornada medida. La primera se mide cuando acabe la jornada guardada.
      </p>
    );
  }
  return (
    <ul className="flex flex-col gap-2.5">
      {rows.map((row) => {
        const top = row.top.mean;
        const naive = row.naive_top.mean;
        const played = (row.top.n ?? 0) > (row.top.missing ?? 0);
        const wins = played && typeof top === "number" && typeof naive === "number" ? top > naive : null;
        return (
          <li key={`${row.jornada}-${row.edition}`} className="home-glass p-4">
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-[14.5px] font-medium text-white">
                Jornada {row.jornada}
                {row.edition ? <span className="ml-2 text-[12px] text-white/40">edición del {row.edition}</span> : null}
              </span>
              {wins === null ? null : (
                <span className="text-[12.5px] font-medium" style={{ color: wins ? "#10B981" : "#FC734D" }}>
                  {wins ? "Acertó más que la media" : "No mejoró a la media"}
                </span>
              )}
            </div>
            {!played ? (
              <p className="mt-2 text-[12.5px] text-white/45">Pendiente: se mide cuando se jueguen los partidos.</p>
            ) : (
            <div className="mt-3 grid grid-cols-3 gap-2.5">
              <HeroStat value={dec(top)} label="los mejores" tone="#10B981" />
              <HeroStat value={dec(naive)} label="solo por media" />
              <HeroStat value={dec(row.no_recomendable.mean)} label="mejor evitar" tone="#FC734D" />
            </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

type View = "mejores" | "mios" | "evitar" | "partidos" | "acierta";

const VIEWS: { id: View; label: string; hint: string }[] = [
  { id: "mejores", label: "Mejores", hint: "Los jugadores con más puntos previstos de toda la jornada." },
  { id: "mios", label: "Tus jugadores", hint: "Cuántos puntos se esperan de cada uno de los tuyos." },
  { id: "evitar", label: "Mejor evitar", hint: "Buena media, pero esta jornada lo tienen difícil (rival, minutos o forma)." },
  { id: "partidos", label: "Por partido", hint: "Los mejores, las sorpresas y los que evitar en cada partido." },
  { id: "acierta", label: "¿Acierta?", hint: "Puntos reales que sacaron las elecciones guardadas. «Los mejores» tiene que ganar a «solo por media»." },
];

function gather(matches: PreviaMatch[], key: "top" | "mine" | "no_recomendable"): (PreviaPick & { match: string })[] {
  const seen = new Set<string>();
  const out: (PreviaPick & { match: string })[] = [];
  for (const match of matches) {
    for (const pick of match[key]) {
      const id = String(pick.player_id ?? pick.name);
      if (seen.has(id)) continue;
      seen.add(id);
      out.push({ ...pick, match: `${match.home} – ${match.away}` });
    }
  }
  return out.sort((x, y) => (key === "no_recomendable" ? y.mean - x.mean : y.score - x.score));
}

function PickList({ picks, empty }: { picks: (PreviaPick & { match: string })[]; empty: string }) {
  const [shown, setShown] = useState(10);
  if (!picks.length) return <p className="home-glass px-4 py-6 text-center text-[13.5px] text-white/50">{empty}</p>;
  return (
    <div className="flex flex-col gap-2">
      <ul className="home-glass overflow-hidden">
        {picks.slice(0, shown).map((pick) => (
          <li key={String(pick.player_id ?? pick.name)} className="px-4 py-2">
            <ul>
              <PickRow pick={pick} />
            </ul>
            <p className="-mt-0.5 pb-1 text-[11.5px] text-white/35">{pick.match}</p>
          </li>
        ))}
      </ul>
      {picks.length > shown ? (
        <button type="button" className="eq-chip self-center" onClick={() => setShown((n) => n + 10)}>
          Ver {Math.min(10, picks.length - shown)} más
        </button>
      ) : null}
    </div>
  );
}

export function PreviaPanel() {
  const [view, setView] = useState<View>("mejores");
  const search = useSearchParams();
  const { trends, state: dash } = useDashboard();
  const league = trends?.league_id || search.get("league");
  const [payload, setPayload] = useState<PreviaPayload | null>(() => peekJson<PreviaPayload>(endpoint("/api/laboratorio/previa", league)) ?? null);
  const [loading, setLoading] = useState(() => !peekJson(endpoint("/api/laboratorio/previa", league)));
  const stamp = dash.trends ? (dash.trends as { dashboard_at?: string }).dashboard_at ?? null : null;

  useEffect(() => {
    let cancelled = false;
    async function run() {
      setLoading(true);
      try {
        const data = await cachedJson<PreviaPayload>(endpoint("/api/laboratorio/previa", league));
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
  const current = VIEWS.find((v) => v.id === view)!;
  const matches = live.matches;

  return (
    <div className="flex min-w-0 flex-col gap-4" data-ui="previa">
      <section className="home-glass p-5">
        <p className="text-[13px] font-medium text-white/60">
          Jornada {live.jornada ?? "?"} · en pruebas
        </p>
        <p className="mt-1 text-[1.35rem] font-semibold leading-tight tracking-tight text-white">Quién va a puntuar esta jornada</p>
        <p className="mt-2 text-[13px] leading-snug text-white/55">
          Se calcula con su media, la probabilidad de que juegue y lo difícil que es el rival.{" "}
          {frozen
            ? `Guardada el ${when(frozen.generated_at)} para poder medir después si acertó.`
            : live.frozen_eligible
              ? "Se guardará con esta foto para medir después si acierta."
              : "La foto es antigua: actualiza desde Inicio para que se guarde."}
        </p>
      </section>

      <div className="eq-scroll -mx-1 flex gap-1.5 px-1" role="tablist" aria-label="Vistas de la previa">
        {VIEWS.map((v) => (
          <button key={v.id} type="button" role="tab" aria-selected={view === v.id} className={view === v.id ? "eq-chip eq-chip--on" : "eq-chip"} onClick={() => setView(v.id)}>
            {v.label}
          </button>
        ))}
      </div>
      <p className="-mt-1 px-1 text-[13px] text-white/50">{current.hint}</p>

      <div key={view} className="row-in min-w-0">
        {!matches.length && view !== "acierta" ? (
          <p className="home-glass px-4 py-6 text-center text-[13.5px] text-white/50">Esta foto no trae partidos. Actualiza desde Inicio.</p>
        ) : view === "mejores" ? (
          <PickList picks={gather(matches, "top")} empty="Sin jugadores destacados." />
        ) : view === "mios" ? (
          <PickList picks={gather(matches, "mine")} empty="Ninguno de tus jugadores juega esta jornada." />
        ) : view === "evitar" ? (
          <PickList picks={gather(matches, "no_recomendable")} empty="Nadie a evitar esta jornada." />
        ) : view === "partidos" ? (
          <ul className="grid min-w-0 gap-3 lg:grid-cols-2">
            {matches.map((match) => (
              <MatchCard key={match.match_key} match={match} />
            ))}
          </ul>
        ) : (
          <Evaluation rows={payload.evaluation ?? []} />
        )}
      </div>
    </div>
  );
}
