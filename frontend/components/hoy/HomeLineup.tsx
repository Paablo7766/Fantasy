"use client";

import { useState } from "react";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { points, titularShare } from "@/lib/format";
import { signedPoints } from "@/lib/hoy";
import { photoFor, type PhotoIndex } from "@/lib/photoIndex";
import type { CapitanPick, OptimizePayload, PlanPayload } from "@/lib/types";

type Mover = { name: string; position: string; ev: number | null };
type Swap = { out: Mover; into: Mover };

function foldKey(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

/** Quién sale y quién entra en tu once al aplicar el plan, emparejados por línea cuando se puede. */
function buildSwaps(plan: PlanPayload | null, optimize: OptimizePayload | null): Swap[] {
  let leaves: Mover[] = (plan?.lineup?.leaves || []).map((row) => ({
    name: row.nickname || row.name || "Jugador",
    position: (row.position || "").toUpperCase(),
    ev: row.expected_points ?? null,
  }));
  let enters: Mover[] = (plan?.lineup?.enters || []).map((row) => ({
    name: row.nickname || row.name || "Jugador",
    position: (row.position || "").toUpperCase(),
    ev: row.expected_points ?? null,
  }));

  if (!leaves.length && !enters.length) {
    const next = plan?.plan_fichajes?.once;
    const current = optimize?.saved_lineup?.xi?.length ? optimize.saved_lineup.xi : optimize?.xi;
    if (!next?.length || !current?.length) return [];
    const nextKeys = new Set(next.map((row) => foldKey(row.nombre || "")));
    const currentKeys = new Set(current.map((row) => foldKey(row.nickname || row.name || "")));
    leaves = current
      .filter((row) => !nextKeys.has(foldKey(row.nickname || row.name || "")))
      .map((row) => ({
        name: row.nickname || row.name || "Jugador",
        position: (row.position || "").toUpperCase(),
        ev: row.jornada_ev ?? row.expected_points ?? null,
      }));
    enters = next
      .filter((row) => !currentKeys.has(foldKey(row.nombre || "")))
      .map((row) => ({ name: row.nombre || "Jugador", position: (row.posicion || "").toUpperCase(), ev: row.jornada ?? null }));
  }

  const pool = [...enters];
  const swaps: Swap[] = [];
  for (const out of leaves) {
    const at = pool.findIndex((row) => row.position === out.position);
    const into = at >= 0 ? pool.splice(at, 1)[0] : pool.shift();
    if (!into) break;
    swaps.push({ out, into });
  }
  return swaps;
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      viewBox="0 0 16 16"
      className={`h-4 w-4 shrink-0 text-white/35 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      aria-hidden="true"
    >
      <path d="M4 6.2 8 10l4-3.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Person({ name, caption, photos }: { name: string; caption?: string; photos: PhotoIndex }) {
  return (
    <span className="flex min-w-0 flex-1 items-center gap-2.5">
      <PlayerAvatar player={{ name, image_url: photoFor(photos, null, name) }} size="sm" className="!h-9 !w-9 !text-[10px] !ring-0" />
      <span className="min-w-0">
        <span className="block truncate text-[14.5px] font-medium leading-tight text-white">{name}</span>
        {caption ? <span className="block truncate text-[12.5px] text-white/50">{caption}</span> : null}
      </span>
    </span>
  );
}

/** Verde si es titular seguro, ámbar si hay duda, rojo si es poco probable. */
function ringColor(share: number | null): string {
  if (share === null) return "linear-gradient(135deg, rgba(255,255,255,0.3), rgba(255,255,255,0.05))";
  if (share >= 0.8) return "linear-gradient(135deg, #34D399, rgba(52,211,153,0.15))";
  if (share >= 0.5) return "linear-gradient(135deg, #FFB454, rgba(255,180,84,0.15))";
  return "linear-gradient(135deg, #FF5A36, rgba(255,90,54,0.15))";
}

function captainCaption(pick: CapitanPick): string | undefined {
  const base = typeof pick.jornada === "number" ? pick.jornada : typeof pick.si_titular === "number" ? pick.si_titular : null;
  return base !== null ? `x2 = ${points(base * 2)} pts` : undefined;
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
  const [open, setOpen] = useState(false);
  const xi = optimize?.saved_lineup?.xi?.length ? optimize.saved_lineup.xi : optimize?.xi || [];
  const squad = xi.map((player, index) => {
    const name = player.nickname || player.name || "Jugador";
    return {
      id: player.player_id || `${name}-${index}`,
      name,
      short: name.split(/\s+/).at(-1) || name,
      imageUrl: player.image_url || photoFor(photos, player.player_id, name),
      share: titularShare(player.p_titular),
    };
  });
  const knownShares = squad.map((player) => player.share).filter((value): value is number => value !== null);
  const avg = knownShares.length ? knownShares.reduce((total, value) => total + value, 0) / knownShares.length : null;
  const swaps = buildSwaps(plan, optimize);
  const safe = plan?.capitan_seguro || optimize?.capitan_seguro;
  const bold = plan?.capitan_remontada || optimize?.capitan_remontada;
  const showBold = bold?.nombre && bold.nombre !== safe?.nombre ? bold : null;
  if (!squad.length && !swaps.length && !safe?.nombre && !showBold) return null;

  const summary = [
    swaps.length ? `${swaps.length} ${swaps.length === 1 ? "cambio" : "cambios"}` : "Sin cambios",
    safe?.nombre ? `Capitán ${safe.nombre}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <section className="home-glass overflow-hidden" aria-label="Tu once y capitanía">
      <div className="px-4 pt-4">
        <div className="flex items-baseline justify-between gap-3">
          <p className="text-[16px] font-medium text-white">Tu once</p>
          {avg !== null ? <p className="text-[13px] tabular-nums text-white/50">Titularidad {Math.round(avg * 100)}%</p> : null}
        </div>
        {squad.length ? (
          <ul className="mt-4 grid grid-cols-6 gap-x-2 gap-y-3">
            {squad.map((player) => (
              <li key={player.id} className="flex min-w-0 flex-col items-center">
                <span className="rounded-full p-[2px]" style={{ background: ringColor(player.share) }}>
                  <PlayerAvatar
                    player={{ name: player.name, image_url: player.imageUrl }}
                    size="sm"
                    className="!h-10 !w-10 !text-[10px] !ring-0 border-2 border-[#120C09]"
                  />
                </span>
                <span className="mt-1 w-full truncate text-center text-[11px] text-white/60">{player.short}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-4 py-3.5 text-left text-[14px] text-white/60 transition-colors hover:text-white"
      >
        <span className="min-w-0 truncate">{summary}</span>
        <Chevron open={open} />
      </button>

      {open ? (
        <div className="row-in border-t border-white/[0.06] px-4 pb-4 pt-4">
          {swaps.length ? (
            <ul className="space-y-3">
              {swaps.map((swap) => {
                const gain = swap.out.ev !== null && swap.into.ev !== null ? swap.into.ev - swap.out.ev : null;
                return (
                  <li key={`${swap.out.name}-${swap.into.name}`} className="flex items-center gap-2.5">
                    <Person name={swap.out.name} caption={swap.out.ev !== null ? `${points(swap.out.ev)} xP` : undefined} photos={photos} />
                    <span className="shrink-0 text-white/35" aria-hidden="true">→</span>
                    <Person name={swap.into.name} caption={swap.into.ev !== null ? `${points(swap.into.ev)} xP` : undefined} photos={photos} />
                    {gain !== null ? (
                      <span className={`shrink-0 text-[14px] font-medium tabular-nums ${gain >= 0 ? "text-[#0297DE]" : "text-[#FC734D]"}`}>
                        {signedPoints(gain)}
                      </span>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="text-[14px] text-white/50">Con el plan tu once no cambia.</p>
          )}

          {safe?.nombre || showBold ? (
            <div className="mt-4 space-y-3 border-t border-white/[0.06] pt-4">
              {safe?.nombre ? (
                <div>
                  <p className="mb-2 text-[12.5px] text-white/50">Capitán seguro</p>
                  <Person name={safe.nombre} caption={captainCaption(safe)} photos={photos} />
                </div>
              ) : null}
              {showBold?.nombre ? (
                <div>
                  <p className="mb-2 text-[12.5px] text-white/50">Capitán remontada</p>
                  <Person name={showBold.nombre} caption={captainCaption(showBold)} photos={photos} />
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
