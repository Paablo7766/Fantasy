import type { DashboardData } from "@/types/engine";

type StatColumnProps = {
  label: string;
  value: string;
};

function StatColumn({ label, value }: StatColumnProps) {
  return (
    <div className="flex min-w-0 flex-1 flex-col items-center text-center">
      <span className="text-xs uppercase tracking-wide text-gray-400">{label}</span>
      <span className="text-xl font-bold text-white">{value}</span>
    </div>
  );
}

type DashboardHeaderProps = {
  dashboard: DashboardData;
};

export function DashboardHeader({ dashboard }: DashboardHeaderProps) {
  return (
    <div className="grid grid-cols-4 gap-2 rounded-xl border border-gray-700/50 bg-gray-800/40 p-4 backdrop-blur">
      <StatColumn label="Saldo" value={dashboard.balance} />
      <StatColumn label="Posición" value={dashboard.position} />
      <StatColumn label="Puntos" value={String(dashboard.points)} />
      <StatColumn label="Jornada" value={dashboard.gameweek} />
    </div>
  );
}
