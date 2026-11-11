"use client";

import { useMemo, useState } from "react";
import { points } from "@/lib/core/format";
import { headToHead } from "@/lib/liga/headToHead";
import { photoFor, type PhotoIndex } from "@/lib/core/photoIndex";
import type { LeagueProjection, LeagueRaceRow, LeagueXiPlayer } from "@/lib/types";
import { Crest } from "@/components/ui/Crest";
import { Face, TONE } from "@/components/ui/kit";
import { CardHead } from "./parts";

const nameOf = (row: LeagueRaceRow) => row.manager_name || row.fantasy_team_name || "Rival";
const ev = (player: LeagueXiPlayer) => (typeof player.expected_points === "number" ? player.expected_points : 0);

/** Cuántos diferenciales se enseñan por lado. */
const SHOWN = 5;

function PlayerLine({ player, photos }: { player: LeagueXiPlayer; photos: PhotoIndex }) {
  const name = player.name || "Jugador";
  return (
    <li className="flex items-center gap-2.5 py-2">
      <Face name={name} src={photoFor(photos, player.player_id, name) || player.image_url} size={30} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13.5px] text-white">{name}</span>
        <span className="mt-0.5 flex items-center gap-1.5 text-[11.5px] text-white/40">
          <Crest club={player.club} size={13} />
          <span className="truncate">{[player.position, player.club].filter(Boolean).join(" · ")}</span>
        </span>
      </span>
      <span className="shrink-0 text-[13.5px] font-medium tabular-nums text-white">{points(ev(player))}</span>
    </li>
  );
}

