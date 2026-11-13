"use client";

import { useState, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { useJson } from "@/lib/core/useJson";
import { points } from "@/lib/core/format";
import type { PlanPayload, Top4Payload } from "@/lib/types";

const MINT = "var(--ini-mint)";
const RED = "var(--ini-red)";

const pct = (value: number) => `${Math.round(value * 100)}`;
/** Diferencia de probabilidad en puntos: +6, −14, 0. */
const dp = (value: number) => {
  const n = Math.round(value * 100);
  return n > 0 ? `+${n}` : n < 0 ? `−${Math.abs(n)}` : "0";
};
const tone = (value: number) => (value > 0.004 ? MINT : value < -0.004 ? RED : "rgba(255,255,255,0.45)");

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <h4 className="px-5 pb-1 pt-4 text-[12px] font-medium text-white/45">{title}</h4>
      <ul>{children}</ul>
    </div>
  );
}

function Row({ left, sub, value, self }: { left: string; sub?: string | null; value: ReactNode; self?: boolean }) {
  return (
    <li className="flex items-center justify-between gap-3 px-5 py-2">
      <span className="min-w-0">
        <span className={`block truncate text-[13.5px] ${self ? "font-semibold text-[var(--ini-copper)]" : "text-white/85"}`}>{left}</span>
        {sub ? <span className="block truncate text-[12px] text-white/40">{sub}</span> : null}
      </span>
      <span className="shrink-0 text-right text-[13.5px] font-semibold tabular-nums">{value}</span>
    </li>
  );
}

/** Cambio en la probabilidad de top 4. Va en %, nunca en «pts»: no son puntos de jornada. */
const Delta = ({ value }: { value: number }) => <span style={{ color: tone(value) }}>{dp(value)} %</span>;

/**
 * La cifra que decide la jornada: probabilidad de quedar entre los 4 primeros
 * (los demás pagan multa). Arriba solo lo que se lee de un vistazo —la cifra,
 * lo que falta para el corte y cuánto la sube el plan de hoy—; el reparto por
 * mánager y lo que mueve cada decisión quedan a un toque.
 */
