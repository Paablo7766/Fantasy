import type { DashboardState, MarketDecision, SourceStatus, TrendsPayload } from "@/lib/types";

export type HealthLevel = "ok" | "warn" | "bad";

export type SourceRow = {
  id: string;
  label: string;
  group: string;
  ok: boolean;
  count: number | null;
  fromCache: boolean;
  error: string | null;
  impacts: string[];
};

export type BlockStatus = {
  id: string;
  label: string;
  ok: boolean;
  detail: string;
};

export type MarketHealth = {
  listings: number;
  missingMatching: number;
  missingIdeal: number;
  missingPoints: number;
  missingSignal: number;
  sinMotivo: number;
};

export type DataHealthReport = {
  level: HealthLevel;
  score: number;
  headline: string;
  compromised: string[];
  notes: string[];
  sources: SourceRow[];
  blocks: BlockStatus[];
  market: MarketHealth | null;
};

const GROUP_ORDER = ["LALIGA", "Motor propio", "Analítica Fantasy", "Fútbol Fantasy", "Forma y calendario", "Otros"];

/** Alineado con ``_OPTIONAL_TRENDS_SOURCES`` en toolbox/scrapers.py */
const OPTIONAL_TRENDS_SOURCES = new Set(["fbref", "sofascore", "transfermarkt", "laliga_odds"]);

function optionalSourcesOnlyFailed(sources: SourceRow[]): boolean {
  const failed = sources.filter((s) => !s.ok);
  if (failed.length === 0) return false;
  return failed.every((s) => OPTIONAL_TRENDS_SOURCES.has(s.id));
}

const SOURCE_META: Record<string, { label: string; group: string; impacts: string[]; critical?: boolean }> = {
  own_intel_points: {
    label: "Puntos esperados (propio)",
    group: "Motor propio",
    impacts: ["Proyección de jornada", "Comparativa once vs mercado", "Motivo «puntos» en mercado"],
    critical: true,
  },
  own_intel_calendar: {
    label: "Calendario λ (propio)",
    group: "Motor propio",
    impacts: ["own_expected_points", "own_calendar en jornada"],
    critical: true,
  },
  own_intel_snapshots: {
    label: "Histórico de precios",
    group: "Motor propio",
    impacts: ["Puja own_ideal / own_max (≥3 días)", "Señal own_market_signal"],
  },
  own_intel_bids: { label: "Pujas propias", group: "Motor propio", impacts: ["Techo de puja own_*"] },
  own_intel_signal: { label: "Señal de mercado propia", group: "Motor propio", impacts: ["Flip / motivo de revalorización"] },
  understat: {
    label: "Understat (xG, fixtures)",
    group: "Forma y calendario",
    impacts: ["Motor OPTA v2", "FDR y rival en forma"],
    critical: true,
  },
  fbref: {
    label: "FBref",
    group: "Forma y calendario",
    impacts: ["Pases clave, duelos, despejes en OPTA v2"],
  },
  sofascore: {
    label: "Sofascore",
    group: "Forma y calendario",
    impacts: ["Nota media y métricas de forma"],
  },
  jornadaperfecta: {
    label: "Jornada Perfecta",
    group: "Forma y calendario",
    impacts: ["Multiplicador jp en proyección"],
  },
  transfermarkt: {
    label: "Transfermarkt",
    group: "Otros",
    impacts: ["Valor real vs fantasy (undervalued)"],
  },
  futbolfantasy_market: {
    label: "FF mercado",
    group: "Fútbol Fantasy",
    impacts: ["Aceleración LALIGA cruzada", "Titularidad mercado"],
  },
  futbolfantasy_lineups: {
    label: "FF alineaciones",
    group: "Fútbol Fantasy",
    impacts: ["p_titular y lineup_status"],
    critical: true,
  },
  futbolfantasy_fitness: {
    label: "FF lesionados",
    group: "Fútbol Fantasy",
    impacts: ["Disponibilidad y vetos"],
  },
  futbolfantasy_sanctions: { label: "FF sanciones", group: "Fútbol Fantasy", impacts: ["Vetos y tarjetas"] },
  futbolfantasy_warnings: { label: "FF avisos", group: "Fútbol Fantasy", impacts: ["Amarillas / verge"] },
  analiticafantasy_market: {
    label: "AF mercado",
    group: "Analítica Fantasy",
    impacts: ["af_price_delta, titularidad AF"],
  },
  analiticafantasy_points: {
    label: "AF puntos / oráculo",
    group: "Analítica Fantasy",
    impacts: ["Contraste af_expected_points", "Panel Intel"],
    critical: true,
  },
  analiticafantasy_ideal_bid: {
    label: "AF puja ideal",
    group: "Analítica Fantasy",
    impacts: ["Techo af_max cuando no hay own_*"],
  },
  analiticafantasy_prediction: {
    label: "AF predicción precio",
    group: "Analítica Fantasy",
    impacts: ["Motivo flip AF (matching ≥0,85)"],
  },
  analiticafantasy_lineups: {
    label: "AF alineaciones",
    group: "Analítica Fantasy",
    impacts: ["Titularidad cuando pisa FF"],
  },
  analiticafantasy_calendar: {
    label: "AF calendario",
    group: "Analítica Fantasy",
    impacts: ["jornada_board y calendario favorable"],
  },
  analiticafantasy_oracle: { label: "AF oráculo listas", group: "Analítica Fantasy", impacts: ["Rankings en Intel"] },
  analiticafantasy_form: { label: "AF forma", group: "Analítica Fantasy", impacts: ["Nota AF en forma"] },
  analiticafantasy_injured: { label: "AF lesionados", group: "Analítica Fantasy", impacts: ["af_injury"] },
  analiticafantasy_suspended: { label: "AF sancionados", group: "Analítica Fantasy", impacts: ["af_suspension"] },
  analiticafantasy_set_pieces: { label: "AF balón parado", group: "Analítica Fantasy", impacts: ["Roles AF"] },
  analiticafantasy: {
    label: "Analítica Fantasy (global)",
    group: "Analítica Fantasy",
    impacts: ["Todo el bloque AF"],
    critical: true,
  },
  own_intel: {
    label: "Motor propio (global)",
    group: "Motor propio",
    impacts: ["own_* completo"],
    critical: true,
  },
};

