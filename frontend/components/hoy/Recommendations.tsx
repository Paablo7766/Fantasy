"use client";

import { useMemo, useState } from "react";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { points } from "@/lib/format";
import {
  boardMoney,
  buildRecommendations,
  type RecCard,
  type RecommendationInput,
  type WindowCard,
} from "@/lib/recommendations";

function ClockIcon() {
  return (
    <svg viewBox="0 0 16 16" className="mt-px h-3.5 w-3.5 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
      <circle cx="8" cy="8" r="5.2" />
      <path d="M8 5.2V8l1.8 1.2" strokeLinecap="round" />
    </svg>
  );
}

function LockIcon() {
  return (
    <svg viewBox="0 0 16 16" className="mt-px h-3.5 w-3.5 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
      <rect x="3.4" y="7" width="9.2" height="6.2" rx="1.2" />
      <path d="M5.4 7V5.4a2.6 2.6 0 0 1 5.2 0V7" strokeLinecap="round" />
    </svg>
  );
}

function MysteryMark() {
  return (
    <span className="rec-mystery" aria-hidden>
      <span className="text-[15px] font-semibold text-[#9ec8ff]">?</span>
      <span className="rec-mystery__badge">
        <svg viewBox="0 0 16 16" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="1.8">
          <circle cx="7" cy="7" r="3.2" />
          <path d="M9.5 9.5 12 12" strokeLinecap="round" />
        </svg>
      </span>
    </span>
  );
}

function Face({ card }: { card: RecCard }) {
  if (card.mystery) return <MysteryMark />;
  const badge =
    card.tone === "bid" ? "rec-face__badge rec-face__badge--bid" : card.tone === "sell-now" || card.tone === "sell-later" ? "rec-face__badge rec-face__badge--sell" : null;
  return (
    <span className="relative shrink-0">
      <PlayerAvatar player={{ name: card.playerName, image_url: card.imageUrl }} size="sm" className="!h-11 !w-11 !text-[11px]" />
      {badge ? (
        <span className={badge} aria-hidden>
          {card.tone === "bid" ? "+" : "–"}
        </span>
      ) : null}
    </span>
  );
}

function titleClass(card: RecCard): string {
  if (card.tone === "search") return "rec-title rec-title--search";
  if (card.tone === "sell-now" || card.tone === "sell-later") return "rec-title rec-title--sell";
  if (card.tone === "offer" || card.tone === "watch") return "rec-title rec-title--offer";
  return "rec-title";
}

function ActionRow({ card }: { card: RecCard }) {
  return (
    <article className="rec-card">
      <Face card={card} />
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-3">
          <h3 className={titleClass(card)}>{card.title}</h3>
          {card.amount ? <p className="rec-amount">{card.amount}</p> : null}
        </div>
        {card.detail ? <p className="rec-detail">{card.detail}</p> : null}
        {card.timing ? (
          <p className="rec-meta">
            <ClockIcon />
            <span>{card.timing}</span>
          </p>
        ) : null}
        {card.fallback ? (
          <p className="rec-meta rec-meta--lock">
            <LockIcon />
            <span>{card.fallback}</span>
          </p>
        ) : null}
      </div>
    </article>
  );
}

