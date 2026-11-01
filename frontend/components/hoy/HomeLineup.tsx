"use client";

import { useState } from "react";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { points } from "@/lib/format";
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
      className={`h-4 w-4 shrink-0 text-[#4B6075] transition-transform duration-200 ${open ? "rotate-180" : ""}`}
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
        {caption ? <span className="block truncate text-[12.5px] text-[#8B9EB0]">{caption}</span> : null}
      </span>
    </span>
  );
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
  const swaps = buildSwaps(plan, optimize);
  const safe = plan?.capitan_seguro || optimize?.capitan_seguro;
  const bold = plan?.capitan_remontada || optimize?.capitan_remontada;
  const showBold = bold?.nombre && bold.nombre !== safe?.nombre ? bold : null;
  if (!swaps.length && !safe?.nombre && !showBold) return null;

  const summary = [
    swaps.length ? `${swaps.length} ${swaps.length === 1 ? "cambio" : "cambios"}` : "Sin cambios",
    safe?.nombre ? `Capitán ${safe.nombre}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <section className="overflow-hidden rounded-3xl bg-white/[0.035]" aria-label="Tu once y capitanía">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-4 py-4 text-left transition-colors hover:bg-white/[0.02]"
      >
        <span className="min-w-0">
          <span className="block text-[16px] font-medium text-white">Tu once</span>
          <span className="mt-0.5 block truncate text-[13.5px] text-[#8B9EB0]">{summary}</span>
        </span>
        <Chevron open={open} />
      </button>

      {open ? (
        <div className="row-in border-t border-white/[0.06] px-4 pb-4 pt-3">
          {swaps.length ? (
            <ul className="space-y-3">
              {swaps.map((swap) => {
                const gain = swap.out.ev !== null && swap.into.ev !== null ? swap.into.ev - swap.out.ev : null;
                return (
                  <li key={`${swap.out.name}-${swap.into.name}`} className="flex items-center gap-2.5">
                    <Person name={swap.out.name} caption={swap.out.ev !== null ? `${points(swap.out.ev)} xP` : undefined} photos={photos} />
                    <span className="shrink-0 text-[#4B6075]" aria-hidden="true">→</span>
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
            <p className="text-[14px] text-[#8B9EB0]">Con el plan tu once no cambia.</p>
          )}

          {safe?.nombre || showBold ? (
            <div className="mt-4 space-y-3 border-t border-white/[0.06] pt-4">
              {safe?.nombre ? (
                <div>
                  <p className="mb-2 text-[12.5px] text-[#8B9EB0]">Capitán seguro</p>
                  <Person name={safe.nombre} caption={captainCaption(safe)} photos={photos} />
                </div>
              ) : null}
              {showBold?.nombre ? (
                <div>
                  <p className="mb-2 text-[12.5px] text-[#8B9EB0]">Capitán remontada</p>
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
