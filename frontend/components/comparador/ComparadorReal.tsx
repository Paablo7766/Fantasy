"use client";

import { Crest } from "@/components/ui/Crest";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useDashboard } from "@/components/DashboardProvider";
import { Face, TONE, money } from "@/components/ui/kit";
import { apiUrl } from "@/lib/core/api";
import { errorText, playerName } from "@/lib/core/format";
import { buildPhotoIndex, photoFor, type PhotoIndex } from "@/lib/core/photoIndex";
import type { OptimizePayload, Player, SquadsPayload, TrendsPayload } from "@/lib/types";

type Precio = {
  importe?: number | null;
  tipo?: "mercado" | "venta_rival" | "clausula" | "propio" | string | null;
  etiqueta?: string | null;
  clausula_abierta?: boolean | null;
  clausula_abre?: string | null;
  rival?: string | null;
};

type Lado = {
  player_id?: string | null;
  nombre?: string | null;
  posicion?: string | null;
  club?: string | null;
  foto?: string | null;
  xp_j1?: number | null;
  xp_4j?: number | null;
  prob_titular?: number | null;
  techo?: number | null;
  media?: number | null;
  valor?: number | null;
  prevision_7d_pct?: number | null;
  subida_7d_euros?: number | null;
  precio?: Precio | null;
  proximos?: Array<{ rival?: string | null; casa?: boolean | null; dificultad?: string | null }>;
  ultimas?: number[];
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
  coste_adquisicion_b?: number | null;
  coste_fuente?: string | null;
  delta_caja?: number | null;
  saldo_final_tras_cambio?: number | null;
  delta_xp_j1?: number | null;
  delta_xp_4j?: number | null;
  delta_titularidad?: number | null;
  delta_subida_7d_euros?: number | null;
  coste_neto_a_7_dias?: number | null;
  coste_por_punto_extra?: number | null;
  impacto_rival?: ImpactoRival | null;
  veredicto_etiqueta?: string | null;
  ganador?: "A" | "B" | string | null;
  ganador_nombre?: string | null;
  pill?: string | null;
  nota_ejecucion?: string | null;
};

const COLOR_A = "#FF8A5B";
const COLOR_B = "#38B6F5";

const PRICE_KIND: Record<string, string> = {
  mercado: "Mercado",
  venta_rival: "Venta de rival",
  clausula: "Cláusula",
  propio: "Tuyo",
};

const DIFF_COLOR: Record<string, string> = {
  muy_facil: TONE.green,
  very_easy: TONE.green,
  facil: "#4FD1A5",
  easy: "#4FD1A5",
  media: TONE.amber,
  medium: TONE.amber,
  dificil: "#FF9A5A",
  hard: "#FF9A5A",
  muy_dificil: TONE.red,
  very_hard: TONE.red,
};

