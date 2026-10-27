"use client";

import { useEffect, useState } from "react";

import { ActionCard } from "@/components/hoy/ActionCard";
import { DashboardHeader } from "@/components/hoy/DashboardHeader";
import { MarketCard } from "@/components/MarketCard";
import { RivalCard } from "@/components/RivalCard";
import { SquadCard } from "@/components/SquadCard";
import { eurShort } from "@/lib/format";
import type { Action, DashboardData, MarketListing, Rival, SquadPlayer } from "@/types/engine";

const EMPTY_DASHBOARD: DashboardData = {
  balance: "—",
  position: "—",
  points: 0,
  gameweek: "—",
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function asNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && !Number.isNaN(value) ? value : fallback;
}

function mapDashboard(raw: unknown): DashboardData {
  const row = asRecord(raw);
  if (!row) return EMPTY_DASHBOARD;
  return {
    balance: asString(row.balance ?? row.cash ?? row.liquidity, "—"),
    position: asString(row.position ?? row.rank_label, "—"),
    points: asNumber(row.points ?? row.total_points, 0),
    gameweek: asString(row.gameweek ?? row.gameweek_id ?? row.jornada, "—"),
  };
}

function mapTrend(row: Record<string, unknown>): MarketListing["trend"] {
  const nested = asRecord(row.trend);
  if (nested) {
    return {
      text: asString(nested.text, "—"),
      isUp: nested.isUp === true || nested.is_up === true,
    };
  }
  const delta = asNumber(
    row.daily_trend ?? row.tendencia ?? row.own_predicted_delta ?? row.price_delta,
    0,
  );
  if (delta === 0) return { text: "—", isUp: false };
  return { text: `${delta > 0 ? "+" : ""}${eurShort(delta)} hoy`, isUp: delta > 0 };
}

function mapAnalysis(row: Record<string, unknown>): MarketListing["analysis"] {
  const nested = asRecord(row.analysis);
  if (nested) {
    return {
      text: asString(nested.text, "—"),
      isPositive: nested.isPositive === true || nested.is_positive === true,
    };
  }
  const rec = asString(row.recommendation ?? row.verdict, "");
  const positive = /SELL|VENDER|STRONG_SELL|LIQUIDATE/i.test(rec);
  return {
    text: rec || asString(row.reason ?? row.label, "Sin análisis"),
    isPositive: positive,
  };
}

function mapMarketListing(row: unknown, index: number): MarketListing {
  const item = asRecord(row) ?? {};
  const id = asString(item.id ?? item.player_id ?? item.jugador_id, `market-${index}`);
  const offerEur = asNumber(item.offer_eur ?? item.recommendedBid ?? item.oferta_sistema, 0);
  const marketEur = asNumber(item.market_value ?? item.valor_mercado ?? item.price_eur, 0);
  return {
    id,
    name: asString(item.name ?? item.nickname, "Jugador"),
    position: asString(item.position, "—"),
    team: asString(item.team ?? item.club, "—"),
    probability: asString(item.probability, "—"),
    price: asString(item.price, marketEur > 0 ? eurShort(marketEur) : "—"),
    trend: mapTrend(item),
    recommendedBid: asString(item.recommendedBid, offerEur > 0 ? eurShort(offerEur) : "—"),
    analysis: mapAnalysis(item),
  };
}

function mapAction(row: unknown, index: number): Action {
  const item = asRecord(row) ?? {};
  const rawType = asString(item.type, "wait").toLowerCase();
  const type: Action["type"] =
    rawType === "buy" || rawType === "sell" || rawType === "wait" ? rawType : "wait";
  return {
    id: asString(item.id, `action-${index}`),
    type,
    title: asString(item.title ?? item.what, "Acción pendiente"),
    subtitle: asString(item.subtitle ?? item.when ?? item.ignore, ""),
    value: asString(item.value ?? item.cost, "—"),
  };
}

function mapSquadPlayer(row: unknown, index: number): SquadPlayer {
  const item = asRecord(row) ?? {};
  const rawStatus = asString(item.matchStatus ?? item.match_status, "pending");
  const matchStatus: SquadPlayer["matchStatus"] =
    rawStatus === "playing" || rawStatus === "finished" || rawStatus === "pending"
      ? rawStatus
      : "pending";
  return {
    id: asString(item.id ?? item.player_id, `squad-${index}`),
    name: asString(item.name ?? item.nickname, "Jugador"),
    position: asString(item.position, "—"),
    team: asString(item.team ?? item.club, "—"),
    pointsExpected: asNumber(item.pointsExpected ?? item.expected_points ?? item.jornada_ev, 0),
    isStarter: item.isStarter === true || item.is_starter === true || item.starter === true,
    matchStatus,
    matchTime: asString(item.matchTime ?? item.match_time ?? item.kickoff, "—"),
    price: asString(item.price, eurShort(asNumber(item.market_value ?? item.fantasy_price, 0))),
  };
}

function mapRival(row: unknown, index: number): Rival {
  const item = asRecord(row) ?? {};
  return {
    id: asString(item.id ?? item.team_id, `rival-${index}`),
    rank: asNumber(item.rank ?? item.position, index + 1),
    name: asString(item.name ?? item.team_name, "Rival"),
    points: asNumber(item.points, 0),
    maxBid: asString(item.maxBid ?? item.max_bid, "—"),
    squadValue: asString(item.squadValue ?? item.squad_value, "—"),
  };
}

type TabId = "hoy" | "equipo" | "mercado" | "liga";

const TABS: { id: TabId; label: string }[] = [
  { id: "hoy", label: "Hoy" },
  { id: "equipo", label: "Equipo" },
  { id: "mercado", label: "Mercado" },
  { id: "liga", label: "Liga" },
];

