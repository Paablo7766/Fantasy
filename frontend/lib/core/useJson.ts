"use client";

import { useEffect, useState } from "react";
import { endpoint, getJson } from "@/lib/core/api";

/**
 * Última respuesta buena de cada endpoint: al volver a Liga se enseña al
 * instante y se refresca por detrás, en vez de esperar otra vez al servidor.
 */
const jsonCache = new Map<string, unknown>();

export function useJson<T>(path: string, league: string | null): T | null {
  const key = endpoint(path, league);
  const [loaded, setLoaded] = useState<{ key: string; payload: T } | null>(() => (jsonCache.has(key) ? { key, payload: jsonCache.get(key) as T } : null));
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      // Un 502/504 suele ser el backend reiniciándose o un arranque en frío:
      // se reintenta dos veces antes de rendirse.
      for (let attempt = 0; ; attempt += 1) {
        try {
          const payload = await getJson<T>(key);
          jsonCache.set(key, payload);
          if (!cancelled) setLoaded({ key, payload });
          return;
        } catch (reason: unknown) {
          if (attempt < 2 && !cancelled) {
            await new Promise((resolve) => setTimeout(resolve, 1500 * (attempt + 1)));
            continue;
          }
          if (cancelled || jsonCache.has(key)) return; // si hay copia buena, se queda esa
          // Se conserva el motivo (HTTP 500, sin conexión…) para poder enseñarlo.
          const sent = (reason as { payload?: unknown } | null)?.payload;
          const message = reason instanceof Error ? reason.message : "Sin respuesta";
          setLoaded({ key, payload: (sent && typeof sent === "object" ? sent : { ok: false, error: { message } }) as T });
          return;
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [key]);
  if (loaded && loaded.key === key) return loaded.payload;
  return jsonCache.has(key) ? (jsonCache.get(key) as T) : null;
}
