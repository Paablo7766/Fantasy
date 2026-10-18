"use client";

import { useCallback, useEffect, useState } from "react";
import { MarketTable } from "@/components/MarketTable";
import { Pitch } from "@/components/Pitch";
import { RivalsDashboard } from "@/components/RivalsDashboard";
import { SignalDeck } from "@/components/SignalDeck";
import { ErrorCard, Skeleton } from "@/components/Feedback";
import { apiUrl, endpoint, getJson, postJson } from "@/lib/api";
import { eur, glass, points, stamp } from "@/lib/format";
import type { ApiError, DashboardState, NeedsPayload, OptimizePayload, SquadsPayload, TrendsPayload } from "@/lib/types";

const EMPTY: DashboardState = { optimize: null, trends: null, squads: null, needs: null };

function leagueFromLocation(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("league");
}

function failedPayload(reason: unknown): ApiError {
  const payload = typeof reason === "object" && reason !== null ? (reason as { payload?: ApiError }).payload : undefined;
  if (payload && payload.ok === false) return payload;
  const message = reason instanceof Error ? reason.message : "Error de red.";
  return { ok: false, error: { code: "network", message } };
}

export function Dashboard() {
  const [state, setState] = useState<DashboardState>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [connectMessage, setConnectMessage] = useState<string | null>(null);

  const load = useCallback(async (fresh: boolean) => {
    setBusy(true);
    const league = leagueFromLocation();
    const names = ["optimize", "trends", "squads", "needs"] as const;
    const results = await Promise.allSettled(
      names.map((name) => getJson<DashboardState[typeof name]>(endpoint(`/api/${name}`, fresh, league))),
    );
    const next: DashboardState = { ...EMPTY };
    results.forEach((result, index) => {
      const name = names[index];
      next[name] = (result.status === "fulfilled" ? result.value : failedPayload(result.reason)) as never;
    });
    setState(next);
    setBusy(false);
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    void load(params.get("fresh") === "1");
  }, [load]);

  async function connectAccount() {
    setConnecting(true);
    setBusy(true);
    setConnectMessage("Se abre Chrome. Elige tu cuenta de Google.");
    try {
      const data = await postJson<{
        league_saved?: boolean;
        league_id?: string;
        league_name?: string;
        leagues?: Array<{ league_id?: string; name?: string }>;
      }>(apiUrl("/api/auth/browser"));
      if (data.league_saved && data.league_id) {
        setConnectMessage(null);
        await load(true);
        return;
      }
      const lines = (data.leagues || [])
        .map((league) => `${league.league_id || ""} ${league.name || ""}`.trim())
        .join(" · ");
      setConnectMessage(`Tokens guardados. Falta elegir LEAGUE_ID. ${lines || "La cuenta no devolvió una sola liga."}`);
    } catch (error) {
      setConnectMessage(error instanceof Error ? error.message : "No se pudo conectar.");
    } finally {
      setConnecting(false);
      setBusy(false);
    }
  }

  const trends = state.trends?.ok ? state.trends : null;
  const squads = state.squads?.ok ? state.squads : null;
  const optimize = state.optimize?.ok ? state.optimize : null;
  const name = trends?.league_name || squads?.league_name || optimize?.manager_name || "Liga activa";
  const when = trends?.dashboard_at || squads?.dashboard_at || optimize?.dashboard_at || trends?.fetched_at;
  const loading = busy && !state.optimize && !state.needs;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(ellipse_at_top,rgba(52,211,153,0.14),transparent_42%),radial-gradient(ellipse_at_bottom_right,rgba(251,113,133,0.12),transparent_46%)]" />
      <main className="relative mx-auto max-w-7xl px-4 py-6 md:px-8 md:py-8">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="grid h-11 w-11 place-items-center rounded-2xl border border-gold/40 bg-gold/10 font-mono text-sm text-gold">
              LF
            </div>
            <div>
              <p className="text-[11px] uppercase tracking-[0.22em] text-emerald-300/80">LALIGA Fantasy</p>
              <h1 className="text-2xl font-medium tracking-tight">Mesa de mercado</h1>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <div className="text-right">
              <p className="text-sm text-white/80">{name}</p>
              <p className="font-mono text-[11px] text-white/40">{when ? `Actualizado ${stamp(when)}` : ""}</p>
            </div>
            {trends?.partial ? (
              <span className="rounded-full border border-gold/30 bg-gold/10 px-3 py-1 text-[11px] text-gold">
                Lectura parcial
              </span>
            ) : null}
            <button
              type="button"
              onClick={() => void connectAccount()}
              disabled={connecting || busy}
              className="inline-flex items-center gap-2 rounded-full border border-gold/40 bg-gold/15 px-4 py-2 text-sm text-gold backdrop-blur transition hover:bg-gold/25 disabled:opacity-50"
            >
              {connecting ? "Elige tu cuenta en la ventana de Chrome…" : "Conectar cuenta con 1 clic"}
            </button>
            <button
              type="button"
              onClick={() => void load(true)}
              disabled={busy}
              className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-4 py-2 text-sm backdrop-blur transition hover:bg-white/10 disabled:opacity-50"
            >
              Actualizar
            </button>
          </div>
        </header>

        <section className="mt-6" role="status">
          <Banner needs={state.needs} loading={loading} connectMessage={connectMessage} />
        </section>

        <section className="mt-5">
          <SignalDeck squads={state.squads as SquadsPayload | null} loading={loading} />
        </section>

        <div className="mt-5 grid min-w-0 items-start gap-5 lg:grid-cols-12">
          <section className="min-w-0 lg:col-span-7">
            <Pitch optimize={state.optimize as OptimizePayload | null} loading={loading} />
          </section>
          <section className="min-w-0 lg:col-span-5">
            <MarketTable trends={state.trends as TrendsPayload | null} loading={loading} />
          </section>
          <section className="min-w-0 lg:col-span-12">
            <RivalsDashboard
              squads={state.squads as SquadsPayload | null}
              needs={state.needs as NeedsPayload | null}
              loading={loading}
            />
          </section>
        </div>
        <footer className="mt-8 text-xs leading-5 text-white/35">
          Solo lectura. Las horas de cláusula salen de la API en Europe/Madrid, con hora y minuto. Si la marca no viene,
          el tablero no inventa una hora.
        </footer>
      </main>
    </div>
  );
}