function metaFor(id: string): { label: string; group: string; impacts: string[]; critical?: boolean } {
  if (SOURCE_META[id]) return SOURCE_META[id];
  if (id.startsWith("analiticafantasy_")) {
    return {
      label: id.replace("analiticafantasy_", "AF ").replace(/_/g, " "),
      group: "Analítica Fantasy",
      impacts: ["Enriquecimiento AF"],
    };
  }
  if (id.startsWith("own_intel_")) {
    return {
      label: id.replace("own_intel_", "Propio ").replace(/_/g, " "),
      group: "Motor propio",
      impacts: ["Motor own_*"],
    };
  }
  if (id.startsWith("futbolfantasy_")) {
    return {
      label: id.replace("futbolfantasy_", "FF ").replace(/_/g, " "),
      group: "Fútbol Fantasy",
      impacts: ["Scraper FF"],
    };
  }
  return { label: id.replace(/_/g, " "), group: "Otros", impacts: ["Dato auxiliar"] };
}

function parseSource(id: string, raw: unknown): SourceRow | null {
  if (!raw || typeof raw !== "object") return null;
  const row = raw as SourceStatus;
  const ok = row.ok !== false;
  const meta = metaFor(id);
  return {
    id,
    label: meta.label,
    group: meta.group,
    ok,
    count: typeof row.count === "number" ? row.count : null,
    fromCache: row.from_cache === true,
    error: typeof row.error === "string" && row.error.trim() ? row.error.trim() : null,
    impacts: meta.impacts,
  };
}

function marketStats(decisions: MarketDecision[] | undefined): MarketHealth | null {
  if (!Array.isArray(decisions) || decisions.length === 0) return null;
  let missingMatching = 0;
  let missingIdeal = 0;
  let missingPoints = 0;
  let missingSignal = 0;
  let sinMotivo = 0;
  for (const row of decisions) {
    const missing = row.missing_inputs || [];
    if (missing.includes("matching_confidence")) missingMatching += 1;
    if (missing.includes("ideal_bid") || missing.includes("max_bid")) missingIdeal += 1;
    if (missing.includes("expected_points")) missingPoints += 1;
    if (missing.includes("market_signal")) missingSignal += 1;
    if (row.primary_motive === "sin_motivo" || (row.reasons || []).includes("sin_motivo")) sinMotivo += 1;
  }
  return {
    listings: decisions.length,
    missingMatching,
    missingIdeal,
    missingPoints,
    missingSignal,
    sinMotivo,
  };
}

