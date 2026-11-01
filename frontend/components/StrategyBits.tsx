import { eur, eurShort } from "@/lib/format";
import type { CapitanPick, PlanFichajes, PlanFichajeAccion, Player } from "@/lib/types";

export type CaptainRole = "seguro" | "techo";

export function captainRoles(
  playerId: string | null | undefined,
  seguro: CapitanPick | null | undefined,
  techo: CapitanPick | null | undefined,
): CaptainRole[] {
  if (!playerId) return [];
  const id = String(playerId);
  const roles: CaptainRole[] = [];
  if (seguro?.player_id && String(seguro.player_id) === id) roles.push("seguro");
  if (techo?.player_id && String(techo.player_id) === id) roles.push("techo");
  return roles;
}

export function forecastTone(text: string | null | undefined): string {
  if (!text) return "text-faint";
  if (text.startsWith("+")) return "text-mint";
  if (text.startsWith("-")) return "text-coral";
  return "text-muted";
}

export function ForecastPct({ value, className = "" }: { value: string | null | undefined; className?: string }) {
  if (!value) return null;
  return (
    <span className={`metric-value ${forecastTone(value)} ${className}`} title="Previsión de valor a 7 días">
      {value}
    </span>
  );
}

export function warLabel(value: number): string {
  const text = Math.abs(value).toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `-${text} pts sin él`;
}

export function WarChip({ value }: { value: number | null | undefined }) {
  if (typeof value !== "number" || Number.isNaN(value) || value <= 0) return null;
  const hot = value > 1.5;
  return (
    <span
      className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-semibold tracking-tight ${
        hot ? "bg-[color:var(--coral-soft)] text-coral" : "bg-white/5 text-muted-strong"
      }`}
      title="Puntos que pierde el once si lo vendes hoy"
    >
      {warLabel(value)}
    </span>
  );
}

function ShieldIcon() {
  return (
    <svg viewBox="0 0 16 16" className="h-3 w-3" aria-hidden="true">
      <path
        d="M8 1.4 13 3.2v4.2c0 3.1-2.1 5.4-5 6.8-2.9-1.4-5-3.7-5-6.8V3.2L8 1.4Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function BoltIcon() {
  return (
    <svg viewBox="0 0 16 16" className="h-3 w-3" aria-hidden="true">
      <path d="M9.2 1.2 3.4 9h4.1l-.8 5.8 6-7.8H8.6l.6-5.8Z" fill="currentColor" />
    </svg>
  );
}

export function CaptainMarks({ roles, compact = false }: { roles: CaptainRole[]; compact?: boolean }) {
  if (!roles.length) return null;
  return (
    <>
      {roles.map((role) => (
        <CaptainBadge key={role} role={role} compact={compact} />
      ))}
    </>
  );
}

export function CaptainBadge({ role, compact = false }: { role: CaptainRole; compact?: boolean }) {
  const seguro = role === "seguro";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full font-semibold ${
        compact ? "p-0.5" : "px-1.5 py-0.5 text-[10px]"
      } ${seguro ? "bg-[rgba(2,151,222,0.15)] text-[#0297DE]" : "bg-[rgba(252,115,77,0.15)] text-[#FC734D]"}`}
      title={seguro ? "Capitán seguro" : "Capitán explosivo"}
    >
      {seguro ? <ShieldIcon /> : <BoltIcon />}
      {compact ? <span className="sr-only">{seguro ? "Capitán seguro" : "Capitán explosivo"}</span> : seguro ? "Seguro" : "Techo"}
    </span>
  );
}

const ACTION_TONE: Record<string, string> = {
  PUJA: "border border-[#0297DE] bg-[rgba(2,151,222,0.15)] text-[#0297DE]",
  BUSCA: "border border-dashed border-[#67C6F5] bg-[rgba(2,151,222,0.08)] text-[#67C6F5]",
  VENDE: "border border-[#FC734D] bg-[rgba(252,115,77,0.15)] text-[#FC734D]",
  CLAUSULAZO: "border border-[#FC734D] bg-[rgba(252,115,77,0.15)] text-[#FC734D]",
};

function verdictTone(verdict: string | null | undefined): string {
  if (verdict === "Hazlo ya") return "bg-[color:var(--mint-soft)] text-mint";
  if (verdict === "Recomendable") return "bg-[color:var(--gold-soft)] text-gold";
  return "bg-white/5 text-muted";
}

