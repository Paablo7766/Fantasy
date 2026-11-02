"use client";

import { useMemo, useState } from "react";
import { playerName, points, stamp, titularShare } from "@/lib/core/format";
import { photoFor, type PhotoIndex } from "@/lib/core/photoIndex";
import type { AuditoriaVenta, PlanPayload, RivalPlayer, SquadsPayload, VeredictoVenta } from "@/lib/types";
import {
  Chevron,
  Disclosure,
  Empty,
  Face,
  Fact,
  HeroStat,
  SectionHead,
  Skeleton,
  Sparkline,
  TONE,
  Verdict,
  compact,
  money,
  parsePct,
  signedMoney,
  signedPct,
  toneOf,
} from "@/components/ui/kit";

const VERDICT: Record<VeredictoVenta, { label: string; color: string }> = {
  ACEPTAR_YA: { label: "Acepta ya", color: TONE.green },
  RECHAZAR_ESPERAR: { label: "Rechaza y espera", color: TONE.amber },
  RECHAZAR_RIVAL: { label: "No vender a rival", color: TONE.red },
  PONER_ESCAPARATE: { label: "Ponlo en venta", color: TONE.blue },
  MANTENER_INTOCABLE: { label: "No vender", color: TONE.gray },
};

type Filter = "all" | "POR" | "DEF" | "MC" | "DEL" | "venta" | "peligro";
type Sort = "value" | "trend" | "roi" | "clause";

const SORTS: { id: Sort; label: string }[] = [
  { id: "value", label: "Valor" },
  { id: "trend", label: "7 días" },
  { id: "roi", label: "Rentabilidad" },
  { id: "clause", label: "Cláusula" },
];

/** Regla rápida de la máquina: ofrece el valor ±5 %. Más de +3 % vende, más de +1 % acepta. */
function machineVerdict(value: number, offer: number, forceCash: boolean): { label: string; color: string; deviation: number } | null {
  if (value <= 0 || offer <= 0) return null;
  const deviation = (offer - value) / value;
  if (deviation > 0.03) return { label: "Vende ya", color: TONE.green, deviation };
  if (deviation > 0.01) return { label: "Acepta", color: TONE.green, deviation };
  if (forceCash) return { label: "Vende por caja", color: TONE.amber, deviation };
  return { label: "Aguanta", color: TONE.red, deviation };
}

function lockCaption(player: RivalPlayer): string {
  if (player.is_shielded) return "Blindada";
  const lock = player.clause_lock;
  if (lock?.is_locked) return lock.local_date ? `Se abre ${lock.local_date.slice(5).split("-").reverse().join("/")}${lock.local_time ? ` ${lock.local_time}` : ""}` : "Con candado";
  return lock?.present ? "Abierta" : "";
}