export function Top4Card({ plan }: { plan: PlanPayload | null }) {
  const league = useSearchParams().get("league");
  const data = useJson<Top4Payload>("/api/top4", league);
  const [open, setOpen] = useState(false);

  if (data === null) return <div className="ini-skel h-36" aria-hidden="true" />;
  if (data.ok === false || typeof data.p_top4 !== "number") {
    return (
      <section className="ini-card px-5 py-4" aria-label="Probabilidad de top 4">
        <p className="ini-eyebrow">Top 4 · próxima jornada</p>
        <p className="mt-1.5 text-[13px] text-white/50">Sin simulación: {data.error?.message || data.message || "faltan plantillas"}.</p>
      </section>
    );
  }

  const incomplete = data.void === true;
  const scenario = incomplete ? (data.if_completed ?? null) : null;
  const prob = scenario ? scenario.p_top4 : data.p_top4;
  const gap = scenario ? scenario.xp_gap_to_cutoff : (data.xp_gap_to_cutoff ?? 0);
  const mine = scenario ? scenario.expected_points : data.expected_points;
  const managers = data.managers ?? [];
  const calibration = data.calibration;

  const levers = plan?.top4 && plan.top4.ok !== false ? plan.top4 : null;
  const withPlan = levers?.plan && Math.abs(levers.plan.delta_p) >= 0.005 ? levers.plan : null;
  const fichajes = levers?.acciones ?? [];
  const ventas = (levers?.ventas ?? []).filter((row) => Math.abs(row.delta_p) >= 0.01).slice(0, 3);
  const blindaje = (levers?.blindaje ?? []).filter((row) => Math.abs(row.delta_p) >= 0.01).slice(0, 3);
  const minima = levers?.plantilla_minima && !levers.plantilla_minima.cumple ? levers.plantilla_minima : null;

  return (
    <section className="ini-card ini-in" aria-label="Probabilidad de top 4" data-ui="top4">
      <div className="px-5 pb-4 pt-5">
        <p className="ini-eyebrow">Top 4 · próxima jornada</p>
        <div className="mt-2 flex items-end justify-between gap-4">
          <p className="flex items-baseline gap-1 leading-none text-white">
            <span className="text-[44px] font-semibold tracking-[-0.04em] tabular-nums">{pct(prob)}</span>
            <span className="text-[20px] font-medium text-white/50">%</span>
          </p>
          {withPlan ? (
            <p className="pb-1 text-right text-[12px] leading-tight text-white/45">
              Con el plan de hoy
              <span className="mt-0.5 block text-[15px] font-semibold tabular-nums text-white">
                {pct(withPlan.p_despues)} % <span style={{ color: tone(withPlan.delta_p) }}>{dp(withPlan.delta_p)} %</span>
              </span>
            </p>
          ) : null}
        </div>
        <div className="ini-meter mt-3.5" aria-hidden="true">
          <span style={{ width: `${Math.max(2, Math.min(100, prob * 100))}%` }} />
          {withPlan ? <i style={{ left: `${Math.max(0, Math.min(100, withPlan.p_despues * 100))}%` }} /> : null}
        </div>
        <p className="mt-3.5 text-[13.5px] leading-snug text-white/60">
          <span className="font-semibold" style={{ color: gap > 0 ? RED : MINT }}>
            {gap > 0 ? `Te faltan ${points(gap)} pts` : `Vas ${points(Math.abs(gap))} pts por encima`}
          </span>{" "}
          {gap > 0 ? "para" : "de"} la línea del 4.º: tu once apunta a {points(mine)} y el corte a {points(data.cutoff_median)}.
          {levers?.postura ? ` ${levers.postura.texto}` : ""}
        </p>
        {incomplete ? (
          <p className="mt-2 text-[13px] leading-snug" style={{ color: "var(--ini-amber)" }}>
            Tienes {data.player_count} jugadores: con menos de 11 la jornada puntúa 0 y hoy tu probabilidad real es {pct(data.p_top4)} %. La cifra grande supone el once completo.
          </p>
        ) : null}
        {minima ? (
          <p className="mt-2 text-[13px] leading-snug" style={{ color: "var(--ini-amber)" }}>
            Plantilla corta para comprar y revender: {minima.faltan.join(" ")}
          </p>
        ) : null}
      </div>

      <button type="button" className="ini-foot" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span>{open ? "Ocultar detalle" : "Rivales y qué mueve tu top 4"}</span>
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <path d="m4 6 4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open ? (
        <div className="row-in pb-3">
          {fichajes.length ? (
            <Group title="Si fichas">
              {fichajes.map((row) => (
                <Row
                  key={String(row.player_id)}
                  left={row.nombre ?? "—"}
                  sub={
                    row.tipo === "PUJA"
                      ? `${row.prob_conocida ? `${Math.round(row.prob_ganar * 100)} % de ganar la puja` : "Puja sin historial"} · ${dp(row.delta_p_si_ganas)} % si la ganas`
                      : `Cláusula · +${points(row.mejora_xp)} pts en tu once`
                  }
                  value={<Delta value={row.delta_p_ponderado} />}
                />
              ))}
            </Group>
          ) : null}
          {ventas.length ? (
            <Group title="Si vendes">
              {ventas.map((row) => (
                <Row key={String(row.player_id)} left={row.nombre ?? "—"} sub={`Tu once pierde ${points(row.pierde_xp)} pts`} value={<Delta value={row.delta_p} />} />
              ))}
            </Group>
          ) : null}
          {blindaje.length ? (
            <Group title="Si te los quitan">
              {blindaje.map((row) => (
                <Row
                  key={String(row.player_id)}
                  left={row.nombre ?? "—"}
                  sub={
                    [
                      row.veredicto === "PROTEGER_YA" ? "Sube su cláusula ya" : null,
                      row.rivales_que_pueden_pagar != null ? `${row.rivales_que_pueden_pagar} ${row.rivales_que_pueden_pagar === 1 ? "rival puede pagarla" : "rivales pueden pagarla"}` : null,
                      row.deja_sin_linea ? "sin recambio en su línea" : null,
                    ]
                      .filter(Boolean)
                      .join(" · ") || null
                  }
                  value={<Delta value={row.delta_p} />}
                />
              ))}
            </Group>
          ) : null}
          {managers.length ? (
            <Group title="Probabilidad de cada mánager">
              {managers.map((row) => (
                <Row
                  key={String(row.team_id ?? row.manager_name)}
                  left={row.is_self ? `${row.manager_name ?? "Tú"} (tú)` : (row.manager_name ?? "—")}
                  sub={row.has_xp ? `Once de ${points(row.expected_points)} pts` : "Sin once estimado"}
                  self={row.is_self}
                  value={<span className={row.is_self ? "text-[var(--ini-copper)]" : "text-white/85"}>{pct(row.is_self && scenario ? scenario.p_top4 : row.p_top4)} %</span>}
                />
              ))}
            </Group>
          ) : null}
          <p className="px-5 pt-3 text-[12px] leading-snug text-white/35">
            El porcentaje de cada fila es cuánto sube o baja tu probabilidad de top 4, no puntos de jornada. Sale de simular 20.000 jornadas con el once esperado de cada mánager
            {calibration ? ` y la dispersión real de la liga (±${points(calibration.sigma)} pts en ${calibration.rounds_used} jornadas)` : ""}.
          </p>
        </div>
      ) : null}
    </section>
  );
}
