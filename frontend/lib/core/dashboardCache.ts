import type { DashboardState } from "@/lib/types";

const STORAGE_KEY = "fantasy.dashboard.v5";

type StoredDashboard = {
  savedAt: number;
  league: string | null;
  state: DashboardState;
};

export type DashboardSnapshot = {
  savedAt: number | null;
  state: DashboardState;
};

function leagueKey(league: string | null): string {
  return league?.trim() || "";
}

export function readDashboardSnapshot(league: string | null): DashboardSnapshot | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredDashboard;
    if (!parsed || typeof parsed !== "object" || !parsed.state) return null;
    if (leagueKey(parsed.league) !== leagueKey(league)) return null;
    return {
      savedAt: typeof parsed.savedAt === "number" ? parsed.savedAt : null,
      state: parsed.state,
    };
  } catch {
    return null;
  }
}

export function readDashboardCache(league: string | null): DashboardState | null {
  return readDashboardSnapshot(league)?.state ?? null;
}

export function readDashboardSavedAt(league: string | null): number | null {
  return readDashboardSnapshot(league)?.savedAt ?? null;
}

export function writeDashboardCache(league: string | null, state: DashboardState): void {
  if (typeof window === "undefined") return;
  try {
    const payload: StoredDashboard = {
      savedAt: Date.now(),
      league,
      state,
    };
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  } catch {
    /* quota / private mode */
  }
}

export function writeDashboardBlock<K extends keyof DashboardState>(
  league: string | null,
  name: K,
  value: DashboardState[K],
): void {
  if (typeof window === "undefined") return;
  if (!value || (typeof value === "object" && "ok" in value && value.ok === false)) return;
  // Los bloques llegan casi a la vez: se juntan y se escribe una sola vez
  // (leer, parsear y serializar el tablero entero por bloque bloqueaba el hilo).
  if (pendingLeague !== league) flushPendingBlocks();
  pendingLeague = league;
  pendingBlocks[name] = value;
  if (flushTimer === null) flushTimer = window.setTimeout(flushPendingBlocks, 250);
}

let pendingLeague: string | null = null;
let pendingBlocks: Partial<DashboardState> = {};
let flushTimer: number | null = null;

function flushPendingBlocks(): void {
  if (flushTimer !== null) {
    window.clearTimeout(flushTimer);
    flushTimer = null;
  }
  if (Object.keys(pendingBlocks).length === 0) return;
  const blocks = pendingBlocks;
  pendingBlocks = {};
  const current = readDashboardCache(pendingLeague) || {
    optimize: null,
    trends: null,
    squads: null,
    needs: null,
    plan: null,
  };
  writeDashboardCache(pendingLeague, { ...current, ...blocks });
}

if (typeof window !== "undefined") {
  window.addEventListener("pagehide", flushPendingBlocks);
}
