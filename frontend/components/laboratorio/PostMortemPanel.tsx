"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useDashboard } from "@/components/DashboardProvider";
import { ErrorCard, Skeleton } from "@/components/ui/Feedback";
import { endpoint, getJson } from "@/lib/core/api";
import { eur, glass, points } from "@/lib/core/format";
import type { PostMortemFuga, PostMortemPayload, PostMortemTrading } from "@/lib/types";

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl bg-[color:var(--surface)] px-4 py-3">
      <p className="text-[11px] uppercase tracking-wide text-faint">{label}</p>
      <p className="metric-value mt-1 text-xl">{value}</p>
      {hint ? <p className="mt-1 text-xs text-muted">{hint}</p> : null}
    </div>
  );
}

function signed(value: number | null | undefined, format: (value: number) => string): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "s/d";
  const text = format(value);
  return value > 0 ? `+${text}` : text;
}

function FugaBlock({ fuga, jornada, fuente }: { fuga: PostMortemFuga; jornada?: string | null; fuente?: string }) {
  if (!fuga.disponible) {
    return <p className="mt-3 text-sm text-muted-strong">{fuga.detalle || "Sin alineación que auditar."}</p>;
  }
  const dejados = fuga.dejados_fuera || [];
  const fuenteLabel = fuente === "guardado" ? "once guardado" : fuente === "recomendado" ? "once recomendado" : "once";
  return (
    <>
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <Metric label="Once alineado" value={points(fuga.puntos_once)} hint={fuenteLabel} />
        <Metric
          label="Máximo de la plantilla"
          value={points(fuga.puntos_maximos)}
          hint={fuga.formacion_optima || undefined}
        />
        <Metric
          label="Fuga"
          value={points(fuga.fuga)}
          hint={jornada && jornada !== "ultima" ? `Jornada ${jornada}` : "Última jornada registrada"}
        />
      </div>
      {dejados.length ? (
        <p className="mt-3 text-sm text-muted-strong">
          Fuera del once:{" "}
          {dejados
            .map((row) => `${row.nombre || row.player_id} (${points(row.puntos)})`)
            .join(", ")}
          .
        </p>
      ) : (
        <p className="mt-3 text-sm text-muted-strong">El once alineado era el máximo de la plantilla.</p>
      )}
    </>
  );
}

function TradingBlock({ trading }: { trading: PostMortemTrading }) {
  if (!trading.disponible) {
    return <p className="mt-3 text-sm text-muted-strong">{trading.detalle || "Sin foto del lunes pasado."}</p>;
  }
  const hoy = trading.hoy || {};
  const base = trading.sin_operar || {};
  const dia = trading.snapshot_day || "el lunes pasado";
  return (
    <>
      <p className="section-support mt-2">
        Contra la foto del {dia}
        {trading.operaciones ? ` · ${trading.operaciones} operaciones en el libro` : " · sin compras ni ventas en el libro"}
        {trading.valores_congelados ? ` · ${trading.valores_congelados} valores sin cotización de hoy` : ""}.
      </p>
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <Metric
          label="Valor de equipo"
          value={signed(trading.delta_valor, eur)}
          hint={`${eur(hoy.valor)} hoy · ${eur(base.valor)} sin operar`}
        />
        <Metric
          label="Caja"
          value={signed(trading.delta_caja, eur)}
          hint={`${eur(hoy.caja)} hoy · ${eur(base.caja)} sin operar`}
        />
        <Metric
          label="Puntos de la jornada"
          value={signed(trading.delta_puntos, points)}
          hint={`${points(hoy.puntos)} hoy · ${points(base.puntos)} sin operar`}
        />
      </div>
    </>
  );
}

export function PostMortemPanel() {
  const search = useSearchParams();
  const { trends } = useDashboard();
  const leagueForApi = trends?.league_id || search.get("league");
  const [payload, setPayload] = useState<PostMortemPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function run() {
      setLoading(true);
      try {
        const data = await getJson<PostMortemPayload>(endpoint("/api/laboratorio/post-mortem", leagueForApi));
        if (cancelled) return;
        setPayload(data);
        setFetchError(null);
      } catch (reason: unknown) {
        if (cancelled) return;
        const message = reason instanceof Error ? reason.message : "Sin datos.";
        setFetchError(message);
        const err =
          typeof reason === "object" && reason !== null && "payload" in reason
            ? (reason as { payload: PostMortemPayload }).payload
            : { ok: false, error: { message } };
        setPayload(err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void run();
    return () => {
      cancelled = true;
    };
  }, [leagueForApi]);

  if (loading && !payload) return <Skeleton title="Post-mortem" rows={4} />;
  if (!payload || payload.ok === false) {
    const hint =
      fetchError && /404|Not Found/i.test(fetchError)
        ? " El backend en el puerto 8000 no tiene la ruta nueva: reinicia con python run_dashboard.py."
        : "";
    return (
      <ErrorCard
        title="Post-mortem"
        payload={payload || { error: { message: `Sin auditoría.${hint}` } }}
        brief
      />
    );
  }

  const ritual = payload.es_lunes
    ? "Lunes. La foto de hoy queda guardada para el próximo post-mortem."
    : `Hoy es ${payload.hoy || "un día entre jornadas"}. Las cifras usan la última foto de un lunes.`;

  return (
    <section className={glass("p-4 md:p-5")}>
      <p className="eyebrow">Laboratorio</p>
      <h2 className="section-title mt-1">Post-mortem de la jornada</h2>
      <p className="section-support mt-2">{ritual}</p>
      <div className="mt-5">
        <h3 className="text-[15px] font-medium text-white">Fuga de puntos por alineación</h3>
        <FugaBlock fuga={payload.fuga || {}} jornada={payload.jornada} fuente={payload.once_fuente} />
      </div>
      <div className="mt-6">
        <h3 className="text-[15px] font-medium text-white">Impacto del trading</h3>
        <TradingBlock trading={payload.trading || {}} />
      </div>
    </section>
  );
}
