"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { eurShort, points } from "@/lib/format";
import { signedPoints } from "@/lib/hoy";
import { photoFor, type PhotoIndex } from "@/lib/photoIndex";
import { buildStrategyViews, type StrategyMove, type StrategyView } from "@/lib/signingBoard";
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

function moveFromAction(action: PlanFichajeAccion, index: number, photos: PhotoIndex): StrategyMove {
  const tipo = (action.tipo || "PUJA").toUpperCase();
  const verb =
    tipo === "VENDE" ? "Poner en venta" : tipo === "BUSCA" ? "Buscar en el mercado" : tipo === "CLAUSULAZO" ? "Fichar de un rival" : "Pujar en el mercado";
  const amount = typeof action.euros === "number" ? action.euros : null;
  const jornada = typeof action.jornada === "number" ? action.jornada : null;
  return {
    id: `plan-${tipo}-${action.player_id || action.nombre || index}`,
    verb,
    title: tipo === "BUSCA" ? (action.posicion ? `un ${action.posicion}` : "un hueco") : action.nombre || "Jugador",
    position: action.posicion || null,
    imageUrl: photoFor(photos, action.player_id, action.nombre),
    cashImpact: amount,
    cashLabel: amount === null ? null : eurShort(amount),
    cashTone: tipo === "VENDE" ? "up" : "down",
    pointsImpact: jornada,
    pointsLabel: jornada === null ? null : `${points(jornada)} pts`,
    pointsTone: "flat",
    detail: action.detalle || null,
    href: tipo === "VENDE" ? "/equipo?tab=cartera" : tipo === "CLAUSULAZO" ? "/equipo?tab=clausulas" : "/mercado",
    guide: tipo === "VENDE" ? "Cartera" : tipo === "CLAUSULAZO" ? "Cláusulas" : "Mercado",
  };
}

const TAB_LABEL: Record<StrategyView["id"], string> = {
  estrategia: "Fichajes",
  clausulas: "Cláusulas",
  ventas: "Ventas",
};

function rowHeadline(move: StrategyMove, later: boolean): string {
  const kind = pillOf(move.verb).label;
  if (kind === "BUSCA") return move.title.startsWith("Busca") ? move.title : `Busca ${move.title}`;
  if (kind === "VENDE") return later ? `Vende más adelante a ${move.title}` : `Vende a ${move.title}`;
  if (kind === "CLAUSULAZO") return `Cláusula a ${move.title}`;
  return `Puja por ${move.title}`;
}

function leadLine(detail: string | null): string | null {
  if (!detail) return null;
  const line = detail.split(/(?<=\.)\s+/)[0]?.trim();
  if (!line) return null;
  return line.length > 96 ? `${line.slice(0, 93)}…` : line;
}

