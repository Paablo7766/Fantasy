"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useDashboard } from "@/components/DashboardProvider";
import { endpoint, getJson } from "@/lib/api";
import { buildDataHealthReport, healthLevelLabel, type HealthLevel } from "@/lib/dataHealth";
import type { DataHealthField, DataHealthPayload } from "@/lib/types";

function tone(level: HealthLevel): string {
  if (level === "ok") return "badge badge--good";
  if (level === "warn") return "badge badge--warn";
  return "badge badge--bad";
}

function dotClass(level: HealthLevel): string {
  if (level === "ok") return "status-dot";
  if (level === "warn") return "status-dot status-dot--warn";
  return "status-dot status-dot--warn";
}

function fieldTone(status: string | undefined): string {
  if (status === "ok") return "badge badge--good";
  if (status === "caducada") return "badge badge--warn";
  if (status === "error") return "badge badge--bad";
  return "badge";
}

/** Campos del motor con su TTL: qué deja de ser fiable y cuándo caduca. */
function FieldHealthTable({ fields }: { fields: DataHealthField[] }) {
  const order = { error: 0, caducada: 1, no_leida: 2, ok: 3 } as Record<string, number>;
  const rows = [...fields].sort(
    (left, right) => (order[left.status] ?? 9) - (order[right.status] ?? 9) || left.label.localeCompare(right.label, "es"),
  );
  return (
    <div className="mt-2 overflow-x-auto rounded-xl border border-[color:var(--line)]">
      <table className="table-dense w-full min-w-[720px] text-left text-sm">
        <thead>
          <tr>
            <th>Campo</th>
            <th>Estado</th>
            <th>TTL</th>
            <th>Caduca</th>
            <th>Si falta</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((field) => (
            <tr key={field.id} className={field.status === "error" ? "bg-coral/[0.06]" : ""}>
              <td>
                <div className="font-medium">{field.label}</div>
                <div className="text-[11px] text-faint">{field.field}</div>
              </td>
              <td>
                <span className={fieldTone(field.status)}>{field.status.replace(/_/g, " ")}</span>
                {field.critical ? <span className="mt-1 block text-[10.5px] text-gold">crítico</span> : null}
              </td>
              <td className="text-muted">{field.ttl_label || "—"}</td>
              <td className="text-muted">{field.expires_label || "sin lectura"}</td>
              <td className="max-w-[280px] text-xs leading-5 text-muted">{field.impact}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DataHealthPanel() {
  const { state, trends, stale, photoAge, photoAgeSeconds } = useDashboard();
  const search = useSearchParams();
  const league = search.get("league");
  const report = useMemo(() => buildDataHealthReport(state), [state]);
  const [open, setOpen] = useState(false);
  const [fieldHealth, setFieldHealth] = useState<DataHealthPayload | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  useEffect(() => {
    if (!open || fieldHealth) return;
    let cancelled = false;
    getJson<DataHealthPayload>(endpoint("/api/data-health", league))
      .then((payload) => {
        if (!cancelled) setFieldHealth(payload);
      })
      .catch(() => {
        if (!cancelled) setFieldHealth({ ok: false, error: { message: "Sin /api/data-health." } });
      });
    return () => {
      cancelled = true;
    };
  }, [open, fieldHealth, league]);

  const fieldHealthLoading = open && fieldHealth === null;

  const level: HealthLevel = report?.level ?? (trends ? "warn" : "bad");
  const failCount = report?.sources.filter((s) => !s.ok).length ?? 0;

  return (
    <>
      <button
        type="button"
        className="btn btn-secondary inline-flex"
        onClick={() => setOpen(true)}
        disabled={!trends}
        title={trends ? "Estado de APIs y fuentes de datos" : "Carga el mercado para ver fuentes"}
        aria-haspopup="dialog"
      >
        <span className={`${dotClass(level)} !mr-1.5 !pl-0`}>Datos</span>
        <span className="font-mono tabular-nums">{report ? `${report.score}%` : "—"}</span>
      </button>

      <dialog
        ref={dialogRef}
        className="bid-dialog data-health-dialog"
        onClose={() => setOpen(false)}
        onClick={(event) => {
          if (event.target === dialogRef.current) setOpen(false);
        }}
      >
        <div className="bid-dialog__body max-h-[min(88vh,720px)] overflow-y-auto">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="eyebrow">Salud de datos</p>
              <h2 className="section-title mt-1">¿Confiar en las tesis ahora?</h2>
              <p className="section-support mt-1">
                APIs, scrapers y bloques del tablero. Si algo falla, el motor no inventa: falta dato o baja la confianza.
              </p>
            </div>
            <button type="button" className="btn btn-secondary !px-2.5 !py-1 text-xs" onClick={() => setOpen(false)}>
              Cerrar
            </button>
          </div>

          {!report ? (
            <p className="mt-6 text-sm text-muted">Sin lectura de mercado. Pulsa Actualizar para cargar fuentes.</p>
          ) : (
            <>
              <div className="mt-5 rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] p-4">
                <div className="flex flex-wrap items-center gap-3">
                  <span className={tone(report.level)}>{healthLevelLabel(report.level)}</span>
                  <span className="metric-value text-lg text-ink">{report.headline}</span>
                  <span className="ml-auto font-mono text-sm text-muted">Confianza {report.score}%</span>
                </div>
                {stale ? (
                  <p className="mt-2 text-xs text-gold">
                    Foto guardada{photoAge ? ` de ${photoAge}` : ""}. Nada se descarga hasta que pulses Actualizar.
                  </p>
                ) : photoAgeSeconds !== null ? (
                  <p className="mt-2 text-xs text-mint">Foto de {photoAge}. Sin descargas en curso.</p>
                ) : null}
                {trends?.partial && !trends?.optional_sources_degraded && report.sources.length > 0 ? (
                  <p className="mt-2 text-xs text-muted">Flag «lectura parcial» activo en el servidor.</p>
                ) : null}
                {trends?.optional_sources_degraded ? (
                  <p className="mt-2 text-xs text-muted">
                    Forma extra opcional incompleta; el núcleo de pujas no depende de FBref/Sofascore.
                  </p>
                ) : null}
              </div>

              {report.compromised.length ? (
                <section className="mt-5">
                  <h3 className="text-sm font-semibold text-ink">Qué puede estar comprometido</h3>
                  <ul className="mt-2 space-y-2 text-sm leading-5 text-muted">
                    {report.compromised.map((line) => (
                      <li key={line} className="rounded-lg bg-coral/10 px-3 py-2 text-ink">
                        {line}
                      </li>
                    ))}
                  </ul>
                </section>
              ) : (
                <p className="mt-5 text-sm text-mint">Ningún fallo grave detectado en fuentes críticas para esta lectura.</p>
              )}

              {report.notes.length ? (
                <section className="mt-4">
                  <h3 className="text-sm font-semibold text-ink">Notas</h3>
                  <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted">
                    {report.notes.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </section>
              ) : null}

              <section className="mt-5">
                <h3 className="text-sm font-semibold text-ink">Bloques del tablero</h3>
                <ul className="mt-2 grid gap-2 sm:grid-cols-2">
                  {report.blocks.map((block) => (
                    <li
                      key={block.id}
                      className="rounded-lg border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-3 py-2.5"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-medium">{block.label}</span>
                        <span className={block.ok ? "badge badge--good" : "badge badge--warn"}>
                          {block.ok ? "OK" : "Revisar"}
                        </span>
                      </div>
                      <p className="mt-1 text-xs leading-5 text-muted">{block.detail}</p>
                    </li>
                  ))}
                </ul>
              </section>

              {report.market ? (
                <section className="mt-5">
                  <h3 className="text-sm font-semibold text-ink">Mercado (esta sincronización)</h3>
                  <dl className="mt-2 grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
                    <div className="rounded-lg bg-[color:var(--surface)] px-3 py-2">
                      <dt className="text-[11px] text-faint">Listings</dt>
                      <dd className="metric-value">{report.market.listings}</dd>
                    </div>
                    <div className="rounded-lg bg-[color:var(--surface)] px-3 py-2">
                      <dt className="text-[11px] text-faint">Sin matching AF</dt>
                      <dd className="metric-value">{report.market.missingMatching}</dd>
                    </div>
                    <div className="rounded-lg bg-[color:var(--surface)] px-3 py-2">
                      <dt className="text-[11px] text-faint">Sin techo puja</dt>
                      <dd className="metric-value">{report.market.missingIdeal}</dd>
                    </div>
                    <div className="rounded-lg bg-[color:var(--surface)] px-3 py-2">
                      <dt className="text-[11px] text-faint">Sin puntos</dt>
                      <dd className="metric-value">{report.market.missingPoints}</dd>
                    </div>
                    <div className="rounded-lg bg-[color:var(--surface)] px-3 py-2">
                      <dt className="text-[11px] text-faint">Sin señal precio</dt>
                      <dd className="metric-value">{report.market.missingSignal}</dd>
                    </div>
                    <div className="rounded-lg bg-[color:var(--surface)] px-3 py-2">
                      <dt className="text-[11px] text-faint">«Sin motivo»</dt>
                      <dd className="metric-value">{report.market.sinMotivo}</dd>
                    </div>
                  </dl>
                </section>
              ) : null}

              <section className="mt-5">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h3 className="text-sm font-semibold text-ink">Campos y caducidad</h3>
                  {fieldHealthLoading && !fieldHealth ? (
                    <span className="text-xs text-muted">Leyendo caché…</span>
                  ) : fieldHealth?.headline ? (
                    <span className="text-xs text-muted">{fieldHealth.headline}</span>
                  ) : null}
                </div>
                {fieldHealth?.fields?.length ? (
                  <FieldHealthTable fields={fieldHealth.fields} />
                ) : (
                  <p className="mt-2 text-xs leading-5 text-muted">
                    {fieldHealth?.ok === false
                      ? "El endpoint de salud por campo no respondió: se muestran solo las fuentes del tablero."
                      : "Sin detalle por campo en esta lectura. El TTL sale de la caché local del servidor."}
                  </p>
                )}
              </section>

              <section className="mt-5">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h3 className="text-sm font-semibold text-ink">Fuentes ({report.sources.length})</h3>
                  {report.sources.length === 0 ? (
                    <span className="text-xs text-gold">Ninguna fuente en esta lectura</span>
                  ) : failCount ? (
                    <span className="text-xs text-coral">{failCount} con error</span>
                  ) : (
                    <span className="text-xs text-mint">Todas respondieron OK</span>
                  )}
                </div>
                <div className="mt-2 overflow-x-auto rounded-xl border border-[color:var(--line)]">
                  <table className="table-dense w-full min-w-[640px] text-left text-sm">
                    <thead>
                      <tr>
                        <th>Fuente</th>
                        <th>Estado</th>
                        <th className="text-right">Registros</th>
                        <th>Caché</th>
                        <th>Error / impacto</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.sources.length === 0 ? (
                        <tr>
                          <td colSpan={5} className="text-sm leading-5 text-muted">
                            La foto rápida no incluye scrapers. Cuando termine la sincronización completa aparecen AF,
                            Fútbol Fantasy, Understat y el motor propio.
                          </td>
                        </tr>
                      ) : null}
                      {report.sources.map((src) => (
                        <tr key={src.id} className={src.ok ? "" : "bg-coral/[0.06]"}>
                          <td>
                            <div className="font-medium">{src.label}</div>
                            <div className="text-[11px] text-faint">{src.group}</div>
                          </td>
                          <td>
                            <span className={src.ok ? "badge badge--good" : "badge badge--bad"}>
                              {src.ok ? "OK" : "Error"}
                            </span>
                          </td>
                          <td className="text-right font-mono tabular-nums">{src.count ?? "—"}</td>
                          <td className="text-muted">{src.fromCache ? "Sí" : "No"}</td>
                          <td className="max-w-[280px] text-xs leading-5 text-muted">
                            {src.error ? <span className="text-coral">{src.error}</span> : "—"}
                            {!src.ok && src.impacts.length ? (
                              <span className="mt-0.5 block text-faint">Afecta: {src.impacts.slice(0, 2).join("; ")}</span>
                            ) : null}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )}
        </div>
      </dialog>
    </>
  );
}
