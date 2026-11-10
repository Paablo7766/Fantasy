"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { ValueChart } from "@/components/mercado/ValueChart";
import { CompararConSugerido } from "@/components/comparador/ComparadorReal";
import { Face, TONE, cleanText, money, parsePct, signedPct } from "@/components/ui/kit";
import { ACTION_VERDICT, auctionLabel, winShare } from "@/components/mercado/shared";
import { bidStory } from "@/lib/mercado/bidStory";
import { playerName } from "@/lib/core/format";
import { actionReason, executableBid, isVetoed, marketAction } from "@/lib/mercado/marketAction";
import { statusBadgeLabel } from "@/components/ui/StatusBadge";
import { Crest } from "@/components/ui/Crest";
import type { MarketDecision } from "@/lib/types";

type Match = { opponent: string; home: boolean | null; difficulty: string | null };

const DIFF: Record<string, { label: string; color: string }> = {
  muy_facil: { label: "Muy fácil", color: TONE.green },
  very_easy: { label: "Muy fácil", color: TONE.green },
  facil: { label: "Fácil", color: TONE.green },
  easy: { label: "Fácil", color: TONE.green },
  media: { label: "Media", color: TONE.gray },
  medium: { label: "Media", color: TONE.gray },
  dificil: { label: "Difícil", color: TONE.red },
  hard: { label: "Difícil", color: TONE.red },
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

/** Sección de la ficha: una sola superficie, separada por una línea fina. */
function Section({ title, aside, children }: { title?: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="border-t border-white/[0.07] px-5 py-5 sm:px-7">
      {title ? (
        <div className="mb-4 flex items-baseline justify-between gap-3">
          <h3 className="text-[11px] font-medium uppercase tracking-[0.14em] text-white/40">{title}</h3>
          {aside ? <span className="text-[12.5px] tabular-nums text-white/50">{aside}</span> : null}
        </div>
      ) : null}
      {children}
    </section>
  );
}

/** Cifra clave sin caja: etiqueta gris, número blanco y una línea de apoyo. */
function Figure({ label, value, tone, sub }: { label: string; value: string; tone?: string; sub?: string }) {
  return (
    <div className="min-w-0">
      <p className="truncate text-[11.5px] text-white/40">{label}</p>
      <p className="mt-1.5 truncate text-[1.3rem] font-semibold leading-none tracking-[-0.02em] tabular-nums" style={{ color: tone || "#fff" }}>
        {value}
      </p>
      {sub ? <p className="mt-1.5 truncate text-[11.5px] text-white/40">{sub}</p> : null}
    </div>
  );
}

/** Aviso de una línea: punto de color y texto gris. */
function Note({ color, children }: { color: string; children: ReactNode }) {
  return (
    <p className="flex items-start gap-2.5 text-[13px] leading-snug text-white/60">
      <span className="mt-[0.45em] h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: color }} aria-hidden="true" />
      <span>{children}</span>
    </p>
  );
}

/** Probabilidad de ganar la puja: cifra y barra fina. */
function WinMeter({ share }: { share: number | null }) {
  return (
    <div className="w-[7.5rem] shrink-0 text-right">
      <p className="text-[11.5px] text-white/40">Opciones de ganar</p>
      <p className="mt-1.5 text-[1.3rem] font-semibold leading-none tracking-[-0.02em] tabular-nums text-white">
        {share === null ? "—" : `${Math.round(share * 100)} %`}
      </p>
      <span className="mt-2.5 block h-[3px] overflow-hidden rounded-full bg-white/[0.08]" aria-hidden="true">
        <span
          className="block h-full rounded-full bg-white/80 transition-[width] duration-700 ease-out"
          style={{ width: `${Math.round((share ?? 0) * 100)}%` }}
        />
      </span>
    </div>
  );
}

/** Puntos por jornada: barras neutras, las que superan la media en blanco. */
function FormBars({ weeks, average }: { weeks: number[]; average: number | null }) {
  const shown = weeks.slice(-8);
  if (!shown.length) return <p className="text-[13px] text-white/45">Sin puntos de jornada guardados.</p>;
  const top = Math.max(10, ...shown);
  const first = weeks.length - shown.length + 1;
  const mean = average ?? shown.reduce((sum, value) => sum + value, 0) / shown.length;
  return (
    <div className="flex h-28 items-end gap-2">
      {shown.map((value, index) => {
        const good = value >= mean && value > 0;
        return (
          <span key={index} className="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1.5">
            <span className={`text-[11.5px] font-medium tabular-nums ${good ? "text-white" : "text-white/45"}`}>{dec(value, 0)}</span>
            <span
              className="w-full max-w-[1.75rem] rounded-[0.3rem]"
              style={{ height: `${Math.max(3, (Math.max(0, value) / top) * 72)}%`, background: good ? "rgba(255,255,255,0.82)" : "rgba(255,255,255,0.16)" }}
            />
            <span className="text-[10.5px] tabular-nums text-white/30">J{first + index}</span>
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
    const bidLabel = sell ? "Puja ideal si vendes a alguien" : action === "PUJAR" ? "Puja recomendada" : "Si decides pujar";
    const status = statusBadgeLabel(player.official_status || player.player_status);
    const overbidStatus = player.bid_plan?.overbid?.status;
    const improves = delta !== null && delta > 0 && Boolean(player.replaces?.name);
    const cap = ideal !== null && max !== null && max > ideal ? max : sell?.max ?? null;
    const leading = typeof player.leading_bid === "number" ? money(player.leading_bid) : heat || "Ninguna";

    return (
      <article className="flex flex-col">
        <span className="mx-auto mt-2 h-1 w-10 rounded-full bg-white/15 sm:hidden" aria-hidden="true" />

        <header className="relative px-5 pb-5 pt-5 sm:px-7 sm:pt-7">
          <button
            type="button"
            onClick={onClose}
            aria-label="Cerrar"
            className="absolute right-4 top-4 grid h-9 w-9 place-items-center rounded-full text-white/45 outline-none transition-colors hover:bg-white/[0.06] hover:text-white focus-visible:shadow-[inset_0_0_0_1px_rgba(255,255,255,0.4)] sm:right-5 sm:top-5"
          >
            <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
              <path d="M4 4l8 8M12 4l-8 8" strokeLinecap="round" />
            </svg>
          </button>
          <div className="flex items-center gap-4 pr-10">
            <Face name={name} src={player.image_url || photo} size={60} />
            <div className="min-w-0 flex-1">
              <h2 className="truncate text-[1.4rem] font-semibold leading-tight tracking-[-0.02em] text-white">{name}</h2>
              <p className="mt-1 flex items-center gap-1.5 text-[13px] text-white/55">
                <Crest club={player.club} size={16} />
                <span className="truncate">{[player.club, player.position].filter(Boolean).join(" · ")}</span>
              </p>
            </div>
          </div>
          <p className="mt-4 text-[12.5px] text-white/40">
            {[seller, closing].filter(Boolean).join(" · ")}
            {status ? (
              <>
                {" · "}
                <span style={{ color: status === "Duda" ? TONE.amber : TONE.red }}>{status}</span>
              </>
            ) : null}
          </p>
        </header>

        <Section>
          <p className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.14em] text-white/40">
            <span className="h-1.5 w-1.5 rounded-full" style={{ background: verdict.color }} aria-hidden="true" />
            Recomendación
          </p>
          <p className="mt-2 text-[1.15rem] font-semibold leading-tight tracking-[-0.01em] text-white">
            {action === "NO" ? "No pujar" : verdict.label}
          </p>
          <p className="mt-1.5 text-[14px] leading-relaxed text-white/60">{reason}</p>

          {shownBid !== null ? (
            <div className="mt-6 flex items-end justify-between gap-5">
              <div className="min-w-0">
                <p className="text-[11.5px] text-white/40">{bidLabel}</p>
                <p className="mt-1.5 text-[2.4rem] font-semibold leading-none tracking-[-0.035em] tabular-nums text-white">{money(shownBid)}</p>
              </div>
              {ideal !== null ? <WinMeter share={win} /> : null}
            </div>
          ) : null}

          <dl className={`mt-6 grid gap-4 border-t border-white/[0.07] pt-4 ${cap !== null ? "grid-cols-3" : "grid-cols-2"}`}>
            {cap !== null ? (
              <div className="min-w-0">
                <dt className="truncate text-[11.5px] text-white/40">{maxIsCash ? "Tope: toda tu caja" : "No pases de"}</dt>
                <dd className="mt-1 truncate text-[14px] font-semibold tabular-nums text-white">{money(cap)}</dd>
              </div>
            ) : null}
            <div className="min-w-0">
              <dt className="truncate text-[11.5px] text-white/40">{typeof player.leading_bid === "number" ? "Puja más alta" : "Pujas de rivales"}</dt>
              <dd className="mt-1 truncate text-[14px] font-semibold tabular-nums text-white">{leading}</dd>
            </div>
            <div className="min-w-0">
              <dt className="truncate text-[11.5px] text-white/40">{cash !== null && shownBid !== null ? "Tu caja si pujas" : "Caja después"}</dt>
              <dd className="mt-1 truncate text-[14px] font-semibold tabular-nums" style={{ color: cashAfter !== null && cashAfter < 0 ? TONE.red : "#fff" }}>
                {money(cashAfter)}
              </dd>
            </div>
          </dl>

          {sell?.missing != null || overbid || risk ? (
            <div className="mt-4 flex flex-col gap-2">
              {sell?.missing != null ? <Note color={TONE.red}>Te faltan {money(sell.missing)} de caja: solo es viable si vendes a alguien.</Note> : null}
              {overbid ? (
                <Note color={overbidStatus === "guerra" ? TONE.red : overbidStatus === "high" ? TONE.amber : TONE.green}>{overbid}</Note>
              ) : null}
              {risk ? <Note color={TONE.amber}>{risk}</Note> : null}
            </div>
          ) : null}
        </Section>

        <Section title="Qué te aporta">
          <div className="grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-4">
            <Figure label="Nota de mercado" value={dec(note)} sub="sobre 10" />
            <Figure label="Próxima jornada" value={`${dec(xp)} pts`} sub={xp4 !== null ? `${dec(xp4)} en 4 jornadas` : "esperados"} />
            <Figure label="Titular" value={titular === null ? "—" : `${Math.round(titular * 100)} %`} sub="probabilidad" />
            <Figure
              label="En tu once"
              value={improves ? `+${dec(delta)} pts` : "No mejora"}
              tone={improves ? TONE.green : "rgba(255,255,255,0.55)"}
              sub={
                player.replaces?.name
                  ? player.replaces.formation && player.replaces.formation !== player.replaces.formation_from
                    ? `por ${player.replaces.name} · ${player.replaces.formation}`
                    : `por ${player.replaces.name}`
                  : "frente a tu titular"
              }
            />
          </div>
        </Section>

        <Section title="Valor de mercado" aside={trend === null ? "sin previsión" : "previsión a 7 días"}>
          <div className="mb-4 flex items-end justify-between gap-3">
            <p className="text-[1.6rem] font-semibold leading-none tracking-[-0.025em] tabular-nums text-white">{money(value)}</p>
            {trend !== null ? (
              <p className="text-[14px] font-semibold tabular-nums" style={{ color: trendColor }}>
                {gain7 !== null ? `${gain7 > 0 ? "+" : ""}${money(gain7)} · ` : ""}
                {signedPct(trend)}
              </p>
            ) : null}
          </div>
          <ValueChart history={history} today={value} forecast={forecast} trendPct={trend} />
        </Section>

        <Section title="Últimas jornadas" aside={average !== null ? `media ${dec(average)} pts` : undefined}>
          <FormBars weeks={weeks} average={average} />
        </Section>

        {matches.length ? (
          <Section title="Próximos rivales">
            <ul className="grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-4">
              {matches.map((match, index) => {
                const diff = (match.difficulty && DIFF[match.difficulty]) || { label: "Sin dato", color: TONE.gray };
                return (
                  <li key={`${match.opponent}-${index}`} className="flex min-w-0 items-center gap-2.5">
                    <Crest club={match.opponent} size={26} />
                    <div className="min-w-0">
                      <p className="truncate text-[13.5px] font-medium text-white">{match.opponent}</p>
                      <p className="mt-0.5 flex items-center gap-1.5 truncate text-[11.5px] text-white/45">
                        <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: diff.color }} aria-hidden="true" />
                        {diff.label}
                        {match.home === null ? "" : match.home ? " · casa" : " · fuera"}
                      </p>
                    </div>
                  </li>
                );
              })}
            </ul>
          </Section>
        ) : null}

        <div className="border-t border-white/[0.07] px-5 py-4 sm:px-7 sm:py-5">
          <button
            type="button"
            onClick={() => {
              if (player.player_id) setComparing({ id: String(player.player_id), position: player.position });
              onClose();
            }}
            className="h-12 w-full rounded-full bg-white text-[14px] font-semibold text-[#0b0b0b] transition-transform duration-200 ease-out active:scale-[0.98]"
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
