"use client";

import { useSearchParams } from "next/navigation";
import { Fragment, useEffect, useMemo, useState, type ReactNode } from "react";
import { CompararButton } from "@/components/comparador/ComparadorReal";
import { endpoint, getJson } from "@/lib/core/api";
import { buildClausulazosGuide, type DateBucket } from "@/lib/clausulas/clausulazosGuide";
import { Crest } from "@/components/ui/Crest";
import { playerName, points } from "@/lib/core/format";
import { countdownClock, countdownParts } from "@/lib/inicio/hoy";
import { photoFor, type PhotoIndex } from "@/lib/core/photoIndex";
import { useNow } from "@/lib/core/useClock";
import type {
  AlertaPrioritaria,
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
import { Chevron, Disclosure, Empty, Face, Fact, Skeleton, TONE, cleanText, forecastHint, money } from "@/components/ui/kit";

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

const MUTED = "rgba(255,255,255,0.45)";

/** Rejilla de las tablas: en móvil, jugador y cláusula; en escritorio, todas las columnas. */
const SLIM_GRID = "grid grid-cols-[minmax(0,1fr)_auto_1rem] items-center gap-x-3";
const DEFEND_GRID = `${SLIM_GRID} min-[900px]:grid-cols-[minmax(0,2.2fr)_minmax(0,1fr)_minmax(0,1.1fr)_minmax(0,2.3fr)_1rem] min-[900px]:gap-x-5`;
const ATTACK_GRID = `${SLIM_GRID} min-[900px]:grid-cols-[minmax(0,2.3fr)_repeat(3,minmax(0,1fr))_minmax(0,1.5fr)_1rem] min-[900px]:gap-x-5`;

/** Celda numérica: cifra arriba y un apoyo gris debajo. Solo la cifra lleva color, y solo si significa algo. */
function Cell({ value, sub, tone, subTone, className = "" }: { value: string; sub?: string; tone?: string; subTone?: string; className?: string }) {
  return (
    <span className={`min-w-0 text-right ${className}`}>
      <span className="block truncate text-[14px] font-medium tabular-nums" style={{ color: tone || "#fff" }}>
        {value}
      </span>
      {sub ? (
        <span className="mt-0.5 block truncate text-[11.5px] tabular-nums" style={{ color: subTone || "rgba(255,255,255,0.4)" }}>
          {sub}
        </span>
      ) : null}
    </span>
  );
}

/** Estado en una línea: punto de color y texto gris. Sin caja ni fondo. */
function Status({ label, color, className = "", wrap = false }: { label: string; color?: string | null; className?: string; wrap?: boolean }) {
  return (
    <span className={`min-w-0 gap-1.5 ${wrap ? "items-baseline" : "items-center"} ${className || "inline-flex"}`}>
      {color ? <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${wrap ? "-translate-y-px" : ""}`} style={{ background: color }} aria-hidden="true" /> : null}
      <span className={wrap ? "min-w-0 leading-snug" : "truncate"}>{label}</span>
    </span>
  );
}

function ColumnHead({ grid, labels }: { grid: string; labels: { label: string; left?: boolean }[] }) {
  return (
    <div className={`${grid} hidden border-y border-white/[0.06] px-5 py-2 min-[900px]:grid`} aria-hidden="true">
      {labels.map((item) => (
        <span key={item.label} className={`truncate text-[11.5px] text-white/40 ${item.left ? "" : "text-right"}`}>
          {item.label}
        </span>
      ))}
      <span />
    </div>
  );
}

function GroupLabel({ title, hint }: { title: string; hint?: string }) {
  return (
    <li className="flex flex-wrap items-baseline gap-x-2 px-4 pb-2 pt-4 text-[11.5px] min-[900px]:px-5">
      <span className="font-semibold text-white/70">{title}</span>
      {hint ? <span className="text-white/40">{hint}</span> : null}
    </li>
  );
}

/** Cabecera de una superficie: título, cuenta y una línea de apoyo. */
function CardHead({ title, count, caption, children }: { title: string; count?: number; caption?: string; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3 px-4 pb-3 pt-4 min-[900px]:px-5">
      <div className="min-w-0">
        <h3 className="text-[15px] font-semibold text-white">
          {title}
          {typeof count === "number" ? <span className="ml-1.5 font-normal tabular-nums text-white/40">{count}</span> : null}
        </h3>
        {caption ? <p className="mt-0.5 text-[12.5px] leading-snug text-white/45">{caption}</p> : null}
      </div>
      {children}
    </div>
  );
}

function Tile({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="min-w-0 rounded-[1.1rem] bg-black/40 px-3.5 py-3 backdrop-blur-md">
      <p className="truncate text-[11.5px] text-white/50">{label}</p>
      <p className="mt-1.5 truncate text-[1.1rem] font-semibold leading-none tabular-nums" style={{ color: tone || "#fff" }}>
        {value}
      </p>
    </div>
  );
}

/* ── Defender ───────────────────────────────────────────────────────────── */

/** La subida que de verdad recomienda el asesor; null si lo sensato es no tocarla. */
function recommendedLevel(row: ClausulaEnPeligro) {
  const best = row.subida_recomendada ?? (row.veredicto_codigo === "SIN_CAJA" ? row.clausula_perfecta : null);
  return best && best.clausula_objetivo > row.clausula_actual ? best : null;
}

/** Por qué no se recomienda subirla, en pocas palabras. */
function keepReason(row: ClausulaEnPeligro): string {
  if (row.veredicto_codigo === "SOBREPROTEGIDO") return "Ya cubre el sustituto";
  if (row.veredicto_codigo === "VENDER_ANTES") return "Mejor venderlo";
  if (!row.rivales_que_pueden_pagar) return "Hoy nadie la paga";
  if (!row.niveles.length) return "Ya está en el tope";
  return "Subirla no compensa";
}

/** Cuándo se puede pagar tu cláusula, en corto. */
function exposure(row: ClausulaEnPeligro): string {
  if (row.en_candado) return `Candado hasta ${row.candado_vence_texto || row.expuesta_cuando || "—"}`;
  if (row.abre_el && row.abre_el !== "abierta") return `Se abre el ${row.abre_el.replace("-", " ")}`;
  return "Abierta";
}

type Action = { title: string; sub: string; color: string | null };

/** Una sola instrucción por jugador: lo que hay que hacer y lo que cuesta. */
function defendAction(row: ClausulaEnPeligro, alert: AlertaPrioritaria | undefined): Action {
  const pos = row.posicion || "jugador";
  if (row.alerta_prioritaria || row.veredicto_codigo === "SIN_RECAMBIO") {
    const swap = row.recambio_sugerido ?? alert?.recambio_sugerido;
    return {
      title: swap?.nombre ? `Ficha recambio: ${swap.nombre}` : `Ficha un ${pos} de recambio`,
      sub: [`Es tu único ${pos}`, typeof swap?.coste === "number" ? `cuesta ${money(swap.coste)}` : null].filter(Boolean).join(" · "),
      color: TONE.red,
    };
  }
  const raise = recommendedLevel(row);
  if (raise) {
    const short = row.veredicto_codigo === "SIN_CAJA";
    return {
      title: `Súbela a ${money(raise.clausula_objetivo)}`,
      sub: `Cuesta ${money(raise.coste_eur, 1)}${short ? " · no te llega la caja" : row.en_candado ? " · antes de que se abra" : ""}`,
      color: short ? TONE.red : TONE.amber,
    };
  }
  if (row.veredicto_codigo === "VENDER_ANTES") return { title: "Mejor venderlo", sub: "Antes de que te lo quiten", color: TONE.blue };
  if (row.en_candado || row.veredicto_codigo === "SOBREPROTEGIDO") return { title: "Nada por ahora", sub: keepReason(row), color: null };
  return { title: (PROTEGER[row.veredicto_codigo] ?? PROTEGER.ASUMIR).label, sub: keepReason(row), color: null };
}

/** Un punto por rival: los rellenos pueden pagar la cláusula hoy. */
function Payers({ can, total, color }: { can: number; total: number; color: string }) {
  const dots = Math.min(Math.max(total, 0), 12);
  const filled = total > dots ? Math.round((can / total) * dots) : can;
  return (
    <span className="mt-1.5 flex justify-end gap-[3px]" aria-hidden="true">
      {Array.from({ length: dots }, (_, index) => (
        <span key={index} className="h-1.5 w-1.5 rounded-full" style={{ background: index < filled ? color : "rgba(255,255,255,0.14)" }} />
      ))}
    </span>
  );
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
  const safe = rich === null || row.clausula_actual > rich;
  return (
    <div>
      <div className="relative h-2 rounded-full bg-white/[0.07]" aria-hidden="true">
        {goal > now ? <span className="absolute inset-y-0 left-0 rounded-full bg-white/[0.14]" style={{ width: `${goal}%` }} /> : null}
        <span
          className="absolute inset-y-0 left-0 rounded-full transition-[width] duration-700 ease-out"
          style={{ width: `${now}%`, background: safe ? TONE.green : "rgba(255,255,255,0.85)" }}
        />
        {rich !== null ? (
          <span className="absolute -top-1 h-4 w-[2px] rounded-full" style={{ left: `calc(${(rich / top) * 100}% - 1px)`, background: TONE.red }} />
        ) : null}
      </div>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-[11.5px] tabular-nums text-white/45">
        <span>
          Tu cláusula <span className="font-semibold text-white">{money(row.clausula_actual)}</span>
          {goal > now ? <span> · recomendada {money(perfect)}</span> : null}
        </span>
        {rich !== null ? (
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-[2px] rounded-full" style={{ background: TONE.red }} aria-hidden="true" />
            {row.rival_mas_rico?.manager || "El rival más rico"} tiene {money(rich)}
          </span>
        ) : null}
      </div>
    </div>
  );
}

function DefendRow({
  row,
  alert,
  radar,
  photos,
}: {
  row: ClausulaEnPeligro;
  alert: AlertaPrioritaria | undefined;
  radar: RadarAntiRobo | undefined;
  photos: PhotoIndex;
}) {
  const [open, setOpen] = useState(false);
  const action = defendAction(row, alert);
  const raise = recommendedLevel(row);
  const riskColor = row.en_candado || !row.rivales_que_pueden_pagar ? MUTED : RIESGO[row.riesgo]?.color === TONE.gray ? "rgba(255,255,255,0.7)" : (RIESGO[row.riesgo] ?? RIESGO.BAJO).color;
  const payers = `${row.rivales_que_pueden_pagar} de ${row.rivales_total}`;
  const multiple =
    typeof row.multiplo_clausula === "number" ? `${row.multiplo_clausula.toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}× su valor` : undefined;
  const advice = cleanText(alert?.accion || row.motivo_detallado);
  return (
    <li className="transition-colors duration-300 hover:bg-white/[0.025]" style={open ? { background: "rgba(255,255,255,0.03)" } : undefined}>
      <button type="button" aria-expanded={open} onClick={() => setOpen((value) => !value)} className={`${DEFEND_GRID} w-full px-4 py-3 text-left min-[900px]:px-5`}>
        <span className="flex min-w-0 items-center gap-3">
          <Face name={row.nombre} src={photoFor(photos, row.player_id, row.nombre)} size={40} />
          <span className="min-w-0">
            <span className="block truncate text-[14.5px] font-medium leading-tight text-white">{row.nombre}</span>
            <span className="mt-1 block truncate text-[12px] text-white/45">{[row.posicion, exposure(row)].filter(Boolean).join(" · ")}</span>
            <Status wrap label={action.title} color={action.color} className="mt-1 flex text-[12.5px] text-white/75 min-[900px]:hidden" />
          </span>
        </span>

        {/* Cláusula: en móvil lleva debajo cuántos la pagan; en escritorio, su múltiplo. */}
        <span className="min-w-0 text-right">
          <span className="block text-[14.5px] font-semibold tabular-nums text-white">{money(row.clausula_actual)}</span>
          <span className="mt-0.5 block text-[11.5px] tabular-nums text-white/40 min-[900px]:hidden">{payers} la pagan</span>
          {multiple ? <span className="mt-0.5 hidden text-[11.5px] tabular-nums text-white/40 min-[900px]:block">{multiple}</span> : null}
        </span>

        <span className="hidden min-w-0 text-right min-[900px]:block">
          <span className="block text-[14px] font-medium tabular-nums text-white">
            {payers} <span className="font-normal text-white/40">rivales</span>
          </span>
          <Payers can={row.rivales_que_pueden_pagar} total={row.rivales_total} color={riskColor} />
        </span>

        <span className="hidden min-w-0 min-[900px]:block">
          <Status label={action.title} color={action.color} className="flex text-[14px] font-medium text-white" />
          <span className="mt-0.5 block truncate text-[11.5px] tabular-nums text-white/40">{action.sub}</span>
        </span>
        <Chevron open={open} />
      </button>

      {open ? (
        <div className="row-in px-4 pb-5 pt-1 min-[900px]:px-5 min-[900px]:pl-[4.5rem]">
          <p className="mb-3 text-[12.5px] tabular-nums text-white/50 min-[900px]:hidden">{action.sub}</p>
          <Shield row={row} />
          <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3.5 sm:grid-cols-4">
            {raise ? (
              <Fact label="Cláusula recomendada" value={money(raise.clausula_objetivo)} hint={`subirla cuesta ${money(raise.coste_eur, 1)}`} />
            ) : (
              <Fact label="Cláusula recomendada" value="La actual" hint={keepReason(row).toLowerCase()} />
            )}
            <Fact label="Valor de mercado" value={money(row.valor_mercado)} hint={forecastHint(row.valor_mercado, row.prevision_7d_pct)} />
            <Fact
              label="Tu once sin él"
              value={row.tu_once_pierde_sin_el < 0.05 ? "Igual" : `−${points(row.tu_once_pierde_sin_el)} pts`}
              tone={row.tu_once_pierde_sin_el < 0.05 ? undefined : TONE.red}
            />
            <Fact label="Próxima jornada" value={typeof row.xp_jornada === "number" ? `${points(row.xp_jornada)} pts` : "—"} hint={row.en_xi ? "en tu once" : "suplente"} />
          </div>
          {advice ? <p className="mt-4 max-w-[62ch] text-[13px] leading-relaxed text-white/60">{advice}</p> : null}
          {/* Con alerta de recambio manda esa instrucción: el consejo del radar («súbela») la contradice. */}
          {radar?.consejo && !alert ? <p className="mt-2 max-w-[62ch] text-[13px] leading-relaxed text-white/45">{cleanText(radar.consejo)}</p> : null}
          {row.niveles.length > 1 ? (
            <div className="mt-4 max-w-md">
              <div className="grid grid-cols-[4.5rem_minmax(0,1fr)_4.5rem] gap-3 pb-1.5 text-[11px] text-white/40">
                <span>Si la subes a</span>
                <span>Rivales que dejan de poder pagarla</span>
                <span className="text-right">Te cuesta</span>
              </div>
              <ul className="divide-y divide-white/[0.05] border-t border-white/[0.06]">
                {row.niveles.map((level) => {
                  const total = level.rivales_cubiertos + level.rivales_sin_cubrir;
                  const picked = raise?.clausula_objetivo === level.clausula_objetivo;
                  return (
                    <li key={level.clausula_objetivo} className="grid grid-cols-[4.5rem_minmax(0,1fr)_4.5rem] items-center gap-3 py-2 text-[12.5px] tabular-nums">
                      <span className={picked ? "font-semibold text-white" : "text-white/70"}>{money(level.clausula_objetivo)}</span>
                      <span className="flex min-w-0 items-center gap-2">
                        <span className="h-1 flex-1 overflow-hidden rounded-full bg-white/[0.07]">
                          <span className="block h-full rounded-full bg-white/70" style={{ width: `${total ? (level.rivales_cubiertos / total) * 100 : 0}%` }} />
                        </span>
                        <span className="shrink-0 text-white/45">
                          {level.rivales_cubiertos}/{total}
                        </span>
                      </span>
                      <span className="text-right" style={{ color: level.viable ? "rgba(255,255,255,0.8)" : TONE.red }}>
                        {money(level.coste_eur)}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : null}
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
  statusColor: string | null;
  radar: RadarAntiRobo | undefined;
  photos: PhotoIndex;
}) {
  const [open, setOpen] = useState(false);
  const loses = player.tu_once_pierde_sin_el ?? null;
  const pct = radar?.prevision_7d_pct;
  const days = radar?.dias_para_abrir;
  return (
    <li>
      <button type="button" aria-expanded={open} onClick={() => setOpen((value) => !value)} className="flex w-full items-center gap-3 py-2.5 text-left">
        <Face name={name} src={player.image_url || photoFor(photos, player.player_id, name)} size={36} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[14px] font-medium text-white">{name}</span>
          <Status label={status} color={statusColor} className="mt-0.5 flex text-[12px] text-white/45" />
        </span>
        <span className="shrink-0 text-[14px] font-semibold tabular-nums text-white">{money(player.buyout_clause)}</span>
        <Chevron open={open} />
      </button>
      {open ? (
        <div className="row-in pb-3 pl-12">
          <div className="grid grid-cols-3 gap-3">
            <Fact label="Valor" value={money(player.market_value)} hint={forecastHint(player.market_value, pct) ?? (player.prevision_7d_pct || undefined)} />
            <Fact label="Próxima jornada" value={typeof player.own_expected_points === "number" ? `${points(player.own_expected_points)} pts` : "—"} />
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

/* ── Atacar ─────────────────────────────────────────────────────────────── */

/** Cláusula frente a valor de mercado: por debajo es ganga (verde); por encima, sobreprecio (gris). */
function premium(clause: number | null | undefined, value: number | null | undefined): { text: string; cheap: boolean } | null {
  if (typeof clause !== "number" || typeof value !== "number" || value <= 0) return null;
  const pct = Math.round((clause / value - 1) * 100);
  if (pct === 0) return { text: "igual que su valor", cheap: false };
  return pct < 0 ? { text: `${Math.abs(pct)} % bajo su valor`, cheap: true } : { text: `${pct} % sobre su valor`, cheap: false };
}

/** Una cláusula rival, venga del asesor (con veredicto) o del tablero de la liga (solo datos). */
function AttackRow({ item, cash, photos, wide = true }: { item: ClauseBrowseItem; cash: number | null | undefined; photos: PhotoIndex; wide?: boolean }) {
  const [open, setOpen] = useState(false);
  const tip = item.suggestion;
  const board = item.board;
  const name = tip?.nombre || board?.nickname || board?.name || "Jugador";
  const position = tip?.posicion || board?.position || null;
  const owner = tip?.propietario || board?.manager_name || null;
  const clause = tip?.clausula_eur ?? board?.buyout_clause_eur ?? null;
  const value = tip?.valor_mercado ?? board?.market_value ?? null;
  const average = typeof board?.average_points === "number" ? board.average_points : null;
  const gain = tip && tip.mejora_once > 0 ? tip.mejora_once : null;
  const cashAfter = tip?.caja_tras ?? (typeof cash === "number" && typeof clause === "number" ? cash - clause : null);
  const short = typeof cashAfter === "number" && cashAfter < 0;
  const versus = premium(clause, value);
  const resale = tip?.es_reventa && typeof tip.beneficio_reventa_eur === "number" ? tip.beneficio_reventa_eur : null;
  const hot = board?.dinero_caliente || null;

  const verdict = tip ? (CLAUSULAZO[tip.veredicto_codigo] ?? CLAUSULAZO.OPORTUNIDAD) : null;
  const status: { label: string; color: string | null; sub?: string } = tip
    ? { label: verdict!.label, color: verdict!.color, sub: tip.abierta_ahora ? undefined : `Abre ${tip.cuando}` }
    : board?.on_market
      ? { label: "En el mercado", color: null, sub: board.market_listing_expires_local_time ? `hasta las ${board.market_listing_expires_local_time}` : undefined }
      : board?.is_locked
        ? { label: opensLabel(board), color: null }
        : { label: short ? "No te llega la caja" : hot ? "Su dueño acaba de cobrar" : "", color: null };

  const wideOnly = wide ? "hidden min-[900px]:block" : "hidden";
  const slimOnly = wide ? "min-[900px]:hidden" : "";
  const slimNote = resale !== null
    ? { text: `+${money(resale)} al revender`, color: TONE.green }
    : gain !== null
      ? { text: `+${points(gain)} pts a tu once`, color: TONE.green }
      : versus
        ? { text: versus.text, color: versus.cheap ? TONE.green : "rgba(255,255,255,0.4)" }
        : null;

  return (
    <li className="transition-colors duration-300 hover:bg-white/[0.025]" style={open ? { background: "rgba(255,255,255,0.03)" } : undefined}>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((state) => !state)}
        className={`${wide ? ATTACK_GRID : SLIM_GRID} w-full px-4 py-3 text-left ${wide ? "min-[900px]:px-5" : ""}`}
      >
        <span className="flex min-w-0 items-center gap-3">
          <Face name={name} src={board?.image_url || photoFor(photos, item.key, name)} size={40} />
          <span className="min-w-0">
            <span className="block truncate text-[14.5px] font-medium leading-tight text-white">{name}</span>
            <span className="mt-1 flex min-w-0 items-center gap-1.5 text-[12px] text-white/45">
              <Crest club={board?.club} size={14} />
              <span className="truncate">{[position, owner].filter(Boolean).join(" · ")}</span>
            </span>
            {status.label ? <Status label={status.label} color={status.color} className={`mt-1 flex text-[12.5px] text-white/75 ${slimOnly}`} /> : null}
          </span>
        </span>

        <span className="min-w-0 text-right">
          <span className="block text-[14.5px] font-semibold tabular-nums text-white">{money(clause)}</span>
          {slimNote ? (
            <span className={`mt-0.5 block text-[11.5px] tabular-nums ${slimOnly}`} style={{ color: slimNote.color }}>
              {slimNote.text}
            </span>
          ) : null}
          {versus ? (
            <span className={`mt-0.5 text-[11.5px] tabular-nums ${wideOnly}`} style={{ color: versus.cheap ? TONE.green : "rgba(255,255,255,0.4)" }}>
              {versus.text}
            </span>
          ) : null}
        </span>

        <Cell
          className={wideOnly}
          value={gain !== null ? `+${points(gain)} pts` : "—"}
          tone={gain !== null ? TONE.green : "rgba(255,255,255,0.35)"}
          sub={tip ? `prevé ${points(tip.xp_jornada)} pts` : average !== null ? `media ${points(average)}` : undefined}
        />
        <Cell
          className={wideOnly}
          value={money(cashAfter)}
          tone={short ? TONE.red : undefined}
          sub={tip && !tip.asequible && tip.falta_caja_eur > 0 ? `faltan ${money(tip.falta_caja_eur)}` : undefined}
        />
        <span className={`min-w-0 ${wideOnly}`}>
          <Status label={status.label || "—"} color={status.color} className={`flex text-[13.5px] ${tip ? "font-medium text-white" : status.label ? "text-white/50" : "text-white/25"}`} />
          {status.sub ? <span className="mt-0.5 block truncate text-[11.5px] tabular-nums text-white/40">{status.sub}</span> : null}
        </span>
        <Chevron open={open} />
      </button>

      {open ? (
        <div className={`row-in px-4 pb-5 pt-1 ${wide ? "min-[900px]:px-5 min-[900px]:pl-[4.5rem]" : ""}`}>
          <div className="grid grid-cols-2 gap-x-4 gap-y-3.5 sm:grid-cols-4">
            <Fact
              label={tip ? "Próxima jornada" : "Media por jornada"}
              value={tip ? `${points(tip.xp_jornada)} pts` : average !== null ? `${points(average)} pts` : "—"}
              hint={gain !== null ? `+${points(gain)} a tu once` : undefined}
            />
            <Fact label="Valor de mercado" value={money(value)} hint={forecastHint(value, tip?.prevision_7d_pct)} />
            {resale !== null ? (
              <Fact label="Ganas al revender" value={money(resale)} tone={TONE.green} />
            ) : (
              <Fact label="Caja después" value={money(cashAfter)} tone={short ? TONE.red : undefined} />
            )}
            {tip && tip.rivales_que_pueden_quitartelo > 0 ? (
              <Fact label="Te lo pueden quitar" value={`${tip.rivales_que_pueden_quitartelo} ${tip.rivales_que_pueden_quitartelo === 1 ? "rival" : "rivales"}`} hint="con caja para su cláusula" />
            ) : (
              <Fact label="Se puede pagar" value={tip ? (tip.abierta_ahora ? "Ahora" : cleanText(tip.cuando)) : board ? opensLabel(board).replace(/^Abre /, "") : "—"} />
            )}
          </div>
          {tip && !tip.asequible && tip.falta_caja_eur > 0 ? (
            <p className="mt-4 text-[13px]" style={{ color: TONE.red }}>
              Te faltan {money(tip.falta_caja_eur)} para pagarla.
            </p>
          ) : null}
          {tip?.motivo_detallado ? <p className="mt-4 max-w-[62ch] text-[13px] leading-relaxed text-white/60">{cleanText(tip.motivo_detallado)}</p> : null}
          {hot ? (
            <p className="mt-3 max-w-[62ch] text-[13px] leading-relaxed text-white/50">
              {owner || "Su dueño"} acaba de cobrar {money(hot.importe_eur, 1)}: puede subir la cláusula en cualquier momento.
            </p>
          ) : null}
          <div className="mt-4">
            <CompararButton objetivoId={item.key} posicion={position} className="!bg-white/[0.08] !px-4 !py-2 !text-white" />
          </div>
        </div>
      ) : null}
    </li>
  );
}

/** Cuándo se abren los candados de los rivales, día a día. */
function Openings({ timeline, photos }: { timeline: DateBucket[]; photos: PhotoIndex }) {
  const [picked, setPicked] = useState<string | null>(null);
  const day = timeline.find((bucket) => bucket.local_date === picked) || timeline[0] || null;
  const rivals = day ? day.entries.filter((entry) => !entry.is_self) : [];
  return (
    <section className="home-glass min-w-0 overflow-hidden" aria-label="Próximas aperturas">
      <CardHead title="Próximas aperturas" caption="Cuándo vence el candado de cada jugador rival" />
      <div className="eq-scroll px-4 pb-3 min-[900px]:px-5" role="tablist" aria-label="Días con aperturas">
        {timeline.map((bucket) => {
          const on = bucket.local_date === day?.local_date;
          const chip = dayChip(bucket.local_date);
          return (
            <button
              key={bucket.local_date}
              type="button"
              role="tab"
              aria-selected={on}
              aria-label={`${chip.week} ${chip.day}: ${bucket.count} aperturas`}
              onClick={() => setPicked(bucket.local_date)}
              className={`flex h-[3.75rem] w-[3.1rem] shrink-0 flex-col items-center justify-center rounded-2xl transition-colors duration-300 ease-out ${
                on ? "bg-white text-ink-on-light" : "text-white/60 hover:bg-white/[0.05] hover:text-white"
              }`}
            >
              <span className="text-[10.5px] font-medium capitalize opacity-60">{chip.week}</span>
              <span className="text-[16px] font-semibold leading-tight tabular-nums">{chip.day}</span>
              <span className="text-[10.5px] tabular-nums opacity-55">{bucket.count}</span>
            </button>
          );
        })}
      </div>
      {day ? (
        rivals.length ? (
          <ul key={day.local_date} className="divide-y divide-white/[0.05] border-t border-white/[0.06]">
            {rivals.slice(0, 8).map((entry, index) => {
              const name = entry.nickname || entry.name || "Jugador";
              return (
                <li key={`${entry.player_id || name}-${index}`} className="row-in flex items-center gap-3 px-4 py-2.5 min-[900px]:px-5" style={{ animationDelay: `${index * 25}ms` }}>
                  <span className="w-11 shrink-0 text-[12.5px] font-medium tabular-nums text-white/70">{entry.is_open ? "Ya" : entry.local_time}</span>
                  <Face name={name} src={photoFor(photos, entry.player_id, name)} size={32} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[14px] font-medium text-white">{name}</span>
                    <span className="block truncate text-[12px] text-white/45">
                      {[entry.position, entry.manager_name || entry.fantasy_team_name || "Rival"].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                  <span className="shrink-0 text-[14px] font-semibold tabular-nums text-white">{money(entry.buyout_clause_eur)}</span>
                </li>
              );
            })}
            {rivals.length > 8 ? <li className="px-4 py-2.5 text-[12.5px] text-white/40 min-[900px]:px-5">y {rivals.length - 8} más ese día</li> : null}
          </ul>
        ) : (
          <p className="border-t border-white/[0.06] px-4 py-4 text-[13px] text-white/45 min-[900px]:px-5">Ese día solo se abren cláusulas tuyas.</p>
        )
      ) : null}
    </section>
  );
}

/* ── Pestaña ────────────────────────────────────────────────────────────── */

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
  const cash = plan?.cash_eur;
  // Atacar enseña lo que recomienda el asesor y, si son pocas, las siguientes mejores hasta MIN_SHOWN.
  const abiertas = topPicks(catalog.abiertas, cash);
  const cerradas = topPicks(catalog.candado, cash);
  // Por defecto, las abiertas; si no hay ninguna, directamente las que tienen candado.
  const estado = estadoElegido ?? (abiertas.length || !cerradas.length ? "abiertas" : "candado");
  const shown = estado === "abiertas" ? abiertas : cerradas;
  const preparar = advisor?.preparar || [];
  const alerts = resumen?.alertas_prioritarias || [];
  const alertById = new Map(alerts.map((alert) => [String(alert.player_id), alert]));
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
  const best = clausulazos.find((row) => row.abierta_ahora && row.asequible && row.mejora_once > 0) || null;

  const hero = (
    <section className="home-feature" aria-label="Resumen de cláusulas">
      <div className="flex items-center justify-between gap-3">
        <p className="shrink-0 text-[13px] font-medium text-white/65">{attack ? "Clausulazos" : "Tus cláusulas"}</p>
        {open !== null ? (
          <p className="flex min-w-0 items-center gap-2 rounded-full bg-black/35 px-3 py-1.5 text-[12px] text-white/70 backdrop-blur-md">
            <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${open ? "bg-mint" : "bg-white/40"}`} aria-hidden="true" />
            <span className="truncate">{open ? (parts ? "Cierra en" : "Ventana abierta") : "Ventana cerrada"}</span>
            {parts ? (
              <span className="shrink-0 font-medium tabular-nums text-white">
                {parts.days > 0 ? `${parts.days}d ` : ""}
                {countdownClock(parts)}
              </span>
            ) : null}
          </p>
        ) : null}
      </div>
      <div className="mt-3 grid gap-5 min-[900px]:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] min-[900px]:items-end">
        <div className="min-w-0">
          <p className="flex items-baseline gap-2.5 tabular-nums">
            <span className="text-[3.1rem] font-semibold leading-none tracking-[-0.045em] text-white">{attack ? ready : danger}</span>
            <span className="text-base font-medium text-white/65">
              {attack
                ? ready === 1
                  ? "listo para pagar"
                  : "listos para pagar"
                : danger
                  ? danger === 1
                    ? "jugador en peligro"
                    : "jugadores en peligro"
                  : "en peligro: todo protegido"}
            </span>
          </p>
          {attack ? (
            best ? (
              <p className="mt-3 max-w-[46ch] text-[13.5px] leading-snug tabular-nums text-white/65">
                El mejor golpe: <span className="font-semibold text-white">{best.nombre}</span>, +{points(best.mejora_once)} pts a tu once por {money(best.clausula_eur)}.
              </p>
            ) : null
          ) : alerts.length || (resumen && resumen.coste_proteger_eur > 0) ? (
            <p className="mt-3 max-w-[46ch] text-[13.5px] leading-snug tabular-nums text-white/65">
              {alerts.length ? (
                <>
                  <span className="font-semibold text-white">
                    {alerts.length === 1 ? "1 no tiene recambio" : `${alerts.length} no tienen recambio`}
                  </span>{" "}
                  en su puesto: si te quitan a uno, la jornada vale 0.{" "}
                </>
              ) : null}
              {resumen && resumen.coste_proteger_eur > 0 ? (
                <>
                  Subir las cláusulas recomendadas cuesta <span className="font-semibold text-white">{money(resumen.coste_proteger_eur)}</span>.
                </>
              ) : null}
            </p>
          ) : null}
        </div>
        {resumen ? (
          <div className="grid grid-cols-2 gap-2 min-[560px]:grid-cols-4">
            {attack ? (
              <>
                <Tile label="Tu caja" value={money(cash, 1)} tone={typeof cash === "number" && cash < 0 ? TONE.red : undefined} />
                <Tile label="Recomendados" value={String(resumen.clausulazos)} />
                <Tile label="Abiertas" value={String(abiertas.length)} />
                <Tile label="Con candado" value={String(cerradas.length)} />
              </>
            ) : (
              <>
                <Tile label="Riesgo alto" value={String(resumen.riesgo_alto)} tone={resumen.riesgo_alto ? TONE.red : undefined} />
                <Tile label="Seguras" value={String(resumen.seguros)} />
                <Tile label="Con candado" value={String(resumen.bloqueadas)} />
                <Tile label="Tu caja" value={money(cash, 1)} tone={typeof cash === "number" && cash < 0 ? TONE.red : undefined} />
              </>
            )}
          </div>
        ) : null}
      </div>
    </section>
  );

  const rules = (
    <Disclosure title="Cómo funcionan las cláusulas">
      <ul className="space-y-2">
        {RULES.map((rule) => (
          <li key={rule} className="flex gap-2.5 text-[13.5px] leading-snug text-white/60">
            <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-white/35" aria-hidden="true" />
            {rule}
          </li>
        ))}
      </ul>
    </Disclosure>
  );

  if (attack) {
    const tabs = [
      { id: "abiertas", label: "Abiertas", count: abiertas.length },
      { id: "candado", label: "Con candado", count: cerradas.length },
    ] as const;
    return (
      <div className="flex min-w-0 flex-col gap-4">
        {hero}
        <section aria-label="A quién clausular" className="home-glass min-w-0 overflow-hidden">
          <CardHead title="A quién clausular" caption="Primero lo que recomienda el asesor; después, las mejores por puntos">
            <div className="relative grid shrink-0 grid-cols-2 rounded-full bg-white/[0.06] p-[3px]" role="tablist" aria-label="Estado de la cláusula">
              <span
                className="absolute inset-y-[3px] left-[3px] w-[calc(50%-3px)] rounded-full bg-white transition-transform duration-500 ease-[cubic-bezier(0.16,1,0.3,1)]"
                style={{ transform: `translateX(${estado === "candado" ? "100%" : "0"})` }}
                aria-hidden="true"
              />
              {tabs.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  role="tab"
                  aria-selected={estado === item.id}
                  onClick={() => setEstado(item.id)}
                  className={`relative z-10 min-h-[2rem] whitespace-nowrap rounded-full px-3.5 text-[12px] font-semibold transition-colors duration-300 ${
                    estado === item.id ? "text-ink-on-light" : "text-white/55 hover:text-white"
                  }`}
                >
                  {item.label}
                  <span className="ml-1.5 font-normal tabular-nums opacity-55">{item.count}</span>
                </button>
              ))}
            </div>
          </CardHead>
          <ColumnHead
            grid={ATTACK_GRID}
            labels={[
              { label: "Jugador", left: true },
              { label: "Cláusula" },
              { label: "Suma a tu once" },
              { label: "Caja después" },
              { label: "Veredicto", left: true },
            ]}
          />
          {shown.length ? (
            <ul key={estado} className="row-in divide-y divide-white/[0.05] border-t border-white/[0.06] min-[900px]:border-t-0">
              {shown.map((item, index) => (
                <Fragment key={item.key}>
                  {!item.suggestion && (index === 0 || shown[index - 1].suggestion) ? (
                    <GroupLabel
                      title={index === 0 ? "Las mejores por puntos" : "También a tener en cuenta"}
                      hint={index === 0 ? "el asesor no recomienda ninguna aquí" : "no mejoran tu once, pero están a tiro"}
                    />
                  ) : index === 0 ? (
                    <GroupLabel title="Recomendadas" />
                  ) : null}
                  <AttackRow item={item} cash={cash} photos={photos} />
                </Fragment>
              ))}
            </ul>
          ) : (
            <p className="border-t border-white/[0.06] px-4 py-5 text-[14px] text-white/55 min-[900px]:px-5">
              {estado === "abiertas" ? "Ahora mismo ninguna cláusula está abierta." : "Ninguna cláusula tiene candado."}
            </p>
          )}
        </section>

        <div className="grid gap-4 min-[900px]:grid-cols-2 min-[900px]:items-start">
          {timeline.length ? <Openings timeline={timeline} photos={photos} /> : null}
          <div className="flex min-w-0 flex-col gap-4">
            {reventa.length ? (
              <section aria-label="Para revender" className="home-glass min-w-0 overflow-hidden">
                <CardHead title="Para revender" count={reventa.length} caption="Cláusula por debajo de su valor de mercado" />
                <ul className="divide-y divide-white/[0.05] border-t border-white/[0.06]">
                  {reventa.map((row) => (
                    <AttackRow key={row.player_id} item={{ key: String(row.player_id), suggestion: row }} cash={cash} photos={photos} wide={false} />
                  ))}
                </ul>
              </section>
            ) : null}
            {rules}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-w-0 flex-col gap-4">
      {hero}
      <section aria-label="Qué proteger" className="home-glass min-w-0 overflow-hidden">
        <CardHead title="Qué proteger" count={proteger.length + preparar.length} caption="Una instrucción por jugador; el detalle, al desplegar" />
        <ColumnHead
          grid={DEFEND_GRID}
          labels={[{ label: "Jugador", left: true }, { label: "Cláusula" }, { label: "Pueden pagarla" }, { label: "Qué hacer", left: true }]}
        />
        <ul className="divide-y divide-white/[0.05] border-t border-white/[0.06] min-[900px]:border-t-0">
          {proteger.length ? (
            <>
              <GroupLabel title="Expuestas hasta el próximo cierre" />
              {proteger.map((row) => (
                <DefendRow key={row.player_id} row={row} alert={alertById.get(String(row.player_id))} radar={radarById.get(String(row.player_id))} photos={photos} />
              ))}
            </>
          ) : (
            <li className="flex items-center gap-2.5 px-4 py-5 text-[14px] text-white/60 min-[900px]:px-5">
              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-mint" aria-hidden="true" />
              Ningún rival puede pagar hoy tus cláusulas.
            </li>
          )}
          {preparar.length ? (
            <>
              <GroupLabel title="Con candado" hint="deja la cláusula recomendada puesta un día antes de que se abra" />
              {preparar.map((row) => (
                <DefendRow key={row.player_id} row={row} alert={alertById.get(String(row.player_id))} radar={radarById.get(String(row.player_id))} photos={photos} />
              ))}
            </>
          ) : null}
        </ul>
      </section>

      <div className="grid gap-4 min-[900px]:grid-cols-2 min-[900px]:items-start">
        {rest.length ? (
          <Disclosure title="Resto de tu plantilla" meta={`${rest.length}`}>
            <ul className="divide-y divide-white/[0.05]">
              {rest.map((player) => {
                const name = playerName(player);
                const lock = player.clause_lock;
                const known = radarById.has(String(player.player_id));
                const tag = RADAR[(radarById.get(String(player.player_id))?.badge as keyof typeof RADAR) || "gris"] ?? RADAR.gris;
                const status = player.is_shielded
                  ? "Blindado"
                  : lock?.is_locked
                    ? `Candado hasta ${lock.local_time || lock.local_date || "—"}`
                    : known
                      ? tag.label
                      : "Sin candado";
                return (
                  <RestRow
                    key={String(player.player_id)}
                    player={player}
                    name={name}
                    status={status}
                    statusColor={known && !lock?.is_locked && !player.is_shielded && tag.color !== TONE.gray ? tag.color : null}
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
