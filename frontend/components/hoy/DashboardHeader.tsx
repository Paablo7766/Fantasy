import type { DashboardData } from "@/types/engine";

type StatColumnProps = {
  label: string;
  value: string;
};

function StatColumn({ label, value }: StatColumnProps) {
  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <span className="text-[10px] font-semibold tracking-[0.14em] text-[#8d97aa]">{label}</span>
      <span className="mt-1 truncate text-[22px] font-semibold leading-none tracking-[-0.03em] text-white">{value}</span>
    </div>
  );
}

type DashboardHeaderProps = {
  dashboard: DashboardData;
  leagueName?: string | null;
  age?: string | null;
  refreshing?: boolean;
  onRefresh?: () => void;
};

export function DashboardHeader({ dashboard, leagueName, age, refreshing, onRefresh }: DashboardHeaderProps) {
  return (
    <header>
      {leagueName ? (
        <p className="truncate text-[11px] font-semibold uppercase tracking-[0.14em] text-[#8d97aa]">{leagueName}</p>
      ) : null}
      <div className="mt-1 flex items-center justify-between gap-3">
        <h2 className="text-[34px] font-semibold leading-none tracking-[-0.04em] text-white">Hoy</h2>
        {onRefresh ? (
          <button type="button" onClick={onRefresh} disabled={refreshing} className="rec-refresh">
            <svg viewBox="0 0 16 16" className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
              <path d="M13 8a5 5 0 1 1-1.2-3.2" strokeLinecap="round" />
              <path d="M13 2.8V5.4H10.4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            {refreshing ? "Actualizando" : "Actualizar"}
          </button>
        ) : null}
      </div>
      <div className="mt-4 grid grid-cols-4 gap-2">
        <StatColumn label="SALDO" value={dashboard.balance} />
        <StatColumn label="POSICIÓN" value={dashboard.position} />
        <StatColumn label="PUNTOS" value={Number.isFinite(dashboard.points) ? String(dashboard.points) : "—"} />
        <StatColumn label="JORNADA" value={dashboard.gameweek} />
      </div>
      <p className="mt-3 text-[12px] text-[#8d97aa]">{age ? `Datos de LaLiga ${age}` : "Sin foto de LaLiga"}</p>
    </header>
  );
}
