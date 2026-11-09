import { eur } from "@/lib/core/format";
import type { PlanClockEvent } from "@/lib/types";

/** Cláusulas que se abren en las próximas 24 h. La misma pieza en Hoy y en Cláusulas. */
export function UnlockWindow({ rows }: { rows: PlanClockEvent[] | null | undefined }) {
  const items = rows ?? [];
  return (
    <section className="home-glass px-4 py-3" aria-label="Cláusulas que se abren en 24 horas">
      <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-white/45">Se abren en 24 h</p>
      {items.length ? (
        <ul className="mt-2 flex flex-col gap-2">
          {items.map((row) => {
            const name = row.nickname || row.name || "Jugador";
            return (
              <li key={row.player_id || name} className="flex items-baseline justify-between gap-3 text-[13.5px]">
                <span className="min-w-0 truncate text-white">
                  <span className="font-semibold">{name}</span>
                  {row.manager_name ? <span className="text-white/45"> · {row.manager_name}</span> : null}
                </span>
                <span className="shrink-0 tabular-nums text-white/70">
                  {typeof row.buyout_clause === "number" ? eur(row.buyout_clause) : "—"}
                  {row.local_time ? ` · ${row.local_time}` : ""}
                </span>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="mt-1.5 text-[13.5px] text-white/55">Ninguna cláusula se abre en las próximas 24 h.</p>
      )}
    </section>
  );
}
