"use client";

import { eur, eurShort } from "@/lib/core/format";
import { temperatureClasses, temperatureLabel, type LiquidityRead } from "@/lib/liga/liquidity";

export function ThermometerIcon({ className = "h-3 w-3" }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" className={className} fill="none" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
      <path d="M6.6 9.1V3.6a1.4 1.4 0 0 1 2.8 0v5.5a2.6 2.6 0 1 1-2.8 0Z" strokeLinejoin="round" />
      <path d="M8 6.6v4.1" strokeLinecap="round" />
    </svg>
  );
}

/** Barra del termómetro: ancho = ``temperature``; color = confianza de la cota. */
export function ThermometerBar({ read, className = "w-12" }: { read: LiquidityRead; className?: string }) {
  const classes = temperatureClasses(read.level);
  const width = read.temperaturePct === null ? 0 : Math.min(100, Math.max(3, read.temperaturePct));
  return (
    <span
      className={`inline-flex h-1.5 shrink-0 overflow-hidden rounded-full bg-[color:var(--line)] ${className}`}
      aria-hidden="true"
    >
      <span className={`block h-full rounded-full ${classes.bar}`} style={{ width: `${width}%` }} />
    </span>
  );
}

/**
 * Insignia del grupo de control.
 *
 * - «Calibrado»: la cota sobraba y se apretó al saldo observado (descuento).
 * - «Fuera de libro»: la cota se quedaba corta; hay dinero que los libros no
 *   explican y se declara como arbitraje en vez de taparlo.
 */
export function CalibratedBadge({ read, compact = false }: { read: LiquidityRead; compact?: boolean }) {
  const classes = temperatureClasses(read.level);
  const size = compact ? "text-[10px]" : "text-[11px]";
  const arbitrage = read.arbitrageEur !== null && read.arbitrageEur > 0 ? read.arbitrageEur : null;
  if (arbitrage !== null) {
    return (
      <span
        className={`badge badge--bad ${size} gap-1`}
        title={`${eur(arbitrage)} de caja observada quedan fuera de los libros: la cota se queda corta.`}
      >
        <ThermometerIcon />
        Fuera de libro
      </span>
    );
  }
  if (!read.tightened) return null;
  const hint =
    read.temperaturePct === null
      ? "Cota calibrada contra el saldo observado."
      : `Cota calibrada contra el saldo observado · termómetro ${read.temperaturePct} %.`;
  return (
    <span className={`${classes.badge} ${size} gap-1`} title={hint}>
      <ThermometerIcon />
      Calibrado
    </span>
  );
}

/**
 * Caja con la cota calibrada como valor principal.
 *
 * - Cota apretada (``tightened``): la cifra anterior se queda tachada y tenue al
 *   lado, para ver de dónde sale el descuento sin perder el dato original.
 * - Cota corta (``raised``): no es un descuento; el saldo observado manda y la
 *   cifra de los libros se anota con una flecha, nunca tachada, porque no se
 *   está corrigiendo hacia abajo.
 */
export function CalibratedCash({
  read,
  size = "sm",
  showOriginal = true,
}: {
  read: LiquidityRead;
  size?: "sm" | "lg";
  showOriginal?: boolean;
}) {
  const classes = temperatureClasses(read.level);
  const main = read.calibratedCash ?? read.cash;
  const former = read.tightened || read.raised ? read.cash : null;
  const showsFormer = showOriginal && typeof former === "number" && former !== main;
  const fmt = size === "lg" ? eur : eurShort;
  const text = size === "lg" ? "text-lg" : "text-[12px]";
  const aside = size === "lg" ? "text-[12px]" : "text-[11px]";
  return (
    <span className="inline-flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
      <span className={`metric-value ${text} ${classes.text}`} title={typeof main === "number" ? eur(main) : undefined}>
        {fmt(main)}
      </span>
      {showsFormer && read.tightened ? (
        <s
          className={`${aside} font-normal text-faint decoration-[color:var(--line-strong)]`}
          title={`Cota publicada antes de calibrar: ${eur(former)}`}
        >
          {fmt(former)}
        </s>
      ) : null}
      {showsFormer && !read.tightened ? (
        <span className={`${aside} font-normal text-faint`} title={`Los libros solo justifican ${eur(former)}`}>
          <span aria-hidden="true">↑</span> libros {fmt(former)}
        </span>
      ) : null}
    </span>
  );
}

