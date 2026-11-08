/** Jornada en juego (``plan_fichajes.jornada_en_juego``): radiografía en vivo de tu once y del de cada rival. */

export type EstadoPartidoLive = "jugado" | "en_juego" | "pendiente";

export interface LiveJugador {
  player_id?: string | null;
  nombre?: string | null;
  posicion?: string | null;
  club?: string | null;
  estado: EstadoPartidoLive;
  puntos?: number | null;
  minutos?: number | null;
  xp: number;
  saque?: string | null;
  sin_acta?: boolean;
  no_jugo?: boolean;
  rosco?: boolean;
  explosion?: boolean;
}

export interface LiveEquipo {
  team_id?: string | null;
  manager?: string | null;
  is_self: boolean;
  rank_tabla?: number | null;
  puntos_tabla?: number | null;
  caja_eur?: number | null;
  formacion?: string | null;
  once_completo?: boolean;
  jugadores_jugados: number;
  jugadores_en_juego: number;
  jugadores_pendientes: number;
  resumen_jugados: string;
  puntos_actuales: number;
  xp_pendiente: number;
  puntos_proyectados_final_jornada: number;
  sin_acta?: number;
  saldo_negativo?: boolean;
  premio_jornada_eur: number;
  premio_ya_firme_eur?: number;
  caja_proyectada_lunes_eur?: number | null;
  puesto_jornada: number;
  puntos_tabla_proyectados?: number | null;
  puesto_tabla_proyectado?: number | null;
  dif_jornada_vs_ti?: number;
  dif_tabla_vs_ti?: number | null;
  recorte_vs_lider?: number;
  recorte_tabla_vs_lider?: number;
  once?: LiveJugador[];
  pendientes?: LiveJugador[];
  roscos?: LiveJugador[];
  explosiones?: LiveJugador[];
}

export interface JornadaEnJuego {
  activa: boolean;
  jornada?: number;
  inicio?: string;
  ultimo_saque?: string | null;
  euros_por_punto?: number;
  abono_jornada_eur?: number;
  nota?: string;
  resumen?: string;
  clasificacion_jornada?: LiveEquipo[];
  clasificacion_tabla?: LiveEquipo[];
  rivales_directos?: LiveEquipo[];
  lider?: LiveEquipo | null;
  propio?: LiveEquipo | null;
  liquidez_entrante_eur?: number;
}
