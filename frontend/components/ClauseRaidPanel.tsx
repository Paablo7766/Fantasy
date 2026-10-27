"use client";

import { useCallback, useMemo, useState } from "react";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import type { RaidExecution, RaidMove, RaidPlanModel, RaidStep } from "@/lib/clauseRaidPlan";
import { eur, glass, multiple, playerName, points } from "@/lib/format";

const STEP_TONE: Record<RaidStep["status"], { box: string; label: string }> = {
  done: { box: "border-[color:var(--mint)]/40 bg-[color:var(--mint-soft)]/40", label: "Hecho" },
  now: { box: "border-[color:var(--gold)]/50 bg-[color:var(--gold-soft)]/40 ring-2 ring-[color:var(--gold)]/25", label: "Ahora" },
  next: { box: "border-[color:var(--line-strong)] bg-[color:var(--surface-strong)]", label: "Siguiente" },
  blocked: { box: "border-[color:var(--coral)]/40 bg-[color:var(--coral-soft)]/30", label: "Bloqueado" },
};

const EXEC_TONE: Record<RaidExecution["tone"], string> = {
  gold: "border-[color:var(--gold)]/50 bg-[color:var(--gold-soft)]/50",
  mint: "border-[color:var(--mint)]/30 bg-[color:var(--mint-soft)]/30",
  coral: "border-[color:var(--coral)]/40 bg-[color:var(--coral-soft)]/30",
  muted: "border-[color:var(--line)] bg-[color:var(--surface-strong)]",
};

function cashTone(value: number | null | undefined): string {
  if (typeof value !== "number") return "text-muted";
  return value < 0 ? "text-coral" : "text-mint";
}

function countdown(targetIso: string | null, nowMs: number): string | null {
  if (!targetIso) return null;
  const ms = Date.parse(targetIso);
  if (Number.isNaN(ms)) return null;
  const diff = ms - nowMs;
  if (diff <= 0) return "ya abierto · refresca";
  const total = Math.floor(diff / 1000);
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const mins = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (days > 0) return `${days}d ${hours}h ${mins}m`;
  if (hours > 0) return `${hours}h ${mins}m ${secs}s`;
  return `${mins}m ${secs}s`;
}

/** Texto plano para pegar en el móvil o en notas: el día clave no se navega. */
function planText(plan: RaidPlanModel): string {
  const lines: string[] = [
    `PLAN CLAUSULAZOS · caja ${eur(plan.cash_eur)} · libre ${eur(plan.budget_eur)}`,
    "",
  ];
  for (const step of plan.executions) {
    lines.push(`${step.order}. ${step.clock} — ${step.title}`);
    if (step.cash_after_eur !== null) lines.push(`   caja después: ${eur(step.cash_after_eur)}`);
  }
  lines.push("", "Paga UNA sola jugada: las de abajo son alternativas, no se suman.");
  if (plan.warnings.length) {
    lines.push("", "Ojo:");
    for (const warning of plan.warnings) lines.push(`- ${warning}`);
  }
  return lines.join("\n");
}

function MoveRow({ move, isBest }: { move: RaidMove; isBest: boolean }) {
  return (
    <li
      className={`flex flex-wrap items-center gap-3 border-b border-[color:var(--line)] py-2 text-sm last:border-0 ${
        isBest ? "rounded-lg bg-[color:var(--gold-soft)]/40 px-2" : ""
      }`}
    >
      <PlayerAvatar player={move} size="sm" />
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-center gap-1.5 font-medium">
          <span className="truncate">{playerName(move)}</span>
          {isBest ? <span className="badge badge--good">principal</span> : null}
          {move.preferred ? <span className="badge badge--warn">minuto tranquilo</span> : null}
          {move.blocked_reason ? <span className="badge badge--bad">no cabe</span> : null}
        </p>
        <p className="text-xs text-muted">
          {move.manager_name || "Rival"}
          {move.position ? ` · ${move.position}` : ""}
          {move.multiple !== null ? ` · ${multiple(move.multiple)}` : ""}
          {move.note ? ` · ${move.note}` : ""}
        </p>
      </div>
      <div className="shrink-0 text-right">
        <p className="font-mono text-sm font-semibold text-gold">{eur(move.clause_eur)}</p>
        <p className="text-[11px] text-muted">
          {move.second_label ?? move.local_time ?? "s/d"}
          {move.gain_pts !== null ? ` · +${points(move.gain_pts)} pts` : ""}
        </p>
      </div>
    </li>
  );
}

