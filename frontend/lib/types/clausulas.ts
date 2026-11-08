// Asesor de cláusulas: tus jugadores en peligro y los clausulazos.

export type NivelClausula = {
  clausula_objetivo: number;
  subida_eur: number;
  coste_eur: number;
  caja_tras: number | null;
  rivales_cubiertos: number;
  rivales_sin_cubrir: number;
  rivales_fuera?: number;
  recortado_por_tope?: boolean;
  viable: boolean;
};

export type VeredictoProteger =
  | "PROTEGER_YA"
  | "PROTEGER_PARCIAL"
  | "SIN_CAJA"
  | "VENDER_ANTES"
  | "ASUMIR"
  | "SOBREPROTEGIDO"
  /** Único jugador posible en su puesto: si te lo roban no hay once legal. */
  | "SIN_RECAMBIO";

export type VeredictoClausulazo = "CLAUSULAR_YA" | "PROGRAMAR" | "SIN_CAJA" | "OPORTUNIDAD" | "GOLPE_RIVAL";

export type BonoRoscoRival = {
  activo: boolean;
  rival?: string | null;
  puesto_liga: number;
  sin_recambio: boolean;
  sanos_tras: number;
  impacto_pts: number;
  mensaje: string;
};

export type ClausulaEnPeligro = {
  /** Candado toda la jornada: no se puede pagar aún, pero conviene dejar la cláusula puesta antes. */
  en_candado?: boolean;
  player_id: string;
  nombre: string;
  posicion?: string | null;
  en_xi: boolean;
  xp_jornada?: number | null;
  tu_once_pierde_sin_el: number;
  valor_mercado?: number | null;
  clausula_actual: number;
  multiplo_clausula?: number | null;
  prevision_7d_pct?: number | null;
  riesgo: "ALTO" | "MEDIO" | "BAJO";
  rivales_que_pueden_pagar: number;
  rivales_total: number;
  rival_mas_rico?: { manager?: string | null; caja: number } | null;
  necesitan_su_posicion: string[];
  bloqueada_hasta?: string | null;
  clausula_perfecta?: NivelClausula | null;
  subida_recomendada?: NivelClausula | null;
  niveles: NivelClausula[];
  exposicion_eur: number;
  expuesta_desde?: string | null;
  expuesta_cuando?: string | null;
  /** Sin él la plantilla no puede alinear un once legal. */
  sin_recambio?: boolean;
  /** Sin recambio, cláusula frágil, un rival puede pagarla y se abre antes del próximo bloqueo. */
  alerta_prioritaria?: boolean;
  abre_at?: string | null;
  /** «15-nov», «abierta» o null. */
  abre_el?: string | null;
  recambio_sugerido?: RecambioSugerido | null;
  veredicto_codigo: VeredictoProteger;
  veredicto_titulo: string;
  motivos: string[];
  motivo_detallado: string;
};

export type RecambioSugerido = {
  player_id?: string | null;
  nombre?: string | null;
  posicion?: string | null;
  coste?: number | null;
  xp?: number | null;
};

export type AlertaPrioritaria = {
  player_id: string;
  nombre: string;
  posicion?: string | null;
  abre_el?: string | null;
  abre_at?: string | null;
  clausula: number;
  rival_mas_rico?: { manager?: string | null; caja: number } | null;
  recambio_sugerido?: RecambioSugerido | null;
  accion: string;
};

export type ClausulazoSugerido = {
  player_id: string;
  nombre: string;
  posicion?: string | null;
  propietario?: string | null;
  clausula_eur: number;
  valor_mercado?: number | null;
  valor_justo?: number | null;
  margen_valor_justo_pct?: number | null;
  multiplo_clausula?: number | null;
  xp_jornada: number;
  mejora_once: number;
  roi_pts_por_millon?: number | null;
  p_titular?: number | null;
  prevision_7d_pct?: number | null;
  abierta_ahora: boolean;
  desbloqueo?: string | null;
  cuando: string;
  ventana_cierra?: string | null;
  asequible: boolean;
  falta_caja_eur: number;
  caja_tras?: number | null;
  rivales_que_pueden_quitartelo: number;
  bono_rosco_rival?: BonoRoscoRival | null;
  prioridad_estrategica?: number | null;
  veredicto_codigo: VeredictoClausulazo;
  veredicto_titulo: string;
  motivo_detallado: string;
};

export type AlertaClausula = {
  tipo: "escudo" | "francotirador" | string;
  tono: "rojo" | "verde" | string;
  mensaje: string;
  player_id?: string | null;
  nombre?: string | null;
  posicion?: string | null;
  rival?: string | null;
  ratio_clausula?: number | null;
};

export type RadarAntiRobo = {
  player_id: string;
  nombre: string;
  posicion?: string | null;
  estado: "RIESGO_ALTO" | "RIESGO_CERO" | "SOBREPROTEGIDO" | string;
  badge: "rojo" | "verde" | "gris" | string;
  consejo: string;
  clausula: number;
  valor_mercado: number;
  valor_proyectado_7d?: number | null;
  prevision_7d_pct?: number | null;
  beneficio_neto?: number | null;
  rivales_con_caja: number;
  clausula_abierta?: boolean;
  dias_para_abrir?: number | null;
};

export type AsesorClausulas = {
  resumen: {
    en_peligro: number;
    riesgo_alto: number;
    coste_proteger_eur: number;
    seguros: number;
    bloqueadas: number;
    clausulazos_listos: number;
    clausulazos: number;
    ventana_cierra?: string | null;
    ventana_abierta: boolean;
    /** Jugadores sin recambio cuya cláusula se abre antes del próximo bloqueo. */
    alertas_prioritarias?: AlertaPrioritaria[];
  };
  proteger: ClausulaEnPeligro[];
  preparar?: ClausulaEnPeligro[];
  clausulazos: ClausulazoSugerido[];
  radar_anti_robo?: RadarAntiRobo[];
  /** Escudo (te la pueden robar) y francotirador (cláusula barata de un rival en rojo). */
  alertas_clausulas?: AlertaClausula[];
};
