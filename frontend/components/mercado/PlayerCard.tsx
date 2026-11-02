"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { gradeColor } from "@/components/mercado/MarketGrade";
import { CompararConSugerido } from "@/components/comparador/ComparadorReal";
import { Face, TONE, money, parsePct, signedPct } from "@/components/ui/kit";
import { ACTION_VERDICT, sourceLabel, winShare } from "@/components/mercado/shared";
import { bidStory } from "@/lib/mercado/bidStory";
import { MONTHS, playerName } from "@/lib/core/format";
import { actionReason, executableBid, isVetoed, marketAction } from "@/lib/mercado/marketAction";
import type { MarketDecision } from "@/lib/types";

type Match = { opponent: string; home: boolean | null; difficulty: string | null };

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

function dayLabel(day: string): string {
  const [, month, date] = day.split("-").map(Number);
  return month && date ? `${date} ${MONTHS[month - 1]}` : day;
}

/** Siguiente partido con la fuente propia y los de después con la de terceros. */
function upcoming(player: MarketDecision): Match[] {
  const out: Match[] = [];
  const fixture = player.fixture;
  if (fixture?.opponent) out.push({ opponent: fixture.opponent, home: fixture.is_home ?? null, difficulty: fixture.difficulty ?? null });
  for (const row of [...(player.own_calendar || []), ...(player.af_calendar || [])]) {
    if (!row.opponent || out.some((match) => match.opponent === row.opponent)) continue;
    out.push({ opponent: row.opponent, home: row.is_home ?? null, difficulty: row.difficulty ?? null });
  }
  return out.slice(0, 4);
}

function maxBid(player: MarketDecision): number | null {
  return num(player.financial_max_bid_eur) ?? num(player.puja_maxima) ?? num(player.max_bid) ?? num(player.aggressive_ceiling);
}

function GradeRing({ note, size = 76 }: { note: number | null; size?: number }) {
  const color = note === null ? TONE.gray : gradeColor(note);
  const r = size / 2 - 5;
  const c = 2 * Math.PI * r;
  const share = note === null ? 0 : Math.max(0, Math.min(1, note / 10));
  return (
    <span className="relative inline-grid shrink-0 place-items-center" style={{ width: size, height: size }}>
      <svg viewBox={`0 0 ${size} ${size}`} className="absolute inset-0 -rotate-90" aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="5" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth="5"
          strokeLinecap="round"
          strokeDasharray={`${c * share} ${c}`}
          style={{ filter: `drop-shadow(0 0 6px ${color}99)` }}
        />
      </svg>
      <span className="text-center">
        <span className="block text-[1.45rem] font-semibold leading-none tabular-nums text-white">{note === null ? "—" : dec(note)}</span>
        <span className="mt-0.5 block text-[9px] font-semibold uppercase tracking-[0.16em] text-white/40">nota</span>
      </span>
    </span>
  );
}

function Section({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="border-t border-white/[0.06] px-5 py-5">
      <div className="mb-3.5 flex items-baseline justify-between gap-3">
        <h3 className="text-[13px] font-semibold text-white/85">{title}</h3>
        {aside ? <span className="text-[12px] text-white/45">{aside}</span> : null}
      </div>
      {children}
    </section>
  );
}

function Metric({ label, value, tone, sub }: { label: string; value: string; tone?: string; sub?: string }) {
  return (
    <div className="min-w-0">
      <p className="text-[11px] font-medium text-white/40">{label}</p>
      <p className="mt-1 truncate text-[1.3rem] font-semibold leading-none tabular-nums" style={{ color: tone || "#fff" }}>
        {value}
      </p>
      {sub ? <p className="mt-1 truncate text-[11px] text-white/40">{sub}</p> : null}
    </div>
  );
}

