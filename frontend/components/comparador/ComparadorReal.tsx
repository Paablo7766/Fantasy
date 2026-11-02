"use client";

import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { useDashboard } from "@/components/DashboardProvider";
import { Face } from "@/components/equipo/ui";
import { apiUrl, getJson } from "@/lib/api";
import { playerName } from "@/lib/format";
import { buildPhotoIndex, photoFor, type PhotoIndex } from "@/lib/photoIndex";
import type { OptimizePayload, Player, SquadsPayload, TrendsPayload } from "@/lib/types";

type Lado = {
  player_id?: string | null;
  nombre?: string | null;
  posicion?: string | null;
  foto?: string | null;
  xp_j1?: number | null;
  xp_4j?: number | null;
  prob_titular?: number | null;
  techo?: number | null;
  valor?: number | null;
  prevision_7d_pct?: number | null;
  subida_7d_euros?: number | null;
};

type ImpactoRival = {
  rival?: string | null;
  posicion_liga?: number | null;
  aviso?: string | null;
  importe_eur?: number | null;
};

export type ComparacionLiga = {
  ok?: boolean;
  jugador_a?: Lado;
  jugador_b?: Lado;
  ingreso_venta_a?: number | null;
  ingreso_fuente?: string | null;
  esperar_oferta_24h?: boolean;
  coste_adquisicion_b?: number | null;
  coste_fuente?: string | null;
  coste_etiqueta?: string | null;
  puja_maxima?: number | null;
  saldo_escenario_maxima?: number | null;
  clausula_abierta?: boolean | null;
  clausula_abre?: string | null;
  delta_caja?: number | null;
  saldo_final_tras_cambio?: number | null;
  delta_xp_j1?: number | null;
  delta_xp_4j?: number | null;
  delta_titularidad?: number | null;
  delta_techo?: number | null;
  delta_subida_7d_euros?: number | null;
  coste_neto_a_7_dias?: number | null;
  coste_por_punto_extra?: number | null;
  dias_amortizacion?: number | null;
  impacto_rival?: ImpactoRival | null;
  veredicto_etiqueta?: string | null;
  ganador?: "A" | "B" | string | null;
  ganador_nombre?: string | null;
  pill?: string | null;
  nota_ejecucion?: string | null;
};

function millones(value: number | null | undefined, signed = false): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  const text = (Math.abs(value) / 1_000_000).toLocaleString("es-ES", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const sign = value < 0 ? "−" : signed && value > 0 ? "+" : "";
  return `${sign}${text}M`;
}

function decimal(value: number | null | undefined, signed = false): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  const text = Math.abs(value).toLocaleString("es-ES", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const sign = value < 0 ? "−" : signed && value > 0 ? "+" : "";
  return `${sign}${text}`;
}

