"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useDashboard } from "@/components/DashboardProvider";
import { ErrorCard, Skeleton } from "@/components/Feedback";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { endpoint, getJson } from "@/lib/api";
import {
  buildClausulazosGuide,
  formatCountdown,
  offerReasonLabel,
  type ClausulazosGuideModel,
  type DateBucket,
  type RoadmapStep,
} from "@/lib/clausulazosGuide";
import { clockLabel, eur, glass, multiple, playerName, points } from "@/lib/format";
import { ClauseRaidPanel } from "@/components/ClauseRaidPanel";
import { buildRaidPlan } from "@/lib/clauseRaidPlan";
import type { ApiError, ClauseBoardPayload, NeedsPayload, OptimizePayload, PlanPayload, SquadsPayload } from "@/lib/types";

const PHASE_BADGE: Record<string, string> = {
  cerrado: "badge badge--bad",
  espera: "badge badge--warn",
  oleada: "badge badge--warn",
  abierto: "badge badge--good",
};

const ACTION_KIND_LABEL: Record<string, string> = {
  clausular: "Clausular",
  subir_clausula: "Subir cláusula",
};

const ROADMAP_STATUS: Record<RoadmapStep["status"], { ring: string; label: string }> = {
  done: { ring: "border-[color:var(--mint)] bg-[color:var(--mint-soft)] text-mint", label: "Hecho" },
  now: { ring: "border-[color:var(--gold)] bg-[color:var(--gold-soft)] text-gold", label: "Ahora" },
  next: { ring: "border-[color:var(--line-strong)] bg-[color:var(--surface-strong)] text-muted", label: "Siguiente" },
  blocked: { ring: "border-[color:var(--coral)]/40 bg-[color:var(--coral-soft)] text-coral", label: "Bloqueado" },
  na: { ring: "border-[color:var(--line)] bg-[color:var(--surface)] text-faint", label: "N/A" },
};

function ReadinessMeter({ guide }: { guide: ClausulazosGuideModel }) {
  const { readiness } = guide;
  const tone =
    readiness.score >= 80
      ? "text-mint"
      : readiness.score >= 50
        ? "text-gold"
        : "text-coral";
  return (
    <div className="flex flex-wrap items-center gap-4">
      <div
        className="relative flex h-16 w-16 shrink-0 items-center justify-center rounded-full border-4 border-[color:var(--line)] bg-[color:var(--surface-strong)]"
        style={{
          background: `conic-gradient(var(--mint) ${readiness.score * 3.6}deg, var(--line) 0deg)`,
        }}
        aria-hidden
      >
        <span className={`flex h-12 w-12 items-center justify-center rounded-full bg-[color:var(--surface)] font-mono text-sm font-semibold ${tone}`}>
          {readiness.score}%
        </span>
      </div>
      <div className="min-w-0 flex-1">
        <p className="font-semibold tracking-tight">{readiness.label}</p>
        <p className="mt-1 text-sm text-muted">{readiness.detail}</p>
      </div>
    </div>
  );
}

