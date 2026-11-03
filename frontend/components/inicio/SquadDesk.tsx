"use client";

import Link from "next/link";
import { useState, type CSSProperties } from "react";
import { DangerRow, RaidRow, money, signedPct } from "@/components/inicio/ClauseAdvisor";
import { SaleRow } from "@/components/inicio/SalesAdvisor";
import { Tabs } from "@/components/inicio/ui";
import type { PhotoIndex } from "@/lib/core/photoIndex";
import type { PlanPayload } from "@/lib/types";

type Desk = "peligro" | "clausulazos" | "ventas";

const VISIBLE = 3;

function Summary({ value, label, detail, tone }: { value: string; label: string; detail: string[]; tone?: string }) {
  return (
    <div className="px-5 pb-1 pt-5">
      <p className="flex items-baseline gap-2">
        <span className="text-[28px] font-semibold leading-none tracking-[-0.03em] tabular-nums" style={{ color: tone || "#fff" }}>
          {value}
        </span>
        <span className="text-[15px] text-white/60">{label}</span>
      </p>
      {detail.length ? (
        <p className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[12.5px] tabular-nums text-white/45">
          {detail.map((bit) => (
            <span key={bit}>{bit}</span>
          ))}
        </p>
      ) : null}
    </div>
  );
}

/**
 * Tu plantilla frente a la liga: cláusulas en peligro, clausulazos y ofertas de
 * venta, cada mesa en una pestaña con sus tres filas más importantes.
 */
export function SquadDesk({ plan, photos, loading }: { plan: PlanPayload | null; photos: PhotoIndex; loading: boolean }) {
  const clauses = plan?.asesor_clausulas ?? null;
  const proteger = clauses?.proteger ?? [];
  const raids = clauses?.clausulazos ?? [];
  const sales = plan?.auditoria_ventas ?? [];
  const summary = plan?.resumen_ventas ?? null;
  const counts: Record<Desk, number> = { peligro: proteger.length, clausulazos: raids.length, ventas: sales.length };
  const first: Desk = proteger.length ? "peligro" : raids.length ? "clausulazos" : "ventas";
  const [picked, setPicked] = useState<Desk | null>(null);
  const [expanded, setExpanded] = useState(false);
  const desk = picked ?? first;

  if (loading && !plan) return <div className="ini-skel h-64" aria-hidden="true" />;
  if (!clauses && !sales.length) return null;

  const windowLabel = clauses?.resumen.ventana_abierta
    ? clauses.resumen.ventana_cierra
      ? `Ventana abierta hasta ${clauses.resumen.ventana_cierra}`
      : "Ventana abierta"
    : "Ventana de cláusulas cerrada";

  let head;
  let rows: React.ReactNode[] = [];
  let empty = "";
  let href = "/clausulas";
  if (desk === "peligro") {
    const r = clauses?.resumen;
    head = (
      <Summary
        value={String(r?.en_peligro ?? 0)}
        label={r?.en_peligro === 1 ? "jugador en peligro" : "jugadores en peligro"}
        tone={r?.riesgo_alto ? "var(--ini-red)" : undefined}
        detail={[
          r?.riesgo_alto ? `${r.riesgo_alto} de riesgo alto` : "",
          r && r.coste_proteger_eur > 0 ? `Blindar todo: ${money(r.coste_proteger_eur)}` : "",
          windowLabel,
        ].filter(Boolean)}
      />
    );
    rows = proteger.map((row, i) => <DangerRow key={row.player_id} row={row} photos={photos} index={i} />);
    empty = "Ningún rival puede pagar hoy la cláusula de tus jugadores.";
  } else if (desk === "clausulazos") {
    const open = raids.filter((row) => row.abierta_ahora).length;
    head = (
      <Summary
        value={String(raids.length)}
        label={raids.length === 1 ? "clausulazo que compensa" : "clausulazos que compensan"}
        detail={[raids.length ? `${open} ${open === 1 ? "abierto" : "abiertos"} ahora` : "", windowLabel].filter(Boolean)}
      />
    );
    rows = raids.map((row, i) => <RaidRow key={row.player_id} row={row} photos={photos} index={i} />);
    empty = "Hoy no hay un clausulazo que mejore tu once o compre por debajo de su valor.";
  } else {
    href = "/equipo?tab=cartera";
    head = (
      <Summary
        value={String(summary?.ofertas_activas ?? 0)}
        label={summary?.ofertas_activas === 1 ? "oferta activa" : "ofertas activas"}
        detail={[
          summary?.total_ofertas_eur ? `Suman ${money(summary.total_ofertas_eur)}` : "",
          typeof summary?.spread_medio_laliga_pct === "number" ? `LaLiga paga ${signedPct(summary.spread_medio_laliga_pct)} de media` : "",
          summary?.ventas_recomendadas_hoy ? `${summary.ventas_recomendadas_hoy} para vender hoy` : "",
        ].filter(Boolean)}
      />
    );
    rows = sales.map((row, i) => <SaleRow key={row.player_id} row={row} photos={photos} index={i} />);
    empty = "Sin ofertas que revisar hoy.";
  }

  const shown = expanded ? rows : rows.slice(0, VISIBLE);
  const hidden = rows.length - shown.length;

  return (
    <section className="ini-card ini-in" style={{ "--i": 2 } as CSSProperties} aria-label="Tu plantilla">
      <div className="flex items-center justify-between gap-3 px-5 pt-5">
        <p className="ini-eyebrow">Tu plantilla</p>
        <Link href={href} className="text-[12px] font-medium text-white/50 transition-colors hover:text-white">
          Ver todo →
        </Link>
      </div>
      <div className="px-5 pt-3">
        <Tabs<Desk>
          label="Mesas de tu plantilla"
          value={desk}
          onChange={(id) => {
            setPicked(id);
            setExpanded(false);
          }}
          items={[
            { id: "peligro", label: "En peligro", count: counts.peligro },
            { id: "clausulazos", label: "Clausulazos", count: counts.clausulazos },
            { id: "ventas", label: "Ventas", count: counts.ventas },
          ]}
        />
      </div>
      <div key={desk}>
        {head}
        {shown.length ? (
          <ul className="ini-divide mt-4">{shown}</ul>
        ) : (
          <p className="px-5 pb-5 pt-3 text-[13.5px] text-white/50">{empty}</p>
        )}
        {hidden > 0 || expanded ? (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="ini-more"
          >
            {expanded ? "Mostrar menos" : `Mostrar ${hidden} más`}
          </button>
        ) : null}
      </div>
    </section>
  );
}
