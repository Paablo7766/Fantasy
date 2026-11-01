"use client";

import Link from "next/link";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { points } from "@/lib/format";
import { photoFor, type PhotoIndex } from "@/lib/photoIndex";
import type { CapitanPick, OptimizePayload, PlanPayload } from "@/lib/types";

type Slot = {
  id: string;
  name: string;
  position: string;
  imageUrl: string | null;
  ev: number | null;
};

const LINES: { code: string; match: string[] }[] = [
  { code: "DEL", match: ["DEL", "DL", "FWD"] },
  { code: "MC", match: ["MC", "MED", "MID", "MI"] },
  { code: "DEF", match: ["DEF", "DF"] },
  { code: "POR", match: ["POR", "GK"] },
];

function shortName(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0];
  const last = parts.at(-1) as string;
  return last.length <= 2 && parts.length > 2 ? parts.slice(-2).join(" ") : last;
}

function slotsFrom(plan: PlanPayload | null, optimize: OptimizePayload | null, photos: PhotoIndex): Slot[] {
  const saved = optimize?.saved_lineup?.xi;
  const source = saved?.length ? saved : optimize?.xi?.length ? optimize.xi : null;
  if (source) {
    return source.map((player, index) => {
      const name = player.nickname || player.name || "Jugador";
      return {
        id: player.player_id || `${name}-${index}`,
        name,
        position: (player.position || "").toUpperCase(),
        imageUrl: player.image_url || photoFor(photos, player.player_id, name),
        ev: typeof player.jornada_ev === "number" ? player.jornada_ev : (player.expected_points ?? null),
      };
    });
  }
  return (plan?.lineup?.xi || []).map((player, index) => {
    const name = player.nickname || player.name || "Jugador";
    return {
      id: player.player_id || `${name}-${index}`,
      name,
      position: (player.position || "").toUpperCase(),
      imageUrl: photoFor(photos, player.player_id, name),
      ev: player.expected_points ?? null,
    };
  });
}

function Captain({ pick, photos, label, tone }: { pick: CapitanPick | null | undefined; photos: PhotoIndex; label: string; tone: "orange" | "blue" }) {
  if (!pick?.nombre) return null;
  const value = pick.criterio === "techo" ? pick.techo : (pick.jornada ?? pick.si_titular);
  return (
    <div className="flex min-w-0 flex-1 items-center gap-3 rounded-2xl border border-white/[0.06] bg-white/[0.04] p-2.5">
      <span className={`rounded-full p-[2px] ${tone === "orange" ? "bg-gradient-to-br from-[#FC734D] to-[#FC734D]/20" : "bg-gradient-to-br from-[#0297DE] to-[#0297DE]/20"}`}>
        <PlayerAvatar
          player={{ name: pick.nombre, image_url: photoFor(photos, pick.player_id, pick.nombre) }}
          size="sm"
          className="!h-12 !w-12 !ring-0 border-2 border-[#07121A]"
        />
      </span>
      <span className="min-w-0">
        <span className="block text-[9.5px] font-semibold uppercase tracking-[0.14em] text-[#8B9EB0]">{label}</span>
        <span className="mt-0.5 block truncate text-[14px] font-bold tracking-tight text-[#F0F6FC]">{shortName(pick.nombre)}</span>
        {typeof value === "number" ? (
          <span className={`font-mono text-[11px] font-semibold tabular-nums ${tone === "orange" ? "text-[#FC734D]" : "text-[#67C6F5]"}`}>
            {points(value)} pts
          </span>
        ) : null}
      </span>
    </div>
  );
}

export function HomeLineup({
  plan,
  optimize,
  photos,
}: {
  plan: PlanPayload | null;
  optimize: OptimizePayload | null;
  photos: PhotoIndex;
}) {
  const slots = slotsFrom(plan, optimize, photos);
  const safe = plan?.capitan_seguro || optimize?.capitan_seguro;
  const bold = plan?.capitan_remontada || optimize?.capitan_remontada;
  const formation = plan?.lineup?.saved_formation || optimize?.saved_lineup?.formation || plan?.lineup?.formation || optimize?.formation;
  if (!slots.length && !safe?.nombre) return null;

  const rows = LINES.map((line) => ({
    code: line.code,
    players: slots.filter((slot) => line.match.includes(slot.position)),
  })).filter((row) => row.players.length);
  const placed = new Set(rows.flatMap((row) => row.players.map((player) => player.id)));
  const rest = slots.filter((slot) => !placed.has(slot.id));
  if (rest.length) rows.push({ code: "—", players: rest });

  return (
    <section className="home-card" aria-label="Tu once">
      <div className="flex items-center justify-between gap-2 px-1">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#8B9EB0]">Tu once</p>
          {formation ? <p className="mt-0.5 font-mono text-[13px] font-bold text-[#F0F6FC]">{formation}</p> : null}
        </div>
        <Link href="/equipo" className="text-xs font-semibold text-[#0297DE]">
          Abrir
        </Link>
      </div>

      {rows.length ? (
        <div className="home-pitch mt-3">
          {rows.map((row) => (
            <div key={row.code} className="flex items-start justify-around gap-1">
              {row.players.map((player) => (
                <div key={player.id} className="flex w-[4.1rem] min-w-0 flex-col items-center">
                  <PlayerAvatar
                    player={{ name: player.name, image_url: player.imageUrl }}
                    size="sm"
                    className="!h-12 !w-12 !text-[11px] !ring-2 !ring-white/15"
                  />
                  <span className="mt-1 w-full truncate text-center text-[10.5px] font-semibold leading-tight text-[#F0F6FC]">
                    {shortName(player.name)}
                  </span>
                  {player.ev !== null ? (
                    <span className="font-mono text-[9.5px] font-semibold tabular-nums text-[#FC734D]">{points(player.ev)}</span>
                  ) : null}
                </div>
              ))}
            </div>
          ))}
        </div>
      ) : null}

      {safe?.nombre || bold?.nombre ? (
        <div className="mt-3 flex gap-2">
          <Captain pick={safe} photos={photos} label="Capitán seguro" tone="blue" />
          {bold?.nombre && bold.nombre !== safe?.nombre ? (
            <Captain pick={bold} photos={photos} label="Capitán remontada" tone="orange" />
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
