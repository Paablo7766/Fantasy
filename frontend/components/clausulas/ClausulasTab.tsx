"use client";

import { useSearchParams } from "next/navigation";
import { Fragment, useEffect, useMemo, useState } from "react";
import { CompararButton } from "@/components/comparador/ComparadorReal";
import { endpoint, getJson } from "@/lib/core/api";
import { buildClausulazosGuide, type DateBucket } from "@/lib/clausulas/clausulazosGuide";
import { UnlockWindow } from "@/components/clausulas/UnlockWindow";
import { playerName, points } from "@/lib/core/format";
import { countdownClock, countdownParts } from "@/lib/inicio/hoy";
import { photoFor, type PhotoIndex } from "@/lib/core/photoIndex";
import { useNow } from "@/lib/core/useClock";
import type {
  ClauseBoardPayload,
  ClauseBoardRow,
  ClausulaEnPeligro,
  ClausulazoSugerido,
  NeedsPayload,
  PlanPayload,
  RadarAntiRobo,
  RivalPlayer,
  SquadsPayload,
  VeredictoClausulazo,
  VeredictoProteger,
} from "@/lib/types";
import { Chevron, Disclosure, Empty, Face, Fact, HeroStat, SectionHead, Skeleton, TONE, cleanText, compact, forecastHint, money } from "@/components/ui/kit";

/** «Mías» defiende tu plantilla; «Clausulazos» ataca la de los rivales. */
export type ClausulasView = "mias" | "clausulazos";

const RIESGO = {
  ALTO: { label: "Riesgo alto", color: TONE.red },
  MEDIO: { label: "Riesgo medio", color: TONE.amber },
  BAJO: { label: "Vigilar", color: TONE.gray },
} as const;

const PROTEGER: Record<VeredictoProteger, { label: string; color: string }> = {
  PROTEGER_YA: { label: "Sube la cláusula", color: TONE.green },
  PROTEGER_PARCIAL: { label: "Súbela un poco", color: TONE.amber },
  SIN_CAJA: { label: "No te llega la caja", color: TONE.red },
  VENDER_ANTES: { label: "Mejor venderlo", color: TONE.blue },
  ASUMIR: { label: "Asume el riesgo", color: TONE.gray },
  SOBREPROTEGIDO: { label: "Ya blindada", color: TONE.green },
  SIN_RECAMBIO: { label: "Sin recambio", color: TONE.red },
};

const RADAR = {
  rojo: { label: "En riesgo", color: TONE.red },
  verde: { label: "Bien protegido", color: TONE.green },
  gris: { label: "Sin riesgo hoy", color: TONE.gray },
} as const;

const CLAUSULAZO: Record<VeredictoClausulazo, { label: string; color: string }> = {
  CLAUSULAR_YA: { label: "Clausula ya", color: TONE.green },
  PROGRAMAR: { label: "Prográmalo", color: TONE.blue },
  SIN_CAJA: { label: "Te falta caja", color: TONE.red },
  OPORTUNIDAD: { label: "Oportunidad", color: TONE.amber },
  GOLPE_RIVAL: { label: "Golpe al rival", color: TONE.copper },
  REVENDER: { label: "Para revender", color: TONE.green },
};

const RULES = [
  "Las cláusulas se pagan hasta 24 h antes del primer partido.",
  "Subir la cláusula cuesta la mitad de lo que subes.",
  "Con candado no se puede pagar hasta la hora exacta.",
  "Los blindados no se pueden clausular.",
  "Caja negativa o menos de 11 al empezar: la jornada vale 0.",
  "Desde aquí no se envía nada: confirma en la app oficial.",
];

/** Cuántas cláusulas se enseñan como mínimo en cada pestaña: las recomendadas y, si faltan, las siguientes mejores. */
const MIN_SHOWN = 6;

const OPEN_MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

/** Cuándo se puede pagar: «Abierta ahora» o «Abre 4 nov · 14:08». */
function opensLabel(row: ClauseBoardRow): string {
  if (row.on_market) return `En el mercado${row.market_listing_expires_local_time ? ` · hasta ${row.market_listing_expires_local_time}` : ""}`;
  if (!row.is_locked) return "Abierta ahora";
  const lock = row.clause_lock;
  if (!lock?.local_date) return "Con candado";
  const [, month, day] = lock.local_date.split("-");
  const when = `${Number(day)} ${OPEN_MONTHS[Number(month) - 1] || month}${lock.local_time ? ` · ${lock.local_time}` : ""}`;
  return `Abre ${when}`;
}

type ClauseBrowseItem = {
  key: string;
  suggestion?: ClausulazoSugerido;
  board?: ClauseBoardRow;
};

/** La foto de la liga ya trae a cada rival. No hace falta esperar a `/api/clause-board`. */
function rowsFromSquads(squads: SquadsPayload | null): ClauseBoardRow[] {
  const rows: ClauseBoardRow[] = [];
  for (const squad of squads?.rivals || []) {
    for (const player of squad.players || []) {
      const clause = player.buyout_clause;
      if (!player.player_id || player.is_shielded || !(typeof clause === "number" && clause > 0)) continue;
      rows.push({
        team_id: squad.team_id,
        manager_name: squad.manager_name,
        fantasy_team_name: squad.fantasy_team_name,
        player_id: String(player.player_id),
        name: player.name,
        nickname: player.nickname,
        position: player.position,
        club: player.club,
        image_url: player.image_url,
        buyout_clause_eur: clause,
        market_value: player.market_value,
        average_points: player.average_points,
        clause_multiple: player.clause_multiple,
        is_shielded: false,
        is_locked: player.clause_lock?.is_locked === true,
        clause_lock: player.clause_lock,
      });
    }
  }
  return rows;
}

