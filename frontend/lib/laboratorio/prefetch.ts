import { endpoint } from "@/lib/core/api";
import { prefetchJson } from "@/lib/core/jsonCache";

/**
 * Lanza en segundo plano todas las lecturas del Laboratorio para que cada
 * pestaña pinte al instante. `apiLeague` es la liga que usan los paneles que
 * leen `trends.league_id` (modelo, previa, calibración, post-mortem);
 * `queryLeague` la del parámetro ?league= (radar, rivales, cláusulas).
 */
export function prefetchLaboratorio(apiLeague: string | null, queryLeague: string | null): void {
  prefetchJson([
    endpoint("/api/laboratorio/modelo", apiLeague),
    endpoint("/api/laboratorio/previa", apiLeague),
    endpoint("/api/laboratorio/post-mortem", apiLeague),
    endpoint("/api/calibration", apiLeague),
    endpoint("/api/market/quant-radar", queryLeague),
    endpoint("/api/catalog/free-agents", queryLeague),
    endpoint("/api/rival-intel", queryLeague),
    endpoint("/api/clause-board", queryLeague),
  ]);
}
