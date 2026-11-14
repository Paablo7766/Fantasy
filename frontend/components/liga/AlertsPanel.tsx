"use client";

import Link from "next/link";
import { points } from "@/lib/core/format";
import { photoFor, type PhotoIndex } from "@/lib/core/photoIndex";
import type { Threat } from "@/lib/liga/threats";
import type { LeagueDenialRow, LeagueRaceRow } from "@/lib/types";
import { Crest } from "@/components/ui/Crest";
import { Empty, Face, TONE, money } from "@/components/ui/kit";
import { CardHead, Cell, ColumnHead, Tile } from "./parts";

const SLIM = "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3";
const THREAT_GRID = `${SLIM} min-[900px]:grid-cols-[minmax(0,1.6fr)_minmax(0,1.5fr)_minmax(0,0.9fr)_minmax(0,0.9fr)] min-[900px]:gap-x-5`;

/** Las cuatro líneas del once, siempre en el mismo orden. */
const LINES: { id: string; label: string; plural: string }[] = [
  { id: "POR", label: "Portería", plural: "Porteros" },
  { id: "DEF", label: "Defensa", plural: "Defensas" },
  { id: "MC", label: "Medio", plural: "Centrocampistas" },
  { id: "DEL", label: "Ataque", plural: "Delanteros" },
];
const THIN_GRID = "grid grid-cols-[minmax(0,1fr)_repeat(4,2.75rem)] items-center gap-x-2";

/** Cuántos jugadores en venta se enseñan por línea. */
const PER_LINE = 3;

const lineOf = (pos: string | null | undefined) => (String(pos || "").toUpperCase() === "MED" ? "MC" : String(pos || "").toUpperCase());

/** Un punto por rival: los que pueden pagar la cláusula, encendidos. */
function Payers({ can, total }: { can: number; total: number }) {
  return (
    <span className="flex gap-[3px]" aria-hidden="true">
      {Array.from({ length: Math.min(total, 12) }, (_, index) => (
        <span key={index} className="h-1.5 w-1.5 rounded-full" style={{ background: index < can ? TONE.red : "rgba(255,255,255,0.14)" }} />
      ))}
    </span>
  );
}

/**
 * Lo que puede cambiar tu liga sin que hagas nada: a quién te pueden quitar,
 * en qué línea flojea cada rival y qué hay en venta que les vendría bien.
 */
