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
import type { PlanificadorJugador, PlanificadorLibre, PlanificadorPartido, PlanificadorPayload, PlanificadorPosicion } from "@/lib/types";

/** 0–3 = una jornada; «total» = las cuatro sumadas. */
type Horizonte = 0 | 1 | 2 | 3 | "total";

const POSICIONES: PlanificadorPosicion[] = ["POR", "DEF", "MC", "DEL"];
const NOMBRE_PUESTO: Record<PlanificadorPosicion, string> = { POR: "Porteros", DEF: "Defensas", MC: "Medios", DEL: "Delanteros" };
const FORMACIONES: Array<[number, number, number]> = [
  [3, 4, 3],
  [3, 5, 2],
  [4, 3, 3],
  [4, 4, 2],
  [4, 5, 1],
  [5, 3, 2],
  [5, 4, 1],
];
const MOVIMIENTOS = 3;
const MEJORA_MINIMA = 0.3;

function valor(jugador: PlanificadorJugador, h: Horizonte): number | null {
  return h === "total" ? jugador.xp_total : (jugador.xp[h] ?? null);
}

type Once = { total: number; ids: Set<string> } | null;

/** Mejor once legal (1 POR y una formación del juego) con lo que haya en ``pool``. */
function mejorOnce(pool: PlanificadorJugador[], h: Horizonte): Once {
  const porPuesto: Record<PlanificadorPosicion, PlanificadorJugador[]> = { POR: [], DEF: [], MC: [], DEL: [] };
  for (const jugador of pool) if (valor(jugador, h) !== null) porPuesto[jugador.posicion].push(jugador);
  for (const puesto of POSICIONES) porPuesto[puesto].sort((a, b) => (valor(b, h) ?? 0) - (valor(a, h) ?? 0));
  let mejor: Once = null;
  for (const [def, mc, del] of FORMACIONES) {
    const cupo: Record<PlanificadorPosicion, number> = { POR: 1, DEF: def, MC: mc, DEL: del };
    if (POSICIONES.some((puesto) => porPuesto[puesto].length < cupo[puesto])) continue;
    const elegidos = POSICIONES.flatMap((puesto) => porPuesto[puesto].slice(0, cupo[puesto]));
    const total = elegidos.reduce((suma, jugador) => suma + (valor(jugador, h) ?? 0), 0);
    if (!mejor || total > mejor.total) mejor = { total, ids: new Set(elegidos.map((j) => j.player_id)) };
  }
  return mejor;
}

type Movimiento = { jugador: PlanificadorJugador; mejora: number; sale: PlanificadorJugador | null };

/** Cuánto sube tu mejor once si entra ``candidato``, y a quién deja fuera. */
function movimiento(mios: PlanificadorJugador[], base: Once, candidato: PlanificadorJugador, h: Horizonte): Movimiento | null {
  if (!base || valor(candidato, h) === null) return null;
  const nuevo = mejorOnce([...mios, candidato], h);
  if (!nuevo || !nuevo.ids.has(candidato.player_id)) return null;
  const mejora = nuevo.total - base.total;
  const sale = mios.find((j) => base.ids.has(j.player_id) && !nuevo.ids.has(j.player_id)) ?? null;
  return { jugador: candidato, mejora, sale };
}

