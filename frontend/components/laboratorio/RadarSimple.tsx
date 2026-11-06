"use client";

import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useDashboard } from "@/components/DashboardProvider";
import { endpoint } from "@/lib/core/api";
import { useCachedJson as useCached } from "@/lib/core/useCachedJson";
import { playerName, points } from "@/lib/core/format";
import { photoFor, type PhotoIndex } from "@/lib/core/photoIndex";
import { beyondBudget, bidBudget } from "@/lib/mercado/budget";
import type { CatalogProfilePlayer, FreeAgentsPayload, QuantPlayer, QuantRadarPayload } from "@/lib/types";
import { Empty, Face, HeroStat, Skeleton, TONE, money, signedMoney } from "@/components/ui/kit";

type View = "gangas" | "suben" | "libres" | "como";

const VIEWS: { id: View; label: string; hint: string }[] = [
  { id: "gangas", label: "Gangas", hint: "Fichables que dan muchos puntos para lo que cuestan." },
  { id: "suben", label: "Suben de precio", hint: "Jugadores en los que está entrando dinero ahora mismo." },
  { id: "libres", label: "Libres buenos", hint: "Sin dueño en tu liga y con buena media: no hace falta clausular." },
  { id: "como", label: "Cómo funciona", hint: "Qué mira el radar para dar cada nota." },
];

const STEP = 8;

function owner(player: { owner?: string | null; manager_name?: string | null; on_market?: boolean; is_free_agent?: boolean | null }): string {
  if (player.owner === "libre" || player.is_free_agent) return "Libre";
  if (player.on_market) return player.manager_name ? `En venta · ${player.manager_name}` : "En el mercado";
  if (player.owner === "propio") return "Tuyo";
  return player.manager_name ? `De ${player.manager_name}` : "Con dueño";
}

/** Nota 0-100 como anillo pequeño: lleno = mejor. */
function ScoreRing({ score }: { score: number | null | undefined }) {
  const value = typeof score === "number" ? Math.max(0, Math.min(100, Math.round(score))) : null;
  const color = value === null ? TONE.gray : value >= 70 ? TONE.green : value >= 45 ? TONE.copper : TONE.amber;
  const r = 15;
  const c = 2 * Math.PI * r;
  return (
    <span className="relative grid h-10 w-10 shrink-0 place-items-center" title="Nota del radar (0-100)">
      <svg viewBox="0 0 36 36" className="absolute inset-0 h-full w-full -rotate-90" aria-hidden="true">
        <circle cx="18" cy="18" r={r} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="3" />
        <circle cx="18" cy="18" r={r} fill="none" stroke={color} strokeWidth="3" strokeLinecap="round" strokeDasharray={`${((value ?? 0) / 100) * c} ${c}`} />
      </svg>
      <span className="text-[12px] font-semibold tabular-nums text-white">{value ?? "—"}</span>
    </span>
  );
}

export function Row({
  name,
  photo,
  meta,
  value,
  valueTone,
  note,
  aside,
  index,
}: {
  name: string;
  photo?: string | null;
  meta: string;
  value: string;
  valueTone?: string;
  note?: string;
  aside?: React.ReactNode;
  index: number;
}) {
  return (
    <li className="row-in flex min-h-[4rem] items-center gap-3 border-b border-white/[0.06] px-4 py-3 last:border-b-0" style={{ animationDelay: `${index * 25}ms` }}>
      <Face name={name} src={photo ?? undefined} size={40} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[15px] font-medium text-white">{name}</span>
        <span className="block truncate text-[12.5px] text-white/45">{meta}</span>
      </span>
      <span className="shrink-0 text-right">
        <span className="block text-[15px] font-semibold tabular-nums" style={{ color: valueTone || "#fff" }}>
          {value}
        </span>
        {note ? <span className="block text-[12px] text-white/50">{note}</span> : null}
      </span>
      {aside}
    </li>
  );
}

export function List<T>({ rows, render, empty }: { rows: T[]; render: (row: T, index: number) => React.ReactNode; empty: string }) {
  const [shown, setShown] = useState(STEP);
  if (!rows.length) return <p className="home-glass px-4 py-6 text-center text-[13.5px] text-white/50">{empty}</p>;
  return (
    <div className="flex flex-col gap-2">
      <ul className="home-glass overflow-hidden">{rows.slice(0, shown).map(render)}</ul>
      {rows.length > shown ? (
        <button type="button" className="eq-chip self-center" onClick={() => setShown((n) => n + STEP)}>
          Ver {Math.min(STEP, rows.length - shown)} más
        </button>
      ) : null}
    </div>
  );
}

function cheaperLine(player: QuantPlayer): string | undefined {
  const d = player.discount_vs_position;
  if (typeof d !== "number" || d <= 0) return undefined;
  return `${Math.round(d * 100)} % más barato`;
}

