"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { getJson } from "@/lib/api";
import { eurShort, playerName, points } from "@/lib/format";
import type { QuantRadarPayload } from "@/lib/types";

/**
 * Lo que el dinero y el rendimiento dicen de los fichables de hoy.
 *
 * Es un GET de solo lectura: ``/api/market/quant-radar`` sirve la foto
 * guardada. Sin foto no se pinta una lista inventada.
 */
export function HoyQuant() {
  const search = useSearchParams();
  const league = search.get("league");
  const query = search.toString();
  const [loaded, setLoaded] = useState<{ league: string | null; payload: QuantRadarPayload } | null>(null);
  const payload = loaded && loaded.league === league ? loaded.payload : null;

  useEffect(() => {
    let cancelled = false;
    const query = new URLSearchParams({ limit: "4" });
    if (league) query.set("league", league);
    getJson<QuantRadarPayload>(`/api/market/quant-radar?${query.toString()}`)
      .then((value) => {
        if (!cancelled) setLoaded({ league, payload: value });
      })
      .catch(() => {
        if (!cancelled) setLoaded({ league, payload: { ok: false } });
      });
    return () => {
      cancelled = true;
    };
  }, [league]);

  const buys = payload && payload.ok !== false && Array.isArray(payload.buys) ? payload.buys.slice(0, 3) : [];
  const href = query ? `/mercado?${query}` : "/mercado";

  return (
    <div className="hoy-panel flex min-w-0 flex-col p-4">
      <div className="flex items-baseline justify-between gap-2">
        <p className="hoy-label">Valor intrínseco</p>
        <Link href={href} className="text-[10.5px] text-[color:var(--hoy-faint)] hover:text-[color:var(--hoy-ink)]">
          Radar
        </Link>
      </div>

      {payload === null ? (
        <div className="mt-3 h-16 animate-pulse rounded-lg bg-white/5" />
      ) : buys.length ? (
        <ul className="mt-2 divide-y divide-[color:var(--hoy-line)]">
          {buys.map((player) => (
            <li key={`hoy-quant-${player.player_id}`} className="flex items-baseline gap-2 py-2">
              <div className="min-w-0 flex-1">
                <p className="truncate text-[12.5px] font-medium text-[color:var(--hoy-ink)]">{playerName(player)}</p>
                <p className="truncate text-[10.5px] text-[color:var(--hoy-faint)]">
                  {player.position || "—"}
                  {player.club ? ` · ${player.club}` : ""} · {points(player.median_points)} pts de mediana
                  {typeof player.blank_rate === "number" ? ` · ${Math.round(player.blank_rate * 100)} % en blanco` : ""}
                </p>
              </div>
              <span className="metric-value shrink-0 text-[12px] text-[color:var(--hoy-mint)]">
                {eurShort(player.effective_price)}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-[11px] leading-4 text-[color:var(--hoy-muted)]">
          {payload.ok === false
            ? "Sin lectura cuantitativa. Pulsa Actualizar para guardar la foto."
            : "Hoy ningún fichable está barato por punto sin ser una trampa de varianza."}
        </p>
      )}

      {payload && payload.ok !== false ? (
        <p className="mt-auto pt-2 text-[10px] leading-4 text-[color:var(--hoy-faint)]">
          {payload.summary?.undervalued ?? 0} infravalorados · {payload.summary?.smart_money ?? 0} con dinero acelerando
          · sin mirar a tu liga.
        </p>
      ) : null}
    </div>
  );
}
