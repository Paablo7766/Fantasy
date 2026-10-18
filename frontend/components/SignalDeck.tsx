"use client";

import { ErrorCard, Skeleton } from "@/components/Feedback";
import { accel, eur, glass, multiple, playerName } from "@/lib/format";
import type { Player, SquadsPayload } from "@/lib/types";

function SignalList({
  players,
  tone,
  empty,
  renderMeta,
}: {
  players: Player[];
  tone: "risk" | "sell";
  empty: string;
  renderMeta: (player: Player) => string;
}) {
  if (!players.length) {
    return <p className="rounded-2xl border border-dashed border-white/15 p-4 text-sm text-white/55">{empty}</p>;
  }
  const accent = tone === "risk" ? "text-rose-200" : "text-emerald-300";
  return (
    <ul className="space-y-2">
      {players.map((player) => (
        <li
          key={String(player.player_id || playerName(player))}
          className="flex items-center justify-between gap-3 rounded-2xl border border-white/10 bg-white/5 p-4 transition hover:bg-white/10"
        >
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{playerName(player)}</p>
            <p className="text-[11px] uppercase tracking-[0.14em] text-white/40">{player.position || "Jugador"}</p>
          </div>
          <p className={`shrink-0 text-right font-mono text-xs ${accent}`}>{renderMeta(player)}</p>
        </li>
      ))}
    </ul>
  );
}

export function SignalDeck({ squads, loading }: { squads: SquadsPayload | null; loading: boolean }) {
  if (loading && !squads) {
    return (
      <div className="grid gap-4 md:grid-cols-2">
        <Skeleton title="Blindar urgente" rows={3} />
        <Skeleton title="Vender ya" rows={3} />
      </div>
    );
  }
  if (!squads || squads.ok === false) {
    return <ErrorCard title="Señales de plantilla" payload={squads || { error: { message: "Sin plantilla propia." } }} />;
  }
  const shield = squads.shield || [];
  const sell = squads.sell || [];
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <article className={glass("border-rose-300/25 bg-rose-400/5 p-4")}>
        <div className="mb-4 flex items-end justify-between gap-3">
          <div>
            <p className="text-[11px] uppercase tracking-[0.18em] text-rose-200/80">Riesgo propio</p>
            <h2 className="text-xl font-medium">Blindar urgente</h2>
          </div>
          <span className="font-mono text-2xl text-rose-200">{shield.length}</span>
        </div>
        <p className="mb-3 text-xs leading-5 text-white/50">Cláusula en 1,25 veces el valor, o por debajo.</p>
        <SignalList
          players={shield}
          tone="risk"
          empty="Ningún jugador propio está tan barato de clausular."
          renderMeta={(player) => `${eur(player.buyout_clause)} · ${multiple(player.clause_multiple)}`}
        />
      </article>
      <article className={glass("border-emerald-300/25 bg-emerald-400/5 p-4")}>
        <div className="mb-4 flex items-end justify-between gap-3">
          <div>
            <p className="text-[11px] uppercase tracking-[0.18em] text-emerald-300/80">Pico de valor</p>
            <h2 className="text-xl font-medium">Vender ya</h2>
          </div>
          <span className="font-mono text-2xl text-emerald-300">{sell.length}</span>
        </div>
        <p className="mb-3 text-xs leading-5 text-white/50">Venía subiendo y el tramo de 1 a 3 días se aplana o cae.</p>
        <SignalList
          players={sell}
          tone="sell"
          empty="Ningún jugador propio está en el pico de la subida."
          renderMeta={(player) => `${accel(player.acceleration)} · ${accel(player.price_delta)} 1d`}
        />
      </article>
    </div>
  );
}
