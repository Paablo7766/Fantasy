"use client";

import { points } from "@/lib/core/format";
import { photoFor, type PhotoIndex } from "@/lib/core/photoIndex";
import { clauseThreats } from "@/lib/liga/threats";
import type { RivalSquad } from "@/lib/types";
import { Disclosure, Face, TONE, money } from "@/components/ui/kit";

/**
 * A quién te pueden quitar ahora mismo: jugadores tuyos con la cláusula
 * abierta y algún rival con caja para pagarla. Si no hay ninguno no sale nada.
 */
export function ThreatRadar({ own, rivals, photos }: { own: RivalSquad | null | undefined; rivals: RivalSquad[]; photos: PhotoIndex }) {
  const threats = clauseThreats(own, rivals);
  if (!threats.length) return null;
  const shown = threats.slice(0, 5);

  return (
    <Disclosure title="A quién te pueden quitar" meta={`${threats.length}`} defaultOpen>
      <p className="text-[12.5px] text-white/45">Tienen la cláusula abierta y algún rival con caja para pagarla. Blíndalos o ponles candado si no quieres perderlos.</p>
      <ul className="mt-2 divide-y divide-white/[0.05]">
        {shown.map(({ player, clause, buyers, loss }) => {
          const name = player.nickname || player.name || "Jugador";
          const who = buyers.slice(0, 2).map((row) => row.name).join(", ");
          const extra = buyers.length > 2 ? ` y ${buyers.length - 2} más` : "";
          return (
            <li key={String(player.player_id ?? name)} className="flex items-center gap-2.5 py-2.5">
              <Face name={name} src={photoFor(photos, player.player_id, name)} size={32} />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[14px] text-white">
                  {name}
                  {loss !== null ? <span style={{ color: TONE.amber }}> · −{points(loss)} pts a tu once</span> : null}
                </span>
                <span className="block truncate text-[12px] text-white/45">
                  Puede pagarlo {who}
                  {extra}
                </span>
              </span>
              <span className="shrink-0 text-[14px] font-medium tabular-nums text-white">{money(clause)}</span>
            </li>
          );
        })}
      </ul>
      {threats.length > shown.length ? <p className="mt-2 text-[12px] text-white/35">Y {threats.length - shown.length} más con menos peso en tu once.</p> : null}
      <p className="mt-2 text-[12px] leading-relaxed text-white/35">La caja de un rival es una estimación: es un aviso de lo que podría pasar, no una certeza.</p>
    </Disclosure>
  );
}