function scoreFromReport(sources: SourceRow[], blocks: BlockStatus[], trends: TrendsPayload | null): number {
  let score = 100;
  const optionalOnly = optionalSourcesOnlyFailed(sources);
  for (const src of sources) {
    if (src.ok) continue;
    const critical = metaFor(src.id).critical;
    if (!critical && optionalOnly) {
      score -= 3;
      continue;
    }
    score -= critical ? 18 : 6;
  }
  for (const block of blocks) {
    if (!block.ok) score -= block.id === "trends" ? 25 : 8;
  }
  const partialCore = Boolean(trends?.partial) && !optionalOnly && !trends?.optional_sources_degraded;
  if (partialCore) score -= 12;
  else if (trends?.optional_sources_degraded || (optionalOnly && Boolean(trends?.partial))) score -= 4;
  if (trends?.stale) score -= 8;
  return Math.max(0, Math.min(100, score));
}

function levelFromScore(score: number, failedCritical: boolean): HealthLevel {
  if (failedCritical || score < 45) return "bad";
  if (score < 80) return "warn";
  return "ok";
}

export function buildDataHealthReport(state: DashboardState): DataHealthReport | null {
  const trends = state.trends;
  if (!trends) return null;

  const sourcesRaw = trends.sources && typeof trends.sources === "object" ? trends.sources : {};
  const sources = Object.entries(sourcesRaw)
    .map(([id, raw]) => parseSource(id, raw))
    .filter((row): row is SourceRow => row !== null)
    .sort((a, b) => {
      const ga = GROUP_ORDER.indexOf(a.group);
      const gb = GROUP_ORDER.indexOf(b.group);
      if (ga !== gb) return (ga === -1 ? 99 : ga) - (gb === -1 ? 99 : gb);
      if (a.ok !== b.ok) return a.ok ? 1 : -1;
      return a.label.localeCompare(b.label, "es");
    });

  const failed = sources.filter((s) => !s.ok);
  const failedCritical = failed.some((s) => metaFor(s.id).critical);
  const optionalOnly = optionalSourcesOnlyFailed(sources);
  const formExtrasMissing = Boolean(trends.optional_sources_degraded) || optionalOnly;

  const awaitingSources = sources.length === 0;

  const blocks: BlockStatus[] = [
    {
      id: "trends",
      label: "Mercado e intel",
      ok: trends.ok !== false && !awaitingSources,
      detail:
        trends.ok === false
          ? "No hay lectura trends válida."
          : awaitingSources
            ? trends.stale
              ? "Foto rápida sin scrapers. No se descarga nada hasta pulsar Actualizar."
              : "Esta lectura no incluye fuentes."
            : formExtrasMissing && !failedCritical
              ? "Núcleo OK; forma extra (FBref/Sofascore/TM) incompleta."
              : trends.partial
                ? "Lectura parcial: alguna fuente crítica falló."
                : `Catálogo ${trends.catalog_count ?? "?"} jugadores.`,
    },
    {
      id: "optimize",
      label: "Once óptimo",
      ok: state.optimize?.ok !== false && !state.optimize?.matchday_void,
      detail: state.optimize?.matchday_void
        ? `Jornada en riesgo: ${(state.optimize?.void_reasons || []).join(", ") || "XI o caja inválidos"}.`
        : state.optimize?.partial
          ? "Once incompleto (huecos)."
          : state.optimize?.formation
            ? `Formación ${state.optimize.formation}.`
            : state.optimize
              ? "Calculado."
              : "Sin datos.",
    },
    {
      id: "squads",
      label: "Plantillas",
      ok: state.squads?.ok !== false,
      detail: state.squads?.partial
        ? "Plantillas parciales (algún equipo sin leer)."
        : state.squads?.rival_count != null
          ? `${state.squads.rival_count} rivales.`
          : state.squads
            ? "OK."
            : "Sin datos.",
    },
    {
      id: "needs",
      label: "Caja e historial",
      ok: state.needs?.ok !== false,
      detail: state.needs?.history?.war_count != null
        ? `${state.needs.history.war_count} guerras con valor guardado (puja de liga).`
        : state.needs
          ? "Ledger leído."
          : "Sin datos.",
    },
  ];

  const market = marketStats(trends.market_decisions);

  const compromised: string[] = [];
  if (awaitingSources) {
    compromised.push(
      trends.stale
        ? "Esta copia es la foto rápida (once, plantillas y mercado de LALIGA). Los scrapers aún no han escrito fuentes: AF, Fútbol Fantasy y Understat llegan con la foto completa."
        : "Esta lectura no trae ninguna fuente. Sin scrapers no hay puntos esperados ni techo de puja.",
    );
  }
  if (!awaitingSources && trends.partial && failedCritical) {
    compromised.push("La lectura global es parcial: falló al menos una fuente crítica en esta sincronización.");
  } else if (!awaitingSources && formExtrasMissing && !failedCritical) {
    compromised.push(
      "Solo fallan fuentes opcionales de forma/valor (FBref, Sofascore, Transfermarkt…). Puja y once siguen en el núcleo FF+AF+Understat.",
    );
  } else if (!awaitingSources && trends.partial) {
    compromised.push("Lectura parcial por plantillas u otro bloque; revisa el detalle de fuentes.");
  }
  if (failedCritical) {
    compromised.push("Falló al menos una fuente crítica; proyección de puntos o techos pueden estar incompletos.");
  }
  if (failed.some((s) => s.id === "fbref" || s.id === "sofascore")) {
    compromised.push("Forma avanzada (duelos, nota, paradas) más fina: el motor OPTA v2 usa sobre todo Understat.");
  }
  if (failed.some((s) => s.id.startsWith("analiticafantasy"))) {
    compromised.push("Analítica Fantasy incompleta: el contraste AF en mercado e Intel puede faltar o no contar como motivo.");
  }
  if (failed.some((s) => s.id === "own_intel_snapshots" || s.id === "own_intel_bids")) {
    compromised.push("Histórico de precios corto: own_ideal_bid puede no existir (<3 días) y el techo queda unknown.");
  }
  if (market && market.missingMatching > 0) {
    compromised.push(
      `${market.missingMatching} listing(s) con matching AF <0,85: las señales AF no cuentan como motivo positivo ahí.`,
    );
  }
  if (market && market.missingIdeal > market.listings / 2) {
    compromised.push("Muchos listings sin techo ideal/máx: las tesis de precio (barato/caro) son más débiles.");
  }
  if (trends.stale) {
    compromised.push(
      "La foto guardada tiene más de 15 minutos. No se descarga nada hasta que pulses Actualizar: los precios y las horas pueden haber cambiado.",
    );
  }

  const notes: string[] = [];
  if (typeof trends.form_note === "string" && trends.form_note.trim()) {
    notes.push(trends.form_note.trim());
  }
  if (market && market.sinMotivo > 0) {
    notes.push(
      `${market.sinMotivo} de ${market.listings} en mercado salen «sin motivo claro»: suele ser criterio (no mejora el once), no solo un fallo de datos.`,
    );
  }
  if (formExtrasMissing && !failedCritical) {
    notes.push(
      "Si FBref/Sofascore dan 403 en el servidor, ejecuta en tu PC: FANTASY_SCRAPER_BROWSER=1 y python cli.py warm-stats --json --fresh para rellenar caché.",
    );
  }

  const score = awaitingSources ? Math.min(scoreFromReport(sources, blocks, trends), 35) : scoreFromReport(sources, blocks, trends);
  const level = awaitingSources ? "warn" : levelFromScore(score, failedCritical);
  const failCount = failed.length;
  const headline = awaitingSources
    ? trends.stale
      ? "Fuentes en camino: no uses aún las tesis de precio ni de puntos"
      : "Sin fuentes en esta lectura"
    : level === "ok"
      ? failCount === 0 && !trends.partial
        ? "Datos al día para decidir"
        : "Datos usables con matices"
      : level === "warn"
        ? `${failCount} fuente(s) con error · revisa antes de pujar fuerte`
        : "Lectura muy comprometida · no confíes al 100% en las tesis";

  return {
    level,
    score,
    headline,
    compromised,
    notes,
    sources,
    blocks,
    market,
  };
}

export function healthLevelLabel(level: HealthLevel): string {
  if (level === "ok") return "OK";
  if (level === "warn") return "Parcial";
  return "Riesgo";
}
