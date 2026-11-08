// Plan de fichajes, auditoría de ventas y ventas forzadas.
import type { AlertaClausula } from "./clausulas";

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
  /** Escalón sobre nuestra cifra que cubre lo que suele pagar la liga (sin pasar del techo). */
  puja_competitiva_liga?: number | null;
  /** Sobrepuja media que sostiene ese escalón, en %. */
  sobrepuja_liga_pct?: number | null;
  /** En el parón: la puja se paga con el crédito del 20 %. */
  financia_con_credito?: boolean;
  /** Modo parón: papel de la acción y etiqueta a mostrar. */
  paron_rol?: "HOLD_J13" | "ESPECULAR" | "CORTA_HEMORRAGIAS" | "RECOGER_BENEFICIOS" | "RUTA_SALIDA" | string;
  etiqueta_paron?: string | null;
  ganancia_esperada_eur?: number | null;
  /** Botón a pulsar: puja en el mercado o pago de la cláusula a un rival. */
  etiqueta?: "PUJAR" | "CLAUSULAR" | null;
  /** Solo en alternativas_liquidez. */
  roi_xp_por_millon?: number | null;
  falta_eur?: number | null;
};

/** De dónde sale cada euro del plan (lo garantiza el solver). */
export type PlanPresupuesto = {
  caja: number;
  ventas_hoy: number;
  ventas_si_ganas: number;
  credito_20pct: number | null;
  /** Parón: lo que el plan gasta por encima de la caja. Hay que saldarlo antes del saque. */
  credito_paron?: number;
  disponible_clausulas: number;
  disponible_pujas: number;
  gasto_clausulas: number;
  gasto_pujas: number;
  holgura: number;
  cumple: boolean;
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

export type PlanResumen = {
  mejora_puntos_jornada?: number | null;
  mejora_horizonte?: number | null;
  saldo_al_final?: number | null;
  presupuesto?: PlanPresupuesto | null;
  compras?: Array<{ player_id?: string | null; nombre?: string | null; etiqueta?: string | null; euros?: number | null; mejora_neta?: number | null }>;
  ventas?: Array<{ player_id?: string | null; nombre?: string | null; euros?: number | null; momento?: string | null }>;
  valido?: boolean;
  motivo?: string | null;
};

/** Modo Parón autónomo: fase por calendario, ruta de salida y proyección hasta el cierre. */
export type PlanParon = {
  activo: boolean;
  fase: 1 | 2 | 3;
  fase_nombre: string;
  dias_al_cierre: number;
  cierre: string;
  dia_venta: string;
  acciones: PlanFichajeAccion[];
  corta_hemorragias: PlanFichajeAccion[];
  especular: PlanFichajeAccion[];
  recoger_beneficios: PlanFichajeAccion[];
  hold_j13: Array<{ player_id: string; nombre: string; euros: number; subida_esperada_eur: number }>;
  capital_especulacion: { caja: number; credito: number };
  ruta_salida: {
    dia_venta: string;
    /** ISO del último día de venta (cierre − 2 días), en hora de Madrid. */
    dia_venta_at?: string | null;
    /** Colchón sobre la deuda que la ruta intenta cubrir (peor caso de oferta). */
    holgura_eur?: number | null;
    /** Fracción del valor que cuenta cada venta (0,90: peor oferta de LaLiga). */
    margen_oferta?: number | null;
    con_holgura?: boolean | null;
    deuda_a_saldar: number;
    saldo_proyectado: number;
    ventas: Array<{
      player_id: string;
      nombre: string;
      valor_hoy: number;
      valor_proyectado: number;
      ingreso: number;
      titular: boolean;
      origen: string;
      xp_perdido: number;
    }>;
    reposiciones: Array<{ player_id: string; nombre: string; posicion?: string | null; euros: number; jornada?: number | null }>;
    ingreso: number;
    cubre: boolean;
    falta_eur: number;
    xp_perdido: number;
    titulares_vendidos: number;
    texto: string | null;
  };
  proyeccion: {
    ganancia_hold_eur: number;
    ganancia_especulacion_eur: number;
    perdida_evitada_eur: number;
    beneficio_total_eur: number;
    mejora_xp_j13: number;
    saldo_viernes_sin_ruta: number;
    xp_perdido_por_ruta: number;
  };
};

export type PlanFichajes = {
  ok?: boolean;
  /** «ok» y «sin_cambios» son cálculos terminados; el resto es un fallo y no significa «nada que hacer». */
  estado_calculo?: "ok" | "sin_cambios" | "fallo_solver" | "impagable" | "sin_caja" | "error" | string | null;
  estado_detalle?: string | null;
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
  presupuesto?: PlanPresupuesto | null;
  /** Deuda que deja el plan en el parón y con qué se puede saldar sin tocar el once. */
  deuda_paron?: {
    eur: number;
    saldar_antes_de_dias: number;
    decidir_ventas_en_dias: number;
    vendible_sin_tocar_el_once: number;
    revalorizacion_prevista: number;
    cubierta_con_banquillo: boolean;
    aviso: string | null;
  } | null;
  /** Must-buy que no caben en la caja de hoy, por mejora por millón. */
  alternativas_liquidez?: PlanFichajeAccion[];
  /** Plan completo frente al prudente (sin ventas que dependan de ganar pujas). */
  comparativa?: { completo?: PlanResumen; prudente?: PlanResumen } | null;
  trading?: TradingDesk;
  /** Presente solo durante un parón de selecciones. */
  paron?: PlanParon | null;
  liquidacion?: PlanLiquidacion;
  /** Escudo y francotirador: cláusulas en riesgo y chollos de rivales en rojo. */
  alertas_clausulas?: AlertaClausula[];
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
