"use client";

// Guardarraíl de ruina: ¿llegas al cierre con saldo negativo (jornada a 0 puntos)?
// Tabla limpia, sin píldoras: el color solo aparece cuando el estado no es OK.

import { cleanText, compact, money } from "@/components/ui/kit";
import type { Guardarrail, GuardarrailAccion, GuardarrailEstado, GuardarrailPlan } from "@/lib/types/guardarrail";

const COLOR: Record<GuardarrailEstado, string | null> = {
  OK: null,
  AVISO: "#F5B25A",
  PELIGRO: "#FC734D",
  SIN_ACTUALIZAR: "#8B9EB0",
};

const TITULO: Record<GuardarrailEstado, string> = {
  OK: "Saldo al cierre: OK",
  AVISO: "Saldo al cierre: aviso",
  PELIGRO: "Saldo al cierre: peligro",
  SIN_ACTUALIZAR: "Saldo al cierre",
};

function xp(value: number | null | undefined): string {
  if (typeof value !== "number") return "—";
  return `${value.toLocaleString("es-ES", { maximumFractionDigits: 2 })} xP`;
}

function horas(dias: number | null | undefined): string {
  if (typeof dias !== "number") return "—";
  if (dias < 1) return `${Math.max(0, Math.round(dias * 24))} h`;
  return `${dias.toLocaleString("es-ES", { maximumFractionDigits: 1 })} días`;
}

function Fila({ etiqueta, valor, color, detalle }: { etiqueta: string; valor: string; color?: string | null; detalle?: string }) {
  return (
    <tr className="border-t border-white/[0.06]">
      <th scope="row" className="py-2 pr-3 text-left text-[13px] font-normal text-white/55">
        {etiqueta}
        {detalle ? <span className="block text-[11.5px] text-white/35">{detalle}</span> : null}
      </th>
      <td className="py-2 text-right text-[14px] font-medium tabular-nums text-white" style={color ? { color } : undefined}>
        {valor}
      </td>
    </tr>
  );
}

function AccionesTabla({ data }: { data: NonNullable<Guardarrail["accion"]> }) {
  return (
    <div className="mt-4">
      <p className="text-[13px] font-medium text-white">
        Para cubrir {money(data.falta_eur)}
        {data.cubre ? "" : " (no llega con lo que tienes)"}
      </p>
      <table className="mt-1 w-full border-collapse">
        <thead>
          <tr className="text-left text-[11.5px] text-white/40">
            <th className="py-1 font-normal">Qué hacer</th>
            <th className="py-1 text-right font-normal">Libera</th>
            <th className="py-1 text-right font-normal">Cuesta</th>
          </tr>
        </thead>
        <tbody>
          {data.acciones.map((accion: GuardarrailAccion) => (
            <tr key={`${accion.tipo}:${accion.player_id}`} className="border-t border-white/[0.06]">
              <td className="py-2 pr-3 text-[13.5px] text-white">
                {accion.tipo === "RETIRAR_PUJA" ? "Retirar la puja por " : "Vender a "}
                {cleanText(accion.nombre) || accion.player_id}
              </td>
              <td className="py-2 text-right text-[13.5px] tabular-nums text-white">{money(accion.euros)}</td>
              <td className="py-2 text-right text-[13.5px] tabular-nums text-white/60">{xp(accion.coste_xp_solo)}</td>
            </tr>
          ))}
          <tr className="border-t border-white/[0.12]">
            <td className="py-2 text-[12.5px] text-white/50">Total</td>
            <td className="py-2 text-right text-[13.5px] font-medium tabular-nums text-white">{money(data.euros_cubiertos)}</td>
            <td className="py-2 text-right text-[13.5px] font-medium tabular-nums text-white">{xp(data.coste_xp)}</td>
          </tr>
        </tbody>
      </table>
      {data.nota ? <p className="mt-1 text-[11.5px] leading-snug text-white/35">{data.nota}</p> : null}
    </div>
  );
}

/** La edad de los datos no es un problema de saldo: se dice en una línea, sin tabla. */
function soloCaducado(data: Guardarrail): boolean {
  return data.estado === "SIN_ACTUALIZAR";
}

/**
 * Saldo en el peor caso al cierre. Arriba, una línea con el veredicto y el
 * margen; las cuentas quedan plegadas salvo que haya aviso o peligro.
 * `modo="inicio"` solo aparece con aviso o peligro: si todo va bien no ocupa
 * sitio, y si los datos son viejos ya lo dice el botón Actualizar del hero.
 */