const madrid = new Intl.DateTimeFormat("es-ES", { timeZone: "Europe/Madrid", weekday: "short", day: "numeric", month: "short" });
const madridHora = new Intl.DateTimeFormat("es-ES", { timeZone: "Europe/Madrid", weekday: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

function fecha(iso: string | null | undefined, conHora = false): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return (conHora ? madridHora : madrid).format(date).replace(/\./g, "");
}

function Rival({ partido }: { partido: PlanificadorPartido | null | undefined }) {
  if (!partido?.rival) return null;
  return (
    <span className="inline-flex min-w-0 items-center gap-1">
      <span className="shrink-0 text-white/35">{partido.casa === false ? "en" : "vs"}</span>
      <Crest club={partido.rival} size={14} />
      <span className="truncate">{partido.rival}</span>
    </span>
  );
}

/** Cómo conseguirlo, en una línea. */
function comoConseguirlo(jugador: PlanificadorJugador): string {
  if (jugador.dueno.tipo === "mio") return "Tuyo";
  if (jugador.mercado) {
    const cierra = fecha(jugador.mercado.cierra_at, true);
    return `Mercado · ${money(jugador.mercado.precio)}${cierra ? ` · cierra ${cierra}` : ""}`;
  }
  const c = jugador.clausula;
  if (c?.estado === "abierta") return `Cláusula ${money(c.eur)} · ${jugador.dueno.nombre}`;
  if (c?.estado === "bloqueada") return `${jugador.dueno.nombre} · cláusula se abre ${fecha(c.abre_at, true) ?? "más adelante"}`;
  if (c?.estado === "blindado") return `${jugador.dueno.nombre} · blindado`;
  return jugador.dueno.nombre;
}

function Detalle({ jugador, jornadas, sufijo }: { jugador: PlanificadorJugador; jornadas: Array<number | null>; sufijo: string }) {
  const accion = jugador.mercado ? { href: `/mercado${sufijo}`, label: "Ir a Mercado" } : jugador.clausula?.estado === "abierta" || jugador.clausula?.estado === "bloqueada" ? { href: `/clausulas${sufijo}`, label: "Ir a Cláusulas" } : null;
  return (
    <div className="row-in px-4 pb-4">
      <ul className="grid grid-cols-4 gap-1.5">
        {jugador.partidos.map((partido, index) => (
          <li key={index} className="flex min-w-0 flex-col items-center rounded-2xl bg-black/30 px-1 py-2.5 text-center">
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

function FilaJugador({
  jugador,
  h,
  abierto,
  onToggle,
  jornadas,
  sufijo,
  derecha,
  linea,
}: {
  jugador: PlanificadorJugador;
  h: Horizonte;
  abierto: boolean;
  onToggle: () => void;
  jornadas: Array<number | null>;
  sufijo: string;
  derecha: ReactNode;
  linea: string;
}) {
  const nombre = jugador.nombre || "Jugador";
  const partido = h === "total" ? jugador.partidos[0] : jugador.partidos[h];
  return (
    <li>
      <button type="button" aria-expanded={abierto} className="flex w-full items-center gap-3 px-3 py-3 text-left" onClick={onToggle}>
        <Face name={nombre} src={jugador.image_url} size={40} ring={ringColor(jugador.p_titular)} />
        <span className="min-w-0 flex-1">
          <span className="flex min-w-0 items-center gap-1.5">
            <Crest club={jugador.club} size={15} />
            <span className="truncate text-[15px] font-medium leading-tight text-white">{lastName(nombre)}</span>
            {jugador.estado ? (
              <span className="shrink-0 text-[11.5px] font-medium" style={{ color: jugador.estado === "baja" ? TONE.red : TONE.amber }}>
                {jugador.estado === "baja" ? "Baja" : "Duda"}
              </span>
            ) : null}
          </span>
          <span className="mt-1 flex min-w-0 items-center gap-1.5 text-[12px] text-white/45">
            <span className="shrink-0">{jugador.posicion}</span>
            {partido?.rival && h !== "total" ? (
              <>
                <span className="text-white/20">·</span>
                <Rival partido={partido} />
              </>
            ) : null}
          </span>
          <span className="mt-0.5 block truncate text-[12px] text-white/55">{linea}</span>
        </span>
        <span className="shrink-0 text-right">{derecha}</span>
      </button>
      {abierto ? <Detalle jugador={jugador} jornadas={jornadas} sufijo={sufijo} /> : null}
    </li>
  );
}

function Mejora({ m }: { m: Movimiento }) {
  return (
    <>
      <span className="block font-mono text-[1.05rem] font-semibold leading-none tabular-nums" style={{ color: TONE.green }}>
        +{points(m.mejora)}
      </span>
      <span className="mt-1 block max-w-[5.5rem] truncate text-[11px] text-white/40">{m.sale ? `por ${lastName(m.sale.nombre || "")}` : "al once"}</span>
    </>
  );
}

function Libre({ libre }: { libre: PlanificadorLibre }) {
  const nombre = libre.nombre || "Jugador";
  return (
    <li className="flex w-[8.5rem] shrink-0 flex-col items-center rounded-[1.25rem] bg-[#1c1c1e] px-3 py-3.5 text-center">
      <Face name={nombre} src={libre.image_url} size={48} />
      <span className="mt-2 flex w-full min-w-0 items-center justify-center gap-1">
        <Crest club={libre.club} size={13} />
        <span className="truncate text-[13.5px] font-medium text-white">{lastName(nombre)}</span>
      </span>
      <span className="mt-0.5 text-[11.5px] text-white/40">
        {libre.posicion}
        {libre.estado ? <span style={{ color: libre.estado === "baja" ? TONE.red : TONE.amber }}> · {libre.estado === "baja" ? "Baja" : "Duda"}</span> : null}
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
    </li>
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

  const plan = useMemo(() => {
    const mios = jugadores.filter((j) => j.dueno.tipo === "mio");
    const base = mejorOnce(mios, h);
    const evaluar = (lista: PlanificadorJugador[]) =>
      lista
        .map((j) => movimiento(mios, base, j, h))
        .filter((m): m is Movimiento => m !== null && m.mejora >= MEJORA_MINIMA)
        .sort((a, b) => b.mejora - a.mejora);
    const mercado = evaluar(jugadores.filter((j) => j.dueno.tipo !== "mio" && j.mercado !== null));
    const clausulas = evaluar(jugadores.filter((j) => j.dueno.tipo === "rival" && !j.mercado && j.clausula?.estado === "abierta"));
    // Techo con los mejores movimientos encadenados (sin mirar caja).
    let pool = [...mios];
    let techo = base;
    const usados = new Set<string>();
    for (let paso = 0; paso < MOVIMIENTOS && techo; paso += 1) {
      const actual = techo;
      const siguiente = [...mercado, ...clausulas]
        .filter((m) => !usados.has(m.jugador.player_id))
        .map((m) => ({ jugador: m.jugador, once: mejorOnce([...pool, m.jugador], h) }))
        .filter((x) => x.once && x.once.total - actual.total >= MEJORA_MINIMA)
        .sort((a, b) => (b.once?.total ?? 0) - (a.once?.total ?? 0))[0];
      if (!siguiente?.once) break;
      usados.add(siguiente.jugador.player_id);
      pool = [...pool, siguiente.jugador];
      techo = siguiente.once;
    }
    return { base, mercado: mercado.slice(0, 3), clausulas: clausulas.slice(0, 3), techo, pasos: usados.size };
  }, [jugadores, h]);

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

  const bloque = (titulo: string, lista: Movimiento[], vacio: string) => (
    <section className="flex flex-col gap-2.5" aria-label={titulo}>
      <h2 className="px-1 text-[1.05rem] font-semibold tracking-tight text-white">{titulo}</h2>
      {lista.length ? (
        <ul className="home-glass">
          {lista.map((m) => (
            <FilaJugador
              key={m.jugador.player_id}
              jugador={m.jugador}
              h={h}
              abierto={abierto === `${titulo}-${m.jugador.player_id}`}
              onToggle={() => toggle(`${titulo}-${m.jugador.player_id}`)}
              jornadas={jornadas}
              sufijo={sufijo}
              linea={comoConseguirlo(m.jugador)}
              derecha={<Mejora m={m} />}
            />
          ))}
        </ul>
      ) : (
        <p className="rounded-[1.5rem] bg-[#141414] px-4 py-4 text-[13.5px] text-white/50">{vacio}</p>
      )}
    </section>
  );

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <div className="desk-switch !grid-cols-5" role="tablist" aria-label="Jornada">
        {([0, 1, 2, 3, "total"] as Horizonte[]).map((opcion) => (
          <button
            key={String(opcion)}
            type="button"
            role="tab"
            aria-selected={h === opcion}
            className={h === opcion ? "desk-switch__btn desk-switch__btn--on" : "desk-switch__btn"}
            onClick={() => {
              setH(opcion);
              setAbierto(null);
            }}
          >
            {opcion === "total" ? "4 J" : `J${jornadas[opcion] ?? opcion + 1}`}
          </button>
        ))}
      </div>

      <section className="home-feature" aria-label="Tu once">
        <div className="relative">
          <p className="text-[13px] font-medium text-white/60">Tu mejor once · {etiquetaH}</p>
          <p className="mt-2 flex items-baseline gap-1.5 tabular-nums">
            <span className="text-[3rem] font-semibold leading-none tracking-[-0.045em] text-white">{plan.base ? points(plan.base.total) : "—"}</span>
            <span className="text-base font-medium text-white/55">xP</span>
          </p>
          <p className="mt-3 text-[14px] leading-snug text-white/70">
            {plan.pasos > 0 && mejora >= MEJORA_MINIMA ? (
              <>
                Con {plan.pasos === 1 ? "1 movimiento" : `${plan.pasos} movimientos`} llegas a{" "}
                <span className="font-semibold text-white tabular-nums">{points(plan.techo?.total)}</span>{" "}
                <span className="font-semibold tabular-nums" style={{ color: TONE.green }}>
                  (+{points(mejora)})
                </span>
              </>
            ) : (
              "Nada en el mercado ni en cláusulas abiertas mejora tu once ahora mismo."
            )}
          </p>
        </div>
      </section>

      {bloque("Fichar del mercado", plan.mercado, `Nadie en el mercado mejora tu once para ${etiquetaH}.`)}
      {bloque("Clausular", plan.clausulas, `Ninguna cláusula abierta mejora tu once para ${etiquetaH}.`)}

      {libres.length ? (
        <section className="flex flex-col gap-2.5" aria-label="Libres a vigilar">
          <div className="px-1">
            <h2 className="text-[1.05rem] font-semibold tracking-tight text-white">Vigilar cuando salgan al mercado</h2>
            <p className="mt-0.5 text-[12.5px] text-white/45">No son de nadie en tu liga. Por media de temporada; aún sin xP.</p>
          </div>
          <ul className="eq-scroll -mx-1 px-1 pb-1">
            {libres.map((libre) => (
              <Libre key={libre.player_id} libre={libre} />
            ))}
          </ul>
        </section>
      ) : null}

      <section className="flex flex-col gap-2.5" aria-label="Los mejores por puesto">
        <div className="flex items-baseline justify-between gap-3 px-1">
          <h2 className="text-[1.05rem] font-semibold tracking-tight text-white">Los mejores · {etiquetaH}</h2>
        </div>
        <div className="desk-switch !grid-cols-4" role="tablist" aria-label="Puesto">
          {POSICIONES.map((id) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={puesto === id}
              className={puesto === id ? "desk-switch__btn desk-switch__btn--on" : "desk-switch__btn"}
              onClick={() => {
                setPuesto(id);
                setVerMas(false);
                setAbierto(null);
              }}
            >
              {NOMBRE_PUESTO[id]}
            </button>
          ))}
        </div>
        <ul className="home-glass">
          {ranking.slice(0, verMas ? 25 : 8).map((jugador) => (
            <FilaJugador
              key={jugador.player_id}
              jugador={jugador}
              h={h}
              abierto={abierto === `rank-${jugador.player_id}`}
              onToggle={() => toggle(`rank-${jugador.player_id}`)}
              jornadas={jornadas}
              sufijo={sufijo}
              linea={comoConseguirlo(jugador)}
              derecha={
                <>
                  <span className="block font-mono text-[1.05rem] font-semibold leading-none tabular-nums text-white">{points(valor(jugador, h))}</span>
                  <span className="mt-1 block text-[11px] text-white/40">xP</span>
                </>
              }
            />
          ))}
        </ul>
        {ranking.length > 8 && !verMas ? (
          <button type="button" className="eq-chip self-center" onClick={() => setVerMas(true)}>
            Ver más {NOMBRE_PUESTO[puesto].toLowerCase()}
          </button>
        ) : null}
      </section>

      <p className="px-1 text-[12px] leading-relaxed text-white/40">
        El número en verde es lo que sube tu mejor once si entra ese jugador, y «por» dice a quién sustituye. Precios y cláusulas sin mirar tu caja: decide la puja en Mercado y el pago en Cláusulas.
      </p>
    </div>
  );
}
