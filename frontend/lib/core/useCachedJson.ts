"use client";

import { useEffect, useState } from "react";
import { cachedJson, peekJson } from "@/lib/core/jsonCache";

/**
 * Lectura GET con caché compartida: devuelve al instante lo guardado (si lo
 * hay) y refresca por detrás. ``null`` solo mientras no hay nada que pintar.
 * Un fallo se devuelve como ``{ ok: false, error }`` para que la vista lo diga.
 */
export function useCachedJson<T>(url: string): T | null {
  const [data, setData] = useState<{ url: string; value: T } | null>(() => {
    const cached = peekJson<T>(url);
    return cached ? { url, value: cached } : null;
  });
  useEffect(() => {
    let cancelled = false;
    cachedJson<T>(url)
      .then((value) => {
        if (!cancelled) setData({ url, value });
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        const message = reason instanceof Error ? reason.message : "Sin datos.";
        setData((prev) => (prev && prev.url === url ? prev : { url, value: { ok: false, error: { message } } as T }));
      });
    return () => {
      cancelled = true;
    };
  }, [url]);
  return data && data.url === url ? data.value : null;
}
