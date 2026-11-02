"use client";

import { money } from "@/components/equipo/ui";
import { points, titularShare } from "@/lib/format";
import { signedPoints } from "@/lib/hoy";
import type { OptimizePayload, PlanPayload, Player } from "@/lib/types";

/** Semicírculo con relleno de cobre y un nudo luminoso en el extremo del progreso. */
function Arc({ fraction }: { fraction: number }) {
  const f = Math.min(1, Math.max(0, fraction));
  const angle = Math.PI - f * Math.PI;
  const knobX = 120 + 100 * Math.cos(angle);
  const knobY = 120 - 100 * Math.sin(angle);
  return (
    <svg viewBox="0 0 240 132" className="w-full" aria-hidden="true">
      <defs>
        <linearGradient id="impact-arc" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stopColor="#FF6A2B" />
          <stop offset="1" stopColor="#FFC08A" />
        </linearGradient>
      </defs>
      <path d="M 20 120 A 100 100 0 0 1 220 120" fill="none" stroke="rgba(255,255,255,0.09)" strokeWidth="14" strokeLinecap="round" />
      <path
        d="M 20 120 A 100 100 0 0 1 220 120"
        pathLength="100"
        fill="none"
        stroke="url(#impact-arc)"
        strokeWidth="14"
        strokeLinecap="round"
        strokeDasharray={`${f * 100} 100`}
        style={{ filter: "drop-shadow(0 0 10px rgba(255,122,61,0.65))", transition: "stroke-dasharray 900ms ease-out" }}
      />
      <circle cx={knobX} cy={knobY} r="11" fill="#fff" style={{ filter: "drop-shadow(0 0 8px rgba(255,170,110,0.9))" }} />
      <circle cx={knobX} cy={knobY} r="4.5" fill="#FF7A3D" />
    </svg>
  );
}

function Fact({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="min-w-0 rounded-2xl border border-white/[0.07] bg-white/[0.05] px-3 py-3 backdrop-blur-md">
      <p className="truncate text-[0.8rem] text-white/50">{label}</p>
      <p className={`mt-1.5 truncate text-[1.1rem] font-semibold leading-none tabular-nums ${tone || "text-white"}`}>{value}</p>
    </div>
  );
}

/**
 * Cuánto suma la estrategia a tu once: el once guardado frente al once con el
 * plan aplicado. Todo sale de ``plan_fichajes`` y ``lineup``; sin dato no se pinta.
 */
export function StrategyImpact({
  plan,
  optimize,
  loading,
}: {
  plan: PlanPayload | null;
  optimize: OptimizePayload | null;
  loading: boolean;
}) {
  const fichajes = plan?.plan_fichajes;
  const now =
    typeof fichajes?.puntos_once_actual === "number"
      ? fichajes.puntos_once_actual
      : typeof plan?.lineup?.saved_points === "number"
        ? plan.lineup.saved_points
        : null;
  const target =
    typeof fichajes?.puntos_once === "number"
      ? fichajes.puntos_once
      : typeof plan?.lineup?.expected_points === "number"
        ? plan.lineup.expected_points
        : (optimize?.expected_points ?? null);
  const delta =
    typeof fichajes?.mejora_puntos_jornada === "number"
      ? fichajes.mejora_puntos_jornada
      : now !== null && target !== null
        ? target - now
        : null;
  const hasGain = delta !== null && Math.abs(delta) >= 0.05;
  // El arco enseña cuánto del potencial del plan ya capturas con tu once guardado.
  const fraction = now !== null && target !== null && target > 0 ? now / target : target !== null ? 1 : 0;

  const xi: Player[] = optimize?.saved_lineup?.xi?.length ? optimize.saved_lineup.xi : optimize?.xi || [];
  const shares = xi.map((player) => titularShare(player.p_titular)).filter((value): value is number => value !== null);
  const avgShare = shares.length ? shares.reduce((total, value) => total + value, 0) / shares.length : null;

  const dash = loading ? "…" : "—";
  const big = hasGain ? signedPoints(delta) : target !== null ? points(target) : dash;
  const saldoFinal = fichajes?.saldo_al_final;
  const formation = fichajes?.formacion || plan?.lineup?.formation || null;

  return (
    <section className="home-feature" aria-label="Lo que suma el plan">
      <div className="relative flex items-center justify-between gap-3">
        <p className="text-[13px] font-medium text-white/60">Lo que suma el plan a tu once</p>
        {fichajes?.veredicto ? (
          <p className="rounded-full border border-white/10 bg-black/25 px-3 py-1.5 text-[12px] font-medium text-white/80">{fichajes.veredicto}</p>
        ) : null}
      </div>

      <div className="relative mx-auto mt-5 w-full max-w-[17.5rem]">
        <Arc fraction={fraction} />
        <div className="absolute inset-x-0 bottom-0 flex flex-col items-center">
          <p className="text-[12px] text-white/55">{hasGain ? "El plan suma" : "Puntos esperados"}</p>
          <p className="flex items-baseline gap-1.5 tabular-nums">
            <span className={`text-[3.4rem] font-semibold leading-none tracking-[-0.045em] ${hasGain && (delta as number) < 0 ? "text-[#FF8F6B]" : "text-white"}`}>{big}</span>
            <span className="text-base font-medium text-white/55">pts</span>
          </p>
        </div>
      </div>

      {hasGain && now !== null && target !== null ? (
        <p className="relative mt-3 text-center text-[13.5px] tabular-nums text-white/55">
          De {points(now)} a <span className="font-medium text-white">{points(target)}</span> esta jornada
        </p>
      ) : null}

      <div className="relative mt-6 grid grid-cols-3 gap-2.5">
        <Fact label="Formación" value={formation || dash} />
        <Fact
          label="Saldo tras el plan"
          value={typeof saldoFinal === "number" ? money(saldoFinal) : dash}
          tone={typeof saldoFinal === "number" && saldoFinal < 0 ? "text-[#FF8F6B]" : undefined}
        />
        <Fact label="Titularidad media" value={avgShare !== null ? `${Math.round(avgShare * 100)}%` : dash} />
      </div>
    </section>
  );
}
