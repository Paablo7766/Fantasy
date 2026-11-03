"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { CompararButton } from "@/components/comparador/ComparadorReal";
import { endpoint, getJson } from "@/lib/core/api";
import { buildClausulazosGuide, type DateBucket } from "@/lib/clausulas/clausulazosGuide";
import { playerName, points } from "@/lib/core/format";
import { countdownClock, countdownParts } from "@/lib/inicio/hoy";
import { photoFor, type PhotoIndex } from "@/lib/core/photoIndex";
import { useNow } from "@/lib/core/useClock";
import type {
  ClauseBoardPayload,
  ClausulaEnPeligro,
  ClausulazoSugerido,
  NeedsPayload,
  PlanPayload,
  AlertaClausula,
  RadarAntiRobo,
  RivalPlayer,
  SquadsPayload,
  VeredictoClausulazo,
  VeredictoProteger,
} from "@/lib/types";
import {
  Chevron,
  Disclosure,
  Empty,
  Face,
  Fact,
  HeroStat,
  SectionHead,
  Skeleton,
  TONE,
  Verdict,
  money,
  signedPct,
  toneOf,
} from "@/components/ui/kit";

const RIESGO = {
  ALTO: { label: "Riesgo alto", color: TONE.red },
  MEDIO: { label: "Riesgo medio", color: TONE.amber },
  BAJO: { label: "Vigilar", color: TONE.gray },
} as const;

const PROTEGER: Record<VeredictoProteger, { label: string; color: string }> = {
  PROTEGER_YA: { label: "Sube la cláusula", color: TONE.green },
  PROTEGER_PARCIAL: { label: "Sube un poco", color: TONE.amber },
  SIN_CAJA: { label: "Sin caja", color: TONE.red },
  VENDER_ANTES: { label: "Vende antes", color: TONE.blue },
  ASUMIR: { label: "Asúmelo", color: TONE.gray },
};

const RADAR_BADGE = {
  rojo: { label: "Riesgo alto", color: TONE.red },
  verde: { label: "Sobreprotegido", color: TONE.green },
  gris: { label: "Riesgo cero", color: TONE.gray },
} as const;

const CLAUSULAZO: Record<VeredictoClausulazo, { label: string; color: string }> = {
  CLAUSULAR_YA: { label: "Clausula ya", color: TONE.green },
  PROGRAMAR: { label: "Prográmalo", color: TONE.blue },
  SIN_CAJA: { label: "Te falta caja", color: TONE.red },
  OPORTUNIDAD: { label: "Oportunidad", color: TONE.amber },
  GOLPE_RIVAL: { label: "Golpe al rival", color: TONE.red },
};

const RULES = [
  "Las cláusulas se pagan hasta 24 h antes del primer partido.",
  "Subir la cláusula cuesta la mitad de lo que subes.",
  "Con candado no se puede pagar hasta la hora exacta.",
  "Los blindados no se pueden clausular.",
  "Caja negativa o menos de 11 al empezar: la jornada vale 0.",
  "Desde aquí no se envía nada: confirma en la app oficial.",
];

function dayChip(localDate: string): string {
  const date = new Date(`${localDate}T12:00:00`);
  if (Number.isNaN(date.getTime())) return localDate;
  return date.toLocaleDateString("es-ES", { weekday: "short", day: "numeric" }).replace(".", "");
}