function TabIcon({ tab }: { tab: TabId }) {
  const common = {
    viewBox: "0 0 24 24",
    className: "h-5 w-5",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    "aria-hidden": true as const,
  };
  if (tab === "hoy") {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="7" />
        <path d="M12 8v4l2.5 1.6" strokeLinecap="round" />
      </svg>
    );
  }
  if (tab === "equipo") {
    return (
      <svg {...common}>
        <circle cx="12" cy="8" r="2.2" />
        <circle cx="7" cy="13" r="2.2" />
        <circle cx="17" cy="13" r="2.2" />
        <circle cx="12" cy="18" r="2.2" />
      </svg>
    );
  }
  if (tab === "mercado") {
    return (
      <svg {...common}>
        <path d="M4 10h16l-1.2 8H5.2L4 10Z" strokeLinejoin="round" />
        <path d="M8 9.8 9.5 5h5L16 9.8" strokeLinecap="round" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <path d="M5 18V8l7-4 7 4v10" strokeLinejoin="round" />
      <path d="M9 18v-5h6v5" strokeLinejoin="round" />
    </svg>
  );
}

export default function HoyPage() {
  const [activeTab, setActiveTab] = useState<"hoy" | "equipo" | "mercado" | "liga">("hoy");
  const [loading, setLoading] = useState(true);
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [actions, setActions] = useState<Action[]>([]);
  const [market, setMarket] = useState<MarketListing[]>([]);
  const [squad, setSquad] = useState<SquadPlayer[]>([]);
  const [league, setLeague] = useState<Rival[]>([]);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await fetch("/api/market-maker");
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const data = (await response.json()) as Record<string, unknown>;

        setDashboard(mapDashboard(data.dashboard ?? data));
        setActions(asArray(data.actions ?? data.priority_actions).map(mapAction));
        setMarket(
          asArray(data.market ?? data.offers ?? data.listings).map(mapMarketListing),
        );
        setSquad(asArray(data.squad ?? data.players).map(mapSquadPlayer));
        setLeague(asArray(data.league ?? data.rivals ?? data.standings).map(mapRival));
      } catch (error) {
        console.error("Error cargando datos del motor:", error);
        setDashboard(EMPTY_DASHBOARD);
        setActions([]);
        setMarket([]);
        setSquad([]);
        setLeague([]);
      } finally {
        setLoading(false);
      }
    };

    void fetchData();
  }, []);

  if (loading) {
    return (
      <div className="flex min-h-[50vh] flex-col items-center justify-center bg-gray-950">
        <p className="animate-pulse text-lg font-medium text-emerald-400">
          Sincronizando motor cuantitativo...
        </p>
      </div>
    );
  }

  if (!dashboard) {
    return null;
  }

  return (
    <div className="hoy-root flex min-w-0 flex-col pb-24">
      {activeTab === "hoy" ? (
        <>
          <DashboardHeader dashboard={dashboard} />

          <h2 className="mb-4 mt-6 text-sm font-bold tracking-wider text-gray-500">PLAN DE FICHAJES</h2>

          {actions.map((action) => (
            <ActionCard key={action.id} {...action} />
          ))}
        </>
      ) : null}

      {activeTab === "mercado" ? (
        <>
          <h2 className="mb-4 mt-2 text-sm font-bold tracking-wider text-gray-500">MERCADO HOY</h2>

          {market.map((player) => (
            <MarketCard key={player.id} {...player} />
          ))}
        </>
      ) : null}

      {activeTab === "equipo" ? (
        <>
          <div className="sticky top-0 z-40 -mx-4 mb-4 border-b border-gray-800/80 bg-gray-950/75 px-4 py-3 backdrop-blur-md">
            <p className="text-sm text-gray-400">Tu once para la jornada:</p>
            <p className="text-lg font-bold text-emerald-400">31,9 → 40,8 pts</p>
          </div>

          <h2 className="mb-3 text-sm font-bold tracking-wider text-gray-500">ONCE TITULAR</h2>
          {squad
            .filter((p) => p.isStarter)
            .map((player) => (
              <SquadCard key={player.id} {...player} />
            ))}

          <h2 className="mb-3 mt-6 text-sm font-bold tracking-wider text-gray-500">BANQUILLO</h2>
          {squad
            .filter((p) => !p.isStarter)
            .map((player) => (
              <SquadCard key={player.id} {...player} />
            ))}
        </>
      ) : null}

      {activeTab === "liga" ? (
        <>
          <h2 className="mb-4 mt-2 text-sm font-bold tracking-wider text-gray-500">
            CLASIFICACIÓN Y LIQUIDEZ
          </h2>
          {league.map((rival) => (
            <RivalCard key={rival.id} {...rival} isSelf={rival.id === "rival-self"} />
          ))}
        </>
      ) : null}

      <nav
        className="fixed inset-x-0 bottom-0 z-50 border-t border-gray-800 bg-gray-950/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-md"
        aria-label="Navegación principal"
      >
        <div className="mx-auto flex max-w-lg items-stretch justify-around px-2 pt-2">
          {TABS.map((tab) => {
            const active = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={`flex min-w-0 flex-1 flex-col items-center gap-1 px-2 py-2 text-[11px] font-medium transition-colors ${
                  active ? "text-emerald-400" : "text-gray-500"
                }`}
                aria-current={active ? "page" : undefined}
              >
                <TabIcon tab={tab.id} />
                <span>{tab.label}</span>
              </button>
            );
          })}
        </div>
      </nav>
    </div>
  );
}
