"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { apiUrl, endpoint, getJson, postJson } from "@/lib/core/api";
import { readDashboardSnapshot, writeDashboardBlock } from "@/lib/core/dashboardCache";
import { durationAgo, liveAge, stamp } from "@/lib/core/format";
import { refreshPhaseLabel, refreshPct, refreshSummary } from "@/lib/core/refreshStatus";
import { useNow } from "@/lib/core/useClock";
import type {
  ApiError,
  DashboardState,
  NeedsPayload,
  OptimizePayload,
  PhotoMeta,
  PlanPayload,
  RefreshStatusPayload,
  SquadsPayload,
  TrendsPayload,
} from "@/lib/types";

const EMPTY: DashboardState = { optimize: null, trends: null, squads: null, needs: null, plan: null };

type BlockName = keyof DashboardState;

const BLOCKS: BlockName[] = ["optimize", "trends", "squads", "needs", "plan"];

const BLOCK_LABELS: Record<BlockName, string> = {
  needs: "Caja",
  optimize: "Once",
  squads: "Plantillas",
  trends: "Mercado",
  plan: "Hoy",
};

function isUsableBlock(doc: unknown): boolean {
  return !!doc && typeof doc === "object" && (doc as { ok?: boolean }).ok !== false;
}

function hasUsableSnapshot(state: DashboardState): boolean {
  return BLOCKS.some((name) => isUsableBlock(state[name]));
}

function pendingFromSnapshot(state: DashboardState): Record<BlockName, boolean> {
  return BLOCKS.reduce(
    (acc, name) => {
      acc[name] = !isUsableBlock(state[name]);
      return acc;
    },
    {} as Record<BlockName, boolean>,
  );
}

function leagueFromLocation(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("league");
}

function failedPayload(reason: unknown): ApiError {
  const payload = typeof reason === "object" && reason !== null ? (reason as { payload?: ApiError }).payload : undefined;
  if (payload && payload.ok === false) return payload;
  const message = reason instanceof Error ? reason.message : "Error de red.";
  return { ok: false, error: { code: "network", message } };
}

/**
 * Foto más antigua de las que se están pintando. ``last_updated`` viene del
 * backend (instante de captura) y ``photo_age_seconds`` de cuánto hace.
 */
function photoFrom(state: DashboardState): PhotoMeta | null {
  let oldest: PhotoMeta | null = null;
  for (const name of BLOCKS) {
    const doc = state[name] as PhotoMeta | null;
    if (!doc || typeof doc !== "object") continue;
    const age = typeof doc.photo_age_seconds === "number" ? doc.photo_age_seconds : null;
    if (age === null && !doc.last_updated) continue;
    if (oldest === null || (age ?? 0) > (oldest.photo_age_seconds ?? 0)) {
      oldest = {
        last_updated: doc.last_updated ?? null,
        photo_age_seconds: age,
        is_stale: doc.is_stale === true,
      };
    }
  }
  return oldest;
}

/** Instante de captura de un bloque en ms, o null si no lo trae. */
function photoMs(doc: PhotoMeta | null): number | null {
  if (!doc || typeof doc !== "object" || typeof doc.last_updated !== "string") return null;
  const ms = Date.parse(doc.last_updated);
  return Number.isFinite(ms) ? ms : null;
}

/** Captura más antigua entre los bloques de la copia local. */
function oldestPhotoMs(state: DashboardState): number | null {
  let oldest: number | null = null;
  for (const name of BLOCKS) {
    const ms = photoMs(state[name] as PhotoMeta | null);
    if (ms !== null && (oldest === null || ms < oldest)) oldest = ms;
  }
  return oldest;
}

/** El once no debe quedarse al 35 % mientras el mercado (lento) sigue en vuelo. */
function progressFromLoad(pending: Record<BlockName, boolean>) {
  const steps: [boolean, number][] = BLOCKS.map((name) => [!pending[name], 20]);
  const pct = Math.min(100, steps.reduce((sum, [done, weight]) => sum + (done ? weight : 0), 0));
  const done = BLOCKS.filter((name) => !pending[name]).length;
  const currentLabel = BLOCKS.find((name) => pending[name]) ?? null;
  return {
    done,
    total: BLOCKS.length,
    pct,
    currentLabel: currentLabel ? BLOCK_LABELS[currentLabel] : null,
  };
}

/** Cadencia del latido cuando el proxy ya cortó y se espera al backend. */
const BEAT_SLOW_MS = 8000;

