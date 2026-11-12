"use client";

import { points } from "@/lib/core/format";
import { TONE } from "@/components/ui/kit";
import type { PlanPayload } from "@/lib/types";

const dp = (value: number) => {
  const n = Math.round(value * 100);
  return n > 0 ? `+${n}` : n < 0 ? `−${Math.abs(n)}` : "0";
};
const tone = (value: number) => (value > 0.004 ? TONE.green : value < -0.004 ? TONE.red : "rgba(255,255,255,0.5)");

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <h4 className="px-4 pb-1.5 pt-3.5 text-[12.5px] font-medium text-white/50 min-[900px]:px-5">{title}</h4>
      {children}
    </div>
  );
}

function Row({ left, sub, right, value }: { left: string; sub?: string | null; right: string; value: number }) {
  return (
    <li className="flex items-baseline justify-between gap-3 border-t border-white/[0.05] px-4 py-2 min-[900px]:px-5">
      <span className="min-w-0">
        <span className="block truncate text-[13.5px] text-white">{left}</span>
        {sub ? <span className="block truncate text-[11.5px] text-white/40">{sub}</span> : null}
      </span>
      <span className="shrink-0 text-right font-mono text-[13px]">
        <span className="text-white/45">{right}</span>{" "}
        <span className="font-semibold" style={{ color: tone(value) }}>
          {dp(value)} pts
        </span>
      </span>
    </li>
  );
}

/**
 * Cada decisión medida en lo que importa: cuánto sube o baja tu probabilidad de
 * top 4. Fichajes, ventas, a quién blindar y si la plantilla permite comprar
 * para revender.
 */
export function Top4Levers({ plan }: { plan: PlanPayload | null }) {
  const t = plan?.top4;
  if (!t || t.ok === false) return null;
  const minima = t.plantilla_minima;
  const acciones = t.acciones ?? [];
  const ventas = (t.ventas ?? []).slice(0, 4);
  const blindaje = (t.blindaje ?? []).filter((row) => Math.abs(row.delta_p) >= 0.01).slice(0, 4);
  return (
    <section className="home-glass overflow-hidden pb-2" aria-label="Qué mueve tu top 4">
      <div className="px-4 pt-4 min-[900px]:px-5">
        <h3 className="text-[15px] font-semibold text-white">Qué mueve tu top 4</h3>
        <p className="mt-0.5 text-[12.5px] leading-snug text-white/45">Puntos de probabilidad que suma o resta cada decisión.</p>
        {t.postura ? <p className="mt-2 text-[13px] leading-snug text-white/70">{t.postura.texto}</p> : null}
      </div>

      {t.paso_1 ? (
        <Block title="Primer paso">
          <p className="border-t border-white/[0.05] px-4 py-2.5 text-[13px] leading-snug text-white/80 min-[900px]:px-5">
            {t.paso_1.texto}
            {typeof t.paso_1.prob_ganar === "number" ? ` Probabilidad de ganarla: ${Math.round(t.paso_1.prob_ganar * 100)} %.` : ""}
            {t.paso_1.respaldo ? ` Respaldo: ${t.paso_1.respaldo}.` : ""}
          </p>
        </Block>
      ) : null}

      {t.plan ? (
        <Block title="Plan de hoy, ponderado por ganar cada puja">
          <ul>
            <Row
              left={`De ${Math.round(t.plan.p_antes * 100)} % a ${Math.round(t.plan.p_despues * 100)} %`}
              sub={`${t.plan.jugadores_despues} jugadores si las ganas · once de ${points(t.plan.puntos_once)} xP · ganarlas todas: ${Math.round(t.plan.prob_ganar_todas * 100)} %, ninguna: ${Math.round(t.plan.prob_ganar_ninguna * 100)} %`}
              right="esperado"
              value={t.plan.delta_p}
            />
            <Row left={`Si ganas todas: ${Math.round(t.plan.p_si_ganas_todas * 100)} %`} sub="El mejor caso, no el esperado" right="" value={t.plan.p_si_ganas_todas - t.plan.p_antes} />
            {t.plan.solo_mas_probable ? (
              <Row
                left={`Solo ganas la más probable: ${Math.round(t.plan.solo_mas_probable.p_top4 * 100)} %`}
                sub={`${t.plan.solo_mas_probable.nombre ?? "—"} (${Math.round(t.plan.solo_mas_probable.prob_ganar * 100)} % de ganarla); pierdes el resto`}
                right=""
                value={t.plan.solo_mas_probable.p_top4 - t.plan.p_antes}
              />
            ) : null}
          </ul>
        </Block>
      ) : null}

      {acciones.length ? (
        <Block title="Fichajes (ponderado por la probabilidad de ganar la puja)">
          <ul>
            {acciones.map((row) => (
              <Row
                key={String(row.player_id)}
                left={row.nombre ?? "—"}
                sub={`${row.tipo === "PUJA" ? `Puja, ${Math.round(row.prob_ganar * 100)} % de ganarla${row.prob_conocida ? "" : " (sin dato, se supone 50 %)"}` : "Cláusula"} · +${points(row.mejora_xp)} xP · si la ganas ${dp(row.delta_p_si_ganas)}`}
                right={`${Math.round(row.p_antes * 100)} → ${Math.round(row.p_despues * 100)} %`}
                value={row.delta_p_ponderado}
              />
            ))}
          </ul>
        </Block>
      ) : null}

      {ventas.length ? (
        <Block title="Si vendes">
          <ul>
            {ventas.map((row) => (
              <Row key={String(row.player_id)} left={row.nombre ?? "—"} sub={`Tu once pierde ${points(row.pierde_xp)} xP`} right={`${Math.round(row.p_si_vendes * 100)} %`} value={row.delta_p} />
            ))}
          </ul>
        </Block>
      ) : null}

      {blindaje.length ? (
        <Block title="A quién blindar primero (si te lo quitan)">
          <ul>
            {blindaje.map((row) => (
              <Row
                key={String(row.player_id)}
                left={row.nombre ?? "—"}
                sub={`Cláusula ${row.multiplo_clausula ? `${row.multiplo_clausula.toLocaleString("es-ES")}×` : "—"} su valor${row.rivales_que_pueden_pagar != null ? ` · ${row.rivales_que_pueden_pagar} ${row.rivales_que_pueden_pagar === 1 ? "rival puede pagarla" : "rivales pueden pagarla"}` : ""}${row.deja_sin_linea ? " · sin otro de su línea" : ""}`}
                right={row.veredicto === "PROTEGER_YA" ? "protégela" : ""}
                value={row.delta_p}
              />
            ))}
          </ul>
        </Block>
      ) : null}

      {minima ? (
        <Block title="Plantilla mínima para comprar y revender">
          <p className="border-t border-white/[0.05] px-4 py-2.5 text-[13px] leading-snug text-white/70 min-[900px]:px-5">
            {minima.cumple ? `Cumples: ${minima.jugadores} jugadores, ${minima.delanteros_titulares} delanteros titulares y recambio en cada línea.` : `No cumples: ${minima.faltan.join(" ")}`}
            {!minima.cumple && t.reventa_bloqueada ? ` Se han retirado ${t.reventa_bloqueada} compras para revender.` : ""}
          </p>
        </Block>
      ) : null}
    </section>
  );
}
