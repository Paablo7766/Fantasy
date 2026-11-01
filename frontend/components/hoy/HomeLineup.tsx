"use client";

import { PlayerAvatar } from "@/components/PlayerAvatar";
import { points, titularShare } from "@/lib/format";
import { signedPoints } from "@/lib/hoy";
import { photoFor, type PhotoIndex } from "@/lib/photoIndex";
import type { CapitanPick, OptimizePayload, PlanPayload } from "@/lib/types";

type Swap = {
  outName: string;
  outPos: string;
  outEv: number | null;
  inName: string;
  inPos: string;
  inEv: number | null;
};

type Mover = { name: string; position: string; ev: number | null };

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
    const incoming = at >= 0 ? pool.splice(at, 1)[0] : pool.shift();
    if (!incoming) break;
    swaps.push({
      outName: out.name,
      outPos: out.position,
      outEv: out.ev,
      inName: incoming.name,
      inPos: incoming.position,
      inEv: incoming.ev,
    });
  }
  return swaps;
}

function Captain({ pick, photos, label }: { pick: CapitanPick | null | undefined; photos: PhotoIndex; label: string }) {
  if (!pick?.nombre) return null;
  const base = typeof pick.jornada === "number" ? pick.jornada : typeof pick.si_titular === "number" ? pick.si_titular : null;
  const ceiling = typeof pick.techo === "number" ? pick.techo : null;
  const share = titularShare(pick.p_titular);
  return (
    <div className="min-w-0 flex-1 rounded-xl border border-white/[0.07] p-3">
      <p className="truncate text-[9.5px] font-semibold uppercase tracking-[0.12em] text-[#8B9EB0]">{label}</p>
      <div className="mt-2 flex items-center gap-2.5">
        <PlayerAvatar
          player={{ name: pick.nombre, image_url: photoFor(photos, pick.player_id, pick.nombre) }}
          size="sm"
          className="!h-9 !w-9 !text-[10px] !ring-0 border border-white/[0.12]"
        />
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-white">{pick.nombre}</p>
          {share !== null ? <p className="text-[10.5px] text-[#8B9EB0]">Titular {Math.round(share * 100)}%</p> : null}
        </div>
      </div>
      <div className="mt-2.5 space-y-0.5 font-mono text-[11.5px] tabular-nums">
        {base !== null ? <p className="text-[#0297DE]">x2 = {points(base * 2)} pts</p> : null}
        {ceiling !== null ? <p className="text-[#FC734D]">Techo x2 = {points(ceiling * 2)} pts</p> : null}
      </div>
    </div>
  );
}

function SwapPlayer({ name, position, ev, photos }: { name: string; position: string; ev: number | null; photos: PhotoIndex }) {
  return (
    <span className="flex min-w-0 flex-1 items-center gap-2">
      <PlayerAvatar
        player={{ name, image_url: photoFor(photos, null, name) }}
        size="sm"
        className="!h-7 !w-7 !text-[9px] !ring-0 border border-white/[0.12]"
      />
      <span className="min-w-0">
        <span className="block truncate text-[12.5px] font-medium leading-tight text-white">{name}</span>
        <span className="block font-mono text-[10px] leading-tight text-[#8B9EB0]">
          {position.slice(0, 3)}
          {ev !== null ? ` · ${points(ev)} xP` : ""}
        </span>
      </span>
    </span>
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
  const swaps = buildSwaps(plan, optimize);
  const safe = plan?.capitan_seguro || optimize?.capitan_seguro;
  const bold = plan?.capitan_remontada || optimize?.capitan_remontada;
  const showBold = bold?.nombre && bold.nombre !== safe?.nombre;
  if (!swaps.length && !safe?.nombre && !showBold) return null;

  return (
    <section className="rounded-2xl border border-white/[0.07] bg-[#07121A]" aria-label="Cambios en tu XI y capitanía">
      <h2 className="border-b border-white/[0.05] px-3.5 py-2.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-[#8B9EB0]">
        Cambios en tu XI &amp; capitanía
      </h2>

      {swaps.length ? (
        <ul className="divide-y divide-white/[0.05]">
          {swaps.map((swap, index) => {
            const gain = swap.outEv !== null && swap.inEv !== null ? swap.inEv - swap.outEv : null;
            return (
              <li key={`${swap.outName}-${swap.inName}`} className="row-in flex items-center gap-2 px-3.5 py-2.5" style={{ animationDelay: `${index * 30}ms` }}>
                <SwapPlayer name={swap.outName} position={swap.outPos} ev={swap.outEv} photos={photos} />
                <span className="shrink-0 text-xs text-[#4B6075]" aria-hidden="true">➔</span>
                <SwapPlayer name={swap.inName} position={swap.inPos} ev={swap.inEv} photos={photos} />
                {gain !== null ? (
                  <span className={`shrink-0 font-mono text-[11.5px] font-semibold tabular-nums ${gain >= 0 ? "text-[#0297DE]" : "text-[#FC734D]"}`}>
                    ({signedPoints(gain)})
                  </span>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="px-3.5 py-3 text-[12px] text-[#8B9EB0]">Con el plan tu once no cambia.</p>
      )}

      {safe?.nombre || showBold ? (
        <div className="flex gap-2 border-t border-white/[0.05] p-3">
          <Captain pick={safe} photos={photos} label="Capitán seguro" />
          {showBold ? <Captain pick={bold} photos={photos} label="Capitán remontada" /> : null}
        </div>
      ) : null}
    </section>
  );
}
