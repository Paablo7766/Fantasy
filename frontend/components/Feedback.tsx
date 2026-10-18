import { errorMessage, glass } from "@/lib/format";
import type { ApiError } from "@/lib/types";

export function ErrorCard({
  title,
  payload,
  brief = false,
}: {
  title: string;
  payload: ApiError | null | undefined;
  brief?: boolean;
}) {
  const code = payload?.error?.code || "";
  const auth = code === "auth_required" || code === "unauthorized";
  const message = auth && brief ? "Inicia sesión para cargar este bloque." : errorMessage(payload);
  const hint = auth
    ? "Pulsa Conectar cuenta con 1 clic y elige tu cuenta de Google."
    : "Prueba a actualizar. Si la API limita las peticiones, espera un momento.";
  return (
    <article className={glass("p-6")}>
      <p className="text-[11px] uppercase tracking-[0.18em] text-white/40">{title}</p>
      <h2 className="mt-2 text-lg text-coral">{message}</h2>
      {!(brief && auth) ? <p className="mt-2 text-sm text-white/55">{hint}</p> : null}
    </article>
  );
}

export function Skeleton({ title, rows = 4 }: { title: string; rows?: number }) {
  return (
    <article className={glass("p-4")} aria-busy="true">
      <p className="text-[11px] uppercase tracking-[0.18em] text-white/40">{title}</p>
      <div className="mt-4 space-y-2">
        {Array.from({ length: rows }, (_, index) => (
          <div key={index} className="h-12 animate-pulse rounded-2xl bg-white/5" />
        ))}
      </div>
    </article>
  );
}