function AdviceRow({ card, onHide }: { card: RecCard; onHide: (id: string) => void }) {
  return (
    <article className="rec-offer">
      <div className="flex items-start gap-3">
        <PlayerAvatar player={{ name: card.playerName, image_url: card.imageUrl }} size="sm" className="!h-11 !w-11" />
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-semibold tracking-wide text-[#e8c98a]">OJO · {card.playerName}</p>
          <h3 className="rec-title rec-title--offer mt-0.5">{card.title}</h3>
          {card.badge ? (
            <p className="mt-1.5 flex items-center gap-1.5 text-[10px] font-bold tracking-[0.14em] text-[#3ee0a0]">
              <span className="rec-bars" aria-hidden>
                <i />
                <i />
                <i />
              </span>
              {card.badge}
            </p>
          ) : null}
        </div>
      </div>
      {card.explain ? <p className="rec-detail mt-3">{card.explain}</p> : null}
      <div className="mt-3 flex gap-2">
        <button type="button" className="rec-btn" onClick={() => onHide(card.id)}>
          Hecho
        </button>
        <button type="button" className="rec-btn rec-btn--ghost" onClick={() => onHide(card.id)}>
          Descartar
        </button>
      </div>
    </article>
  );
}

function reachCopy(row: WindowCard): { text: string; className: string } | null {
  if (row.reach === "llega") return { text: "te llega", className: "text-[#e8c98a]" };
  if (row.reach === "falta" && row.shortfall) return { text: `te faltan ${row.shortfall}`, className: "text-[#ff8d7c]" };
  if (row.reach === "sin-caja") return { text: "sin caja para comparar", className: "text-[#9aa3b5]" };
  return null;
}

function WindowRow({ row }: { row: WindowCard }) {
  const reach = reachCopy(row);
  return (
    <article className="rec-card">
      <span className="relative shrink-0">
        <PlayerAvatar player={{ name: row.name, image_url: row.imageUrl }} size="sm" className="!h-11 !w-11" />
        {row.gain ? (
          <span className="rec-face__badge rec-face__badge--bid" aria-hidden>
            <svg viewBox="0 0 16 16" className="h-3 w-3" fill="currentColor">
              <path d="M9 2 4 9h3l-1 5 6-8H9l1-4Z" />
            </svg>
          </span>
        ) : null}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-3">
          <h3 className="rec-title">
            {row.name}
            {row.amount ? <span className="ml-2 text-[13px] font-semibold text-white/80">{row.amount}</span> : null}
          </h3>
        </div>
        <p className="rec-detail">
          {[row.position, row.gain, row.manager ? `de ${row.manager}` : null].filter(Boolean).join(" · ")}
          {row.note ? <span className="text-[#e8c98a]"> · {row.note}</span> : null}
        </p>
        <p className="rec-meta">
          <ClockIcon />
          <span>{row.when}</span>
          {reach ? <span className={reach.className}>{reach.text}</span> : null}
        </p>
      </div>
    </article>
  );
}

function Lane({ label, icon, cards }: { label: string; icon: "hoy" | "espera"; cards: RecCard[] }) {
  if (cards.length === 0) return null;
  return (
    <section className="mt-4">
      <p className="rec-lane">
        {icon === "hoy" ? (
          <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 text-[#3ee0a0]" fill="currentColor" aria-hidden>
            <path d="M9 1 3.5 9H8l-1 6 6.5-9H9l1-5Z" />
          </svg>
        ) : (
          <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 text-[#9ec8ff]" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
            <path d="M4 2.5h8M5 2.5c0 3 3 4 3 5.5S5 11 5 13.5M11 2.5c0 3-3 4-3 5.5s3 3 3 5.5M4 13.5h8" strokeLinecap="round" />
          </svg>
        )}
        {label}
      </p>
      <div className="mt-1">
        {cards.map((card) => (
          <ActionRow key={card.id} card={card} />
        ))}
      </div>
    </section>
  );
}

export function Recommendations({
  plan,
  optimize,
  trends,
  squads,
  loading,
}: RecommendationInput & { loading: boolean }) {
  const board = useMemo(
    () => buildRecommendations({ plan, optimize, trends, squads }),
    [plan, optimize, trends, squads],
  );
  const [hidden, setHidden] = useState<string[]>([]);

  const hide = (id: string) => {
    setHidden((current) => (current.includes(id) ? current : [...current, id]));
  };

  const offers = board.offers.filter((card) => !hidden.includes(card.id));
  const watches = board.watches.filter((card) => !hidden.includes(card.id));
  const advice = [...offers, ...watches];
  const delta = board.pointsDelta;
  const value = board.valueDelta;
  const from = board.savedPoints;
  const to = board.recommendedPoints;

  if (loading && !plan && !trends) {
    return <p className="mt-6 text-sm text-[#9aa3b5]">Leyendo la pizarra…</p>;
  }

  return (
    <div className="mt-5">
      <div className="flex items-end justify-between gap-3">
        <h2 className="text-[15px] font-bold tracking-[0.04em] text-white">PLAN DE FICHAJES</h2>
        <p className="text-[11px] text-[#8d97aa]">Con el mercado de hoy</p>
      </div>

      <p className="rec-status">{board.status}</p>
      <p className="mt-3 text-[13.5px] leading-5 text-[#d7deea]">{board.narrative}</p>

      {board.impactTitle && delta !== null ? (
        <div className="rec-impact">
          <div>
            <p className="text-[15px] font-semibold text-white">{board.impactTitle}</p>
            <p className="mt-0.5 text-[10px] font-semibold tracking-[0.14em] text-[#8d97aa]">QUÉ HACE EL PLAN</p>
          </div>
          <div className="text-right">
            <p className={`text-[22px] font-semibold leading-none ${delta > 0 ? "text-[#3ee0a0]" : "text-[#ff8d7c]"}`}>
              {delta > 0 ? "+" : "−"}
              {points(Math.abs(delta))}
            </p>
            <p className="mt-1 text-[10px] font-semibold tracking-[0.12em] text-[#8d97aa]">PTS/JORNADA</p>
            {value !== null ? (
              <p className="mt-1 text-[10px] font-semibold tracking-[0.08em] text-[#ff8d7c]">
                {boardMoney(value)} DE VALOR
              </p>
            ) : null}
          </div>
        </div>
      ) : null}

      <Lane label="HOY" icon="hoy" cards={board.hoy} />
      <Lane label="ESPERA" icon="espera" cards={board.espera} />

      {advice.length > 0 ? (
        <section className="mt-6">
          <p className="text-[10px] font-bold tracking-[0.16em] text-[#e8c98a]">RECOMENDABLE</p>
          <div className="mt-2 flex flex-col gap-3">
            {advice.map((card) => (
              <AdviceRow key={card.id} card={card} onHide={hide} />
            ))}
          </div>
        </section>
      ) : null}

      {board.windows.length > 0 ? (
        <section className="mt-6">
          <p className="text-[13px] leading-5 text-[#9aa3b5]">
            De otros místeres, en los puestos que te hacen falta o que mejoran tu once. Se pueden pagar cuando abra la cláusula.
          </p>
          <div className="mt-2">
            {board.windows.map((row) => (
              <WindowRow key={row.id} row={row} />
            ))}
          </div>
        </section>
      ) : null}

      {from !== null || to !== null ? (
        <p className="rec-footer">
          <svg viewBox="0 0 16 16" className="h-4 w-4 text-[#8d97aa]" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden>
            <path d="M3 10.5 8 4l5 6.5" strokeLinejoin="round" />
            <path d="M5 12.5h6" strokeLinecap="round" />
          </svg>
          <span>
            Tu once para la jornada:{" "}
            <strong className="font-semibold text-white">
              {from !== null ? points(from) : "s/d"}
              {to !== null ? ` → ${points(to)} pts` : " pts"}
            </strong>
          </span>
        </p>
      ) : null}
    </div>
  );
}
