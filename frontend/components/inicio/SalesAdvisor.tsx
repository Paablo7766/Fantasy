"use client";

import { points } from "@/lib/core/format";
import { projected7d } from "@/components/ui/kit";
import { photoFor, type PhotoIndex } from "@/lib/core/photoIndex";
import { money, signedPct } from "@/components/inicio/ClauseAdvisor";
import { AdvisorRow, Meter, type Fact } from "@/components/inicio/ui";
import type { AuditoriaVenta, VeredictoVenta } from "@/lib/types";

const VERDICT: Record<VeredictoVenta, { label: string; color: string }> = {
  ACEPTAR_YA: { label: "Acepta ya", color: "var(--ini-mint)" },
  RECHAZAR_ESPERAR: { label: "Espera", color: "var(--ini-amber)" },
  RECHAZAR_RIVAL: { label: "No a un rival", color: "var(--ini-red)" },
  PONER_ESCAPARATE: { label: "Ponlo en venta", color: "var(--ini-sky)" },
  MANTENER_INTOCABLE: { label: "No vender", color: "rgba(255,255,255,0.55)" },
};

/** Oferta por tu jugador frente a su valor de mercado. */
export function SaleRow({ row, photos, index }: { row: AuditoriaVenta; photos: PhotoIndex; index: number }) {
  const verdict = VERDICT[row.veredicto_codigo] ?? VERDICT.MANTENER_INTOCABLE;
  const offer = row.oferta_activa;
  const amount = typeof offer.importe_oferta === "number" ? offer.importe_oferta : null;
  const spread = offer.spread_pct;
  const pct = row.prevision_7d_pct;
  const bench = row.tu_once_pierde_sin_el < 0.05;
  const facts: Fact[] = [{ label: "Valor de mercado", value: money(row.valor_mercado) }];
  if (offer.comprador) facts.push({ label: "Comprador", value: offer.comprador });
  if (typeof spread === "number") facts.push({ label: "Sobre su valor", value: signedPct(spread), tone: spread >= 0 ? "var(--ini-mint)" : "var(--ini-red)" });
  if (typeof row.xp_jornada === "number") facts.push({ label: "Puntos esperados", value: `${points(row.xp_jornada)} pts` });
  facts.push({ label: "Tu once pierde", value: bench ? "Nada · fuera del once" : `−${points(row.tu_once_pierde_sin_el)} pts`, tone: bench ? undefined : "var(--ini-red)" });
  if (typeof pct === "number") facts.push({ label: "Valor en 7 días", value: projected7d(row.valor_mercado, pct) !== null ? money(projected7d(row.valor_mercado, pct) as number) : signedPct(pct), tone: pct >= 0 ? "var(--ini-mint)" : "var(--ini-red)" });

  const sub = [
    row.posicion ? row.posicion.slice(0, 3).toUpperCase() : null,
    amount === null ? (offer.comprador ? `Oferta de ${offer.comprador}` : "Sin oferta") : null,
    row.alerta_refuerzo_rival ? "Refuerza a un rival" : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <AdvisorRow
      index={index}
      name={row.nombre}
      sub={sub}
      imageUrl={photoFor(photos, row.player_id, row.nombre)}
      ring={verdict.color}
      verdict={verdict}
      value={amount !== null ? money(amount) : <span className="text-white/45">{money(row.valor_mercado)}</span>}
      meter={amount !== null ? <Meter value={amount} reference={row.valor_mercado} good={amount >= row.valor_mercado} /> : null}
      facts={facts}
      reason={row.motivo_detallado}
    />
  );
}
