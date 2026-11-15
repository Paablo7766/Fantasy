"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useDashboard } from "@/components/DashboardProvider";
import { Crest } from "@/components/ui/Crest";
import { ErrorCard } from "@/components/ui/Feedback";
import { Empty, Face, Skeleton, TONE, lastName, money, ringColor } from "@/components/ui/kit";
import { endpoint } from "@/lib/core/api";
import { points, titularFull } from "@/lib/core/format";
import { cachedJson, peekJson } from "@/lib/core/jsonCache";
import { POSICIONES, compensa, construirTablero, valor, ventaja, type Horizonte, type Liston } from "@/lib/equipo/planificador";
import type { PlanificadorJugador, PlanificadorLibre, PlanificadorPayload, PlanificadorPosicion } from "@/lib/types";

const NOMBRE_PUESTO: Record<PlanificadorPosicion, string> = { POR: "Porteros", DEF: "Defensas", MC: "Medios", DEL: "Delanteros" };
/** Mejora mínima sobre tu titular para pintarla en verde. */
const VENTAJA_VISIBLE = 0.1;

const madrid = new Intl.DateTimeFormat("es-ES", { timeZone: "Europe/Madrid", weekday: "short", day: "numeric" });
const madridHora = new Intl.DateTimeFormat("es-ES", { timeZone: "Europe/Madrid", weekday: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

function fecha(iso: string | null | undefined, conHora = false): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return (conHora ? madridHora : madrid).format(date).replace(/\./g, "");
}

function multiplo(value: number | null | undefined): string | null {
  return typeof value === "number" ? `×${value.toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : null;
}

function EstadoMedico({ estado }: { estado: "baja" | "duda" | null }) {
  if (!estado) return null;
  return (
    <span className="shrink-0 text-[11.5px] font-medium" style={{ color: estado === "baja" ? TONE.red : TONE.amber }}>
      {estado === "baja" ? "Baja" : "Duda"}
    </span>
  );
}

/** Dónde está y cuánto cuesta, en una línea corta. */
function disponible(jugador: PlanificadorJugador): string {
  if (jugador.dueno.tipo === "mio") return jugador.valor ? `${jugador.posicion} · ${money(jugador.valor)}` : jugador.posicion;
  if (jugador.mercado) return `Mercado · ${money(jugador.mercado.precio)}`;
  const c = jugador.clausula;
  if (!c) return jugador.dueno.nombre;
  if (c.estado === "abierta") return [`Cláusula ${money(c.eur)}`, multiplo(c.multiplo)].filter(Boolean).join(" ");
  if (c.estado === "bloqueada") return `Abre ${fecha(c.abre_at) ?? "más adelante"} · ${money(c.eur)}`;
  if (c.estado === "blindado") return "Blindado";
  return jugador.dueno.nombre;
}

const VEREDICTO = {
  rentable: { texto: "Rentable", color: TONE.green },
  justo: { texto: "Precio justo", color: "rgba(255,255,255,0.62)" },
  caro: { texto: "No rentable", color: TONE.amber },
} as const;

/** ¿Compensa ficharlo? En una línea: veredicto y lo que vale su xP. */
function Veredicto({ jugador }: { jugador: PlanificadorJugador }) {
  const r = jugador.rentabilidad;
  if (!r) return null;
  const v = VEREDICTO[r.veredicto];
  const quema = r.veredicto === "caro" && jugador.clausula?.cara && !jugador.mercado && jugador.clausula.prima_eur;
  return (
    <span className="mt-0.5 block truncate text-[12px]">
      <span className="font-medium" style={{ color: v.color }}>
        {v.texto}
      </span>
      <span className="text-white/40"> · {quema ? `quemas ${money(jugador.clausula?.prima_eur)}` : `vale ${money(r.valor_justo)}`}</span>
    </span>
  );
}

/** Explicación del veredicto para el detalle. */
function porQue(jugador: PlanificadorJugador, jornada: number | null): string | null {
  const r = jugador.rentabilidad;
  if (!r) return null;
  const xp = `Su xP${jornada ? ` de la J${jornada}` : ""} (${points(jugador.xp[0])}) vale unos ${money(r.valor_justo)} en esta liga y cuesta ${money(r.precio)}`;
  const margen = `${r.margen_pct > 0 ? "+" : ""}${Math.round(r.margen_pct)} %`;
  if (r.veredicto === "caro" && jugador.clausula?.cara && !jugador.mercado) {
    return `${xp}, pero la cláusula pasa de 1,25× su valor de mercado: pagas ${money(jugador.clausula.prima_eur)} que pierdes nada más ficharlo. No rentable.`;
  }
  if (r.veredicto === "rentable") return `${xp}: rentable (${margen}).`;
  if (r.veredicto === "justo") return `${xp}: precio justo (${margen}).`;
  return `${xp}: pagas más de lo que rinde (${margen}). No rentable.`;
}

/** Línea completa del detalle: dueño, fechas y, si es cara, lo que pagas de más. */
function contexto(jugador: PlanificadorJugador): string {
  if (jugador.dueno.tipo === "mio") return "Tuyo";
  if (jugador.mercado) {
    const cierra = fecha(jugador.mercado.cierra_at, true);
    return `En el mercado por ${money(jugador.mercado.precio)}${cierra ? `, cierra ${cierra}` : ""}.`;
  }
  const c = jugador.clausula;
  if (!c) return `De ${jugador.dueno.nombre}.`;
  const base =
    c.estado === "bloqueada"
      ? `De ${jugador.dueno.nombre}. Cláusula ${money(c.eur)}, se abre ${fecha(c.abre_at, true) ?? "más adelante"}`
      : c.estado === "blindado"
        ? `De ${jugador.dueno.nombre}. Blindado`
        : `De ${jugador.dueno.nombre}. Cláusula ${money(c.eur)}`;
  return `${base}.`;
}

function Detalle({ jugador, h, jornadas, sufijo }: { jugador: PlanificadorJugador; h: Horizonte; jornadas: Array<number | null>; sufijo: string }) {
  const explicacion = porQue(jugador, jornadas[0]);
  const accion = jugador.mercado
    ? { href: `/mercado${sufijo}`, label: "Pujar en Mercado" }
    : jugador.clausula && jugador.dueno.tipo === "rival" && jugador.clausula.estado !== "blindado"
      ? { href: `/clausulas${sufijo}`, label: "Ver en Cláusulas" }
      : null;
  return (
    <div className="row-in px-3.5 pb-3.5">
      <p className="text-[12.5px] leading-snug text-white/60">{contexto(jugador)}</p>
      {explicacion ? <p className="mt-1 text-[12.5px] leading-snug text-white/60">{explicacion}</p> : null}
      <div className="mb-2.5" />
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
  liston: Liston;
  abierto: boolean;
  onToggle: () => void;
  jornadas: Array<number | null>;
  sufijo: string;
  lead?: ReactNode;
};

function Fila({ jugador, h, liston, abierto, onToggle, jornadas, sufijo, lead }: FilaProps) {
  const nombre = jugador.nombre || "Jugador";
  const partido = h === "total" ? null : jugador.partidos[h];
  const mio = jugador.dueno.tipo === "mio";
  const extra = mio ? null : ventaja(jugador, liston, h);
  const rival = liston[jugador.posicion];
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
            <span className="truncate">{disponible(jugador)}</span>
          </span>
          <Veredicto jugador={jugador} />
        </span>
        <span className="shrink-0 text-right">
          <span className="block font-mono text-[1.05rem] font-semibold leading-none tabular-nums" style={{ color: mio ? "rgba(255,255,255,0.7)" : "#fff" }}>
            {points(valor(jugador, h))}
          </span>
          {extra !== null && extra >= VENTAJA_VISIBLE && rival ? (
            <span
              className="mt-1 block text-[11px] font-medium tabular-nums"
              style={{ color: TONE.green }}
              title={`${points(extra)} más que ${lastName(rival.nombre || "")}, tu peor ${rival.posicion} titular`}
            >
              +{points(extra)}
            </span>
          ) : (
            <span className="mt-1 block text-[11px] text-white/40">xP</span>
          )}
        </span>
      </button>
      {abierto ? <Detalle jugador={jugador} h={h} jornadas={jornadas} sufijo={sufijo} /> : null}
    </li>
  );
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

/** Tu titular más flojo por puesto. Cada casilla filtra la pantalla a ese puesto. */
function ListonCard({
  liston,
  h,
  puesto,
  onPuesto,
  etiqueta,
}: {
  liston: Liston;
  h: Horizonte;
  puesto: PlanificadorPosicion | null;
  onPuesto: (p: PlanificadorPosicion | null) => void;
  etiqueta: string;
}) {
  return (
    <section className="home-glass px-3 pb-3 pt-3.5" aria-label="Tu peor titular por puesto">
      <div className="flex items-baseline justify-between gap-3 px-1">
        <h2 className="text-[14px] font-semibold text-white">Tu peor titular · {etiqueta}</h2>
        {puesto ? (
          <button type="button" className="text-[12.5px] font-medium text-ember-strong" onClick={() => onPuesto(null)}>
            Ver todos
          </button>
        ) : (
          <span className="text-[11.5px] text-white/40">Toca para filtrar</span>
        )}
      </div>
      <div className="mt-2.5 grid grid-cols-4 gap-1.5">
        {POSICIONES.map((id) => {
          const jugador = liston[id];
          const on = puesto === id;
          return (
            <button key={id} type="button" aria-pressed={on} onClick={() => onPuesto(on ? null : id)} className={on ? "plan-day plan-day--on" : "plan-day"}>
              <span className="text-[10.5px] font-medium text-white/45">{id}</span>
              <span className="mt-1 w-full truncate px-0.5 text-[12px] text-white/75">{jugador ? lastName(jugador.nombre || "") : "—"}</span>
              <span className="mt-0.5 font-mono text-[15px] font-semibold tabular-nums text-white">{jugador ? points(valor(jugador, h)) : "—"}</span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function Switch<T extends string>({ opciones, actual, onChange, label }: { opciones: Array<[T, string]>; actual: T; onChange: (v: T) => void; label: string }) {
  return (
    <div className="desk-switch" style={{ gridTemplateColumns: `repeat(${opciones.length}, minmax(0, 1fr))` }} role="tablist" aria-label={label}>
      {opciones.map(([id, texto]) => (
        <button
          key={id}
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
  const [puesto, setPuesto] = useState<PlanificadorPosicion | null>(null);
  const [abierto, setAbierto] = useState<string | null>(null);
  const [verMas, setVerMas] = useState<Record<string, boolean>>({});
  const [filtro, setFiltro] = useState<"todos" | "compensan">("todos");

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
  const tablero = useMemo(() => construirTablero(jugadores, h), [jugadores, h]);

  if (loading && !payload) return <Skeleton />;
  if (!payload || payload.ok === false) {
    return <ErrorCard title="Planificador" payload={payload || { error: { message: "Sin datos." } }} brief />;
  }
  if (!jugadores.length) {
    return <Empty title="Sin xP de las próximas jornadas" detail="Pulsa Actualizar en Inicio para calcular la proyección." />;
  }

  const jornadas = payload.jornadas ?? [null, null, null, null];
  const etiquetaH = h === "total" ? `J${jornadas[0] ?? "?"}–J${jornadas[3] ?? "?"}` : `J${jornadas[h] ?? h + 1}`;
  const delPuesto = (lista: PlanificadorJugador[]) => (puesto ? lista.filter((j) => j.posicion === puesto) : lista);
  const libres = (payload.libres ?? []).filter((l) => l.estado !== "baja" && (!puesto || l.posicion === puesto)).slice(0, 12);
  const toggle = (id: string) => setAbierto((actual) => (actual === id ? null : id));
  const nombrePuesto = puesto ? NOMBRE_PUESTO[puesto].toLowerCase() : null;

  const lista = (clave: string, todos: PlanificadorJugador[], corto: number, numerar = false) => {
    const largo = Boolean(verMas[clave]);
    return (
      <>
        <ul className="home-glass">
          {todos.slice(0, largo ? 25 : corto).map((jugador, index) => (
            <Fila
              key={`${clave}-${jugador.player_id}`}
              jugador={jugador}
              h={h}
              liston={tablero.liston}
              abierto={abierto === `${clave}-${jugador.player_id}`}
              onToggle={() => toggle(`${clave}-${jugador.player_id}`)}
              jornadas={jornadas}
              sufijo={sufijo}
              lead={numerar ? <span className="plan-rank">{index + 1}</span> : undefined}
            />
          ))}
        </ul>
        {todos.length > corto ? (
          <button type="button" className="eq-chip self-center" onClick={() => setVerMas((v) => ({ ...v, [clave]: !largo }))}>
            {largo ? "Ver menos" : `Ver ${Math.min(todos.length, 25) - corto} más`}
          </button>
        ) : null}
      </>
    );
  };

  const deFiltro = (lista: PlanificadorJugador[]) => delPuesto(filtro === "compensan" ? lista.filter(compensa) : lista);
  const fichables = deFiltro(tablero.fichables);
  const porAbrir = deFiltro(tablero.porAbrir);
  const fuera = delPuesto(tablero.fuera);

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

      <ListonCard
        liston={tablero.liston}
        h={h}
        puesto={puesto}
        etiqueta={etiquetaH}
        onPuesto={(p) => {
          setPuesto(p);
          setAbierto(null);
          setVerMas({});
        }}
      />

      <Switch<"todos" | "compensan">
        label="Qué fichajes ver"
        actual={filtro}
        opciones={[
          ["todos", "Todos"],
          ["compensan", "Solo rentables"],
        ]}
        onChange={(v) => {
          setFiltro(v);
          setAbierto(null);
          setVerMas({});
        }}
      />

      <Seccion
        titulo={nombrePuesto ? `Fichables ahora · ${nombrePuesto}` : "Fichables ahora"}
        nota="Mercado y cláusulas abiertas, por xP. Rentable = su xP vale más de lo que cuesta."
      >
        {fichables.length ? (
          lista("fichables", fichables, 8, true)
        ) : (
          <p className="rounded-[1.5rem] bg-white/[0.04] px-4 py-4 text-[13.5px] text-white/50">{filtro === "compensan" ? "Nada rentable" : "Nada fichable"} ahora{nombrePuesto ? ` en ${nombrePuesto}` : ""}.</p>
        )}
      </Seccion>

      {porAbrir.length ? (
        <Seccion titulo="Cláusulas que se abren" nota="Aún bloqueadas: apunta la fecha.">
          {lista("abrir", porAbrir, 5)}
        </Seccion>
      ) : null}

      {fuera.length ? (
        <Seccion titulo="Tuyos fuera del once" nota={`No te suman en ${etiquetaH}.`}>
          {lista("fuera", fuera, 6)}
        </Seccion>
      ) : null}

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
