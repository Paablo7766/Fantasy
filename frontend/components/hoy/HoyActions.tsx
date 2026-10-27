"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { buildActionCards, signedPoints, type ActionCard } from "@/lib/hoy";
import { eur, eurShort } from "@/lib/format";
import type { PlanPayload } from "@/lib/types";

const MAX_ACTIONS = 4;

function CopyButton({ action }: { action: ActionCard }) {
  const [state, setState] = useState<"idle" | "done" | "error">("idle");

  useEffect(() => {
    if (state === "idle") return;
    const timer = window.setTimeout(() => setState("idle"), 1800);
    return () => window.clearTimeout(timer);
  }, [state]);

  const copy = useCallback(async () => {
    if (!action.copyValue) return;
    try {
      await navigator.clipboard.writeText(action.copyValue);
      setState("done");
    } catch {
      setState("error");
    }
  }, [action.copyValue]);

  if (!action.copyValue) return null;

  return (
    <button type="button" onClick={() => void copy()} className="hoy-btn hoy-btn--primary" aria-live="polite">
      {state === "done" ? "Copiado" : state === "error" ? "Copia manual" : action.copyLabel}
    </button>
  );
}

const OPEN_LABEL: Record<string, string> = {
  alinear: "Abrir once",
  cerrar_hueco: "Ir al mercado",
  vender_emergencia: "Abrir cartera",
  pujar: "Abrir mercado",
  clausular: "Abrir cláusulas",
  subir_clausula: "Subir cláusula",
  vender: "Abrir cartera",
  blindar: "Blindar",
};

