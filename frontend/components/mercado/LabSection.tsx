"use client";

import { cachedJson, peekJson } from "@/lib/core/jsonCache";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Face, Fact, SectionHead, TONE, Verdict, compact, money, signedMoney, toneOf } from "@/components/ui/kit";
import { useDashboard } from "@/components/DashboardProvider";
import { endpoint } from "@/lib/core/api";
import { beyondBudget, bidBudget } from "@/lib/mercado/budget";
import { photoFor, type PhotoIndex } from "@/lib/core/photoIndex";
import { errorText, points } from "@/lib/core/format";
import type { ArbitragePayload, CatalogProfilePlayer, FreeAgentsPayload } from "@/lib/types";

type Vista = "libres" | "suelo" | "refugio" | "riesgo";

const VISTAS: { id: Vista; label: string; hint: string; empty: string }[] = [
  {
    id: "libres",
    label: "Libres",
    hint: "Top libres por mediana: el talento que no exige cláusula.",
    empty: "Sin libres de nivel top: o el catálogo no trae series, o están todos fichados.",
  },
  {
    id: "suelo",
    label: "Suelo de lesión",
    hint: "Lesionados o sancionados con la caída de precio ya frenada: tesis de suelo, no de rebote.",
    empty: "Ninguno con la caída frenada. Hacen falta 3 días de histórico y que la última caída sea menor que la anterior.",
  },
  {
    id: "refugio",
    label: "Refugio",
    hint: "Suelo alto y varianza baja: el que no se cae del once.",
    empty: "Sin refugios: hace falta mediana ≥ 5, desviación ≤ 3 y blank ≤ 20 %.",
  },
  {
    id: "riesgo",
    label: "Lotería",
    hint: "Techo alto con muchos ceros: se paga la lotería, no el valor.",
    empty: "Sin loterías: hace falta desviación ≥ 6, blank ≥ 35 % y techo ≥ 10.",
  },
];

const INFLATION: Record<string, { label: string; color: string }> = {
  normal: { label: "Inflación normal", color: TONE.green },
  alta: { label: "Inflación alta", color: TONE.amber },
  extrema: { label: "Inflación extrema", color: TONE.red },
};

const ASSET: Record<string, { label: string; color: string }> = {
  refugio: { label: "Refugio", color: TONE.blue },
  riesgo: { label: "Lotería", color: TONE.red },
  equilibrado: { label: "Equilibrado", color: TONE.gray },
};

const PLAYABLE = new Set(["POR", "DEF", "MC", "DEL"]);

/**
 * El catálogo de la competición trae también entrenadores. Esta liga no tiene
 * ficha de entrenador: no se ficha ni puntúa, así que aquí no entra. El motor
 * ya los tira en la normalización; este filtro cubre una foto antigua.
 */
function onlyPlayers(rows: CatalogProfilePlayer[] | null | undefined): CatalogProfilePlayer[] {
  return (Array.isArray(rows) ? rows : []).filter((row) => PLAYABLE.has(String(row.position || "").toUpperCase()));
}

function blankColor(rate: number | null | undefined): string {
  if (typeof rate !== "number") return TONE.gray;
  if (rate >= 0.4) return TONE.red;
  if (rate >= 0.3) return TONE.amber;
  return TONE.green;
}

function trendLabel(row: CatalogProfilePlayer): string {
  const trend = row.price_trend;
  if (!trend) return "sin histórico";
  return trend.decelerating ? "caída frenando" : trend.falling ? "cayendo" : trend.recovery ? "recupera" : "estable";
}

