import type { ApiError } from "@/lib/types";
import { errorMessage } from "@/lib/format";

// El navegador siempre llama al mismo origen (/api/...). Así se oculta la URL
// del backend. El proxy en app/api/[...path]/route.ts reenvía a Render (o a
// uvicorn en local) leyendo NEXT_PUBLIC_API_URL.

export function apiUrl(path: string, search?: URLSearchParams): string {
  const suffix = search && search.toString() ? `?${search.toString()}` : "";
  return `${path}${suffix}`;
}

export function endpoint(path: string, fresh: boolean, league: string | null): string {
  const query = new URLSearchParams();
  if (league) query.set("league", league);
  if (fresh) query.set("fresh", "true");
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
