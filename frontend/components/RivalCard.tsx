import type { Rival } from "@/types/engine";

type RivalCardProps = Rival & {
  isSelf?: boolean;
};

function initialFromName(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "?";
  return trimmed.charAt(0).toUpperCase();
}

export function RivalCard({
  rank,
  name,
  points,
  maxBid,
  squadValue,
  isSelf = false,
}: RivalCardProps) {
  return (
    <article
      className={`mb-2 flex items-center justify-between rounded-xl border bg-gray-800/40 p-4 ${
        isSelf ? "border-emerald-500/30" : "border-gray-700/50"
      }`}
    >
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <span className="w-8 text-xl font-bold text-gray-400">{rank}</span>
        <div
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gray-700 text-sm font-bold text-white"
          aria-hidden
        >
          {initialFromName(name)}
        </div>
        <div className="min-w-0">
          <h3 className="truncate font-bold text-white">{name}</h3>
          <p className="text-sm text-emerald-400">{points} pts</p>
        </div>
      </div>

      <div className="ml-3 shrink-0 text-right">
        <p className="text-[10px] text-gray-400">Valor: {squadValue}</p>
        <span className="mt-1 inline-block rounded border border-rose-800/50 bg-rose-900/30 px-2 py-0.5 text-xs font-bold text-rose-400">
          Tope: {maxBid}
        </span>
      </div>
    </article>
  );
}
