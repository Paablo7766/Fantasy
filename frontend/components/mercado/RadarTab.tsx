"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  Disclosure,
  Empty,
  Face,
  Fact,
  HeroStat,
  SectionHead,
  Skeleton,
  TONE,
  Verdict,
  compact,
  money,
  signedMoney,
  toneOf,
} from "@/components/equipo/ui";
import { endpoint, getJson } from "@/lib/api";
import { photoFor, type PhotoIndex } from "@/lib/photoIndex";
import { playerName, points, roiPct } from "@/lib/format";
import type { QuantPlayer, QuantRadarPayload } from "@/lib/types";

type Tone = "buy" | "watch" | "toxic";

const TONE_COLOR: Record<Tone, string> = { buy: TONE.green, watch: TONE.amber, toxic: TONE.red };

const VERDICT: Record<string, { label: string; color: string }> = {
  COMPRAR: { label: "Comprar", color: TONE.green },
  VIGILAR: { label: "Vigilar", color: TONE.amber },
  TOXICO: { label: "Tóxico", color: TONE.red },
  MERCADO: { label: "Mercado", color: TONE.gray },
  NO_FICHABLE: { label: "No fichable", color: TONE.gray },
  SIN_MUESTRA: { label: "Sin muestra", color: TONE.gray },
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

function blankColor(rate: number | null | undefined): string {
  if (typeof rate !== "number") return TONE.gray;
  if (rate >= 0.4) return TONE.red;
  if (rate >= 0.3) return TONE.amber;
  return TONE.green;
}

/** Nota 0–100 como anillo: el color dice si el valor compensa el riesgo. */
function ScoreRing({ score }: { score: number | null | undefined }) {
  const value = typeof score === "number" ? Math.max(0, Math.min(100, score)) : null;
  const color = value === null ? TONE.gray : value >= 70 ? TONE.green : value >= 40 ? TONE.amber : TONE.red;
  const deg = ((value ?? 0) / 100) * 360;
  return (
    <span
      className="grid h-10 w-10 shrink-0 place-items-center rounded-full"
      style={{ background: `conic-gradient(${color} ${deg}deg, rgba(255,255,255,0.08) 0)` }}
      title="Nota del radar"
    >
      <span className="grid h-[34px] w-[34px] place-items-center rounded-full bg-[#140d0a] text-[12px] font-semibold tabular-nums" style={{ color }}>
        {value === null ? "—" : Math.round(value)}
      </span>
    </span>
  );
}

function QuantRow({ player, photo, tone, index }: { player: QuantPlayer; photo: string | null; tone: Tone; index: number }) {
  const [open, setOpen] = useState(false);
  const name = playerName(player);
  const discount = player.discount_vs_position;
  const reasons = player.reasons || [];
  return (
    <li className="row-in border-b border-white/[0.06] last:border-b-0" style={{ animationDelay: `${Math.min(index, 12) * 30}ms` }}>
      <div className="flex items-center">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex min-h-[4rem] min-w-0 flex-1 items-center gap-3 px-4 py-3 text-left transition-colors duration-200 ease-out hover:bg-white/[0.02]"
      >
        <Face name={name} src={photo} size={42} ring={tone === "buy" ? TONE_COLOR.buy : undefined} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[15px] font-medium leading-tight text-white">{name}</span>
          <span className="mt-0.5 block truncate text-[12.5px] text-white/45">
            {[player.position, player.club, player.owner === "libre" ? "libre" : "", player.on_market ? "en venta" : "", player.manager_name]
              .filter(Boolean)
              .join(" · ")}
          </span>
        </span>
        <span className="shrink-0 text-right">
          <span className="block text-[15px] font-semibold tabular-nums text-white">{money(player.effective_price)}</span>
          <span className="block text-[12px] font-medium tabular-nums" style={{ color: typeof discount === "number" && discount > 0 ? TONE.green : "rgba(255,255,255,0.45)" }}>
            {typeof discount === "number" && discount > 0 ? `${roiPct(discount)} barato` : "sin descuento"}
          </span>
        </span>
        <ScoreRing score={player.score} />
      </button>
      </div>
      {open ? (
        <div className="row-in px-4 pb-4 pt-1">
          <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
            <Fact label="Mediana" value={`${points(player.median_points)} pts`} hint={player.games ? `${player.games} jornadas` : "sin serie"} />
            <Fact
              label="Blank"
              value={typeof player.blank_rate === "number" ? `${Math.round(player.blank_rate * 100)}%` : "—"}
              tone={blankColor(player.blank_rate)}
              hint="jornadas ≤ 2 pts"
            />
            <Fact
              label="Δ hoy"
              value={signedMoney(player.price_delta)}
              tone={toneOf(player.price_delta)}
              hint={player.smart_money ? "acelera" : typeof player.acceleration === "number" ? "sin acelerar" : "sin dato"}
            />
            <Fact
              label="Valor"
              value={money(player.market_value)}
              hint={player.affordable === false ? "no te llega" : undefined}
              tone={player.affordable === false ? TONE.red : undefined}
            />
          </div>
          {reasons.length ? (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {reasons.slice(0, 4).map((reason) => (
                <span
                  key={reason}
                  className="rounded-full px-2.5 py-1 text-[11.5px] font-medium"
                  style={
                    reason === "smart_money"
                      ? { color: TONE.green, background: `${TONE.green}1f` }
                      : { color: "rgba(255,255,255,0.6)", background: "rgba(255,255,255,0.06)" }
                  }
                >
                  {reasonLabel(reason)}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

function QuantList({ rows, tone, photos }: { rows: QuantPlayer[]; tone: Tone; photos: PhotoIndex }) {
  return (
    <ul className="home-glass overflow-hidden">
      {rows.map((player, index) => (
        <QuantRow
          key={`${tone}-${player.player_id}`}
          player={player}
          tone={tone}
          index={index}
          photo={photoFor(photos, String(player.player_id), playerName(player))}
        />
      ))}
    </ul>
  );
}

/**
 * Radar cuantitativo: qué libre o anunciado se ficha hoy por valor intrínseco
 * y momentum global. Lee ``/api/market/quant-radar``, que a su vez solo lee
 * la foto guardada: aquí no se descarga nada.
 */
export function RadarTab({ photos }: { photos: PhotoIndex }) {
  const search = useSearchParams();
  const league = search.get("league");
  const [loaded, setLoaded] = useState<{ league: string | null; payload: QuantRadarPayload } | null>(null);
  const payload = loaded && loaded.league === league ? loaded.payload : null;

  useEffect(() => {
    let cancelled = false;
    getJson<QuantRadarPayload>(endpoint("/api/market/quant-radar", league))
      .then((value) => {
        if (!cancelled) setLoaded({ league, payload: value });
      })
      .catch(() => {
        if (!cancelled) setLoaded({ league, payload: { ok: false, error: { message: "Sin /api/market/quant-radar." } } });
      });
    return () => {
      cancelled = true;
    };
  }, [league]);

  const buys = useMemo(() => (Array.isArray(payload?.buys) ? payload!.buys! : []), [payload]);
  const watchlist = useMemo(() => (Array.isArray(payload?.watchlist) ? payload!.watchlist! : []), [payload]);
  const toxic = useMemo(() => (Array.isArray(payload?.toxic) ? payload!.toxic! : []), [payload]);
  const smartMoney = useMemo(() => (Array.isArray(payload?.momentum?.smart_money) ? payload!.momentum!.smart_money! : []), [payload]);

  if (payload === null) return <Skeleton />;
  if (payload.ok === false) {
    return (
      <Empty
        title="Sin lectura cuantitativa"
        detail={`${payload.error?.message || "El radar no devolvió la lista priorizada."} Pulsa Actualizar para guardar una foto nueva.`}
      />
    );
  }

  const summary = payload.summary || {};
  const baselines = payload.baselines || {};
  const weights = payload.assumptions?.weights;
  const strong = summary.buys ?? buys.length;

  return (
    <div className="flex flex-col gap-5">
      <section className="home-hero" aria-label="Resumen del radar">
        <p className="text-[13px] font-medium text-white/60">Value investing · lo que puedes fichar hoy</p>
        <p className="mt-1 text-[2.6rem] font-semibold leading-none tabular-nums text-white">
          {strong}
          <span className="ml-2 text-[1.1rem] font-medium text-white/60">{strong === 1 ? "compra fuerte" : "compras fuertes"}</span>
        </p>
        <div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <HeroStat value={String(summary.smart_money ?? 0)} label="dinero acelerando" tone={TONE.green} />
          <HeroStat value={String(summary.undervalued ?? 0)} label="infravalorados" tone="#FFC08A" />
          <HeroStat value={String(summary.toxic ?? 0)} label="tóxicos" tone={TONE.red} />
          <HeroStat value={compact(payload.cash_eur)} label="caja" />
        </div>
        <p className="mt-4 text-[12.5px] leading-snug text-white/55">
          Coste por punto contra la mediana de su posición, penalizando las jornadas en blanco.{" "}
          {payload.sources?.players_scored ?? summary.scanned ?? 0} escaneados · {payload.sources?.real_series ?? 0} con serie real.
        </p>
      </section>

      <section className="flex flex-col gap-3">
        <SectionHead title="Compras fuertes" meta={buys.length < strong ? `las ${buys.length} mejores` : `${buys.length}`} />
        {buys.length ? (
          <QuantList rows={buys} tone="buy" photos={photos} />
        ) : (
          <Empty
            title="Nada que comprar hoy"
            detail="Ningún fichable es a la vez barato por punto, con muestra real y fiable. Mejor esperar que comprar una trampa."
          />
        )}
        <p className="px-1 text-[12px] text-white/40">
          Nota: valor {Math.round((weights?.value ?? 0.55) * 100)} % · descuento {Math.round((weights?.discount ?? 0.25) * 100)} % · momentum{" "}
          {Math.round((weights?.momentum ?? 0.2) * 100)} %. Pulsa un jugador para ver el detalle.
        </p>
      </section>

      <section className="flex flex-col gap-3">
        <SectionHead
          title="Dinero global"
          meta={`${payload.momentum?.counts?.up ?? 0} suben · ${payload.momentum?.counts?.down ?? 0} bajan`}
        />
        {smartMoney.length ? (
          <ul className="home-glass overflow-hidden">
            {smartMoney.slice(0, 8).map((player, index) => {
              const name = playerName(player);
              return (
                <li
                  key={`smart-${player.player_id}`}
                  className="row-in flex min-h-[3.75rem] items-center gap-3 border-b border-white/[0.06] px-4 py-2.5 last:border-b-0"
                  style={{ animationDelay: `${index * 30}ms` }}
                >
                  <Face name={name} src={photoFor(photos, String(player.player_id), name)} size={38} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[14.5px] font-medium text-white">{name}</span>
                    <span className="block truncate text-[12px] text-white/45">
                      {[player.position, player.club, player.in_catalog === false ? "fuera del catálogo" : ""].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                  <span className="shrink-0 text-right">
                    <span className="block text-[14.5px] font-semibold tabular-nums" style={{ color: toneOf(player.price_delta) }}>
                      {signedMoney(player.price_delta)}
                    </span>
                    <Verdict {...(VERDICT[player.verdict || ""] || VERDICT.MERCADO)} />
                  </span>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="px-1 text-[13px] text-white/45">Ningún precio sube acelerando: sin dinero entrando no hay señal global.</p>
        )}
      </section>

      <Disclosure title="En vigilancia" meta={`${watchlist.length}`}>
        <p className="mb-3 text-[12.5px] text-white/50">El dinero acelera pero el precio aún está en línea.</p>
        {watchlist.length ? <QuantList rows={watchlist} tone="watch" photos={photos} /> : <p className="text-[13px] text-white/45">Ningún candidato.</p>}
      </Disclosure>

      <Disclosure title="Tóxicos descartados" meta={`${toxic.length}`}>
        <p className="mb-3 text-[12.5px] text-white/50">Baratos, pero dejan demasiadas jornadas en blanco.</p>
        {toxic.length ? <QuantList rows={toxic} tone="toxic" photos={photos} /> : <p className="text-[13px] text-white/45">Ninguno entre los fichables.</p>}
      </Disclosure>

      <Disclosure title="Precio de referencia por posición" meta="€ / punto">
        <p className="text-[12.5px] leading-relaxed text-white/50">
          Cuánto cuesta cada punto que produce un jugador, comparado con la mediana de su posición: un MC de 2 M que puntúa como uno
          de 6 M es una ineficiencia, no una corazonada.
        </p>
        <ul className="mt-2">
          {(["POR", "DEF", "MC", "DEL"] as const).map((position) => {
            const row = baselines[position];
            return (
              <li key={position} className="flex items-center justify-between gap-3 border-b border-white/[0.06] py-2.5 last:border-b-0">
                <span className="text-[14.5px] font-medium text-white">{position}</span>
                <span className="text-right">
                  <span className="block text-[14.5px] font-semibold tabular-nums text-white">{money(row?.median_cost_per_point_eur)}</span>
                  <span className="block text-[12px] text-white/45">
                    {row?.count ?? 0} con muestra · mediana {points(row?.median_points)} pts
                  </span>
                </span>
              </li>
            );
          })}
        </ul>
        <p className="mt-3 text-[12px] leading-relaxed text-white/40">
          Blank = jornadas con ≤ {payload.assumptions?.blank_threshold_points ?? 2} puntos. Por encima del{" "}
          {Math.round((payload.assumptions?.max_blank_rate ?? 0.4) * 100)} % el jugador se marca tóxico aunque esté barato.
        </p>
      </Disclosure>

      <p className="flex flex-wrap items-center justify-between gap-2 px-1 text-[12px] text-white/35">
        <span>
          Catálogo {payload.sources?.catalog_rows ?? 0} · momentum {payload.sources?.momentum_source || "sin fuente"}
        </span>
        <Link href={league ? `/intel?league=${league}` : "/intel"} className="text-white/55 no-underline hover:text-white">
          Señales externas →
        </Link>
      </p>
    </div>
  );
}
