"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useDashboard } from "@/components/DashboardProvider";
import { Crest } from "@/components/ui/Crest";
import { ErrorCard } from "@/components/ui/Feedback";
import { Empty, Face, HeroStat, Skeleton, TONE, compact, lastName, money, ringColor } from "@/components/ui/kit";
import { endpoint } from "@/lib/core/api";
import { points, titularFull } from "@/lib/core/format";
import { cachedJson, peekJson } from "@/lib/core/jsonCache";
import { POSICIONES, construirPlan, valor, type Horizonte, type Movimiento } from "@/lib/equipo/planificador";
import type { PlanificadorJugador, PlanificadorLibre, PlanificadorPayload, PlanificadorPosicion } from "@/lib/types";

const NOMBRE_PUESTO: Record<PlanificadorPosicion, string> = { POR: "Porteros", DEF: "Defensas", MC: "Medios", DEL: "Delanteros" };
const RANKING_CORTO = 8;
const RANKING_LARGO = 25;

const madrid = new Intl.DateTimeFormat("es-ES", { timeZone: "Europe/Madrid", weekday: "short", day: "numeric" });
const madridHora = new Intl.DateTimeFormat("es-ES", { timeZone: "Europe/Madrid", weekday: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

function fecha(iso: string | null | undefined, conHora = false): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return (conHora ? madridHora : madrid).format(date).replace(/\./g, "");
}

/** Tiempo hasta un cierre, corto: «5 h», «2 d». */
function faltan(iso: string | null): string {
  if (!iso) return "—";
  const ms = new Date(iso).getTime() - Date.now();
  if (Number.isNaN(ms)) return "—";
  if (ms <= 0) return "Ya";
  const horas = ms / 3_600_000;
  if (horas < 1) return `${Math.max(1, Math.round(ms / 60_000))} min`;
  if (horas < 48) return `${Math.round(horas)} h`;
  return `${Math.round(horas / 24)} d`;
}

function urgente(iso: string | null): boolean {
  if (!iso) return false;
  const ms = new Date(iso).getTime() - Date.now();
  return ms > 0 && ms < 12 * 3_600_000;
}

function EstadoMedico({ estado }: { estado: "baja" | "duda" | null }) {
  if (!estado) return null;
  return (
    <span className="shrink-0 text-[11.5px] font-medium" style={{ color: estado === "baja" ? TONE.red : TONE.amber }}>
      {estado === "baja" ? "Baja" : "Duda"}
    </span>
  );
}

/** Cómo conseguirlo, en una línea corta. */
function comoConseguirlo(jugador: PlanificadorJugador): string {
  if (jugador.dueno.tipo === "mio") return "Tuyo";
  if (jugador.mercado) {
    const cierra = fecha(jugador.mercado.cierra_at, true);
    return `Mercado · ${money(jugador.mercado.precio)}${cierra ? ` · ${cierra}` : ""}`;
  }
  const c = jugador.clausula;
  if (c?.estado === "abierta") return `Cláusula · ${money(c.eur)} · ${jugador.dueno.nombre}`;
  if (c?.estado === "bloqueada") return `${jugador.dueno.nombre} · abre ${fecha(c.abre_at, true) ?? "más adelante"}`;
  if (c?.estado === "blindado") return `${jugador.dueno.nombre} · blindado`;
  return jugador.dueno.nombre;
}

/** Versión corta para la fila; el detalle lleva la completa. */
function disponible(jugador: PlanificadorJugador): string {
  if (jugador.dueno.tipo === "mio") return jugador.valor ? `Tuyo · ${money(jugador.valor)}` : "Tuyo";
  if (jugador.mercado) return `Mercado · ${money(jugador.mercado.precio)}`;
  const c = jugador.clausula;
  if (c?.estado === "abierta") return `Cláusula · ${money(c.eur)}`;
  if (c?.estado === "bloqueada") return `Cláusula abre ${fecha(c.abre_at) ?? "más adelante"}`;
  if (c?.estado === "blindado") return "Blindado";
  return jugador.dueno.nombre;
}

/** Las cuatro jornadas del jugador, con la elegida resaltada. */
function Detalle({ jugador, h, jornadas, sufijo }: { jugador: PlanificadorJugador; h: Horizonte; jornadas: Array<number | null>; sufijo: string }) {
  const accion = jugador.mercado
    ? { href: `/mercado${sufijo}`, label: "Pujar en Mercado" }
    : jugador.clausula?.estado === "abierta" || jugador.clausula?.estado === "bloqueada"
      ? { href: `/clausulas${sufijo}`, label: "Ver en Cláusulas" }
      : null;
  return (
    <div className="row-in px-3.5 pb-3.5">
      <p className="mb-2.5 truncate text-[12.5px] text-white/60">{comoConseguirlo(jugador)}</p>
      <ul className="grid grid-cols-4 gap-1.5">
        {jugador.partidos.map((partido, index) => (
          <li key={index} className={h === index ? "plan-day plan-day--on" : "plan-day"}>
            <span className="text-[10.5px] text-white/40">J{jornadas[index] ?? index + 1}</span>
            <span className="mt-1.5 h-[18px]">{partido?.rival ? <Crest club={partido.rival} size={18} /> : null}</span>
            <span className="mt-1 text-[10.5px] text-white/40">{partido ? (partido.casa === false ? "fuera" : "casa") : "—"}</span>
            <span className="mt-1 font-mono text-[15px] font-semibold tabular-nums text-white">{points(jugador.xp[index])}</span>
          </li>
        ))}
      </ul>
      <p className="mt-3 flex items-center justify-between gap-3 text-[12.5px] text-white/50">
        <span>
          Titular <span className="font-medium" style={{ color: ringColor(jugador.p_titular) }}>{titularFull(jugador.p_titular)}</span>
        </span>
        {accion ? (
          <Link href={accion.href} className="shrink-0 font-medium text-ember-strong hover:text-white">
            {accion.label} →
          </Link>
        ) : null}
      </p>
    </div>
  );
}

type FilaProps = {
  jugador: PlanificadorJugador;
  h: Horizonte;
  abierto: boolean;
  onToggle: () => void;
  jornadas: Array<number | null>;
  sufijo: string;
  linea: string;
  derecha: ReactNode;
  lead?: ReactNode;
  /** Enseña el rival de la jornada (solo con una jornada elegida). */
  rival?: boolean;
};

function Fila({ jugador, h, abierto, onToggle, jornadas, sufijo, linea, derecha, lead, rival = false }: FilaProps) {
  const nombre = jugador.nombre || "Jugador";
  const partido = rival && h !== "total" ? jugador.partidos[h] : null;
  return (
    <li>
      <button type="button" aria-expanded={abierto} className="plan-row" onClick={onToggle}>
        {lead}
        <Face name={nombre} src={jugador.image_url} size={40} ring={ringColor(jugador.p_titular)} />
        <span className="min-w-0 flex-1">
          <span className="flex min-w-0 items-center gap-1.5">
            <Crest club={jugador.club} size={15} />
            <span className="truncate text-[15px] font-medium leading-tight text-white">{lastName(nombre)}</span>
            <EstadoMedico estado={jugador.estado} />
          </span>
          <span className="mt-1 flex min-w-0 items-center gap-1 text-[12px] text-white/45">
            {partido?.rival ? (
              <span className="inline-flex shrink-0 items-center gap-1" title={`${partido.casa === false ? "en" : "vs"} ${partido.rival}`}>
                <span className="text-white/35">{partido.casa === false ? "en" : "vs"}</span>
                <Crest club={partido.rival} size={13} />
                <span className="text-white/25">·</span>
              </span>
            ) : null}
            <span className="truncate">{linea}</span>
          </span>
        </span>
        <span className="shrink-0 text-right">{derecha}</span>
      </button>
      {abierto ? <Detalle jugador={jugador} h={h} jornadas={jornadas} sufijo={sufijo} /> : null}
    </li>
  );
}

function Cifra({ value, label, tone }: { value: string; label: string; tone?: string }) {
  return (
    <>
      <span className="block font-mono text-[1.05rem] font-semibold leading-none tabular-nums" style={{ color: tone ?? "#fff" }}>
        {value}
      </span>
      <span className="mt-1 block max-w-[5.5rem] truncate text-[11px] text-white/40">{label}</span>
    </>
  );
}

function Mejora({ m }: { m: Movimiento }) {
  return <Cifra value={`+${points(m.mejora)}`} tone={TONE.green} label={m.sale ? `por ${lastName(m.sale.nombre || "")}` : "al once"} />;
}

function Seccion({ titulo, nota, children }: { titulo: string; nota?: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2.5" aria-label={titulo}>
      <div className="px-1">
        <h2 className="text-[1.05rem] font-semibold tracking-tight text-white">{titulo}</h2>
        {nota ? <p className="mt-0.5 text-[12.5px] leading-snug text-white/45">{nota}</p> : null}
      </div>
      {children}
    </section>
  );
}

function Libre({ libre }: { libre: PlanificadorLibre }) {
  const nombre = libre.nombre || "Jugador";
  return (
    <li className="home-glass flex w-[8.25rem] shrink-0 flex-col items-center px-3 py-3.5 text-center">
      <Face name={nombre} src={libre.image_url} size={44} />
      <span className="mt-2 flex w-full min-w-0 items-center justify-center gap-1">
        <Crest club={libre.club} size={13} />
        <span className="truncate text-[13.5px] font-medium text-white">{lastName(nombre)}</span>
      </span>
      <span className="mt-0.5 text-[11.5px] text-white/40">
        {libre.posicion}
        {libre.valor ? <span className="tabular-nums text-white/55"> · {money(libre.valor)}</span> : null}
      </span>
      <span className="mt-2.5 grid w-full grid-cols-2 gap-1 border-t border-white/[0.06] pt-2.5">
        <span>
          <span className="block font-mono text-[15px] font-semibold tabular-nums text-white">{points(libre.media)}</span>
          <span className="block text-[10.5px] text-white/40">media</span>
        </span>
        <span>
          <span className="block font-mono text-[15px] font-semibold tabular-nums text-white">{points(libre.forma)}</span>
          <span className="block text-[10.5px] text-white/40">últ. 3</span>
        </span>
      </span>
      {libre.estado ? (
        <span className="mt-2">
          <EstadoMedico estado={libre.estado} />
        </span>
      ) : null}
    </li>
  );
}

function Switch<T extends string | number>({ opciones, actual, onChange, label }: { opciones: Array<[T, string]>; actual: T; onChange: (v: T) => void; label: string }) {
  return (
    <div className="desk-switch" style={{ gridTemplateColumns: `repeat(${opciones.length}, minmax(0, 1fr))` }} role="tablist" aria-label={label}>
      {opciones.map(([id, texto]) => (
        <button
          key={String(id)}
          type="button"
          role="tab"
          aria-selected={actual === id}
          className={actual === id ? "desk-switch__btn desk-switch__btn--on" : "desk-switch__btn"}
          onClick={() => onChange(id)}
        >
          {texto}
        </button>
      ))}
    </div>
  );
}

export function Planificador() {
  const search = useSearchParams();
  const { trends, state: dash } = useDashboard();
  const league = trends?.league_id || search.get("league");
  const url = endpoint("/api/planificador", league);
  const sufijo = search.get("league") ? `?league=${encodeURIComponent(search.get("league")!)}` : "";
  const [payload, setPayload] = useState<PlanificadorPayload | null>(() => peekJson<PlanificadorPayload>(url) ?? null);
  const [loading, setLoading] = useState(() => !peekJson(url));
  const stamp = dash.trends ? ((dash.trends as { dashboard_at?: string }).dashboard_at ?? null) : null;

  const [h, setH] = useState<Horizonte>(0);
  const [puesto, setPuesto] = useState<PlanificadorPosicion>("DEL");
  const [abierto, setAbierto] = useState<string | null>(null);
  const [verMas, setVerMas] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function run() {
      setLoading(true);
      try {
        const data = await cachedJson<PlanificadorPayload>(url);
        if (!cancelled) setPayload(data);
      } catch (reason: unknown) {
        if (cancelled) return;
        const message = reason instanceof Error ? reason.message : "Sin datos.";
        const hint = /404|Not Found/i.test(message) ? " El backend no tiene la ruta nueva: reinícialo." : "";
        setPayload({ ok: false, error: { message: `${message}${hint}` } });
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void run();
    return () => {
      cancelled = true;
    };
  }, [url, stamp]);

  const jugadores = useMemo(() => payload?.jugadores ?? [], [payload]);
  const plan = useMemo(() => construirPlan(jugadores, h), [jugadores, h]);
  const ranking = useMemo(
    () => jugadores.filter((j) => j.posicion === puesto && valor(j, h) !== null).sort((a, b) => (valor(b, h) ?? 0) - (valor(a, h) ?? 0)),
    [jugadores, puesto, h],
  );

  if (loading && !payload) return <Skeleton />;
  if (!payload || payload.ok === false) {
    return <ErrorCard title="Planificador" payload={payload || { error: { message: "Sin datos." } }} brief />;
  }
  if (!jugadores.length) {
    return <Empty title="Sin xP de las próximas jornadas" detail="Pulsa Actualizar en Inicio para calcular la proyección." />;
  }

  const jornadas = payload.jornadas ?? [null, null, null, null];
  const etiquetaH = h === "total" ? `J${jornadas[0] ?? "?"}–J${jornadas[3] ?? "?"}` : `J${jornadas[h] ?? h + 1}`;
  const libres = (payload.libres ?? []).filter((l) => l.estado !== "baja").slice(0, 12);
  const toggle = (id: string) => setAbierto((actual) => (actual === id ? null : id));
  const mejora = plan.base && plan.techo ? plan.techo.total - plan.base.total : 0;
  const hayPlan = plan.pasos.length > 0;
  const fila = (clave: string, jugador: PlanificadorJugador, linea: string, derecha: ReactNode, lead?: ReactNode, rival = false) => (
    <Fila
      key={`${clave}-${jugador.player_id}`}
      jugador={jugador}
      h={h}
      abierto={abierto === `${clave}-${jugador.player_id}`}
      onToggle={() => toggle(`${clave}-${jugador.player_id}`)}
      jornadas={jornadas}
      sufijo={sufijo}
      linea={linea}
      derecha={derecha}
      lead={lead}
      rival={rival}
    />
  );

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <Switch<string>
        label="Jornada"
        actual={String(h)}
        opciones={[...[0, 1, 2, 3].map((i): [string, string] => [String(i), `J${jornadas[i] ?? i + 1}`]), ["total", "Total"]]}
        onChange={(v) => {
          setH(v === "total" ? "total" : (Number(v) as Horizonte));
          setAbierto(null);
        }}
      />

      <section className="home-feature" aria-label="Tu once">
        <div className="relative">
          <div className="flex items-start justify-between gap-3">
            <p className="text-[13px] font-medium text-white/60">Tu mejor once · {etiquetaH}</p>
            {(plan.techo ?? plan.base)?.formacion ? (
              <span className="shrink-0 rounded-full border border-white/10 bg-black/25 px-2.5 py-1 text-[12.5px] font-semibold tabular-nums text-white/85">
                {(plan.techo ?? plan.base)?.formacion}
              </span>
            ) : null}
          </div>
          <p className="mt-2 flex flex-wrap items-baseline gap-x-2.5 tabular-nums">
            {hayPlan ? (
              <>
                <span className="text-[1.6rem] font-semibold leading-none tracking-[-0.03em] text-white/45">{points(plan.base?.total)}</span>
                <svg viewBox="0 0 20 12" className="h-3 w-5 self-center text-white/35" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
                  <path d="M1 6h17M13 1l5 5-5 5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                <span className="text-[3rem] font-semibold leading-none tracking-[-0.045em] text-white">{points(plan.techo?.total)}</span>
              </>
            ) : (
              <span className="text-[3rem] font-semibold leading-none tracking-[-0.045em] text-white">{plan.base ? points(plan.base.total) : "—"}</span>
            )}
            <span className="text-base font-medium text-white/55">xP</span>
          </p>
          <p className="mt-2 text-[13.5px] text-white/65">
            {hayPlan
              ? `Con ${plan.pasos.length === 1 ? "1 movimiento" : `${plan.pasos.length} movimientos`}`
              : "Nada en el mercado ni en cláusulas abiertas mejora tu once."}
          </p>
          {hayPlan ? (
            <div className="mt-4 grid grid-cols-3 gap-2.5">
              <HeroStat value={`+${points(mejora)}`} label="Mejora" tone={TONE.green} />
              <HeroStat value={compact(Math.round(plan.coste / 1_000_000) * 1_000_000)} label="Coste" />
              <HeroStat value={faltan(plan.primerCierre)} label="Cierra en" tone={urgente(plan.primerCierre) ? TONE.amber : undefined} />
            </div>
          ) : null}
          <p className="mt-3 text-[11.5px] leading-snug text-white/40">Estimado y sin mirar tu caja. El xP tiende a quedarse alto con los mejores jugadores.</p>
        </div>
      </section>

      {hayPlan ? (
        <Seccion titulo="Tu plan" nota="En orden: cada paso suma sobre el anterior.">
          <ul className="home-glass">
            {plan.pasos.map((m, index) => fila("plan", m.jugador, disponible(m.jugador), <Mejora m={m} />, <span className="plan-step">{index + 1}</span>))}
          </ul>
        </Seccion>
      ) : null}

      {plan.alternativas.length ? (
        <Seccion titulo="Alternativas" nota="Por si pierdes una puja: mejora de cada una por separado.">
          <ul className="home-glass">
            {plan.alternativas.map((m) => fila("alt", m.jugador, disponible(m.jugador), <Mejora m={m} />))}
          </ul>
        </Seccion>
      ) : null}

      {plan.fuera.length ? (
        <Seccion titulo="Fuera de tu once" nota={`Tuyos que no suman en ${etiquetaH}.`}>
          <ul className="home-glass">
            {plan.fuera.map((jugador) =>
              fila("fuera", jugador, jugador.valor ? `${jugador.posicion} · ${money(jugador.valor)}` : jugador.posicion, <Cifra value={points(valor(jugador, h))} label="xP" tone="rgba(255,255,255,0.7)" />, undefined, true),
            )}
          </ul>
        </Seccion>
      ) : null}

      <Seccion titulo={`Los mejores · ${etiquetaH}`}>
        <Switch<PlanificadorPosicion>
          label="Puesto"
          actual={puesto}
          opciones={POSICIONES.map((id): [PlanificadorPosicion, string] => [id, NOMBRE_PUESTO[id]])}
          onChange={(id) => {
            setPuesto(id);
            setVerMas(false);
            setAbierto(null);
          }}
        />
        <ul className="home-glass">
          {ranking
            .slice(0, verMas ? RANKING_LARGO : RANKING_CORTO)
            .map((jugador, index) => fila("rank", jugador, disponible(jugador), <Cifra value={points(valor(jugador, h))} label="xP" />, <span className="plan-rank">{index + 1}</span>, true))}
        </ul>
        {ranking.length > RANKING_CORTO ? (
          <button type="button" className="eq-chip self-center" onClick={() => setVerMas((v) => !v)}>
            {verMas ? "Ver menos" : `Ver más ${NOMBRE_PUESTO[puesto].toLowerCase()}`}
          </button>
        ) : null}
      </Seccion>

      {libres.length ? (
        <Seccion titulo="Libres a vigilar" nota="Sin dueño en tu liga. Por media de temporada, aún sin xP.">
          <ul className="eq-scroll -mx-1 px-1 pb-1">
            {libres.map((libre) => (
              <Libre key={libre.player_id} libre={libre} />
            ))}
          </ul>
        </Seccion>
      ) : null}
    </div>
  );
}
