"use client";

import { useMemo, useState } from "react";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { eur, glass, playerName } from "@/lib/format";
import type { RivalPlayer } from "@/lib/types";

/** Oferta de referencia: el sistema se mueve dentro de ±10 % del valor de mercado. */
const SPREAD_MIN = -0.10;
const SPREAD_MAX = 0.10;
/** Ventana rápida de ofertas del Computer: uniforme ±5 % (regla de sellado rápido). */
const QUICK_SPREAD = 0.05;
const QUICK_INSTANT_SELL = 0.03;
const QUICK_ACCEPT = 0.01;

type QuickAction = "INSTANT_SELL" | "ACCEPT" | "HOLD" | "SELL_FOR_LIQUIDITY";

const ACTION_TONE: Record<QuickAction, { box: string; text: string }> = {
  INSTANT_SELL: { box: "border-[color:var(--mint)]/50 bg-[color:var(--mint-soft)]/50", text: "text-mint" },
  ACCEPT: { box: "border-[color:var(--mint)]/30 bg-[color:var(--mint-soft)]/30", text: "text-mint" },
  SELL_FOR_LIQUIDITY: { box: "border-[color:var(--gold)]/50 bg-[color:var(--gold-soft)]/40", text: "text-[color:var(--gold)]" },
  HOLD: { box: "border-[color:var(--coral)]/40 bg-[color:var(--coral-soft)]/30", text: "text-coral" },
};

/**
 * Regla rápida del Computer: distribución uniforme de VM ± 5 %.
 * Se replica en la app lo mismo que hace ``scripts/eval_ofertas_maquina.py``:
 * un único criterio, sin motor, para decidir en segundos.
 */
function quickAction(marketValue: number, offer: number, forceLiquidity: boolean) {
  if (marketValue <= 0 || offer <= 0) return null;
  const deviation = (offer - marketValue) / marketValue;
  const low = marketValue * (1 - QUICK_SPREAD);
  const high = marketValue * (1 + QUICK_SPREAD);
  let action: QuickAction;
  if (deviation > QUICK_INSTANT_SELL) action = "INSTANT_SELL";
  else if (deviation > QUICK_ACCEPT) action = "ACCEPT";
  else if (forceLiquidity) action = "SELL_FOR_LIQUIDITY";
  else action = "HOLD";
  return {
    deviation,
    low,
    high,
    action,
    insideSpread: offer >= low && offer <= high,
  };
}

function pct(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? `${value > 0 ? "+" : ""}${value.toFixed(2)} %` : "—";
}

function OfferRow({ player, onUse }: { player: RivalPlayer; onUse: (player: RivalPlayer) => void }) {
  const value = typeof player.market_value === "number" && player.market_value > 0 ? player.market_value : null;
  const [offer, setOffer] = useState<string>("");
  const amount = Number(offer.replace(/[^\d]/g, ""));
  const valid = Number.isFinite(amount) && amount > 0;
  const quick = value && valid ? quickAction(value, amount, false) : null;
  const tone = quick ? ACTION_TONE[quick.action] : null;

  return (
    <li className={`rounded-2xl border px-3 py-3 ${tone ? tone.box : "border-[color:var(--line)] bg-[color:var(--surface-strong)]"}`}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <PlayerAvatar player={player} size="sm" />
          <div className="min-w-0">
            <p className="truncate font-medium tracking-tight text-ink">{playerName(player)}</p>
            <p className="text-[11px] text-faint">
              VM {eur(value)} · hueco ±5 %: {value ? `${eur(value * (1 - QUICK_SPREAD))} – ${eur(value * (1 + QUICK_SPREAD))}` : "s/d"}
            </p>
          </div>
        </div>
        <input
          type="text"
          inputMode="numeric"
          value={offer}
          onChange={(event) => setOffer(event.target.value.replace(/[^\d]/g, ""))}
          onFocus={() => (offer === "" ? onUse(player) : undefined)}
          placeholder="oferta €"
          aria-label={`Oferta recibida por ${playerName(player)}`}
          className="w-28 shrink-0 rounded-lg border border-[color:var(--line-strong)] bg-[color:var(--surface)] px-2 py-1.5 text-right font-mono text-xs text-ink outline-none focus:border-[color:var(--gold)]"
        />
      </div>
      {quick && tone ? (
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11px]">
          <span className={`font-semibold tracking-tight ${tone.text}`}>{quick.action}</span>
          <span className="font-mono text-muted-strong">
            {pct(quick.deviation * 100)} · {quick.insideSpread ? "dentro de ±5 %" : "fuera de ±5 %"}
          </span>
        </div>
      ) : (
        <p className="mt-2 text-[11px] text-faint">Escribe la oferta del Computer para el veredicto rápido.</p>
      )}
    </li>
  );
}

