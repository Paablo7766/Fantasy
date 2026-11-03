// Plan de fichajes, auditoría de ventas y ventas forzadas.

export type PlanFichajeAccion = {
  tipo?: "VENDE" | "VENDER HOY" | "ESCAPARATE" | "PUJA" | "CLAUSULAZO" | "BUSCA" | string;
  momento?: "hoy" | "luego" | "radar" | "condicional" | string;
  impulso?: "MUST-BUY" | "CHOLLO" | "HOLD" | "ALL-IN" | "NORMAL" | "VENTA" | string | null;
  player_id?: string | null;
  nombre?: string | null;
  posicion?: string | null;
  jornada?: number | null;
  euros?: number | null;
  mejora_neta?: number | null;
  prevision_7d_pct?: number | null;
  detalle?: string | null;
  /** Cifra redonda que daría La Pizarra y la nuestra cuando hay demanda alta. */
  puja_pizarra?: number | null;
  puja_anti_pizarra?: number | null;
  diferencial_anti_pizarra_eur?: number | null;
  alta_demanda?: boolean;
};

export type TradingOperacion = {
  player_id?: string | null;
  nombre?: string | null;
  origen?: string | null;
  euros?: number | null;
  pct?: number | null;
  ganancia_esperada?: number | null;
  etiqueta?: string | null;
  cierre?: string | null;
};

export type TradingDesk = {
  activo?: boolean;
  operaciones?: TradingOperacion[];
  caja_libre?: number | null;
  deuda_usable?: number | null;
  capital?: number | null;
  gasto?: number | null;
  usa_deuda?: number | null;
  ganancia_esperada?: number | null;
};

export type FaseSemana = "APALANCAMIENTO" | "ESCAPARATE" | "LIQUIDACION";

export type LiquidacionSobrante = {
  player_id?: string | null;
  nombre?: string | null;
  position?: string | null;
  valor?: number | null;
  oferta_eur?: number | null;
  pct?: number | null;
  elegible?: boolean;
  accion?: string | null;
  motivo?: string | null;
  etiqueta?: string | null;
};

export type PlanLiquidacion = {
  activo?: boolean;
  fase?: FaseSemana | string | null;
  dias_para_jornada?: number | null;
  once_completo?: boolean;
  sobrantes?: LiquidacionSobrante[];
  saldo?: number | null;
  saldo_tras_liquidar?: number | null;
  saldo_peor_caso?: number | null;
  deficit_eur?: number | null;
};

export type PlanFichajes = {
  ok?: boolean;
  mejora_puntos_jornada?: number | null;
  saldo_al_final?: number | null;
  nota?: number | null;
  veredicto?: "Hazlo ya" | "Recomendable" | "Opcional" | string | null;
  acciones?: PlanFichajeAccion[];
  formacion?: string | null;
  puntos_once?: number | null;
  puntos_once_actual?: number | null;
  ratio_mercado?: number | null;
  dias_al_cierre?: number | null;
  penalizacion_liquidez?: number | null;
  factor_ajuste?: number | null;
  modo_liquidez?: "VENTANA" | "ALL-IN" | "SIN_RELOJ" | string | null;
  en_radar?: PlanFichajeAccion[];
  trading?: TradingDesk;
  liquidacion?: PlanLiquidacion;
  once?: Array<{
    player_id?: string | null;
    nombre?: string | null;
    posicion?: string | null;
    jornada?: number | null;
    origen?: string | null;
  }>;
};

export type VeredictoVenta =
  | "ACEPTAR_YA"
  | "RECHAZAR_ESPERAR"
  | "RECHAZAR_RIVAL"
  | "PONER_ESCAPARATE"
  | "MANTENER_INTOCABLE";

export type AuditoriaVenta = {
  player_id: string;
  nombre: string;
  posicion?: string | null;
  valor_mercado: number;
  valor_justo?: number | null;
  xp_jornada?: number | null;
  prevision_7d_pct?: number | null;
  tu_once_pierde_sin_el: number;
  relevo_banquillo?: { player_id?: string | null; nombre?: string | null; jornada?: number | null } | null;
  financia_must_buy_hoy?: boolean;
  plan_vende_hoy?: boolean;
  en_mercado?: boolean;
  dias_al_cierre?: number | null;
  oferta_activa: {
    comprador: string | null;
    importe_oferta: number | null;
    spread_pct: number | null;
    calidad_oferta: "Excelente" | "Justa" | "Baja" | null;
  };
  ganancia_esperar_jueves?: {
    pct: number | null;
    eur: number | null;
    valor_proyectado_jueves: number | null;
  };
  alerta_refuerzo_rival?: boolean;
  veredicto_codigo: VeredictoVenta;
  veredicto_titulo: string;
  motivo_detallado: string;
  prioridad: number;
};

export type ResumenVentas = {
  ofertas_activas: number;
  total_ofertas_eur: number;
  spread_medio_laliga_pct: number | null;
  ventas_recomendadas_hoy: number;
  jugadores: number;
};

export type VentaForzada = {
  player_id?: string | null;
  nombre?: string | null;
  team_id?: string | null;
  manager?: string | null;
  posicion?: string | null;
  prevision_7d_pct?: string | null;
  en_mercado?: boolean;
  venta_forzada_rival?: boolean;
  detalle?: string | null;
};