export function AlertsPanel({
  threats,
  thin,
  denial,
  rivalCount,
  photos,
}: {
  threats: Threat[];
  thin: LeagueRaceRow[];
  denial: LeagueDenialRow[];
  rivalCount: number;
  photos: PhotoIndex;
}) {
  if (!threats.length && !thin.length && !denial.length) {
    return <Empty title="Todo tranquilo" detail="Ningún jugador tuyo está al alcance de un clausulazo y no hay rivales con líneas flojas que aprovechar." />;
  }
  const shown = threats.slice(0, 6);
  const weakOf = (row: LeagueRaceRow) => (row.thin_positions || []).map(lineOf);
  const lineCounts = LINES.map((line) => ({ ...line, count: thin.filter((row) => weakOf(row).includes(line.id)).length }));
  const weakest = lineCounts.slice().sort((a, b) => b.count - a.count)[0];
  const groups = LINES.map((line) => {
    const rows = denial.filter((row) => lineOf(row.position) === line.id);
    const first = rows[0];
    const managers = first?.managers || [];
    const total = first?.count ?? managers.length;
    return { ...line, rows, total, who: `${managers.join(", ")}${total > managers.length ? ` y ${total - managers.length} más` : ""}` };
  })
    .filter((group) => group.rows.length)
    .sort((a, b) => b.total - a.total);
  const exposed = threats.reduce((sum, threat) => sum + (threat.loss ?? 0), 0);

  return (
    <>
      <div className="grid grid-cols-1 gap-2 min-[560px]:grid-cols-3 [&>div]:bg-white/[0.05]">
        <Tile
          label="Te pueden quitar"
          value={threats.length ? `${threats.length} ${threats.length === 1 ? "jugador" : "jugadores"}` : "Nadie"}
          tone={threats.length ? TONE.red : undefined}
          hint={threats.length ? (exposed > 0 ? `hasta −${points(exposed)} pts en tu once` : "con la cláusula abierta") : "Tus cláusulas aguantan"}
        />
        <Tile
          label="La línea más floja de la liga"
          value={weakest && weakest.count ? weakest.label : "Ninguna"}
          hint={weakest && weakest.count ? `${weakest.count} de ${rivalCount} rivales van cortos` : "Todos tienen recambio"}
        />
        <Tile label="En venta que les hace falta" value={`${denial.length} ${denial.length === 1 ? "jugador" : "jugadores"}`} hint={groups[0] ? `sobre todo ${groups[0].plural.toLowerCase()}` : "Nada que les sirva"} />
      </div>

      {threats.length ? (
        <section className="home-glass overflow-hidden" aria-label="Jugadores que te pueden quitar">
          <CardHead title="Te los pueden quitar" count={threats.length} caption="Tienen la cláusula abierta y hay rivales con caja para pagarla. Cada punto es un rival; los rojos pueden pagarla hoy.">
            <Link href="/clausulas" className="shrink-0 text-[13px] font-medium text-peach transition-colors hover:text-white">
              Protegerlos en Cláusulas →
            </Link>
          </CardHead>
          <ColumnHead grid={THREAT_GRID} labels={[{ label: "Jugador", left: true }, { label: "Quién puede pagarla", left: true }, { label: "Cláusula" }, { label: "Tu once pierde" }]} />
          <ul className="divide-y divide-white/[0.05] border-t border-white/[0.06] min-[900px]:border-t-0">
            {shown.map(({ player, clause, buyers, loss }) => {
              const name = player.nickname || player.name || "Jugador";
              const who = `${buyers.slice(0, 2).map((row) => row.name).join(", ")}${buyers.length > 2 ? ` y ${buyers.length - 2} más` : ""}`;
              return (
                <li key={String(player.player_id ?? name)} className={`${THREAT_GRID} px-4 py-3 min-[900px]:px-5`}>
                  <span className="flex min-w-0 items-center gap-3">
                    <Face name={name} src={player.image_url || photoFor(photos, player.player_id, name)} size={34} />
                    <span className="min-w-0">
                      <span className="block truncate text-[14px] font-medium text-white">{name}</span>
                      <span className="mt-0.5 flex items-center gap-1.5 text-[11.5px] text-white/40">
                        <Crest club={player.club} size={13} />
                        <span className="truncate">{[player.position, player.club].filter(Boolean).join(" · ")}</span>
                      </span>
                      <span className="mt-1.5 flex items-center gap-2 min-[900px]:hidden">
                        <Payers can={buyers.length} total={rivalCount} />
                        <span className="truncate text-[11.5px] tabular-nums text-white/40">
                          {buyers.length} de {rivalCount} pueden
                        </span>
                      </span>
                    </span>
                  </span>
                  <span className="hidden min-w-0 min-[900px]:block">
                    <span className="flex items-center gap-2.5">
                      <Payers can={buyers.length} total={rivalCount} />
                      <span className="text-[13px] tabular-nums text-white/75">
                        {buyers.length} de {rivalCount}
                      </span>
                    </span>
                    <span className="mt-1 block truncate text-[11.5px] text-white/40">{who}</span>
                  </span>
                  <Cell value={money(clause)} sub={loss !== null ? `−${points(loss)} pts` : null} subTone={TONE.red} className="min-[900px]:hidden" />
                  <Cell className="hidden min-[900px]:block" value={money(clause)} />
                  <Cell className="hidden min-[900px]:block" value={loss !== null ? `−${points(loss)} pts` : "—"} tone={loss !== null ? TONE.red : "rgba(255,255,255,0.4)"} />
                </li>
              );
            })}
          </ul>
          <p className="border-t border-white/[0.06] px-4 py-3 text-[12px] leading-relaxed text-white/35 min-[900px]:px-5">
            {threats.length > shown.length ? `Y ${threats.length - shown.length} más con menos peso en tu once. ` : ""}
            La caja de un rival es una estimación: es un aviso de lo que podría pasar, no una certeza.
          </p>
        </section>
      ) : null}

      <div className={thin.length && groups.length ? "grid min-w-0 gap-4 min-[1100px]:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] min-[1100px]:items-start" : "contents"}>
        {thin.length ? (
          <section className="home-glass min-w-0 overflow-hidden" aria-label="Líneas flojas de tus rivales">
            <CardHead title="Dónde flojean tus rivales" caption="Un punto marca la línea en la que no tienen recambio: una baja ahí les deja un hueco." />
            <div className={`${THIN_GRID} border-y border-white/[0.06] px-4 py-2 min-[900px]:px-5`}>
              <span className="text-[11.5px] text-white/40">Mánager</span>
              {lineCounts.map((line) => (
                <span key={line.id} className="text-center">
                  <span className="block text-[11.5px] text-white/60">{line.id}</span>
                  <span className="block text-[11px] tabular-nums text-white/35">{line.count}</span>
                </span>
              ))}
            </div>
            <ul className="divide-y divide-white/[0.05]">
              {thin.map((row) => {
                const weak = weakOf(row);
                return (
                  <li key={String(row.team_id)} className={`${THIN_GRID} px-4 py-2.5 min-[900px]:px-5`}>
                    <span className="min-w-0 truncate text-[14px] text-white">
                      {row.manager_name || row.fantasy_team_name || "Rival"}
                      {row.rank ? <span className="ml-1.5 text-[12px] tabular-nums text-white/35">{row.rank}º</span> : null}
                    </span>
                    {LINES.map((line) => (
                      <span key={line.id} className="grid place-items-center" title={weak.includes(line.id) ? `${line.label} sin recambio` : undefined}>
                        {weak.includes(line.id) ? (
                          <span className="h-2 w-2 rounded-full" style={{ background: TONE.amber }}>
                            <span className="sr-only">{line.label} sin recambio</span>
                          </span>
                        ) : (
                          <span className="h-px w-2.5 bg-white/15" aria-hidden="true" />
                        )}
                      </span>
                    ))}
                  </li>
                );
              })}
            </ul>
          </section>
        ) : null}

        {groups.length ? (
          <section className="home-glass min-w-0 overflow-hidden" aria-label="Jugadores en venta que necesita un rival">
            <CardHead title="En venta y les hace falta" count={denial.length} caption="Están en el mercado y cubren la línea floja de rivales con caja para pagarlos. Si te sirven, ficharlos también les cierra la puerta." />
            {groups.map((group) => (
              <div key={group.id} className="border-t border-white/[0.06]">
                <p className="flex flex-wrap items-baseline gap-x-2 px-4 pb-1 pt-3.5 text-[11.5px] min-[900px]:px-5">
                  <span className="font-semibold text-white/70">{group.plural}</span>
                  <span className="min-w-0 truncate text-white/40">
                    los necesitan {group.total} {group.total === 1 ? "rival" : "rivales"}: {group.who}
                  </span>
                </p>
                <ul className="divide-y divide-white/[0.05]">
                  {group.rows.slice(0, PER_LINE).map((row) => {
                    const name = row.nickname || row.name || "Jugador";
                    return (
                      <li key={String(row.player_id)} className="flex items-center gap-3 px-4 py-2.5 min-[900px]:px-5">
                        <Face name={name} src={photoFor(photos, row.player_id, name)} size={32} />
                        <span className="min-w-0 flex-1 truncate text-[14px] font-medium text-white">{name}</span>
                        <span className="shrink-0 text-[14px] font-medium tabular-nums text-white">{money(row.sale_price)}</span>
                      </li>
                    );
                  })}
                </ul>
                {group.rows.length > PER_LINE ? <p className="px-4 pb-3 pt-1 text-[11.5px] text-white/35 min-[900px]:px-5">Y {group.rows.length - PER_LINE} más en el mercado.</p> : null}
              </div>
            ))}
          </section>
        ) : null}
      </div>
    </>
  );
}
