import { connection, NextRequest, NextResponse } from "next/server";

export const maxDuration = 300;

async function proxy(request: NextRequest): Promise<NextResponse> {
  await connection();
  const base = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (!base) {
    return NextResponse.json(
      {
        ok: false,
        error: {
          code: "network",
          message:
            "NEXT_PUBLIC_API_URL no está disponible. En local apunta a uvicorn (p. ej. http://127.0.0.1:8000); en Vercel, al dominio público de Render.",
        },
      },
      { status: 503 },
    );
  }

  const target = new URL(
    `${request.nextUrl.pathname}${request.nextUrl.search}`,
    base.endsWith("/") ? base : `${base}/`,
  );
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("content-length");
  // El backend del VPS exige X-Remote-Token para POST /api/plan/refresh. El
  // token vive solo en el servidor de Next (`REMOTE_REFRESH_TOKEN`), nunca en
  // el bundle del navegador: se inyecta aquí si el cliente no lo mandó ya.
  const remoteToken = process.env.REMOTE_REFRESH_TOKEN?.trim();
  if (remoteToken && !headers.has("x-remote-token")) {
    headers.set("x-remote-token", remoteToken);
  }

  let response: Response;
  try {
    response = await fetch(target, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer(),
      cache: "no-store",
      // Cold start del tablero (LALIGA + scrapers) puede pasar de 1 min.
      signal: AbortSignal.timeout(300_000),
    });
  } catch (reason) {
    const timedOut =
      reason instanceof Error &&
      (reason.name === "TimeoutError" || reason.name === "AbortError" || /timeout/i.test(reason.message));
    return NextResponse.json(
      {
        ok: false,
        error: {
          code: timedOut ? "timeout" : "network",
          message: timedOut
            ? "El backend tardó demasiado. Si uvicorn está arrancado, espera un momento y pulsa Actualizar."
            : "No se pudo contactar con el backend. En local, arranca uvicorn en el puerto 8000 (start_backend.bat).",
        },
      },
      { status: timedOut ? 504 : 502 },
    );
  }

  const outbound = new Headers();
  const contentType = response.headers.get("content-type");
  if (contentType) outbound.set("content-type", contentType);
  return new NextResponse(response.body, { status: response.status, headers: outbound });
}

export function GET(request: NextRequest) {
  return proxy(request);
}

export function POST(request: NextRequest) {
  return proxy(request);
}
