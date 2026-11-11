"use client";

import { points } from "@/lib/core/format";
import { photoFor, type PhotoIndex } from "@/lib/core/photoIndex";
import type { Threat } from "@/lib/liga/threats";
import type { LeagueDenialRow, LeagueRaceRow } from "@/lib/types";
import { Crest } from "@/components/ui/Crest";
import { Empty, Face, TONE, money } from "@/components/ui/kit";
import { CardHead, Cell, ColumnHead } from "./parts";

const SLIM = "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3";
const THREAT_GRID = `${SLIM} min-[900px]:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,2fr)] min-[900px]:gap-x-5`;
const DENIAL_GRID = `${SLIM} min-[900px]:grid-cols-[minmax(0,1.6fr)_minmax(0,1.5fr)_minmax(0,1fr)] min-[900px]:gap-x-5`;
/** Las cuatro líneas del once, siempre en el mismo orden. */
const LINES = ["POR", "DEF", "MC", "DEL"];
const THIN_GRID = "grid grid-cols-[minmax(0,1fr)_repeat(4,2.75rem)] items-center gap-x-2";

function buyersText(buyers: { name: string }[]): string {
  const who = buyers.slice(0, 2).map((row) => row.name).join(", ");
  return buyers.length > 2 ? `${who} y ${buyers.length - 2} más` : who;
}

/**
 * Lo que puede cambiar tu liga sin que hagas nada: a quién te pueden quitar,
 * qué líneas tienen flojas tus rivales y qué jugadores en venta les vendrían bien.
 */