export function ClauseRaidPanel({ plan, nowMs }: { plan: RaidPlanModel; nowMs: number }) {
  const [copied, setCopied] = useState(false);
  const wait = countdown(plan.next_unlock_at, nowMs);

  const text = useMemo(() => planText(plan), [plan]);

  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2200);
    } catch {
      setCopied(false);
    }
  }, [text]);

  return (
    <div className="flex flex-col gap-4">
      <section className={`${glass("p-4 md:p-5")} border-[color:var(--gold)]/35`}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="eyebrow text-gold">Plan previo · antes de que abra</p>
            <h2 className="section-title mt-1 text-[1.15rem]">{plan.phase_title}</h2>
            <p className="section-support mt-1">{plan.phase_detail}</p>
          </div>
          {wait ? (
            <div className="shrink-0 rounded-xl border border-[color:var(--gold)]/40 bg-[color:var(--gold-soft)]/40 px-3 py-2 text-right">
              <p className="metric-label">Primer candado</p>
              <p className="font-mono text-sm font-semibold text-gold">{wait}</p>
            </div>
          ) : null}
        </div>

        <dl className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-3 py-2">
            <dt className="metric-label">Caja</dt>
            <dd className={`metric-value mt-0.5 text-base ${cashTone(plan.cash_eur)}`}>{eur(plan.cash_eur)}</dd>
          </div>
          <div className="rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-3 py-2">
            <dt className="metric-label">Libre para clausular</dt>
            <dd className="metric-value mt-0.5 text-base">{eur(plan.budget_eur)}</dd>
            <dd className="text-[11px] text-muted">reserva {eur(plan.reserve_eur)}</dd>
          </div>
          <div className="rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-3 py-2">
            <dt className="metric-label">Venta previa</dt>
            <dd className="metric-value mt-0.5 text-sm">
              {plan.sell ? `${playerName(plan.sell)} · ${eur(plan.sell.market_value_eur)}` : "No hace falta"}
            </dd>
          </div>
          <div className="rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-3 py-2">
            <dt className="metric-label">Jugada principal</dt>
            <dd className="metric-value mt-0.5 text-sm">
              {plan.best ? `${playerName(plan.best)} · ${eur(plan.best.clause_eur)}` : "Ninguna viable"}
            </dd>
            {plan.best?.gain_pts !== null && plan.best ? (
              <dd className="text-[11px] text-mint">+{points(plan.best.gain_pts)} pts al XI</dd>
            ) : null}
          </div>
        </dl>

        <ol className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {plan.roadmap.map((step) => {
            const tone = STEP_TONE[step.status];
            return (
              <li key={step.id} className={`rounded-xl border px-3 py-3 ${tone.box}`}>
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs opacity-70">{step.order}</span>
                  <span className="text-[10px] font-medium uppercase tracking-wide">{tone.label}</span>
                </div>
                <p className="mt-1 text-sm font-semibold">{step.title}</p>
                <p className="mt-0.5 text-xs leading-snug opacity-85">{step.subtitle}</p>
                <p className="mt-2 text-[11px] leading-snug text-muted">{step.detail}</p>
              </li>
            );
          })}
        </ol>
      </section>

      <section className={glass("p-4 md:p-5")}>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <p className="eyebrow">Guion del día clave</p>
            <h2 className="section-title mt-1 text-[1.05rem]">En este orden, a esta hora</h2>
          </div>
          <button type="button" className="btn btn-secondary" onClick={() => void copy()}>
            {copied ? "Copiado" : "Copiar plan"}
          </button>
        </div>
        <p className="mt-2 text-[11px] text-faint">
          Paga <strong>una</strong> jugada: cada tarjeta se presupuesta por separado con la venta ya hecha, no se suman.
        </p>
        <ol className="mt-3 flex flex-col gap-2">
          {plan.executions.map((step) => (
            <li key={`${step.order}-${step.title}`} className={`rounded-xl border px-3 py-2 ${EXEC_TONE[step.tone]}`}>
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-sm font-semibold">
                  <span className="mr-2 font-mono text-xs opacity-60">{step.order}</span>
                  {step.title}
                </p>
                <span className="font-mono text-xs font-semibold">{step.clock}</span>
              </div>
              <p className="mt-1 text-xs text-muted">{step.detail}</p>
              <p className={`mt-1 font-mono text-[11px] ${cashTone(step.cash_after_eur)}`}>
                Caja después {eur(step.cash_after_eur)}
              </p>
            </li>
          ))}
        </ol>
      </section>

      {plan.warnings.length ? (
        <section className={`${glass("p-4 md:p-5")} border-[color:var(--coral)]/30`}>
          <p className="eyebrow text-coral">Ojo antes de pagar</p>
          <ul className="mt-2 flex flex-col gap-1.5 text-sm text-muted-strong">
            {plan.warnings.map((warning) => (
              <li key={warning} className="flex gap-2">
                <span className="shrink-0 text-coral" aria-hidden>
                  !
                </span>
                <span>{warning}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className={glass("p-4 md:p-5")}>
        <p className="eyebrow">Tablero filtrado por tu caja</p>
        <h2 className="section-title mt-1 text-[1.05rem]">Candados que puedes pagar</h2>
        <ul className="mt-2">
          {plan.moves.length ? (
            plan.moves.map((move) => (
              <MoveRow key={String(move.player_id)} move={move} isBest={move.player_id === plan.best?.player_id} />
            ))
          ) : (
            <li className="text-sm text-muted">Sin desbloqueos futuros en esta lectura.</li>
          )}
        </ul>
        <p className="mt-3 text-[11px] text-faint">
          Calculado desde el tablero de cláusulas, tu plantilla y tu once óptimo. La app no envía nada: pagar o vender
          se confirma en la app oficial.
        </p>
      </section>
    </div>
  );
}
