/**
 * Normaliza la URL base del backend (Render, uvicorn local, túnel…).
 * Debe ser solo el origen: `https://fantasy-api.onrender.com`, sin `/api` final
 * ni barras sobrantes (evita `…/api/api/plan` o `https://host//api/plan`).
 */
export function normalizeBackendOrigin(raw: string | undefined | null): string | null {
  if (raw == null) return null;
  let base = raw.trim();
  if (!base) return null;

  base = base.replace(/\/+$/, "");
  if (base.endsWith("/api")) {
    base = base.slice(0, -4);
    base = base.replace(/\/+$/, "");
  }
  if (!base) return null;
  return base;
}

/** Une origen del backend con la ruta que llega al proxy (`/api/...`). */
export function backendProxyTarget(
  rawBase: string,
  pathname: string,
  search: string,
): URL {
  const base = normalizeBackendOrigin(rawBase);
  if (!base) {
    throw new Error("Backend base URL vacía o inválida.");
  }
  const path = pathname.startsWith("/") ? pathname : `/${pathname}`;
  const safePath = path.replace(/\/{2,}/g, "/");
  return new URL(`${safePath}${search}`, `${base}/`);
}

/** Rutas relativas del navegador hacia el proxy de Next (`/api/...`). */
export function clientApiPath(path: string, search?: URLSearchParams): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  const safePath = normalized.replace(/\/{2,}/g, "/");
  const suffix = search && search.toString() ? `?${search.toString()}` : "";
  return `${safePath}${suffix}`;
}