/** Una tarjeta = una decisión. Qué, cuánto y cuándo; nada más. */
function ActionCardView({ action }: { action: ActionCard }) {
  const delta = signedPoints(action.pointsDelta);
  const blocked = !action.eligible || action.verdict === "NO";
  const verdictTone =
    action.verdict === "HAZLO" && !blocked
      ? "hoy-chip hoy-chip--mint"
      : blocked
        ? "hoy-chip hoy-chip--red"
        : "hoy-chip";
  const whenTone =
    action.whenTone === "now"
      ? "text-[color:var(--hoy-mint)]"
      : action.whenTone === "later"
        ? "text-[color:var(--hoy-gold)]"
        : "text-[color:var(--hoy-muted)]";

  return (
    <li className={`hoy-act ${blocked ? "hoy-act--blocked" : ""} ${action.isSurvival ? "hoy-act--survival" : ""}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          {action.playerName ? (
            <PlayerAvatar player={{ name: action.playerName, image_url: action.imageUrl }} size="sm" />
          ) : null}
          <div className="min-w-0">
            <p className="truncate text-[13.5px] font-semibold leading-tight tracking-[-0.015em] text-[color:var(--hoy-ink)]">
              {action.what || action.title}
            </p>
            <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-[color:var(--hoy-muted)]">
              {action.rank ? (
                <span className="font-mono text-[9.5px] font-semibold text-[color:var(--hoy-faint)]">
                  {String(action.rank).padStart(2, "0")}
                </span>
              ) : null}
              {action.playerName && action.position ? (
                <span className="rounded border border-[color:var(--hoy-line-strong)] px-1 py-px text-[9px] font-bold tracking-[0.06em] text-[color:var(--hoy-faint)]">
                  {action.position}
                </span>
              ) : null}
              {action.playerName ? <span className="truncate">{action.playerName}</span> : null}
              {action.playerName ? <span className="opacity-40" aria-hidden="true">·</span> : null}
              <span className={whenTone}>{action.whenLabel}</span>
            </p>
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <span className={action.verdict ? verdictTone : "hoy-chip"}>{blocked ? "NO" : action.verdict || "VER"}</span>
          <p className="hoy-act__amount">{action.costLabel || (typeof action.amount === "number" ? eur(action.amount) : "—")}</p>
          {delta ? (
            <p
              className={`metric-value text-[10.5px] ${
                action.pointsDelta && action.pointsDelta > 0 ? "text-[color:var(--hoy-mint)]" : "text-[#fca5a5]"
              }`}
            >
              {delta} pts
            </p>
          ) : null}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
        {typeof action.cashAfter === "number" ? (
          <span className={action.cashAfter < 0 ? "text-[#fca5a5]" : "text-[color:var(--hoy-faint)]"}>
            Caja después{" "}
            <span className={`metric-value ${action.cashAfter < 0 ? "text-[#fca5a5]" : "text-[color:var(--hoy-muted)]"}`}>
              {eurShort(action.cashAfter)}
            </span>
          </span>
        ) : null}
        {action.riskLabel ? (
          <span
            className={
              action.risk === "high"
                ? "text-[#fca5a5]"
                : action.risk === "low"
                  ? "text-[color:var(--hoy-mint)]"
                  : "text-[color:var(--hoy-gold)]"
            }
          >
            {action.riskLabel}
          </span>
        ) : null}
        {action.requiresConfirmation ? <span className="text-[color:var(--hoy-gold)]">Pide confirmación</span> : null}
      </div>

      {action.blockedReason ? (
        <p className="rounded-lg border border-[rgba(248,113,113,0.28)] bg-[rgba(239,68,68,0.1)] px-2.5 py-1.5 text-[11px] font-medium leading-4 text-[#fca5a5]">
          {action.blockedReason}
        </p>
      ) : action.ignore ? (
        <p className="text-[11px] leading-4 text-[color:var(--hoy-muted)]">
          <span className="font-semibold uppercase tracking-[0.1em] text-[color:var(--hoy-faint)]">Si no </span>
          {action.ignore}
        </p>
      ) : action.detail ? (
        <p className="line-clamp-2 text-[11px] leading-4 text-[color:var(--hoy-muted)]">{action.detail}</p>
      ) : null}

      <div className="mt-auto flex flex-wrap items-center gap-2 pt-0.5">
        <CopyButton action={action} />
        <Link href={action.href} className="hoy-btn">
          {OPEN_LABEL[action.kind] || "Ver detalle"}
        </Link>
      </div>
    </li>
  );
}

/** Estado vacío con la razón real, no un «todo bien» genérico. */
function ClearDay({ plan }: { plan: PlanPayload | null }) {
  const summary = plan?.market_summary;
  const rejected = typeof summary?.no === "number" ? summary.no : 0;
  const listings = typeof summary?.count === "number" ? summary.count : 0;
  const cash = typeof plan?.cash_eur === "number" ? plan.cash_eur : null;
  const savedPoints = typeof plan?.lineup?.saved_points === "number" ? plan.lineup.saved_points : null;

  const reasons = [
    typeof summary?.markets_left === "number"
      ? `Quedan ${summary.markets_left} mercado(s) hasta el saque: no se fuerza una compra.`
      : "Ninguna puja pasa hoy el filtro de precio y hueco.",
    rejected && listings
      ? `${rejected} de ${listings} listings descartados por precio, sobrepuja o falta de mejora real.`
      : "El motor no encontró una mejora que pague su coste.",
    savedPoints !== null
      ? `El once guardado rinde ${savedPoints.toLocaleString("es-ES", { maximumFractionDigits: 1 })} pts previstos y no hay cambio que lo mejore.`
      : "El once guardado no necesita cambios antes del cierre.",
  ];

  return (
    <div className="mt-4 rounded-xl border border-[rgba(74,222,128,0.2)] bg-[rgba(13,107,77,0.08)] px-3.5 py-3">
      <div className="flex items-start gap-2.5">
        <span className="mt-px grid h-6 w-6 shrink-0 place-items-center rounded-full border border-[rgba(74,222,128,0.3)] bg-[rgba(74,222,128,0.14)] text-[color:var(--hoy-mint)]">
          <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M3.4 8.4 6.3 11.3 12.6 5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-semibold tracking-[-0.02em] text-white">
            Nada que ejecutar hoy
            {cash !== null ? (
              <span className="ml-2 font-normal text-[color:var(--hoy-faint)]">
                Caja intacta · <span className="metric-value text-[color:var(--hoy-mint)]">{eurShort(cash)}</span>
              </span>
            ) : null}
          </p>
          <ul className="mt-1.5 flex flex-col gap-1">
            {reasons.map((reason) => (
              <li
                key={reason}
                className="flex gap-1.5 text-[11px] leading-4 text-[color:var(--hoy-muted)]"
              >
                <span className="text-[color:var(--hoy-faint)]" aria-hidden="true">
                  ·
                </span>
                {reason}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

export function HoyActions({ plan, loading }: { plan: PlanPayload | null; loading: boolean }) {
  const cards = useMemo(() => buildActionCards(plan, MAX_ACTIONS), [plan]);
  const prioritized = Array.isArray(plan?.priority_actions) ? plan.priority_actions : [];
  const total = prioritized.length || (Array.isArray(plan?.actions) ? plan.actions.length : 0);
  const hazlo = prioritized.filter((row) => row.verdict === "HAZLO").length;

  return (
    <section className="hoy-panel p-4 md:p-5" aria-labelledby="hoy-acciones">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2.5">
          <p className="hoy-label" id="hoy-acciones">
            Qué hacer
          </p>
          {hazlo ? <span className="hoy-chip hoy-chip--mint">{hazlo} HAZLO</span> : null}
          {total > MAX_ACTIONS ? <span className="hoy-chip">+{total - MAX_ACTIONS} en el plan</span> : null}
        </div>
        <p className="text-[10.5px] text-[color:var(--hoy-faint)]">Máximo 4 · orden por prioridad</p>
      </div>

      {loading && !plan ? (
        <div className="mt-4 grid gap-2.5 sm:grid-cols-2">
          {Array.from({ length: 2 }, (_, index) => (
            <div key={index} className="h-36 animate-pulse rounded-2xl bg-white/5" />
          ))}
        </div>
      ) : cards.length ? (
        <ul className="mt-4 grid gap-2.5 xl:grid-cols-2">
          {cards.map((action) => (
            <ActionCardView key={action.key} action={action} />
          ))}
        </ul>
      ) : (
        <ClearDay plan={plan} />
      )}
    </section>
  );
}
