import type { SquadPlayer } from "@/types/engine";

function MatchIndicator({
  matchStatus,
  matchTime,
}: Pick<SquadPlayer, "matchStatus" | "matchTime">) {
  if (matchStatus === "playing") {
    return (
      <span className="animate-pulse text-xs font-medium text-emerald-400">
        Jugando {matchTime}
      </span>
    );
  }
  if (matchStatus === "finished") {
    return <span className="text-xs text-gray-500">Finalizado</span>;
  }
  return <span className="text-xs text-gray-500">{matchTime}</span>;
}

export function SquadCard({
  name,
  position,
  team,
  pointsExpected,
  isStarter,
  matchStatus,
  matchTime,
}: SquadPlayer) {
  const pointsLabel =
    pointsExpected % 1 === 0
      ? String(pointsExpected)
      : pointsExpected.toFixed(1).replace(".", ",");

  return (
    <article
      className={`mb-2 flex items-center rounded-xl border bg-gray-800/40 p-3 ${
        isStarter
          ? "border-gray-700/50"
          : "border-rose-900/40 opacity-60"
      }`}
    >
      <div
        className="mr-3 h-10 w-10 shrink-0 rounded-full bg-gray-700"
        aria-hidden
      />

      <div className="min-w-0 flex-1">
        <h3 className="truncate font-semibold text-white">{name}</h3>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-gray-400">
          <span className="rounded bg-blue-600/80 px-1.5 py-0.5 text-[10px] text-white">
            {position}
          </span>
          <span>{team}</span>
        </div>
        <div className="mt-1">
          <MatchIndicator matchStatus={matchStatus} matchTime={matchTime} />
        </div>
        {!isStarter ? (
          <span className="mt-0.5 inline-block text-[10px] font-medium uppercase tracking-wide text-rose-400/80">
            Banquillo
          </span>
        ) : null}
      </div>

      <div className="ml-2 shrink-0 text-right">
        <span className="text-lg font-bold text-emerald-400">{pointsLabel}</span>
        <p className="text-[10px] text-gray-500">pts Opta</p>
      </div>
    </article>
  );
}