/**
 * Todas las cláusulas rivales que se pueden mirar, partidas en abiertas y candado.
 * Las recomendadas se quedan delante; el resto se ve igual aunque no mejore el once.
 */
function browseClauses(
  board: ClauseBoardPayload | null,
  suggested: ClausulazoSugerido[],
  squads: SquadsPayload | null,
): {
  abiertas: ClauseBrowseItem[];
  candado: ClauseBrowseItem[];
} {
  const byId = new Map(suggested.map((row) => [String(row.player_id), row]));
  const order = new Map(suggested.map((row, index) => [String(row.player_id), index]));
  const taken = new Set((board?.taken || []).map((row) => String(row.player_id)));
  const seen = new Set<string>(taken);
  const items: ClauseBrowseItem[] = [];
  const source = board?.ok !== false && board?.rows?.length ? board.rows : rowsFromSquads(squads);
  for (const row of source) {
    const id = row.player_id ? String(row.player_id) : "";
    if (!id || row.is_shielded || !(typeof row.buyout_clause_eur === "number" && row.buyout_clause_eur > 0)) continue;
    seen.add(id);
    items.push({ key: id, board: row, suggestion: byId.get(id) });
  }
  for (const row of suggested) {
    const id = String(row.player_id);
    if (seen.has(id)) continue;
    items.push({ key: id, suggestion: row });
  }
  const rank = (item: ClauseBrowseItem) => order.get(item.key) ?? 1000;
  const pointsOf = (item: ClauseBrowseItem) => item.board?.average_points ?? item.suggestion?.xp_jornada ?? 0;
  const priceOf = (item: ClauseBrowseItem) => item.board?.buyout_clause_eur ?? item.suggestion?.clausula_eur ?? 0;
  items.sort((a, b) => rank(a) - rank(b) || pointsOf(b) - pointsOf(a) || priceOf(a) - priceOf(b));
  return {
    abiertas: items.filter((item) => (item.board ? !item.board.is_locked : item.suggestion?.abierta_ahora)),
    candado: items.filter((item) => (item.board ? item.board.is_locked : item.suggestion ? !item.suggestion.abierta_ahora : false)),
  };
}

/**
 * Las recomendadas siempre; si son menos de MIN_SHOWN, se completa con las mejores por puntos,
 * primero las que se pueden pagar con la caja. Nunca la lista entera de la liga.
 */
function topPicks(items: ClauseBrowseItem[], cash: number | null | undefined): ClauseBrowseItem[] {
  const recommended = items.filter((item) => item.suggestion);
  if (recommended.length >= MIN_SHOWN) return recommended;
  const payable = (item: ClauseBrowseItem) =>
    typeof cash !== "number" || (item.board?.buyout_clause_eur ?? Infinity) <= cash ? 0 : 1;
  const extra = items
    .filter((item) => !item.suggestion && item.board)
    .sort((a, b) => payable(a) - payable(b) || (b.board?.average_points ?? 0) - (a.board?.average_points ?? 0))
    .slice(0, MIN_SHOWN - recommended.length);
  return [...recommended, ...extra];
}

function dayChip(localDate: string): { week: string; day: string } {
  const date = new Date(`${localDate}T12:00:00`);
  if (Number.isNaN(date.getTime())) return { week: "", day: localDate };
  return {
    week: date.toLocaleDateString("es-ES", { weekday: "short" }).replace(".", ""),
    day: String(date.getDate()),
  };
}

function Pill({ label, color }: { label: string; color: string }) {
  return (
    <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[11.5px] font-semibold" style={{ color, background: `${color}1c` }}>
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} aria-hidden="true" />
      {label}
    </span>
  );
}

/** La subida que de verdad recomienda el asesor; null si lo sensato es no tocarla. */
function recommendedLevel(row: ClausulaEnPeligro) {
  const best = row.subida_recomendada ?? (row.veredicto_codigo === "SIN_CAJA" ? row.clausula_perfecta : null);
  return best && best.clausula_objetivo > row.clausula_actual ? best : null;
}

/** Por qué no se recomienda subirla, en pocas palabras. */
function keepReason(row: ClausulaEnPeligro): string {
  if (row.veredicto_codigo === "SOBREPROTEGIDO") return "ya cubre el sustituto";
  if (row.veredicto_codigo === "VENDER_ANTES") return "mejor venderlo";
  if (!row.rivales_que_pueden_pagar) return "hoy nadie la paga";
  if (!row.niveles.length) return "ya está en el tope";
  return "subirla no compensa";
}

/**
 * La cláusula frente a lo que pueden pagar: la barra es tu cláusula, el tramo
 * claro llega a la recomendada y la marca blanca es la caja del rival más rico.
 */
