"use client";

import { useMemo, useState } from "react";
import { points } from "@/lib/core/format";
import { headToHead } from "@/lib/liga/headToHead";
import { photoFor, type PhotoIndex } from "@/lib/core/photoIndex";
import type { LeagueProjection, LeagueRaceRow, LeagueXiPlayer } from "@/lib/types";
import { Face, TONE } from "@/components/ui/kit";

const nameOf = (row: LeagueRaceRow) => row.manager_name || row.fantasy_team_name || "Rival";

function PlayerLine({ player, photos }: { player: LeagueXiPlayer; photos: PhotoIndex }) {
  const name = player.name || "Jugador";
  return (
    <li className="flex items-center gap-2.5 py-2">
      <Face name={name} src={photoFor(photos, player.player_id, name) || player.image_url} size={28} />
      <span className="min-w-0 flex-1 truncate text-[13.5px] text-white">
        {name}
        {player.position ? <span className="text-white/40"> · {player.position}</span> : null}
      </span>
      <span className="shrink-0 text-[13px] tabular-nums text-white/70">{points(player.expected_points ?? 0)}</span>
    </li>
  );
}

function Column({ title, players, photos }: { title: string; players: LeagueXiPlayer[]; photos: PhotoIndex }) {
  return (
    <div className="min-w-0">
      <p className="truncate text-[12px] text-white/45">{title}</p>
      <ul className="mt-1 divide-y divide-white/[0.05]">
        {players.slice(0, 3).map((player) => (
          <PlayerLine key={String(player.player_id ?? player.name)} player={player} photos={photos} />
        ))}
        {!players.length ? <li className="py-2 text-[13px] text-white/35">Nada propio</li> : null}
      </ul>
    </div>
  );
}

/**
 * Tu once esperado frente al de un rival. Lo que comparten puntúa igual para
 * los dos, así que solo se enseña lo que los separa.
 */
export function HeadToHeadCard({
  mine,
  rivals,
  defaultId,
  photos,
}: {
  mine: LeagueProjection | null | undefined;
  rivals: LeagueRaceRow[];
  defaultId: string | null;
  photos: PhotoIndex;
}) {
  const options = useMemo(
    () => rivals.filter((row) => row.team_id != null && (row.projection?.xi?.length ?? 0) > 0).sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999)),
    [rivals],
  );
  const [picked, setPicked] = useState<string | null>(null);
  const activeId = picked ?? (defaultId && options.some((row) => String(row.team_id) === defaultId) ? defaultId : options[0] ? String(options[0].team_id) : null);
  const rival = options.find((row) => String(row.team_id) === activeId) || null;
  const duel = useMemo(() => (rival ? headToHead(mine, rival.projection) : null), [mine, rival]);

  if (!options.length || !rival || !duel) return null;

  const edge = duel.edge ?? 0;
  const close = Math.abs(edge) < 1;
  const color = close ? TONE.blue : edge > 0 ? TONE.green : TONE.copper;
  const verdict = close
    ? "Jornada muy igualada"
    : edge > 0
      ? `Vas ${points(edge)} pts por delante en la proyección`
      : `Te saca ${points(-edge)} pts en la proyección`;

  return (
    <section className="home-glass p-4" aria-label="Cara a cara">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-[12.5px] text-white/45">Cara a cara · próxima jornada</p>
        <p className="text-[12px] tabular-nums text-white/35">{duel.shared.length} en común</p>
      </div>

      <div className="eq-scroll -mx-1 mt-3 px-1" role="toolbar" aria-label="Elegir rival">
        {options.map((row) => {
          const id = String(row.team_id);
          return (
            <button key={id} type="button" aria-pressed={id === activeId} onClick={() => setPicked(id)} className={id === activeId ? "eq-chip eq-chip--on" : "eq-chip"}>
              {nameOf(row)}
            </button>
          );
        })}
      </div>

      <div className="mt-4 grid grid-cols-2 gap-x-5">
        {[
          { label: "Tu once", value: duel.me.total, color: "#FFC08A" },
          { label: nameOf(rival), value: duel.them.total, color: "#fff" },
        ].map((side) => (
          <div key={side.label} className="min-w-0">
            <p className="truncate text-[12px] text-white/45">{side.label}</p>
            <p className="mt-0.5 text-[24px] font-semibold leading-none tabular-nums" style={{ color: side.color }}>
              {side.value !== null ? points(side.value) : "—"}
              <span className="ml-1 text-[12px] font-medium text-white/40">pts</span>
            </p>
          </div>
        ))}
      </div>
      <p className="mt-3 text-[14px] font-medium" style={{ color }}>
        {verdict}
      </p>

      <div className="mt-3 grid grid-cols-2 gap-x-5 border-t border-white/[0.06] pt-3">
        <Column title="Solo tú" players={duel.me.only} photos={photos} />
        <Column title={`Solo ${nameOf(rival)}`} players={duel.them.only} photos={photos} />
      </div>
      <p className="mt-3 text-[12px] leading-relaxed text-white/35">
        Se enseñan los tres diferenciales más fuertes de cada lado. Es una proyección: el rival puede alinear distinto.
      </p>
    </section>
  );
}