function Column({ title, players, photos }: { title: string; players: LeagueXiPlayer[]; photos: PhotoIndex }) {
  const total = players.reduce((sum, player) => sum + ev(player), 0);
  return (
    <div className="min-w-0">
      <div className="flex items-baseline justify-between gap-2 border-b border-white/[0.06] pb-2">
        <p className="truncate text-[12.5px] font-semibold text-white/70">{title}</p>
        {players.length ? <p className="shrink-0 text-[11.5px] tabular-nums text-white/40">{points(total)} pts entre {players.length}</p> : null}
      </div>
      <ul className="divide-y divide-white/[0.05]">
        {players.slice(0, SHOWN).map((player) => (
          <PlayerLine key={String(player.player_id ?? player.name)} player={player} photos={photos} />
        ))}
        {!players.length ? <li className="py-3 text-[13px] text-white/35">Nada propio: compartís el once.</li> : null}
      </ul>
      {players.length > SHOWN ? <p className="pt-2 text-[11.5px] text-white/35">Y {players.length - SHOWN} más con menos peso.</p> : null}
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

  if (!rivals.length) return null;
  if (!options.length || !rival) {
    // Sin onces no hay duelo; se dice por qué en vez de esconder la tarjeta.
    return <p className="px-1 text-[12px] leading-relaxed text-white/35">Cara a cara: el servidor aún no envía los onces de los rivales (¿versión antigua?).</p>;
  }

  const picker = (
    <label className="flex shrink-0 items-center gap-2 text-[12.5px] text-white/45">
      Contra
      <select
        value={activeId ?? ""}
        onChange={(event) => setPicked(event.target.value)}
        className="h-9 max-w-[11rem] rounded-full bg-white/[0.06] px-3 text-[13px] font-medium text-white outline-none"
      >
        {options.map((row) => (
          <option key={String(row.team_id)} value={String(row.team_id)} className="bg-[#141414]">
            {row.rank ? `${row.rank}º · ` : ""}
            {nameOf(row)}
          </option>
        ))}
      </select>
    </label>
  );

  if (!duel) {
    // Falta tu once: se enseña al menos lo que se espera del rival.
    const xi = (rival.projection?.xi || []).slice().sort((a, b) => ev(b) - ev(a));
    return (
      <section className="home-glass overflow-hidden" aria-label="Cara a cara">
        <CardHead title="Cara a cara" caption="Falta tu once proyectado: guarda una alineación de 11 y pulsa Actualizar. Mientras, esto es lo que se espera del rival.">
          {picker}
        </CardHead>
        <div className="border-t border-white/[0.06] px-4 pb-4 pt-4 min-[900px]:px-5">
          <p className="text-[12.5px] text-white/45">Once previsto de {nameOf(rival)}</p>
          <p className="mt-1 text-[2rem] font-semibold leading-none tracking-tight tabular-nums text-white">
            {typeof rival.projection?.expected_points === "number" ? points(rival.projection.expected_points) : "—"}
            <span className="ml-1.5 text-[13px] font-medium text-white/40">pts</span>
          </p>
          <div className="mt-4">
            <Column title="Sus jugadores con más peso" players={xi} photos={photos} />
          </div>
        </div>
      </section>
    );
  }

  const edge = duel.edge ?? 0;
  const close = Math.abs(edge) < 1;
  const mineTotal = duel.me.total ?? 0;
  const theirTotal = duel.them.total ?? 0;
  const share = mineTotal + theirTotal > 0 ? (mineTotal / (mineTotal + theirTotal)) * 100 : 50;
  const verdict = close
    ? "Jornada muy igualada: se decide en los jugadores que no compartís."
    : edge > 0
      ? `Tu once parte con ventaja sobre ${nameOf(rival)}.`
      : `${nameOf(rival)} parte con ventaja: necesitas que acierten tus diferenciales.`;

  return (
    <section className="home-glass overflow-hidden" aria-label="Cara a cara">
      <CardHead title="Cara a cara" caption={`Próxima jornada · ${duel.shared.length} ${duel.shared.length === 1 ? "jugador" : "jugadores"} en común`}>
        {picker}
      </CardHead>

      <div className="border-t border-white/[0.06] px-4 pb-4 pt-5 min-[900px]:px-5">
        <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-end gap-x-4">
          <div className="min-w-0">
            <p className="truncate text-[12.5px] text-white/45">Tu once</p>
            <p className="mt-1 text-[2.1rem] font-semibold leading-none tracking-tight tabular-nums text-white">{points(mineTotal)}</p>
          </div>
          <p className="pb-1 text-center">
            <span className="block text-[15px] font-semibold tabular-nums" style={{ color: close ? "rgba(255,255,255,0.6)" : edge > 0 ? TONE.green : TONE.red }}>
              {edge > 0 ? "+" : edge < 0 ? "−" : ""}
              {points(Math.abs(edge))}
            </span>
            <span className="block text-[11px] text-white/35">pts esperados</span>
          </p>
          <div className="min-w-0 text-right">
            <p className="truncate text-[12.5px] text-white/45">{nameOf(rival)}</p>
            <p className="mt-1 text-[2.1rem] font-semibold leading-none tracking-tight tabular-nums text-white/75">{points(theirTotal)}</p>
          </div>
        </div>

        <div className="mt-4 flex h-1.5 gap-1 overflow-hidden rounded-full" aria-hidden="true">
          <span className="rounded-full bg-[#FFC08A] transition-[width] duration-700 ease-out" style={{ width: `${share}%` }} />
          <span className="flex-1 rounded-full bg-white/25" />
        </div>
        <p className="mt-3 text-[13.5px] leading-snug text-white/65">{verdict}</p>

        <div className="mt-5 grid gap-x-6 gap-y-5 min-[640px]:grid-cols-2">
          <Column title="Solo los tienes tú" players={duel.me.only} photos={photos} />
          <Column title={`Solo los tiene ${nameOf(rival)}`} players={duel.them.only} photos={photos} />
        </div>
      </div>

      <p className="border-t border-white/[0.06] px-4 py-3 text-[12px] leading-relaxed text-white/35 min-[900px]:px-5">
        Los jugadores en común puntúan igual para los dos, así que no se enseñan. Es una proyección: el rival puede alinear distinto.
      </p>
    </section>
  );
}
