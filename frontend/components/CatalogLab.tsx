"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ErrorCard } from "@/components/Feedback";
import { endpoint, getJson } from "@/lib/api";
import { eurShort, points } from "@/lib/format";
import type { ArbitragePayload, CatalogProfilePlayer, FreeAgentsPayload } from "@/lib/types";

type Vista = "libres" | "suelo" | "refugio" | "riesgo";

const INFLATION_TONE: Record<string, string> = {
  normal: "badge badge--good",
  alta: "badge badge--warn",
  extrema: "badge badge--bad",
  desconocida: "badge",
};

const ASSET_LABEL: Record<string, string> = {
  refugio: "refugio",
  riesgo: "lotería",
  equilibrado: "equilibrado",
};

const PLAYABLE = new Set(["POR", "DEF", "MC", "DEL"]);

/**
 * El catálogo de la competición trae también entrenadores: llegan sin
 * ``position`` y con 5,0 de mediana, así que se cuelan en el top de libres.
 * Un entrenador no se ficha ni puntúa: aquí no entra.
 */
function onlyPlayers(rows: CatalogProfilePlayer[]): CatalogProfilePlayer[] {
  return rows.filter((row) => PLAYABLE.has(String(row.position || "").toUpperCase()));
}

function blankTone(rate: number | null | undefined): string {
  if (typeof rate !== "number") return "text-faint";
  if (rate >= 0.4) return "text-coral";
  if (rate >= 0.3) return "text-warn";
  return "text-mint";
}

function TrendCell({ row }: { row: CatalogProfilePlayer }) {
  const trend = row.price_trend;
  if (!trend) return <span className="text-[11px] text-faint">sin histórico</span>;
  const last = trend.last_delta;
  const tone = typeof last === "number" ? (last < 0 ? "text-coral" : last > 0 ? "text-mint" : "text-muted") : "text-muted";
  return (
    <span className="flex flex-col items-end">
      <span className={`metric-value text-[12px] ${tone}`}>
        {typeof last === "number" ? `${last > 0 ? "+" : ""}${last.toLocaleString("es-ES")}` : "s/d"}
      </span>
      <span className="text-[10.5px] text-faint">
        {trend.decelerating ? "caída frenando" : trend.falling ? "cayendo" : trend.recovery ? "recupera" : "estable"}
      </span>
    </span>
  );
}