export function SigningBoard({
  plan,
  optimize,
  squads,
  trends,
  needs,
  loading,
  refreshing,
  photos,
}: {
  plan: PlanPayload | null;
  optimize: OptimizePayload | null;
  squads: SquadsPayload | null;
  trends: TrendsPayload | null;
  needs: NeedsPayload | null;
  loading: boolean;
  refreshing: boolean;
  photos: PhotoIndex;
  photoLine?: string;
}) {
  const views = useMemo(
    () => buildStrategyViews(plan, optimize, squads, trends, needs),
    [plan, optimize, squads, trends, needs],
  );
  const [desk, setDesk] = useState<StrategyView["id"]>("estrategia");
  const [openId, setOpenId] = useState<string | null>(null);
  const view = views.find((item) => item.id === desk) ?? views[0];
  const fichajes = plan?.plan_fichajes;
  const planMoves = (fichajes?.acciones || []).map((action, index) => moveFromAction(action, index, photos));
  const listed = (desk === "estrategia" && planMoves.length ? planMoves : view.groups.flatMap((group) => group.moves)).map(
    (move) => (move.imageUrl ? move : { ...move, imageUrl: photoFor(photos, null, move.title) }),
  );
  const hoy = listed.filter((move) => {
    if (desk === "estrategia" && planMoves.length) {
      const action = (fichajes?.acciones || []).find((row, index) => moveFromAction(row, index, photos).id === move.id);
      return action ? action.momento !== "luego" : bucketOf(move.verb) === "hoy";
    }
    return bucketOf(move.verb) === "hoy";
  });
  const luego = listed.filter((move) => !hoy.includes(move));
  const verdict =
    desk === "estrategia"
      ? fichajes?.veredicto || (view.pointsTone === "up" ? "Hazlo ya" : view.headline || "Sin plan")
      : view.headline || view.label;
  const gain =
    typeof fichajes?.mejora_puntos_jornada === "number"
      ? signedPoints(fichajes.mejora_puntos_jornada)
      : view.pointsMove
        ? view.pointsMove.replace(" pts", "")
        : null;
  const cashNow = typeof plan?.cash_eur === "number" ? plan.cash_eur : null;
  const cashEnd = typeof fichajes?.saldo_al_final === "number" ? fichajes.saldo_al_final : null;

  return (
    <div className="desk">
      <div className="desk-switch" role="tablist" aria-label="Mesas de recomendación">
        {views.map((item) => {
          const count =
            item.id === "estrategia" && planMoves.length
              ? planMoves.length
              : item.groups.reduce((total, group) => total + group.moves.length, 0);
          const active = item.id === view.id;
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={active}
              className={active ? "desk-switch__btn desk-switch__btn--on" : "desk-switch__btn"}
              onClick={() => {
                setDesk(item.id);
                setOpenId(null);
              }}
            >
              {TAB_LABEL[item.id]}
              {count ? <span>{count}</span> : null}
            </button>
          );
        })}
      </div>

      <header className="board-hero">
        <div className="relative flex items-end justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#8B9EB0]">Qué hace el plan</p>
            <p className="mt-1.5 text-[1.5rem] font-bold leading-tight tracking-tight text-[#F0F6FC]">
              {loading && !plan ? "…" : verdict}
            </p>
            {refreshing ? <p className="mt-1 font-mono text-[11px] text-[#0297DE]">Actualizando</p> : null}
          </div>
          {gain && desk === "estrategia" ? (
            <div className="shrink-0 text-right">
              <p className={`font-mono text-[2.4rem] font-bold leading-none tabular-nums ${gain.startsWith("−") || gain.startsWith("-") ? "text-[#FC734D]" : "text-[#67C6F5]"}`}>
                {gain}
              </p>
              <p className="mt-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-[#8B9EB0]">pts/jornada</p>
            </div>
          ) : null}
        </div>
        {desk === "estrategia" && (cashNow !== null || cashEnd !== null) ? (
          <div className="relative mt-4 flex items-center gap-2 text-[11px] font-semibold text-[#8B9EB0]">
            {cashNow !== null ? <span className="rounded-full bg-white/[0.06] px-2.5 py-1 font-mono tabular-nums text-[#C5D4E2]">Ahora {eurShort(cashNow)}</span> : null}
            {cashNow !== null && cashEnd !== null ? <span aria-hidden="true">→</span> : null}
            {cashEnd !== null ? (
              <span className={`rounded-full px-2.5 py-1 font-mono tabular-nums ${cashEnd < 0 ? "bg-[#FC734D]/20 text-[#FFB4A0]" : "bg-[#10B981]/15 text-[#6EE7B7]"}`}>
                Final {eurShort(cashEnd)}
              </span>
            ) : null}
          </div>
        ) : null}
      </header>

      {loading && !plan ? (
        <div className="desk-skel" aria-hidden="true" />
      ) : hoy.length || luego.length ? (
        <>
          <ActionGroup title="Hoy" tone="hoy" moves={hoy} later={false} openId={openId} onToggle={setOpenId} />
          <ActionGroup title="Espera" tone="espera" moves={luego} later openId={openId} onToggle={setOpenId} />
        </>
      ) : (
        <p className="desk-empty">
          {view.id === "estrategia"
            ? "Con esta foto no hay un fichaje que suba los puntos del once."
            : "Esta foto no deja un movimiento en esta mesa."}
        </p>
      )}
    </div>
  );
}

