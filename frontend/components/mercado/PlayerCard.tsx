"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { AuctionV2Panel } from "@/components/AuctionV2Panel";
import { gradeColor } from "@/components/MarketGrade";
import { CompararConSugerido } from "@/components/comparador/ComparadorReal";
import { Disclosure, Face, TONE, money, parsePct, signedPct } from "@/components/equipo/ui";
import { ACTION_VERDICT, sourceLabel, winShare } from "@/components/mercado/shared";
import { bidStory } from "@/lib/bidStory";
import { playerName } from "@/lib/format";
import { actionReason, executableBid, isVetoed, marketAction } from "@/lib/marketAction";
import type { MarketDecision } from "@/lib/types";

type Match = { opponent: string; home: boolean | null; difficulty: string | null; pct: number | null; score: string | null };

const DIFF: Record<string, { label: string; color: string }> = {
  muy_facil: { label: "Muy fácil", color: TONE.green },
  very_easy: { label: "Muy fácil", color: TONE.green },
  facil: { label: "Fácil", color: "#4FD1A5" },
  easy: { label: "Fácil", color: "#4FD1A5" },
  media: { label: "Media", color: TONE.amber },
  medium: { label: "Media", color: TONE.amber },
  dificil: { label: "Difícil", color: "#FF9A5A" },
  hard: { label: "Difícil", color: "#FF9A5A" },
  muy_dificil: { label: "Muy difícil", color: TONE.red },
  very_hard: { label: "Muy difícil", color: TONE.red },
};

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function dec(value: number | null, digits = 1): string {
  return value === null ? "—" : value.toLocaleString("es-ES", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** Siguiente partido con la fuente propia y los de después con la de terceros. */
function upcoming(player: MarketDecision): Match[] {
  const out: Match[] = [];
  const fixture = player.fixture;
  if (fixture?.opponent) {
    out.push({
      opponent: fixture.opponent,
      home: fixture.is_home ?? null,
      difficulty: fixture.difficulty ?? null,
      pct: num(fixture.recommendation_pct),
      score: fixture.predicted_score ?? null,
    });
  }
  const rest = [...(player.own_calendar || []), ...(player.af_calendar || [])];
  for (const row of rest) {
    if (!row.opponent || out.some((match) => match.opponent === row.opponent)) continue;
    out.push({
      opponent: row.opponent,
      home: row.is_home ?? null,
      difficulty: row.difficulty ?? null,
      pct: num(row.recommendation_pct),
      score: row.predicted_score ?? null,
    });
  }
  return out.slice(0, 4);
}

function maxBid(player: MarketDecision): number | null {
  return num(player.financial_max_bid_eur) ?? num(player.puja_maxima) ?? num(player.max_bid) ?? num(player.aggressive_ceiling);
}

/** Anillo 0-10 con la nota de la app. */
function GradeRing({ note, size = 92 }: { note: number | null; size?: number }) {
  const color = note === null ? TONE.gray : gradeColor(note);
  const r = size / 2 - 6;
  const c = 2 * Math.PI * r;
  const share = note === null ? 0 : Math.max(0, Math.min(1, note / 10));
  return (
    <span className="relative inline-grid shrink-0 place-items-center" style={{ width: size, height: size }}>
      <svg viewBox={`0 0 ${size} ${size}`} className="absolute inset-0 -rotate-90" aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="6" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={`${c * share} ${c}`}
          style={{ filter: `drop-shadow(0 0 8px ${color}88)`, transition: "stroke-dasharray 600ms ease-out" }}
        />
      </svg>
      <span className="text-center">
        <span className="block text-[1.7rem] font-semibold leading-none tabular-nums text-white">{note === null ? "—" : dec(note)}</span>
        <span className="mt-0.5 block text-[10px] font-medium uppercase tracking-[0.14em] text-white/45">nota</span>
      </span>
    </span>
  );
}

function Panel({ title, meta, children }: { title: string; meta?: ReactNode; children: ReactNode }) {
  return (
    <section className="home-glass px-4 py-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-[12px] font-semibold uppercase tracking-[0.14em] text-white/50">{title}</p>
        {meta ? <span className="text-[12px] text-white/45">{meta}</span> : null}
      </div>
      {children}
    </section>
  );
}

function Stat({ label, value, tone, hint }: { label: string; value: string; tone?: string; hint?: string }) {
  return (
    <div className="min-w-0">
      <p className="text-[11.5px] text-white/45">{label}</p>
      <p className="mt-0.5 truncate text-[1.25rem] font-semibold leading-tight tabular-nums" style={{ color: tone || "#fff" }}>
        {value}
      </p>
      {hint ? <p className="mt-0.5 truncate text-[11px] text-white/40">{hint}</p> : null}
    </div>
  );
}

/** Escala valor → puja ideal → máxima, con las tres marcas sobre una barra. */
function BidScale({ value, ideal, max }: { value: number | null; ideal: number | null; max: number | null }) {
  const marks = [value, ideal, max].filter((item): item is number => item !== null);
  if (marks.length < 2) return null;
  const low = Math.min(...marks) * 0.97;
  const high = Math.max(...marks) * 1.02;
  const at = (amount: number) => `${((amount - low) / (high - low || 1)) * 100}%`;
  return (
    <div className="relative mt-4 h-10" aria-hidden="true">
      <span className="absolute inset-x-0 top-[0.9rem] h-1.5 rounded-full bg-white/[0.08]" />
      {ideal !== null && max !== null ? (
        <span
          className="absolute top-[0.9rem] h-1.5 rounded-full"
          style={{ left: at(Math.min(ideal, max)), right: `calc(100% - ${at(Math.max(ideal, max))})`, background: "linear-gradient(90deg,#10B981,#FF9A5A)" }}
        />
      ) : null}
      {[
        { amount: value, color: "rgba(255,255,255,0.7)", label: "valor" },
        { amount: ideal, color: TONE.green, label: "ideal" },
        { amount: max, color: "#FF9A5A", label: "máx." },
      ].map((mark) =>
        mark.amount === null ? null : (
          <span key={mark.label} className="absolute top-0 flex -translate-x-1/2 flex-col items-center" style={{ left: at(mark.amount) }}>
            <span className="h-[1.9rem] w-[3px] rounded-full" style={{ background: mark.color, boxShadow: `0 0 8px ${mark.color}` }} />
            <span className="mt-0.5 text-[10px] font-medium uppercase tracking-wide" style={{ color: mark.color }}>
              {mark.label}
            </span>
          </span>
        ),
      )}
    </div>
  );
}

/** Barras de puntos por jornada; la media se dibuja como línea. */
function WeekBars({ weeks, average }: { weeks: number[]; average: number | null }) {
  const shown = weeks.slice(-10);
  if (!shown.length) return <p className="text-[13px] text-white/45">Sin puntos de jornada en la foto.</p>;
  const top = Math.max(10, ...shown.map((value) => Math.abs(value)));
  const first = weeks.length - shown.length + 1;
  return (
    <div>
      <div className="relative flex h-28 items-end gap-1.5">
        {average !== null ? (
          <span className="absolute inset-x-0 border-t border-dashed border-white/25" style={{ bottom: `${(Math.max(0, average) / top) * 100}%` }}>
          </span>
        ) : null}
        {shown.map((value, index) => {
          const color = value >= 10 ? TONE.green : value >= 5 ? "#FF9A5A" : value > 0 ? TONE.amber : TONE.red;
          return (
            <span key={index} className="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1">
              <span className="text-[11px] font-semibold tabular-nums text-white/80">{dec(value, 0)}</span>
              <span
                className="w-full rounded-t-md"
                style={{ height: `${Math.max(4, (Math.max(0, value) / top) * 100)}%`, background: `linear-gradient(180deg, ${color}, ${color}55)` }}
              />
            </span>
          );
        })}
      </div>
      <div className="mt-1.5 flex gap-1.5">
        {shown.map((_, index) => (
          <span key={index} className="min-w-0 flex-1 text-center text-[10px] tabular-nums text-white/35">
            J{first + index}
          </span>
        ))}
      </div>
    </div>
  );
}

function Fixtures({ matches }: { matches: Match[] }) {
  if (!matches.length) return <p className="text-[13px] text-white/45">Sin calendario contrastado.</p>;
  return (
    <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {matches.map((match, index) => {
        const diff = (match.difficulty && DIFF[match.difficulty]) || { label: "s/d", color: TONE.gray };
        return (
          <li
            key={`${match.opponent}-${index}`}
            className="rounded-2xl px-3 py-2.5"
            style={{ background: `${diff.color}14`, boxShadow: `inset 0 0 0 1px ${diff.color}40` }}
          >
            <p className="text-[10.5px] font-medium uppercase tracking-wide text-white/40">
              {index === 0 ? "Próximo" : `+${index}`} · {match.home === true ? "casa" : match.home === false ? "fuera" : "—"}
            </p>
            <p className="mt-0.5 truncate text-[14px] font-semibold text-white">{match.opponent}</p>
            <p className="mt-0.5 text-[11.5px] font-medium" style={{ color: diff.color }}>
              {diff.label}
              {match.score ? <span className="text-white/40"> · {match.score}</span> : null}
            </p>
          </li>
        );
      })}
    </ul>
  );
}

/** Ficha completa de un jugador del mercado: cuánto pujar, qué rinde y por qué. */
export function PlayerCard({ player, photo, onClose }: { player: MarketDecision | null; photo?: string | null; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [comparing, setComparing] = useState<{ id: string; position?: string | null } | null>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (player && !dialog.open) dialog.showModal();
    if (!player && dialog.open) dialog.close();
  }, [player]);

  const body = (() => {
    if (!player) return null;
    const name = playerName(player);
    const story = bidStory(player);
    const action = marketAction(player);
    const verdict = ACTION_VERDICT[action];
    const ideal = executableBid(player);
    const max = isVetoed(player) ? null : maxBid(player);
    const value = num(player.market_value) ?? num(player.sale_price);
    const win = winShare(typeof player.smart_bid_success_pct === "number" ? player.smart_bid_success_pct : player.win_probability);
    const trend = parsePct(player.prevision_7d_pct);
    const in7 = num(player.valor_en_7d);
    const gain7 = in7 !== null && value !== null ? in7 - value : null;
    const xp = num(player.jornada_ev) ?? num(player.expected_points);
    const xp4 = num(player.xp_4_jornadas);
    const ceiling = num(player.own_ceiling_points) ?? num(player.af_ceiling_points);
    const titular = num(player.p_titular);
    const note = num(player.nota_mercado);
    const delta = num(player.points_delta);
    const weeks = Array.isArray(player.week_points) ? player.week_points : [];
    const average = num(player.average_points);
    const matches = upcoming(player);
    const accent = note === null ? TONE.gray : gradeColor(note);
    const bids = player.rival_bids || [];
    const reason = actionReason(player, story.motive) || story.headline;

    return (
      <div className="flex flex-col gap-4">
        <header
          className="relative overflow-hidden rounded-[1.75rem] px-5 pb-5 pt-5"
          style={{
            background: `radial-gradient(120% 90% at 85% 0%, ${accent}44 0%, transparent 60%), radial-gradient(90% 80% at 0% 0%, rgba(255,122,61,0.35), transparent 65%), linear-gradient(180deg,#1a0f0a,#0c0807)`,
            border: "1px solid rgba(255,255,255,0.09)",
          }}
        >
          <button
            type="button"
            onClick={onClose}
            aria-label="Cerrar"
            className="absolute right-4 top-4 grid h-9 w-9 place-items-center rounded-full bg-black/30 text-white/70 transition-colors hover:bg-black/50 hover:text-white"
          >
            <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
              <path d="M4 4l8 8M12 4l-8 8" strokeLinecap="round" />
            </svg>
          </button>
          <div className="flex items-center gap-4">
            <Face name={name} src={player.image_url || photo} size={76} ring={accent} />
            <div className="min-w-0 flex-1 pr-8">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-white/50">
                {[player.position, player.club].filter(Boolean).join(" · ")}
              </p>
              <h2 className="mt-1 line-clamp-2 text-[1.3rem] sm:text-[1.6rem] font-semibold leading-tight tracking-tight text-white">{name}</h2>
              <p className="mt-1 truncate text-[12.5px] text-white/55">{sourceLabel(player)}</p>
            </div>
          </div>
          <div className="mt-5 flex items-center gap-4">
            <GradeRing note={note} />
            <div className="min-w-0 flex-1">
              <span
                className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[12.5px] font-semibold"
                style={{ color: verdict.color, background: `${verdict.color}1f`, boxShadow: `inset 0 0 0 1px ${verdict.color}55` }}
              >
                <span className="h-1.5 w-1.5 rounded-full" style={{ background: verdict.color }} />
                {verdict.label}
              </span>
              {player.etiqueta_mercado ? (
                <p className="mt-2 text-[12px] font-semibold uppercase tracking-wider" style={{ color: accent }}>
                  {player.etiqueta_mercado}
                </p>
              ) : null}
              <p className="mt-1 line-clamp-3 text-[13.5px] leading-snug text-white/80">{player.frase_mercado || reason}</p>
            </div>
          </div>
        </header>

        <Panel title="La puja" meta={win !== null ? `${Math.round(win * 100)}% de ganarla` : undefined}>
          <div className="grid grid-cols-3 gap-3">
            <Stat label="Ideal" value={money(ideal)} tone={ideal !== null ? TONE.green : undefined} />
            <Stat label="Máxima" value={money(max)} tone="#FFC08A" />
            <Stat label="Valor hoy" value={money(value)} />
          </div>
          <BidScale value={value} ideal={ideal} max={max} />
          {win !== null ? (
            <span className="mt-3 block h-1.5 overflow-hidden rounded-full bg-white/[0.08]" aria-hidden="true">
              <span
                className="block h-full rounded-full"
                style={{ width: `${Math.round(win * 100)}%`, background: win >= 0.7 ? TONE.green : win >= 0.4 ? TONE.amber : TONE.red }}
              />
            </span>
          ) : null}
        </Panel>

        <div className="grid gap-4 sm:grid-cols-2">
          <Panel title="Valor en 7 días">
            <div className="flex items-center gap-3">
              <span
                className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl text-[1.4rem]"
                style={{ background: `${trend === null ? TONE.gray : trend >= 0 ? TONE.green : TONE.red}22`, color: trend === null ? TONE.gray : trend >= 0 ? TONE.green : TONE.red }}
                aria-hidden="true"
              >
                {trend === null ? "·" : trend >= 0 ? "↗" : "↘"}
              </span>
              <div className="min-w-0">
                <p className="text-[1.5rem] font-semibold leading-none tabular-nums" style={{ color: trend === null ? "#fff" : trend >= 0 ? TONE.green : TONE.red }}>
                  {trend === null ? "—" : signedPct(trend)}
                </p>
                <p className="mt-1 truncate text-[12px] text-white/50">
                  {gain7 !== null ? `${gain7 >= 0 ? "+" : ""}${money(gain7)} · ${money(in7)} previsto` : "Sin previsión"}
                </p>
              </div>
            </div>
          </Panel>

          <Panel title="Para tu once">
            {player.replaces?.name ? (
              <div>
                <p className="text-[1.5rem] font-semibold leading-none tabular-nums" style={{ color: delta !== null && delta > 0 ? TONE.green : TONE.gray }}>
                  {delta === null ? "—" : `${delta > 0 ? "+" : ""}${dec(delta)} pts`}
                </p>
                <p className="mt-1 truncate text-[12px] text-white/50">
                  por jornada si entra por {player.replaces.name}
                  {typeof player.replaces.points === "number" ? ` (${dec(player.replaces.points)})` : ""}
                </p>
              </div>
            ) : (
              <p className="text-[13px] leading-snug text-white/55">No mejora a ningún titular de tu once ahora mismo.</p>
            )}
          </Panel>
        </div>

        <Panel title="Puntos esperados">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Próxima jornada" value={dec(xp)} tone="#FFC08A" />
            <Stat label="Próximas 4" value={dec(xp4)} />
            <Stat label="Techo" value={dec(ceiling)} />
            <Stat label="Titular" value={titular === null ? "—" : `${Math.round(titular * 100)}%`} tone={titular === null ? undefined : titular >= 0.8 ? TONE.green : titular >= 0.5 ? TONE.amber : TONE.red} />
          </div>
        </Panel>

        <Panel title="Últimas jornadas" meta={average !== null ? `media ${dec(average)}` : undefined}>
          <WeekBars weeks={weeks} average={average} />
          {player.af_form?.signals?.length ? (
            <ul className="mt-3 flex flex-wrap gap-1.5">
              {player.af_form.signals.slice(0, 3).map((signal) => (
                <li key={signal} className="rounded-full bg-white/[0.06] px-2.5 py-1 text-[11.5px] text-white/65">
                  {signal}
                </li>
              ))}
            </ul>
          ) : null}
        </Panel>

        <Panel title="Próximos rivales">
          <Fixtures matches={matches} />
        </Panel>

        <Panel title="La compra">
          <ul className="flex flex-col gap-2.5 text-[13.5px]">
            <li className="flex justify-between gap-3">
              <span className="text-white/50">Vende</span>
              <span className="truncate text-right font-medium text-white">{sourceLabel(player)}</span>
            </li>
            <li className="flex justify-between gap-3">
              <span className="text-white/50">Puja más alta conocida</span>
              <span className="font-medium tabular-nums text-white">{money(player.leading_bid)}</span>
            </li>
            <li className="flex justify-between gap-3">
              <span className="text-white/50">Caja tras la puja</span>
              <span className="font-medium tabular-nums text-white">{money(player.cash_after_eur)}</span>
            </li>
            {player.listing_expires_at ? (
              <li className="flex justify-between gap-3">
                <span className="text-white/50">Cierra</span>
                <span className="font-medium tabular-nums text-white">
                  {new Date(player.listing_expires_at).toLocaleString("es-ES", { weekday: "short", hour: "2-digit", minute: "2-digit" })}
                </span>
              </li>
            ) : null}
          </ul>
          {bids.length ? (
            <ul className="mt-3 border-t border-white/[0.06] pt-2">
              {bids.map((row) => (
                <li key={`${row.team_id}-${row.amount}`} className="flex justify-between py-1.5 text-[13.5px]">
                  <span className={row.own ? "font-medium text-[#FFC08A]" : "text-white/75"}>{row.own ? "Tú" : row.manager_name || "Rival"}</span>
                  <span className="font-semibold tabular-nums text-white">{money(row.amount)}</span>
                </li>
              ))}
            </ul>
          ) : null}
          <p className="mt-3 rounded-2xl px-3 py-2.5 text-[13.5px] leading-snug text-white" style={{ background: "rgba(255,154,90,0.1)", border: "1px solid rgba(255,154,90,0.2)" }}>
            {story.action}
          </p>
        </Panel>

        <Disclosure title="Análisis completo">
          <div className="flex flex-col gap-4">
            <p className="text-[13.5px] leading-relaxed text-white/75">{reason}</p>
            <AuctionV2Panel player={player} variant="full" />
            {story.reasons.length ? (
              <ul className="flex flex-col gap-2">
                {story.reasons.map((item) => (
                  <li key={item} className="flex gap-2.5 text-[13px] leading-relaxed text-white/70">
                    <span className="mt-[0.55rem] h-1 w-1 shrink-0 rounded-full bg-[#FF9A5A]" aria-hidden="true" />
                    {item}
                  </li>
                ))}
              </ul>
            ) : null}
            {story.theory ? <p className="text-[13px] leading-relaxed text-white/60">{story.theory}</p> : null}
            {story.gaps.length ? <p className="text-[12px] leading-relaxed text-white/40">{story.gaps.join(" ")}</p> : null}
          </div>
        </Disclosure>

        <button
          type="button"
          onClick={() => {
            if (player.player_id) setComparing({ id: String(player.player_id), position: player.position });
            onClose();
          }}
          className="h-12 rounded-full border border-[#0297DE]/40 bg-[#0297DE]/10 text-[14px] font-semibold text-[#7fd4ff] transition-colors hover:bg-[#0297DE]/20"
        >
          Comparar con otro jugador
        </button>
      </div>
    );
  })();

  return (
    <>
      <dialog
        ref={ref}
        className="mk-card"
        onClose={onClose}
        onClick={(event) => {
          if (event.target === ref.current) onClose();
        }}
      >
        <div className="mk-card__body">{body}</div>
      </dialog>
      {comparing ? (
        <CompararConSugerido objetivoId={comparing.id} posicion={comparing.position} onClose={() => setComparing(null)} />
      ) : null}
    </>
  );
}
