"use client";

import { points } from "@/lib/core/format";
import { photoFor, type PhotoIndex } from "@/lib/core/photoIndex";
import { AdvisorRow, Meter, type Fact } from "@/components/inicio/ui";
import type { ClausulaEnPeligro, ClausulazoSugerido, VeredictoClausulazo, VeredictoProteger } from "@/lib/types";

const RIESGO = {
  ALTO: { label: "Riesgo alto", color: "var(--ini-red)" },
  MEDIO: { label: "Riesgo medio", color: "var(--ini-amber)" },
  BAJO: { label: "Vigilar", color: "rgba(255,255,255,0.4)" },
} as const;

const PROTEGER: Record<VeredictoProteger, { label: string; color: string }> = {
  PROTEGER_YA: { label: "Sube la cláusula", color: "var(--ini-mint)" },
  PROTEGER_PARCIAL: { label: "Sube un poco", color: "var(--ini-amber)" },
  SIN_CAJA: { label: "No te llega", color: "var(--ini-red)" },
  VENDER_ANTES: { label: "Vende antes", color: "var(--ini-sky)" },
  ASUMIR: { label: "Asúmelo", color: "rgba(255,255,255,0.55)" },
};

const CLAUSULAZO: Record<VeredictoClausulazo, { label: string; color: string }> = {
  CLAUSULAR_YA: { label: "Clausula ya", color: "var(--ini-mint)" },
  PROGRAMAR: { label: "Prográmalo", color: "var(--ini-sky)" },
  SIN_CAJA: { label: "Te falta caja", color: "var(--ini-red)" },
  OPORTUNIDAD: { label: "Oportunidad", color: "var(--ini-amber)" },
  GOLPE_RIVAL: { label: "Golpe al rival", color: "var(--ini-violet)" },
};

export function money(value: number): string {
  const digits = Math.abs(value) >= 10_000_000 ? 1 : 2;
  return `${(value / 1_000_000).toLocaleString("es-ES", { minimumFractionDigits: digits, maximumFractionDigits: digits })} M€`;
}

export function signedPct(value: number): string {
  return `${value >= 0 ? "+" : "−"}${Math.abs(value).toLocaleString("es-ES", { maximumFractionDigits: 1 })}%`;
}

function pos(value: string | null | undefined): string {
  return value ? value.slice(0, 3).toUpperCase() : "—";
}

