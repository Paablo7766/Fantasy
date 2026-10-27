"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { endpoint, getJson } from "@/lib/api";
import { accel, eurShort, playerName, points, roiPct } from "@/lib/format";
import type { QuantPlayer, QuantRadarPayload } from "@/lib/types";

const VERDICT_TONE: Record<string, string> = {
  COMPRAR: "badge badge--good",
  VIGILAR: "badge badge--warn",
  TOXICO: "badge badge--bad",
  MERCADO: "badge",
  NO_FICHABLE: "badge",
  SIN_MUESTRA: "badge",
};

const REASON_LABEL: Record<string, string> = {
  smart_money: "dinero acelerando",
  infravalorado: "infravalorado",
  cerca_del_umbral: "cerca del umbral",
  volatilidad: "volatilidad alta",
  blank_rate_alto: "deja jornadas en blanco",
  precio_en_linea: "precio en línea",
  sin_momentum: "sin momentum",
  pocas_jornadas: "pocas jornadas",
  sin_puntos: "sin puntos",
  sin_venta_ni_libre: "no está a la venta",
  ya_en_plantilla: "ya es tuyo",
  sin_clausula_ni_venta: "sin cláusula ni venta",
};

function reasonLabel(reason: string): string {
  if (REASON_LABEL[reason]) return REASON_LABEL[reason];
  if (reason.startsWith("fitness_")) return "no disponible";
  return reason.replace(/_/g, " ");
}

function blankTone(rate: number | null | undefined): string {
  if (typeof rate !== "number") return "text-faint";
  if (rate >= 0.4) return "text-coral";
  if (rate >= 0.3) return "text-warn";
  return "text-mint";
}

function EdgeBar({ score }: { score: number | null | undefined }) {
  const value = typeof score === "number" ? Math.max(0, Math.min(100, score)) : 0;
  const tone = value >= 70 ? "bg-[color:var(--mint)]" : value >= 40 ? "bg-[color:var(--warn)]" : "bg-[color:var(--coral)]";
  return (
    <div className="flex items-center gap-2">
      <span className="metric-value w-9 shrink-0 text-right text-sm">{typeof score === "number" ? Math.round(value) : "s/d"}</span>
      <span className="h-1.5 w-14 overflow-hidden rounded-full bg-black/8" aria-hidden="true">
        <span className={`block h-full rounded-full ${tone}`} style={{ width: `${value}%` }} />
      </span>
    </div>
  );
}

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="min-w-[6.5rem] flex-1 rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-3 py-2">
      <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-faint">{label}</p>
      <p className="metric-value mt-1 text-[15px] leading-none text-ink">{value}</p>
      {hint ? <p className="mt-1 truncate text-[10.5px] text-muted">{hint}</p> : null}
    </div>
  );
}

/** Una fila del radar: valor, supervivencia y momentum en la misma línea. */
function QuantRow({ player, rank, tone }: { player: QuantPlayer; rank: number; tone: "buy" | "watch" | "toxic" }) {
  const accent =
    tone === "buy" ? "text-mint" : tone === "watch" ? "text-warn" : "text-coral";
  const discount = player.discount_vs_position;
  return (
    <tr>
      <td className="w-6 text-right text-[11px] text-faint">{rank}</td>
      <td>
        <div className="flex items-center gap-2">
          <span className={`metric-value w-5 shrink-0 text-[11px] ${accent}`}>{player.position || "—"}</span>
          <div className="min-w-0">
            <div className="truncate font-medium tracking-tight">{playerName(player)}</div>
            <div className="truncate text-[11px] text-muted">
              {player.club || "sin club"}
              {player.owner === "libre" ? " · libre" : ""}
              {player.on_market ? " · en venta" : ""}
              {player.manager_name ? ` · ${player.manager_name}` : ""}
            </div>
          </div>
        </div>
      </td>
      <td className="text-right">
        <span className="metric-value text-sm">{eurShort(player.effective_price)}</span>
        {typeof player.market_value === "number" && typeof player.effective_price === "number" && player.effective_price !== player.market_value ? (
          <span className="mt-0.5 block text-[10.5px] text-faint">valor {eurShort(player.market_value)}</span>
        ) : null}
        {player.affordable === false ? <span className="mt-0.5 block text-[10.5px] text-coral">no te llega</span> : null}
      </td>
      <td className="text-right">
        <span className="metric-value text-sm">{points(player.median_points)}</span>
        <span className="mt-0.5 block text-[10.5px] text-muted">{player.games ? `${player.games} j` : "sin serie"}</span>
      </td>
      <td className="text-right">
        <span className={`metric-value text-sm ${blankTone(player.blank_rate)}`}>
          {typeof player.blank_rate === "number" ? `${Math.round(player.blank_rate * 100)}%` : "s/d"}
        </span>
        <span className="mt-0.5 block text-[10.5px] text-muted">≤ 2 pts</span>
      </td>
      <td className="text-right">
        <span className={`metric-value text-sm ${typeof discount === "number" && discount > 0 ? "text-mint" : "text-muted"}`}>
          {roiPct(discount)}
        </span>
        <span className="mt-0.5 block text-[10.5px] text-faint">vs {player.position || "pos."}</span>
      </td>
      <td className="text-right">
        <span className={`metric-value text-sm ${(player.price_delta ?? 0) > 0 ? "text-mint" : (player.price_delta ?? 0) < 0 ? "text-coral" : "text-faint"}`}>
          {accel(player.price_delta)}
        </span>
        <span className="mt-0.5 block text-[10.5px] text-faint">
          {player.smart_money ? "acelera" : typeof player.acceleration === "number" ? "sin acelerar" : "sin dato"}
        </span>
      </td>
      <td>
        <EdgeBar score={player.score} />
      </td>
    </tr>
  );
}