function num(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function dec(value: number | null | undefined, signed = false): string {
  const v = num(value);
  if (v === null) return "—";
  const text = Math.abs(v).toLocaleString("es-ES", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const sign = v < 0 ? "−" : signed && v > 0 ? "+" : "";
  return `${sign}${text}`;
}

function share(value: number | null | undefined): string {
  const v = num(value);
  return v === null ? "—" : `${Math.round(v * 100)}%`;
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

type Opcion = { id: string; nombre: string; posicion: string; club: string; foto: string | null; dueno: string };

/** Todos los jugadores de la foto: tu plantilla, el mercado, los rivales y el catálogo. */
function universo(optimize: OptimizePayload | null, squads: SquadsPayload | null, trends: TrendsPayload | null): Opcion[] {
  const out = new Map<string, Opcion>();
  const add = (player: Player | null | undefined, dueno: string) => {
    const id = player?.player_id ? String(player.player_id) : "";
    if (!id || out.has(id)) return;
    out.set(id, { id, nombre: playerName(player), posicion: player?.position || "", club: player?.club || "", foto: player?.image_url || null, dueno });
  };
  roster(optimize, squads).forEach((player) => add(player, "Tu equipo"));
  (trends?.market_decisions || []).forEach((player) => add(player, "Mercado"));
  (squads?.rivals || []).forEach((rival) => (rival.players || []).forEach((player) => add(player as Player, rival.manager_name || "Rival")));
  (trends?.catalog || []).forEach((player) => add(player, player.owner === "libre" ? "Libre" : ""));
  return [...out.values()];
}

/** Lista de búsqueda. El hueco de arriba no se esconde: aquí solo se elige quién lo ocupa. */
function Picker({
  color,
  etiqueta,
  opciones,
  excluir,
  photos,
  onPick,
  onCancel,
}: {
  color: string;
  etiqueta: string;
  opciones: Opcion[];
  excluir: string | null;
  photos: PhotoIndex;
  onPick: (id: string) => void;
  onCancel: () => void;
}) {
  const [texto, setTexto] = useState("");
  const filtradas = useMemo(() => {
    const aguja = texto.trim().toLowerCase();
    return opciones
      .filter((opcion) => opcion.id !== excluir)
      .filter((opcion) => !aguja || `${opcion.nombre} ${opcion.club} ${opcion.dueno}`.toLowerCase().includes(aguja))
      .slice(0, 40);
  }, [opciones, texto, excluir]);
  return (
    <div className="flex flex-col rounded-3xl bg-raised-deep p-3">
      <div className="flex items-center gap-2 px-1">
        <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: color }} />
        <p className="flex-1 text-[13px] font-semibold text-white">Buscar {etiqueta}</p>
        <button type="button" onClick={onCancel} className="text-[13px] font-medium text-white/50 hover:text-white">
          Cancelar
        </button>
      </div>
      <input
        value={texto}
        onChange={(event) => setTexto(event.target.value)}
        placeholder="Nombre, equipo o dueño"
        aria-label={`Buscar ${etiqueta}`}
        className="mt-3 h-12 w-full rounded-full bg-raised px-5 text-[16px] text-white sm:text-[15px] outline-none placeholder:text-white/35 focus:shadow-[inset_0_0_0_1px_rgba(255,255,255,0.25)]"
      />
      <ul className="mt-2 max-h-[18rem] overflow-y-auto">
        {filtradas.map((opcion) => (
          <li key={opcion.id}>
            <button
              type="button"
              onClick={() => onPick(opcion.id)}
              className="flex w-full items-center gap-3 rounded-2xl px-2 py-2 text-left transition-colors hover:bg-raised"
            >
              <Face name={opcion.nombre} src={opcion.foto || photoFor(photos, opcion.id, opcion.nombre)} size={36} />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[14px] font-medium text-white">{opcion.nombre}</span>
                <span className="block truncate text-[12px] text-white/40">{[opcion.posicion, opcion.club].filter(Boolean).join(" · ")}</span>
              </span>
              {opcion.dueno ? <span className="shrink-0 rounded-full bg-white/[0.05] px-2 py-0.5 text-[11px] text-white/50">{opcion.dueno}</span> : null}
            </button>
          </li>
        ))}
        {!filtradas.length ? <li className="px-2 py-6 text-center text-[13px] text-white/40">Nadie coincide con la búsqueda.</li> : null}
      </ul>
    </div>
  );
}

/** Hueco de un jugador: foto grande, nombre y botón para cambiarlo. */
function Slot({
  color,
  opcion,
  lado,
  photos,
  winner,
  active,
  onChange,
}: {
  color: string;
  opcion: Opcion | null;
  lado: Lado | undefined;
  photos: PhotoIndex;
  winner: boolean;
  active: boolean;
  onChange: () => void;
}) {
  const nombre = lado?.nombre || opcion?.nombre || "Jugador";
  const foto = lado?.foto || opcion?.foto || (opcion ? photoFor(photos, opcion.id, opcion.nombre) : null);
  const sub = [lado?.posicion || opcion?.posicion, lado?.club || opcion?.club].filter(Boolean).join(" · ");
  return (
    <button
      type="button"
      onClick={onChange}
      aria-pressed={active}
      className="group relative flex min-w-0 flex-1 flex-col items-center rounded-3xl px-2 pb-3 pt-4 text-center transition-colors"
      style={{
        background: winner || active ? `radial-gradient(90% 80% at 50% 0%, ${color}30, transparent 70%), #141414` : "#141414",
        boxShadow: winner || active ? `inset 0 0 0 ${active ? 2 : 1}px ${color}` : "none",
      }}
      aria-label={active ? `Eligiendo. Ahora es ${nombre}` : `Cambiar ${nombre}`}
    >
      {winner ? (
        <span className="absolute -top-2.5 rounded-full px-2.5 py-0.5 text-[10.5px] font-semibold text-[#0a0706]" style={{ background: color }}>
          Mejor opción
        </span>
      ) : null}
      <Face name={nombre} src={foto} size={64} ring={color} />
      <span className="mt-2 block w-full truncate text-[15px] font-semibold text-white">{nombre}</span>
      <span className="block w-full truncate text-[11.5px] text-white/45">{sub || " "}</span>
      <span className="mt-2 text-[11.5px] font-medium text-white/45 transition-colors group-hover:text-white">{active ? "Eligiendo…" : "Cambiar"}</span>
    </button>
  );
}

function EmptySlot({ color, etiqueta, active, onPick }: { color: string; etiqueta: string; active: boolean; onPick: () => void }) {
  return (
    <button
      type="button"
      onClick={onPick}
      aria-pressed={active}
      className="flex min-h-[10.5rem] min-w-0 flex-1 flex-col items-center justify-center gap-2.5 rounded-3xl border border-dashed bg-raised-deep text-center transition-colors hover:bg-raised"
      style={{ borderColor: active ? color : `${color}66`, background: active ? `${color}14` : undefined, boxShadow: active ? `inset 0 0 0 1px ${color}` : undefined }}
    >
      <span className="grid h-12 w-12 place-items-center rounded-full text-[22px]" style={{ color, background: `${color}1a` }}>
        +
      </span>
      <span className="text-[13px] font-medium text-white/70">{active ? "Elige abajo" : `Elegir ${etiqueta}`}</span>
    </button>
  );
}

/** Fila de duelo: cifra de cada lado y barra hacia el que gana. */
function Duel({
  label,
  a,
  b,
  va,
  vb,
  higherWins = true,
  hintA,
  hintB,
}: {
  label: string;
  a: string;
  b: string;
  va: number | null;
  vb: number | null;
  higherWins?: boolean;
  hintA?: ReactNode;
  hintB?: ReactNode;
}) {
  const both = va !== null && vb !== null;
  const winA = both && va !== vb && (higherWins ? va > vb : va < vb);
  const winB = both && va !== vb && !winA;
  const top = Math.max(Math.abs(va ?? 0), Math.abs(vb ?? 0), 1e-9);
  const width = (value: number | null) => `${value === null ? 0 : Math.max(6, (Math.abs(value) / top) * 100)}%`;
  return (
    <div className="py-3">
      <p className="text-center text-[11px] font-medium text-white/40">{label}</p>
      <div className="mt-1.5 grid grid-cols-2 items-center gap-3">
        <div className="min-w-0 text-right">
          <p className={`truncate text-[17px] tabular-nums ${winA ? "font-semibold" : "font-medium text-white/60"}`} style={winA ? { color: COLOR_A } : undefined}>
            {a}
          </p>
          {hintA ? <p className="truncate text-[11px] text-white/40">{hintA}</p> : null}
          <span className="mt-1.5 flex h-1 justify-end rounded-full bg-white/[0.06]">
            <span className="block h-full rounded-full" style={{ width: width(va), background: winA ? COLOR_A : "rgba(255,255,255,0.22)" }} />
          </span>
        </div>
        <div className="min-w-0">
          <p className={`truncate text-[17px] tabular-nums ${winB ? "font-semibold" : "font-medium text-white/60"}`} style={winB ? { color: COLOR_B } : undefined}>
            {b}
          </p>
          {hintB ? <p className="truncate text-[11px] text-white/40">{hintB}</p> : null}
          <span className="mt-1.5 block h-1 rounded-full bg-white/[0.06]">
            <span className="block h-full rounded-full" style={{ width: width(vb), background: winB ? COLOR_B : "rgba(255,255,255,0.22)" }} />
          </span>
        </div>
      </div>
    </div>
  );
}

function PriceHint({ precio }: { precio: Precio | null | undefined }) {
  if (!precio?.tipo) return null;
  const kind = PRICE_KIND[precio.tipo] || "Sin precio";
  const closed = precio.tipo === "clausula" && precio.clausula_abierta === false;
  return (
    <>
      {kind}
      {closed ? <span style={{ color: TONE.amber }}> · abre {precio.clausula_abre || "más tarde"}</span> : null}
    </>
  );
}

function LastWeeks({ values, color, align }: { values: number[]; color: string; align: "left" | "right" }) {
  if (!values.length) return <p className={`text-[12px] text-white/35 ${align === "right" ? "text-right" : ""}`}>Sin datos</p>;
  const top = Math.max(10, ...values);
  return (
    <div className={`flex h-12 items-end gap-1 ${align === "right" ? "justify-end" : ""}`}>
      {values.map((value, index) => (
        <span key={index} className="flex w-5 flex-col items-center justify-end gap-0.5">
          <span className="text-[9.5px] tabular-nums text-white/55">{Math.round(value)}</span>
          <span className="w-full rounded-sm" style={{ height: Math.max(3, (Math.max(0, value) / top) * 30), background: color, opacity: 0.45 + (index / values.length) * 0.55 }} />
        </span>
      ))}
    </div>
  );
}

function Fixtures({ items, align }: { items: Lado["proximos"]; align: "left" | "right" }) {
  if (!items?.length) return <p className={`text-[12px] text-white/35 ${align === "right" ? "text-right" : ""}`}>Sin calendario</p>;
  return (
    <ul className={`flex flex-col gap-1.5 ${align === "right" ? "items-end" : "items-start"}`}>
      {items.map((item, index) => {
        const color = (item.dificultad && DIFF_COLOR[item.dificultad]) || TONE.gray;
        return (
          <li key={`${item.rival}-${index}`} className="flex max-w-full items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px]" style={{ background: `${color}17` }}>
            <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: color }} />
            <Crest club={item.rival} size={16} />
            <span className="truncate text-white/80">{item.rival}</span>
            <span className="shrink-0 text-white/35">{item.casa === true ? "C" : item.casa === false ? "F" : ""}</span>
          </li>
        );
      })}
    </ul>
  );
}

