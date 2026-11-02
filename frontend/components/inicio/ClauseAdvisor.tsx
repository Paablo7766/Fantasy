"use client";

import { useState } from "react";
import { PlayerAvatar } from "@/components/ui/PlayerAvatar";
import { points } from "@/lib/core/format";
import { photoFor, type PhotoIndex } from "@/lib/core/photoIndex";
import type {
  AsesorClausulas,
  ClausulaEnPeligro,
  ClausulazoSugerido,
  VeredictoClausulazo,
  VeredictoProteger,
} from "@/lib/types";

const RIESGO = {
  ALTO: { label: "Riesgo alto", color: "#FC734D" },
  MEDIO: { label: "Riesgo medio", color: "#F59E0B" },
  BAJO: { label: "Vigilar", color: "#8B9EB0" },
} as const;

const PROTEGER: Record<VeredictoProteger, { label: string; color: string }> = {
  PROTEGER_YA: { label: "SUBE LA CLÁUSULA", color: "#10B981" },
  PROTEGER_PARCIAL: { label: "SUBE UN POCO", color: "#F59E0B" },
  SIN_CAJA: { label: "NO TE LLEGA LA CAJA", color: "#FC734D" },
  VENDER_ANTES: { label: "VENDE ANTES", color: "#0297DE" },
  ASUMIR: { label: "PUEDES ASUMIRLO", color: "#8B9EB0" },
};

const CLAUSULAZO: Record<VeredictoClausulazo, { label: string; color: string }> = {
  CLAUSULAR_YA: { label: "CLAUSULA YA", color: "#10B981" },
  PROGRAMAR: { label: "PROGRAMA", color: "#0297DE" },
  SIN_CAJA: { label: "TE FALTA CAJA", color: "#FC734D" },
  OPORTUNIDAD: { label: "OPORTUNIDAD DE VALOR", color: "#F59E0B" },
  GOLPE_RIVAL: { label: "GOLPE AL RIVAL", color: "#FC734D" },
};

function money(value: number): string {
  const abs = Math.abs(value);
  const digits = abs >= 10_000_000 ? 1 : 2;
  return `${(value / 1_000_000).toLocaleString("es-ES", { minimumFractionDigits: digits, maximumFractionDigits: digits })} M€`;
}

function signedPct(value: number): string {
  return `${value >= 0 ? "+" : "−"}${Math.abs(value).toLocaleString("es-ES", { maximumFractionDigits: 1 })}%`;
}

function Chip({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-lg bg-white/[0.05] px-2 py-1 text-[11px] tabular-nums">
      <span className="text-white/45">{label}</span>
      <span className="font-semibold" style={tone ? { color: tone } : undefined}>
        {value}
      </span>
    </span>
  );
}

function Verdict({ label, color }: { label: string; color: string }) {
  return (
    <span className="inline-flex rounded-md px-2 py-1 text-[10.5px] font-bold tracking-wide" style={{ color, background: `${color}22` }}>
      {label}
    </span>
  );
}

function Advice({ text }: { text: string }) {
  return <p className="mt-3 rounded-xl bg-black/20 px-3 py-2.5 text-[12.5px] leading-[1.45] text-[#8B9EB0]">{text}</p>;
}

/** Barra de la cláusula actual frente a la perfecta; la marca blanca es la caja del rival más rico. */
function ClauseGauge({ row }: { row: ClausulaEnPeligro }) {
  const perfecta = row.clausula_perfecta?.clausula_objetivo ?? row.clausula_actual;
  const tope = Math.max(perfecta, row.clausula_actual, 1);
  const actual = Math.min(100, (row.clausula_actual / tope) * 100);
  const rico = row.rival_mas_rico ? Math.min(100, (row.rival_mas_rico.caja / tope) * 100) : null;
  const protegida = row.clausula_actual >= perfecta;
  return (
    <div className="mt-3">
      <div className="relative h-2 rounded-full bg-white/[0.08]">
        <div
          className="absolute inset-y-0 left-0 rounded-full"
          style={{
            width: `${actual}%`,
            background: protegida ? "#10B981" : "linear-gradient(90deg, #FC734D, #FF9A5A)",
          }}
        />
        {rico !== null ? (
          <span
            className="absolute -top-1 h-4 w-[2px] rounded-full bg-white"
            style={{ left: `${rico}%` }}
            title={`Caja del rival más rico: ${money(row.rival_mas_rico?.caja ?? 0)}`}
          />
        ) : null}
      </div>
      <div className="mt-1.5 flex items-center justify-between text-[11px] tabular-nums text-white/45">
        <span>Ahora {money(row.clausula_actual)}</span>
        {row.clausula_perfecta ? <span>Perfecta {money(row.clausula_perfecta.clausula_objetivo)}</span> : null}
      </div>
    </div>
  );
}

