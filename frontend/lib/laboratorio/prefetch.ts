import { endpoint } from "@/lib/core/api";
import { prefetchJsonInOrder } from "@/lib/core/jsonCache";

/**
 * Deja en segundo plano las lecturas del Laboratorio para que cada pestaña
 * pinte al instante. Se llama solo al entrar en el Laboratorio y van **de una
 * en una**: nueve a la vez llevaban a Render a 472 MB de 512 sin descarga.
 * `apiLeague` es la liga que usan los paneles que leen `trends.league_id`
 * (modelo, previa, calibración, post-mortem); `queryLeague` la del parámetro
 * ?league= (radar, rivales, cláusulas).
 */
export function prefetchLaboratorio(apiLeague: string | null, queryLeague: string | null): void {
  void prefetchJsonInOrder([
    endpoint("/api/laboratorio/modelo", apiLeague),
    endpoint("/api/laboratorio/previa", apiLeague),
    endpoint("/api/laboratorio/post-mortem", apiLeague),
    endpoint("/api/calibration", apiLeague),
    endpoint("/api/laboratorio/primas", apiLeague),
    endpoint("/api/market/quant-radar", queryLeague),
    endpoint("/api/catalog/free-agents", queryLeague),
    endpoint("/api/rival-intel", queryLeague),
    endpoint("/api/clause-board", queryLeague),
  ]);
}