function headline(data: ComparacionLiga): { title: string; subtitle: string } {
  const label = (data.veredicto_etiqueta || "").toUpperCase();
  const winner = data.ganador_nombre || "—";
  let subtitle = "Ventaja ligera";
  if (label.includes("OBLIGATORIO")) subtitle = "Cambio obligatorio";
  else if (label.startsWith("CLARAMENTE")) subtitle = "Claramente mejor";
  else if (label.startsWith("AJUSTADA")) subtitle = "Ajustada, por poco";
  else if (label.includes("INFLADA")) subtitle = "La cláusula está inflada";
  else if (label.startsWith("MEJOR QUEDARSE")) subtitle = "El cambio no compensa";
  return { title: winner, subtitle };
}

/** Dos o tres frases con el porqué, en lenguaje llano. */
function reasons(data: ComparacionLiga): string[] {
  const a = data.jugador_a?.nombre || "A";
  const b = data.jugador_b?.nombre || "B";
  const out: string[] = [];
  const xp = num(data.delta_xp_4j);
  if (xp !== null && Math.abs(xp) >= 0.1) {
    out.push(`${xp > 0 ? b : a} suma ${dec(Math.abs(xp))} pts más por jornada en las próximas 4.`);
  } else if (xp !== null) {
    out.push("Rinden casi igual en las próximas 4 jornadas.");
  }
  const tit = num(data.delta_titularidad);
  if (tit !== null && Math.abs(tit) >= 0.1) {
    out.push(`${tit > 0 ? b : a} es más fijo: ${Math.round(Math.abs(tit) * 100)} puntos más de titularidad.`);
  }
  const neto = num(data.coste_neto_a_7_dias);
  const caja = num(data.delta_caja);
  if (data.pill === "CLÁUSULA CARA") {
    out.push(`La cláusula de ${b} está muy por encima de su valor.`);
  } else if (neto !== null && neto <= 0) {
    out.push("La subida prevista en 7 días paga el cambio.");
  } else if (caja !== null && caja > 0) {
    out.push(`Pasar de ${a} a ${b} te cuesta ${money(caja)} de caja hoy.`);
  } else if (caja !== null && caja < 0) {
    out.push(`Pasar de ${a} a ${b} te deja ${money(-caja)} más en caja.`);
  }
  return out.slice(0, 3);
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
  const [idA, setIdA] = useState<string | null>(inicialA);
  const [idB, setIdB] = useState<string | null>(inicialB);
  const [picking, setPicking] = useState<"A" | "B" | null>(!inicialA ? "A" : !inicialB ? "B" : null);
  const [attempt, setAttempt] = useState(0);
  // Un único resultado por par e intento: cargando es «aún no ha llegado el de este intento».
  const [result, setResult] = useState<{ key: string; data?: ComparacionLiga; error?: string } | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const photos = useMemo(() => buildPhotoIndex(state.plan, optimize, squads, trends), [state.plan, optimize, squads, trends]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [onClose]);

  useEffect(() => {
    if (!idA || !idB) return;
    const pair = `${idA}|${idB}`;
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 45_000);
    const key = `${pair}#${attempt}`;
    let cancelled = false;
    const params = new URLSearchParams(window.location.search);
    const query = new URLSearchParams();
    const league = params.get("league");
    if (league) query.set("league", league);
    query.set("actual", idA);
    query.set("objetivo", idB);
    fetch(apiUrl("/api/comparar", query), { signal: controller.signal })
      .then(async (response) => {
        const payload = (await response.json().catch(() => ({
          ok: false,
          error: { message: `HTTP ${response.status}` },
        }))) as ComparacionLiga & { error?: { message?: string }; message?: string };
        if (!response.ok || payload.ok === false) {
          throw new Error(errorText(payload, "No se ha podido comparar."));
        }
        return payload;
      })
      .then((payload) => {
        if (!cancelled) setResult({ key, data: payload });
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        const aborted = reason instanceof Error && reason.name === "AbortError";
        setResult({
          key,
          error: aborted ? "La comparación está tardando demasiado. Vuelve a intentarlo." : reason instanceof Error ? reason.message : "No se ha podido comparar.",
        });
      })
      .finally(() => window.clearTimeout(timer));
    return () => {
      cancelled = true;
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [idA, idB, attempt]);

  const pick = (id: string) => {
    if (picking === "A") {
      setIdA(id);
      setPicking(idB ? null : "B");
    } else {
      setIdB(id);
      setPicking(idA ? null : "A");
    }
    // En móvil la lista empuja los huecos fuera de la vista: se sube para ver a quién has elegido.
    scroller.current?.scrollTo({ top: 0, behavior: "smooth" });
  };
  const swap = () => {
    setIdA(idB);
    setIdB(idA);
    setPicking((side) => (side === "A" ? "B" : side === "B" ? "A" : null));
  };

  const pair = idA && idB ? `${idA}|${idB}` : "";
  const current = pair && result?.key === `${pair}#${attempt}` ? result : null;
  const data = current?.data ?? null;
  const error = current?.error ?? null;
  const loading = Boolean(pair) && !current;
  const a = data?.jugador_a;
  const b = data?.jugador_b;
  const opcionA = opciones.find((opcion) => opcion.id === idA) || null;
  const opcionB = opciones.find((opcion) => opcion.id === idB) || null;
  const nombreA = a?.nombre || opcionA?.nombre || "el primero";
  const nombreB = b?.nombre || opcionB?.nombre || "el segundo";
  const ganaB = data?.ganador === "B";
  const ganaA = data?.ganador === "A";
  const head = data ? headline(data) : null;
  const why = data ? reasons(data) : [];
  const winnerColor = ganaB ? COLOR_B : COLOR_A;
  const aviso = (() => {
    if (picking === "A") return idB ? `Elige con quién comparar a ${nombreB}` : "Elige el primer jugador";
    if (picking === "B") return idA ? `Elige con quién comparar a ${nombreA}` : "Elige el segundo jugador";
    if (idA && idB && error) return null;
    if (idA && idB && !data) return `Comparando ${nombreA} con ${nombreB}…`;
    if (idA && idB) return null;
    return "Elige los dos jugadores";
  })();

  const body = (
    <div className="fixed inset-0 z-[200] flex items-end justify-center sm:items-center sm:p-4" role="presentation">
      <button type="button" aria-label="Cerrar comparador" className="absolute inset-0 bg-black/75 backdrop-blur-sm" onClick={onClose} />
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="comparador-titulo"
        className="cmp-sheet relative flex max-h-[94dvh] w-full flex-col overflow-hidden rounded-t-[2rem] bg-black shadow-[0_40px_120px_rgba(0,0,0,0.8),inset_0_0_0_1px_rgba(255,255,255,0.06)] sm:max-w-2xl sm:rounded-[2rem]"
      >
        <span className="mx-auto mt-2.5 h-1 w-10 shrink-0 rounded-full bg-white/20 sm:hidden" aria-hidden="true" />
        <header className="flex items-center justify-between gap-3 px-5 pb-2 pt-4">
          <h2 id="comparador-titulo" className="text-[1.25rem] font-semibold tracking-tight text-white">
            Comparar
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Cerrar"
            className="grid h-9 w-9 place-items-center rounded-full bg-raised text-white/70 outline-none transition-colors hover:text-white"
          >
            <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
              <path d="M4 4l8 8M12 4l-8 8" strokeLinecap="round" />
            </svg>
          </button>
        </header>

        <div ref={scroller} className="flex-1 overflow-y-auto px-3 pb-6 pt-3 sm:px-4">
          {!opciones.length ? (
            <p className="py-10 text-center text-[14px] text-white/55">Todavía no hay jugadores en la foto. Actualiza y vuelve a comparar.</p>
          ) : (
            <div className="flex flex-col gap-4">
              <div className="flex items-stretch gap-2">
                {idA ? (
                  <Slot color={COLOR_A} opcion={opcionA} lado={a} photos={photos} winner={ganaA} active={picking === "A"} onChange={() => setPicking("A")} />
                ) : (
                  <EmptySlot color={COLOR_A} etiqueta="el primero" active={picking === "A"} onPick={() => setPicking("A")} />
                )}
                <button
                  type="button"
                  onClick={swap}
                  disabled={!idA && !idB}
                  aria-label="Intercambiar jugadores"
                  className="grid h-9 w-9 shrink-0 place-items-center self-center rounded-full bg-raised text-white/60 transition-colors hover:bg-white/[0.14] hover:text-white disabled:opacity-30"
                >
                  <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
                    <path d="M5 3 2 6l3 3M2 6h9M11 13l3-3-3-3M14 10H5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </button>
                {idB ? (
                  <Slot color={COLOR_B} opcion={opcionB} lado={b} photos={photos} winner={ganaB} active={picking === "B"} onChange={() => setPicking("B")} />
                ) : (
                  <EmptySlot color={COLOR_B} etiqueta="el segundo" active={picking === "B"} onPick={() => setPicking("B")} />
                )}
              </div>

              {aviso ? (
                <p aria-live="polite" className="flex items-center justify-center gap-2 text-center text-[13px] font-medium text-white/60">
                  {picking ? <span className="h-1.5 w-1.5 rounded-full" style={{ background: picking === "B" ? COLOR_B : COLOR_A }} aria-hidden="true" /> : null}
                  {aviso}
                </p>
              ) : null}

              {picking ? (
                <Picker
                  key={picking}
                  color={picking === "A" ? COLOR_A : COLOR_B}
                  etiqueta={picking === "A" ? "el primero" : "el segundo"}
                  opciones={opciones}
                  excluir={picking === "A" ? idB : idA}
                  photos={photos}
                  onPick={pick}
                  onCancel={() => setPicking(null)}
                />
              ) : null}

              {idA && idB && error ? (
                <div className="flex flex-col items-start gap-3 rounded-2xl bg-coral/10 px-4 py-3">
                  <p className="text-[13.5px] text-coral">{error}</p>
                  <button
                    type="button"
                    onClick={() => setAttempt((value) => value + 1)}
                    className="rounded-full bg-white/[0.08] px-3 py-1.5 text-[13px] font-semibold text-white hover:bg-white/[0.14]"
                  >
                    Reintentar
                  </button>
                </div>
              ) : idA && idB && !data ? (
                <div className="flex flex-col gap-3" aria-busy={loading} aria-label={`Comparando ${nombreA} con ${nombreB}`}>
                  {loading ? (
                    <>
                      <div className="eq-skel h-28 rounded-3xl" />
                      <div className="eq-skel h-40 rounded-3xl" />
                    </>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setAttempt((value) => value + 1)}
                      className="rounded-2xl bg-white/[0.06] px-4 py-3 text-left text-[13.5px] text-white/80 hover:bg-white/[0.1]"
                    >
                      No ha llegado la comparación. Toca para reintentar.
                    </button>
                  )}
                </div>
              ) : data && head ? (
                <>
                  <section
                    className="rounded-3xl px-5 py-5"
                    style={{ background: `radial-gradient(ellipse 120% 90% at 50% 0%, ${winnerColor}38, transparent 70%), #141414` }}
                  >
                    <p className="text-[12.5px] font-medium" style={{ color: winnerColor }}>
                      Veredicto
                    </p>
                    <p className="mt-1.5 text-[1.6rem] font-semibold leading-tight tracking-tight text-white">
                      Mejor {head.title}
                    </p>
                    <p className="mt-0.5 text-[13px] font-medium text-white/55">{head.subtitle}</p>
                    {why.length ? (
                      <ul className="mt-4 flex flex-col gap-2">
                        {why.map((line) => (
                          <li key={line} className="flex gap-2.5 text-[13.5px] leading-snug text-white/80">
                            <span className="mt-[0.45rem] h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: winnerColor }} aria-hidden="true" />
                            {line}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </section>

                  <section className="rounded-3xl bg-raised-deep px-4 py-1">
                    <div className="divide-y divide-white/[0.05]">
                      <Duel label="Puntos próxima jornada" a={dec(a?.xp_j1)} b={dec(b?.xp_j1)} va={num(a?.xp_j1)} vb={num(b?.xp_j1)} />
                      <Duel label="Puntos por jornada · próximas 4" a={dec(a?.xp_4j)} b={dec(b?.xp_4j)} va={num(a?.xp_4j)} vb={num(b?.xp_4j)} />
                      <Duel label="Media de la temporada" a={dec(a?.media)} b={dec(b?.media)} va={num(a?.media)} vb={num(b?.media)} />
                      <Duel label="Titular" a={share(a?.prob_titular)} b={share(b?.prob_titular)} va={num(a?.prob_titular)} vb={num(b?.prob_titular)} />
                      <Duel
                        label="Precio"
                        a={money(a?.precio?.importe)}
                        b={money(b?.precio?.importe)}
                        va={num(a?.precio?.importe)}
                        vb={num(b?.precio?.importe)}
                        higherWins={false}
                        hintA={<PriceHint precio={a?.precio} />}
                        hintB={<PriceHint precio={b?.precio} />}
                      />
                      <Duel
                        label="Previsión de valor · 7 días"
                        a={`${dec(a?.prevision_7d_pct, true)}%`}
                        b={`${dec(b?.prevision_7d_pct, true)}%`}
                        va={num(a?.prevision_7d_pct)}
                        vb={num(b?.prevision_7d_pct)}
                        hintA={`${num(a?.subida_7d_euros) !== null && (a?.subida_7d_euros ?? 0) > 0 ? "+" : ""}${money(a?.subida_7d_euros)}`}
                        hintB={`${num(b?.subida_7d_euros) !== null && (b?.subida_7d_euros ?? 0) > 0 ? "+" : ""}${money(b?.subida_7d_euros)}`}
                      />
                    </div>
                  </section>

                  <section className="grid grid-cols-2 gap-3">
                    <div className="rounded-3xl bg-raised-deep p-4">
                      <p className="mb-2 text-[11px] font-medium text-white/40">Últimas jornadas</p>
                      <LastWeeks values={a?.ultimas || []} color={COLOR_A} align="left" />
                      <p className="mb-2 mt-4 text-[11px] font-medium text-white/40">Próximos rivales</p>
                      <Fixtures items={a?.proximos} align="left" />
                    </div>
                    <div className="rounded-3xl bg-raised-deep p-4 text-right">
                      <p className="mb-2 text-[11px] font-medium text-white/40">Últimas jornadas</p>
                      <LastWeeks values={b?.ultimas || []} color={COLOR_B} align="right" />
                      <p className="mb-2 mt-4 text-[11px] font-medium text-white/40">Próximos rivales</p>
                      <Fixtures items={b?.proximos} align="right" />
                    </div>
                  </section>

                  {data.impacto_rival?.aviso || data.nota_ejecucion ? (
                    <section className="flex flex-col gap-2">
                      {data.impacto_rival?.aviso ? (
                        <p className="rounded-2xl px-4 py-3 text-[13px] leading-snug" style={{ color: TONE.amber, background: `${TONE.amber}14` }}>
                          {data.impacto_rival.aviso}
                          {typeof data.impacto_rival.posicion_liga === "number" ? `, que va ${data.impacto_rival.posicion_liga}º.` : "."}
                        </p>
                      ) : null}
                      {data.nota_ejecucion ? <p className="px-1 text-[12.5px] leading-relaxed text-white/45">{data.nota_ejecucion}</p> : null}
                    </section>
                  ) : null}
                </>
              ) : null}
            </div>
          )}
        </div>
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
        className={`inline-flex h-10 shrink-0 items-center gap-2 rounded-full bg-raised px-4 text-[13.5px] font-semibold text-white transition-colors hover:bg-[#262628] ${className}`}
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
        className={`shrink-0 rounded-full px-2.5 py-1 text-[12px] font-semibold text-accent transition-colors hover:bg-accent/10 ${className}`}
      >
        Comparar
      </button>
      {open ? <CompararConSugerido objetivoId={objetivoId} posicion={posicion} onClose={() => setOpen(false)} /> : null}
    </>
  );
}
