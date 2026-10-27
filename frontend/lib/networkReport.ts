// Reporte de red listo para pegar en un chat de IA.
//
// El panel de «Ritmo de llamadas» solo conoce lo que lleva en RAM desde el
// arranque. Para auditar de verdad hace falta la bitácora en disco
// (`.cache/network_logs.jsonl`), que sobrevive al reinicio. Aquí se pide
// `/api/diagnostics/network`, se resume el conteo de errores por fuente y se
// deja el JSON debajo en un bloque Markdown para que la IA lo pueda leer.

import type { NetworkDiagnosticsPayload, NetworkLogEntry } from "@/lib/types";

/** Lo que se copia al portapapeles: contexto en prosa + datos crudos. */
export function buildNetworkReport(payload: NetworkDiagnosticsPayload, now = new Date()): string {
  const calls = payload.calls || [];
  const errors = payload.errors || [];
  const lines: string[] = [];

  lines.push("## Auditoría de red — LALIGA Fantasy");
  lines.push("");
  lines.push(`- Generado: ${now.toISOString()}`);
  lines.push(`- Peticiones en este corte: ${calls.length} (de ${payload.count ?? calls.length} leídas, ${payload.scanned ?? calls.length} válidas)`);
  lines.push("- Solo llamadas reales: los aciertos de caché no se registran.");
  lines.push("- Cada reintento es una línea propia. URL sin query string (sin token).");
  lines.push("");

  if (errors.length === 0) {
    lines.push("### Errores por fuente");
    lines.push("");
    lines.push(calls.length === 0 ? "Sin llamadas registradas todavía." : "Ningún error (HTTP >= 400) en el último corte.");
  } else {
    lines.push("### Errores por fuente");
    lines.push("");
    lines.push("| Fuente | Total | Por status | Último |");
    lines.push("| --- | ---: | --- | --- |");
    for (const row of errors) {
      const mix = Object.entries(row.por_status || {})
        .map(([code, count]) => `${code}: ${count}`)
        .join(", ");
      lines.push(`| ${row.fuente} | ${row.total} | ${mix || "—"} | ${row.ultimo || "—"} |`);
    }
  }
  lines.push("");

  lines.push("### Llamadas (más reciente primero)");
  lines.push("");
  if (calls.length === 0) {
    lines.push("`network_logs.jsonl` no tiene entradas todavía.");
  } else {
    lines.push("| Timestamp | Fuente | Método | Status | ms | URL |");
    lines.push("| --- | --- | --- | ---: | ---: | --- |");
    for (const row of calls) {
      lines.push(
        `| ${row.timestamp || "—"} | ${row.fuente || "—"} | ${row.metodo || "GET"} | ${row.status ?? "red"} | ${formatMs(row.duracion_ms)} | ${row.url || "—"} |`,
      );
    }
  }
  lines.push("");

  if (payload.notes?.length) {
    lines.push("### Notas");
    lines.push("");
    for (const note of payload.notes) lines.push(`- ${note}`);
    lines.push("");
  }

  lines.push("### JSON crudo");
  lines.push("");
  lines.push("```json");
  lines.push(JSON.stringify({ calls, errors }, null, 2));
  lines.push("```");
  return lines.join("\n");
}

function formatMs(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${Math.round(value)}`;
}

/** Texto de una fila individual, para depurar desde la consola si hiciera falta. */
export function networkEntryLine(row: NetworkLogEntry): string {
  return `${row.timestamp} ${row.fuente} ${row.metodo} ${row.status ?? "red"} ${formatMs(row.duracion_ms)} ms`;
}