function ProfileTable({
  rows,
  showTrend = false,
  showRange = false,
}: {
  rows: CatalogProfilePlayer[];
  showTrend?: boolean;
  showRange?: boolean;
}) {
  return (
    <div className="overflow-x-auto rounded-xl border border-[color:var(--line)]">
      <table className="table-dense w-full min-w-[760px] text-left text-sm">
        <thead>
          <tr>
            <th>Jugador</th>
            <th className="text-right">Precio</th>
            <th className="text-right">Mediana</th>
            <th className="text-right">Blank</th>
            {showRange ? <th className="text-right">Suelo / techo</th> : null}
            <th className="text-right">Consistencia</th>
            {showTrend ? <th className="text-right">Δ último</th> : null}
            <th>Tipo</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.player_id}>
              <td>
                <div className="min-w-0">
                  <p className="truncate font-medium tracking-tight">{row.nickname || row.name || "Jugador"}</p>
                  <p className="truncate text-[11px] text-muted">
                    {row.position || "—"}
                    {row.club ? ` · ${row.club}` : ""}
                    {row.is_free_agent ? " · libre" : row.owner_team_id ? " · fichado" : ""}
                    {row.distress_kind === "injured" ? " · lesionado" : ""}
                    {row.distress_kind === "suspended" ? " · sancionado" : ""}
                  </p>
                </div>
              </td>
              <td className="text-right">
                <span className="metric-value text-sm">{eurShort(row.market_value)}</span>
              </td>
              <td className="text-right">
                <span className="metric-value text-sm">{points(row.median)}</span>
                <span className="mt-0.5 block text-[10.5px] text-muted">
                  {row.sample ? `${row.sample} j` : "sin serie"}
                </span>
              </td>
              <td className="text-right">
                <span className={`metric-value text-sm ${blankTone(row.blank_rate)}`}>
                  {typeof row.blank_rate === "number" ? `${Math.round(row.blank_rate * 100)}%` : "s/d"}
                </span>
              </td>
              {showRange ? (
                <td className="text-right text-[11px] text-muted">
                  {points(row.floor)} / {points(row.ceiling)}
                </td>
              ) : null}
              <td className="text-right text-[11px] text-muted">
                {typeof row.consistency === "number" ? row.consistency.toFixed(1) : "s/d"}
              </td>
              {showTrend ? (
                <td className="text-right">
                  <TrendCell row={row} />
                </td>
              ) : null}
              <td>
                <span className={row.asset_class === "riesgo" ? "badge badge--bad" : "badge"}>
                  {ASSET_LABEL[row.asset_class || ""] || row.asset_class || "s/d"}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Catálogo profundo: agentes libres con perfil de jornadas, inflación esperada
 * y arbitraje de lesiones. Lee ``/api/catalog/free-agents`` y
 * ``/api/catalog/arbitrage``, que solo miran la foto guardada y el caché.
 * Sin foto no se pinta una lista inventada.
 */
export function CatalogLab() {
  const search = useSearchParams();
  const league = search.get("league");
  const [vista, setVista] = useState<Vista>("libres");
  const [free, setFree] = useState<{ league: string | null; payload: FreeAgentsPayload } | null>(null);
  const [arb, setArb] = useState<{ league: string | null; payload: ArbitragePayload } | null>(null);

  useEffect(() => {
    let cancelled = false;
    getJson<FreeAgentsPayload>(endpoint("/api/catalog/free-agents", league))
      .then((payload) => {
        if (!cancelled) setFree({ league, payload });
      })
      .catch(() => {
        if (!cancelled) setFree({ league, payload: { ok: false, error: { message: "Sin /api/catalog/free-agents." } } });
      });
    getJson<ArbitragePayload>(endpoint("/api/catalog/arbitrage", league))
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
  const loading = freePayload === null || arbPayload === null;

  const topFree = useMemo(
    () => onlyPlayers(Array.isArray(freePayload?.top_free) ? freePayload!.top_free! : []),
    [freePayload],
  );
  const freeAgents = useMemo(
    () => onlyPlayers(Array.isArray(freePayload?.free_agents) ? freePayload!.free_agents! : []),
    [freePayload],
  );
  const distressed = useMemo(
    () => onlyPlayers(Array.isArray(arbPayload?.distressed) ? arbPayload!.distressed! : []),
    [arbPayload],
  );
  const refuge = useMemo(
    () => onlyPlayers(Array.isArray(arbPayload?.refuge) ? arbPayload!.refuge! : []),
    [arbPayload],
  );
  const risk = useMemo(
    () => onlyPlayers(Array.isArray(arbPayload?.risk) ? arbPayload!.risk! : []),
    [arbPayload],
  );

  if (loading) {
    return (
      <article className="card p-4 md:p-5">
        <p className="eyebrow">Catálogo</p>
        <div className="mt-3 h-28 animate-pulse rounded-xl bg-black/5" />
      </article>
    );
  }

  if (freePayload?.ok === false && arbPayload?.ok === false) {
    return <ErrorCard title="Catálogo" payload={freePayload} brief />;
  }

  const counts = freePayload?.counts || arbPayload?.counts;
  const inflation = freePayload?.inflation;
  const scarcity = inflation?.thresholds;

  return (
    <article className="card flex flex-col p-4 md:p-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <p className="eyebrow">Catálogo · fuera de tu liga</p>
          <h2 className="section-title mt-1">
            <span className="metric-value text-mint">{freeAgents.length}</span> libres
            <span className="mx-2 text-faint">·</span>
            <span className="metric-value text-warn">{refuge.length}</span> refugio
            <span className="mx-2 text-faint">·</span>
            <span className="metric-value text-coral">{risk.length}</span> lotería
          </h2>
          <p className="section-support">
            Perfil de {counts?.profiled ?? 0} jugadores con serie real de jornadas. Un libre sin dueño no cuesta
            cláusula; una lotería tiene techo alto y muchos ceros. Solo lectura del catálogo guardado.
          </p>
        </div>
        {inflation ? (
          <div className="max-w-[22rem] rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-3 py-2">
            <div className="flex items-center justify-between gap-2">
              <p className="metric-label">Inflación esperada</p>
              <span className={INFLATION_TONE[inflation.level || ""] || "badge"}>{inflation.level || "s/d"}</span>
            </div>
            <p className="mt-1 text-[11.5px] leading-4 text-muted">
              {inflation.flag || "sin medir"} · {inflation.top_free_count ?? 0} top libres ·{" "}
              {eurShort(inflation.top_free_liquidity_eur)} de liquidez
            </p>
            {inflation.recommendation ? (
              <p className="mt-1 text-[11px] leading-4 text-faint">{inflation.recommendation}</p>
            ) : null}
            {scarcity ? (
              <p className="mt-1 text-[10.5px] text-faint">
                Umbral escasez: ≤ {scarcity.max_top_free ?? 5} top libres o ≤ {eurShort(scarcity.max_liquidity_eur)}.
              </p>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
        <div className="seg">
          {(
            [
              ["libres", "Agentes libres"],
              ["suelo", "Suelo (lesión)"],
              ["refugio", "Refugio"],
              ["riesgo", "Lotería"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setVista(key)}
              className={vista === key ? "seg__btn seg__btn--active" : "seg__btn"}
              aria-pressed={vista === key}
            >
              {label}
            </button>
          ))}
        </div>
        <p className="text-[11px] leading-4 text-faint">
          {vista === "libres"
            ? "Top libres por mediana: el talento que no exige cláusula."
            : vista === "suelo"
              ? "Caída de precio ya frenada en lesionados o sancionados: tesis de suelo, no de rebote."
              : vista === "refugio"
                ? "Suelo alto y varianza baja: el que no se cae del once."
                : "Techo alto con muchos ceros: se paga la lotería, no el valor."}
        </p>
      </div>

      <div className="mt-3">
        {vista === "libres" ? (
          topFree.length ? (
            <>
              <ProfileTable rows={topFree} />
              <p className="mt-2 text-[11px] text-faint">
                {topFree.length} top libres · liquidez {eurShort(inflation?.top_free_liquidity_eur)} ·{" "}
                {freeAgents.length} libres con perfil en total.
              </p>
            </>
          ) : (
            <p className="rounded-xl border border-[color:var(--line)] px-3 py-3 text-sm text-muted">
              Sin libres de nivel top en esta lectura: o el catálogo no trae series, o están todos fichados.
            </p>
          )
        ) : null}

        {vista === "suelo" ? (
          distressed.length ? (
            <ProfileTable rows={distressed} showTrend showRange />
          ) : (
            <p className="rounded-xl border border-[color:var(--line)] px-3 py-3 text-sm text-muted">
              Ningún lesionado o sancionado con caída de precio ya frenada. Hacen falta al menos 3 días de histórico por
              jugador y que la caída del último día sea menor que la anterior: sin eso el módulo no afirma suelo.
            </p>
          )
        ) : null}

        {vista === "refugio" ? (
          refuge.length ? <ProfileTable rows={refuge} showRange /> : (
            <p className="rounded-xl border border-[color:var(--line)] px-3 py-3 text-sm text-muted">
              Sin refugios: hace falta mediana ≥ 5, desviación ≤ 3 y blank rate ≤ 20 %.
            </p>
          )
        ) : null}

        {vista === "riesgo" ? (
          risk.length ? <ProfileTable rows={risk} showRange showTrend /> : (
            <p className="rounded-xl border border-[color:var(--line)] px-3 py-3 text-sm text-muted">
              Sin loterías: hace falta desviación ≥ 6, blank rate ≥ 35 % y techo ≥ 10.
            </p>
          )
        ) : null}
      </div>

      <p className="mt-3 text-[11px] text-faint">
        Fuente <span className="font-mono">/api/catalog/free-agents</span> y{" "}
        <span className="font-mono">/api/catalog/arbitrage</span> · catálogo {counts?.catalog ?? 0} entradas ·{" "}
        {counts?.owned ?? 0} fichados en tu liga · entrenadores excluidos (llegan sin posición y no puntúan). No
        sustituye al optimizador ni al veredicto de Mercado.
      </p>
    </article>
  );
}