/**
 * Espera a que el backend termine una descarga que el proxy ya no cubre.
 *
 * ``POST /api/plan/refresh`` puede tardar 30 min y el proxy de Next corta a los
 * 5 (``AbortSignal.timeout(300_000)``). Antes eso se traducía en «No se pudo
 * actualizar» con la descarga viva: el usuario pulsaba otra vez y duplicaba la
 * pasada. Aquí se sondea solo el latido (RAM, gratis) hasta que dice que ya no
 * corre, con un techo para no sondear para siempre.
 */
async function waitForRefresh(
  beat: () => Promise<RefreshStatusPayload | null>,
): Promise<RefreshStatusPayload | null> {
  const deadline = Date.now() + 60 * 60 * 1000;
  while (Date.now() < deadline) {
    // Al volver a la app se sondea al momento: en segundo plano los temporizadores
    // se congelan y esperar otros 8 s dejaba la pantalla sin cargar.
    await new Promise<void>((resolve) => {
      const done = () => {
        window.clearTimeout(id);
        document.removeEventListener("visibilitychange", onVisible);
        resolve();
      };
      const onVisible = () => {
        if (document.visibilityState === "visible") done();
      };
      const id = window.setTimeout(done, BEAT_SLOW_MS);
      document.addEventListener("visibilitychange", onVisible);
    });
    const status = await beat();
    if (!status) continue;
    if (status.running === false) return status;
  }
  return null;
}

/** Render/Vercel pueden tardar en arrancar: el POST falla antes de que ``running`` sea true. */
async function waitForRefreshStart(
  beat: () => Promise<RefreshStatusPayload | null>,
  maxMs = 90_000,
): Promise<RefreshStatusPayload | null> {
  const deadline = Date.now() + maxMs;
  while (Date.now() < deadline) {
    await new Promise((resolve) => window.setTimeout(resolve, 2000));
    const status = await beat();
    if (status?.running === true) return status;
  }
  return null;
}

type DashboardContextValue = {
  state: DashboardState;
  pending: Record<BlockName, boolean>;
  connecting: boolean;
  connectMessage: string | null;
  /**
   * LECTURA: hidrata los cinco bloques desde la foto del servidor (sin
   * descargar). Tras Actualizar, o al abrir si no hay copia local guardada.
   */
  load: () => Promise<void>;
  /**
   * ACTUALIZACIÓN: ``POST /api/plan/refresh``. El único punto de la interfaz
   * que dispara scrapers y sale a Internet. Lo llama el botón Actualizar.
   */
  refresh: () => Promise<void>;
  /** Relee solo la portada guardada. No descarga: la usa el panel de nota experta. */
  refreshPlan: () => Promise<void>;
  connectAccount: () => Promise<void>;
  /** Call from AppShell after mount so cache/load never race Suspense hydration. */
  markShellReady: () => void;
  trends: TrendsPayload | null;
  squads: SquadsPayload | null;
  optimize: OptimizePayload | null;
  needs: NeedsPayload | null;
  plan: PlanPayload | null;
  leagueName: string;
  updatedAt: string | null | undefined;
  busy: boolean;
  /** Hay una descarga en curso (botón Actualizar). */
  refreshing: boolean;
  /** Último error del refresco, si lo hubo. La foto anterior sigue en pantalla. */
  refreshError: string | null;
  /** La foto servida tiene más de 15 min: el usuario decide si actualizar. */
  stale: boolean;
  photo: PhotoMeta | null;
  /** «hace 6 h» a partir de ``photo_age_seconds`` del backend, **en vivo**. */
  photoAge: string;
  /** Edad de la foto en segundos, ya envejecida desde la lectura. */
  photoAgeSeconds: number | null;
  /** “Actualizado 09:14 · hace 6 min”: sello y edad en una sola línea. */
  photoLine: string;
  progress: ReturnType<typeof progressFromLoad>;
  /** Texto corto del avance mientras se descarga («2/5 · Once»). */
  statusLine: string | null;
  coreLoading: boolean;
  /** Latido de la descarga en curso (``/api/refresh-status``). */
  refreshStatus: RefreshStatusPayload | null;
  /** Fase legible de la descarga, p. ej. «Plantillas de la liga». */
  refreshPhase: string;
  /** Avance 0–100 medido con las fases reales del backend. */
  refreshPct: number;
  /** «Plantillas · pidiendo LALIGA · 37 llamadas»: una línea que se mueve. */
  refreshLine: string;
};

const DashboardContext = createContext<DashboardContextValue | null>(null);