/** Tu jugador en peligro: cláusula actual frente a la perfecta; la muesca ámbar es la caja del rival más rico. */
export function DangerRow({ row, photos, index }: { row: ClausulaEnPeligro; photos: PhotoIndex; index: number }) {
  const verdict = PROTEGER[row.veredicto_codigo] ?? PROTEGER.ASUMIR;
  const risk = RIESGO[row.riesgo];
  const perfecta = row.clausula_perfecta?.clausula_objetivo ?? row.clausula_actual;
  const best = row.subida_recomendada ?? (row.veredicto_codigo === "SIN_CAJA" ? row.clausula_perfecta : null);
  const bench = row.tu_once_pierde_sin_el < 0.05;
  const facts: Fact[] = [];
  if (row.clausula_perfecta) facts.push({ label: "Cláusula perfecta", value: money(perfecta) });
  if (best && best.subida_eur > 0) facts.push({ label: "Subir", value: `+${money(best.subida_eur)}`, tone: "var(--ini-copper)" });
  if (best && best.coste_eur > 0) facts.push({ label: "Coste", value: money(best.coste_eur) });
  facts.push({
    label: "Pueden pagarla",
    value: `${row.rivales_que_pueden_pagar} de ${row.rivales_total}`,
    tone: row.rivales_que_pueden_pagar ? "var(--ini-red)" : undefined,
  });
  if (row.rival_mas_rico) facts.push({ label: "Rival más rico", value: money(row.rival_mas_rico.caja) });
  facts.push({ label: "Tu once pierde", value: bench ? "Nada · suplente" : `−${points(row.tu_once_pierde_sin_el)} pts`, tone: bench ? undefined : "var(--ini-red)" });

  return (
    <AdvisorRow
      index={index}
      name={row.nombre}
      sub={`${pos(row.posicion)} · ${risk.label}`}
      imageUrl={photoFor(photos, row.player_id, row.nombre)}
      ring={risk.color}
      verdict={verdict}
      value={money(row.clausula_actual)}
      meter={<Meter value={row.clausula_actual} reference={perfecta} good={row.clausula_actual >= perfecta} mark={row.rival_mas_rico?.caja ?? null} />}
      facts={facts}
      reason={row.motivo_detallado}
      extra={
        row.niveles.length > 1 ? (
          <ul className="mt-3 overflow-hidden rounded-xl border border-[var(--ini-line)] text-[12.5px] tabular-nums">
            {row.niveles.map((nivel) => (
              <li key={nivel.clausula_objetivo} className="flex items-center justify-between gap-3 border-t border-[var(--ini-line)] px-3 py-2 first:border-t-0">
                <span className="text-white/75">
                  {money(nivel.clausula_objetivo)}
                  <span className="ml-2 text-white/40">
                    cubre {nivel.rivales_cubiertos} de {nivel.rivales_cubiertos + nivel.rivales_sin_cubrir}
                  </span>
                </span>
                <span style={{ color: nivel.viable ? "#fff" : "var(--ini-red)" }}>
                  {money(nivel.coste_eur)}
                  {nivel.viable ? "" : " · sin caja"}
                </span>
              </li>
            ))}
          </ul>
        ) : null
      }
    />
  );
}

/** Clausulazo sugerido: precio frente a su valor justo. */
export function RaidRow({ row, photos, index }: { row: ClausulazoSugerido; photos: PhotoIndex; index: number }) {
  const verdict = CLAUSULAZO[row.veredicto_codigo] ?? CLAUSULAZO.OPORTUNIDAD;
  const margin = row.margen_valor_justo_pct;
  const pct = row.prevision_7d_pct;
  const facts: Fact[] = [];
  if (row.valor_justo) facts.push({ label: "Valor justo", value: money(row.valor_justo) });
  if (typeof margin === "number") {
    facts.push({
      label: margin >= 0 ? "Bajo su justo" : "Sobre su justo",
      value: `${Math.abs(Math.round(margin))}%`,
      tone: margin >= 0 ? "var(--ini-mint)" : "var(--ini-red)",
    });
  }
  if (row.mejora_once > 0) facts.push({ label: "Mejora del once", value: `+${points(row.mejora_once)} pts`, tone: "var(--ini-mint)" });
  facts.push({ label: "Puntos esperados", value: `${points(row.xp_jornada)} pts` });
  if (typeof pct === "number") facts.push({ label: "Previsión 7 días", value: signedPct(pct), tone: pct >= 0 ? "var(--ini-mint)" : "var(--ini-red)" });
  if (row.rivales_que_pueden_quitartelo) facts.push({ label: "Rivales con caja", value: String(row.rivales_que_pueden_quitartelo), tone: "var(--ini-red)" });

  return (
    <AdvisorRow
      index={index}
      name={row.nombre}
      sub={`${pos(row.posicion)}${row.propietario ? ` · ${row.propietario}` : ""} · ${row.abierta_ahora ? "Abierta" : `Se abre ${row.cuando}`}`}
      imageUrl={photoFor(photos, row.player_id, row.nombre)}
      ring={verdict.color}
      verdict={verdict}
      value={money(row.clausula_eur)}
      meter={row.valor_justo ? <Meter value={row.clausula_eur} reference={row.valor_justo} good={row.clausula_eur <= row.valor_justo} /> : null}
      facts={facts}
      reason={row.motivo_detallado}
    />
  );
}