/** Límite de puja con el desglose de la banda de liquidez. */
export function LiquidityBand({ read, label = "Límite de puja" }: { read: LiquidityRead; label?: string }) {
  const classes = temperatureClasses(read.level);
  const arbitrage = read.arbitrageEur !== null && read.arbitrageEur > 0 ? read.arbitrageEur : null;
  return (
    <div className="min-w-0 rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-3 py-2.5">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <p className="metric-label">{label}</p>
        <span className={`${classes.badge} gap-1 text-[10px]`} title={temperatureLabel(read.level)}>
          <ThermometerIcon />
          {temperatureLabel(read.level)}
        </span>
      </div>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className={`metric-value text-lg ${classes.text}`}>{eurShort(read.bidLimit)}</span>
        {read.bidTightened && typeof read.rawBidLimit === "number" ? (
          <s
            className="text-[11px] text-faint decoration-[color:var(--line-strong)]"
            title={`Tope sin calibrar: ${eur(read.rawBidLimit)}`}
          >
            {eurShort(read.rawBidLimit)}
          </s>
        ) : null}
        {!read.bidTightened &&
        typeof read.rawBidLimit === "number" &&
        typeof read.bidLimit === "number" &&
        read.bidLimit > read.rawBidLimit ? (
          <span className="text-[11px] text-faint" title={`Los libros solo justifican ${eur(read.rawBidLimit)}`}>
            <span aria-hidden="true">↑</span> libros {eurShort(read.rawBidLimit)}
          </span>
        ) : null}
        <span className="ml-auto inline-flex items-center gap-1.5">
          <ThermometerBar read={read} className="w-14" />
          <span className={`metric-value text-[11px] ${classes.text}`}>
            {read.temperaturePct === null ? "s/d" : `${read.temperaturePct} %`}
          </span>
        </span>
      </div>
      <p className="mt-1 text-[11px] leading-4 text-muted">
        {arbitrage === null ? (
          <span className="text-faint">Sin margen de error detectado fuera de los libros.</span>
        ) : (
          <>
            <span className="font-medium text-coral">{eurShort(arbitrage)}</span> sin explicar
            <span className="text-faint"> · arbitraje</span>
          </>
        )}
      </p>
      <details className="mt-2 border-t border-[color:var(--line)] pt-2">
        <summary className="cursor-pointer text-[10.5px] font-medium text-faint transition-colors hover:text-muted-strong">
          Desglose de la cota
        </summary>
        <dl className="mt-1.5 space-y-1 text-[11px]">
          {(
            [
              ["Cota de libros", read.cash],
              ["Cota calibrada", read.calibratedCash],
              ["Saldo observado", read.reconciliation?.observed_cash_eur ?? null],
              ["Puja sin calibrar", read.rawBidLimit],
              ["Arbitraje (sin explicar)", read.arbitrageEur],
              ["Hueco contable", read.reconciliation?.gap_eur ?? null],
              ["σ de caja", read.reconciliation?.posterior_sigma_eur ?? null],
            ] as const
          )
            .filter(([, value]) => typeof value === "number")
            .map(([name, value]) => {
              const outOfBooks = name.startsWith("Arbitraje") && (value ?? 0) > 0;
              return (
                <div key={name} className="flex items-baseline justify-between gap-3">
                  <dt className="text-muted">{name}</dt>
                  <dd className={`metric-value ${outOfBooks ? "text-coral" : "text-ink"}`}>{eur(value)}</dd>
                </div>
              );
            })}
          <div className="flex items-baseline justify-between gap-3">
            <dt className="text-muted">Temperatura</dt>
            <dd className={`metric-value ${classes.text}`}>
              {read.temperaturePct === null ? "s/d" : `${read.temperaturePct} %`}
              <span className="ml-1.5 font-sans text-[10px] font-normal text-faint">
                · {temperatureLabel(read.level).toLowerCase()}
              </span>
            </dd>
          </div>
          {read.reconciliation?.cover_probability !== undefined &&
          read.reconciliation.cover_probability !== null ? (
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-muted">Cubre la caja real</dt>
              <dd className={`metric-value ${classes.text}`}>
                {Math.round(read.reconciliation.cover_probability * 100)} %
              </dd>
            </div>
          ) : null}
        </dl>
        <p className="mt-1.5 text-[10.5px] leading-4 text-faint">
          Temperatura alta = la cota cuadra con el saldo observado. Si baja, la cota es frágil y la puja se acerca al
          riesgo contable.
        </p>
      </details>
    </div>
  );
}