/** Valor guardado día a día y, en discontinuo, la previsión a 7 días. */
function ValueChart({ history, today, forecast }: { history: { day: string; value: number }[]; today: number | null; forecast: number | null }) {
  const gradientId = useId();
  const series = [...history];
  if (today !== null && (!series.length || series.at(-1)!.value !== today)) series.push({ day: "hoy", value: today });
  if (!series.length) return <p className="text-[13px] text-white/45">Sin histórico de valor guardado.</p>;
  const values = [...series.map((point) => point.value), ...(forecast !== null ? [forecast] : [])];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = (max - min || max * 0.02 || 1) * 0.2;
  const lo = min - pad;
  const hi = max + pad;
  const width = 600;
  const height = 150;
  const last = series.length - 1;
  // La previsión ocupa un tercio del ancho para que se lea como futuro.
  const pastWidth = forecast !== null ? (width - 16) * 0.7 : width - 16;
  const x = (index: number) => 8 + (last ? index / last : 0) * pastWidth;
  const xEnd = width - 8;
  const y = (value: number) => 12 + (1 - (value - lo) / (hi - lo)) * (height - 24);
  const line = series.map((point, index) => `${index ? "L" : "M"}${x(index).toFixed(1)} ${y(point.value).toFixed(1)}`).join(" ");
  const area = `${line} L${x(last).toFixed(1)} ${height} L${x(0).toFixed(1)} ${height} Z`;
  const pastColor = series[last].value >= series[0].value ? TONE.green : TONE.red;
  const futureColor = forecast !== null && forecast < series[last].value ? TONE.red : TONE.green;
  const left = (px: number) => `${(px / width) * 100}%`;
  const top = (px: number) => `${(px / height) * 100}%`;
  return (
    <div>
      <div className="relative">
        <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="block h-[150px] w-full" role="img" aria-label="Evolución del valor">
          <defs>
            <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor={pastColor} stopOpacity="0.3" />
              <stop offset="1" stopColor={pastColor} stopOpacity="0" />
            </linearGradient>
          </defs>
          {[0.25, 0.5, 0.75].map((share) => (
            <line key={share} x1="0" x2={width} y1={height * share} y2={height * share} stroke="rgba(255,255,255,0.05)" vectorEffect="non-scaling-stroke" />
          ))}
          {forecast !== null ? (
            <rect x={x(last)} y="0" width={xEnd - x(last) + 8} height={height} fill="rgba(255,255,255,0.025)" />
          ) : null}
          {last ? <path d={area} fill={`url(#${gradientId})`} /> : null}
          {last ? <path d={line} fill="none" stroke={pastColor} strokeWidth="2.4" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" /> : null}
          {forecast !== null ? (
            <path
              d={`M${x(last).toFixed(1)} ${y(series[last].value).toFixed(1)} L${xEnd} ${y(forecast).toFixed(1)}`}
              fill="none"
              stroke={futureColor}
              strokeWidth="2.4"
              strokeDasharray="6 6"
              strokeLinecap="round"
              vectorEffect="non-scaling-stroke"
            />
          ) : null}
        </svg>
        <span
          className="absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white"
          style={{ left: left(x(last)), top: top(y(series[last].value)), boxShadow: `0 0 0 4px ${pastColor}44` }}
          aria-hidden="true"
        />
        {forecast !== null ? (
          <span
            className="absolute -translate-x-full -translate-y-1/2 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold tabular-nums"
            style={{ left: left(xEnd), top: top(Math.max(14, Math.min(height - 14, y(forecast) - 14))), color: futureColor, background: `${futureColor}22` }}
          >
            {money(forecast)}
          </span>
        ) : null}
      </div>
      <div className="relative mt-1.5 h-4 text-[10.5px] tabular-nums text-white/35">
        <span className="absolute left-0">{series[0].day === "hoy" ? "hoy" : dayLabel(series[0].day)}</span>
        {last ? (
          <span className="absolute -translate-x-1/2" style={{ left: left(x(last)) }}>
            hoy
          </span>
        ) : null}
        {forecast !== null ? <span className="absolute right-0">+7 días</span> : null}
      </div>
    </div>
  );
}

function WeekBars({ weeks }: { weeks: number[] }) {
  const shown = weeks.slice(-8);
  if (!shown.length) return <p className="text-[13px] text-white/45">Sin puntos de jornada guardados.</p>;
  const top = Math.max(10, ...shown);
  const first = weeks.length - shown.length + 1;
  return (
    <div className="flex h-24 items-end gap-2">
      {shown.map((value, index) => {
        const color = value >= 10 ? TONE.green : value >= 5 ? "#FF9A5A" : value > 0 ? TONE.amber : TONE.red;
        return (
          <span key={index} className="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1">
            <span className="text-[11px] font-semibold tabular-nums text-white/75">{dec(value, 0)}</span>
            <span className="w-full rounded-md" style={{ height: `${Math.max(5, (Math.max(0, value) / top) * 70)}%`, background: color, opacity: 0.85 }} />
            <span className="text-[10px] tabular-nums text-white/35">J{first + index}</span>
          </span>
        );
      })}
    </div>
  );
}

function Point({ icon, color, title, text }: { icon: string; color: string; title: string; text: string }) {
  return (
    <li className="flex gap-3">
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-[14px] font-semibold" style={{ color, background: `${color}1c` }} aria-hidden="true">
        {icon}
      </span>
      <span className="min-w-0 pt-0.5">
        <span className="block text-[12px] font-semibold" style={{ color }}>
          {title}
        </span>
        <span className="mt-0.5 block text-[13.5px] leading-snug text-white/75">{text}</span>
      </span>
    </li>
  );
}

/** Ficha de un jugador del mercado: cuánto pujar, qué rinde y por qué, sin jerga. */
export function PlayerCard({ player, photo, onClose }: { player: MarketDecision | null; photo?: string | null; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [comparing, setComparing] = useState<{ id: string; position?: string | null } | null>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (player && !dialog.open) {
      dialog.showModal();
      dialog.scrollTop = 0;
    }
    if (!player && dialog.open) dialog.close();
  }, [player]);

  const body = (() => {
    if (!player) return null;
    const name = playerName(player);
    const story = bidStory(player);
    const verdict = ACTION_VERDICT[marketAction(player)];
    const ideal = executableBid(player);
    const max = isVetoed(player) ? null : maxBid(player);
    const value = num(player.market_value) ?? num(player.sale_price);
    const rawWin = winShare(typeof player.smart_bid_success_pct === "number" ? player.smart_bid_success_pct : player.win_probability);
    // Sin puja que hacer no hay probabilidad de ganarla que enseñar.
    const win = ideal === null ? null : rawWin;
    const trend = parsePct(player.prevision_7d_pct);
    const forecast = num(player.valor_en_7d);
    const gain7 = forecast !== null && value !== null ? forecast - value : null;
    const xp = num(player.jornada_ev) ?? num(player.expected_points);
    const xp4 = num(player.xp_4_jornadas);
    const titular = num(player.p_titular);
    const note = num(player.nota_mercado);
    const delta = num(player.points_delta);
    const weeks = Array.isArray(player.week_points) ? player.week_points : [];
    const average = num(player.average_points);
    const history = Array.isArray(player.value_history) ? player.value_history : [];
    const matches = upcoming(player);
    const accent = note === null ? TONE.gray : gradeColor(note);
    const reason = player.frase_mercado || actionReason(player, story.motive) || story.headline;
    const trendColor = trend === null ? TONE.gray : trend >= 0 ? TONE.green : TONE.red;
    const risk =
      win !== null && win < 0.4
        ? "Es difícil ganar la puja: hay rivales con caja para superarte."
        : trend !== null && trend < 0
          ? `Se espera que pierda valor (${signedPct(trend)} en 7 días).`
          : titular !== null && titular < 0.6
            ? `No es titular seguro: ${Math.round(titular * 100)}% de jugar de inicio.`
            : "Sin riesgos destacados con los datos de hoy.";

    return (
      <article>
        <header
          className="relative px-5 pb-5 pt-6"
          style={{ background: `radial-gradient(110% 100% at 100% 0%, ${accent}30 0%, transparent 55%), radial-gradient(80% 90% at 0% 0%, rgba(255,122,61,0.22), transparent 60%)` }}
        >
          <button
            type="button"
            onClick={onClose}
            aria-label="Cerrar"
            className="absolute right-4 top-4 grid h-9 w-9 place-items-center rounded-full bg-white/[0.07] text-white/70 transition-colors hover:bg-white/[0.14] hover:text-white"
          >
            <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
              <path d="M4 4l8 8M12 4l-8 8" strokeLinecap="round" />
            </svg>
          </button>
          <div className="flex items-center gap-4 pr-10">
            <Face name={name} src={player.image_url || photo} size={72} ring={accent} />
            <div className="min-w-0 flex-1">
              <h2 className="line-clamp-2 text-[1.35rem] font-semibold leading-tight tracking-tight text-white sm:text-[1.55rem]">{name}</h2>
              <p className="mt-1 truncate text-[12.5px] text-white/50">{[player.position, player.club].filter(Boolean).join(" · ")}</p>
              <p className="mt-0.5 truncate text-[12px] text-white/40">{sourceLabel(player)}</p>
            </div>
          </div>
          <div className="mt-5 flex items-center gap-4">
            <GradeRing note={note} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[12.5px] font-semibold" style={{ color: verdict.color, background: `${verdict.color}1f` }}>
                  <span className="h-1.5 w-1.5 rounded-full" style={{ background: verdict.color }} />
                  {verdict.label}
                </span>
                {player.etiqueta_mercado ? (
                  <span className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: accent }}>
                    {player.etiqueta_mercado}
                  </span>
                ) : null}
              </div>
              <p className="mt-2 line-clamp-3 text-[13.5px] leading-snug text-white/75">{reason}</p>
            </div>
          </div>
        </header>

        <div className="grid grid-cols-3 divide-x divide-white/[0.06] border-t border-white/[0.06]">
          {[
            { label: "Puja ideal", value: money(ideal), tone: ideal !== null ? TONE.green : undefined },
            { label: "Puja máxima", value: money(max), tone: "#FFC08A" },
            { label: "Ganarla", value: win === null ? "—" : `${Math.round(win * 100)}%`, tone: win === null ? undefined : win >= 0.7 ? TONE.green : win >= 0.4 ? TONE.amber : TONE.red },
          ].map((item) => (
            <div key={item.label} className="px-3 py-4 text-center">
              <p className="text-[11px] font-medium text-white/40">{item.label}</p>
              <p className="mt-1 truncate text-[1.15rem] font-semibold tabular-nums sm:text-[1.4rem]" style={{ color: item.tone || "#fff" }}>
                {item.value}
              </p>
            </div>
          ))}
        </div>

        <Section
          title="Valor de mercado"
          aside={
            <span className="font-semibold tabular-nums" style={{ color: trendColor }}>
              {trend === null ? "sin previsión" : `${trend >= 0 ? "▲" : "▼"} ${signedPct(trend)} en 7 días`}
            </span>
          }
        >
          <div className="mb-3 flex items-end justify-between gap-3">
            <p className="text-[1.6rem] font-semibold leading-none tabular-nums text-white">{money(value)}</p>
            {gain7 !== null ? (
              <p className="text-[13px] font-semibold tabular-nums" style={{ color: trendColor }}>
                {gain7 >= 0 ? "+" : ""}
                {money(gain7)} previstos
              </p>
            ) : null}
          </div>
          <ValueChart history={history} today={value} forecast={forecast} />
        </Section>

        <Section title="Rendimiento">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Metric label="Próxima jornada" value={`${dec(xp)} pts`} tone="#FFC08A" />
            <Metric label="Próximas 4" value={`${dec(xp4)} pts`} />
            <Metric
              label="Titular"
              value={titular === null ? "—" : `${Math.round(titular * 100)}%`}
              tone={titular === null ? undefined : titular >= 0.8 ? TONE.green : titular >= 0.5 ? TONE.amber : TONE.red}
            />
            <Metric
              label="Tu once"
              value={delta === null || !player.replaces?.name ? "—" : `${delta > 0 ? "+" : ""}${dec(delta)} pts`}
              tone={delta !== null && delta > 0 ? TONE.green : undefined}
              sub={player.replaces?.name ? `por ${player.replaces.name}` : "no mejora tu once"}
            />
          </div>
        </Section>

        <Section title="Últimas jornadas" aside={average !== null ? `media ${dec(average)} pts` : undefined}>
          <WeekBars weeks={weeks} />
        </Section>

        {matches.length ? (
          <Section title="Próximos rivales">
            <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {matches.map((match, index) => {
                const diff = (match.difficulty && DIFF[match.difficulty]) || { label: "s/d", color: TONE.gray };
                return (
                  <li key={`${match.opponent}-${index}`} className="rounded-2xl bg-white/[0.04] px-3 py-2.5">
                    <p className="text-[10.5px] text-white/40">
                      {index === 0 ? "Próximo" : `+${index}`} · {match.home === true ? "casa" : match.home === false ? "fuera" : "—"}
                    </p>
                    <p className="mt-0.5 truncate text-[14px] font-semibold text-white">{match.opponent}</p>
                    <p className="mt-1 flex items-center gap-1.5 text-[11.5px] font-medium" style={{ color: diff.color }}>
                      <span className="h-1.5 w-1.5 rounded-full" style={{ background: diff.color }} />
                      {diff.label}
                    </p>
                  </li>
                );
              })}
            </ul>
          </Section>
        ) : null}

        <Section title="En resumen">
          <ul className="flex flex-col gap-3.5">
            <Point icon="✓" color={TONE.green} title="Por qué" text={reason} />
            <Point icon="!" color={TONE.amber} title="Riesgo" text={risk} />
            <Point icon="→" color="#FF9A5A" title="Qué hacer" text={story.action} />
          </ul>
          <div className="mt-4 flex flex-wrap gap-x-5 gap-y-1.5 text-[12px] text-white/45">
            <span>
              Puja más alta: <span className="tabular-nums text-white/75">{money(player.leading_bid)}</span>
            </span>
            <span>
              Caja tras pujar: <span className="tabular-nums text-white/75">{money(player.cash_after_eur)}</span>
            </span>
            {player.listing_expires_at ? (
              <span>
                Cierra:{" "}
                <span className="tabular-nums text-white/75">
                  {new Date(player.listing_expires_at).toLocaleString("es-ES", { weekday: "short", hour: "2-digit", minute: "2-digit" })}
                </span>
              </span>
            ) : null}
          </div>
        </Section>

        <div className="border-t border-white/[0.06] p-4">
          <button
            type="button"
            onClick={() => {
              if (player.player_id) setComparing({ id: String(player.player_id), position: player.position });
              onClose();
            }}
            className="h-12 w-full rounded-full bg-white/[0.06] text-[14px] font-semibold text-white transition-colors hover:bg-white/[0.1]"
          >
            Comparar con otro jugador
          </button>
        </div>
      </article>
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
        {body}
      </dialog>
      {comparing ? <CompararConSugerido objetivoId={comparing.id} posicion={comparing.position} onClose={() => setComparing(null)} /> : null}
    </>
  );
}