function pct(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  const text = Math.abs(value).toLocaleString("es-ES", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${text}%`;
}

function share(value: number | null | undefined, other: number | null | undefined): number {
  const left = typeof value === "number" ? Math.abs(value) : 0;
  const right = typeof other === "number" ? Math.abs(other) : 0;
  const top = Math.max(left, right, 1e-9);
  return Math.max(0.04, Math.min(1, left / top));
}

function xpOf(player: Player): number {
  const value = player.jornada_ev ?? player.own_expected_points ?? player.expected_points;
  return typeof value === "number" ? value : Number.POSITIVE_INFINITY;
}

/** Titular con menos puntos esperados en la misma posición. */
export function titularMasFlojo(xi: Player[], position?: string | null): Player | null {
  const withId = xi.filter((player) => player.player_id);
  const same = position ? withId.filter((player) => player.position === position) : [];
  const pool = same.length ? same : withId;
  if (!pool.length) return null;
  return pool.reduce((worst, player) => (xpOf(player) < xpOf(worst) ? player : worst));
}

function roster(optimize: OptimizePayload | null, squads: SquadsPayload | null): Player[] {
  const lined = [...(optimize?.xi || []), ...(optimize?.benched || [])].filter((player) => player.player_id);
  if (lined.length) return lined;
  return (squads?.self?.players || [])
    .filter((player) => player.player_id)
    .map((player) => ({
      player_id: player.player_id,
      name: player.name,
      nickname: player.nickname,
      position: player.position,
      image_url: player.image_url,
      market_value: player.market_value,
      expected_points: player.own_expected_points,
      p_titular: player.p_titular,
    }));
}

function BarRow({
  label,
  left,
  right,
  leftValue,
  rightValue,
}: {
  label: string;
  left: string;
  right: string;
  leftValue: number | null | undefined;
  rightValue: number | null | undefined;
}) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_7.6rem_minmax(0,1fr)] items-end gap-2">
      <div className="text-right">
        <p className="font-mono text-[12.5px] tabular-nums text-white/80">{left}</p>
        <span className="mt-1 flex h-1.5 justify-end overflow-hidden rounded-full bg-white/[0.08]">
          <span className="block h-full rounded-full bg-[#FC734D]" style={{ width: `${share(leftValue, rightValue) * 100}%` }} />
        </span>
      </div>
      <p className="pb-0.5 text-center font-mono text-[10px] uppercase leading-tight tracking-wide text-white/40">{label}</p>
      <div>
        <p className="font-mono text-[12.5px] tabular-nums text-[#7fd4ff]">{right}</p>
        <span className="mt-1 block h-1.5 rounded-full bg-white/[0.08]">
          <span className="block h-full rounded-full bg-[#0297DE]" style={{ width: `${share(rightValue, leftValue) * 100}%` }} />
        </span>
      </div>
    </div>
  );
}

function Cara({
  lado,
  foto,
  gana,
}: {
  lado: Lado | undefined;
  foto: string | null;
  gana: boolean;
}) {
  const nombre = lado?.nombre || "Jugador";
  return (
    <div className="flex w-[5.5rem] flex-col items-center gap-1.5 text-center">
      <Face name={nombre} src={foto} size={64} ring={gana ? "#0297DE" : "#FC734D"} />
      <p className="line-clamp-2 text-[13px] font-semibold leading-tight text-white">{nombre}</p>
      <p className="text-[11px] uppercase tracking-wide text-white/40">{lado?.posicion || "—"}</p>
    </div>
  );
}

type Opcion = { id: string; nombre: string; posicion: string; club: string; foto: string | null; dueno: string };

/** Todos los jugadores de la foto: tu plantilla, el mercado, los rivales y el catálogo. */
function universo(optimize: OptimizePayload | null, squads: SquadsPayload | null, trends: TrendsPayload | null): Opcion[] {
  const out = new Map<string, Opcion>();
  const add = (player: Player | null | undefined, dueno: string) => {
    const id = player?.player_id ? String(player.player_id) : "";
    if (!id || out.has(id)) return;
    out.set(id, {
      id,
      nombre: playerName(player),
      posicion: player?.position || "",
      club: player?.club || "",
      foto: player?.image_url || null,
      dueno,
    });
  };
  roster(optimize, squads).forEach((player) => add(player, "Tu equipo"));
  (trends?.market_decisions || []).forEach((player) => add(player, "Mercado"));
  (squads?.rivals || []).forEach((rival) => (rival.players || []).forEach((player) => add(player as Player, rival.manager_name || "Rival")));
  (trends?.catalog || []).forEach((player) => add(player, player.owner === "libre" ? "Libre" : ""));
  return [...out.values()];
}

function Selector({
  etiqueta,
  color,
  opciones,
  valor,
  excluir,
  onChange,
  photos,
}: {
  etiqueta: string;
  color: string;
  opciones: Opcion[];
  valor: string | null;
  excluir: string | null;
  onChange: (id: string) => void;
  photos: PhotoIndex;
}) {
  const [abierto, setAbierto] = useState(!valor);
  const [texto, setTexto] = useState("");
  const elegido = opciones.find((opcion) => opcion.id === valor) || null;
  const filtradas = useMemo(() => {
    const aguja = texto.trim().toLowerCase();
    return opciones
      .filter((opcion) => opcion.id !== excluir)
      .filter((opcion) => !aguja || `${opcion.nombre} ${opcion.club}`.toLowerCase().includes(aguja))
      .slice(0, 30);
  }, [opciones, texto, excluir]);
  const foto = (opcion: Opcion) => opcion.foto || photoFor(photos, opcion.id, opcion.nombre);

  if (!abierto && elegido) {
    return (
      <button
        type="button"
        onClick={() => setAbierto(true)}
        className="flex w-full items-center gap-3 rounded-2xl border bg-white/[0.03] px-3 py-2.5 text-left transition-colors hover:bg-white/[0.06]"
        style={{ borderColor: `${color}55` }}
      >
        <Face name={elegido.nombre} src={foto(elegido)} size={40} ring={color} />
        <span className="min-w-0 flex-1">
          <span className="block text-[10.5px] font-semibold uppercase tracking-[0.16em]" style={{ color }}>
            {etiqueta}
          </span>
          <span className="block truncate text-[15px] font-semibold text-white">{elegido.nombre}</span>
          <span className="block truncate text-[12px] text-white/45">{[elegido.posicion, elegido.club, elegido.dueno].filter(Boolean).join(" · ")}</span>
        </span>
        <span className="text-[12px] font-medium text-white/50">Cambiar</span>
      </button>
    );
  }

  return (
    <div className="rounded-2xl border bg-white/[0.03] p-3" style={{ borderColor: `${color}55` }}>
      <p className="text-[10.5px] font-semibold uppercase tracking-[0.16em]" style={{ color }}>
        {etiqueta}
      </p>
      <input
        value={texto}
        onChange={(event) => setTexto(event.target.value)}
        placeholder="Busca un jugador o un equipo"
        aria-label={`Buscar ${etiqueta}`}
        className="mt-2 h-11 w-full rounded-xl border border-white/10 bg-black/30 px-3 text-[14px] text-white outline-none placeholder:text-white/30"
      />
      <ul className="mt-2 max-h-56 overflow-y-auto">
        {filtradas.map((opcion) => (
          <li key={opcion.id}>
            <button
              type="button"
              onClick={() => {
                onChange(opcion.id);
                setTexto("");
                setAbierto(false);
              }}
              className="flex w-full items-center gap-3 rounded-xl px-2 py-2 text-left transition-colors hover:bg-white/[0.06]"
            >
              <Face name={opcion.nombre} src={foto(opcion)} size={32} />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[14px] font-medium text-white">{opcion.nombre}</span>
                <span className="block truncate text-[11.5px] text-white/40">{[opcion.posicion, opcion.club].filter(Boolean).join(" · ")}</span>
              </span>
              {opcion.dueno ? <span className="shrink-0 text-[11px] text-white/40">{opcion.dueno}</span> : null}
            </button>
          </li>
        ))}
        {!filtradas.length ? <li className="px-2 py-3 text-[13px] text-white/40">Nadie coincide con la búsqueda.</li> : null}
      </ul>
    </div>
  );
}

/** Cara a cara libre: eliges los dos jugadores y la app pone el coste real de la liga. */
export function ComparadorModal({
  inicialA = null,
  inicialB = null,
  onClose,
}: {
  inicialA?: string | null;
  inicialB?: string | null;
  onClose: () => void;
}) {
  const { state } = useDashboard();
  const optimize = state.optimize as OptimizePayload | null;
  const squads = state.squads as SquadsPayload | null;
  const trends = state.trends as TrendsPayload | null;
  const opciones = useMemo(() => universo(optimize, squads, trends), [optimize, squads, trends]);
  const [chosen, setChosen] = useState<string | null>(inicialA);
  const [objetivoId, setObjetivoId] = useState<string | null>(inicialB);
  const [data, setData] = useState<ComparacionLiga | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const photos = useMemo(
    () => buildPhotoIndex(state.plan, optimize, squads, trends),
    [state.plan, optimize, squads, trends],
  );

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    if (!chosen || !objetivoId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    const params = new URLSearchParams(window.location.search);
    const query = new URLSearchParams();
    const league = params.get("league");
    if (league) query.set("league", league);
    query.set("actual", chosen);
    query.set("objetivo", objetivoId);
    getJson<ComparacionLiga>(apiUrl("/api/comparar", query))
      .then((payload) => {
        if (!cancelled) setData(payload);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setData(null);
          setError(reason instanceof Error ? reason.message : "No se ha podido comparar.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [chosen, objetivoId]);

  const a = data?.jugador_a;
  const b = data?.jugador_b;
  const fotoA = a?.foto || photoFor(photos, chosen, a?.nombre || "");
  const fotoB = b?.foto || photoFor(photos, objetivoId, b?.nombre || "");
  const ganaB = data?.ganador === "B";
  const delta = data?.delta_xp_4j;
  const saldo = data?.saldo_final_tras_cambio;
  const pillCara = data?.pill === "CLÁUSULA CARA";

  const body = (
    <div className="fixed inset-0 z-[200] flex items-end justify-center sm:items-center" role="presentation">
      <button type="button" aria-label="Cerrar comparador" className="absolute inset-0 bg-black/70" onClick={onClose} />
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="comparador-titulo"
        className="relative max-h-[100dvh] w-full overflow-y-auto rounded-t-3xl border border-[#0297DE]/35 px-4 py-5 shadow-[0_0_40px_rgba(2,151,222,0.18)] sm:max-w-xl sm:rounded-3xl sm:px-6"
        style={{ background: "#02070A" }}
      >
        <div className="mb-4 flex items-center justify-between gap-3">
          <p id="comparador-titulo" className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[#0297DE]">
            Cara a Cara
          </p>
          <button type="button" onClick={onClose} className="text-[13px] text-white/50 hover:text-white">
            Cerrar
          </button>
        </div>

        <div className="mb-5 flex flex-col gap-2">
          <Selector etiqueta="Jugador A" color="#FC734D" opciones={opciones} valor={chosen} excluir={objetivoId} onChange={setChosen} photos={photos} />
          <Selector etiqueta="Jugador B" color="#0297DE" opciones={opciones} valor={objetivoId} excluir={chosen} onChange={setObjetivoId} photos={photos} />
        </div>

        {!opciones.length ? (
          <p className="text-[14px] text-white/60">Todavía no hay jugadores en la foto. Actualiza y vuelve a comparar.</p>
        ) : !chosen || !objetivoId ? (
          <p className="py-6 text-center text-[14px] text-white/45">Elige los dos jugadores para ver el cara a cara.</p>
        ) : loading && !data ? (
          <p className="py-10 text-center text-[14px] text-white/50">Calculando el coste real…</p>
        ) : error ? (
          <p className="text-[14px] text-[#FC734D]">{error}</p>
        ) : data ? (
          <div className="flex flex-col gap-5">
            <div className="flex items-start justify-between gap-2">
              <Cara lado={a} foto={fotoA} gana={!ganaB} />
              <div className="min-w-0 flex-1 pt-2 text-center">
                <p className="text-[10px] uppercase tracking-[0.16em] text-white/40">La app se queda con</p>
                <p className="mt-1 text-[1.35rem] font-semibold uppercase leading-none tracking-tight text-white">
                  {data.ganador_nombre || "—"}
                </p>
                <p className="mt-2 text-[11px] font-semibold uppercase leading-snug tracking-wide text-white/70">
                  {data.veredicto_etiqueta}
                </p>
                {data.pill ? (
                  <span
                    className="mt-2 inline-flex rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide"
                    style={{
                      color: pillCara ? "#FC734D" : "#0297DE",
                      background: pillCara ? "rgba(252,115,77,0.14)" : "rgba(2,151,222,0.16)",
                    }}
                  >
                    {data.pill}
                  </span>
                ) : null}
              </div>
              <Cara lado={b} foto={fotoB} gana={ganaB} />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-2xl border border-[#0297DE]/40 bg-[#0297DE]/10 px-3 py-3">
                <p className="text-[11px] font-medium uppercase tracking-wide text-white/45">Tu once</p>
                <p className="mt-1 font-mono text-[1.35rem] font-semibold leading-none tabular-nums" style={{ color: typeof delta === "number" && delta < 0 ? "#FC734D" : "#0297DE" }}>
                  {decimal(delta, true)} pts/j
                </p>
                <p className="mt-1 text-[11px] text-white/45">próximas 4J</p>
              </div>
              <div className="rounded-2xl border border-white/10 bg-white/[0.03] px-3 py-3">
                <p className="text-[11px] font-medium uppercase tracking-wide text-white/45">Saldo final</p>
                <p className="mt-1 font-mono text-[1.35rem] font-semibold leading-none tabular-nums text-white">{millones(saldo)} €</p>
                <p className="mt-1 truncate text-[12px] text-white/55">{data.coste_etiqueta || "Sin coste de ejecución"}</p>
              </div>
            </div>

            <div className="flex flex-col gap-3.5">
              <BarRow
                label="xP Próximas 4J"
                left={decimal(a?.xp_4j)}
                right={decimal(b?.xp_4j)}
                leftValue={a?.xp_4j}
                rightValue={b?.xp_4j}
              />
              <BarRow
                label="Titularidad"
                left={typeof a?.prob_titular === "number" ? `${Math.round(a.prob_titular * 100)}%` : "—"}
                right={typeof b?.prob_titular === "number" ? `${Math.round(b.prob_titular * 100)}%` : "—"}
                leftValue={a?.prob_titular}
                rightValue={b?.prob_titular}
              />
              <BarRow
                label="Coste Real en Liga"
                left={`Venta: ${millones(data.ingreso_venta_a)}`}
                right={`Compra/Cláusula: ${millones(data.coste_adquisicion_b)}`}
                leftValue={data.ingreso_venta_a}
                rightValue={data.coste_adquisicion_b}
              />
              <BarRow
                label="Subida en 7 días"
                left={`${millones(a?.subida_7d_euros, true)} (${pct(a?.prevision_7d_pct)})`}
                right={`${millones(b?.subida_7d_euros, true)} (${pct(b?.prevision_7d_pct)})`}
                leftValue={a?.subida_7d_euros}
                rightValue={b?.subida_7d_euros}
              />
              <BarRow
                label="Coste real tras 7d"
                left={`Hoy: ${millones(data.delta_caja, true)}`}
                right={`En 7d: ${millones(data.coste_neto_a_7_dias, true)}`}
                leftValue={data.delta_caja}
                rightValue={data.coste_neto_a_7_dias}
              />
            </div>

            {data.impacto_rival?.aviso ? (
              <p className="rounded-2xl bg-[#FC734D]/10 px-3 py-2.5 text-[13px] leading-snug text-[#FC734D]">
                {data.impacto_rival.aviso}
                {typeof data.impacto_rival.posicion_liga === "number" ? ` · ${data.impacto_rival.posicion_liga}º en la liga` : ""}
              </p>
            ) : null}
            {data.nota_ejecucion ? <p className="text-[12.5px] leading-relaxed text-white/55">{data.nota_ejecucion}</p> : null}
            <p className="font-mono text-[11.5px] leading-relaxed text-white/40">
              {typeof data.coste_por_punto_extra === "number" && data.coste_por_punto_extra > 0
                ? `${millones(data.coste_por_punto_extra)} por cada +1,0 pt/j. `
                : ""}
              {typeof data.dias_amortizacion === "number" ? `La subida de B recupera la diferencia en ${decimal(data.dias_amortizacion)} días. ` : ""}
              {typeof data.puja_maxima === "number" ? `Si vas al máximo (${millones(data.puja_maxima)}) el saldo queda en ${millones(data.saldo_escenario_maxima)}.` : ""}
              {typeof data.delta_xp_j1 === "number" ? ` Jornada inmediata: ${decimal(data.delta_xp_j1, true)} pts.` : ""}
              {typeof data.delta_techo === "number" ? ` Techo: ${decimal(data.delta_techo, true)}.` : ""}
            </p>
          </div>
        ) : null}
      </section>
    </div>
  );

  return createPortal(body, document.body);
}

/** Botón suelto: abre el comparador vacío para elegir los dos jugadores. */
export function ComparadorLauncher({ className = "" }: { className?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={`inline-flex h-10 shrink-0 items-center gap-2 rounded-full border border-[#0297DE]/40 bg-[#0297DE]/10 px-4 text-[13.5px] font-semibold text-[#7fd4ff] transition-colors hover:bg-[#0297DE]/20 ${className}`}
      >
        <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <path d="M5 3 2 6l3 3M2 6h9M11 13l3-3-3-3M14 10H5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        Comparar
      </button>
      {open ? <ComparadorModal onClose={() => setOpen(false)} /> : null}
    </>
  );
}

/** Abre el comparador con el jugador como B y tu titular más flojo de su puesto como A. */
export function CompararConSugerido({ objetivoId, posicion, onClose }: { objetivoId: string; posicion?: string | null; onClose: () => void }) {
  const { state } = useDashboard();
  const optimize = state.optimize as OptimizePayload | null;
  const squads = state.squads as SquadsPayload | null;
  const sugerido = useMemo(() => {
    const xi = (optimize?.xi || []).filter((player) => player.player_id && String(player.player_id) !== objetivoId);
    const pool = xi.length ? xi : roster(optimize, squads).filter((player) => String(player.player_id) !== objetivoId);
    return titularMasFlojo(pool, posicion);
  }, [optimize, squads, objetivoId, posicion]);
  return <ComparadorModal inicialA={sugerido?.player_id ? String(sugerido.player_id) : null} inicialB={objetivoId} onClose={onClose} />;
}

export function CompararButton({
  objetivoId,
  posicion,
  className = "",
}: {
  objetivoId?: string | null;
  posicion?: string | null;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  if (!objetivoId) return null;
  return (
    <>
      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          event.preventDefault();
          setOpen(true);
        }}
        className={`shrink-0 rounded-full px-2.5 py-1 text-[12px] font-semibold text-[#0297DE] transition-colors hover:bg-[#0297DE]/10 ${className}`}
      >
        Comparar
      </button>
      {open ? <CompararConSugerido objetivoId={objetivoId} posicion={posicion} onClose={() => setOpen(false)} /> : null}
    </>
  );
}