export function GuardarrailRuina({ data, modo }: { data: Guardarrail | null | undefined; modo: "inicio" | "mercado" }) {
  if (!data) return null;
  const color = COLOR[data.estado] ?? null;
  const caducado = soloCaducado(data);
  if (modo === "inicio" && (data.estado === "OK" || caducado)) return null;

  const peor = data.saldo_peor;
  const margen = data.margen_eur;
  const alerta = data.estado === "AVISO" || data.estado === "PELIGRO";
  const resumen = caducado
    ? "Sin comprobar: los datos tienen más de un día. Actualiza antes de pujar."
    : data.estado === "OK"
      ? data.total_pujas_vivas
        ? `Aunque ganes todas tus pujas (${money(data.total_pujas_vivas)}) acabas en ${money(peor)}.`
        : "No tienes pujas vivas que comprometan tu caja."
      : (data.razones?.[0] ?? "Si ganas todas tus pujas quedas en negativo.");
  return (
    <section className="home-glass px-4 py-3.5 min-[900px]:px-5" aria-label="Saldo al cierre" data-estado={data.estado}>
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="flex items-center gap-2 text-[14px] font-medium text-white">
          <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: color ?? "#10B981" }} aria-hidden="true" />
          {TITULO[data.estado]}
        </h2>
        {!caducado && typeof margen === "number" ? (
          <p className="shrink-0 text-[13px] tabular-nums text-white/55" style={alerta && color ? { color } : undefined}>
            {margen >= 0 ? "Margen " : "Te pasas "}
            {money(Math.abs(margen))}
          </p>
        ) : null}
      </div>
      <p className="mt-1 text-[13px] leading-snug text-white/55">{resumen}</p>
      {alerta && data.razones && data.razones.length > 1 ? (
        <ul className="mt-1 text-[12.5px] leading-snug text-white/45">
          {data.razones.slice(1).map((razon) => (
            <li key={razon}>{razon}</li>
          ))}
        </ul>
      ) : null}
      {data.accion && data.accion.acciones.length ? <AccionesTabla data={data.accion} /> : null}
      <details className="group mt-2.5">
        <summary className="flex cursor-pointer list-none items-center gap-1.5 text-[12.5px] font-medium text-white/45 hover:text-white/70 [&::-webkit-details-marker]:hidden">
          Ver las cuentas
          <svg viewBox="0 0 16 16" className="h-3 w-3 transition-transform group-open:rotate-180" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <path d="m4 6 4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </summary>
        <table className="mt-2 w-full border-collapse">
          <tbody>
            <Fila etiqueta="Caja actual" valor={money(data.caja)} />
            <Fila
              etiqueta="Pujas vivas"
              valor={data.total_pujas_vivas ? `−${money(data.total_pujas_vivas)}` : "0 €"}
              detalle={data.pujas_vivas.length ? `${data.pujas_vivas.length} ${data.pujas_vivas.length === 1 ? "puja" : "pujas"}, como si ganaras todas` : undefined}
            />
            {data.ofertas_compra_pendientes ? <Fila etiqueta="Ofertas de compra pendientes" valor={`−${money(data.ofertas_compra_pendientes)}`} /> : null}
            <Fila etiqueta="Saldo en el peor caso" valor={money(peor)} color={typeof peor === "number" && peor < 0 ? color : null} />
            <Fila
              etiqueta="Deuda máxima permitida"
              valor={money(data.limite_deuda_estresado)}
              detalle={`20 % del valor de tu equipo${typeof data.valor_estresado === "number" ? `, contando con que baje a ${compact(data.valor_estresado)}` : ""} · cierre en ${horas(data.dias_al_cierre)}`}
            />
          </tbody>
        </table>
        {data.razones?.length && !alerta ? <p className="mt-2 text-[12px] leading-snug text-white/35">{data.razones.join(" ")}</p> : null}
      </details>
    </section>
  );
}

/** Aviso sobre el plan de fichajes si, además de lo vivo, te deja en aviso o peligro. */
export function PlanGuardarrailNota({ plan }: { plan: GuardarrailPlan | null | undefined }) {
  if (!plan || plan.estado === "OK") return null;
  const color = COLOR[plan.estado];
  return (
    <p className="px-1 text-[13px] leading-snug" style={color ? { color } : undefined} role="note">
      {plan.descartar
        ? `Descarta este plan: gastaría ${money(plan.gasto_plan_adicional)} más y el peor caso sería ${money(plan.saldo_peor)}, por debajo del límite de deuda.`
        : `Este plan gasta ${money(plan.gasto_plan_adicional)} más y el peor caso sería ${money(plan.saldo_peor)}. Cabe en el 20 %, pero hay que vender antes del saque.`}
    </p>
  );
}