export function ComputerOffersPanel({ players }: { players: RivalPlayer[] }) {
  const [force, setForce] = useState(false);
  const [marketValue, setMarketValue] = useState("");
  const [offer, setOffer] = useState("");

  const mv = Number(marketValue.replace(/[^\d]/g, ""));
  const of = Number(offer.replace(/[^\d]/g, ""));
  const manual = useMemo(
    () => (mv > 0 && of > 0 ? quickAction(mv, of, force) : null),
    [mv, of, force],
  );

  const sorted = useMemo(() => {
    return players
      .filter((player) => typeof player.market_value === "number" && (player.market_value ?? 0) > 0)
      .slice()
      .sort((a, b) => (b.market_value ?? 0) - (a.market_value ?? 0));
  }, [players]);

  return (
    <article className={glass("p-4 md:p-5")}>
      <div className="mb-1 flex flex-wrap items-end justify-between gap-2">
        <div>
          <p className="eyebrow">Computer</p>
          <h3 className="section-title mt-1 text-[1.05rem]">Ofertas de la máquina</h3>
          <p className="section-support">
            La máquina ofrece una distribución uniforme del valor de mercado ±5 %. Pega la oferta y la app te dice si
            vender ya, aceptar o aguantar. Nada se envía a la liga desde aquí.
          </p>
        </div>
        <label className="flex items-center gap-2 text-[11px] text-muted-strong">
          <input type="checkbox" checked={force} onChange={(event) => setForce(event.target.checked)} />
          Forzar liquidez
        </label>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <label className="text-[11px] text-faint">
          Valor de mercado
          <input
            type="text"
            inputMode="numeric"
            value={marketValue}
            onChange={(event) => setMarketValue(event.target.value.replace(/[^\d]/g, ""))}
            placeholder="10.000.000"
            className="mt-1 w-full rounded-lg border border-[color:var(--line-strong)] bg-[color:var(--surface)] px-2 py-1.5 font-mono text-xs text-ink outline-none focus:border-[color:var(--gold)]"
          />
        </label>
        <label className="text-[11px] text-faint">
          Oferta recibida
          <input
            type="text"
            inputMode="numeric"
            value={offer}
            onChange={(event) => setOffer(event.target.value.replace(/[^\d]/g, ""))}
            placeholder="10.320.000"
            className="mt-1 w-full rounded-lg border border-[color:var(--line-strong)] bg-[color:var(--surface)] px-2 py-1.5 font-mono text-xs text-ink outline-none focus:border-[color:var(--gold)]"
          />
        </label>
      </div>

      {manual ? (
        <div className={`mt-3 rounded-2xl border px-3 py-2.5 ${ACTION_TONE[manual.action].box}`}>
          <p className={`text-sm font-semibold tracking-tight ${ACTION_TONE[manual.action].text}`}>{manual.action}</p>
          <p className="mt-0.5 font-mono text-[11px] text-muted-strong">
            Desviación {pct(manual.deviation * 100)} · horquilla {eur(manual.low)} – {eur(manual.high)} ·{" "}
            {manual.insideSpread ? "dentro de ±5 %" : "fuera de ±5 %"}
          </p>
          <p className="mt-1 text-[11px] text-faint">
            Regla: &gt;+3 % vender ya · &gt;+1 % aceptar · ≤ +1 % aguantar (salvo liquidez forzada).
          </p>
        </div>
      ) : null}

      <ul className="mt-4 grid gap-2 md:grid-cols-2">
        {sorted.length ? (
          sorted.map((player) => (
            <OfferRow
              key={String(player.player_id)}
              player={player}
              onUse={(row) => setMarketValue(String(row.market_value ?? ""))}
            />
          ))
        ) : (
          <li className="rounded-xl border border-dashed border-[color:var(--line-strong)] px-3 py-4 text-sm text-muted">
            Tu plantilla aún no trae valores de mercado.
          </li>
        )}
      </ul>

      <p className="mt-3 text-[10px] leading-4 text-faint">
        Referencia del motor completo (percentil de la oferta y EV de mañana, banda ±{Math.round(SPREAD_MAX * 100)} %):
        comando <span className="font-mono">python scripts/eval_ofertas_maquina.py</span> o la tarjeta de auditoría del
        día. Esta tarjeta es la regla rápida del ±{Math.round(QUICK_SPREAD * 100)} %.
      </p>
    </article>
  );
}
