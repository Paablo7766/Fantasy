// Lógica pura del Planificador: mejor once legal, movimientos y plan encadenado.
import type { PlanificadorJugador, PlanificadorPosicion } from "@/lib/types";

/** 0–3 = una jornada; «total» = las cuatro sumadas. */
export type Horizonte = 0 | 1 | 2 | 3 | "total";

export const POSICIONES: PlanificadorPosicion[] = ["POR", "DEF", "MC", "DEL"];
const FORMACIONES: Array<[number, number, number]> = [
  [3, 4, 3],
  [3, 5, 2],
  [4, 3, 3],
  [4, 4, 2],
  [4, 5, 1],
  [5, 3, 2],
  [5, 4, 1],
];
export const MOVIMIENTOS = 3;
export const MEJORA_MINIMA = 0.3;

export function valor(jugador: PlanificadorJugador, h: Horizonte): number | null {
  return h === "total" ? jugador.xp_total : (jugador.xp[h] ?? null);
}

export type Once = { total: number; ids: Set<string>; formacion: string };

/** Mejor once legal (1 POR y una formación del juego) con lo que haya en ``pool``. */
export function mejorOnce(pool: PlanificadorJugador[], h: Horizonte): Once | null {
  const porPuesto: Record<PlanificadorPosicion, PlanificadorJugador[]> = { POR: [], DEF: [], MC: [], DEL: [] };
  for (const jugador of pool) if (valor(jugador, h) !== null) porPuesto[jugador.posicion].push(jugador);
  for (const puesto of POSICIONES) porPuesto[puesto].sort((a, b) => (valor(b, h) ?? 0) - (valor(a, h) ?? 0));
  let mejor: Once | null = null;
  for (const [def, mc, del] of FORMACIONES) {
    const cupo: Record<PlanificadorPosicion, number> = { POR: 1, DEF: def, MC: mc, DEL: del };
    if (POSICIONES.some((puesto) => porPuesto[puesto].length < cupo[puesto])) continue;
    const elegidos = POSICIONES.flatMap((puesto) => porPuesto[puesto].slice(0, cupo[puesto]));
    const total = elegidos.reduce((suma, jugador) => suma + (valor(jugador, h) ?? 0), 0);
    if (!mejor || total > mejor.total) mejor = { total, ids: new Set(elegidos.map((j) => j.player_id)), formacion: `${def}-${mc}-${del}` };
  }
  return mejor;
}

export type Via = "mercado" | "clausula";

export type Movimiento = {
  jugador: PlanificadorJugador;
  /** Lo que sube el mejor once al entrar. */
  mejora: number;
  /** A quién deja fuera del once. */
  sale: PlanificadorJugador | null;
  via: Via;
  /** Precio de mercado o importe de la cláusula. */
  coste: number | null;
};

function viaDe(jugador: PlanificadorJugador): Via {
  return jugador.mercado ? "mercado" : "clausula";
}

function costeDe(jugador: PlanificadorJugador): number | null {
  return jugador.mercado ? (jugador.mercado.precio ?? jugador.valor) : (jugador.clausula?.eur ?? null);
}

function mover(pool: PlanificadorJugador[], base: Once, candidato: PlanificadorJugador, h: Horizonte): Movimiento | null {
  if (valor(candidato, h) === null) return null;
  const nuevo = mejorOnce([...pool, candidato], h);
  if (!nuevo || !nuevo.ids.has(candidato.player_id)) return null;
  const sale = pool.find((j) => base.ids.has(j.player_id) && !nuevo.ids.has(j.player_id)) ?? null;
  return { jugador: candidato, mejora: nuevo.total - base.total, sale, via: viaDe(candidato), coste: costeDe(candidato) };
}

export type Plan = {
  mios: PlanificadorJugador[];
  base: Once | null;
  /** Mejor once tras encadenar los pasos. */
  techo: Once | null;
  /** Movimientos encadenados, cada uno con su mejora sobre el anterior. */
  pasos: Movimiento[];
  /** Otros movimientos sueltos que también mejoran el once (fuera del plan). */
  alternativas: Movimiento[];
  /** Tuyos que no entran en tu mejor once. */
  fuera: PlanificadorJugador[];
  coste: number;
  /** Cierre de mercado más cercano entre los pasos. */
  primerCierre: string | null;
};

/** Plan de hasta ``MOVIMIENTOS`` fichajes o cláusulas, sin mirar la caja. */
export function construirPlan(jugadores: PlanificadorJugador[], h: Horizonte): Plan {
  const mios = jugadores.filter((j) => j.dueno.tipo === "mio");
  const base = mejorOnce(mios, h);
  const candidatos = jugadores.filter(
    (j) => j.dueno.tipo !== "mio" && (j.mercado !== null || (j.dueno.tipo === "rival" && j.clausula?.estado === "abierta")),
  );
  const fuera = base ? mios.filter((j) => !base.ids.has(j.player_id)).sort((a, b) => (valor(b, h) ?? 0) - (valor(a, h) ?? 0)) : [];
  if (!base) return { mios, base, techo: null, pasos: [], alternativas: [], fuera, coste: 0, primerCierre: null };

  const sueltos = candidatos
    .map((j) => mover(mios, base, j, h))
    .filter((m): m is Movimiento => m !== null && m.mejora >= MEJORA_MINIMA)
    .sort((a, b) => b.mejora - a.mejora);

  let pool = [...mios];
  let techo = base;
  const pasos: Movimiento[] = [];
  const usados = new Set<string>();
  for (let paso = 0; paso < MOVIMIENTOS; paso += 1) {
    const actual = techo;
    const mejor = sueltos
      .filter((m) => !usados.has(m.jugador.player_id))
      .map((m) => mover(pool, actual, m.jugador, h))
      .filter((m): m is Movimiento => m !== null && m.mejora >= MEJORA_MINIMA)
      .sort((a, b) => b.mejora - a.mejora)[0];
    if (!mejor) break;
    usados.add(mejor.jugador.player_id);
    pool = [...pool, mejor.jugador];
    techo = mejorOnce(pool, h) ?? actual;
    pasos.push(mejor);
  }

  const coste = pasos.reduce((suma, m) => suma + (m.coste ?? 0), 0);
  const cierres = pasos
    .map((m) => m.jugador.mercado?.cierra_at)
    .filter((iso): iso is string => Boolean(iso))
    .sort((a, b) => new Date(a).getTime() - new Date(b).getTime());
  const alternativas = sueltos.filter((m) => !usados.has(m.jugador.player_id)).slice(0, 4);
  return { mios, base, techo, pasos, alternativas, fuera, coste, primerCierre: cierres[0] ?? null };
}
