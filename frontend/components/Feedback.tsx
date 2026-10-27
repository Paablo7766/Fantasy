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
  const offline = code === "offline_miss" || code === "offline";
  const message = auth && brief ? "Inicia sesión para cargar este bloque." : errorMessage(payload);
  const hint = auth
    ? "Pulsa Conectar cuenta con 1 clic y elige tu cuenta de Google."
    : offline
      ? "Aún no hay ninguna foto guardada. Pulsa Actualizar para descargar la primera: la lectura nunca descarga sola."
      : code === "optimize_missing"
        ? "La foto guardada no trae once calculado. Pulsa Actualizar y se recalcula con la plantilla que hay en disco."
        : "Prueba a actualizar. Si la API limita las peticiones, espera un momento.";
  return (
    <article className={glass("p-5 md:p-6 reveal")} role="alert">
      <div className="flex items-start gap-3">
        <span
          className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-[color:var(--coral-soft)] text-coral"
          aria-hidden="true"
        >
          <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.6">
            <circle cx="8" cy="8" r="6.2" />
            <path d="M8 5v3.5M8 11.2h.01" strokeLinecap="round" />
          </svg>
        </span>
        <div className="min-w-0">
          <p className="eyebrow">{title}</p>
          <h2 className="mt-1.5 text-base font-medium tracking-tight text-coral md:text-lg">{message}</h2>
          {!(brief && auth) ? <p className="mt-2 text-sm leading-6 text-muted">{hint}</p> : null}
        </div>
      </div>
    </article>
  );
}

export function Skeleton({ title, rows = 4 }: { title: string; rows?: number }) {
  return (
    <article className={glass("p-5")} aria-busy="true" aria-label={`Cargando ${title}`}>
      <p className="eyebrow">{title}</p>
      <div className="mt-1 h-5 w-40 skeleton-bar" />
      <div className="mt-5 space-y-2.5">
        {Array.from({ length: rows }, (_, index) => (
          <div
            key={index}
            className="skeleton-bar h-11"
            style={{ opacity: 1 - index * 0.08, animationDelay: `${index * 80}ms` }}
          />
        ))}
      </div>
    </article>
  );
}
