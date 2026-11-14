"use client";

import { useEffect, useMemo, useRef, useState } from "react";
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

const LINES: { id: string; label: string }[] = [
  { id: "POR", label: "Portería" },
  { id: "DEF", label: "Defensa" },
  { id: "MC", label: "Medio" },
  { id: "DEL", label: "Ataque" },
];

function lineTotal(xi: LeagueXiPlayer[] | undefined, line: string): number {
  return (xi || []).filter((player) => (String(player.position || "").toUpperCase() === "MED" ? "MC" : String(player.position || "").toUpperCase()) === line).reduce((sum, player) => sum + ev(player), 0);
}

function diffText(value: number): string {
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${points(Math.abs(value))}`;
}

function diffTone(value: number): string {
  return Math.abs(value) < 0.05 ? "rgba(255,255,255,0.5)" : value > 0 ? TONE.green : TONE.red;
}

function PlayerLine({ player, top, mine, photos }: { player: LeagueXiPlayer; top: number; mine: boolean; photos: PhotoIndex }) {
  const name = player.name || "Jugador";
  return (
    <li className="flex items-center gap-2.5 py-2">
      <Face name={name} src={photoFor(photos, player.player_id, name) || player.image_url} size={30} />
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline justify-between gap-2">
          <span className="truncate text-[13.5px] text-white">{name}</span>
          <span className="shrink-0 text-[13.5px] font-medium tabular-nums text-white">{points(ev(player))}</span>
        </span>
        <span className="mt-0.5 flex items-center gap-1.5 text-[11.5px] text-white/40">
          <Crest club={player.club} size={13} />
          <span className="truncate">{[player.position, player.club].filter(Boolean).join(" · ")}</span>
        </span>
        <span className="mt-1.5 block h-1 overflow-hidden rounded-full bg-white/[0.06]" aria-hidden="true">
          <span className="block h-full rounded-full" style={{ width: `${top > 0 ? Math.max(3, (ev(player) / top) * 100) : 0}%`, background: mine ? "#FFC08A" : "rgba(255,255,255,0.5)" }} />
        </span>
      </span>
    </li>
  );
}

function Column({ title, players, top, mine, photos }: { title: string; players: LeagueXiPlayer[]; top: number; mine: boolean; photos: PhotoIndex }) {
  const total = players.reduce((sum, player) => sum + ev(player), 0);
  return (
    <div className="min-w-0">
      <div className="flex items-baseline justify-between gap-2 border-b border-white/[0.06] pb-2">
        <p className="truncate text-[12.5px] font-semibold text-white/70">{title}</p>
        {players.length ? <p className="shrink-0 text-[11.5px] tabular-nums text-white/40">{points(total)} pts entre {players.length}</p> : null}
      </div>
      <ul className="divide-y divide-white/[0.05]">
        {players.slice(0, SHOWN).map((player) => (
          <PlayerLine key={String(player.player_id ?? player.name)} player={player} top={top} mine={mine} photos={photos} />
        ))}
        {!players.length ? <li className="py-3 text-[13px] text-white/35">Nadie propio: compartís el once.</li> : null}
      </ul>
      {players.length > SHOWN ? <p className="pt-2 text-[11.5px] text-white/35">Y {players.length - SHOWN} más con menos peso.</p> : null}
    </div>
  );
}

/**
 * Tu once esperado frente al de un rival. A la izquierda eliges rival viendo ya
 * quién parte por delante; a la derecha, el marcador, en qué línea ganas o
 * pierdes y los jugadores que no compartís, que son los que deciden.
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

  // En móvil la lista se desliza: el rival elegido se centra para que se vea cuál es.
  const strip = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const box = strip.current;
    const on = box?.querySelector<HTMLElement>('[aria-selected="true"]');
    if (box && on && box.scrollWidth > box.clientWidth) box.scrollLeft = on.offsetLeft - (box.clientWidth - on.offsetWidth) / 2;
  }, [activeId]);

  if (!rivals.length) return null;
  if (!options.length || !rival) {
    // Sin onces no hay duelo; se dice por qué en vez de esconder la tarjeta.
    return <p className="px-1 text-[12px] leading-relaxed text-white/35">Cara a cara: el servidor aún no envía los onces de los rivales (¿versión antigua?).</p>;
  }

  const myTotal = typeof mine?.expected_points === "number" ? mine.expected_points : null;
  const beaten = myTotal !== null ? options.filter((row) => (row.projection?.expected_points ?? 0) < myTotal).length : null;

  // La lista de rivales es el selector: en móvil se desliza en horizontal, en escritorio es una columna.
  const picker = (
    <div
      ref={strip}
      className="relative flex gap-2 overflow-x-auto px-4 pb-4 [scrollbar-width:none] min-[900px]:flex-col min-[900px]:gap-0 min-[900px]:overflow-visible min-[900px]:border-r min-[900px]:border-white/[0.06] min-[900px]:p-2"
      role="tablist"
      aria-label="Elegir rival"
    >
      {options.map((row) => {
        const id = String(row.team_id);
        const on = id === activeId;
        const theirs = row.projection?.expected_points;
        const diff = myTotal !== null && typeof theirs === "number" ? myTotal - theirs : null;
        return (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={on}
            onClick={() => setPicked(id)}
            className={`flex w-[9.5rem] shrink-0 items-center gap-2.5 rounded-xl px-3 py-2.5 text-left transition-colors duration-200 min-[900px]:w-full ${
              on ? "bg-white/[0.09]" : "bg-white/[0.03] hover:bg-white/[0.06] min-[900px]:bg-transparent"
            }`}
          >
            <span className="w-4 shrink-0 text-[12px] tabular-nums" style={{ color: on ? "#FFC08A" : "rgba(255,255,255,0.4)" }}>
              {row.rank ?? "—"}
            </span>
            <span className="min-w-0 flex-1">
              <span className={`block truncate text-[13.5px] ${on ? "font-semibold text-white" : "text-white/75"}`}>{nameOf(row)}</span>
              <span className="mt-0.5 block truncate text-[11.5px] tabular-nums text-white/40">{typeof theirs === "number" ? `${points(theirs)} pts previstos` : "sin proyección"}</span>
            </span>
            {diff !== null ? (
              <span className="shrink-0 text-[12.5px] font-medium tabular-nums" style={{ color: diffTone(diff) }}>
                {diffText(diff)}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );

  const caption =
    myTotal !== null && beaten !== null
      ? `Próxima jornada: tu once apunta a ${points(myTotal)} pts y parte por delante de ${beaten} de ${options.length} rivales. La cifra de cada rival es tu ventaja o desventaja contra él.`
      : "Elige un rival para ver qué se espera de su once en la próxima jornada.";

  const detail = (() => {
    if (!duel) {
      // Falta tu once: se enseña al menos lo que se espera del rival.
      const xi = (rival.projection?.xi || []).slice().sort((a, b) => ev(b) - ev(a));
      return (
        <div className="min-w-0 px-4 pb-4 pt-1 min-[900px]:px-5 min-[900px]:pt-4">
          <p className="text-[12.5px] leading-snug text-white/45">No hay once tuyo que comparar: ficha o alinea jugadores y pulsa Actualizar. Esto es lo que se espera de {nameOf(rival)}.</p>
          <p className="mt-3 text-[2rem] font-semibold leading-none tracking-tight tabular-nums text-white">
            {typeof rival.projection?.expected_points === "number" ? points(rival.projection.expected_points) : "—"}
            <span className="ml-1.5 text-[13px] font-medium text-white/40">pts previstos</span>
          </p>
          <div className="mt-4">
            <Column title="Sus jugadores con más peso" players={xi} top={ev(xi[0] || {})} mine={false} photos={photos} />
          </div>
        </div>
      );
    }

    const edge = duel.edge ?? 0;
    const close = Math.abs(edge) < 1;
    const mineTotal = duel.me.total ?? 0;
    const theirTotal = duel.them.total ?? 0;
    const share = mineTotal + theirTotal > 0 ? (mineTotal / (mineTotal + theirTotal)) * 100 : 50;
    const lines = LINES.map((line) => ({ ...line, me: lineTotal(mine?.xi, line.id), them: lineTotal(rival.projection?.xi, line.id) }));
    const lineTop = Math.max(1, ...lines.flatMap((line) => [line.me, line.them]));
    const best = lines.slice().sort((a, b) => b.me - b.them - (a.me - a.them))[0];
    const worst = lines.slice().sort((a, b) => a.me - a.them - (b.me - b.them))[0];
    const playerTop = Math.max(0.1, ...duel.me.only.map(ev), ...duel.them.only.map(ev));
    const verdict = close
      ? "Jornada muy igualada: se decide en los jugadores que no compartís."
      : edge > 0
        ? `Partes con ventaja sobre ${nameOf(rival)}.`
        : `${nameOf(rival)} parte con ventaja: necesitas que acierten tus diferenciales.`;
    const where = [
      best && best.me - best.them >= 0.5 ? `Ganas en ${best.label.toLowerCase()} (${diffText(best.me - best.them)})` : null,
      worst && worst.me - worst.them <= -0.5 ? `${best && best.me - best.them >= 0.5 ? "pierdes" : "Pierdes"} en ${worst.label.toLowerCase()} (${diffText(worst.me - worst.them)})` : null,
    ]
      .filter(Boolean)
      .join(" y ");
    const myCeiling = typeof mine?.ceiling_points === "number" ? mine.ceiling_points : null;
    const theirCeiling = typeof rival.projection?.ceiling_points === "number" ? rival.projection.ceiling_points : null;

    return (
      <div className="min-w-0 px-4 pb-4 pt-1 min-[900px]:px-5 min-[900px]:pt-5">
        <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-end gap-x-4">
          <div className="min-w-0">
            <p className="truncate text-[12.5px] text-peach">Tu once</p>
            <p className="mt-1 text-[2.1rem] font-semibold leading-none tracking-tight tabular-nums text-white">{points(mineTotal)}</p>
            {myCeiling !== null ? <p className="mt-1.5 text-[11.5px] tabular-nums text-white/40">techo {points(myCeiling)}</p> : null}
          </div>
          <p className="pb-1 text-center">
            <span className="block text-[17px] font-semibold tabular-nums" style={{ color: close ? "rgba(255,255,255,0.6)" : diffTone(edge) }}>
              {diffText(edge)}
            </span>
            <span className="block text-[11px] text-white/35">para ti</span>
          </p>
          <div className="min-w-0 text-right">
            <p className="truncate text-[12.5px] text-white/55">{nameOf(rival)}</p>
            <p className="mt-1 text-[2.1rem] font-semibold leading-none tracking-tight tabular-nums text-white/75">{points(theirTotal)}</p>
            {theirCeiling !== null ? <p className="mt-1.5 text-[11.5px] tabular-nums text-white/40">techo {points(theirCeiling)}</p> : null}
          </div>
        </div>

        <div className="mt-4 flex h-1.5 gap-1 overflow-hidden rounded-full" aria-hidden="true">
          <span className="rounded-full bg-peach transition-[width] duration-700 ease-out" style={{ width: `${share}%` }} />
          <span className="flex-1 rounded-full bg-white/25" />
        </div>
        <p className="mt-3 text-[13.5px] leading-snug text-white/65">
          <span className="font-semibold text-white">{verdict}</span> {where ? `${where}.` : ""}
        </p>
        {mine?.partial ? <p className="mt-2 text-[12px] leading-snug text-white/40">Tu once está incompleto ({mine.xi?.length ?? 0} de 11): los huecos puntúan 0.</p> : null}

        <div className="mt-6">
          <p className="border-b border-white/[0.06] pb-2 text-[12.5px] font-semibold text-white/70">Línea a línea</p>
          <ul className="mt-1">
            {lines.map((line) => {
              const diff = line.me - line.them;
              return (
                <li key={line.id} className="grid grid-cols-[2.75rem_minmax(0,1fr)_4.5rem_minmax(0,1fr)_2.75rem] items-center gap-x-2.5 py-2">
                  <span className={`text-right text-[13.5px] tabular-nums ${diff >= 0 ? "font-semibold text-white" : "text-white/50"}`}>{points(line.me)}</span>
                  <span className="flex h-2 justify-end overflow-hidden rounded-full bg-white/[0.05]" aria-hidden="true">
                    <span className="h-full rounded-full bg-peach transition-[width] duration-500 ease-out" style={{ width: `${(line.me / lineTop) * 100}%` }} />
                  </span>
                  <span className="text-center">
                    <span className="block text-[12px] text-white/60">{line.label}</span>
                    <span className="block text-[11px] tabular-nums" style={{ color: diffTone(diff) }}>
                      {diffText(diff)}
                    </span>
                  </span>
                  <span className="flex h-2 overflow-hidden rounded-full bg-white/[0.05]" aria-hidden="true">
                    <span className="h-full rounded-full bg-white/50 transition-[width] duration-500 ease-out" style={{ width: `${(line.them / lineTop) * 100}%` }} />
                  </span>
                  <span className={`text-[13.5px] tabular-nums ${diff < 0 ? "font-semibold text-white" : "text-white/50"}`}>{points(line.them)}</span>
                </li>
              );
            })}
          </ul>
        </div>

        <div className="mt-5 grid gap-x-6 gap-y-5 min-[640px]:grid-cols-2">
          <Column title="Solo los tienes tú" players={duel.me.only} top={playerTop} mine photos={photos} />
          <Column title={`Solo los tiene ${nameOf(rival)}`} players={duel.them.only} top={playerTop} mine={false} photos={photos} />
        </div>
        <p className="mt-4 text-[12px] leading-relaxed text-white/35">
          {duel.shared.length ? `Compartís ${duel.shared.length} ${duel.shared.length === 1 ? "jugador" : "jugadores"}: puntúan igual para los dos y no deciden nada. ` : ""}
          Es una proyección: el rival puede alinear distinto.
        </p>
      </div>
    );
  })();

  return (
    <section className="home-glass overflow-hidden" aria-label="Cara a cara">
      <CardHead title="Cara a cara" caption={caption} />
      <div className="min-[900px]:grid min-[900px]:grid-cols-[15.5rem_minmax(0,1fr)] min-[900px]:border-t min-[900px]:border-white/[0.06]">
        {picker}
        {detail}
      </div>
    </section>
  );
}
