"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { DashboardHeader } from "@/components/hoy/DashboardHeader";
import { Recommendations } from "@/components/hoy/Recommendations";
import { useDashboard } from "@/components/DashboardProvider";
import { RivalCard } from "@/components/RivalCard";
import { SquadCard } from "@/components/SquadCard";
import { eurShort, jornadaEv, points } from "@/lib/format";
import type { Player } from "@/lib/types";
import type { DashboardData, Rival, SquadPlayer } from "@/types/engine";

type TabId = "hoy" | "equipo" | "mercado" | "liga";

const TABS: { id: TabId; label: string }[] = [
  { id: "hoy", label: "Hoy" },
  { id: "equipo", label: "Mi equipo" },
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
        <path d="M13 3 6 13h5l-1 8 8-12h-6l1-6Z" strokeLinejoin="round" />
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
      <path d="M7 18V8l5-3 5 3v10" strokeLinejoin="round" />
      <path d="M10 18v-4h4v4" />
    </svg>
  );
}

function asSquad(player: Player, starter: boolean, index: number): SquadPlayer {
  const ev = jornadaEv(player);
  return {
    id: player.player_id || `squad-${index}`,
    name: player.nickname || player.name || "Jugador",
    position: player.position || "—",
    team: player.club || "—",
    pointsExpected: ev ?? 0,
    isStarter: starter,
    matchStatus: "pending",
    matchTime: "—",
    price: eurShort(player.market_value),
  };
}

export default function HoyPage() {
  const { plan, optimize, trends, squads, pending, busy, photoAge, leagueName } = useDashboard();
  const query = useSearchParams().toString();
  const [activeTab, setActiveTab] = useState<TabId>("hoy");
  const loading = pending.plan || pending.trends || (!plan && busy);

  const dashboard = useMemo<DashboardData>(() => {
    const table = plan?.league_race?.table || [];
    const rank = plan?.mode?.own_rank;
    const size = table.length;
    const pointsTotal = plan?.mode?.own_points;
    const cash = plan?.cash_eur ?? squads?.self?.cash_eur;
    return {
      balance: typeof cash === "number" ? eurShort(cash) : "—",
      position: typeof rank === "number" ? (size > 0 ? `${rank}º/${size}` : `${rank}º`) : "—",
      points: typeof pointsTotal === "number" ? pointsTotal : Number.NaN,
      gameweek: "—",
    };
  }, [plan, squads]);

  const squad = useMemo(() => {
    const xi = optimize?.xi || [];
    const bench = optimize?.benched || [];
    return {
      xi: xi.map((player, index) => asSquad(player, true, index)),
      bench: bench.map((player, index) => asSquad(player, false, index)),
    };
  }, [optimize]);

  const league = useMemo<Rival[]>(() => {
    const rows = plan?.league_race?.table || [];
    return rows.map((row, index) => ({
      id: row.team_id || `rival-${index}`,
      rank: row.rank ?? index + 1,
      name: row.manager_name || row.fantasy_team_name || "Rival",
      points: row.points ?? 0,
      maxBid: typeof row.cash_eur === "number" ? eurShort(row.cash_eur) : "—",
      squadValue: typeof row.player_count === "number" ? `${row.player_count} jug.` : "—",
    }));
  }, [plan]);

  const selfId = squads?.self?.team_id || null;
  const saved = plan?.lineup?.saved_points;
  const next = plan?.lineup?.expected_points;

  return (
    <div className="hoy-root mx-auto flex min-w-0 max-w-lg flex-col pb-24 lg:pb-8">
      <DashboardHeader
        dashboard={dashboard}
        leagueName={leagueName}
        age={photoAge || null}
      />

      {activeTab === "hoy" ? (
        <Recommendations plan={plan} optimize={optimize} trends={trends} squads={squads} loading={loading} />
      ) : null}

      {activeTab === "equipo" ? (
        <div className="mt-5">
          {typeof saved === "number" || typeof next === "number" ? (
            <p className="rec-footer mb-4">
              Tu once para la jornada:{" "}
              <strong className="font-semibold text-white">
                {typeof saved === "number" ? points(saved) : "s/d"}
                {typeof next === "number" ? ` → ${points(next)} pts` : ""}
              </strong>
            </p>
          ) : null}
          <h2 className="mb-2 text-[11px] font-bold tracking-[0.14em] text-[#8d97aa]">ONCE TITULAR</h2>
          {squad.xi.length === 0 ? <p className="text-sm text-[#9aa3b5]">El once todavía no está en la foto.</p> : null}
          {squad.xi.map((player) => (
            <SquadCard key={player.id} {...player} />
          ))}
          <h2 className="mb-2 mt-6 text-[11px] font-bold tracking-[0.14em] text-[#8d97aa]">BANQUILLO</h2>
          {squad.bench.map((player) => (
            <SquadCard key={player.id} {...player} />
          ))}
        </div>
      ) : null}

      {activeTab === "mercado" ? (
        <div className="mt-5">
          <p className="text-[13px] leading-5 text-[#9aa3b5]">
            Las pujas, las esperas y los precios viven en Mercado. Aquí solo está el plan del día.
          </p>
          <Link href={query ? `/mercado?${query}` : "/mercado"} className="rec-btn mt-3 inline-flex">
            Abrir mercado
          </Link>
        </div>
      ) : null}

      {activeTab === "liga" ? (
        <div className="mt-5">
          <h2 className="mb-3 text-[11px] font-bold tracking-[0.14em] text-[#8d97aa]">CLASIFICACIÓN</h2>
          {league.length === 0 ? <p className="text-sm text-[#9aa3b5]">La tabla todavía no está en la foto.</p> : null}
          {league.map((rival) => (
            <RivalCard key={rival.id} {...rival} isSelf={rival.id === selfId} />
          ))}
        </div>
      ) : null}

      <nav
        className="fixed inset-x-0 bottom-0 z-50 border-t border-white/10 bg-[#07090e]/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-md lg:hidden"
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
                className={`flex min-w-0 flex-1 flex-col items-center gap-1 px-2 py-2 text-[11px] font-medium ${
                  active ? "text-[#3ee0a0]" : "text-[#6e788b]"
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
