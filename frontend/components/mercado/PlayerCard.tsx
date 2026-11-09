"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { gradeColor } from "@/components/mercado/MarketGrade";
import { ValueChart } from "@/components/mercado/ValueChart";
import { CompararConSugerido } from "@/components/comparador/ComparadorReal";
import { Face, TONE, cleanText, money, parsePct, signedPct } from "@/components/ui/kit";
import { ACTION_VERDICT, auctionLabel, winShare } from "@/components/mercado/shared";
import { bidStory } from "@/lib/mercado/bidStory";
import { playerName } from "@/lib/core/format";
import { actionReason, executableBid, isVetoed, marketAction } from "@/lib/mercado/marketAction";
import { StatusBadge } from "@/components/ui/StatusBadge";
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

/** Veto que solo es de caja: el jugador vale la pena, pero hoy no te llega. */
function isCashVeto(player: MarketDecision): boolean {
  if (!isVetoed(player)) return false;
  const reasons = Array.isArray(player.reasons) ? player.reasons : [];
  const blocked = ["ya_en_plantilla", "listing_propio", "lesionado", "sancionado", "mercado_cerrado", "sin_slots"];
  if (reasons.some((reason) => blocked.includes(reason))) return false;
  return player.bid_limit === "sin_caja" || player.primary_motive === "sin_caja" || reasons.includes("sin_caja") || (num(player.cash_after_eur) ?? 0) < 0;
}

/**
 * Cifras si liberas caja vendiendo a otro jugador. Salen de las fuentes
 * (ideal/máx.), que no dependen de tu saldo; la puja smart sí se recorta a la
 * caja, así que no sirve aquí.
 */
function ifYouSell(player: MarketDecision, cash: number | null): { ideal: number; max: number | null; missing: number | null } | null {
  if (!isCashVeto(player)) return null;
  const ideal = num(player.ideal_bid) ?? num(player.own_ideal_bid) ?? num(player.af_ideal_bid) ?? num(player.app_bid_eur);
  if (ideal === null) return null;
  const max = num(player.max_bid) ?? num(player.own_max_bid) ?? num(player.af_max_bid) ?? num(player.financial_max_bid_eur);
  return { ideal, max: max !== null && max > ideal ? max : null, missing: cash !== null && ideal > cash ? ideal - cash : null };
}

function titularColor(share: number | null): string | undefined {
  if (share === null) return undefined;
  return share >= 0.8 ? TONE.green : share >= 0.5 ? TONE.amber : TONE.red;
}

function closesIn(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return null;
  const hours = (at.getTime() - Date.now()) / 3_600_000;
  if (hours <= 0) return "Cerrada";
  if (hours < 1) return `Cierra en ${Math.max(1, Math.round(hours * 60))} min`;
  if (hours < 24) return `Cierra en ${Math.round(hours)} h`;
  return `Cierra ${at.toLocaleString("es-ES", { weekday: "short", hour: "2-digit", minute: "2-digit" })}`;
}

function Pill({ color, children }: { color: string; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px] font-semibold" style={{ color, background: `${color}1f` }}>
      {children}
    </span>
  );
}

