"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { eur, eurShort, points } from "@/lib/format";
import { signedPoints } from "@/lib/hoy";
import { buildStrategyViews, type MoveTone, type StrategyMove, type StrategyView } from "@/lib/signingBoard";
import type { NeedsPayload, OptimizePayload, PlanFichajeAccion, PlanPayload, SquadsPayload, TrendsPayload } from "@/lib/types";

const PILL: Record<string, string> = {
  PUJA: "border border-[#0297DE] bg-[rgba(2,151,222,0.15)] text-[#0297DE]",
  BUSCA: "border border-dashed border-[#67C6F5] bg-[rgba(2,151,222,0.08)] text-[#67C6F5]",
  VENDE: "border border-[#FC734D] bg-[rgba(252,115,77,0.15)] text-[#FC734D]",
  CLAUSULAZO: "border border-[#FC734D] bg-[rgba(252,115,77,0.15)] text-[#FC734D]",
};

function pillOf(verb: string): { label: string; className: string } {
  const value = verb.toLowerCase();
  if (value.includes("busca") || value.includes("buscar")) return { label: "BUSCA", className: PILL.BUSCA };
  if (value.includes("vend") || value.includes("venta")) return { label: "VENDE", className: PILL.VENDE };
  if (value.includes("cláus") || value.includes("claus") || value.includes("rival") || value.includes("proteger") || value.includes("subir")) {
    return { label: "CLAUSULAZO", className: PILL.CLAUSULAZO };
  }
  return { label: "PUJA", className: PILL.PUJA };
}

function bucketOf(verb: string): "hoy" | "luego" {
  return pillOf(verb).label === "BUSCA" ? "luego" : "hoy";
}

function moveFromAction(action: PlanFichajeAccion, index: number): StrategyMove {
  const tipo = (action.tipo || "PUJA").toUpperCase();
  const verb =
    tipo === "VENDE" ? "Poner en venta" : tipo === "BUSCA" ? "Buscar en el mercado" : tipo === "CLAUSULAZO" ? "Fichar de un rival" : "Pujar en el mercado";
  const amount = typeof action.euros === "number" ? action.euros : null;
  const jornada = typeof action.jornada === "number" ? action.jornada : null;
  return {
    id: `plan-${tipo}-${action.player_id || action.nombre || index}`,
    verb,
    title: action.nombre || "Jugador",
    position: action.posicion || null,
    imageUrl: null,
    cashImpact: amount,
    cashLabel: amount === null ? null : eurShort(amount),
    cashTone: tipo === "VENDE" ? "up" : "down",
    pointsImpact: jornada,
    pointsLabel: jornada === null ? null : `${points(jornada)} pts`,
    pointsTone: "flat",
    detail: action.detalle || null,
    href: tipo === "VENDE" ? "/equipo?tab=cartera" : tipo === "CLAUSULAZO" ? "/equipo?tab=clausulas" : "/mercado",
    guide: tipo === "VENDE" ? "Abrir cartera" : tipo === "CLAUSULAZO" ? "Abrir cláusulas" : "Abrir mercado",
  };
}

const TONE: Record<MoveTone, string> = {
  up: "desk-fig--up",
  down: "desk-fig--down",
  flat: "desk-fig--flat",
  none: "",
};

