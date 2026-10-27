import type { MarketListing } from "@/types/engine";

export function MarketCard({
  name,
  position,
  team,
  probability,
  price,
  trend,
  recommendedBid,
  analysis,
}: MarketListing) {
  const trendClass = trend.isUp ? "text-emerald-400" : "text-rose-400";
  const trendArrow = trend.isUp ? "▲" : "▼";
  const decisionClass = analysis.isPositive
    ? "bg-emerald-900/50 text-emerald-400"
    : "bg-gray-700 text-gray-300";

  return (
    <article className="mb-3 rounded-xl border border-gray-700/50 bg-gray-800/40 p-4 backdrop-blur">
      <div className="mb-3 flex items-start gap-3">
        <div
          className="h-10 w-10 shrink-0 rounded-full bg-gray-700"
          aria-hidden
        />
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-lg font-bold text-white">{name}</h3>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <span className="rounded bg-blue-600/80 px-1.5 py-0.5 text-[10px] text-white">
              {position}
            </span>
            <span className="text-xs text-gray-400">{team}</span>
            <span className="text-xs font-medium text-emerald-400">
              {probability}
            </span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 items-end gap-3">
        <div>
          <p className="text-xl font-bold text-white">{price}</p>
          <p className={`mt-0.5 text-xs ${trendClass}`}>
            {trendArrow} {trend.text}
          </p>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <span className="rounded-full border border-blue-500 px-2 py-1 text-[10px] text-blue-400">
            Puja recomendada {recommendedBid}
          </span>
          <span className={`rounded-full px-2 py-1 text-[10px] ${decisionClass}`}>
            {analysis.text}
          </span>
        </div>
      </div>
    </article>
  );
}