export function RadarSimple({ photos }: { photos: PhotoIndex }) {
  const search = useSearchParams();
  const league = search.get("league");
  const { state } = useDashboard();
  const radar = useCached<QuantRadarPayload>(endpoint("/api/market/quant-radar", league));
  const free = useCached<FreeAgentsPayload>(endpoint("/api/catalog/free-agents", league));
  const [view, setView] = useState<View>("gangas");
  const budget = bidBudget(state.plan?.cash_eur, state.squads?.self?.market_value_total);

  const buys = useMemo(() => radar?.buys ?? [], [radar]);
  const rising = useMemo(() => (radar?.momentum?.smart_money ?? []).filter((p) => (p.price_delta ?? 0) > 0), [radar]);
  const goodFree = useMemo(
    () =>
      (free?.top_free ?? [])
        .filter((p: CatalogProfilePlayer) => !beyondBudget(p.market_value, budget))
        .sort((a, b) => (b.median ?? 0) - (a.median ?? 0)),
    [free, budget],
  );

  if (radar === null) return <Skeleton />;
  if (radar.ok === false) {
    return <Empty title="El radar no ha respondido" detail={`${radar.error?.message || "Sin datos."} Prueba a actualizar la foto desde Inicio.`} />;
  }

  const summary = radar.summary ?? {};
  const weights = radar.assumptions?.weights ?? {};
  const blank = radar.assumptions?.blank_threshold_points ?? 2;
  const maxBlank = radar.assumptions?.max_blank_rate ?? 0.4;
  const current = VIEWS.find((v) => v.id === view)!;

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="grid grid-cols-3 gap-2.5">
        <HeroStat value={String(summary.buys ?? buys.length)} label="gangas hoy" tone={TONE.green} />
        <HeroStat value={String(rising.length)} label="suben de precio" tone={TONE.copper} />
        <HeroStat value={budget !== null ? money(budget) : "—"} label="puedes pujar hasta" />
      </div>

      <div className="eq-scroll -mx-1 flex gap-1.5 px-1" role="tablist" aria-label="Vistas del radar">
        {VIEWS.map((v) => (
          <button key={v.id} type="button" role="tab" aria-selected={view === v.id} className={view === v.id ? "eq-chip eq-chip--on" : "eq-chip"} onClick={() => setView(v.id)}>
            {v.label}
          </button>
        ))}
      </div>
      <p className="-mt-1 px-1 text-[13px] text-white/50">{current.hint}</p>

      <div key={view} className="row-in">
        {view === "gangas" ? (
          <List
            rows={buys}
            empty="Hoy no hay gangas claras. Mejor esperar que comprar una trampa."
            render={(p, i) => {
              const name = playerName(p);
              return (
                <Row
                  key={p.player_id}
                  index={i}
                  name={name}
                  photo={photoFor(photos, String(p.player_id), name)}
                  meta={[p.position, p.club, owner(p)].filter(Boolean).join(" · ")}
                  value={money(p.effective_price ?? p.market_value)}
                  note={cheaperLine(p)}
                  aside={<ScoreRing score={p.score} />}
                />
              );
            }}
          />
        ) : view === "suben" ? (
          <List
            rows={rising}
            empty="Ahora mismo no entra dinero fuerte en ningún jugador."
            render={(p, i) => {
              const name = playerName(p);
              return (
                <Row
                  key={p.player_id}
                  index={i}
                  name={name}
                  photo={photoFor(photos, String(p.player_id), name)}
                  meta={[p.position, p.club].filter(Boolean).join(" · ")}
                  value={signedMoney(p.price_delta)}
                  valueTone={TONE.green}
                  note={p.verdict === "NO_FICHABLE" ? "No fichable" : p.affordable === false ? "No te llega" : "Fichable"}
                />
              );
            }}
          />
        ) : view === "libres" ? (
          free === null ? (
            <Skeleton />
          ) : (
            <List
              rows={goodFree}
              empty="No hay libres buenos que te quepan en el presupuesto."
              render={(p, i) => {
                const name = playerName(p);
                return (
                  <Row
                    key={p.player_id}
                    index={i}
                    name={name}
                    photo={photoFor(photos, String(p.player_id), name)}
                    meta={[p.position, p.club].filter(Boolean).join(" · ")}
                    value={`${points(p.median)} pts`}
                    note={money(p.market_value)}
                  />
                );
              }}
            />
          )
        ) : (
          <div className="flex flex-col gap-3">
            <ol className="home-glass flex flex-col gap-4 p-5">
              {[
                ["Puntos por euro", `Compara lo que cuesta cada punto con lo normal en su posición. Pesa un ${Math.round((weights.value ?? 0.55) * 100)} % de la nota.`],
                ["Descuento", `Cuánto más barato está que un jugador que puntúa igual. Pesa un ${Math.round((weights.discount ?? 0.25) * 100)} %.`],
                ["Dinero entrando", `Si su precio sube cada vez más rápido. Pesa un ${Math.round((weights.momentum ?? 0.2) * 100)} %.`],
                ["Filtro de trampas", `Si más del ${Math.round(maxBlank * 100)} % de sus jornadas hace ${blank} puntos o menos, se descarta aunque sea barato. Hoy: ${summary.toxic ?? 0} descartados.`],
              ].map(([title, text], i) => (
                <li key={title} className="flex gap-3">
                  <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-[#FF7A3D]/15 text-[12.5px] font-semibold text-[#FF9A5A]">{i + 1}</span>
                  <span>
                    <span className="block text-[14.5px] font-medium text-white">{title}</span>
                    <span className="block text-[13px] leading-snug text-white/55">{text}</span>
                  </span>
                </li>
              ))}
            </ol>
            <div className="home-glass p-5">
              <p className="text-[13px] font-medium text-white/60">Lo normal que cuesta un punto</p>
              <div className="mt-3 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
                {["POR", "DEF", "MC", "DEL"].map((pos) => (
                  <HeroStat key={pos} value={money(radar.baselines?.[pos]?.median_cost_per_point_eur)} label={pos} />
                ))}
              </div>
              <p className="mt-3 text-[12px] text-white/40">
                {radar.sources?.players_scored ?? summary.scanned ?? 0} jugadores analizados con la foto guardada. Nada de esto descarga ni decide una compra.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
