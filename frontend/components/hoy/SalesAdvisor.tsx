"use client";

import { PlayerAvatar } from "@/components/PlayerAvatar";
import { points } from "@/lib/format";
import { photoFor, type PhotoIndex } from "@/lib/photoIndex";
import type { AuditoriaVenta, ResumenVentas, VeredictoVenta } from "@/lib/types";

const VERDICT: Record<VeredictoVenta, { label: string; color: string }> = {
  ACEPTAR_YA: { label: "ACEPTA YA", color: "#10B981" },
  RECHAZAR_ESPERAR: { label: "RECHAZA Y ESPERA", color: "#F59E0B" },
  RECHAZAR_RIVAL: { label: "NO VENDER A RIVAL", color: "#FC734D" },
  PONER_ESCAPARATE: { label: "PON EN VENTA", color: "#0297DE" },
  MANTENER_INTOCABLE: { label: "NO VENDER", color: "#8B9EB0" },
};

function money(value: number): string {
  return `${(value / 1_000_000).toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} M€`;
}

function signedPct(value: number, digits = 1): string {
  const text = Math.abs(value).toLocaleString("es-ES", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return `${value >= 0 ? "+" : "−"}${text}%`;
}

function Pill({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-lg bg-white/[0.05] px-2 py-1 text-[11px] tabular-nums">
      <span className="text-white/45">{label}</span>
      <span className="font-semibold" style={tone ? { color: tone } : undefined}>
        {value}
      </span>
    </span>
  );
}

function SaleCard({ row, photos, index }: { row: AuditoriaVenta; photos: PhotoIndex; index: number }) {
  const verdict = VERDICT[row.veredicto_codigo] ?? VERDICT.MANTENER_INTOCABLE;
  const offer = row.oferta_activa;
  const hasAmount = typeof offer.importe_oferta === "number";
  const spread = offer.spread_pct;
  const good = typeof spread === "number" && spread >= 0;
  const pct = row.prevision_7d_pct;
  const bench = row.tu_once_pierde_sin_el < 0.05;
  return (
    <article className="home-glass row-in p-4" style={{ animationDelay: `${index * 30}ms` }}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <PlayerAvatar
            player={{ name: row.nombre, image_url: photoFor(photos, row.player_id, row.nombre) }}
            size="sm"
            className="!h-10 !w-10 !text-[11px] !ring-0 border border-white/[0.12]"
          />
          <div className="min-w-0">
            <p className="truncate text-[15.5px] font-medium leading-tight text-white">{row.nombre}</p>
            <p className="mt-0.5 text-[12.5px] text-white/50">{row.posicion ? row.posicion.slice(0, 3).toUpperCase() : "—"}</p>
          </div>
        </div>
        <div className="shrink-0 text-right">
          {hasAmount ? (
            <>
              <p className="text-[1.3rem] font-semibold leading-none tabular-nums text-white">{money(offer.importe_oferta as number)}</p>
              {typeof spread === "number" ? (
                <p className="mt-1.5">
                  <span
                    className="inline-flex rounded-md px-1.5 py-0.5 text-[11px] font-semibold tabular-nums"
                    style={{
                      color: good ? "#10B981" : "#FC734D",
                      background: good ? "rgba(16,185,129,0.14)" : "rgba(252,115,77,0.14)",
                    }}
                  >
                    {signedPct(spread)} de {offer.comprador || "LaLiga"}
                  </span>
                </p>
              ) : null}
              <p className="mt-1 text-[11.5px] tabular-nums text-white/45">Valor: {money(row.valor_mercado)}</p>
            </>
          ) : offer.comprador ? (
            <>
              <p className="text-[13px] font-medium text-white">Oferta de {offer.comprador}</p>
              <p className="mt-1 text-[11.5px] tabular-nums text-white/45">Importe sin leer · Valor {money(row.valor_mercado)}</p>
            </>
          ) : (
            <p className="text-[12px] tabular-nums text-white/50">Sin oferta · Valor {money(row.valor_mercado)}</p>
          )}
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        <span
          className="inline-flex rounded-md px-2 py-1 text-[10.5px] font-bold tracking-wide"
          style={{ color: verdict.color, background: `${verdict.color}22` }}
        >
          {verdict.label}
        </span>
        {typeof row.xp_jornada === "number" ? <Pill label="xP" value={`${points(row.xp_jornada)} pts`} tone="#0297DE" /> : null}
        <Pill
          label="Impacto XI"
          value={bench ? "Suplente" : `−${points(row.tu_once_pierde_sin_el)} pts`}
          tone={bench ? undefined : "#FC734D"}
        />
        {typeof pct === "number" ? <Pill label="7 días" value={signedPct(pct)} tone={pct >= 0 ? "#10B981" : "#FC734D"} /> : null}
        {row.alerta_refuerzo_rival ? (
          <span className="inline-flex rounded-md bg-[#FC734D]/15 px-2 py-1 text-[10.5px] font-semibold text-[#FFA088]">Refuerza a un rival</span>
        ) : null}
      </div>

      <p className="mt-3 rounded-xl bg-black/20 px-3 py-2.5 text-[12.5px] leading-[1.45] text-[#8B9EB0]">{row.motivo_detallado}</p>
    </article>
  );
}

export function SalesAdvisor({
  rows,
  summary,
  photos,
}: {
  rows: AuditoriaVenta[];
  summary: ResumenVentas | null | undefined;
  photos: PhotoIndex;
}) {
  const bits: string[] = [];
  if (summary) {
    bits.push(`Ofertas activas hoy: ${summary.ofertas_activas}${summary.total_ofertas_eur ? ` (Total: ${(summary.total_ofertas_eur / 1_000_000).toLocaleString("es-ES", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} M€)` : ""}`);
    if (typeof summary.spread_medio_laliga_pct === "number") bits.push(`Spread medio LaLiga: ${signedPct(summary.spread_medio_laliga_pct)}`);
    bits.push(`Ventas recomendadas hoy: ${summary.ventas_recomendadas_hoy}`);
  }
  return (
    <div className="flex flex-col gap-3">
      {bits.length ? (
        <p className="inline-flex max-w-full flex-wrap items-center gap-x-4 gap-y-0.5 self-start rounded-2xl border border-white/[0.07] bg-white/[0.04] px-3 py-1.5 text-[12px] tabular-nums text-white/60">
          {bits.map((bit) => (
            <span key={bit}>{bit}</span>
          ))}
        </p>
      ) : null}
      {rows.map((row, index) => (
        <SaleCard key={row.player_id} row={row} photos={photos} index={index} />
      ))}
    </div>
  );
}
