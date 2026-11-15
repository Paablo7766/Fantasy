"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { useDashboard } from "@/components/DashboardProvider";
import { Crest } from "@/components/ui/Crest";
import { ErrorCard } from "@/components/ui/Feedback";
import { Empty, Face, Fact, HeroStat, Skeleton, TONE, lastName, money, ringColor } from "@/components/ui/kit";
import { endpoint } from "@/lib/core/api";
import { points, titularFull } from "@/lib/core/format";
import { cachedJson, peekJson } from "@/lib/core/jsonCache";
import type { PlanificadorJugador, PlanificadorPayload, PlanificadorPosicion } from "@/lib/types";

/** 0–3 = una jornada concreta; «total» = las cuatro sumadas. */
type Horizonte = 0 | 1 | 2 | 3 | "total";
type Filtro = "todos" | "mios" | "rivales" | "mercado" | "clausulables";
type PosFiltro = "todas" | PlanificadorPosicion;

const POSICIONES: PlanificadorPosicion[] = ["POR", "DEF", "MC", "DEL"];
const FORMACIONES: Array<[number, number, number]> = [
  [3, 4, 3],
  [3, 5, 2],
  [4, 3, 3],
  [4, 4, 2],
  [4, 5, 1],
  [5, 3, 2],
  [5, 4, 1],
];
const FILTROS: Array<[Filtro, string]> = [
  ["todos", "Todos"],
  ["mios", "Míos"],
  ["rivales", "Rivales"],
  ["mercado", "Mercado"],
  ["clausulables", "Clausulables"],
];
const DIFICULTAD: Record<string, string> = {
  muy_facil: "Muy fácil",
  very_easy: "Muy fácil",
  facil: "Fácil",
  easy: "Fácil",
  media: "Media",
  medium: "Media",
  dificil: "Difícil",
  hard: "Difícil",
  muy_dificil: "Muy difícil",
  very_hard: "Muy difícil",
};
const PAGINA = 30;
const BRASA = "#FF7A3D";

function valor(jugador: PlanificadorJugador, h: Horizonte): number | null {
  return h === "total" ? jugador.xp_total : (jugador.xp[h] ?? null);
}

/** Abierta, en el mercado o tuya: lo que se puede tener sin depender de nadie más. */
function alcanzable(jugador: PlanificadorJugador): boolean {
  return jugador.dueno.tipo === "mio" || jugador.mercado !== null || jugador.clausula?.estado === "abierta";
}

type Once = { total: number; ids: Set<string>; formacion: string } | null;

/** Mejor once legal (1 POR y una de las formaciones del juego) con lo que haya en ``pool``. */
function mejorOnce(pool: PlanificadorJugador[], h: Horizonte): Once {
  const porPuesto: Record<PlanificadorPosicion, PlanificadorJugador[]> = { POR: [], DEF: [], MC: [], DEL: [] };
  for (const jugador of pool) {
    if (valor(jugador, h) !== null) porPuesto[jugador.posicion].push(jugador);
  }
  for (const puesto of POSICIONES) porPuesto[puesto].sort((a, b) => (valor(b, h) ?? 0) - (valor(a, h) ?? 0));
  let mejor: Once = null;
  for (const [def, mc, del] of FORMACIONES) {
    const cupo: Record<PlanificadorPosicion, number> = { POR: 1, DEF: def, MC: mc, DEL: del };
    if (POSICIONES.some((puesto) => porPuesto[puesto].length < cupo[puesto])) continue;
    const elegidos = POSICIONES.flatMap((puesto) => porPuesto[puesto].slice(0, cupo[puesto]));
    const total = elegidos.reduce((suma, jugador) => suma + (valor(jugador, h) ?? 0), 0);
    if (!mejor || total > mejor.total) mejor = { total, ids: new Set(elegidos.map((j) => j.player_id)), formacion: `${def}-${mc}-${del}` };
  }
  return mejor;
}