function Shield({ row }: { row: ClausulaEnPeligro }) {
  const perfect = recommendedLevel(row)?.clausula_objetivo ?? row.clausula_actual;
  const rich = row.rival_mas_rico?.caja ?? null;
  const top = Math.max(perfect, row.clausula_actual, rich ?? 0, 1) * 1.04;
  const now = (row.clausula_actual / top) * 100;
  const goal = (perfect / top) * 100;
  const safe = row.clausula_actual >= perfect;
  return (
    <div>
      <div className="relative h-2.5 rounded-full bg-white/[0.07]" aria-hidden="true">
        {!safe ? <span className="absolute inset-y-0 left-0 rounded-full bg-white/[0.12]" style={{ width: `${goal}%` }} /> : null}
        <span
          className="absolute inset-y-0 left-0 rounded-full transition-[width] duration-700 ease-out"
          style={{ width: `${now}%`, background: safe ? TONE.green : "linear-gradient(90deg, #FC734D, #FF9A5A)" }}
        />
        {rich !== null ? (
          <span className="absolute -top-1 h-[18px] w-[3px] rounded-full bg-white shadow-[0_0_8px_rgba(255,255,255,0.6)]" style={{ left: `calc(${(rich / top) * 100}% - 1.5px)` }} />
        ) : null}
      </div>
      <div className="mt-2 flex items-center justify-between gap-3 text-[11.5px] tabular-nums">
        <span className="text-white/55">
          Cláusula <span className="font-semibold text-white">{money(row.clausula_actual)}</span>
        </span>
        {rich !== null ? (
          <span className="flex items-center gap-1.5 text-white/45">
            <span className="h-2.5 w-[3px] rounded-full bg-white" aria-hidden="true" />
            {row.rival_mas_rico?.manager || "Rival"} tiene {money(rich)}
          </span>
        ) : null}
      </div>
    </div>
  );
}