function DangerCard({ row, photos, index }: { row: ClausulaEnPeligro; photos: PhotoIndex; index: number }) {
  const [open, setOpen] = useState(false);
  const verdict = PROTEGER[row.veredicto_codigo] ?? PROTEGER.ASUMIR;
  const risk = RIESGO[row.riesgo];
  // Solo se enseña el coste de subir cuando es la recomendación o cuando es lo que no te llega a pagar.
  const best = row.subida_recomendada ?? (row.veredicto_codigo === "SIN_CAJA" ? row.clausula_perfecta : null);
  return (
    <article className="home-glass row-in p-4" style={{ animationDelay: `${index * 30}ms` }}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <PlayerAvatar
            player={{ name: row.nombre, image_url: photoFor(photos, row.player_id, row.nombre) }}
            size="sm"
            className="!h-10 !w-10 !text-[11px] !ring-0 border border-white/[0.12]"
          />
          <div className="min-w-0">
            <p className="truncate text-[15.5px] font-medium leading-tight text-white">{row.nombre}</p>
            <p className="mt-0.5 text-[12.5px] text-white/50">
              {row.posicion ? row.posicion.slice(0, 3).toUpperCase() : "—"}
              {row.en_xi ? " · Titular" : " · Banquillo"}
            </p>
          </div>
        </div>
        <span
          className="inline-flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1 text-[11px] font-semibold"
          style={{ color: risk.color, background: `${risk.color}22` }}
        >
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: risk.color }} />
          {risk.label}
        </span>
      </div>

      <ClauseGauge row={row} />

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        <Verdict label={verdict.label} color={verdict.color} />
        {best && best.subida_eur > 0 ? <Chip label="Subir" value={`+${money(best.subida_eur)}`} tone="#FF9A5A" /> : null}
        {best && best.coste_eur > 0 ? <Chip label="Coste" value={money(best.coste_eur)} /> : null}
        <Chip
          label="Pueden pagarla"
          value={`${row.rivales_que_pueden_pagar}/${row.rivales_total}`}
          tone={row.rivales_que_pueden_pagar ? "#FC734D" : undefined}
        />
        <Chip
          label="Impacto XI"
          value={row.tu_once_pierde_sin_el < 0.05 ? "Suplente" : `−${points(row.tu_once_pierde_sin_el)} pts`}
          tone={row.tu_once_pierde_sin_el < 0.05 ? undefined : "#FC734D"}
        />
      </div>

      <Advice text={row.motivo_detallado} />

      {row.niveles.length > 1 ? (
        <>
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            className="mt-2 text-[12.5px] font-medium text-[#FF9A5A]"
          >
            {open ? "Ocultar niveles" : "Ver niveles de protección"}
          </button>
          {open ? (
            <ul className="row-in mt-2 divide-y divide-white/[0.06] rounded-xl bg-black/20 px-3">
              {row.niveles.map((nivel) => (
                <li key={nivel.clausula_objetivo} className="flex items-center justify-between gap-3 py-2 text-[12.5px] tabular-nums">
                  <span className="text-white/70">
                    {money(nivel.clausula_objetivo)}
                    <span className="ml-2 text-white/40">
                      cubre {nivel.rivales_cubiertos} de {nivel.rivales_cubiertos + nivel.rivales_sin_cubrir}
                    </span>
                  </span>
                  <span className={nivel.viable ? "text-white" : "text-[#FC734D]"}>
                    {money(nivel.coste_eur)}
                    {nivel.viable ? "" : " · sin caja"}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
        </>
      ) : null}
    </article>
  );
}

function RaidCard({ row, photos, index }: { row: ClausulazoSugerido; photos: PhotoIndex; index: number }) {
  const verdict = CLAUSULAZO[row.veredicto_codigo] ?? CLAUSULAZO.OPORTUNIDAD;
  const margin = row.margen_valor_justo_pct;
  const pct = row.prevision_7d_pct;
  return (
    <article className="home-glass row-in p-4" style={{ animationDelay: `${index * 30}ms` }}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <PlayerAvatar
            player={{ name: row.nombre, image_url: photoFor(photos, row.player_id, row.nombre) }}
            size="sm"
            className="!h-10 !w-10 !text-[11px] !ring-0 border border-white/[0.12]"
          />
          <div className="min-w-0">
            <p className="truncate text-[15.5px] font-medium leading-tight text-white">{row.nombre}</p>
            <p className="mt-0.5 truncate text-[12.5px] text-white/50">
              {row.posicion ? row.posicion.slice(0, 3).toUpperCase() : "—"}
              {row.propietario ? ` · de ${row.propietario}` : ""}
            </p>
          </div>
        </div>
        <div className="shrink-0 text-right">
          <p className="text-[1.3rem] font-semibold leading-none tabular-nums text-white">{money(row.clausula_eur)}</p>
          {typeof margin === "number" ? (
            <p className="mt-1.5">
              <span
                className="inline-flex rounded-md px-1.5 py-0.5 text-[11px] font-semibold tabular-nums"
                style={{
                  color: margin >= 0 ? "#10B981" : "#FC734D",
                  background: margin >= 0 ? "rgba(16,185,129,0.14)" : "rgba(252,115,77,0.14)",
                }}
              >
                {margin >= 0 ? `${Math.round(margin)}% bajo su justo` : `${Math.abs(Math.round(margin))}% sobre su justo`}
              </span>
            </p>
          ) : null}
          {row.valor_justo ? <p className="mt-1 text-[11.5px] tabular-nums text-white/45">Justo: {money(row.valor_justo)}</p> : null}
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        <Verdict label={verdict.label} color={verdict.color} />
        <span
          className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] font-semibold tabular-nums"
          style={{ color: row.abierta_ahora ? "#10B981" : "#0297DE", background: row.abierta_ahora ? "rgba(16,185,129,0.12)" : "rgba(2,151,222,0.12)" }}
        >
          {row.abierta_ahora ? "Abierta ahora" : `Se abre ${row.cuando}`}
        </span>
        {row.mejora_once > 0 ? <Chip label="Once" value={`+${points(row.mejora_once)} pts`} tone="#0297DE" /> : null}
        <Chip label="xP" value={`${points(row.xp_jornada)} pts`} />
        {typeof pct === "number" ? <Chip label="7 días" value={signedPct(pct)} tone={pct >= 0 ? "#10B981" : "#FC734D"} /> : null}
        {typeof row.roi_pts_por_millon === "number" && row.mejora_once > 0 ? (
          <Chip label="ROI" value={`${row.roi_pts_por_millon.toLocaleString("es-ES", { maximumFractionDigits: 2 })} pts/M€`} />
        ) : null}
        {row.rivales_que_pueden_quitartelo ? (
          <Chip label="Rivales con caja" value={String(row.rivales_que_pueden_quitartelo)} tone="#FC734D" />
        ) : null}
      </div>

      <Advice text={row.motivo_detallado} />
    </article>
  );
}

export function ClauseAdvisor({ data, photos }: { data: AsesorClausulas; photos: PhotoIndex }) {
  const { resumen, proteger, clausulazos } = data;
  const bits: string[] = [
    `En peligro: ${resumen.en_peligro}${resumen.riesgo_alto ? ` (${resumen.riesgo_alto} de riesgo alto)` : ""}`,
  ];
  if (resumen.coste_proteger_eur > 0) bits.push(`Proteger todo: ${money(resumen.coste_proteger_eur)}`);
  bits.push(
    resumen.ventana_abierta
      ? resumen.ventana_cierra
        ? `Ventana abierta hasta ${resumen.ventana_cierra}`
        : "Hora de cierre sin datos"
      : "Ventana cerrada",
  );
  return (
    <div className="flex flex-col gap-7">
      <p className="inline-flex max-w-full flex-wrap items-center gap-x-4 gap-y-0.5 self-start rounded-2xl border border-white/[0.07] bg-white/[0.04] px-3 py-1.5 text-[12px] tabular-nums text-white/60">
        {bits.map((bit) => (
          <span key={bit}>{bit}</span>
        ))}
      </p>

      <section aria-label="Tus jugadores en peligro" className="flex flex-col gap-3">
        <div className="px-1">
          <h3 className="text-[1.15rem] font-semibold tracking-tight text-white">Tus jugadores en peligro</h3>
          <p className="mt-0.5 text-[13px] text-white/50">
            {proteger.length
              ? "Cuánto subirles la cláusula para que ningún rival con caja pueda pagarla."
              : resumen.seguros || resumen.bloqueadas
                ? "Ningún rival puede pagar hoy la cláusula de tus jugadores."
                : "Sin cláusulas que revisar."}
          </p>
        </div>
        {proteger.map((row, index) => (
          <DangerCard key={row.player_id} row={row} photos={photos} index={index} />
        ))}
      </section>

      <section aria-label="Mejores clausulazos" className="flex flex-col gap-3">
        <div className="px-1">
          <h3 className="text-[1.15rem] font-semibold tracking-tight text-white">Mejores clausulazos</h3>
          <p className="mt-0.5 text-[13px] text-white/50">
            {clausulazos.length
              ? "Quién mejora tu once, cuánto cuesta y cuándo se puede pagar."
              : "Hoy no hay un clausulazo que mejore tu once o compre por debajo de su valor."}
          </p>
        </div>
        {clausulazos.map((row, index) => (
          <RaidCard key={row.player_id} row={row} photos={photos} index={index} />
        ))}
      </section>
    </div>
  );
}
