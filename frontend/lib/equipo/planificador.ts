// Lógica pura del Planificador: clasifica jugadores por xP y disponibilidad. No arma planes.
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

export function valor(jugador: PlanificadorJugador, h: Horizonte): number | null {
  return h === "total" ? jugador.xp_total : (jugador.xp[h] ?? null);
}

/** Mejor once legal (1 POR y una formación del juego) con tu plantilla. */
function mejorOnce(pool: PlanificadorJugador[], h: Horizonte): PlanificadorJugador[] | null {
  const porPuesto: Record<PlanificadorPosicion, PlanificadorJugador[]> = { POR: [], DEF: [], MC: [], DEL: [] };
  for (const jugador of pool) if (valor(jugador, h) !== null) porPuesto[jugador.posicion].push(jugador);
  for (const puesto of POSICIONES) porPuesto[puesto].sort((a, b) => (valor(b, h) ?? 0) - (valor(a, h) ?? 0));
  let mejor: { total: number; once: PlanificadorJugador[] } | null = null;
  for (const [def, mc, del] of FORMACIONES) {
    const cupo: Record<PlanificadorPosicion, number> = { POR: 1, DEF: def, MC: mc, DEL: del };
    if (POSICIONES.some((puesto) => porPuesto[puesto].length < cupo[puesto])) continue;
    const once = POSICIONES.flatMap((puesto) => porPuesto[puesto].slice(0, cupo[puesto]));
    const total = once.reduce((suma, jugador) => suma + (valor(jugador, h) ?? 0), 0);
    if (!mejor || total > mejor.total) mejor = { total, once };
  }
  return mejor?.once ?? null;
}

/** Tu titular más flojo en cada puesto: el listón que tiene que superar un fichaje. */
export type Liston = Record<PlanificadorPosicion, PlanificadorJugador | null>;

export type Tablero = {
  liston: Liston;
  /** Mercado y cláusulas abiertas a precio razonable. */
  fichables: PlanificadorJugador[];
  /** Cláusulas a precio razonable que aún están bloqueadas. */
  porAbrir: PlanificadorJugador[];
  /** Cláusulas por encima de lo que compensa pagar (regla del asesor de cláusulas). */
  caras: PlanificadorJugador[];
  /** Tuyos que no entran en tu mejor once. */
  fuera: PlanificadorJugador[];
};

export function construirTablero(jugadores: PlanificadorJugador[], h: Horizonte): Tablero {
  const conXp = jugadores.filter((j) => valor(j, h) !== null);
  const porXp = (a: PlanificadorJugador, b: PlanificadorJugador) => (valor(b, h) ?? 0) - (valor(a, h) ?? 0);
  const mios = conXp.filter((j) => j.dueno.tipo === "mio");
  const once = mejorOnce(mios, h);
  const ids = new Set((once ?? []).map((j) => j.player_id));
  const liston: Liston = { POR: null, DEF: null, MC: null, DEL: null };
  for (const jugador of once ?? []) {
    const actual = liston[jugador.posicion];
    if (!actual || (valor(jugador, h) ?? 0) < (valor(actual, h) ?? 0)) liston[jugador.posicion] = jugador;
  }
  const ajenos = conXp.filter((j) => j.dueno.tipo !== "mio");
  const conClausula = ajenos.filter((j) => !j.mercado && j.dueno.tipo === "rival" && j.clausula);
  return {
    liston,
    fichables: ajenos.filter((j) => j.mercado || (j.clausula?.estado === "abierta" && !j.clausula.cara && j.dueno.tipo === "rival")).sort(porXp),
    porAbrir: conClausula.filter((j) => j.clausula?.estado === "bloqueada" && !j.clausula.cara).sort(porXp),
    caras: conClausula.filter((j) => (j.clausula?.estado === "abierta" || j.clausula?.estado === "bloqueada") && j.clausula.cara).sort(porXp),
    fuera: once ? mios.filter((j) => !ids.has(j.player_id)).sort(porXp) : [],
  };
}

/** Puntos que saca a tu titular más flojo de su puesto (negativo = no lo mejora). */
export function ventaja(jugador: PlanificadorJugador, liston: Liston, h: Horizonte): number | null {
  const rival = liston[jugador.posicion];
  const propio = valor(jugador, h);
  if (!rival || propio === null) return null;
  return propio - (valor(rival, h) ?? 0);
}
