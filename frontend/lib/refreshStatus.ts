import type { RefreshStatusPayload } from "@/lib/types";

/**
 * Fases reales de una pasada, en el orden en que el backend las ejecuta.
 *
 * El ``pct`` es el avance acumulado al **entrar** en esa fase, no una medida
 * exacta: sin esto la barra se quedaba clavada en 0 % o saltaba a 100 % al
 * empezar, que es justo lo que hacía imposible saber si la descarga avanzaba.
 * Los pesos siguen el coste real de cada tramo (plantillas y scrapers mandan).
 */
const PHASES: ReadonlyArray<{ id: string; label: string; pct: number }> = [
  { id: "mercado", label: "Mercado de LALIGA", pct: 8 },
  { id: "plantillas", label: "Plantillas de la liga", pct: 28 },
  { id: "scrapers", label: "Scrapers: puntos, forma y valor", pct: 62 },
  { id: "once", label: "Once óptimo", pct: 74 },
  { id: "actividad", label: "Historial de pujas", pct: 86 },
  { id: "caja", label: "Caja y necesidades", pct: 94 },
  { id: "imagenes", label: "Fotos de jugador", pct: 98 },
];

/** Fase del latido, o ``null`` si el backend no la manda. */
function phaseOf(status: RefreshStatusPayload | null | undefined) {
  if (!status || !status.phase) return null;
  return PHASES.find((phase) => phase.id === status.phase) ?? null;
}

/** Avance 0–100 de la descarga en curso. ``0`` si aún no hay latido. */
export function refreshPct(status: RefreshStatusPayload | null | undefined): number {
  if (!status) return 0;
  if (status.running === false) return status.result_ok === false ? 0 : 100;
  const phase = phaseOf(status);
  return phase ? phase.pct : 4;
}

/** Nombre legible de la fase («Plantillas de la liga»), nunca el id crudo. */
export function refreshPhaseLabel(status: RefreshStatusPayload | null | undefined): string {
  if (!status) return "Conectando con el backend";
  if (status.running === false) return status.result_ok === false ? "Descarga fallida" : "Descarga terminada";
  const phase = phaseOf(status);
  // ``phase_label`` lo manda el backend; sirve de red si añade una fase nueva.
  return phase?.label || status.phase_label || "Descargando";
}

/** «LALIGA Fantasy» o ``null``: la fuente que se está pidiendo ahora mismo. */
export function refreshCurrentLabel(status: RefreshStatusPayload | null | undefined): string | null {
  if (!status || status.running !== true) return null;
  return status.current_label || null;
}

/**
 * Línea de estado de una descarga: fase, tiempo y trabajo hecho.
 *
 * ``calls`` son peticiones reales y ``cache_hits`` documentos servidos de
 * disco. Se nombran por separado porque en air-gap (el modo por defecto) no
 * sale ni una petición: decir solo «0 llamadas» se lee como «colgado» cuando
 * en realidad está leyendo la caché a toda velocidad.
 */
export function refreshSummary(status: RefreshStatusPayload | null | undefined): string {
  if (!status || status.started_at === undefined) return "Preparando la descarga";
  const parts: string[] = [refreshPhaseLabel(status)];
  const current = refreshCurrentLabel(status);
  if (current) parts.push(`pidiendo ${current}`);
  const calls = status.calls ?? 0;
  const cacheHits = status.cache_hits ?? 0;
  if (calls > 0) parts.push(`${calls} llamada${calls === 1 ? "" : "s"}`);
  if (cacheHits > 0) parts.push(`${cacheHits} de caché`);
  if (calls === 0 && cacheHits === 0 && status.running === true) parts.push("arrancando");
  const idle = refreshIdleNote(status);
  if (idle) parts.push(idle);
  return parts.join(" · ");
}

/**
 * «Sin novedad desde hace X s» cuando la pasada lleva un rato sin resolver nada.
 *
 * Una descarga real tiene pausas legítimas (fuente lenta, reintento, cadencia
 * humana). Sin decirlo, una pausa de 40 s es indistinguible de un cuelgue: es
 * exactamente la duda que hacía mirar la pantalla sin saber si esperar.
 * Devuelve ``null`` si hay actividad reciente o si no hay dato.
 */
export function refreshIdleNote(status: RefreshStatusPayload | null | undefined): string | null {
  if (!status || status.running !== true) return null;
  const idle = status.last_activity_seconds;
  if (typeof idle !== "number") return null;
  const threshold = status.in_flight && status.in_flight > 0 ? 45 : 20;
  if (idle < threshold) return null;
  return `sin novedad desde hace ${Math.round(idle)} s`;
}

/**
 * Aviso de por qué no suben las llamadas, cuando no es un fallo.
 *
 * Sin esto el usuario ve «0 llamadas» durante minutos y concluye que la
 * actualización no hace nada. Es la explicación explícita del air-gap.
 */
export function refreshNetworkNote(status: RefreshStatusPayload | null | undefined): string | null {
  if (!status || status.running !== true) return null;
  if (status.network !== false) return null;
  return "Modo local: la pasada lee de la caché de disco, así que no gasta llamadas a LALIGA. El contador que avanza es el de caché.";
}

/**
 * ¿Se puede dar la descarga por acabada? Solo con una lectura del latido que
 * diga que ya no corre. Un ``null`` (backend sin responder) no vale como final:
 * sería justo el caso en que el usuario se queda mirando una foto vieja.
 */
export function refreshFinished(status: RefreshStatusPayload | null | undefined): boolean {
  return Boolean(status) && status?.running === false;
}