function ProfileRow({ row, photo, index, tooPricey }: { row: CatalogProfilePlayer; photo: string | null; index: number; tooPricey: boolean }) {
  const [open, setOpen] = useState(false);
  const name = row.nickname || row.name || "Jugador";
  const asset = ASSET[row.asset_class || ""];
  const status = row.distress_kind === "injured" ? "lesionado" : row.distress_kind === "suspended" ? "sancionado" : "";
  const last = row.price_trend?.last_delta;
  return (
    <li className="row-in border-b border-white/[0.06] last:border-b-0" style={{ animationDelay: `${Math.min(index, 12) * 30}ms` }}>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex min-h-[3.75rem] w-full items-center gap-3 px-4 py-2.5 text-left transition-colors duration-200 ease-out hover:bg-white/[0.02]"
      >
        <Face name={name} src={photo} size={40} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[15px] font-medium leading-tight text-white">{name}</span>
          <span className="mt-0.5 block truncate text-[12.5px] text-white/45">
            {[row.position, row.club, row.is_free_agent ? "libre" : row.owner_team_id ? "fichado" : ""].filter(Boolean).join(" · ")}
            {status ? <span style={{ color: TONE.red }}> · {status}</span> : null}
            {tooPricey ? <span style={{ color: TONE.amber }}> · No te llega</span> : null}
          </span>
        </span>
        <span className="shrink-0 text-right">
          <span className={`block text-[15px] font-semibold tabular-nums ${tooPricey ? "text-white/45" : "text-white"}`}>{money(row.market_value)}</span>
          <span className="block text-[12.5px] font-medium tabular-nums text-peach">{points(row.median)} pts</span>
        </span>
      </button>
      {open ? (
        <div className="row-in grid grid-cols-2 gap-x-4 gap-y-3 px-4 pb-4 pt-1 sm:grid-cols-4">
          <Fact
            label="Blank"
            value={typeof row.blank_rate === "number" ? `${Math.round(row.blank_rate * 100)}%` : "—"}
            tone={blankColor(row.blank_rate)}
            hint={row.sample ? `${row.sample} jornadas` : "sin serie"}
          />
          <Fact label="Suelo / techo" value={`${points(row.floor)} / ${points(row.ceiling)}`} />
          <Fact label="Consistencia" value={typeof row.consistency === "number" ? row.consistency.toFixed(1) : "—"} />
          <Fact
            label="Δ último"
            value={typeof last === "number" ? signedMoney(last) : "—"}
            tone={toneOf(last)}
            hint={trendLabel(row)}
          />
          {asset ? (
            <div className="col-span-2 sm:col-span-4">
              <Verdict {...asset} />
            </div>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

/**
 * Catálogo profundo: agentes libres con perfil de jornadas, inflación esperada
 * y arbitraje de lesiones. Lee ``/api/catalog/free-agents`` y
 * ``/api/catalog/arbitrage``, que solo miran la foto guardada y el caché.
 * Sin foto no se pinta una lista inventada.
 */
export function LabSection({ photos }: { photos: PhotoIndex }) {
  const search = useSearchParams();
  const league = search.get("league");
  const { state } = useDashboard();
  const budget = bidBudget(state.plan?.cash_eur, state.squads?.self?.market_value_total);
  const [vista, setVista] = useState<Vista>("libres");
  const [free, setFree] = useState<{ league: string | null; payload: FreeAgentsPayload } | null>(() => {
    const cached = peekJson<FreeAgentsPayload>(endpoint("/api/catalog/free-agents", league));
    return cached ? { league, payload: cached } : null;
  });
  const [arb, setArb] = useState<{ league: string | null; payload: ArbitragePayload } | null>(() => {
    const cached = peekJson<ArbitragePayload>(endpoint("/api/catalog/arbitrage", league));
    return cached ? { league, payload: cached } : null;
  });

  useEffect(() => {
    let cancelled = false;
    cachedJson<FreeAgentsPayload>(endpoint("/api/catalog/free-agents", league))
      .then((payload) => {
        if (!cancelled) setFree({ league, payload });
      })
      .catch(() => {
        if (!cancelled) setFree({ league, payload: { ok: false, error: { message: "Sin /api/catalog/free-agents." } } });
      });
    cachedJson<ArbitragePayload>(endpoint("/api/catalog/arbitrage", league))
      .then((payload) => {
        if (!cancelled) setArb({ league, payload });
      })
      .catch(() => {
        if (!cancelled) setArb({ league, payload: { ok: false, error: { message: "Sin /api/catalog/arbitrage." } } });
      });
    return () => {
      cancelled = true;
    };
  }, [league]);

  const freePayload = free && free.league === league ? free.payload : null;
  const arbPayload = arb && arb.league === league ? arb.payload : null;

  const lists = useMemo<Record<Vista, CatalogProfilePlayer[]>>(() => {
    // Los libres que superan tu presupuesto de puja pasan al final: siguen visibles, pero no mandan.
    const reach = (rows: CatalogProfilePlayer[]) => [
      ...rows.filter((row) => !(row.is_free_agent && beyondBudget(row.market_value, budget))),
      ...rows.filter((row) => row.is_free_agent && beyondBudget(row.market_value, budget)),
    ];
    return {
      libres: reach(onlyPlayers(freePayload?.top_free)),
      suelo: reach(onlyPlayers(arbPayload?.distressed)),
      refugio: reach(onlyPlayers(arbPayload?.refuge)),
      riesgo: reach(onlyPlayers(arbPayload?.risk)),
    };
  }, [freePayload, arbPayload, budget]);
  const freeCount = useMemo(() => onlyPlayers(freePayload?.free_agents).length, [freePayload]);

  if (freePayload === null || arbPayload === null) {
    return <div className="eq-skel h-40" aria-busy="true" aria-label="Cargando catálogo" />;
  }
  if (freePayload.ok === false && arbPayload.ok === false) {
    return (
      <p className="home-glass px-4 py-4 text-[13.5px] text-white/50">
        Sin catálogo guardado: {errorText(freePayload, "pulsa Actualizar para leerlo.")}
      </p>
    );
  }

  const counts = freePayload.counts || arbPayload.counts;
  const inflation = freePayload.inflation;
  const current = VISTAS.find((item) => item.id === vista)!;
  const rows = lists[vista];

  return (
    <section className="flex flex-col gap-3">
      <SectionHead title="Fuera del mercado" meta={`${freeCount} libres con perfil`} />
      {inflation ? (
        <div className="home-glass px-4 py-3.5">
          <div className="flex items-center justify-between gap-3">
            <Verdict {...(INFLATION[inflation.level || ""] || { label: "Inflación sin medir", color: TONE.gray })} />
            <span className="text-[13px] tabular-nums text-white/50">
              {inflation.top_free_count ?? 0} top libres · {compact(inflation.top_free_liquidity_eur)}
            </span>
          </div>
          {inflation.recommendation ? <p className="mt-2 text-[13px] leading-snug text-white/65">{inflation.recommendation}</p> : null}
        </div>
      ) : null}
      <div className="eq-scroll">
        {VISTAS.map((item) => (
          <button
            key={item.id}
            type="button"
            aria-pressed={vista === item.id}
            onClick={() => setVista(item.id)}
            className={vista === item.id ? "eq-chip eq-chip--on" : "eq-chip"}
          >
            {item.label}
            <span className="tabular-nums opacity-60">{lists[item.id].length}</span>
          </button>
        ))}
      </div>
      <p className="px-1 text-[12.5px] text-white/50">{current.hint}</p>
      {rows.length ? (
        <ul className="home-glass overflow-hidden">
          {rows.map((row, index) => (
            <ProfileRow
              key={`${vista}-${row.player_id}`}
              row={row}
              index={index}
              tooPricey={Boolean(row.is_free_agent) && beyondBudget(row.market_value, budget)}
              photo={photoFor(photos, String(row.player_id), row.nickname || row.name || "")}
            />
          ))}
        </ul>
      ) : (
        <p className="home-glass px-4 py-4 text-[13.5px] text-white/50">{current.empty}</p>
      )}
      <p className="px-1 text-[12px] leading-relaxed text-white/35">
        Perfil de {counts?.profiled ?? 0} jugadores con serie real · catálogo {counts?.catalog ?? 0} · {counts?.owned ?? 0} fichados en tu liga.
        Entrenadores excluidos. «No te llega» = vale más que tu caja más el 20 % de endeudamiento. No sustituye al veredicto de Hoy.
      </p>
    </section>
  );
}
