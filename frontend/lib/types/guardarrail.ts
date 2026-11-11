// Guardarraíl de ruina (`guardarrail_ruina` en /api/plan y /api/trends).
// Saldo en el peor caso al cierre: caja − todas las pujas vivas − ofertas de compra pendientes.

export type GuardarrailEstado = "OK" | "AVISO" | "PELIGRO" | "SIN_ACTUALIZAR";

export type GuardarrailPuja = {
  player_id: string;
  nombre?: string | null;
  euros: number;
};

export type GuardarrailAccion = {
  tipo: "RETIRAR_PUJA" | "VENDER" | string;
  player_id: string;
  nombre?: string | null;
  euros: number;
  /** xP que pierde el once si solo se hace este movimiento. */
  coste_xp_solo?: number | null;
};

export type GuardarrailCobertura = {
  falta_eur: number;
  cubre: boolean;
  acciones: GuardarrailAccion[];
  euros_cubiertos?: number;
  coste_xp: number;
  nota?: string | null;
};

export type GuardarrailPlan = {
  estado: GuardarrailEstado;
  saldo_peor: number;
  margen_eur: number;
  gasto_plan_adicional: number;
  descartar: boolean;
};

export type Guardarrail = {
  estado: GuardarrailEstado;
  razones?: string[];
  caja: number | null;
  pujas_vivas: GuardarrailPuja[];
  total_pujas_vivas: number;
  ofertas_compra_pendientes?: number;
  saldo_peor: number | null;
  valor_equipo?: number;
  sigma_diaria_rel?: number | null;
  sigma_diaria_eur?: number | null;
  observaciones_sigma?: number;
  k?: number;
  dias_al_cierre?: number | null;
  valor_estresado?: number;
  limite_deuda?: number;
  limite_deuda_estresado?: number;
  /** Euros que sobran (+) o faltan (−) para quedar dentro del límite estresado. */
  margen_eur: number | null;
  /** Euros que faltan para saldo_peor ≥ 0. */
  falta_eur?: number;
  datos_caducados?: boolean;
  accion?: GuardarrailCobertura | null;
  plan?: GuardarrailPlan | null;
};