function ActionGroup({
  title,
  tone,
  moves,
  later,
  openId,
  onToggle,
}: {
  title: string;
  tone: "hoy" | "espera";
  moves: StrategyMove[];
  later: boolean;
  openId: string | null;
  onToggle: (id: string | null) => void;
}) {
  if (!moves.length) return null;
  return (
    <section aria-label={title}>
      <h2 className="mb-2">
        <span
          className={`inline-flex items-center rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.14em] ${
            tone === "hoy" ? "bg-[#FC734D] text-[#02070A]" : "bg-[#0297DE]/20 text-[#67C6F5]"
          }`}
        >
          {title}
        </span>
      </h2>
      <ul className="flex flex-col gap-2">
        {moves.map((move) => (
          <ActionRow key={move.id} move={move} later={later} open={openId === move.id} onToggle={() => onToggle(openId === move.id ? null : move.id)} />
        ))}
      </ul>
    </section>
  );
}

const KIND_RING: Record<string, string> = {
  PUJA: "from-[#0297DE] to-[#0297DE]/10",
  BUSCA: "from-[#4B6075] to-[#4B6075]/10",
  VENDE: "from-[#FC734D] to-[#FC734D]/10",
  CLAUSULAZO: "from-[#FC734D] to-[#FC734D]/10",
};

const KIND_COPY: Record<string, string> = {
  PUJA: "Pujar",
  BUSCA: "Buscar",
  VENDE: "Vender",
  CLAUSULAZO: "Cláusula",
};

function ActionRow({
  move,
  later,
  open,
  onToggle,
}: {
  move: StrategyMove;
  later: boolean;
  open: boolean;
  onToggle: () => void;
}) {
  const kind = pillOf(move.verb).label;
  const name = kind === "BUSCA" ? move.position || move.title : move.title;
  const preview = leadLine(move.detail);
  const selling = kind === "VENDE";
  return (
    <li className={`home-card !p-0 ${open ? "!border-[#0297DE]/40" : ""} ${later ? "opacity-80" : ""}`}>
      <button type="button" className="flex w-full items-center gap-3.5 p-3 text-left" onClick={onToggle} aria-expanded={open}>
        <span className={`shrink-0 rounded-full bg-gradient-to-br p-[2.5px] ${KIND_RING[kind] || KIND_RING.PUJA}`}>
          <PlayerAvatar
            player={{ name, image_url: move.imageUrl }}
            size="sm"
            className="!h-[3.4rem] !w-[3.4rem] !text-[12px] !ring-0 border-[3px] border-[#07121A]"
          />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1.5">
            <span className={`rounded-full px-2 py-[3px] text-[9.5px] font-bold uppercase tracking-[0.12em] ${pillOf(move.verb).className}`}>
              {KIND_COPY[kind] || kind}
            </span>
            {later ? <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[#8B9EB0]">luego</span> : null}
          </span>
          <span className="mt-1 block truncate text-[16px] font-bold leading-tight tracking-tight text-[#F0F6FC]">
            {kind === "BUSCA" ? rowHeadline(move, later) : name}
          </span>
          {move.position && kind !== "BUSCA" ? (
            <span className="mt-0.5 block truncate text-[11.5px] capitalize text-[#8B9EB0]">{move.position}</span>
          ) : preview && !open ? (
            <span className="mt-0.5 block truncate text-[11.5px] text-[#8B9EB0]">{preview}</span>
          ) : null}
        </span>
        <span className="flex shrink-0 flex-col items-end gap-1">
          {move.cashLabel ? (
            <span className={`font-mono text-[14px] font-bold tabular-nums ${selling ? "text-[#6EE7B7]" : "text-[#F0F6FC]"}`}>
              {selling ? "+" : ""}
              {move.cashLabel}
            </span>
          ) : null}
          {move.pointsLabel ? <span className="font-mono text-[11px] font-semibold tabular-nums text-[#FC734D]">{move.pointsLabel}</span> : null}
        </span>
      </button>
      {open ? (
        <div className="border-t border-white/[0.06] px-3.5 pb-3.5 pt-3">
          {move.detail ? <p className="text-[13px] leading-5 text-[#C5D4E2]">{move.detail}</p> : null}
          <Link href={move.href} className="mt-3 inline-flex items-center gap-1 rounded-full bg-[#0297DE]/15 px-3 py-1.5 text-xs font-semibold text-[#67C6F5]">
            Ver en {move.guide} →
          </Link>
        </div>
      ) : null}
    </li>
  );
}
