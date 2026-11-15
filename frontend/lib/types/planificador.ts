// Planificador de jornada (`/api/planificador`).
import type { ApiError, PhotoMeta } from "./common";

export type PlanificadorPosicion = "POR" | "DEF" | "MC" | "DEL";

export type PlanificadorPartido = {
  rival: string | null;
  casa: boolean | null;
  dificultad: string | null;
  p_victoria: number | null;
  saque: string | null;
};

export type PlanificadorDueno = {
  tipo: "mio" | "rival" | "mercado" | "libre";
  nombre: string;
  team_id: string | null;
};

export type PlanificadorClausula = {
  eur: number;
  multiplo: number | null;
  estado: "abierta" | "bloqueada" | "blindado" | "sin_dato";
  abre_at: string | null;
};

export type PlanificadorJugador = {
  player_id: string;
  nombre: string | null;
  posicion: PlanificadorPosicion;
  club: string | null;
  image_url: string | null;
  /** xP de las 4 próximas jornadas, la primera es la próxima. */
  xp: Array<number | null>;
  xp_total: number | null;
  techo: number | null;
  si_juega: number | null;
  p_titular: number | null;
  estado: "baja" | "duda" | null;
  media: number | null;
  valor: number | null;
  partidos: Array<PlanificadorPartido | null>;
  dueno: PlanificadorDueno;
  mercado: { precio: number | null; cierra_at: string | null } | null;
  clausula: PlanificadorClausula | null;
};

export type PlanificadorPayload = ApiError &
  PhotoMeta & {
    ok?: boolean;
    jornada?: number | null;
    jornadas?: Array<number | null>;
    generado_at?: string;
    dashboard_at?: string | null;
    managers?: Array<{ team_id: string | null; nombre: string; es_mio: boolean }>;
    jugadores?: PlanificadorJugador[];
    nota?: string;
  };