function QuantTable({ rows, tone }: { rows: QuantPlayer[]; tone: "buy" | "watch" | "toxic" }) {
  return (
    <div className="overflow-x-auto">
      <table className="table-dense w-full min-w-[820px] text-left text-sm">
        <thead>
          <tr>
            <th aria-label="Puesto" />
            <th>Jugador</th>
            <th className="text-right">Precio</th>
            <th className="text-right">Mediana</th>
            <th className="text-right">Blank</th>
            <th className="text-right">Descuento</th>
            <th className="text-right">Δ hoy</th>
            <th>Nota</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((player, index) => (
            <QuantRow key={player.player_id} player={player} rank={index + 1} tone={tone} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Reasons({ player }: { player: QuantPlayer }) {
  const reasons = player.reasons || [];
  if (!reasons.length) return null;
  return (
    <span className="flex flex-wrap gap-1">
      {reasons.slice(0, 3).map((reason) => (
        <span key={reason} className={`badge ${reason === "smart_money" ? "badge--good" : ""}`}>
          {reasonLabel(reason)}
        </span>
      ))}
    </span>
  );
}

/**
 * Radar cuantitativo: qué libre o anunciado se ficha hoy por valor intrínseco
 * y momentum global. Lee ``/api/market/quant-radar``, que a su vez solo lee
 * la foto guardada: aquí no se descarga nada.
 */
export function QuantRadarPanel() {
  const search = useSearchParams();
  const league = search.get("league");
  const [loaded, setLoaded] = useState<{ league: string | null; payload: QuantRadarPayload } | null>(null);
  const [open, setOpen] = useState<"watch" | "toxic" | null>(null);
  const payload = loaded && loaded.league === league ? loaded.payload : null;
  const loading = payload === null;

  useEffect(() => {
    let cancelled = false;
    getJson<QuantRadarPayload>(endpoint("/api/market/quant-radar", league))
      .then((value) => {
        if (!cancelled) setLoaded({ league, payload: value });
      })
      .catch(() => {
        if (!cancelled) {
          setLoaded({ league, payload: { ok: false, error: { message: "Sin /api/market/quant-radar." } } });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [league]);

  const buys = useMemo(() => (Array.isArray(payload?.buys) ? payload!.buys! : []), [payload]);
  const watchlist = useMemo(() => (Array.isArray(payload?.watchlist) ? payload!.watchlist! : []), [payload]);
  const toxic = useMemo(() => (Array.isArray(payload?.toxic) ? payload!.toxic! : []), [payload]);
  const smartMoney = useMemo(
    () => (Array.isArray(payload?.momentum?.smart_money) ? payload!.momentum!.smart_money! : []),
    [payload],
  );

  if (loading) {
    return (
      <article className="card p-4 md:p-5">
        <p className="eyebrow">Radar cuantitativo</p>
        <div className="mt-3 h-28 animate-pulse rounded-xl bg-black/5" />
      </article>
    );
  }

  if (!payload || payload.ok === false) {
    return (
      <article className="card p-4 md:p-5">
        <p className="eyebrow">Radar cuantitativo</p>
        <h2 className="section-title mt-1">Sin lectura cuantitativa</h2>
        <p className="section-support">
          {payload?.error?.message || "El endpoint no devolvió la lista priorizada."} Pulsa Actualizar para guardar una
          foto nueva y vuelve a abrir esta pestaña.
        </p>
      </article>
    );
  }

  const summary = payload.summary || {};
  const baselines = payload.baselines || {};
  const weights = payload.assumptions?.weights;

  return (
    <article className="card flex flex-col p-4 md:p-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <p className="eyebrow">Radar cuantitativo · value investing</p>
          <h2 className="section-title mt-1">
            <span className="metric-value text-mint">{summary.buys ?? buys.length}</span> compras fuertes
            <span className="mx-2 text-faint">·</span>
            <span className="metric-value text-warn">{summary.watchlist ?? watchlist.length}</span> en vigilancia
          </h2>
          <p className="section-support">
            Coste por punto contra la mediana de su posición, penalizando la probabilidad de dejar la jornada en blanco.
            Solo entra lo que puedes fichar hoy: libre o ya anunciado.{" "}
            {payload.sources?.players_scored ?? summary.scanned ?? 0} jugadores escaneados ·{" "}
            {payload.sources?.real_series ?? 0} con serie real de jornadas.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Metric label="Smart money" value={String(summary.smart_money ?? 0)} hint="precio acelerando" />
          <Metric label="Infravalorados" value={String(summary.undervalued ?? 0)} hint="≥ 30 % bajo su posición" />
          <Metric label="Tóxicos" value={String(summary.toxic ?? 0)} hint="blank rate alto" />
          <Metric label="Caja" value={eurShort(payload.cash_eur)} hint="para pujar" />
        </div>
      </div>

      <section className="mt-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <p className="eyebrow">Compras fuertes</p>
          <p className="text-[11px] text-muted">
            {buys.length < (summary.buys ?? buys.length)
              ? `Las ${buys.length} mejores por nota · `
              : "Ordenadas por nota · "}
            valor 55 % · descuento 25 % · momentum 20 %
          </p>
        </div>
        {buys.length ? (
          <>
            <div className="mt-2 overflow-x-auto rounded-xl border border-[color:var(--line)]">
              <QuantTable rows={buys} tone="buy" />
            </div>
            <div className="mt-3 grid gap-2 md:grid-cols-2">
              {buys.slice(0, 4).map((player) => (
                <div
                  key={`buy-${player.player_id}`}
                  className="rounded-xl border border-[color:var(--line)] bg-[color:var(--mint-soft)] px-3 py-2.5"
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="truncate font-medium">{playerName(player)}</span>
                    <span className="metric-value shrink-0 text-sm text-mint">{eurShort(player.effective_price)}</span>
                  </div>
                  <p className="mt-1 text-[11px] leading-4 text-muted-strong">
                    {points(player.median_points)} pts de mediana en {player.games || 0} jornadas · deja la jornada en
                    blanco el {typeof player.blank_rate === "number" ? Math.round(player.blank_rate * 100) : "—"} % de
                    las veces · {(player.discount_vs_position ?? 0) > 0 ? roiPct(player.discount_vs_position) : "sin descuento"}{" "}
                    más barato por punto que su posición.
                  </p>
                  <div className="mt-1.5">
                    <Reasons player={player} />
                  </div>
                </div>
              ))}
            </div>
          </>
        ) : (
          <p className="mt-2 rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-3 py-4 text-sm text-muted">
            Ningún fichable cumple hoy las tres condiciones a la vez: barato por punto, con muestra real y con una
            varianza que no deje la jornada en blanco. Mejor esperar que comprar una trampa.
          </p>
        )}
      </section>

      <section className="mt-6 grid gap-4 lg:grid-cols-2">
        <div className="min-w-0">
          <div className="flex items-baseline justify-between gap-2">
            <p className="eyebrow">Masa monetaria global</p>
            <span className="text-[11px] text-faint">
              {payload.momentum?.counts?.up ?? 0} suben · {payload.momentum?.counts?.down ?? 0} bajan
            </span>
          </div>
          {smartMoney.length ? (
            <ul className="mt-2 divide-y divide-[color:var(--line)] rounded-xl border border-[color:var(--line)]">
              {smartMoney.slice(0, 8).map((player) => (
                <li key={`smart-${player.player_id}`} className="flex items-center gap-2 px-3 py-2">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{playerName(player)}</p>
                    <p className="truncate text-[11px] text-muted">
                      {player.position || "—"}
                      {player.club ? ` · ${player.club}` : ""}
                      {player.in_catalog === false ? " · fuera del catálogo" : ""}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="metric-value text-[13px] text-mint">{accel(player.price_delta)}</p>
                    <p className="text-[10.5px] text-faint">acel. {accel(player.acceleration)}</p>
                  </div>
                  <span className={VERDICT_TONE[player.verdict || ""] || "badge"}>
                    {player.verdict === "SIN_MUESTRA" ? "sin muestra" : (player.verdict || "—").toLowerCase()}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-3 py-4 text-sm text-muted">
              La foto no trae aceleración positiva con precio subiendo. Sin dinero acelerando no hay señal global.
            </p>
          )}
        </div>

        <div className="min-w-0">
          <p className="eyebrow">Referencia de precio</p>
          <p className="mt-1 text-[11.5px] leading-5 text-muted">
            El «PER» del jugador es cuánto cuesta cada punto que produce de verdad. Se compara con la mediana de su
            posición: un MC de 2 M que puntúa como uno de 6 M es una ineficiencia, no una corazonada.
          </p>
          <dl className="mt-2 overflow-hidden rounded-xl border border-[color:var(--line)]">
            {(["POR", "DEF", "MC", "DEL"] as const).map((position) => {
              const row = baselines[position];
              return (
                <div
                  key={position}
                  className="flex items-baseline justify-between gap-2 border-b border-[color:var(--line)] px-3 py-2 last:border-b-0"
                >
                  <dt className="text-sm font-medium">{position}</dt>
                  <dd className="text-right text-[11.5px] text-muted">
                    <span className="metric-value block text-[13px] text-ink">
                      {eurShort(row?.median_cost_per_point_eur)}
                      <span className="ml-1 font-normal text-faint">/ punto</span>
                    </span>
                    {row?.count ?? 0} con muestra · mediana {points(row?.median_points)} pts
                  </dd>
                </div>
              );
            })}
          </dl>
          <p className="mt-2 text-[10.5px] leading-4 text-faint">
            Blank = proporción de jornadas con ≤ {payload.assumptions?.blank_threshold_points ?? 2} puntos. Por encima
            del {Math.round((payload.assumptions?.max_blank_rate ?? 0.4) * 100)} % el activo se marca tóxico aunque esté
            barato. Pesos {weights?.value ?? 0.55}/{weights?.discount ?? 0.25}/{weights?.momentum ?? 0.2}.
          </p>
        </div>
      </section>

      <section className="mt-6">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setOpen((current) => (current === "watch" ? null : "watch"))}
            className={open === "watch" ? "seg__btn seg__btn--active" : "seg__btn"}
            aria-expanded={open === "watch"}
          >
            Vigilancia · {watchlist.length}
          </button>
          <button
            type="button"
            onClick={() => setOpen((current) => (current === "toxic" ? null : "toxic"))}
            className={open === "toxic" ? "seg__btn seg__btn--active" : "seg__btn"}
            aria-expanded={open === "toxic"}
          >
            Tóxicos descartados · {toxic.length}
          </button>
          <span className="text-[11px] text-faint">
            Vigilancia: el dinero acelera pero el precio aún está en línea. Tóxicos: baratos, pero dejan demasiadas
            jornadas en blanco.
          </span>
        </div>

        {open === "watch" ? (
          watchlist.length ? (
            <div className="mt-3 overflow-x-auto rounded-xl border border-[color:var(--line)]">
              <QuantTable rows={watchlist} tone="watch" />
            </div>
          ) : (
            <p className="mt-3 text-sm text-muted">Ningún candidato en vigilancia.</p>
          )
        ) : null}

        {open === "toxic" ? (
          toxic.length ? (
            <div className="mt-3 overflow-x-auto rounded-xl border border-[color:var(--line)]">
              <QuantTable rows={toxic} tone="toxic" />
            </div>
          ) : (
            <p className="mt-3 text-sm text-muted">Ningún activo tóxico entre los fichables.</p>
          )
        ) : null}
      </section>

      <footer className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-[color:var(--line)] pt-3 text-[10.5px] text-faint">
        <span>
          Fuente <span className="font-mono">/api/market/quant-radar</span> · red:{" "}
          <span className="font-mono">{payload.sources?.network || "none"}</span> · catálogo{" "}
          {payload.sources?.catalog_rows ?? 0} · momentum {payload.sources?.momentum_source || "sin fuente"}
        </span>
        <Link href={league ? `/intel?league=${league}` : "/intel"} className="hover:text-ink">
          Señales externas
        </Link>
      </footer>
    </article>
  );
}
