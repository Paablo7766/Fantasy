import type { Action } from "@/types/engine";

const accentByType: Record<Action["type"], string> = {
  buy: "text-emerald-400",
  sell: "text-rose-400",
  wait: "text-blue-400",
};

const actionTextByType: Record<Action["type"], string> = {
  buy: "Comprar",
  sell: "Vender",
  wait: "Esperar",
};

type ActionCardProps = Action & { actionText?: string };

export function ActionCard({ type, title, subtitle, value, actionText }: ActionCardProps) {
  const label = actionText ?? actionTextByType[type];
  const accent = accentByType[type];

  return (
    <div className="mb-3 rounded-xl border border-gray-700/50 bg-gray-800/40 p-4 backdrop-blur">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className={`font-semibold ${accent}`}>{title}</p>
          <p className="mt-1 text-sm text-gray-400">{subtitle}</p>
        </div>
        <p className="shrink-0 text-lg font-bold text-white">{value}</p>
      </div>
      <p className={`mt-3 text-sm font-medium ${accent}`}>{label}</p>
    </div>
  );
}