const madrid = new Intl.DateTimeFormat("es-ES", { timeZone: "Europe/Madrid", weekday: "short", day: "numeric", month: "short" });
const madridHora = new Intl.DateTimeFormat("es-ES", { timeZone: "Europe/Madrid", weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

function fecha(iso: string | null | undefined, conHora = false): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return (conHora ? madridHora : madrid).format(date).replace(/\./g, "");
}

function normaliza(texto: string): string {
  return texto.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

/** Las 4 jornadas como barras: la elegida en brasa, el resto en gris. */
function Barras({ xp, h, max }: { xp: Array<number | null>; h: Horizonte; max: number }) {
  return (
    <span className="flex h-6 items-end gap-[3px]" aria-hidden="true">
      {xp.map((valorJ, index) => {
        const alto = valorJ !== null && max > 0 ? Math.max(8, Math.round((Math.max(0, valorJ) / max) * 100)) : 8;
        const activa = h === "total" || h === index;
        return (
          <span
            key={index}
            className="w-[5px] rounded-full transition-[height,background-color] duration-300 ease-out"
            style={{ height: `${alto}%`, background: valorJ === null ? "rgba(255,255,255,0.08)" : activa ? BRASA : "rgba(255,255,255,0.22)" }}
          />
        );
      })}
    </span>
  );
}

function DuenoTexto({ jugador }: { jugador: PlanificadorJugador }) {
  const { dueno, clausula, mercado } = jugador;
  if (dueno.tipo === "mio") return <span className="text-white/80">Tuyo</span>;
  if (dueno.tipo === "mercado" || dueno.tipo === "libre") {
    return <span className="text-white/60">Mercado{mercado?.precio ? ` · ${money(mercado.precio)}` : ""}</span>;
  }
  const etiqueta = mercado ? " · en venta" : clausula?.estado === "abierta" ? " · cláusula abierta" : "";
  return (
    <span className="text-white/50">
      {dueno.nombre}
      {etiqueta ? <span className="text-white/75">{etiqueta}</span> : null}
    </span>
  );
}

function Ficha({ jugador, jornadas, sufijo }: { jugador: PlanificadorJugador; jornadas: Array<number | null>; sufijo: string }) {
  const { clausula, mercado, dueno } = jugador;
  return (
    <div className="row-in border-t border-white/[0.06] px-4 pb-4 pt-3">
      <ul className="grid grid-cols-2 gap-2 min-[520px]:grid-cols-4">
        {jugador.partidos.map((partido, index) => (
          <li key={index} className="min-w-0 rounded-2xl bg-black/30 px-3 py-2.5">
            <p className="flex items-baseline justify-between gap-2 text-[11px] text-white/40">
              <span>J{jornadas[index] ?? index + 1}</span>
              <span className="font-mono text-[14px] font-semibold tabular-nums text-white">{points(jugador.xp[index])}</span>
            </p>
            {partido?.rival ? (
              <>
                <p className="mt-1.5 flex min-w-0 items-center gap-1.5 text-[13px] font-medium text-white">
                  <Crest club={partido.rival} size={16} />
                  <span className="truncate">{partido.rival}</span>
                </p>
                <p className="mt-0.5 truncate text-[11.5px] text-white/45">
                  {partido.casa === true ? "Casa" : partido.casa === false ? "Fuera" : "—"}
                  {partido.dificultad ? ` · ${DIFICULTAD[partido.dificultad] ?? partido.dificultad}` : ""}
                </p>
                {fecha(partido.saque) ? <p className="truncate text-[11px] text-white/35">{fecha(partido.saque)}</p> : null}
              </>
            ) : (
              <p className="mt-1.5 text-[12.5px] text-white/40">Sin partido</p>
            )}
          </li>
        ))}
      </ul>

      <div className="mt-4 grid grid-cols-2 gap-x-3 gap-y-3 min-[520px]:grid-cols-4">
        <Fact label="Titular" value={titularFull(jugador.p_titular)} tone={ringColor(jugador.p_titular)} />
        <Fact label="Si es titular" value={jugador.si_juega !== null ? `${points(jugador.si_juega)} pts` : "—"} />
        <Fact label="Techo" value={jugador.techo ? `${points(jugador.techo)} pts` : "—"} hint="en su mejor día" />
        <Fact label="Media" value={jugador.media !== null ? points(jugador.media) : "—"} hint={jugador.valor ? `Valor ${money(jugador.valor)}` : undefined} />
      </div>

      <div className="mt-4 flex flex-col gap-2 border-t border-white/[0.06] pt-3 text-[13px] leading-snug text-white/60">
        {dueno.tipo === "mio" ? <p>Está en tu plantilla.</p> : null}
        {dueno.tipo === "rival" ? (
          <p>
            Lo tiene <span className="font-medium text-white">{dueno.nombre}</span>.
          </p>
        ) : null}
        {mercado ? (
          <p>
            En el mercado por <span className="font-mono font-medium tabular-nums text-white">{money(mercado.precio)}</span>
            {fecha(mercado.cierra_at, true) ? ` · cierra ${fecha(mercado.cierra_at, true)}` : ""}.
          </p>
        ) : null}
        {clausula ? (
          <p>
            Cláusula <span className="font-mono font-medium tabular-nums text-white">{money(clausula.eur)}</span>
            {clausula.multiplo ? <span className="tabular-nums"> ({clausula.multiplo.toLocaleString("es-ES")}× su valor)</span> : null}
            {" · "}
            {clausula.estado === "abierta"
              ? "abierta"
              : clausula.estado === "bloqueada"
                ? `se abre ${fecha(clausula.abre_at, true) ?? "más adelante"}`
                : clausula.estado === "blindado"
                  ? "blindado"
                  : "sin dato del candado"}
            .
          </p>
        ) : null}
        {mercado || clausula?.estado === "abierta" || clausula?.estado === "bloqueada" ? (
          <p className="flex flex-wrap gap-2 pt-1">
            {mercado ? (
              <Link href={`/mercado${sufijo}`} className="eq-chip !min-h-9 !text-[12.5px]">
                Ver en Mercado
              </Link>
            ) : null}
            {clausula && clausula.estado !== "blindado" ? (
              <Link href={`/clausulas${sufijo}`} className="eq-chip !min-h-9 !text-[12.5px]">
                Ver en Cláusulas
              </Link>
            ) : null}
          </p>
        ) : null}
      </div>
    </div>
  );
}

export function Planificador() {
  const search = useSearchParams();
  const { trends, state: dash } = useDashboard();
  const league = trends?.league_id || search.get("league");
  const url = endpoint("/api/planificador", league);
  const [payload, setPayload] = useState<PlanificadorPayload | null>(() => peekJson<PlanificadorPayload>(url) ?? null);
  const [loading, setLoading] = useState(() => !peekJson(url));
  const stamp = dash.trends ? ((dash.trends as { dashboard_at?: string }).dashboard_at ?? null) : null;

  const [h, setH] = useState<Horizonte>(0);
  const [filtro, setFiltro] = useState<Filtro>("todos");
  const [puesto, setPuesto] = useState<PosFiltro>("todas");
  const [manager, setManager] = useState<string | null>(null);
  const [soloIdeal, setSoloIdeal] = useState(false);
  const [texto, setTexto] = useState("");
  const busca = useDeferredValue(texto);
  const [abierto, setAbierto] = useState<string | null>(null);
  const [vistos, setVistos] = useState(PAGINA);

  useEffect(() => {
    let cancelled = false;
    async function run() {
      setLoading(true);
      try {
        const data = await cachedJson<PlanificadorPayload>(url);
        if (!cancelled) setPayload(data);
      } catch (reason: unknown) {
        if (cancelled) return;
        const message = reason instanceof Error ? reason.message : "Sin datos.";
        const hint = /404|Not Found/i.test(message) ? " El backend no tiene la ruta nueva: reinícialo." : "";
        setPayload({ ok: false, error: { message: `${message}${hint}` } });
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void run();
    return () => {
      cancelled = true;
    };
  }, [url, stamp]);

  const jugadores = useMemo(() => payload?.jugadores ?? [], [payload]);
  const jornadas = payload?.jornadas ?? [null, null, null, null];

  const onces = useMemo(
    () => ({
      tuyo: mejorOnce(jugadores.filter((j) => j.dueno.tipo === "mio"), h),
      alcanzable: mejorOnce(jugadores.filter(alcanzable), h),
      liga: mejorOnce(jugadores, h),
    }),
    [jugadores, h],
  );

  const maxXp = useMemo(() => jugadores.reduce((m, j) => Math.max(m, ...j.xp.map((x) => x ?? 0)), 0), [jugadores]);

  const lista = useMemo(() => {
    const q = normaliza(busca.trim());
    return jugadores
      .filter((j) => {
        if (puesto !== "todas" && j.posicion !== puesto) return false;
        if (filtro === "mios" && j.dueno.tipo !== "mio") return false;
        if (filtro === "rivales" && (j.dueno.tipo !== "rival" || (manager && j.dueno.team_id !== manager))) return false;
        if (filtro === "mercado" && !j.mercado) return false;
        if (filtro === "clausulables" && j.clausula?.estado !== "abierta") return false;
        if (soloIdeal && !onces.liga?.ids.has(j.player_id)) return false;
        if (q && !normaliza(`${j.nombre ?? ""} ${j.club ?? ""} ${j.dueno.nombre}`).includes(q)) return false;
        return valor(j, h) !== null;
      })
      .sort((a, b) => (valor(b, h) ?? 0) - (valor(a, h) ?? 0));
  }, [jugadores, busca, puesto, filtro, manager, soloIdeal, onces, h]);

  if (loading && !payload) return <Skeleton />;
  if (!payload || payload.ok === false) {
    return <ErrorCard title="Planificador" payload={payload || { error: { message: "Sin datos." } }} brief />;
  }
  if (!jugadores.length) {
    return <Empty title="Sin xP de las próximas jornadas" detail="Pulsa Actualizar en Inicio para calcular la proyección." />;
  }

  const etiquetaH = h === "total" ? `J${jornadas[0] ?? "?"}–J${jornadas[3] ?? "?"}` : `J${jornadas[h] ?? h + 1}`;
  const brecha = onces.tuyo && onces.alcanzable ? onces.alcanzable.total - onces.tuyo.total : null;
  const rivales = (payload.managers ?? []).filter((m) => !m.es_mio);
  const cambiar = (fn: () => void) => {
    fn();
    setAbierto(null);
    setVistos(PAGINA);
  };
  const mostrados = lista.slice(0, vistos);

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <section className="home-feature" aria-label="Resumen del planificador">
        <div className="relative">
          <p className="text-[13px] font-medium text-white/60">Tu mejor once · {etiquetaH}</p>
          <p className="mt-2 flex items-baseline gap-1.5 tabular-nums">
            <span className="text-[3rem] font-semibold leading-none tracking-[-0.045em] text-white">{onces.tuyo ? points(onces.tuyo.total) : "—"}</span>
            <span className="text-base font-medium text-white/55">xP</span>
            {onces.tuyo ? <span className="ml-2 text-[13px] font-medium text-white/50">{onces.tuyo.formacion}</span> : null}
          </p>
          {brecha !== null && brecha >= 0.05 ? (
            <p className="mt-2 text-[13.5px] tabular-nums text-white/60">
              <span className="font-semibold text-white">+{points(brecha)} pts</span> si sumas lo que está en el mercado o con cláusula abierta
            </p>
          ) : null}
        </div>
        <div className="relative mt-5 grid grid-cols-3 gap-2.5">
          <HeroStat value={onces.alcanzable ? points(onces.alcanzable.total) : "—"} label="Con fichajes" />
          <HeroStat value={onces.liga ? points(onces.liga.total) : "—"} label="Ideal liga" />
          <HeroStat value={String(jugadores.length)} label="Jugadores" />
        </div>
      </section>

      <div className="desk-switch !grid-cols-5" role="tablist" aria-label="Jornada">
        {([0, 1, 2, 3, "total"] as Horizonte[]).map((opcion) => (
          <button
            key={String(opcion)}
            type="button"
            role="tab"
            aria-selected={h === opcion}
            className={h === opcion ? "desk-switch__btn desk-switch__btn--on" : "desk-switch__btn"}
            onClick={() => cambiar(() => setH(opcion))}
          >
            {opcion === "total" ? "4 J" : `J${jornadas[opcion] ?? opcion + 1}`}
          </button>
        ))}
      </div>

      <div className="flex flex-col gap-2">
        <label className="relative block">
          <span className="sr-only">Buscar jugador, club o rival</span>
          <svg viewBox="0 0 16 16" className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-white/35" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
            <circle cx="7" cy="7" r="4.6" />
            <path d="m10.5 10.5 3 3" strokeLinecap="round" />
          </svg>
          <input
            type="search"
            value={texto}
            onChange={(event) => cambiar(() => setTexto(event.target.value))}
            placeholder="Buscar jugador, club o rival"
            className="h-11 w-full rounded-full border-0 bg-[#1c1c1e] pl-11 pr-4 text-[16px] text-white placeholder:text-white/35 focus:outline-none focus:ring-1 focus:ring-white/20"
          />
        </label>
        <div className="eq-scroll -mx-1 px-1" role="group" aria-label="Quién lo tiene">
          {FILTROS.map(([id, label]) => (
            <button
              key={id}
              type="button"
              aria-pressed={filtro === id}
              className={filtro === id ? "eq-chip eq-chip--on" : "eq-chip"}
              onClick={() => cambiar(() => {
                setFiltro(id);
                setManager(null);
              })}
            >
              {label}
            </button>
          ))}
        </div>
        {filtro === "rivales" && rivales.length ? (
          <div className="eq-scroll -mx-1 px-1" role="group" aria-label="Rival">
            <button type="button" aria-pressed={manager === null} className={manager === null ? "eq-chip eq-chip--on" : "eq-chip"} onClick={() => cambiar(() => setManager(null))}>
              Todos
            </button>
            {rivales.map((m) => (
              <button
                key={m.team_id ?? m.nombre}
                type="button"
                aria-pressed={manager === m.team_id}
                className={manager === m.team_id ? "eq-chip eq-chip--on" : "eq-chip"}
                onClick={() => cambiar(() => setManager(m.team_id))}
              >
                {m.nombre}
              </button>
            ))}
          </div>
        ) : null}
        <div className="eq-scroll -mx-1 px-1" role="group" aria-label="Posición">
          {(["todas", ...POSICIONES] as PosFiltro[]).map((id) => (
            <button key={id} type="button" aria-pressed={puesto === id} className={puesto === id ? "eq-chip eq-chip--on" : "eq-chip"} onClick={() => cambiar(() => setPuesto(id))}>
              {id === "todas" ? "Todas" : id}
            </button>
          ))}
          <span className="mx-1 w-px shrink-0 self-stretch bg-white/[0.08]" aria-hidden="true" />
          <button type="button" aria-pressed={soloIdeal} className={soloIdeal ? "eq-chip eq-chip--on" : "eq-chip"} onClick={() => cambiar(() => setSoloIdeal((v) => !v))}>
            Once ideal
          </button>
        </div>
      </div>

      <div className="flex items-baseline justify-between gap-3 px-1">
        <h2 className="text-[1.1rem] font-semibold tracking-tight text-white">Más puntos esperados</h2>
        <p className="shrink-0 text-[13px] tabular-nums text-white/50">
          {lista.length} · {etiquetaH}
        </p>
      </div>

      {lista.length ? (
        <ul className="home-glass" aria-label="Jugadores por puntos esperados">
          {mostrados.map((jugador, index) => {
            const id = jugador.player_id;
            const open = abierto === id;
            const nombre = jugador.nombre || "Jugador";
            const partido = h === "total" ? jugador.partidos[0] : jugador.partidos[h];
            const enIdeal = onces.liga?.ids.has(id);
            return (
              <li key={id} className="row-in" style={{ animationDelay: `${Math.min(index, 12) * 20}ms` }}>
                <button
                  type="button"
                  aria-expanded={open}
                  aria-label={`${nombre}, ${points(valor(jugador, h))} puntos esperados`}
                  className="flex w-full items-center gap-3 px-3 py-3 text-left"
                  onClick={() => setAbierto(open ? null : id)}
                >
                  <span className="w-5 shrink-0 text-right font-mono text-[12px] tabular-nums text-white/35">{index + 1}</span>
                  <Face name={nombre} src={jugador.image_url} size={42} ring={ringColor(jugador.p_titular)} />
                  <span className="min-w-0 flex-1">
                    <span className="flex min-w-0 items-center gap-1.5">
                      <span className="truncate text-[15px] font-medium leading-tight text-white">{lastName(nombre)}</span>
                      {jugador.estado ? (
                        <span className="shrink-0 text-[11.5px] font-medium" style={{ color: jugador.estado === "baja" ? TONE.red : TONE.amber }}>
                          {jugador.estado === "baja" ? "Baja" : "Duda"}
                        </span>
                      ) : null}
                      {enIdeal ? <span className="shrink-0 text-[11px] font-semibold text-white/40" title="En el once ideal de la liga">XI</span> : null}
                    </span>
                    <span className="mt-0.5 flex min-w-0 items-center gap-1.5 text-[12px] text-white/45">
                      <Crest club={jugador.club} size={14} />
                      <span className="shrink-0">{jugador.posicion}</span>
                      {partido?.rival ? (
                        <>
                          <span className="shrink-0 text-white/25">·</span>
                          <span className="shrink-0">{partido.casa === false ? "en" : "vs"}</span>
                          <Crest club={partido.rival} size={14} />
                          <span className="truncate">{partido.rival}</span>
                        </>
                      ) : null}
                    </span>
                    <span className="mt-0.5 block truncate text-[12px]">
                      <DuenoTexto jugador={jugador} />
                    </span>
                  </span>
                  <span className="flex shrink-0 flex-col items-end gap-1">
                    <span className="font-mono text-[1.15rem] font-semibold leading-none tabular-nums text-white">{points(valor(jugador, h))}</span>
                    <Barras xp={jugador.xp} h={h} max={maxXp} />
                  </span>
                </button>
                {open ? <Ficha jugador={jugador} jornadas={jornadas} sufijo={search.get("league") ? `?league=${encodeURIComponent(search.get("league")!)}` : ""} /> : null}
              </li>
            );
          })}
        </ul>
      ) : (
        <Empty title="Nadie con esos filtros" detail="Quita algún filtro o cambia la búsqueda." />
      )}

      {lista.length > vistos ? (
        <button type="button" className="eq-chip self-center" onClick={() => setVistos((n) => n + PAGINA)}>
          Ver {Math.min(PAGINA, lista.length - vistos)} más
        </button>
      ) : null}

      <p className="px-1 text-[12px] leading-relaxed text-white/40">
        xP propio de la app para tus plantillas, las de tus rivales y el mercado. «Con fichajes» suma lo que está en venta o con cláusula abierta sin mirar caja ni pujas: es un techo, no un plan.
        El anillo de la foto es la opción de ser titular.
      </p>
    </div>
  );
}
