import { getJson } from "@/lib/core/api";

/**
 * Caché de lecturas GET en memoria del navegador (vive mientras la pestaña
 * esté abierta). Sirve para que el Laboratorio pinte al instante lo último
 * que vio y refresque por detrás: cada panel se desmonta al cambiar de
 * pestaña y, sin esto, volvía a esperar al servidor cada vez.
 *
 * - `peekJson(url)`: lo guardado, o undefined. Síncrono: úsalo en useState.
 * - `cachedJson(url)`: pide al servidor y guarda. Si ya hay una petición en
 *   vuelo a esa URL, devuelve esa misma promesa (no duplica llamadas).
 * - `prefetchJson(urls)`: lanza las que no estén ni guardadas ni en vuelo.
 */
const store = new Map<string, unknown>();
const inflight = new Map<string, Promise<unknown>>();

export function peekJson<T>(url: string): T | undefined {
  return store.get(url) as T | undefined;
}

export function cachedJson<T>(url: string): Promise<T> {
  const running = inflight.get(url);
  if (running) return running as Promise<T>;
  const request = getJson<T>(url)
    .then((data) => {
      store.set(url, data);
      return data;
    })
    .finally(() => {
      inflight.delete(url);
    });
  inflight.set(url, request);
  return request;
}

export function prefetchJson(urls: string[]): void {
  for (const url of urls) {
    if (store.has(url) || inflight.has(url)) continue;
    void cachedJson(url).catch(() => undefined);
  }
}