function gainLabel(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "s/d";
  const text = value.toLocaleString("es-ES", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return `${value > 0 ? "+" : ""}${text} PTS/J`;
}

export function SigningPlanCard({ plan }: { plan: PlanFichajes | null | undefined }) {
  const acciones = Array.isArray(plan?.acciones) ? plan.acciones : [];
  const veredicto = plan?.veredicto || "Opcional";
  const nota = typeof plan?.nota === "number" ? plan.nota : 0;
  return (
    <article className="rounded-2xl border border-[color:var(--line)] bg-[color:var(--surface-strong)] p-4 md:p-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="eyebrow">Motor</p>
          <h2 className="section-title mt-1">Tu plan de fichajes</h2>
        </div>
        <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${verdictTone(veredicto)}`}>{veredicto}</span>
      </div>
      <div className="mt-4 grid grid-cols-3 gap-2">
        <div>
          <p className="metric-label">Gana el once</p>
          <p className={`metric-value mt-1 text-lg ${(plan?.mejora_puntos_jornada ?? 0) > 0 ? "text-mint" : "text-muted"}`}>
            {gainLabel(plan?.mejora_puntos_jornada)}
          </p>
        </div>
        <div>
          <p className="metric-label">Nota</p>
          <p className="metric-value mt-1 text-lg text-gold">{nota}/10</p>
        </div>
        <div>
          <p className="metric-label">Saldo final</p>
          <p className="metric-value mt-1 text-lg text-ink">{eur(plan?.saldo_al_final)}</p>
        </div>
      </div>
      {acciones.length ? (
        <ul className="mt-4 divide-y divide-[color:var(--line)]">
          {acciones.map((accion, index) => (
            <PlanRow key={`${accion.tipo}-${accion.player_id || accion.nombre}-${index}`} accion={accion} />
          ))}
        </ul>
      ) : (
        <p className="mt-4 text-sm text-muted">Hoy el mercado no mejora el once. No hay operaciones que merezcan la caja.</p>
      )}
    </article>
  );
}

function PlanRow({ accion }: { accion: PlanFichajeAccion }) {
  const tipo = accion.tipo || "PUJA";
  const momento = accion.momento === "hoy" ? "hoy" : "luego";
  return (
    <li className="flex items-start justify-between gap-3 py-2.5">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold tracking-wide ${ACTION_TONE[tipo] || "bg-white/5 text-muted"}`}>
            {tipo}
          </span>
          <span className="truncate text-sm font-medium text-ink">{accion.nombre || "Jugador"}</span>
        </div>
        <p className="mt-1 text-[11px] leading-4 text-muted">
          {accion.posicion ? `${accion.posicion}` : ""}
          {typeof accion.jornada === "number" ? ` · ${accion.jornada.toLocaleString("es-ES", { maximumFractionDigits: 1 })} pts` : ""}
          {typeof accion.euros === "number" ? ` · ${eurShort(accion.euros)}` : ""}
        </p>
      </div>
      <span className={`shrink-0 text-[11px] font-semibold uppercase tracking-[0.08em] ${momento === "hoy" ? "text-gold" : "text-faint"}`}>
        {momento}
      </span>
    </li>
  );
}

export function BidTrio({ player }: { player: Player }) {
  const rows: Array<[string, number | null | undefined]> = [
    ["Recomendada", player.puja_recomendada],
    ["Smart (vs Rivales)", player.puja_smart],
    ["Máxima", player.puja_maxima],
  ];
  if (!rows.some((row) => typeof row[1] === "number")) return null;
  return (
    <dl className="mt-1.5 grid grid-cols-3 gap-1.5">
      {rows.map(([label, value]) => (
        <div key={label} className="rounded-lg bg-black/25 px-1.5 py-1">
          <dt className="text-[9px] uppercase tracking-[0.06em] text-faint">{label}</dt>
          <dd className="metric-value text-[11px] text-ink">{typeof value === "number" ? eurShort(value) : "s/d"}</dd>
        </div>
      ))}
    </dl>
  );
}

export function ForcedSaleBadge() {
  return (
    <span className="inline-flex items-center rounded-full bg-[color:var(--coral-soft)] px-1.5 py-0.5 text-[10px] font-semibold text-coral">
      Venta obligada por deuda
    </span>
  );
}

export function DebtBanner() {
  return (
    <p className="mt-1.5 text-[11px] font-medium leading-4 text-coral">
      Saldo negativo: tiene que vender antes del viernes para que la jornada puntúe.
    </p>
  );
}
