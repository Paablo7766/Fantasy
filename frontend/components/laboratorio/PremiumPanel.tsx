"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useDashboard } from "@/components/DashboardProvider";
import { endpoint, getJson } from "@/lib/core/api";
import type { PremiumGroup, PremiumReport } from "@/lib/types";

function pct(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return `${(value * 100).toLocaleString("es-ES", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} %`;
}

function GroupTable({ title, rows }: { title: string; rows: PremiumGroup[] }) {
  if (!rows.length) return null;
  return (
    <div className="mt-3">
      <p className="text-[12px] text-white/45">{title}</p>
      <div className="mt-1 overflow-x-auto">
        <table className="w-full text-left text-[12.5px] text-white/80">
          <thead className="text-[11px] uppercase tracking-wide text-white/40">
            <tr>
              <th className="py-1 pr-3 font-medium">Id</th>
              <th className="py-1 pr-3 font-medium">n</th>
              <th className="py-1 pr-3 font-medium">Mediana</th>
              <th className="py-1 pr-3 font-medium">P25</th>
              <th className="py-1 font-medium">P75</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.buyer_id || row.seller_id} className="border-t border-white/10">
                <td className="py-1.5 pr-3 font-mono text-[11.5px]">{row.buyer_id || row.seller_id}</td>
                <td className="py-1.5 pr-3 tabular-nums">
                  {row.n ?? 0}
                  {row.muestra_pequena ? " · n<30" : ""}
                </td>
                <td className="py-1.5 pr-3 tabular-nums">{pct(row.mediana)}</td>
                <td className="py-1.5 pr-3 tabular-nums">{pct(row.p25)}</td>
                <td className="py-1.5 tabular-nums">{pct(row.p75)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Block({ title, group }: { title: string; group: PremiumGroup | undefined }) {
  return (
    <section className="home-glass px-4 py-4">
      <h3 className="text-[15px] font-semibold text-white">{title}</h3>
      <p className="mt-2 text-[13px] text-white/70">
        n {group?.n ?? 0}
        {group?.muestra_pequena ? " · muestra pequeña, no se extrapola" : ""} · mediana {pct(group?.mediana)} · p25{" "}
        {pct(group?.p25)} · p75 {pct(group?.p75)} · mín {pct(group?.minimo)} · máx {pct(group?.maximo)}
      </p>
      <p className="mt-1 text-[12.5px] text-white/45">
        Sin referencia del mismo día: {group?.n_sin_referencia ?? 0}. Sin importe o fecha: {group?.n_sin_datos ?? 0}.
      </p>
      <GroupTable title="Por comprador" rows={group?.por_comprador || []} />
      <GroupTable title="Por vendedor" rows={group?.por_vendedor || []} />
    </section>
  );
}

export function PremiumPanel() {
  const search = useSearchParams();
  const { trends } = useDashboard();
  const league = trends?.league_id || search.get("league");
  const [report, setReport] = useState<PremiumReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getJson<PremiumReport>(endpoint("/api/laboratorio/primas", league))
      .then((payload) => {
        if (!cancelled) setReport(payload);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "No hay prima calculada.");
      });
    return () => {
      cancelled = true;
    };
  }, [league]);

  const comparison = report?.comparacion_laliga;
  const closer =
    comparison?.mas_cerca === "prima_puja"
      ? "4,7 %"
      : comparison?.mas_cerca === "sobreprecio_rival"
        ? "12 %"
        : comparison?.mas_cerca === "empate"
          ? "las dos por igual"
          : null;

  return (
    <section className="flex flex-col gap-3" aria-label="Prima real de la liga">
      <header className="px-1">
        <h2 className="text-[1.15rem] font-semibold text-white">Prima pagada</h2>
        <p className="mt-1 text-[13px] text-white/50">
          Compras a LaLiga y clausulazos, cada uno por su lado. El valor es el de ese mismo día. Sin red.
        </p>
      </header>
      {error ? <p className="home-glass px-4 py-3 text-[13px] text-white/70">{error}</p> : null}
      {report ? (
        <>
          <p className="home-glass px-4 py-3 text-[13.5px] leading-snug text-white/80">
            {closer ? (
              <>
                La mediana de las compras a LaLiga (n={comparison?.n ?? 0}) queda más cerca del {closer}. Las constantes
                no se han tocado.
              </>
            ) : (
              <>No hay compras a LaLiga con valor de mercado del mismo día.</>
            )}{" "}
            {comparison?.nota || report.comparacion_clausulazos?.nota || ""}
          </p>
          <Block title="Compras a LaLiga" group={report.compras_laliga} />
          <Block title="Clausulazos" group={report.clausulazos} />
        </>
      ) : error ? null : (
        <p className="home-glass px-4 py-3 text-[13px] text-white/50">Calculando la prima con la caché…</p>
      )}
    </section>
  );
}