function Block({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-[1.5rem] bg-[#141414] p-4">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h3 className="text-[13px] font-semibold text-white/80">{title}</h3>
        {aside ? <span className="text-[12px] tabular-nums text-white/45">{aside}</span> : null}
      </div>
      {children}
    </section>
  );
}

function Stat({ label, value, tone, sub }: { label: string; value: string; tone?: string; sub?: string }) {
  return (
    <div className="min-w-0 rounded-2xl bg-white/[0.04] px-3 py-3">
      <p className="truncate text-[11px] text-white/45">{label}</p>
      <p className="mt-1 truncate text-[1.2rem] font-semibold leading-none tabular-nums" style={{ color: tone || "#fff" }}>
        {value}
      </p>
      {sub ? <p className="mt-1 truncate text-[11px] text-white/40">{sub}</p> : null}
    </div>
  );
}

/** Probabilidad de ganar la puja como anillo pequeño. */
function WinRing({ share }: { share: number | null }) {
  const size = 64;
  const r = 26;
  const c = 2 * Math.PI * r;
  const color = share === null ? TONE.gray : share >= 0.7 ? TONE.green : share >= 0.4 ? TONE.amber : TONE.red;
  return (
    <span className="relative inline-grid shrink-0 place-items-center" style={{ width: size, height: size }}>
      <svg viewBox={`0 0 ${size} ${size}`} className="absolute inset-0 -rotate-90" aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="5" />
        {share !== null ? (
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={color}
            strokeWidth="5"
            strokeLinecap="round"
            strokeDasharray={`${c * share} ${c}`}
            className="transition-[stroke-dasharray] duration-700 ease-out"
          />
        ) : null}
      </svg>
      <span className="text-center">
        <span className="block text-[15px] font-semibold leading-none tabular-nums" style={{ color: share === null ? "rgba(255,255,255,0.5)" : "#fff" }}>
          {share === null ? "—" : `${Math.round(share * 100)}%`}
        </span>
        <span className="mt-0.5 block text-[9px] font-medium uppercase tracking-[0.12em] text-white/40">ganar</span>
      </span>
    </span>
  );
}

/** Puntos por jornada en barras redondeadas. */
function FormBars({ weeks }: { weeks: number[] }) {
  const shown = weeks.slice(-8);
  if (!shown.length) return <p className="text-[13px] text-white/45">Sin puntos de jornada guardados.</p>;
  const top = Math.max(10, ...shown);
  const first = weeks.length - shown.length + 1;
  return (
    <div className="flex h-28 items-end gap-1.5">
      {shown.map((value, index) => {
        const color = value >= 10 ? TONE.green : value >= 5 ? "#FF9A5A" : value > 0 ? TONE.amber : TONE.red;
        return (
          <span key={index} className="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1">
            <span className="text-[11px] font-semibold tabular-nums text-white/80">{dec(value, 0)}</span>
            <span
              className="w-full max-w-[1.5rem] rounded-t-[0.6rem] rounded-b-[0.3rem]"
              style={{ height: `${Math.max(4, (Math.max(0, value) / top) * 78)}%`, background: `linear-gradient(180deg, ${color}, ${color}88)` }}
            />
            <span className="text-[10px] tabular-nums text-white/35">J{first + index}</span>
          </span>
        );
      })}
    </div>
  );
}

/** Ficha de un jugador del mercado: qué hacer, cuánto pujar y cómo va su valor. */
/**
 * `cash` es tu caja de hoy. No se saca de `cash_after_eur`: ese campo es lo que
 * queda tras todas las pujas del plan hasta esta, no tras pujar solo esta.
 */
export function PlayerCard({
  player,
  photo,
  cash: cashProp,
  onClose,
}: {
  player: MarketDecision | null;
  photo?: string | null;
  cash?: number | null;
  onClose: () => void;
}) {
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
    const action = marketAction(player);
    const verdict = ACTION_VERDICT[action];
    const ideal = executableBid(player);
    const cash = num(cashProp);
    // El máximo de las fuentes no mira tu caja: pasar de ella te deja en
    // negativo y con saldo negativo puntúas 0, así que se recorta a la caja.
    const rawMax = isVetoed(player) ? null : maxBid(player);
    const max = rawMax !== null && cash !== null && cash > 0 ? Math.min(rawMax, cash) : rawMax;
    const maxIsCash = rawMax !== null && max !== null && max < rawMax;
    const value = num(player.market_value) ?? num(player.sale_price);
    const rawWin = winShare(typeof player.smart_bid_success_pct === "number" ? player.smart_bid_success_pct : player.win_probability);
    const win = ideal === null ? null : rawWin;
    const forecast = num(player.valor_en_7d);
    const parsedTrend = parsePct(player.prevision_7d_pct);
    const trend = parsedTrend ?? (forecast !== null && value ? ((forecast - value) / value) * 100 : null);
    const gain7 = forecast !== null && value !== null ? forecast - value : null;
    const trendColor = trend === null || Math.abs(trend) < 0.05 ? "rgba(255,255,255,0.55)" : trend > 0 ? TONE.green : TONE.red;
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
    const heat = auctionLabel(player);
    // Si es objetivo del plan de Inicio, manda su frase («viable vendiendo a X»).
    const reason = cleanText(
      (player.en_plan ? actionReason(player) : null) || player.frase_mercado || actionReason(player, story.motive) || story.headline,
    );
    const closing = closesIn(player.listing_expires_at);
    const seller = player.offer_source === "rival" ? `Lo vende ${player.seller_manager || "un rival"}` : "Lo vende LaLiga";
    const risk =
      player.offer_source === "rival"
        ? "Venta de un rival: en esta liga casi nunca se gana pujando, y si pasa es por bastante más de la recomendada. No cuenta en el plan."
        : win !== null && win < 0.4
        ? "Difícil ganar la puja: hay rivales con caja para superarte."
        : trend !== null && trend < -0.5
          ? `Se espera que pierda valor esta semana (${signedPct(trend)}).`
          : titular !== null && titular < 0.6
            ? `No es titular seguro: ${Math.round(titular * 100)}% de salir de inicio.`
            : null;
    const overbid = cleanText(player.bid_plan?.overbid?.etiqueta);
    const sell = ifYouSell(player, cash);
    // «Caja después» con la cifra grande de la ficha, no con `bid_eur`.
    const shownBid = ideal ?? sell?.ideal ?? null;
    const cashAfter = cash !== null && shownBid !== null ? cash - shownBid : num(player.cash_after_eur);
    const bidLabel = sell ? "Puja ideal si vendes a alguien" : ideal === null ? "Valor de mercado" : action === "PUJAR" ? "Puja recomendada" : "Si decides pujar";
    const howTo =
      ideal === null
        ? null
        : action === "PUJAR"
          ? `Ofrece ${money(ideal)}${max !== null && max > ideal ? ` y, si te superan, no pases de ${money(max)}` : ""}.`
          : action === "ESPERAR"
            ? "Hoy no compensa pujar: espera a que baje o a que cambie tu once."
            : null;

    return (
      <article className="flex flex-col gap-2.5 p-2.5 sm:p-3">
        <span className="mx-auto mt-0.5 h-1 w-10 rounded-full bg-white/20 sm:hidden" aria-hidden="true" />

        <header
          className="relative overflow-hidden rounded-[1.75rem] px-4 pb-4 pt-5"
          style={{
            background: `radial-gradient(ellipse 120% 90% at 50% 0%, ${verdict.color}40 0%, ${verdict.color}14 45%, transparent 75%), #111`,
          }}
        >
          <button
            type="button"
            onClick={onClose}
            aria-label="Cerrar"
            className="absolute right-3 top-3 grid h-9 w-9 place-items-center rounded-full bg-black/30 text-white/70 outline-none backdrop-blur-md transition-colors hover:bg-black/50 hover:text-white focus-visible:shadow-[inset_0_0_0_1px_rgba(255,255,255,0.4)]"
          >
            <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
              <path d="M4 4l8 8M12 4l-8 8" strokeLinecap="round" />
            </svg>
          </button>
          <div className="flex items-center gap-3.5 pr-10">
            <Face name={name} src={player.image_url || photo} size={64} ring={verdict.color} />
            <div className="min-w-0 flex-1">
              <h2 className="truncate text-[1.35rem] font-semibold leading-tight tracking-tight text-white">{name}</h2>
              <p className="mt-0.5 truncate text-[13px] text-white/55">{[player.position, player.club].filter(Boolean).join(" · ")}</p>
              <p className="mt-0.5 truncate text-[12px] text-white/40">{[seller, closing].filter(Boolean).join(" · ")}</p>
            </div>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-1.5">
            <Pill color={verdict.color}>
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: verdict.color }} aria-hidden="true" />
              {verdict.label}
            </Pill>
            {note !== null ? <Pill color={accent}>Nota {dec(note)}</Pill> : null}
            {heat ? <Pill color={TONE.amber}>{heat}</Pill> : null}
            <StatusBadge status={player.official_status || player.player_status} />
          </div>
          <p className="mt-3 line-clamp-3 text-[14px] leading-snug text-white/80">{reason}</p>
        </header>

        <section className="rounded-[1.5rem] bg-[#141414] p-4" aria-label="Tu puja">
          <div className="flex items-center gap-4">
            <div className="min-w-0 flex-1">
              <p className="text-[12px] text-white/45">{bidLabel}</p>
              <p className="mt-1 text-[2.1rem] font-semibold leading-none tracking-[-0.03em] tabular-nums text-white">
                {money(ideal ?? sell?.ideal ?? value)}
              </p>
              {ideal !== null && max !== null && max > ideal ? (
                <p className="mt-1.5 text-[12.5px] tabular-nums text-white/50">
                  Hasta <span className="font-semibold text-[#FFC08A]">{money(max)}</span> {maxIsCash ? "como máximo: es toda tu caja" : "como máximo"}
                </p>
              ) : null}
              {sell ? (
                <p className="mt-1.5 text-[12.5px] tabular-nums text-white/50">
                  {sell.max !== null ? (
                    <>
                      Hasta <span className="font-semibold text-[#FFC08A]">{money(sell.max)}</span> como máximo
                    </>
                  ) : null}
                  {sell.max !== null && sell.missing !== null ? " · " : null}
                  {sell.missing !== null ? <>te faltan <span className="font-semibold text-[#FF8A7A]">{money(sell.missing)}</span> de caja</> : null}
                </p>
              ) : null}
            </div>
            {ideal !== null ? <WinRing share={win} /> : null}
          </div>
          {overbid ? (
            <p
              className="mt-3 flex items-center gap-2 text-[12.5px] font-medium"
              style={{ color: player.bid_plan?.overbid?.status === "guerra" ? TONE.red : player.bid_plan?.overbid?.status === "high" ? TONE.copper : TONE.green }}
            >
              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-current" aria-hidden="true" />
              {overbid}
            </p>
          ) : null}
          <div className="mt-4 grid grid-cols-3 gap-2 border-t border-white/[0.06] pt-3 text-[12px]">
            <div className="min-w-0">
              <p className="text-white/40">Valor</p>
              <p className="mt-0.5 truncate font-semibold tabular-nums text-white">{money(value)}</p>
            </div>
            <div className="min-w-0">
              <p className="text-white/40">Puja más alta</p>
              <p className="mt-0.5 truncate font-semibold tabular-nums text-white">
                {typeof player.leading_bid === "number" ? money(player.leading_bid) : heat ? "Oculta" : "Ninguna"}
              </p>
            </div>
            <div className="min-w-0 text-right">
              <p className="text-white/40">{cash !== null && shownBid !== null ? "Caja si pujas esta" : "Caja después"}</p>
              <p
                className="mt-0.5 truncate font-semibold tabular-nums"
                style={{ color: cashAfter !== null && cashAfter < 0 ? TONE.red : "#fff" }}
              >
                {money(cashAfter)}
              </p>
            </div>
          </div>
          {howTo ? (
            <p className="mt-3 flex gap-2 rounded-2xl bg-white/[0.04] px-3 py-2.5 text-[13px] leading-snug text-white/75">
              <span className="font-semibold text-[#FF9A5A]" aria-hidden="true">
                →
              </span>
              <span>{howTo}</span>
            </p>
          ) : null}
          {risk ? (
            <p className="mt-2 flex gap-2 rounded-2xl px-3 py-2.5 text-[13px] leading-snug" style={{ color: TONE.amber, background: `${TONE.amber}14` }}>
              <span className="font-semibold" aria-hidden="true">
                !
              </span>
              <span>{risk}</span>
            </p>
          ) : null}
        </section>

        <Block
          title="Valor y previsión"
          aside={
            trend !== null ? (
              <span className="font-semibold" style={{ color: trendColor }}>
                {trend > 0 ? "▲" : trend < 0 ? "▼" : "•"} {signedPct(trend)} en 7 días
              </span>
            ) : (
              "sin previsión"
            )
          }
        >
          <div className="mb-3 flex items-end justify-between gap-3">
            <p className="text-[1.7rem] font-semibold leading-none tracking-[-0.02em] tabular-nums text-white">{money(value)}</p>
            {gain7 !== null ? (
              <p className="text-right text-[12px] text-white/45">
                En 7 días
                <span className="block text-[14px] font-semibold tabular-nums" style={{ color: trendColor }}>
                  {gain7 > 0 ? "+" : ""}
                  {money(gain7)}
                </span>
              </p>
            ) : null}
          </div>
          <ValueChart history={history} today={value} forecast={forecast} trendPct={trend} />
        </Block>

        <div className="grid grid-cols-2 gap-2.5">
          <Stat label="Próxima jornada" value={`${dec(xp)} pts`} tone="#FFC08A" sub={xp4 !== null ? `${dec(xp4)} en 4 jornadas` : undefined} />
          <Stat label="Titular" value={titular === null ? "—" : `${Math.round(titular * 100)}%`} tone={titularColor(titular)} sub="probabilidad" />
          <Stat
            label="Tu once"
            value={delta === null || !player.replaces?.name ? "No mejora" : `${delta > 0 ? "+" : ""}${dec(delta)} pts`}
            tone={delta !== null && delta > 0 && player.replaces?.name ? TONE.green : "rgba(255,255,255,0.6)"}
            sub={
              player.replaces?.name
                ? player.replaces.formation && player.replaces.formation !== player.replaces.formation_from
                  ? `por ${player.replaces.name} · ${player.replaces.formation}`
                  : `por ${player.replaces.name}`
                : undefined
            }
          />
          <Stat label="Media" value={average !== null ? `${dec(average)} pts` : "—"} sub="por jornada" />
        </div>

        <Block title="Últimas jornadas" aside={average !== null ? `media ${dec(average)} pts` : undefined}>
          <FormBars weeks={weeks} />
        </Block>

        {matches.length ? (
          <Block title="Próximos rivales">
            <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {matches.map((match, index) => {
                const diff = (match.difficulty && DIFF[match.difficulty]) || { label: "s/d", color: TONE.gray };
                return (
                  <li key={`${match.opponent}-${index}`} className="relative overflow-hidden rounded-2xl bg-white/[0.04] px-3 py-2.5">
                    <span className="absolute inset-y-0 left-0 w-1" style={{ background: diff.color }} aria-hidden="true" />
                    <p className="text-[10.5px] text-white/40">
                      {index === 0 ? "Próximo" : `En ${index + 1}`} · {match.home === true ? "casa" : match.home === false ? "fuera" : "—"}
                    </p>
                    <p className="mt-0.5 truncate text-[14px] font-semibold text-white">{match.opponent}</p>
                    <p className="mt-0.5 text-[11.5px] font-medium" style={{ color: diff.color }}>
                      {diff.label}
                    </p>
                  </li>
                );
              })}
            </ul>
          </Block>
        ) : null}

        <button
          type="button"
          onClick={() => {
            if (player.player_id) setComparing({ id: String(player.player_id), position: player.position });
            onClose();
          }}
          className="mb-1 h-12 w-full rounded-full bg-white text-[14px] font-semibold text-[#0b0b0b] transition-transform duration-200 ease-out active:scale-[0.98]"
        >
          Comparar con otro jugador
        </button>
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
