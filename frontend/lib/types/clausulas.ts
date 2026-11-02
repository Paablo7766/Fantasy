// Asesor de cláusulas: tus jugadores en peligro y los clausulazos.

export type NivelClausula = {
  clausula_objetivo: number;
  subida_eur: number;
  coste_eur: number;
  caja_tras: number | null;
  rivales_cubiertos: number;
  rivales_sin_cubrir: number;
  viable: boolean;
};

export type VeredictoProteger = "PROTEGER_YA" | "PROTEGER_PARCIAL" | "SIN_CAJA" | "VENDER_ANTES" | "ASUMIR";

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
  veredicto_codigo: VeredictoProteger;
  veredicto_titulo: string;
  motivos: string[];
  motivo_detallado: string;
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
  };
  proteger: ClausulaEnPeligro[];
  clausulazos: ClausulazoSugerido[];
  radar_anti_robo?: RadarAntiRobo[];
};
