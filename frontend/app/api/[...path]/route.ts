import { connection, NextRequest, NextResponse } from "next/server";

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

  let response: Response;
  try {
    response = await fetch(target, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer(),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json(
      { ok: false, error: { code: "network", message: "No se pudo contactar con el backend en Render." } },
      { status: 502 },
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
