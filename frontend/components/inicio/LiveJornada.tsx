"use client";

import { useEffect, type CSSProperties } from "react";
import { RollingNumber, rememberValue } from "@/components/ui/RollingNumber";
import { eurShort, points } from "@/lib/core/format";
import type { JornadaEnJuego, LiveEquipo, LiveJugador, PlanPayload } from "@/lib/types";

const hora = new Intl.DateTimeFormat("es-ES", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Madrid" });

function signed(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "s/d";
  const text = Math.abs(value).toLocaleString("es-ES", { maximumFractionDigits: 0 });
  return value > 0 ? `+${text}` : value < 0 ? `−${text}` : "0";
}

function saque(row: LiveJugador): string {
  if (!row.saque) return "";
  const date = new Date(row.saque);
  return Number.isNaN(date.getTime()) ? "" : hora.format(date);
}

function PlayerChip({ row, tone }: { row: LiveJugador; tone: "bad" | "good" | "wait" }) {
  const color = tone === "bad" ? "text-rose-300" : tone === "good" ? "text-emerald-300" : "text-white/70";
  const memoKey = `live:jugador:${row.player_id ?? row.nombre}`;
  const pending = row.estado !== "jugado";
  // Antes de jugar cuenta como 0: al entrar en juego, sus primeros puntos ruedan desde cero.
  useEffect(() => {
    if (pending) rememberValue(memoKey, 0);
  }, [pending, memoKey]);
  const value =
    row.estado === "jugado" ? (
      row.no_jugo ? (
        "no jugó"
      ) : (
        <RollingNumber value={row.puntos ?? 0} format={(v) => `${points(v)} pts`} memoKey={memoKey} />
      )
    ) : (
      `${saque(row)} · xP ${points(row.xp)}`
    );
  return (
    <li className="flex items-baseline justify-between gap-3 text-sm">
      <span className="truncate text-white/85">
        {row.nombre} <span className="text-white/35">{row.posicion}</span>
      </span>
      <span className={`shrink-0 tabular-nums ${color}`}>{value}</span>
    </li>
  );
}

function Group({ title, rows, tone }: { title: string; rows: LiveJugador[]; tone: "bad" | "good" | "wait" }) {
  if (!rows.length) return null;
  return (
    <div className="min-w-0">
      <p className="ini-kicker">{title}</p>
      <ul className="mt-1.5 space-y-1">
        {rows.map((row) => (
          <PlayerChip key={row.player_id ?? row.nombre} row={row} tone={tone} />
        ))}
      </ul>
    </div>
  );
}

function Fila({ row }: { row: LiveEquipo }) {
  return (
    <li
      className="grid grid-cols-[1.5rem_1fr_auto_auto] items-baseline gap-x-3 py-1 text-sm"
      data-self={row.is_self ? "true" : undefined}
    >
      <span className="tabular-nums text-white/40">{row.puesto_jornada}</span>
      <span className={`truncate ${row.is_self ? "font-semibold text-white" : "text-white/75"}`}>
        {row.manager}
        <span className="ml-2 text-xs text-white/35">{row.resumen_jugados}</span>
      </span>
      <span className="tabular-nums text-white">
        <RollingNumber value={row.puntos_proyectados_final_jornada} format={points} memoKey={`live:equipo:${row.team_id ?? row.manager}`} />
        <span className="ml-1 text-xs text-white/35">({points(row.puntos_actuales)} ya)</span>
      </span>
      <span className="w-20 text-right tabular-nums text-emerald-300/90">{eurShort(row.premio_jornada_eur)}</span>
    </li>
  );
}

export function LiveJornada({ plan }: { plan: PlanPayload | null }) {
  const live = (plan?.plan_fichajes as { jornada_en_juego?: JornadaEnJuego } | null | undefined)?.jornada_en_juego;
  if (!live || live.activa !== true || !live.propio) return null;
  const propio = live.propio;
  const clasificacion = live.clasificacion_jornada ?? [];
  const recorte = propio.recorte_vs_lider ?? 0;
  return (
    <section
      className="ini-card ini-in"
      style={{ "--i": 1 } as CSSProperties}
      aria-label={`Jornada ${live.jornada} en juego`}
      data-ui="live-jornada"
    >
      <div className="p-5 sm:p-6">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <p className="ini-kicker">Jornada {live.jornada} en juego</p>
          <p className="text-sm text-white/50">
            Puesto <b className="text-white">{propio.puesto_jornada}</b> de {clasificacion.length} · {propio.resumen_jugados}
          </p>
        </div>

        <div className="mt-3 grid grid-cols-3 gap-3">
          <div>
            <p className="ini-kicker">Ya sumas</p>
            <p className="text-2xl font-semibold tabular-nums text-white">
              <RollingNumber value={propio.puntos_actuales} format={points} memoKey="live:actual" />
            </p>
          </div>
          <div>
            <p className="ini-kicker">Proyección</p>
            <p className="text-2xl font-semibold tabular-nums text-white">
              <RollingNumber value={propio.puntos_proyectados_final_jornada} format={points} memoKey="live:proyeccion" />
            </p>
          </div>
          <div>
            <p className="ini-kicker">Cobras</p>
            <p className="text-2xl font-semibold tabular-nums text-emerald-300">
              <RollingNumber value={propio.premio_jornada_eur} format={eurShort} memoKey="live:premio" />
            </p>
          </div>
        </div>

        <p className="mt-3 text-sm text-white/60">
          Frente al líder ({live.lider?.manager ?? "—"}) {recorte >= 0 ? "recortas" : "pierdes"}{" "}
          <b className="text-white">{points(Math.abs(recorte))} pts</b> en la jornada
          {typeof propio.recorte_tabla_vs_lider === "number" && propio.recorte_tabla_vs_lider < 0
            ? ` · en la tabla seguirías a ${points(Math.abs(propio.recorte_tabla_vs_lider))} pts`
            : ""}
          . Este dinero entra el lunes y ya cuenta en el mercado.
        </p>

        <div className="mt-4 grid gap-5 sm:grid-cols-3">
          <Group title="Rosco" rows={propio.roscos ?? []} tone="bad" />
          <Group title="Explotó (≥10)" rows={propio.explosiones ?? []} tone="good" />
          <Group title="Te falta por jugar" rows={propio.pendientes ?? []} tone="wait" />
        </div>

        <details className="mt-5">
          <summary className="cursor-pointer text-sm text-white/60">Clasificación virtual de la jornada</summary>
          <ol className="mt-2 divide-y divide-white/5">
            {clasificacion.map((row) => (
              <Fila key={row.team_id ?? row.manager} row={row} />
            ))}
          </ol>
          <p className="mt-2 text-xs text-white/35">{live.nota}</p>
        </details>
      </div>
    </section>
  );
}
