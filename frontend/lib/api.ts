import type { ApiError } from "@/lib/types";
import { errorMessage } from "@/lib/format";
import { clientApiPath } from "@/lib/backendUrl";

// El navegador siempre llama al mismo origen (/api/...). Así se oculta la URL
// del backend. El proxy en app/api/[...path]/route.ts reenvía a Render (o a
// uvicorn en local) leyendo NEXT_PUBLIC_API_URL.

export function apiUrl(path: string, search?: URLSearchParams): string {
  return clientApiPath(path, search);
}

/**
 * URL de un bloque del tablero. **Nunca** lleva ``fresh``: los GET solo leen
 * la foto guardada. La descarga vive en ``POST /api/plan/refresh``.
 */
export function endpoint(
  path: string,
  league: string | null,
  opts?: { asyncRefresh?: boolean },
): string {
  const query = new URLSearchParams();
  if (league) query.set("league", league);
  if (opts?.asyncRefresh) query.set("async", "1");
  return apiUrl(path, query);
}

export async function getJson<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path);
  } catch {
    const error = new Error("No se pudo contactar con el servidor FastAPI.");
    (error as Error & { payload: ApiError }).payload = {
      ok: false,
      error: { code: "network", message: error.message },
    };
    throw error;
  }
  const data = (await response.json().catch(() => ({
    ok: false,
    error: { code: "invalid_json", message: `HTTP ${response.status}` },
  }))) as T & ApiError;
  if (!response.ok || data.ok === false) {
    const error = new Error(errorMessage(data));
    (error as Error & { payload: ApiError }).payload = data;
    throw error;
  }
  return data;
}

export async function postJsonBody<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = (await response.json().catch(() => ({
    ok: false,
    error: { message: `HTTP ${response.status}` },
  }))) as T & ApiError;
  if (!response.ok || data.ok === false) {
    throw new Error(errorMessage(data));
  }
  return data;
}

export async function postJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { method: "POST" });
  const data = (await response.json().catch(() => ({
    ok: false,
    error: { message: `HTTP ${response.status}` },
  }))) as T & ApiError;
  if (!response.ok || data.ok === false) {
    throw new Error(errorMessage(data));
  }
  return data;
}