function Banner({
  needs,
  loading,
  connectMessage,
}: {
  needs: NeedsPayload | null;
  loading: boolean;
  connectMessage: string | null;
}) {
  if (connectMessage) {
    return (
      <article className={glass("p-6")}>
        <p className="text-[11px] uppercase tracking-[0.18em] text-white/40">Cuenta</p>
        <h2 className="mt-2 text-lg">{connectMessage}</h2>
      </article>
    );
  }
  if (loading) return <Skeleton title="Estado de caja" />;
  if (!needs || needs.ok === false) {
    return <ErrorCard title="Estado de caja" payload={needs || { error: { message: "Sin datos de caja." } }} />;
  }
  const liquidity = needs.liquidity || {};
  const tone =
    liquidity.status === "penalty_risk"
      ? "border-rose-300/40 bg-rose-400/10"
      : liquidity.status === "safe"
        ? "border-emerald-300/30 bg-emerald-400/10"
        : "border-white/15 bg-white/5";
  const alerts = Number(needs.alert_count || 0);
  return (
    <article className={glass(`border ${tone} p-5 md:p-6`)}>
      <div className="flex flex-wrap items-end justify-between gap-6">
        <div className="max-w-xl">
          <p className="text-[11px] uppercase tracking-[0.18em] text-white/45">Estado de caja</p>
          <h2 className="mt-1 text-2xl font-medium tracking-tight">{liquidity.headline || "Caja"}</h2>
          <p className="mt-2 text-sm leading-6 text-white/70">{liquidity.detail || ""}</p>
          {alerts > 0 ? (
            <p className="mt-3 text-sm text-gold">
              {alerts} clausulazo{alerts === 1 ? "" : "s"} con hora de desbloqueo.
            </p>
          ) : null}
        </div>
        <dl className="grid grid-cols-3 gap-6">
          <div>
            <dt className="text-[11px] uppercase tracking-[0.16em] text-white/40">Saldo</dt>
            <dd className="mt-1 font-mono text-xl text-emerald-300 md:text-2xl">{eur(liquidity.cash_eur)}</dd>
          </div>
          <div>
            <dt className="text-[11px] uppercase tracking-[0.16em] text-white/40">Formación</dt>
            <dd className="mt-1 font-mono text-xl md:text-2xl">{liquidity.formation || "s/d"}</dd>
          </div>
          <div>
            <dt className="text-[11px] uppercase tracking-[0.16em] text-white/40">Proyección</dt>
            <dd className="mt-1 font-mono text-xl md:text-2xl">{points(liquidity.expected_points)}</dd>
          </div>
        </dl>
      </div>
    </article>
  );
}