export function SigningBoard({
  plan,
  optimize,
  squads,
  trends,
  needs,
  loading,
  refreshing,
  photoLine,
}: {
  plan: PlanPayload | null;
  optimize: OptimizePayload | null;
  squads: SquadsPayload | null;
  trends: TrendsPayload | null;
  needs: NeedsPayload | null;
  loading: boolean;
  refreshing: boolean;
  photoLine: string;
}) {
  const views = useMemo(
    () => buildStrategyViews(plan, optimize, squads, trends, needs),
    [plan, optimize, squads, trends, needs],
  );
  const [desk, setDesk] = useState<StrategyView["id"]>("estrategia");
  const view = views.find((item) => item.id === desk) ?? views[0];
  const fichajes = plan?.plan_fichajes;
  const planMoves = (fichajes?.acciones || []).map(moveFromAction);
  const listed = desk === "estrategia" && planMoves.length ? planMoves : view.groups.flatMap((group) => group.moves);
  const hoy = listed.filter((move) => {
    if (desk === "estrategia" && planMoves.length) {
      const action = (fichajes?.acciones || []).find((row, index) => moveFromAction(row, index).id === move.id);
      return action ? action.momento !== "luego" : bucketOf(move.verb) === "hoy";
    }
    return bucketOf(move.verb) === "hoy";
  });
  const luego = listed.filter((move) => !hoy.includes(move));
  const verdict = fichajes?.veredicto || (view.pointsTone === "up" ? "Hazlo ya" : view.headline || "Opcional");
  const gain =
    typeof fichajes?.mejora_puntos_jornada === "number"
      ? `${signedPoints(fichajes.mejora_puntos_jornada) || "0,0"} PTS/J`
      : view.pointsMove
        ? view.pointsMove.replace(" pts", " PTS/J")
        : null;
  const cashNow = typeof plan?.cash_eur === "number" ? plan.cash_eur : null;
  const cashEnd = typeof fichajes?.saldo_al_final === "number" ? fichajes.saldo_al_final : null;

  return (
    <div className="desk">
      <div className="desk-switch" role="tablist" aria-label="Mesas de recomendación">
        {views.map((item) => {
          const count = item.groups.reduce((total, group) => total + group.moves.length, 0);
          const active = item.id === view.id;
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={active}
              className={active ? "desk-switch__btn desk-switch__btn--on" : "desk-switch__btn"}
              onClick={() => setDesk(item.id)}
            >
              {item.label}
              <span>{count}</span>
            </button>
          );
        })}
      </div>

      <header className="desk-hero">
        <div className="desk-hero__top">
          <p className="desk-kicker">Tu plan de fichajes</p>
          {refreshing ? <p className="desk-photo">Actualizando</p> : null}
        </div>
        {loading && !plan ? (
          <div className="desk-skel" aria-hidden="true" />
        ) : (
          <>
            <div className="mt-3 flex items-start justify-between gap-3">
              <p className="desk-headline">{verdict}</p>
              {gain ? (
                <span className="shrink-0 rounded-full border border-[#0297DE] bg-[rgba(2,151,222,0.15)] px-2.5 py-1 font-mono text-xs font-bold tabular-nums text-[#0297DE]">
                  {gain}
                </span>
              ) : null}
            </div>
            {view.sentence ? <p className="desk-sentence">{view.sentence}</p> : null}
            {cashNow !== null || cashEnd !== null ? (
              <p className="mt-3 font-mono text-sm font-semibold tabular-nums text-[#F0F6FC]">
                <span className={cashNow !== null && cashNow < 0 ? "text-[#FC734D]" : undefined}>{eur(cashNow)}</span>
                <span className="mx-1.5 text-[#4B6075]">→</span>
                <span className={cashEnd !== null && cashEnd < 0 ? "text-[#FC734D]" : "text-[#0297DE]"}>{eur(cashEnd)}</span>
              </p>
            ) : null}
            <p className="desk-photo">{photoLine}</p>
          </>
        )}
      </header>

      {loading && !plan ? null : hoy.length || luego.length ? (
        <>
          <MoveGroup title="Hoy" hint="Urgente antes del cierre de mercado" moves={hoy} urgent />
          <MoveGroup title="Luego" hint="Cuando el mercado de hoy haya cerrado" moves={luego} />
        </>
      ) : (
        <p className="desk-empty">
          {view.id === "estrategia"
            ? "Con esta foto no hay un fichaje que suba los puntos del once. Actualiza o espera al mercado del día."
            : "Esta foto no deja un movimiento que mejore la estrategia."}
        </p>
      )}

      {view.id === "estrategia" && view.savedPoints && view.recommendedPoints ? (
        <footer className="desk-xi">
          <span>Once</span>
          <strong>
            {view.savedPoints}
            <span aria-hidden="true"> → </span>
            {view.recommendedPoints}
          </strong>
        </footer>
      ) : null}
    </div>
  );
}

function MoveGroup({
  title,
  hint,
  moves,
  urgent = false,
}: {
  title: string;
  hint: string;
  moves: StrategyMove[];
  urgent?: boolean;
}) {
  if (!moves.length) return null;
  return (
    <section className="desk-group" aria-label={title}>
      <h2 className={urgent ? "!text-[#FC734D]" : ""}>{title}</h2>
      <p className="-mt-2 mb-2 text-[11px] text-[#8B9EB0]">{hint}</p>
      <ul className="desk-list">
        {moves.map((move) => (
          <MoveCard key={move.id} move={move} />
        ))}
      </ul>
    </section>
  );
}

function MoveCard({ move }: { move: StrategyMove }) {
  const pill = pillOf(move.verb);
  return (
    <li className="desk-card">
      <div className="desk-card__main">
        {move.imageUrl ? (
          <PlayerAvatar player={{ name: move.title, image_url: move.imageUrl }} size="sm" />
        ) : (
          <span className="desk-card__mark" aria-hidden="true">
            {move.position ? move.position.slice(0, 3) : "·"}
          </span>
        )}
        <div className="min-w-0 flex-1">
          <p className="desk-card__verb">
            <span className={`rounded-md px-1.5 py-0.5 text-[10px] font-bold tracking-wide ${pill.className}`}>{pill.label}</span>
            {move.position ? <span>{move.position}</span> : null}
          </p>
          <h3>{move.title}</h3>
          {move.detail ? <p className="desk-card__detail">{move.detail}</p> : null}
        </div>
        {move.cashLabel || move.pointsLabel ? (
          <div className="desk-card__figs">
            {move.pointsLabel ? <span className={TONE[move.pointsTone]}>{move.pointsLabel}</span> : null}
            {move.cashLabel ? <span className={TONE[move.cashTone]}>{move.cashLabel}</span> : null}
          </div>
        ) : null}
      </div>
      <Link href={move.href} className="desk-card__go">
        {move.guide}
      </Link>
    </li>
  );
}