/** Barra de la cláusula actual frente a la perfecta; la marca blanca es la caja del rival más rico. */
function Gauge({ row, verdict }: { row: ClausulaEnPeligro; verdict: { label: string; color: string } }) {
  const perfect = row.clausula_perfecta?.clausula_objetivo ?? row.clausula_actual;
  const top = Math.max(perfect, row.clausula_actual, row.rival_mas_rico?.caja ?? 0, 1);
  const now = Math.min(100, (row.clausula_actual / top) * 100);
  const goal = Math.min(100, (perfect / top) * 100);
  const rich = row.rival_mas_rico ? Math.min(100, (row.rival_mas_rico.caja / top) * 100) : null;
  const safe = row.clausula_actual >= perfect;
  return (
    <span className="block">
      <span className="relative block h-2 rounded-full bg-white/[0.08]" aria-hidden="true">
        {!safe ? <span className="absolute inset-y-0 left-0 rounded-full bg-white/[0.08]" style={{ width: `${goal}%` }} /> : null}
        <span
          className="absolute inset-y-0 left-0 rounded-full"
          style={{ width: `${now}%`, background: safe ? TONE.green : "linear-gradient(90deg, #FC734D, #FF9A5A)" }}
        />
        {rich !== null ? <span className="absolute -top-1 h-4 w-[2px] rounded-full bg-white" style={{ left: `calc(${rich}% - 1px)` }} /> : null}
      </span>
      <span className="mt-2 flex items-center justify-between gap-3">
        <span className="min-w-0 truncate text-[12px] tabular-nums text-white/45">
          {money(row.clausula_actual)}
          {row.clausula_perfecta && !safe ? <span> → {money(perfect)}</span> : null}
        </span>
        <Verdict {...verdict} />
      </span>
    </span>
  );
}