function DefendCard({
  row,
  radar,
  photos,
  index,
}: {
  row: ClausulaEnPeligro;
  radar: RadarAntiRobo | undefined;
  photos: PhotoIndex;
  index: number;
}) {
  const [open, setOpen] = useState(false);
  const verdict = PROTEGER[row.veredicto_codigo] ?? PROTEGER.ASUMIR;
  const risk = RIESGO[row.riesgo] ?? RIESGO.BAJO;
  const raise = recommendedLevel(row);
  return (
    <li className="row-in" style={{ animationDelay: `${index * 35}ms` }}>
      <button type="button" aria-expanded={open} onClick={() => setOpen((value) => !value)} className="block w-full px-3.5 py-3.5 text-left">
        <span className="flex items-center gap-3">
          <Face name={row.nombre} src={photoFor(photos, row.player_id, row.nombre)} size={44} ring={risk.color} />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[15px] font-medium leading-tight text-white">{row.nombre}</span>
            <span className="mt-0.5 block truncate text-[12.5px] text-white/45">
              {row.en_candado ? (
                <>
                  <span className="text-white/70">Candado hasta {row.expuesta_cuando || "—"}</span> · hoy la pagarían {row.rivales_que_pueden_pagar} de {row.rivales_total}
                </>
              ) : (
                <>
                  <span style={{ color: risk.color }}>{risk.label}</span> · la pueden pagar {row.rivales_que_pueden_pagar} de {row.rivales_total}
                </>
              )}
            </span>
          </span>
          <Chevron open={open} />
        </span>
        <span className="mt-3.5 block">
          <Shield row={row} />
        </span>
        <span className="mt-3 flex items-center justify-between gap-3 rounded-2xl bg-black/25 px-3 py-2.5">
          <Pill {...(row.en_candado && !raise ? { label: "De momento, bien", color: TONE.green } : row.en_candado ? { label: "Súbela antes de que abra", color: TONE.amber } : verdict)} />
          {raise ? (
            <span className="min-w-0 truncate text-right text-[12.5px] tabular-nums text-white/55">
              <span className="font-semibold text-[#FFC08A]">+{money(raise.subida_eur, 1)}</span> por {money(raise.coste_eur, 1)}
            </span>
          ) : null}
        </span>
      </button>
      {open ? (
        <div className="row-in border-t border-white/[0.05] px-3.5 pb-4 pt-3">
          <div className="grid grid-cols-3 gap-3">
            {raise ? (
              <Fact label="Recomendada" value={money(raise.clausula_objetivo)} hint={`ahora ${money(row.clausula_actual)}`} tone="#FFC08A" />
            ) : (
              <Fact label="Recomendada" value="Mantener" hint={keepReason(row)} />
            )}
            <Fact label="Valor" value={money(row.valor_mercado)} hint={forecastHint(row.valor_mercado, row.prevision_7d_pct)} />
            <Fact
              label="Tu once sin él"
              value={row.tu_once_pierde_sin_el < 0.05 ? "Igual" : `−${points(row.tu_once_pierde_sin_el)} pts`}
              tone={row.tu_once_pierde_sin_el < 0.05 ? undefined : TONE.red}
            />
          </div>
          <p className="mt-3 text-[13px] leading-relaxed text-white/60">{cleanText(row.motivo_detallado)}</p>
          {radar?.consejo ? <p className="mt-2 text-[13px] leading-relaxed text-white/50">{cleanText(radar.consejo)}</p> : null}
          {row.niveles.length > 1 ? (
            <div className="mt-3">
              <p className="mb-1.5 text-[11.5px] text-white/40">Cuánto subirla</p>
              <ul className="divide-y divide-white/[0.05] rounded-2xl bg-black/25 px-3">
                {row.niveles.map((level) => {
                  const total = level.rivales_cubiertos + level.rivales_sin_cubrir;
                  return (
                    <li key={level.clausula_objetivo} className="flex items-center gap-3 py-2.5 text-[12.5px] tabular-nums">
                      <span className="w-[4.5rem] shrink-0 font-semibold text-white">{money(level.clausula_objetivo)}</span>
                      <span className="flex min-w-0 flex-1 items-center gap-2">
                        <span className="h-1 flex-1 overflow-hidden rounded-full bg-white/[0.07]">
                          <span className="block h-full rounded-full" style={{ width: `${total ? (level.rivales_cubiertos / total) * 100 : 0}%`, background: TONE.green }} />
                        </span>
                        <span className="shrink-0 text-white/45">
                          {level.rivales_cubiertos}/{total}
                        </span>
                      </span>
                      <span className="w-[4.5rem] shrink-0 text-right" style={{ color: level.viable ? "rgba(255,255,255,0.8)" : TONE.red }}>
                        {money(level.coste_eur)}
                      </span>
                    </li>
                  );
                })}
              </ul>
              <p className="mt-1.5 text-[11px] text-white/35">Cláusula · rivales que ya no pueden pagarla · lo que te cuesta</p>
            </div>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

function AttackCard({ row, photos, index }: { row: ClausulazoSugerido; photos: PhotoIndex; index: number }) {
  const [open, setOpen] = useState(false);
  const verdict = CLAUSULAZO[row.veredicto_codigo] ?? CLAUSULAZO.OPORTUNIDAD;
  // El margen que se enseña es contra el valor de mercado (dinero real), no contra el valor justo por puntos.
  const margin = row.margen_reventa_pct;
  return (
    <li className="row-in" style={{ animationDelay: `${index * 35}ms` }}>
      <button type="button" aria-expanded={open} onClick={() => setOpen((value) => !value)} className="block w-full px-3.5 py-3.5 text-left">
        <span className="flex items-center gap-3">
          <Face name={row.nombre} src={photoFor(photos, row.player_id, row.nombre)} size={44} ring={verdict.color} />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[15px] font-medium leading-tight text-white">{row.nombre}</span>
            <span className="mt-0.5 block truncate text-[12.5px] text-white/45">
              {[row.posicion, row.propietario ? `de ${row.propietario}` : ""].filter(Boolean).join(" · ")}
            </span>
          </span>
          <span className="shrink-0 text-right">
            <span className="block text-[15px] font-semibold tabular-nums text-white">{money(row.clausula_eur)}</span>
            {typeof margin === "number" ? (
              <span className="block text-[12px] font-medium tabular-nums" style={{ color: margin >= 0 ? TONE.green : TONE.red }}>
                {margin >= 0 ? `${Math.round(margin)}% bajo el mercado` : `${Math.abs(Math.round(margin))}% sobre el mercado`}
              </span>
            ) : null}
          </span>
          <Chevron open={open} />
        </span>
        <span className="mt-3 flex flex-wrap items-center gap-1.5 pl-[3.5rem]">
          <Pill {...verdict} />
          <span className="rounded-full bg-white/[0.06] px-2.5 py-1 text-[11.5px] font-medium" style={{ color: row.abierta_ahora ? TONE.green : "rgba(255,255,255,0.6)" }}>
            {row.abierta_ahora ? "Abierta ahora" : `Abre ${row.cuando}`}
          </span>
          {row.mejora_once > 0 ? (
            <span className="rounded-full bg-white/[0.06] px-2.5 py-1 text-[11.5px] font-medium tabular-nums text-[#7FE0A8]">+{points(row.mejora_once)} pts a tu once</span>
          ) : null}
        </span>
      </button>
      {open ? (
        <div className="row-in border-t border-white/[0.05] px-3.5 pb-4 pt-3">
          <div className="grid grid-cols-3 gap-3">
            <Fact label="Próxima jornada" value={`${points(row.xp_jornada)} pts`} tone="#FFC08A" />
            <Fact
              label={row.es_reventa ? "Ganas al revender" : "Valor de mercado"}
              value={row.es_reventa ? money(row.beneficio_reventa_eur) : money(row.valor_mercado)}
              tone={row.es_reventa ? TONE.green : undefined}
              hint={forecastHint(row.valor_mercado, row.prevision_7d_pct)}
            />
            <Fact
              label="Caja después"
              value={money(row.caja_tras)}
              tone={typeof row.caja_tras === "number" && row.caja_tras < 0 ? TONE.red : undefined}
            />
          </div>
          {!row.asequible && row.falta_caja_eur > 0 ? (
            <p className="mt-3 rounded-2xl px-3 py-2.5 text-[13px]" style={{ color: TONE.red, background: `${TONE.red}14` }}>
              Te faltan {money(row.falta_caja_eur)} para pagarla.
            </p>
          ) : null}
          <p className="mt-3 text-[13px] leading-relaxed text-white/60">{cleanText(row.motivo_detallado)}</p>
          <div className="mt-3 flex justify-end">
            <CompararButton objetivoId={row.player_id} posicion={row.posicion} className="!bg-[#1c1c1e] !px-4 !py-2 !text-white" />
          </div>
        </div>
      ) : null}
    </li>
  );
}

/** Cláusula de la liga que el asesor no recomienda, pero que se puede mirar igual. */
function PlainClauseRow({ row, photos, index }: { row: ClauseBoardRow; photos: PhotoIndex; index: number }) {
  const [open, setOpen] = useState(false);
  const name = row.nickname || row.name || "Jugador";
  const pts = typeof row.average_points === "number" ? row.average_points : null;
  const openNow = !row.is_locked;
  return (
    <li className="row-in" style={{ animationDelay: `${Math.min(index, 12) * 35}ms` }}>
      <button type="button" aria-expanded={open} onClick={() => setOpen((value) => !value)} className="block w-full px-3.5 py-3.5 text-left">
        <span className="flex items-center gap-3">
          <Face name={name} src={row.image_url || photoFor(photos, row.player_id, name)} size={44} />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[15px] font-medium leading-tight text-white">{name}</span>
            <span className="mt-0.5 block truncate text-[12.5px] text-white/45">
              {[row.position, row.manager_name ? `de ${row.manager_name}` : ""].filter(Boolean).join(" · ")}
            </span>
          </span>
          <span className="shrink-0 text-right">
            <span className="block text-[15px] font-semibold tabular-nums text-white">{money(row.buyout_clause_eur)}</span>
            {pts !== null ? <span className="block text-[12px] tabular-nums text-white/45">{points(pts)} pts</span> : null}
          </span>
          <Chevron open={open} />
        </span>
        <span className="mt-3 flex flex-wrap items-center gap-1.5 pl-[3.5rem]">
          <span className="rounded-full bg-white/[0.06] px-2.5 py-1 text-[11.5px] font-medium" style={{ color: openNow ? TONE.green : "rgba(255,255,255,0.6)" }}>
            {opensLabel(row)}
          </span>
        </span>
      </button>
      {open ? (
        <div className="row-in border-t border-white/[0.05] px-3.5 pb-4 pt-3">
          <div className="grid grid-cols-3 gap-3">
            <Fact label="Valor" value={money(row.market_value)} />
            <Fact label="Media" value={pts !== null ? `${points(pts)} pts` : "—"} tone="#FFC08A" />
            <Fact label="Múltiplo" value={typeof row.clause_multiple === "number" ? row.clause_multiple.toLocaleString("es-ES", { maximumFractionDigits: 2 }) : "—"} />
          </div>
          <div className="mt-3 flex justify-end">
            <CompararButton objetivoId={row.player_id || undefined} posicion={row.position} className="!bg-[#1c1c1e] !px-4 !py-2 !text-white" />
          </div>
        </div>
      ) : null}
    </li>
  );
}

/** Jugador propio sin peligro hoy: desplegable para prepararse antes de que se abra su cláusula. */
function RestRow({
  player,
  name,
  status,
  statusColor,
  radar,
  photos,
}: {
  player: RivalPlayer;
  name: string;
  status: string;
  statusColor: string;
  radar: RadarAntiRobo | undefined;
  photos: PhotoIndex;
}) {
  const [open, setOpen] = useState(false);
  const loses = player.tu_once_pierde_sin_el ?? null;
  const pct = radar?.prevision_7d_pct;
  const days = radar?.dias_para_abrir;
  return (
    <li>
      <button type="button" aria-expanded={open} onClick={() => setOpen((value) => !value)} className="flex w-full items-center gap-2.5 py-2.5 text-left">
        <Face name={name} src={player.image_url || photoFor(photos, player.player_id, name)} size={34} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[14px] text-white">{name}</span>
          <span className="block truncate text-[12px]" style={{ color: statusColor }}>
            {status}
          </span>
        </span>
        <span className="shrink-0 text-[14px] font-medium tabular-nums text-white">{money(player.buyout_clause)}</span>
        <Chevron open={open} />
      </button>
      {open ? (
        <div className="row-in pb-3">
          <div className="grid grid-cols-3 gap-3">
            <Fact label="Valor" value={money(player.market_value)} hint={forecastHint(player.market_value, pct) ?? (player.prevision_7d_pct || undefined)} />
            <Fact label="Próxima jornada" value={typeof player.own_expected_points === "number" ? `${points(player.own_expected_points)} pts` : "—"} tone="#FFC08A" />
            <Fact
              label="Tu once sin él"
              value={loses === null ? "—" : loses < 0.05 ? "Igual" : `−${points(loses)} pts`}
              tone={loses !== null && loses >= 0.05 ? TONE.red : undefined}
            />
          </div>
          <p className="mt-3 text-[12.5px] tabular-nums text-white/50">
            {[
              radar ? `${radar.rivales_con_caja} ${radar.rivales_con_caja === 1 ? "rival podría pagarla" : "rivales podrían pagarla"}` : null,
              typeof days === "number" && days > 0 ? `abre en ${days} ${days === 1 ? "día" : "días"}` : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
          {radar?.consejo ? <p className="mt-2 text-[13px] leading-relaxed text-white/60">{cleanText(radar.consejo)}</p> : null}
        </div>
      ) : null}
    </li>
  );
}

/** Cuándo se abren los candados de los rivales, día a día. */
function Openings({ timeline, photos }: { timeline: DateBucket[]; photos: PhotoIndex }) {
  const peak = timeline.find((bucket) => bucket.is_peak)?.local_date ?? timeline[0]?.local_date;
  const [picked, setPicked] = useState<string | null>(null);
  const day = timeline.find((bucket) => bucket.local_date === (picked ?? peak)) || null;
  const rivals = day ? day.entries.filter((entry) => !entry.is_self) : [];
  return (
    <div className="home-glass p-3">
      <div className="eq-scroll px-0.5" role="tablist" aria-label="Días con aperturas">
        {timeline.map((bucket) => {
          const on = bucket.local_date === day?.local_date;
          const chip = dayChip(bucket.local_date);
          return (
            <button
              key={bucket.local_date}
              type="button"
              role="tab"
              aria-selected={on}
              onClick={() => setPicked(bucket.local_date)}
              className={`relative flex h-[4.25rem] w-[3.6rem] shrink-0 flex-col items-center justify-center rounded-2xl transition-colors duration-300 ease-out ${
                on ? "bg-white text-[#0b0b0b]" : "bg-[#1c1c1e] text-white/70 hover:text-white"
              }`}
            >
              <span className="text-[10.5px] font-medium capitalize opacity-70">{chip.week}</span>
              <span className="text-[17px] font-semibold leading-tight tabular-nums">{chip.day}</span>
              <span className="text-[10.5px] tabular-nums opacity-60">{bucket.count}</span>
              {bucket.is_peak ? <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-[#FF7A3D]" aria-label="día clave" /> : null}
            </button>
          );
        })}
      </div>
      {day ? (
        rivals.length ? (
          <ul key={day.local_date} className="mt-2 divide-y divide-white/[0.05] px-1">
            {rivals.slice(0, 10).map((entry, index) => {
              const name = entry.nickname || entry.name || "Jugador";
              return (
                <li key={`${entry.player_id || name}-${index}`} className="row-in flex items-center gap-2.5 py-2.5" style={{ animationDelay: `${index * 25}ms` }}>
                  <Face name={name} src={photoFor(photos, entry.player_id, name)} size={34} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[14px] font-medium text-white">{name}</span>
                    <span className="block truncate text-[12px] text-white/45">
                      {entry.manager_name || entry.fantasy_team_name || "Rival"} · {entry.is_open ? "abierta" : entry.local_time}
                    </span>
                  </span>
                  <span className="shrink-0 text-[14px] font-semibold tabular-nums text-white">{money(entry.buyout_clause_eur)}</span>
                </li>
              );
            })}
            {rivals.length > 10 ? <li className="py-2 text-center text-[12.5px] text-white/40">y {rivals.length - 10} más</li> : null}
          </ul>
        ) : (
          <p className="px-1 pb-1 pt-3 text-[13px] text-white/45">Ese día solo se abren cláusulas tuyas.</p>
        )
      ) : null}
    </div>
  );
}

export function ClausulasTab({
  plan,
  squads,
  needs,
  photos,
  loading,
  view,
}: {
  plan: PlanPayload | null;
  squads: SquadsPayload | null;
  needs: NeedsPayload | null;
  photos: PhotoIndex;
  loading: boolean;
  view: ClausulasView;
}) {
  const league = useSearchParams().get("league");
  const nowMs = useNow();
  // El calendario necesita todas las cláusulas rivales, no solo las de la regla de oro.
  const [board, setBoard] = useState<{ league: string | null; payload: ClauseBoardPayload | null } | null>(null);

  useEffect(() => {
    let cancelled = false;
    getJson<ClauseBoardPayload>(endpoint("/api/clause-board", league))
      .then((payload) => {
        if (!cancelled) setBoard({ league, payload: payload?.ok === false ? null : payload });
      })
      .catch(() => {
        if (!cancelled) setBoard({ league, payload: null });
      });
    return () => {
      cancelled = true;
    };
  }, [league]);

  const boardPayload = board && board.league === league ? board.payload : null;
  const minute = nowMs > 0 ? Math.floor(nowMs / 60_000) : 0;
  const timeline = useMemo(() => {
    if (!minute) return [];
    return buildClausulazosGuide(plan, squads, needs, minute * 60_000, boardPayload).timeline.filter((bucket) =>
      bucket.entries.some((entry) => !entry.is_self && !entry.is_open),
    );
  }, [plan, squads, needs, boardPayload, minute]);

  const advisor = plan?.asesor_clausulas || null;
  const catalog = useMemo(
    () => browseClauses(boardPayload, advisor?.clausulazos || [], squads),
    [boardPayload, advisor, squads],
  );
  const radarRows = useMemo(
    () => (advisor?.radar_anti_robo?.length ? advisor.radar_anti_robo : plan?.radar_anti_robo || []),
    [advisor, plan],
  );
  const radarById = useMemo(() => new Map(radarRows.map((row) => [String(row.player_id), row])), [radarRows]);
  const [estadoElegido, setEstado] = useState<"abiertas" | "candado" | null>(null);

  if (loading && !plan) return <Skeleton />;
  if (!advisor && !timeline.length) {
    return <Empty title="Sin informe de cláusulas" detail="Pulsa Actualizar para calcular tus cláusulas y los clausulazos." />;
  }

  const resumen = advisor?.resumen;
  const proteger = advisor?.proteger || [];
  const clausulazos = advisor?.clausulazos || [];
  const reventa = advisor?.reventa || [];
  // Atacar enseña lo que recomienda el asesor y, si son pocas, las siguientes mejores hasta MIN_SHOWN.
  const abiertas = topPicks(catalog.abiertas, plan?.cash_eur);
  const cerradas = topPicks(catalog.candado, plan?.cash_eur);
  // Por defecto, las abiertas; si no hay ninguna, directamente las que tienen candado.
  const estado = estadoElegido ?? (abiertas.length || !cerradas.length ? "abiertas" : "candado");
  const shown = estado === "abiertas" ? abiertas : cerradas;
  const preparar = advisor?.preparar || [];
  const watched = new Set([...proteger, ...preparar].map((row) => String(row.player_id)));
  const rest = ((squads?.self?.players || []) as RivalPlayer[])
    .filter((player) => player.player_id && !watched.has(String(player.player_id)))
    .sort((a, b) => (b.buyout_clause ?? 0) - (a.buyout_clause ?? 0));

  const closeMs = plan?.clause_market_close?.at ? Date.parse(plan.clause_market_close.at) : NaN;
  const open = resumen ? resumen.ventana_abierta : Number.isFinite(closeMs) ? nowMs < closeMs : null;
  const parts = open && Number.isFinite(closeMs) && nowMs > 0 ? countdownParts(closeMs, nowMs) : null;
  const danger = resumen?.en_peligro ?? proteger.length;
  const ready = resumen?.clausulazos_listos ?? clausulazos.filter((row) => row.veredicto_codigo === "CLAUSULAR_YA").length;
  const attack = view === "clausulazos";

  const windowPill =
    open !== null ? (
      <p className="flex min-w-0 items-center gap-2 rounded-full bg-black/30 px-3 py-1.5 text-[12px] text-white/70 backdrop-blur-md">
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${open ? "animate-pulse bg-[#10B981]" : "bg-white/40"}`} aria-hidden="true" />
        <span className="truncate">{open ? "Se pueden pagar" : "Ventana cerrada"}</span>
        {parts ? (
          <span className="shrink-0 font-medium tabular-nums text-white">
            {parts.days > 0 ? `${parts.days}d ` : ""}
            {countdownClock(parts)}
          </span>
        ) : null}
      </p>
    ) : null;

  const hero = (
    <section className="home-feature" aria-label="Resumen de cláusulas">
      <div className="relative flex items-center justify-between gap-3">
        <p className="text-[13px] font-medium text-white/60">{attack ? "Clausulazos" : "Tus cláusulas"}</p>
        {windowPill}
      </div>
      {attack ? (
        <p className="relative mt-3 flex items-baseline gap-2 tabular-nums">
          <span className="text-[3rem] font-semibold leading-none tracking-[-0.045em] text-white">{ready}</span>
          <span className="text-base font-medium text-white/60">{ready === 1 ? "listo para pagar" : "listos para pagar"}</span>
        </p>
      ) : (
        <p className="relative mt-3 flex items-baseline gap-2 tabular-nums">
          <span className="text-[3rem] font-semibold leading-none tracking-[-0.045em]" style={{ color: danger ? "#fff" : TONE.green }}>
            {danger}
          </span>
          <span className="text-base font-medium text-white/60">{danger ? (danger === 1 ? "jugador en peligro" : "jugadores en peligro") : "todo protegido"}</span>
        </p>
      )}
      {!attack && resumen?.alertas_prioritarias?.length ? (
        <ul className="relative mt-3 space-y-2" data-ui="alertas-prioritarias">
          {resumen.alertas_prioritarias.map((alerta) => (
            <li key={alerta.player_id} className="rounded-xl border border-[#F87171]/40 bg-[#F87171]/10 px-3 py-2.5 text-[13px] leading-snug text-white/80">
              <span className="font-semibold text-[#FCA5A5]">
                Alerta prioritaria · {alerta.nombre}
                {alerta.abre_el && alerta.abre_el !== "abierta" ? ` · se abre el ${alerta.abre_el}` : " · cláusula abierta"}
              </span>
              <span className="mt-1 block">{alerta.accion}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {!attack && resumen && resumen.coste_proteger_eur > 0 ? (
        <p className="relative mt-2 text-[13.5px] tabular-nums text-white/55">
          Protegerlos cuesta <span className="font-semibold text-white">{money(resumen.coste_proteger_eur)}</span>
        </p>
      ) : null}
      {resumen ? (
        <div className="relative mt-5 grid grid-cols-3 gap-2.5">
          {attack ? (
            <>
              <HeroStat value={String(resumen.clausulazos)} label="Candidatos" />
              <HeroStat value={String(abiertas.length)} label="Abiertas" tone={TONE.green} />
              <HeroStat value={compact(plan?.cash_eur)} label="Caja" />
            </>
          ) : (
            <>
              <HeroStat value={String(resumen.riesgo_alto)} label="Riesgo alto" tone={resumen.riesgo_alto ? TONE.red : undefined} />
              <HeroStat value={String(resumen.seguros)} label="Seguras" tone={TONE.green} />
              <HeroStat value={String(resumen.bloqueadas)} label="Con candado" />
            </>
          )}
        </div>
      ) : null}
    </section>
  );

  const rules = (
    <Disclosure title="Cómo funcionan las cláusulas">
      <ul className="space-y-2">
        {RULES.map((rule) => (
          <li key={rule} className="flex gap-2.5 text-[13.5px] leading-snug text-white/60">
            <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-[#FF9A5A]" aria-hidden="true" />
            {rule}
          </li>
        ))}
      </ul>
    </Disclosure>
  );

  if (attack) {
    return (
      <div className="grid gap-5 min-[1100px]:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] min-[1100px]:items-start">
        <div className="flex min-w-0 flex-col gap-4">
          <UnlockWindow rows={plan?.clause_unlocks_24h} />
          {hero}
          <section aria-label="Clausulazos" className="flex flex-col gap-3">
            <SectionHead title="A quién clausular" meta={abiertas.length + cerradas.length ? `${abiertas.length + cerradas.length}` : undefined} />
            <div className="desk-switch eq-tabs" role="tablist" aria-label="Estado de la cláusula">
              <span className="eq-tabs__ind" style={{ transform: `translateX(${estado === "abiertas" ? 0 : 100}%)` }} aria-hidden="true" />
              {(
                [
                  { id: "abiertas", label: "Abiertas", count: abiertas.length },
                  { id: "candado", label: "Con candado", count: cerradas.length },
                ] as const
              ).map((item) => (
                <button
                  key={item.id}
                  type="button"
                  role="tab"
                  aria-selected={estado === item.id}
                  className="desk-switch__btn eq-tabs__btn"
                  onClick={() => setEstado(item.id)}
                >
                  {item.label}
                  <span className="ml-1.5 tabular-nums opacity-50">{item.count}</span>
                </button>
              ))}
            </div>
            {shown.length ? (
              <ul key={estado} className="home-glass overflow-hidden">
                {shown.map((item, index) => (
                  <Fragment key={item.key}>
                    {!item.suggestion && (index === 0 || shown[index - 1].suggestion) ? (
                      <li className="border-t border-white/[0.05] px-3.5 pb-1 pt-3 text-[11.5px] font-medium text-white/40 first:border-t-0">
                        {index === 0 ? "Sin recomendadas aquí: las mejores por puntos" : "También a tener en cuenta"}
                      </li>
                    ) : null}
                    {item.suggestion ? (
                      <AttackCard row={item.suggestion} photos={photos} index={index} />
                    ) : item.board ? (
                      <PlainClauseRow row={item.board} photos={photos} index={index} />
                    ) : null}
                  </Fragment>
                ))}
              </ul>
            ) : (
              <p className="home-glass flex items-center gap-2.5 px-4 py-4 text-[14px] text-white/60">
                <span className="h-2 w-2 shrink-0 rounded-full bg-white/30" aria-hidden="true" />
                {estado === "abiertas" ? "Ahora mismo ninguna cláusula está abierta." : "Ninguna cláusula tiene candado."}
              </p>
            )}
          </section>
        </div>
        <div className="flex min-w-0 flex-col gap-4">
          {reventa.length ? (
            <section aria-label="Para revender" className="flex flex-col gap-3">
              <SectionHead title="Para revender" meta="cláusula bajo el valor de mercado" />
              <ul className="home-glass overflow-hidden">
                {reventa.map((row, index) => (
                  <AttackCard key={row.player_id} row={row} photos={photos} index={index} />
                ))}
              </ul>
            </section>
          ) : null}
          {timeline.length ? (
            <section aria-label="Próximas aperturas" className="flex flex-col gap-3">
              <SectionHead title="Próximas aperturas" meta="candados de rivales" />
              <Openings timeline={timeline} photos={photos} />
            </section>
          ) : null}
          {rules}
        </div>
      </div>
    );
  }

  return (
    <div className="grid gap-5 min-[1100px]:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] min-[1100px]:items-start">
      <div className="flex min-w-0 flex-col gap-4">
        <UnlockWindow rows={plan?.clause_unlocks_24h} />
        {hero}
      </div>
      <div className="flex min-w-0 flex-col gap-4">
        <section aria-label="Jugadores en peligro" className="flex flex-col gap-3">
          <SectionHead title="Qué proteger" meta={proteger.length ? `${proteger.length}` : undefined} />
          {proteger.length ? (
            <ul className="home-glass overflow-hidden">
              {proteger.map((row, index) => (
                <DefendCard key={row.player_id} row={row} radar={radarById.get(String(row.player_id))} photos={photos} index={index} />
              ))}
            </ul>
          ) : (
            <p className="home-glass flex items-center gap-2.5 px-4 py-4 text-[14px] text-white/60">
              <span className="h-2 w-2 shrink-0 rounded-full bg-[#10B981]" aria-hidden="true" />
              Ningún rival puede pagar hoy tus cláusulas.
            </p>
          )}
        </section>

        {preparar.length ? (
          <section aria-label="Prepara sus cláusulas" className="flex flex-col gap-3">
            <SectionHead title="Prepárate" meta="aún con candado" />
            <p className="-mt-1 px-1 text-[12.5px] leading-snug text-white/45">
              Todavía no se pueden pagar. Deja la cláusula recomendada puesta al menos un día antes de que se abra.
            </p>
            <ul className="home-glass overflow-hidden">
              {preparar.map((row, index) => (
                <DefendCard key={row.player_id} row={row} radar={radarById.get(String(row.player_id))} photos={photos} index={index} />
              ))}
            </ul>
          </section>
        ) : null}

        {rest.length ? (
          <Disclosure title="Resto de tu plantilla" meta={`${rest.length}`}>
            <ul className="divide-y divide-white/[0.05]">
              {rest.map((player) => {
                const name = playerName(player);
                const lock = player.clause_lock;
                const tag = RADAR[(radarById.get(String(player.player_id))?.badge as keyof typeof RADAR) || "gris"];
                const status = player.is_shielded
                  ? "Blindado"
                  : lock?.is_locked
                    ? `Candado hasta ${lock.local_time || lock.local_date || "—"}`
                    : radarById.has(String(player.player_id))
                      ? tag.label
                      : "Sin candado";
                return (
                  <RestRow
                    key={String(player.player_id)}
                    player={player}
                    name={name}
                    status={status}
                    statusColor={radarById.has(String(player.player_id)) && !lock?.is_locked ? tag.color : "rgba(255,255,255,0.45)"}
                    radar={radarById.get(String(player.player_id))}
                    photos={photos}
                  />
                );
              })}
            </ul>
          </Disclosure>
        ) : null}
        {rules}
      </div>
    </div>
  );
}