function PlayerRow({
  player,
  photos,
  audit,
  danger,
  index,
}: {
  player: RivalPlayer;
  photos: PhotoIndex;
  audit: AuditoriaVenta | undefined;
  danger: boolean;
  index: number;
}) {
  const [open, setOpen] = useState(false);
  const name = playerName(player);
  const trend = parsePct(player.prevision_7d_pct);
  const share = titularShare(player.p_titular);
  const status = audit?.en_mercado ? { label: "En venta", color: TONE.blue } : danger ? { label: "En peligro", color: TONE.red } : null;
  return (
    <li className="row-in border-b border-white/[0.06] last:border-b-0" style={{ animationDelay: `${Math.min(index, 12) * 30}ms` }}>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex min-h-[3.75rem] w-full items-center gap-3 px-4 py-2.5 text-left transition-colors duration-200 ease-out hover:bg-white/[0.02]"
      >
        <Face name={name} src={player.image_url || photoFor(photos, player.player_id, name)} size={40} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[15px] font-medium leading-tight text-white">{name}</span>
          <span className="mt-0.5 block truncate text-[12.5px] text-white/45">
            {player.position || "—"}
            {status ? <span style={{ color: status.color }}> · {status.label}</span> : null}
          </span>
        </span>
        <span className="shrink-0 text-right">
          <span className="block text-[15px] font-semibold tabular-nums text-white">{money(player.market_value)}</span>
          <span className="block text-[12.5px] font-medium tabular-nums" style={{ color: toneOf(trend) }}>
            {trend !== null ? signedPct(trend) : "—"}
          </span>
        </span>
        <Chevron open={open} />
      </button>
      {open ? (
        <div className="row-in grid grid-cols-2 gap-x-4 gap-y-3 px-4 pb-4 pt-1 sm:grid-cols-4">
          <Fact
            label="Compra"
            value={money(player.cost_eur)}
            hint={[player.acquisition_kind === "clausula" ? "Cláusula" : player.acquisition_kind === "mercado" ? "Mercado" : "", stamp(player.acquired_at)].filter(Boolean).join(" · ") || undefined}
          />
          <Fact
            label="Rentabilidad"
            value={signedMoney(player.gain_eur)}
            tone={toneOf(player.gain_eur)}
            hint={typeof player.roi === "number" ? signedPct(player.roi * 100) : undefined}
          />
          <Fact label="Cláusula" value={money(player.buyout_clause)} hint={lockCaption(player) || undefined} />
          <Fact
            label="xP jornada"
            value={points(player.own_expected_points)}
            tone="#FFC08A"
            hint={share !== null ? `Titular ${Math.round(share * 100)}%` : undefined}
          />
          {audit ? (
            <div className="col-span-2 sm:col-span-4">
              <Verdict {...(VERDICT[audit.veredicto_codigo] ?? VERDICT.MANTENER_INTOCABLE)} />
            </div>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

function SaleRow({ row, photos, index }: { row: AuditoriaVenta; photos: PhotoIndex; index: number }) {
  const [open, setOpen] = useState(false);
  const verdict = VERDICT[row.veredicto_codigo] ?? VERDICT.MANTENER_INTOCABLE;
  const offer = row.oferta_activa;
  const trend = typeof row.prevision_7d_pct === "number" ? row.prevision_7d_pct : null;
  return (
    <li className="row-in border-b border-white/[0.06] last:border-b-0" style={{ animationDelay: `${index * 30}ms` }}>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex min-h-[3.5rem] w-full items-center gap-3 py-2.5 text-left"
      >
        <Face name={row.nombre} src={photoFor(photos, row.player_id, row.nombre)} size={36} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[14.5px] font-medium leading-tight text-white">{row.nombre}</span>
          <Verdict {...verdict} />
        </span>
        <span className="shrink-0 text-right">
          {typeof offer.importe_oferta === "number" ? (
            <>
              <span className="block text-[14.5px] font-semibold tabular-nums text-white">{money(offer.importe_oferta)}</span>
              {typeof offer.spread_pct === "number" ? (
                <span className="block text-[12px] font-medium tabular-nums" style={{ color: toneOf(offer.spread_pct) }}>
                  {signedPct(offer.spread_pct)}
                </span>
              ) : null}
            </>
          ) : (
            <span className="block text-[12.5px] text-white/45">{offer.comprador ? `Oferta de ${offer.comprador}` : "Sin oferta"}</span>
          )}
        </span>
        <Chevron open={open} />
      </button>
      {open ? (
        <div className="row-in pb-4">
          <div className="grid grid-cols-3 gap-3">
            <Fact label="Valor" value={money(row.valor_mercado)} />
            <Fact
              label="Impacto XI"
              value={row.tu_once_pierde_sin_el < 0.05 ? "Suplente" : `−${points(row.tu_once_pierde_sin_el)}`}
              tone={row.tu_once_pierde_sin_el < 0.05 ? undefined : TONE.red}
            />
            <Fact label="7 días" value={signedPct(trend)} tone={toneOf(trend)} />
          </div>
          <p className="mt-3 text-[13px] leading-relaxed text-white/55">{row.motivo_detallado}</p>
        </div>
      ) : null}
    </li>
  );
}

function MachineOffer() {
  const [value, setValue] = useState("");
  const [offer, setOffer] = useState("");
  const [forceCash, setForceCash] = useState(false);
  const result = machineVerdict(Number(value) || 0, Number(offer) || 0, forceCash);
  const field =
    "mt-1 h-11 w-full rounded-xl border border-white/[0.08] bg-black/25 px-3 text-[15px] tabular-nums text-white outline-none transition-colors duration-200 ease-out placeholder:text-white/25 focus:border-[#FF9A5A]/60";
  return (
    <div className="mt-4 border-t border-white/[0.06] pt-4">
      <p className="text-[14px] font-medium text-white">Oferta de la máquina</p>
      <p className="mt-0.5 text-[12.5px] text-white/45">Pega el valor y la oferta para saber qué hacer.</p>
      <div className="mt-3 grid grid-cols-2 gap-2.5">
        <label className="min-w-0 text-[12px] text-white/50">
          Valor
          <input inputMode="numeric" value={value} onChange={(event) => setValue(event.target.value.replace(/\D/g, ""))} placeholder="10000000" className={field} />
        </label>
        <label className="min-w-0 text-[12px] text-white/50">
          Oferta
          <input inputMode="numeric" value={offer} onChange={(event) => setOffer(event.target.value.replace(/\D/g, ""))} placeholder="10320000" className={field} />
        </label>
      </div>
      <label className="mt-3 flex min-h-[2.5rem] items-center gap-2.5 text-[13px] text-white/60">
        <input type="checkbox" checked={forceCash} onChange={(event) => setForceCash(event.target.checked)} className="h-4 w-4 accent-[#FF7A3D]" />
        Necesito caja
      </label>
      {result ? (
        <p className="row-in mt-2 flex items-center justify-between gap-3 rounded-xl bg-black/25 px-3 py-2.5">
          <Verdict label={result.label} color={result.color} />
          <span className="text-[13px] tabular-nums text-white/55">{signedPct(result.deviation * 100, 2)}</span>
        </p>
      ) : null}
    </div>
  );
}

export function CarteraTab({
  plan,
  squads,
  photos,
  loading,
}: {
  plan: PlanPayload | null;
  squads: SquadsPayload | null;
  photos: PhotoIndex;
  loading: boolean;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<Sort>("value");

  const own = squads?.self || null;
  const players = useMemo(() => (own?.players || []) as RivalPlayer[], [own]);
  const audit = useMemo(() => {
    const rows = plan?.auditoria_ventas || [];
    return new Map(rows.map((row) => [String(row.player_id), row]));
  }, [plan]);
  const danger = useMemo(() => {
    const ids = new Set<string>();
    for (const row of plan?.asesor_clausulas?.proteger || []) if (row.riesgo !== "BAJO") ids.add(String(row.player_id));
    for (const row of squads?.shield || []) if (row.player_id) ids.add(String(row.player_id));
    return ids;
  }, [plan, squads]);

  const visible = useMemo(() => {
    const rows = players.filter((player) => {
      const id = String(player.player_id);
      if (filter === "all") return true;
      if (filter === "venta") return Boolean(audit.get(id)?.en_mercado);
      if (filter === "peligro") return danger.has(id);
      return (player.position || "").toUpperCase() === filter;
    });
    const key = (player: RivalPlayer): number => {
      if (sort === "trend") return parsePct(player.prevision_7d_pct) ?? -Infinity;
      if (sort === "roi") return typeof player.roi === "number" ? player.roi : -Infinity;
      if (sort === "clause") return player.buyout_clause ?? -Infinity;
      return player.market_value ?? -Infinity;
    };
    return rows.slice().sort((a, b) => key(b) - key(a));
  }, [players, filter, sort, audit, danger]);

  if (loading && !own) return <Skeleton />;
  if (!squads || squads.ok === false || !own) {
    return <Empty title="Sin cartera" detail="Pulsa Actualizar para leer tu plantilla y sus valores." />;
  }

  const summary = squads.portfolio?.summary;
  const history = (squads.value_history || []).filter((row) => typeof row.value_eur === "number");
  const total =
    own.market_value_total ?? summary?.market_value_eur ?? players.reduce((sum, player) => sum + (player.market_value ?? 0), 0);
  const first = history.length >= 2 ? history[0].value_eur : null;
  const change = first !== null ? history.at(-1)!.value_eur - first : (own.price_delta_day ?? null);
  const changePct = first ? ((history.at(-1)!.value_eur - first) / first) * 100 : null;
  const cash = typeof plan?.cash_eur === "number" ? plan.cash_eur : (own.cash_eur ?? null);
  const roi = summary?.roi;

  const sales = (plan?.auditoria_ventas || []).slice().sort((a, b) => a.prioridad - b.prioridad);
  const resumen = plan?.resumen_ventas;
  const onSale = sales.filter((row) => row.en_mercado).length;
  const events = squads.portfolio?.recent_events?.length ? squads.portfolio.recent_events : own.activity_profile?.recent_events || [];

  const filters: { id: Filter; label: string; count?: number }[] = [
    { id: "all", label: "Todos", count: players.length },
    { id: "POR", label: "POR" },
    { id: "DEF", label: "DEF" },
    { id: "MC", label: "MC" },
    { id: "DEL", label: "DEL" },
    { id: "venta", label: "En venta", count: onSale },
    { id: "peligro", label: "En peligro", count: danger.size },
  ];

  return (
    <div className="grid gap-5 min-[1100px]:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)] min-[1100px]:items-start">
      <div className="flex min-w-0 flex-col gap-4">
        <section className="home-feature" aria-label="Resumen de tu cartera">
          <div className="relative flex items-center justify-between gap-3">
            <p className="text-[13px] font-medium text-white/60">Valor de plantilla</p>
            {history.length >= 2 ? <p className="text-[12px] tabular-nums text-white/45">{history.length} días</p> : null}
          </div>
          <p className="relative mt-2 text-[2.9rem] font-semibold leading-none tracking-[-0.045em] tabular-nums text-white">
            {money(total, 1)}
          </p>
          {change !== null ? (
            <p className="relative mt-2 text-[13.5px] tabular-nums text-white/55">
              <span className="font-semibold" style={{ color: toneOf(change) }}>
                {signedMoney(change)}
                {changePct !== null ? ` · ${signedPct(changePct)}` : ""}
              </span>{" "}
              {first !== null ? `en ${history.length} días` : "hoy"}
            </p>
          ) : null}
          {history.length >= 2 ? (
            <div className="relative mt-4">
              <Sparkline values={history.map((row) => row.value_eur)} label={`Evolución del valor de tu plantilla en ${history.length} días`} />
            </div>
          ) : null}
          <div className="relative mt-5 grid grid-cols-3 gap-2.5">
            <HeroStat value={compact(cash)} label="Caja" tone={cash !== null && cash < 0 ? TONE.red : undefined} />
            <HeroStat value={compact(summary?.gain_eur, true)} label="Plusvalía" tone={toneOf(summary?.gain_eur)} />
            <HeroStat value={typeof roi === "number" ? signedPct(roi * 100) : "—"} label="Rentabilidad" tone={toneOf(roi)} />
          </div>
        </section>

        {sales.length ? (
          <Disclosure
            title="Ofertas y ventas"
            meta={
              resumen
                ? `${resumen.ofertas_activas} ${resumen.ofertas_activas === 1 ? "oferta" : "ofertas"}${resumen.ventas_recomendadas_hoy ? ` · ${resumen.ventas_recomendadas_hoy} ${resumen.ventas_recomendadas_hoy === 1 ? "venta" : "ventas"}` : ""}`
                : `${sales.length}`
            }
          >
            <ul>
              {sales.map((row, index) => (
                <SaleRow key={row.player_id} row={row} photos={photos} index={index} />
              ))}
            </ul>
            <MachineOffer />
          </Disclosure>
        ) : (
          <Disclosure title="Oferta de la máquina">
            <MachineOffer />
          </Disclosure>
        )}

        <Disclosure title="Movimientos" meta={events.length ? `${events.length}` : undefined}>
          {squads.portfolio_meta?.history_ready === false ? (
            <p className="mb-3 text-[13px] text-[#F59E0B]">Historial sin sincronizar: pulsa Actualizar.</p>
          ) : null}
          {events.length ? (
            <ul>
              {events.map((event, index) => (
                <li key={`${event.at}-${event.kind}-${index}`} className="flex items-center justify-between gap-3 border-b border-white/[0.06] py-2.5 last:border-b-0">
                  <span className="min-w-0">
                    <span className="block truncate text-[14px] text-white">
                      {event.label || event.kind}
                      {event.player_name ? <span className="text-white/50"> · {event.player_name}</span> : null}
                    </span>
                    <span className="block text-[12px] text-white/40">{stamp(event.at) || "Sin fecha"}</span>
                  </span>
                  <span className="shrink-0 text-[14px] font-medium tabular-nums" style={{ color: toneOf(event.signed_eur) }}>
                    {typeof event.signed_eur === "number" ? signedMoney(event.signed_eur) : money(event.amount_eur)}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[13.5px] text-white/50">Aún no hay movimientos sincronizados.</p>
          )}
        </Disclosure>
      </div>

      <section aria-label="Jugadores de tu plantilla" className="flex min-w-0 flex-col gap-3">
        <SectionHead
          title="Jugadores"
          meta={
            <label className="inline-flex items-center gap-1.5">
              <span className="sr-only">Ordenar por</span>
              <select
                value={sort}
                onChange={(event) => setSort(event.target.value as Sort)}
                className="h-10 rounded-full border border-white/[0.08] bg-white/[0.04] px-3 text-[13px] text-white outline-none"
              >
                {SORTS.map((item) => (
                  <option key={item.id} value={item.id} className="bg-[#120C09]">
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
          }
        />
        <div className="eq-scroll -mx-1 px-1 min-[1100px]:flex-wrap" role="toolbar" aria-label="Filtrar jugadores">
          {filters.map((item) => (
            <button
              key={item.id}
              type="button"
              aria-pressed={filter === item.id}
              onClick={() => setFilter(item.id)}
              className={filter === item.id ? "eq-chip eq-chip--on" : "eq-chip"}
            >
              {item.label}
              {item.count ? <span className="tabular-nums opacity-60">{item.count}</span> : null}
            </button>
          ))}
        </div>
        {visible.length ? (
          <ul className="home-glass overflow-hidden">
            {visible.map((player, index) => (
              <PlayerRow
                key={String(player.player_id)}
                player={player}
                photos={photos}
                audit={audit.get(String(player.player_id))}
                danger={danger.has(String(player.player_id))}
                index={index}
              />
            ))}
          </ul>
        ) : (
          <p className="home-glass px-4 py-6 text-center text-[13.5px] text-white/50">
            {players.length ? "Nadie cumple este filtro." : "Tu plantilla no trae jugadores."}
          </p>
        )}
      </section>
    </div>
  );
}