function DangerRow({ row, photos, index }: { row: ClausulaEnPeligro; photos: PhotoIndex; index: number }) {
  const [open, setOpen] = useState(false);
  const verdict = PROTEGER[row.veredicto_codigo] ?? PROTEGER.ASUMIR;
  const risk = RIESGO[row.riesgo] ?? RIESGO.BAJO;
  const best = row.subida_recomendada ?? (row.veredicto_codigo === "SIN_CAJA" ? row.clausula_perfecta : null);
  return (
    <li className="row-in border-b border-white/[0.06] last:border-b-0" style={{ animationDelay: `${index * 30}ms` }}>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="w-full px-4 pb-3 pt-3 text-left transition-colors duration-200 ease-out hover:bg-white/[0.02]"
      >
        <span className="flex items-center gap-3">
          <Face name={row.nombre} src={photoFor(photos, row.player_id, row.nombre)} size={40} />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[15px] font-medium leading-tight text-white">{row.nombre}</span>
            <span className="mt-0.5 block truncate text-[12.5px]" style={{ color: risk.color }}>
              {risk.label}
              <span className="text-white/45">
                {" · "}la pagan {row.rivales_que_pueden_pagar} de {row.rivales_total}
              </span>
            </span>
          </span>
          <Chevron open={open} />
        </span>
        <span className="mt-3 block">
          <Gauge row={row} verdict={verdict} />
        </span>
      </button>
      {open ? (
        <div className="row-in px-4 pb-4">
          <div className="grid grid-cols-3 gap-3">
            <Fact label="Subir" value={best && best.subida_eur > 0 ? `+${money(best.subida_eur)}` : "—"} tone={TONE.copper} />
            <Fact label="Te cuesta" value={best && best.coste_eur > 0 ? money(best.coste_eur) : "—"} />
            <Fact
              label="Impacto XI"
              value={row.tu_once_pierde_sin_el < 0.05 ? "Suplente" : `−${points(row.tu_once_pierde_sin_el)}`}
              tone={row.tu_once_pierde_sin_el < 0.05 ? undefined : TONE.red}
            />
          </div>
          <p className="mt-3 text-[13px] leading-relaxed text-white/55">{row.motivo_detallado}</p>
          {row.niveles.length > 1 ? (
            <ul className="mt-3 divide-y divide-white/[0.06] rounded-xl bg-black/20 px-3">
              {row.niveles.map((level) => (
                <li key={level.clausula_objetivo} className="flex items-center justify-between gap-3 py-2 text-[12.5px] tabular-nums">
                  <span className="min-w-0 truncate text-white/75">
                    {money(level.clausula_objetivo)}
                    <span className="ml-2 text-white/40">
                      cubre {level.rivales_cubiertos}/{level.rivales_cubiertos + level.rivales_sin_cubrir}
                    </span>
                  </span>
                  <span className="shrink-0" style={{ color: level.viable ? "#fff" : TONE.red }}>
                    {money(level.coste_eur)}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

function RaidRow({ row, photos, index }: { row: ClausulazoSugerido; photos: PhotoIndex; index: number }) {
  const [open, setOpen] = useState(false);
  const verdict = CLAUSULAZO[row.veredicto_codigo] ?? CLAUSULAZO.OPORTUNIDAD;
  const margin = row.margen_valor_justo_pct;
  return (
    <li className="row-in border-b border-white/[0.06] last:border-b-0" style={{ animationDelay: `${index * 30}ms` }}>
      <div className="flex items-center">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex min-h-[4rem] min-w-0 flex-1 items-center gap-3 py-3 pl-4 pr-2 text-left transition-colors duration-200 ease-out hover:bg-white/[0.02]"
      >
        <Face name={row.nombre} src={photoFor(photos, row.player_id, row.nombre)} size={40} />
        <span className="min-w-0 flex-1">
          <span className="line-clamp-2 block break-words text-[15px] font-medium leading-tight text-white">{row.nombre}</span>
          <span className="mt-0.5 block truncate text-[12.5px] text-white/45">
            <span style={{ color: row.abierta_ahora ? TONE.green : TONE.blue }}>{row.abierta_ahora ? "Abierta" : row.cuando}</span>
            {row.propietario ? ` · ${row.propietario}` : ""}
          </span>
        </span>
        <span className="shrink-0 text-right">
          <span className="block text-[15px] font-semibold tabular-nums text-white">{money(row.clausula_eur)}</span>
          {typeof margin === "number" ? (
            <span className="block text-[12px] font-medium tabular-nums" style={{ color: toneOf(margin) }}>
              {margin >= 0 ? `${Math.round(margin)}% bajo` : `${Math.abs(Math.round(margin))}% sobre`}
            </span>
          ) : null}
        </span>
        <Chevron open={open} />
      </button>
      <CompararButton objetivoId={row.player_id} posicion={row.posicion} className="mr-3" />
      </div>
      {open ? (
        <div className="row-in px-4 pb-4">
          <p className="flex flex-wrap items-center justify-between gap-2">
            <Verdict {...verdict} />
            <span className="text-[12.5px] text-white/45">{row.abierta_ahora ? "Se puede pagar ya" : `Se abre ${row.cuando}`}</span>
          </p>
          <div className="mt-3 grid grid-cols-3 gap-3">
            <Fact label="Mejora once" value={row.mejora_once > 0 ? `+${points(row.mejora_once)}` : "—"} tone={row.mejora_once > 0 ? TONE.green : undefined} />
            <Fact label="xP jornada" value={points(row.xp_jornada)} tone="#FFC08A" />
            <Fact label="Valor justo" value={money(row.valor_justo)} hint={typeof row.prevision_7d_pct === "number" ? `${signedPct(row.prevision_7d_pct)} 7 días` : undefined} />
          </div>
          {!row.asequible && row.falta_caja_eur > 0 ? (
            <p className="mt-3 text-[13px] text-[#FC734D]">Te faltan {money(row.falta_caja_eur)}</p>
          ) : null}
          <p className="mt-3 text-[13px] leading-relaxed text-white/55">{row.motivo_detallado}</p>
        </div>
      ) : null}
    </li>
  );
}

function RadarCard({ row, photos, index }: { row: RadarAntiRobo; photos: PhotoIndex; index: number }) {
  const tone = RADAR_BADGE[row.badge as keyof typeof RADAR_BADGE] ?? RADAR_BADGE.gris;
  const when = row.clausula_abierta ? "Abierta" : typeof row.dias_para_abrir === "number" ? `Abre en ${row.dias_para_abrir.toLocaleString("es-ES", { maximumFractionDigits: 1 })} días` : "A punto de abrir";
  return (
    <li className="row-in border-b border-white/[0.06] px-4 py-3 last:border-b-0" style={{ animationDelay: `${index * 30}ms` }}>
      <div className="flex items-start gap-3">
        <Face name={row.nombre} src={photoFor(photos, row.player_id, row.nombre)} size={40} />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="truncate text-[15px] font-medium leading-tight text-white">{row.nombre}</p>
              <p className="mt-0.5 text-[12px] text-white/45">
                {when}
                {row.posicion ? ` · ${row.posicion}` : ""}
                {typeof row.rivales_con_caja === "number" ? ` · ${row.rivales_con_caja} con caja` : ""}
              </p>
            </div>
            <Verdict {...tone} />
          </div>
          <p className="mt-2 rounded-xl px-3 py-2 text-[13px] leading-relaxed" style={{ color: tone.color, background: "rgba(0,0,0,0.22)" }}>
            {row.consejo}
          </p>
        </div>
      </div>
    </li>
  );
}

function Calendar({ timeline, photos }: { timeline: DateBucket[]; photos: PhotoIndex }) {
  const peak = timeline.find((bucket) => bucket.is_peak)?.local_date ?? timeline.find((bucket) => bucket.locked_count)?.local_date;
  const [picked, setPicked] = useState<string | null>(null);
  const day = timeline.find((bucket) => bucket.local_date === (picked ?? peak ?? timeline[0]?.local_date)) || null;
  return (
    <div>
      <div className="eq-scroll -mx-1 px-1" role="tablist" aria-label="Días con desbloqueos">
        {timeline.map((bucket) => {
          const on = bucket.local_date === day?.local_date;
          return (
            <button
              key={bucket.local_date}
              type="button"
              role="tab"
              aria-selected={on}
              onClick={() => setPicked(bucket.local_date)}
              className={`flex min-h-[3.5rem] w-[4.25rem] shrink-0 flex-col items-center justify-center rounded-2xl border transition-all duration-200 ease-out ${
                on ? "border-transparent bg-white text-[#120C09]" : "border-white/[0.08] bg-white/[0.04] text-white/70 hover:text-white"
              }`}
            >
              <span className="text-[12px] capitalize">{dayChip(bucket.local_date)}</span>
              <span className="text-[16px] font-semibold tabular-nums">{bucket.count}</span>
              {bucket.is_peak ? <span className={`h-1 w-1 rounded-full ${on ? "bg-[#FF7A3D]" : "bg-[#FF9A5A]"}`} aria-label="día clave" /> : null}
            </button>
          );
        })}
      </div>
      {day ? (
        <ul key={day.local_date} className="mt-3">
          {day.entries.slice(0, 12).map((entry, index) => {
            const name = entry.nickname || entry.name || "Jugador";
            return (
              <li
                key={`${entry.player_id || name}-${index}`}
                className="row-in flex items-center gap-2.5 border-b border-white/[0.06] py-2.5 last:border-b-0"
                style={{ animationDelay: `${index * 30}ms` }}
              >
                <Face name={name} src={photoFor(photos, entry.player_id, name)} size={36} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[14px] font-medium text-white">{name}</span>
                  <span className="block truncate text-[12px] text-white/45">
                    {entry.is_self ? <span className="text-[#FF9A5A]">Tuyo</span> : entry.manager_name || entry.fantasy_team_name || "Rival"}
                    {" · "}
                    {entry.is_open ? "abierta" : entry.local_time}
                  </span>
                </span>
                <span className="shrink-0 text-[14px] font-medium tabular-nums text-white">{money(entry.buyout_clause_eur)}</span>
                {entry.is_self ? null : <CompararButton objetivoId={entry.player_id} posicion={entry.position} />}
              </li>
            );
          })}
          {day.entries.length > 12 ? <li className="pt-2 text-center text-[12.5px] text-white/45">y {day.entries.length - 12} más</li> : null}
        </ul>
      ) : null}
    </div>
  );
}

/** «Mías» defiende tu plantilla; «Clausulazos» ataca la de los rivales. */
export type ClausulasView = "mias" | "clausulazos";

function ClausulaAlertas({ alertas }: { alertas: AlertaClausula[] }) {
  if (!alertas.length) return null;
  return (
    <section aria-label="Escudo y francotirador" className="flex flex-col gap-3">
      <SectionHead title="Escudo y francotirador" meta={`${alertas.length}`} />
      <ul className="home-glass overflow-hidden">
        {alertas.map((alerta, index) => {
          const tone = alerta.tono === "verde" ? TONE.green : TONE.red;
          return (
            <li
              key={`${alerta.tipo}-${alerta.player_id || alerta.nombre}-${index}`}
              className="border-b border-white/[0.06] px-4 py-3 last:border-b-0"
            >
              <p className="text-[13.5px] leading-snug" style={{ color: tone }}>
                {alerta.mensaje}
              </p>
            </li>
          );
        })}
      </ul>
    </section>
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
  // El calendario solo cambia con los datos; la cuenta atrás se pinta aparte.
  const minute = nowMs > 0 ? Math.floor(nowMs / 60_000) : 0;
  const timeline = useMemo(() => {
    if (!minute) return [];
    return buildClausulazosGuide(plan, squads, needs, minute * 60_000, boardPayload).timeline.filter((bucket) => bucket.locked_count > 0);
  }, [plan, squads, needs, boardPayload, minute]);

  const advisor = plan?.asesor_clausulas || null;
  const radar = advisor?.radar_anti_robo?.length ? advisor.radar_anti_robo : plan?.radar_anti_robo || [];
  const alertas = advisor?.alertas_clausulas?.length ? advisor.alertas_clausulas : plan?.plan_fichajes?.alertas_clausulas || [];
  if (loading && !plan) return <Skeleton />;
  if (!advisor && !timeline.length) {
    return <Empty title="Sin informe de cláusulas" detail="Pulsa Actualizar para calcular tus cláusulas y los clausulazos." />;
  }

  const resumen = advisor?.resumen;
  const proteger = advisor?.proteger || [];
  const clausulazos = advisor?.clausulazos || [];
  const watched = new Set(proteger.map((row) => String(row.player_id)));
  const rest = ((squads?.self?.players || []) as RivalPlayer[])
    .filter((player) => player.player_id && !watched.has(String(player.player_id)))
    .sort((a, b) => (b.buyout_clause ?? 0) - (a.buyout_clause ?? 0));

  const closeMs = plan?.clause_market_close?.at ? Date.parse(plan.clause_market_close.at) : NaN;
  const open = resumen ? resumen.ventana_abierta : Number.isFinite(closeMs) ? nowMs < closeMs : null;
  const parts = open && Number.isFinite(closeMs) && nowMs > 0 ? countdownParts(closeMs, nowMs) : null;
  const danger = resumen?.en_peligro ?? proteger.length;

  const heroBlock = (
        <section className="home-feature" aria-label="Resumen de cláusulas">
          <div className="relative flex items-center justify-between gap-3">
            <p className="text-[13px] font-medium text-white/60">Tus cláusulas</p>
            {open !== null ? (
              <p className="flex min-w-0 items-center gap-2 rounded-full border border-white/10 bg-black/25 px-3 py-1.5 text-[12px] text-white/70 backdrop-blur-md">
                <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${open ? "animate-pulse bg-[#10B981]" : "bg-white/40"}`} aria-hidden="true" />
                <span className="truncate">{open ? "Ventana abierta" : "Ventana cerrada"}</span>
                {parts ? (
                  <span className="shrink-0 font-medium tabular-nums text-white">
                    {parts.days > 0 ? `${parts.days}d ` : ""}
                    {countdownClock(parts)}
                  </span>
                ) : null}
              </p>
            ) : null}
          </div>
          <p className="relative mt-3 flex items-baseline gap-2 tabular-nums">
            <span className="text-[3rem] font-semibold leading-none tracking-[-0.045em]" style={{ color: danger ? "#fff" : TONE.green }}>
              {danger}
            </span>
            <span className="text-base font-medium text-white/55">{danger ? "en peligro" : "Todo protegido"}</span>
          </p>
          {resumen && resumen.coste_proteger_eur > 0 ? (
            <p className="relative mt-2 text-[13.5px] tabular-nums text-white/55">
              Protegerlo todo cuesta <span className="font-medium text-white">{money(resumen.coste_proteger_eur)}</span>
            </p>
          ) : null}
          {resumen ? (
            <div className="relative mt-5 grid grid-cols-3 gap-2.5">
              <HeroStat value={String(resumen.riesgo_alto)} label="Riesgo alto" tone={resumen.riesgo_alto ? TONE.red : undefined} />
              <HeroStat value={String(resumen.seguros + resumen.bloqueadas)} label="Seguras" tone={TONE.green} />
              <HeroStat value={String(resumen.clausulazos)} label="Clausulazos" tone={resumen.clausulazos_listos ? TONE.copper : undefined} />
            </div>
          ) : null}
        </section>
  );
  const rulesBlock = (
        <Disclosure title="Reglas clave">
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

  if (view === "clausulazos") {
    return (
      <div className="flex min-w-0 flex-col gap-4">
        {heroBlock}
        <ClausulaAlertas alertas={alertas} />
        <section aria-label="Clausulazos disponibles" className="flex flex-col gap-3">
          <SectionHead title="Clausulazos" meta={clausulazos.length ? `${clausulazos.length}` : undefined} />
          {clausulazos.length ? (
            <ul className="home-glass overflow-hidden">
              {clausulazos.map((row, index) => (
                <RaidRow key={row.player_id} row={row} photos={photos} index={index} />
              ))}
            </ul>
          ) : (
            <p className="home-glass px-4 py-4 text-[14px] text-white/60">Hoy ningún clausulazo mejora tu once ni sale barato.</p>
          )}
        </section>
        {rulesBlock}
      </div>
    );
  }

  return (
    <div className="grid gap-5 min-[1100px]:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] min-[1100px]:items-start">
      <div className="flex min-w-0 flex-col gap-4">
        {heroBlock}
        <ClausulaAlertas alertas={alertas} />
        {radar.length ? (
          <section aria-label="Radar anti-robo" className="flex flex-col gap-3">
            <SectionHead title="Radar anti-robo" meta={`${radar.length}`} />
            <ul className="home-glass overflow-hidden">
              {radar.map((row, index) => (
                <RadarCard key={row.player_id} row={row} photos={photos} index={index} />
              ))}
            </ul>
          </section>
        ) : null}

        <section aria-label="Mis cláusulas" className="flex flex-col gap-3">
          <SectionHead title="Mis cláusulas" meta={proteger.length ? `${proteger.length} a vigilar` : undefined} />
          {proteger.length ? (
            <ul className="home-glass overflow-hidden">
              {proteger.map((row, index) => (
                <DangerRow key={row.player_id} row={row} photos={photos} index={index} />
              ))}
            </ul>
          ) : (
            <p className="home-glass flex items-center gap-2.5 px-4 py-4 text-[14px] text-white/60">
              <span className="h-2 w-2 shrink-0 rounded-full bg-[#10B981]" aria-hidden="true" />
              Ningún rival puede pagar hoy tus cláusulas.
            </p>
          )}
          {rest.length ? (
            <Disclosure title="Resto de tu plantilla" meta={`${rest.length}`}>
              <ul>
                {rest.map((player) => {
                  const name = playerName(player);
                  const lock = player.clause_lock;
                  return (
                    <li key={String(player.player_id)} className="flex items-center gap-2.5 border-b border-white/[0.06] py-2.5 last:border-b-0">
                      <Face name={name} src={player.image_url || photoFor(photos, player.player_id, name)} size={36} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[14px] text-white">{name}</span>
                        <span className="block truncate text-[12px] text-white/45">
                          {player.is_shielded ? "Blindado" : lock?.is_locked ? `Candado hasta ${lock.local_time || lock.local_date || "—"}` : "Sin candado"}
                        </span>
                      </span>
                      <span className="shrink-0 text-[14px] font-medium tabular-nums text-white">{money(player.buyout_clause)}</span>
                    </li>
                  );
                })}
              </ul>
            </Disclosure>
          ) : null}
        </section>
      </div>

      <div className="flex min-w-0 flex-col gap-4">
        {timeline.length ? (
          <section aria-label="Calendario de desbloqueos" className="flex flex-col gap-3">
            <SectionHead title="Desbloqueos" meta={`${timeline.reduce((sum, bucket) => sum + bucket.locked_count, 0)} candados`} />
            <div className="home-glass p-4">
              <Calendar timeline={timeline} photos={photos} />
            </div>
          </section>
        ) : null}
        {rulesBlock}
      </div>
    </div>
  );
}
