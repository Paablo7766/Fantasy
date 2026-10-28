"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { buildStrategyViews, type MoveTone, type StrategyMove, type StrategyView } from "@/lib/signingBoard";
import type { NeedsPayload, OptimizePayload, PlanPayload, SquadsPayload, TrendsPayload } from "@/lib/types";

const TONE: Record<MoveTone, string> = {
  up: "desk-fig--up",
  down: "desk-fig--down",
  flat: "desk-fig--flat",
  none: "",
};

export function SigningBoard({
  plan,
  optimize,
  squads,
  trends,
  needs,
  loading,
  refreshing,
  photoLine,
}: {
  plan: PlanPayload | null;
  optimize: OptimizePayload | null;
  squads: SquadsPayload | null;
  trends: TrendsPayload | null;
  needs: NeedsPayload | null;
  loading: boolean;
  refreshing: boolean;
  photoLine: string;
}) {
  const views = useMemo(
    () => buildStrategyViews(plan, optimize, squads, trends, needs),
    [plan, optimize, squads, trends, needs],
  );
  const [desk, setDesk] = useState<StrategyView["id"]>("estrategia");
  const view = views.find((item) => item.id === desk) ?? views[0];

  return (
    <div className="desk">
      <div className="desk-switch" role="tablist" aria-label="Mesas de recomendación">
        {views.map((item) => {
          const count = item.groups.reduce((total, group) => total + group.moves.length, 0);
          const active = item.id === view.id;
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={active}
              className={active ? "desk-switch__btn desk-switch__btn--on" : "desk-switch__btn"}
              onClick={() => setDesk(item.id)}
            >
              {item.label}
              <span>{count}</span>
            </button>
          );
        })}
      </div>

      <header className="desk-hero">
        <div className="desk-hero__top">
          <p className="desk-kicker">{view.kicker}</p>
          {refreshing ? <p className="desk-photo">Actualizando</p> : null}
        </div>
        {loading && !plan ? (
          <div className="desk-skel" aria-hidden="true" />
        ) : (
          <>
            {view.headline ? <p className="desk-headline">{view.headline}</p> : null}
            {view.sentence ? <p className="desk-sentence">{view.sentence}</p> : null}
            {view.pointsMove || view.cashMove ? (
              <div className="desk-meters">
                {view.pointsMove ? <Meter label="Puntos" value={view.pointsMove} tone={view.pointsTone} /> : null}
                {view.cashMove ? <Meter label="Saldo" value={view.cashMove} tone={view.cashTone} /> : null}
              </div>
            ) : null}
            <p className="desk-photo">{photoLine}</p>
          </>
        )}
      </header>

      {loading && !plan ? null : view.groups.length ? (
        view.groups.map((group) => (
          <section key={group.id} className="desk-group" aria-labelledby={`desk-${view.id}-${group.id}`}>
            <h2 id={`desk-${view.id}-${group.id}`}>{group.label}</h2>
            <ul className="desk-list">
              {group.moves.map((move) => (
                <MoveCard key={move.id} move={move} />
              ))}
            </ul>
          </section>
        ))
      ) : (
        <p className="desk-empty">
          {view.id === "estrategia"
            ? "Con esta foto no hay un fichaje que suba los puntos del once. Actualiza o espera al mercado del día."
            : "Esta foto no deja un movimiento que mejore la estrategia."}
        </p>
      )}

      {view.id === "estrategia" && view.savedPoints && view.recommendedPoints ? (
        <footer className="desk-xi">
          <span>Once</span>
          <strong>
            {view.savedPoints}
            <span aria-hidden="true"> → </span>
            {view.recommendedPoints}
          </strong>
        </footer>
      ) : null}
    </div>
  );
}

function Meter({ label, value, tone }: { label: string; value: string; tone: MoveTone }) {
  return (
    <div className={`desk-meter ${TONE[tone]}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function MoveCard({ move }: { move: StrategyMove }) {
  return (
    <li className="desk-card">
      <div className="desk-card__main">
        {move.imageUrl ? (
          <PlayerAvatar player={{ name: move.title, image_url: move.imageUrl }} size="sm" />
        ) : (
          <span className="desk-card__mark" aria-hidden="true">
            {move.position ? move.position.slice(0, 3) : "·"}
          </span>
        )}
        <div className="min-w-0 flex-1">
          <p className="desk-card__verb">
            {move.verb}
            {move.position ? <span>{move.position}</span> : null}
          </p>
          <h3>{move.title}</h3>
          {move.detail ? <p className="desk-card__detail">{move.detail}</p> : null}
        </div>
        {move.cashLabel || move.pointsLabel ? (
          <div className="desk-card__figs">
            {move.pointsLabel ? <span className={TONE[move.pointsTone]}>{move.pointsLabel}</span> : null}
            {move.cashLabel ? <span className={TONE[move.cashTone]}>{move.cashLabel}</span> : null}
          </div>
        ) : null}
      </div>
      <Link href={move.href} className="desk-card__go">
        {move.guide}
      </Link>
    </li>
  );
}