export function DashboardProvider({ children }: { children: ReactNode }) {
  // Always EMPTY on server + first client paint. localStorage is restored only after
  // AppShell marks ready, so SSR HTML matches hydration.
  const [state, setState] = useState<DashboardState>(EMPTY);
  const [pending, setPending] = useState<Record<BlockName, boolean>>({
    optimize: true,
    trends: true,
    squads: true,
    needs: true,
    plan: true,
  });
  const [connecting, setConnecting] = useState(false);
  const [connectMessage, setConnectMessage] = useState<string | null>(null);
  const [shellReady, setShellReady] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [refreshStatus, setRefreshStatus] = useState<RefreshStatusPayload | null>(null);
  // Instante (ms) de la última lectura de los bloques. ``photo_age_seconds``
  // llega medido en ese momento: sin este sello se quedaría congelado y una foto
  // de hace dos horas seguiría diciendo «hace 2 min».
  const [readAt, setReadAt] = useState(0);
  const nowMs = useNow();
  const markShellReady = useCallback(() => {
    setShellReady(true);
  }, []);

  const stateRef = useRef<DashboardState>(EMPTY);
  /** El botón Actualizar es dueño de ``refreshing`` hasta que termina su ``load()``. */
  const refreshLeadRef = useRef(false);
  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const fetchBlock = useCallback(
    async (name: BlockName) => {
      const league = leagueFromLocation();
      try {
        // Sin ``fresh``: un GET jamás descarga, solo devuelve la foto guardada.
        const value = await getJson<DashboardState[typeof name]>(endpoint(`/api/${name}`, league));
        setState((prev) => ({ ...prev, [name]: value }));
        writeDashboardBlock(league, name, value);
        return value;
      } catch (reason) {
        setState((prev) => {
          if (prev[name] && (prev[name] as { ok?: boolean }).ok !== false) return prev;
          return { ...prev, [name]: failedPayload(reason) as never };
        });
        return null;
      } finally {
        setPending((prev) => ({ ...prev, [name]: false }));
      }
    },
    [],
  );

  /** Tras ``load``: ¿no llegó ninguna foto utilizable del servidor? */
  const blankAfterLoad = useCallback((): boolean => {
    const current = stateRef.current;
    return BLOCKS.every((name) => {
      const doc = current[name] as { ok?: boolean } | null;
      return !doc || doc.ok === false;
    });
  }, []);

  /** Hidrata los cinco bloques desde la foto del servidor. Solo lectura. */
  const load = useCallback(async () => {
    // Solo «carga» lo que aún no se ve: releer una foto nueva por debajo de lo ya
    // pintado es silencioso (sin punto azul ni «Cargando»).
    setPending(pendingFromSnapshot(stateRef.current));
    // Mercado no espera a caja/once: si Jornada u otro bloque se alarga,
    // Tenaglia y el resto del día tienen que pintar igual.
    // Los cinco bloques son lecturas independientes de la misma foto (el
    // backend ya mezcla needs dentro de squads): se piden a la vez.
    await Promise.all(BLOCKS.map((name) => fetchBlock(name)));
    setReadAt(Date.now());
  }, [fetchBlock]);

  /** Relee la portada guardada, sin barra de progreso: es una lectura, no una descarga. */
  const refreshPlan = useCallback(async () => {
    await fetchBlock("plan");
  }, [fetchBlock]);

  /**
   * Descarga nueva foto y la pinta. Es el único punto de la interfaz que gasta
   * peticiones: ``POST /api/plan/refresh`` baja LALIGA y los scrapers, guarda
   * en disco y devuelve el plan; después se releen los bloques ya cacheados.
   *
   * El POST puede tardar media hora (la cadencia humana espera 12–25 s por GET
   * y hay ~60). Mientras corre, un latido a ``/api/refresh-status`` —RAM pura,
   * sin red— dice la fase, el tiempo y las llamadas hechas: es lo que permite
   * distinguir «avanza» de «colgado». El latido se consulta aunque el proxy
   * corte el POST, porque la descarga sigue en el backend.
   */
  const refresh = useCallback(async () => {
    const league = leagueFromLocation();
    refreshLeadRef.current = true;
    setRefreshing(true);
    setRefreshError(null);
    setRefreshStatus(null);
    let beating = false;
    // La foto rápida (mercado, plantillas, once) queda guardada mucho antes que
    // la completa: se pinta en cuanto el latido lo dice, sin otra petición a
    // las fuentes (``GET /api/plan`` solo lee disco). La barra sigue hasta el final.
    let paintedCore = false;
    const beat = async () => {
      try {
        const status = await getJson<RefreshStatusPayload>(apiUrl("/api/refresh-status"));
        setRefreshStatus(status);
        if (!paintedCore && status.running === true && status.core_saved_at) {
          paintedCore = true;
          void refreshPlan();
        }
        return status;
      } catch {
        // Un fallo del latido no cancela la descarga ni inventa un estado:
        // simplemente se sigue mostrando el último dato conocido.
        return null;
      }
    };
    // El primer latido sale a los pocos cientos de ms: el usuario ve de inmediato
    // que el botón hizo algo, en vez de un «Actualizando…» sin fondo.
    const timer = window.setInterval(() => {
      if (beating) return;
      beating = true;
      void beat().finally(() => {
        beating = false;
      });
    }, 3000);
    try {
      // ``async=1``: el backend responde 202 al instante (imprescindible en Vercel:
      // el proxy serverless no puede mantener un POST de media hora abierto).
      const fresh = await postJson<PlanPayload & { accepted?: boolean }>(
        endpoint("/api/plan/refresh", league, { asyncRefresh: true }),
      );
      if (fresh.accepted) {
        const last = await waitForRefresh(beat);
        await load();
        if (last?.running === false && last.result_ok === false) {
          setRefreshError(last.error?.message || "La descarga falló en el servidor; se mantiene la foto anterior.");
        }
      } else if (fresh && fresh.ok !== false) {
        setState((prev) => ({ ...prev, plan: fresh }));
        writeDashboardBlock(league, "plan", fresh);
        await load();
      } else {
        await load();
      }
    } catch (reason) {
      // El proxy de Next corta a los 5 min aunque el backend siga trabajando.
      // Si el latido dice que la descarga continúa, no es un error: se sigue
      // esperando y se recarga al terminar.
      let status = await beat();
      if (status?.running !== true) {
        status = await waitForRefreshStart(beat);
      }
      if (status?.running === true) {
        await waitForRefresh(beat);
        await load();
      } else {
        // Si la app estuvo en segundo plano, el POST muere pero la descarga pudo
        // terminar: se relee la foto del servidor antes de dar nada por perdido.
        await load();
        if (status === null || status.result_ok === false) {
          // La foto anterior sigue siendo válida: se avisa y no se borra nada.
          setRefreshError(failedPayload(reason).error?.message || "No se pudo actualizar.");
        }
      }
    } finally {
      window.clearInterval(timer);
      refreshLeadRef.current = false;
      setRefreshing(false);
    }
  }, [load, refreshPlan]);

  useEffect(() => {
    if (!shellReady) return;
    const league = leagueFromLocation();
    // Al abrir (p. ej. al día siguiente) se enseña la última foto que el usuario
    // vio tras pulsar Actualizar. ``GET /api/plan`` recomputa el plan con la
    // foto vieja y cambia recomendaciones sin descargar; por eso no se relee
    // el servidor hasta que vuelva a pulsar Actualizar.
    const snap = readDashboardSnapshot(league);
    if (snap?.state && hasUsableSnapshot(snap.state)) {
      setState({ ...EMPTY, ...snap.state });
      setPending(pendingFromSnapshot(snap.state));
      setReadAt(typeof snap.savedAt === "number" ? snap.savedAt : Date.now());
      // La copia local se pinta al momento, pero el mercado se relee de la
      // foto ya guardada. Así un cambio del cálculo (la previsión a 7 días)
      // llega sin pulsar Actualizar y sin salir a LaLiga. El plan no se toca:
      // releerlo cambiaba recomendaciones con la misma foto.
      // Si el servidor ya tiene una foto más nueva (cron, móvil u otra
      // pestaña), se relee entera: si no, el mercado sería de hoy y el once,
      // la caja y el plan de la copia local, de otra foto.
      // La sonda es «needs» (20 KB, instantánea) y no «trends» (1 MB): decide
      // en décimas de segundo si hay foto nueva y, solo entonces, relee todo.
      // Se compara «needs» con «needs»: los bloques se capturan en instantes algo
      // distintos y comparar con el más viejo releía todo en cada apertura.
      const localAt = photoMs(snap.state.needs as PhotoMeta | null) ?? oldestPhotoMs(snap.state);
      void fetchBlock("needs").then((fresh) => {
        const serverAt = photoMs(fresh as PhotoMeta | null);
        if (serverAt !== null && (localAt === null || serverAt > localAt + 1000)) void load();
      });
      return;
    }
    void load().then(() => {
      if (blankAfterLoad()) {
        const fallback = readDashboardSnapshot(league);
        if (fallback?.state) {
          setState({ ...EMPTY, ...fallback.state });
          setPending(pendingFromSnapshot(fallback.state));
          if (typeof fallback.savedAt === "number") setReadAt(fallback.savedAt);
        }
      }
    });
  }, [fetchBlock, load, shellReady, blankAfterLoad]);

  /**
   * Al volver a la app (p. ej. tras tocar el aviso de «actualizado») se mira si
   * el servidor tiene una foto más nueva que la pintada y, si es así, se relee
   * todo al momento. La sonda es ligera, así que no cuesta nada hacerlo siempre.
   */
  useEffect(() => {
    if (!shellReady) return;
    const league = leagueFromLocation();
    let probing = false;
    const check = async () => {
      if (document.visibilityState !== "visible" || probing || refreshLeadRef.current) return;
      probing = true;
      try {
        const fresh = await getJson<PhotoMeta>(endpoint("/api/needs", league));
        const serverAt = photoMs(fresh);
        const localAt = photoMs(stateRef.current.needs as PhotoMeta | null) ?? oldestPhotoMs(stateRef.current);
        if (serverAt !== null && (localAt === null || serverAt > localAt + 1000)) await load();
      } catch {
        // Sin respuesta se queda lo que hay.
      } finally {
        probing = false;
      }
    };
    document.addEventListener("visibilitychange", check);
    window.addEventListener("focus", check);
    return () => {
      document.removeEventListener("visibilitychange", check);
      window.removeEventListener("focus", check);
    };
  }, [shellReady, load]);

  /**
   * Jornada en vivo: solo ese bloque se relee del servidor (lectura de la foto, sin red).
   *
   * El plan guardado en el navegador no se relee para no cambiar recomendaciones con la
   * misma foto, pero la jornada en juego depende del reloj (qué partidos ya se jugaron),
   * así que se injerta ``jornada_en_juego`` en el plan que hay, al abrir, cada 2 min y al
   * volver a la pestaña.
   */
  useEffect(() => {
    if (!shellReady) return;
    let cancelled = false;
    const league = leagueFromLocation();
    const sync = async () => {
      if (document.visibilityState === "hidden") return;
      try {
        const fresh = await getJson<PlanPayload>(endpoint("/api/plan", league));
        const live = (fresh?.plan_fichajes as { jornada_en_juego?: unknown } | null | undefined)?.jornada_en_juego;
        if (cancelled || live === undefined) return;
        setState((prev) => {
          const plan = prev.plan as (PlanPayload & { plan_fichajes?: Record<string, unknown> | null }) | null;
          if (!plan || plan.ok === false) return prev;
          const merged = {
            ...plan,
            plan_fichajes: { ...(plan.plan_fichajes ?? {}), jornada_en_juego: live },
          } as unknown as DashboardState["plan"];
          writeDashboardBlock(league, "plan", merged);
          return { ...prev, plan: merged };
        });
      } catch {
        // Sin respuesta se queda lo último que se vio.
      }
    };
    const first = window.setTimeout(() => void sync(), 1500);
    const timer = window.setInterval(() => void sync(), 120_000);
    const onVisible = () => {
      if (document.visibilityState === "visible") void sync();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      window.clearTimeout(first);
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [shellReady]);

  /**
   * Recargar la pestaña **a mitad de descarga** tiene que mostrar la descarga.
   *
   * El estado del refresco vive en el backend, no en esta pestaña: si se pulsa
   * F5 mientras baja la foto (o si la descarga la lanzó el móvil o un cron), el
   * panel arrancaba sin latido y «Actualizando» no aparecía, así que parecía
   * que no estaba pasando nada. Aquí se comprueba si hay una pasada viva y, si
   * la hay, se engancha a su latido hasta que termine.
   */
  useEffect(() => {
    if (!shellReady) return;
    let cancelled = false;
    let timer: number | undefined;
    // ``false`` hasta que el backend confirme una pasada viva: así una lectura
    // en reposo nunca enciende el estado «Actualizando».
    let following = false;

    const follow = async () => {
      let status: RefreshStatusPayload | null = null;
      try {
        status = await getJson<RefreshStatusPayload>(apiUrl("/api/refresh-status"));
      } catch {
        return;
      }
      if (cancelled) return;
      setRefreshStatus(status);
      if (status?.running !== true) {
        if (following) {
          following = false;
          // Si el usuario pulsó Actualizar, no apagar la barra aquí: el POST
          // puede seguir en vuelo y ``refresh()`` hará el ``load()`` al cerrar.
          if (!refreshLeadRef.current) {
            setRefreshing(false);
            await load();
          }
        }
        return;
      }
      following = true;
      if (!refreshLeadRef.current) {
        setRefreshing(true);
      }
      timer = window.setTimeout(() => {
        void follow();
      }, 3000);
    };

    void follow();

    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [load, shellReady]);

  const connectAccount = useCallback(async () => {
    setConnecting(true);
    setConnectMessage("Se abre Chrome. Elige tu cuenta de Google.");
    try {
      const data = await postJson<{
        league_saved?: boolean;
        league_id?: string;
        league_name?: string;
        leagues?: Array<{ league_id?: string; name?: string }>;
      }>(endpoint("/api/auth/browser", null));
      if (data.league_saved && data.league_id) {
        setConnectMessage(null);
        await refresh();
        return;
      }
      const lines = (data.leagues || [])
        .map((league) => `${league.league_id || ""} ${league.name || ""}`.trim())
        .join(" · ");
      setConnectMessage(`Tokens guardados. Falta elegir LEAGUE_ID. ${lines || "La cuenta no devolvió una sola liga."}`);
    } catch (error) {
      setConnectMessage(error instanceof Error ? error.message : "No se pudo conectar.");
    } finally {
      setConnecting(false);
    }
  }, [refresh]);

  const value = useMemo<DashboardContextValue>(() => {
    const trends = state.trends?.ok ? state.trends : null;
    const squads = state.squads?.ok ? state.squads : null;
    const optimize = state.optimize?.ok ? state.optimize : null;
    const busy = Object.values(pending).some(Boolean) || refreshing;
    const photo = photoFrom(state);
    // ``photo_age_seconds`` se midió cuando el backend respondió. Sin sumarle
    // el tiempo transcurrido desde entonces, el rótulo se queda en «hace 2 min»
    // toda la tarde y el dato parece más fresco de lo que es.
    const photoAgeSeconds = liveAge(photo?.photo_age_seconds ?? null, readAt, nowMs);
    const photoAge = durationAgo(photoAgeSeconds);
    const stale = photoAgeSeconds !== null ? photoAgeSeconds > 15 * 60 : photo?.is_stale === true;
    const progress = progressFromLoad(pending);
    const updatedAt =
      photo?.last_updated ?? trends?.dashboard_at ?? squads?.dashboard_at ?? optimize?.dashboard_at;
    const refreshLine = refreshSummary(refreshStatus);
    const refreshPctValue = refreshing ? refreshPct(refreshStatus) : progress.pct;
    return {
      state,
      pending,
      connecting,
      connectMessage,
      load,
      refresh,
      refreshPlan,
      connectAccount,
      markShellReady,
      trends,
      squads,
      optimize,
      needs: state.needs as NeedsPayload | null,
      plan: state.plan,
      leagueName: trends?.league_name || squads?.league_name || optimize?.manager_name || "Liga activa",
      updatedAt,
      busy,
      refreshing,
      refreshError,
      stale,
      photo,
      photoAge,
      photoAgeSeconds,
      photoLine: updatedAt ? (photoAge ? `${stamp(updatedAt)} · ${photoAge}` : stamp(updatedAt)) : "Sin foto guardada",
      progress,
      statusLine: progress.currentLabel
        ? `${progress.done}/${progress.total} · ${progress.currentLabel}`
        : `${progress.done}/${progress.total}`,
      coreLoading: (pending.optimize || pending.needs) && !state.optimize && !state.needs,
      refreshStatus,
      refreshPhase: refreshPhaseLabel(refreshStatus),
      refreshPct: refreshPctValue,
      refreshLine,
    };
  }, [
    state,
    pending,
    connecting,
    connectMessage,
    load,
    refresh,
    refreshPlan,
    connectAccount,
    markShellReady,
    refreshing,
    refreshError,
    refreshStatus,
    readAt,
    nowMs,
  ]);

  return <DashboardContext.Provider value={value}>{children}</DashboardContext.Provider>;
}

export function useDashboard(): DashboardContextValue {
  const ctx = useContext(DashboardContext);
  if (!ctx) throw new Error("useDashboard debe usarse dentro de DashboardProvider");
  return ctx;
}