function RoadmapStrip({ steps }: { steps: RoadmapStep[] }) {
  return (
    <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
      {steps.map((step) => {
        const style = ROADMAP_STATUS[step.status];
        return (
          <li
            key={step.id}
            className={`rounded-xl border px-3 py-3 ${style.ring}${step.status === "now" ? " ring-2 ring-[color:var(--gold)]/30" : ""}`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-xs opacity-70">{step.order}</span>
              <span className="text-[10px] font-medium uppercase tracking-wide">{style.label}</span>
            </div>
            <p className="mt-1 text-sm font-semibold">{step.title}</p>
            <p className="mt-0.5 text-xs leading-snug opacity-85">{step.subtitle}</p>
          </li>
        );
      })}
    </ol>
  );
}

function Step({
  n,
  title,
  children,
  active,
  action,
}: {
  n: number;
  title: string;
  children: ReactNode;
  active?: boolean;
  action?: ReactNode;
}) {
  return (
    <section className={`${glass("p-4 md:p-5")}${active ? " ring-2 ring-[color:var(--gold)]/35" : ""}`}>
      <div className="flex items-start gap-3">
        <span
          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full font-mono text-sm font-semibold ${
            active ? "bg-[color:var(--gold-soft)] text-gold" : "bg-[color:var(--surface-strong)] text-muted"
          }`}
        >
          {n}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <h2 className="section-title text-[1.1rem]">{title}</h2>
            {action}
          </div>
          <div className="mt-3">{children}</div>
        </div>
      </div>
    </section>
  );
}

function TimelineDay({ bucket, expanded, onToggle }: { bucket: DateBucket; expanded: boolean; onToggle: () => void }) {
  const status =
    bucket.open_count === bucket.count
      ? "Todo abierto"
      : bucket.locked_count === bucket.count
        ? "Todo bloqueado"
        : `${bucket.open_count} abierto · ${bucket.locked_count} bloqueado`;
  return (
    <div className="border-b border-[color:var(--line)] pb-3 last:border-0">
      <button type="button" onClick={onToggle} className="flex w-full items-center justify-between gap-2 text-left">
        <span className="font-medium">
          {bucket.label}
          {bucket.is_peak ? <span className="ml-2 badge badge--warn">oleada</span> : null}
        </span>
        <span className="text-xs text-muted">{expanded ? "Ocultar" : "Ver lista"}</span>
      </button>
      <p className="mt-1 text-sm text-muted">{status}</p>
      {expanded ? (
        <ul className="mt-2 flex flex-col gap-2">
          {bucket.entries.map((entry) => (
            <li key={String(entry.player_id)} className="flex items-center gap-3 text-sm">
              <PlayerAvatar player={entry} size="sm" />
              <div className="min-w-0 flex-1">
                <p className="flex flex-wrap items-center gap-1.5 font-medium">
                  <span className="truncate">{playerName(entry)}</span>
                  {entry.raised_today ? (
                    <span className="badge badge--bad !px-1.5 !py-0 text-[10px]" title="El rival subió esta cláusula en la última lectura">
                      subió {entry.clause_delta_eur ? eur(entry.clause_delta_eur) : ""}
                    </span>
                  ) : entry.raised_since_photo ? (
                    <span className="badge badge--warn !px-1.5 !py-0 text-[10px]" title="Cláusula más alta que en la foto de referencia">
                      +{entry.clause_delta_eur ? eur(entry.clause_delta_eur) : ""}
                    </span>
                  ) : null}
                  {entry.clause_rule ? (
                    <span className="badge badge--warn !px-1.5 !py-0 text-[10px]">regla {entry.clause_rule}</span>
                  ) : null}
                </p>
                <p className="text-xs text-muted">
                  {entry.manager_name || entry.fantasy_team_name || "Rival"}
                  {entry.position ? ` · ${entry.position}` : ""}
                  {typeof entry.buyout_clause_eur === "number" ? ` · ${eur(entry.buyout_clause_eur)}` : ""}
                  {typeof entry.clause_multiple === "number" ? ` · ${multiple(entry.clause_multiple)}` : ""}
                </p>
              </div>
              <span className={entry.is_open ? "badge badge--good" : "badge badge--warn"}>
                {entry.is_open ? "Abierto" : entry.local_time}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function ClausulazosGuide() {
  const search = useSearchParams();
  const league = search.get("league");
  const hoyHref = search.toString() ? `/?${search.toString()}` : "/";
  const rivalesHref = search.toString() ? `/rivales?${search.toString()}` : "/rivales";
  const { squads, needs, coreLoading, busy, plan, pending, refresh } = useDashboard();
  const [nowMs, setNowMs] = useState(() => Date.now());
  // ``undefined`` = el usuario aún no ha tocado el calendario: se abre el pico.
  const [pickedDate, setPickedDate] = useState<string | null | undefined>(undefined);
  const [rulesOpen, setRulesOpen] = useState(false);
  // El calendario tiene que ver **todas** las cláusulas rivales: ``squads.clauses``
  // solo trae las que cumplen la regla de oro y dejaría fuera a la mayoría.
  const [board, setBoard] = useState<{ league: string | null; payload: ClauseBoardPayload } | null>(null);
  const [optimize, setOptimize] = useState<OptimizePayload | null>(null);

  useEffect(() => {
    const tick = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(tick);
  }, []);

  useEffect(() => {
    let cancelled = false;
    getJson<OptimizePayload>(endpoint("/api/optimize", league))
      .then((payload) => {
        if (!cancelled && payload?.ok !== false) setOptimize(payload);
      })
      .catch(() => {
        // Sin once el plan previo sigue: pierde la columna de puntos, no el orden.
        if (!cancelled) setOptimize(null);
      });
    return () => {
      cancelled = true;
    };
  }, [league]);

  useEffect(() => {
    let cancelled = false;
    getJson<ClauseBoardPayload>(endpoint("/api/clause-board", league))
      .then((payload) => {
        if (!cancelled) setBoard({ league, payload });
      })
      .catch(() => {
        // Sin el tablero la guía sigue funcionando con ``squads.clauses``:
        // es una mejora de cobertura, no un requisito para pintar.
        if (!cancelled) setBoard({ league, payload: { ok: false, error: { message: "Sin clause-board." } } });
      });
    return () => {
      cancelled = true;
    };
  }, [league]);

  const boardPayload = board && board.league === league ? board.payload : null;

  const guide: ClausulazosGuideModel | null = useMemo(() => {
    if (!plan || plan.ok === false) return null;
    return buildClausulazosGuide(
      plan as PlanPayload,
      squads as SquadsPayload | null,
      needs as NeedsPayload | null,
      nowMs,
      boardPayload,
    );
  }, [plan, squads, needs, nowMs, boardPayload]);

  const raid = useMemo(
    () =>
      buildRaidPlan({
        plan: plan as PlanPayload | null,
        squads: squads as SquadsPayload | null,
        board: boardPayload,
        optimize,
        nowMs,
      }),
    [plan, squads, boardPayload, optimize, nowMs],
  );

  // El día abierto por defecto es el pico; mientras el usuario no toque nada,
  // se deriva en el render en vez de sembrar estado desde un efecto.
  const openDate = pickedDate === undefined ? (guide?.peak_date ?? null) : pickedDate;

  const countdown = formatCountdown(
    guide?.next_unlock_at ? Date.parse(guide.next_unlock_at) : null,
    nowMs,
  );
  const closeCountdown = formatCountdown(
    guide?.window_close_at ? Date.parse(guide.window_close_at) : null,
    nowMs,
  );

  const activeStep =
    guide?.phase === "cerrado" ? 4 : guide?.phase === "oleada" || guide?.phase === "espera" ? 1 : guide?.top_pick ? 3 : 2;

  const loadingPlan = pending.plan && !plan;
  if ((coreLoading || loadingPlan) && !guide) {
    return <Skeleton title="Clausulazos" rows={10} />;
  }

  if (!guide) {
    return (
      <ErrorCard
        title="Clausulazos"
        payload={(plan as ApiError | null) || { error: { message: "Sin plan de cláusulas." } }}
      />
    );
  }

  return (
    <div className="flex flex-col gap-5">
      {raid ? <ClauseRaidPanel plan={raid} nowMs={nowMs} /> : null}

      <section className={glass("p-4 md:p-5")}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="eyebrow">Hoja de ruta · clausulazos</p>
            <h2 className="section-title mt-1">{guide.phase_title}</h2>
            <p className="section-support mt-2">{guide.phase_detail}</p>
            <p className="mt-2 text-xs text-muted">
              Acciones y reloj en{" "}
              <Link href={hoyHref} className="underline decoration-dotted underline-offset-2">
                Hoy
              </Link>
              {" · "}caja rival en{" "}
              <Link href={rivalesHref} className="underline decoration-dotted underline-offset-2">
                Rivales
              </Link>
            </p>
          </div>
          <span className={PHASE_BADGE[guide.phase] || "badge"}>{guide.phase.replace(/_/g, " ")}</span>
        </div>
        <div className="mt-5">
          <ReadinessMeter guide={guide} />
        </div>
        <div className="mt-5">
          <p className="metric-label mb-2">Cuatro pasos</p>
          <RoadmapStrip steps={guide.roadmap} />
        </div>
        <dl className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-3 py-2">
            <dt className="metric-label">Tu caja</dt>
            <dd className="metric-value mt-0.5 text-lg text-gold">{eur(guide.cash_eur)}</dd>
          </div>
          <div className="rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-3 py-2">
            <dt className="metric-label">Candados / abiertos</dt>
            <dd className="metric-value mt-0.5 text-lg">
              {guide.locked_total} / {guide.open_total}
            </dd>
          </div>
          <div className="rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-3 py-2">
            <dt className="metric-label">Cierre clausulazos</dt>
            <dd className="metric-value mt-0.5 text-sm">{guide.window_close_label || "s/d"}</dd>
            <dd className="text-[11px] text-muted">
              {guide.window_open === false ? "cerrado" : guide.window_open ? "abierto" : "sin saque"}
            </dd>
            {closeCountdown && guide.window_open ? (
              <dd className="font-mono text-[11px] text-warn">Cierra en {closeCountdown}</dd>
            ) : null}
          </div>
          <div className="rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] px-3 py-2">
            <dt className="metric-label">Próximo desbloqueo</dt>
            <dd className="metric-value mt-0.5 text-sm">{guide.next_unlock_label || "Ninguno pendiente"}</dd>
            {countdown ? <dd className="font-mono text-[11px] text-mint">{countdown}</dd> : null}
          </div>
        </dl>
        <p className="mt-3 text-[11px] text-faint">
          Foto guardada · última lectura{" "}
          {guide.fetched_at ? new Date(guide.fetched_at).toLocaleString("es-ES") : "s/d"}. No hay recarga en segundo
          plano: cuando quieras datos nuevos, pulsa Actualizar arriba.
        </p>
      </section>

      <section className={glass("p-4 md:p-5")}>
        <p className="eyebrow">Checklist de preparación</p>
        <h2 className="section-title mt-1 text-[1.1rem]">Qué tener listo al 100%</h2>
        <ul className="mt-3 flex flex-col gap-2">
          {guide.checklist.map((item) => (
            <li
              key={item.id}
              className={`flex gap-3 rounded-lg border px-3 py-2 text-sm ${
                item.done
                  ? "border-[color:var(--mint)]/25 bg-[color:var(--mint-soft)]/40"
                  : item.priority === "critical"
                    ? "border-[color:var(--coral)]/20 bg-[color:var(--coral-soft)]/30"
                    : "border-[color:var(--line)] bg-[color:var(--surface-strong)]"
              }`}
            >
              <span className="mt-0.5 shrink-0" aria-hidden>
                {item.done ? "✓" : item.priority === "critical" ? "!" : "○"}
              </span>
              <div className="min-w-0">
                <p className="font-medium">{item.label}</p>
                {item.detail ? <p className="mt-0.5 text-xs text-muted">{item.detail}</p> : null}
              </div>
            </li>
          ))}
        </ul>
        {guide.playbook.length ? (
          <div className="mt-4 rounded-xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] p-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted">Playbook esta jornada</p>
            <ul className="mt-2 list-disc space-y-1 pl-4 text-sm text-muted-strong">
              {guide.playbook.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
        ) : null}
        <button
          type="button"
          className="mt-3 text-xs text-muted underline decoration-dotted underline-offset-2"
          onClick={() => setRulesOpen((open) => !open)}
        >
          {rulesOpen ? "Ocultar reglas clave" : "Ver reglas que no puedes olvidar"}
        </button>
        {rulesOpen ? (
          <ul className="mt-2 space-y-1 text-xs leading-5 text-faint">
            <li>El mercado de cláusulas cierra 24 h antes del primer partido de la jornada (Europe/Madrid).</li>
            <li>Subir cláusula: por cada 2 € de incremento pagas 1 € (redondeo al alza).</li>
            <li>Caja negativa o menos de 11 al inicio de jornada → 0 puntos en toda la jornada.</li>
            <li>Blindados no son clausulables; candado cerrado = no comprable hasta la hora exacta.</li>
            <li>Aquí no se envía nada: en la app confirma clausular o subir cláusula con un sí explícito.</li>
          </ul>
        ) : null}
      </section>

      {guide.clause_actions.length ? (
        <section className={glass("p-4 md:p-5")}>
          <p className="eyebrow">Órdenes del plan</p>
          <h2 className="section-title mt-1 text-[1.1rem]">Acciones concretas (sin envío automático)</h2>
          <ul className="mt-3 flex flex-col gap-3">
            {guide.clause_actions.map((action, index) => (
              <li key={`${action.kind}-${action.player_id}-${index}`} className="border-b border-[color:var(--line)] pb-3 last:border-0">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="font-medium">
                    {ACTION_KIND_LABEL[action.kind || ""] || action.kind}{" "}
                    {playerName(action)}
                    {action.eligible === false ? (
                      <span className="ml-2 badge badge--bad">no elegible</span>
                    ) : (
                      <span className="ml-2 badge badge--good">elegible</span>
                    )}
                  </span>
                  <span className="font-mono text-sm text-gold">{eur(action.amount_eur)}</span>
                </div>
                <p className="mt-1 text-sm text-muted">
                  {action.detail}
                  {action.reason ? ` · ${offerReasonLabel(action.reason)}` : ""}
                </p>
                <p className="text-xs text-faint">
                  Caja después {eur(action.cash_after_eur)}
                  {typeof action.points_delta === "number" ? ` · +${points(action.points_delta)} pts` : ""}
                  {typeof action.target_clause_eur === "number"
                    ? ` · cláusula objetivo ${eur(action.target_clause_eur)}`
                    : ""}
                </p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {guide.upcoming_unlocks.length ? (
        <section className={glass("p-4 md:p-5")}>
          <p className="eyebrow">Próximos candados</p>
          <h2 className="section-title mt-1 text-[1.05rem]">Los siguientes en abrirse</h2>
          <ul className="mt-2 flex flex-col gap-2">
            {guide.upcoming_unlocks.map((entry) => (
              <li key={String(entry.player_id)} className="flex items-center gap-3 text-sm">
                <PlayerAvatar player={entry} size="sm" />
                <div className="min-w-0 flex-1">
                  <p className="font-medium truncate">{playerName(entry)}</p>
                  <p className="text-xs text-muted">
                    {entry.manager_name || "Rival"}
                    {entry.is_self ? " · tu plantilla" : ""}
                    {typeof entry.buyout_clause_eur === "number" ? ` · ${eur(entry.buyout_clause_eur)}` : ""}
                  </p>
                </div>
                <span className="shrink-0 font-mono text-xs text-muted">
                  {entry.local_date} {entry.local_time}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {guide.top_pick ? (
        <section className={`${glass("p-4 md:p-5")} border-[color:var(--gold)]/40 bg-[color:var(--gold-soft)]/40`}>
          <p className="eyebrow text-gold">Prioridad al abrir</p>
          <div className="mt-2 flex flex-wrap items-center gap-4">
            <div className="h-14 w-14 overflow-hidden rounded-full bg-[color:var(--surface-strong)]">
              <PlayerAvatar player={guide.top_pick} />
            </div>
            <div className="min-w-0 flex-1">
              <h3 className="text-lg font-semibold tracking-tight">
                {playerName(guide.top_pick)}
                {guide.top_pick.decision === "PAGAR" ? (
                  <span className="ml-2 badge badge--good">PAGAR</span>
                ) : (
                  <span className="ml-2 badge badge--warn">alternativa</span>
                )}
              </h3>
              <p className="text-sm text-muted-strong">
                Cláusula {eur(guide.top_pick.buyout_clause_eur)}
                {guide.top_pick.manager_name ? ` · plantilla de ${guide.top_pick.manager_name}` : ""}
                {typeof guide.top_pick.points_delta === "number"
                  ? ` · +${points(guide.top_pick.points_delta)} pts al XI`
                  : ""}
              </p>
              <p className="mt-1 text-sm">
                Caja después {eur(guide.top_pick.cash_after_eur)}. En la app: cláusula → confirmar (hace falta un sí explícito).
              </p>
              {guide.top_pick.reason ? (
                <p className="mt-1 text-xs text-faint">{offerReasonLabel(guide.top_pick.reason)}</p>
              ) : null}
            </div>
          </div>
        </section>
      ) : (
        <section className={glass("p-4 md:p-5")}>
          <p className="text-sm text-muted">
            Ningún clausulazo encaja en tu XI con caja positiva. Revisa el calendario por si se abren opciones baratas.
          </p>
        </section>
      )}

      <Step n={1} title="Antes de que abran — protege lo tuyo" active={activeStep === 1}>
        {guide.protect.length ? (
          <ul className="flex flex-col gap-3">
            {guide.protect.map((row) => (
              <li key={String(row.player_id)} className="border-b border-[color:var(--line)] pb-3 last:border-0">
                <p className="font-medium">
                  {playerName(row)}
                  {row.urgent ? <span className="ml-2 badge badge--bad">urgente</span> : null}
                </p>
                <p className="text-sm text-muted">
                  Cláusula {eur(row.buyout_clause_eur)} · {row.threat_count} rival(es) pueden pagar
                </p>
                <p className="mt-1 text-sm font-medium text-ink">{row.headline}</p>
                <p className="text-sm text-muted">{row.detail}</p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">Ningún rival con caja conocida cubre una cláusula tuya desbloqueada.</p>
        )}
      </Step>

      <Step n={2} title="Calendario de desbloqueos (Europe/Madrid)" active={activeStep === 2}>
        {guide.timeline.length ? (
          <div className="flex flex-col gap-3">
            {guide.timeline.map((bucket) => (
              <TimelineDay
                key={bucket.local_date}
                bucket={bucket}
                expanded={openDate === bucket.local_date}
                onToggle={() => setPickedDate((current) => ((current ?? guide.peak_date) === bucket.local_date ? null : bucket.local_date))}
              />
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted">La API no devolvió horas de candado en esta lectura.</p>
        )}
        {squads?.clause_lock_note ? (
          <p className="mt-3 text-xs leading-5 text-faint">{squads.clause_lock_note}</p>
        ) : null}
      </Step>

      <Step n={3} title="A quién clausular y cuánto" active={activeStep === 3}>
        {guide.offers.length ? (
          <ol className="flex flex-col gap-3">
            {guide.offers.map((row) => (
              <li
                key={String(row.player_id)}
                className={`flex gap-3 border-b border-[color:var(--line)] pb-3 last:border-0 ${
                  row.decision === "PAGAR" ? "rounded-lg bg-[color:var(--mint-soft)]/50 px-2 py-2" : ""
                }`}
              >
                <span className="metric-value w-6 shrink-0 text-faint">{row.rank}</span>
                <PlayerAvatar player={row} size="sm" />
                <div className="min-w-0 flex-1">
                  <p className="font-medium">
                    {playerName(row)}
                    {row.decision === "PAGAR" ? <span className="ml-2 badge badge--good">mejor delta</span> : null}
                  </p>
                  <p className="text-sm text-muted">
                    {eur(row.buyout_clause_eur)}
                    {row.manager_name ? ` · ${row.manager_name}` : ""}
                    {typeof row.points_delta === "number" ? ` · +${points(row.points_delta)} pts` : ""}
                  </p>
                  <p className="text-[11px] text-faint">
                    Caja después {eur(row.cash_after_eur)}
                    {row.reason ? ` · ${offerReasonLabel(row.reason)}` : ""}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-sm text-muted">Nadie desbloqueado mejora tu once sin dejar la caja en negativo.</p>
        )}
      </Step>

      <Step n={4} title="Rivales en riesgo (clausulazo probable)" active={activeStep === 4}>
        {guide.alerts.length ? (
          <ul className="flex flex-col gap-3">
            {guide.alerts.map((row) => (
              <li key={`${row.manager_name}-${row.player_id}`} className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                <span>
                  <span className="font-medium">{playerName(row)}</span>
                  <span className="text-muted"> · {row.manager_name}</span>
                  <span className="text-muted"> · {eur(row.buyout_clause_eur)}</span>
                </span>
                <span className="text-xs text-muted">
                  {row.already_open ? "ya abierto" : row.local_date && row.local_time ? clockLabel({ present: true, local_date: row.local_date, local_time: row.local_time }) : "sin hora"}
                  {" · "}
                  {row.motive}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">Sin alertas de clausulazo encajando con tu caja en esta lectura.</p>
        )}
        <button type="button" className="btn btn-secondary mt-4" onClick={() => void refresh()} disabled={busy}>
          Descargar datos nuevos
        </button>
      </Step>
    </div>
  );
}