export function AlertsPanel({
  threats,
  thin,
  denial,
  photos,
}: {
  threats: Threat[];
  thin: LeagueRaceRow[];
  denial: LeagueDenialRow[];
  photos: PhotoIndex;
}) {
  if (!threats.length && !thin.length && !denial.length) {
    return <Empty title="Todo tranquilo" detail="Ningún jugador tuyo está al alcance de un clausulazo y no hay rivales con líneas flojas que aprovechar." />;
  }
  const shown = threats.slice(0, 6);

  return (
    <>
      {threats.length ? (
        <section className="home-glass overflow-hidden" aria-label="Jugadores que te pueden quitar">
          <CardHead title="Te los pueden quitar" count={threats.length} caption="Tienen la cláusula abierta y algún rival con caja para pagarla. Blíndalos o súbeles la cláusula en Cláusulas." />
          <ColumnHead grid={THREAT_GRID} labels={[{ label: "Jugador", left: true }, { label: "Tu once pierde" }, { label: "Cláusula" }, { label: "Quién puede pagarla" }]} />
          <ul className="divide-y divide-white/[0.05] border-t border-white/[0.06] min-[900px]:border-t-0">
            {shown.map(({ player, clause, buyers, loss }) => {
              const name = player.nickname || player.name || "Jugador";
              return (
                <li key={String(player.player_id ?? name)} className={`${THREAT_GRID} px-4 py-3 min-[900px]:px-5`}>
                  <span className="flex min-w-0 items-center gap-3">
                    <Face name={name} src={player.image_url || photoFor(photos, player.player_id, name)} size={34} />
                    <span className="min-w-0">
                      <span className="block truncate text-[14px] font-medium text-white">{name}</span>
                      <span className="mt-0.5 flex items-center gap-1.5 text-[11.5px] text-white/40">
                        <Crest club={player.club} size={13} />
                        <span className="truncate min-[900px]:hidden">Puede pagarlo {buyersText(buyers)}</span>
                        <span className="hidden truncate min-[900px]:inline">{[player.position, player.club].filter(Boolean).join(" · ")}</span>
                      </span>
                    </span>
                  </span>
                  <Cell className="hidden min-[900px]:block" value={loss !== null ? `−${points(loss)} pts` : "—"} tone={loss !== null ? TONE.red : "rgba(255,255,255,0.4)"} />
                  <Cell className="min-[900px]:hidden" value={money(clause)} sub={loss !== null ? `−${points(loss)} pts a tu once` : null} />
                  <Cell className="hidden min-[900px]:block" value={money(clause)} />
                  <span className="hidden min-w-0 truncate text-right text-[13px] text-white/60 min-[900px]:block">{buyersText(buyers)}</span>
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

      <div className={thin.length && denial.length ? "grid min-w-0 gap-4 min-[1100px]:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] min-[1100px]:items-start" : "contents"}>
      {thin.length ? (
        <section className="home-glass min-w-0 overflow-hidden" aria-label="Líneas flojas de tus rivales">
          <CardHead title="Dónde flojean tus rivales" count={thin.length} caption="Un punto marca la línea en la que van cortos. Si fichas lo que necesitan, les cuesta más reforzarse." />
          <div className={`${THIN_GRID} border-y border-white/[0.06] px-4 py-2 min-[900px]:px-5`} aria-hidden="true">
            <span className="text-[11.5px] text-white/40">Mánager</span>
            {LINES.map((pos) => (
              <span key={pos} className="text-center text-[11.5px] text-white/40">
                {pos}
              </span>
            ))}
          </div>
          <ul className="divide-y divide-white/[0.05]">
            {thin.map((row) => {
              const weak = (row.thin_positions || []).map((pos) => (pos === "MED" ? "MC" : pos));
              return (
                <li key={String(row.team_id)} className={`${THIN_GRID} px-4 py-2.5 min-[900px]:px-5`}>
                  <span className="min-w-0 truncate text-[14px] text-white">
                    {row.manager_name || row.fantasy_team_name || "Rival"}
                    {row.rank ? <span className="ml-1.5 text-[12px] tabular-nums text-white/35">{row.rank}º</span> : null}
                  </span>
                  {LINES.map((pos) => (
                    <span key={pos} className="grid place-items-center" title={weak.includes(pos) ? `${pos} flojo` : undefined}>
                      {weak.includes(pos) ? (
                        <span className="h-2 w-2 rounded-full" style={{ background: TONE.amber }}>
                          <span className="sr-only">{pos} flojo</span>
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

      {denial.length ? (
        <section className="home-glass min-w-0 overflow-hidden" aria-label="Jugadores en venta que necesita un rival">
          <CardHead title="En venta y les hace falta" count={denial.length} caption="Están en el mercado y cubren justo la línea floja de un rival con caja para pagarlos." />
          <ColumnHead grid={DENIAL_GRID} labels={[{ label: "Jugador", left: true }, { label: "Lo necesitan" }, { label: "Precio" }]} />
          <ul className="divide-y divide-white/[0.05] border-t border-white/[0.06] min-[900px]:border-t-0">
            {denial.map((row) => {
              const name = row.nickname || row.name || "Jugador";
              const managers = row.managers || [];
              const extra = (row.count ?? managers.length) - managers.length;
              const names = `${managers.join(", ")}${extra > 0 ? ` y ${extra} más` : ""}`;
              const total = row.count ?? managers.length;
              const who = total > 1 ? `${total} rivales` : managers[0] || "1 rival";
              return (
                <li key={String(row.player_id)} className={`${DENIAL_GRID} px-4 py-3 min-[900px]:px-5`}>
                  <span className="flex min-w-0 items-center gap-3">
                    <Face name={name} src={photoFor(photos, row.player_id, name)} size={34} />
                    <span className="min-w-0">
                      <span className="block truncate text-[14px] font-medium text-white">{name}</span>
                      <span className="mt-0.5 block truncate text-[11.5px] text-white/40">
                        {row.position}
                        <span className="min-[900px]:hidden"> · {who}</span>
                      </span>
                    </span>
                  </span>
                  <span className="hidden min-w-0 text-right min-[900px]:block" title={names}>
                    <span className="block truncate text-[13px] tabular-nums text-white/75">{who}</span>
                    <span className="mt-0.5 block truncate text-[11.5px] text-white/40">{names}</span>
                  </span>
                  <Cell value={money(row.sale_price)} />
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}
      </div>
    </>
  );
}
