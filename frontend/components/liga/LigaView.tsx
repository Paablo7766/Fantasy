"use client";

import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useJson } from "@/lib/core/useJson";
import { points } from "@/lib/core/format";
import { applyLiquidity, financialIndex, liquidityRead } from "@/lib/liga/liquidity";
import { SEASON_ROUNDS, paceLines } from "@/lib/liga/pace";
import { enrichSquadsPayload } from "@/lib/liga/squadEnrich";
import { squadTotals } from "@/lib/liga/squadTotals";
import type { PhotoIndex } from "@/lib/core/photoIndex";
import { clauseThreats } from "@/lib/liga/threats";
import type { LeagueEdge, LeagueFormPayload, LeagueFormRow, LeagueProjection, LeagueRacePayload, RivalIntelPayload, RivalSquad, SquadsPayload, TrendsPayload } from "@/lib/types";
import { Empty, Skeleton, TONE } from "@/components/ui/kit";
import { AlertsPanel } from "./AlertsPanel";
import { HeadToHeadCard } from "./HeadToHeadCard";
import { RivalDialog } from "./RivalDialog";
import { RoundsTable } from "./RoundsTable";
import { StandingsTable, type StandingRow } from "./StandingsTable";
import { rivalLabel } from "./dashboard/shared";
import { Tile } from "./parts";

type Tab = "clasificacion" | "jornadas" | "duelo" | "alertas";

const MODE: Record<string, { label: string; color: string; text: string }> = {
  ventaja: { label: "Vas por delante", color: TONE.green, text: "Tu once busca puntos seguros: titulares fijos antes que apuestas." },
  remontada: { label: "Toca remontar", color: TONE.copper, text: "Tu once busca techo: jugadores capaces de dar muchos puntos aunque sean más arriesgados." },
  neutro: { label: "Carrera igualada", color: TONE.blue, text: "Ni ventaja ni remontada: el once equilibra suelo y techo." },
};

function cashOf(squad: RivalSquad): number | null {
  const read = liquidityRead(squad);
  return read.calibratedCash ?? read.cash ?? squad.cash_eur ?? null;
}

/**
 * La carrera en una línea: cada mánager es un punto colocado por sus puntos.
 * Se nombran el líder (arriba) y tú (abajo); el resto se lee al pasar el ratón.
 */
function RaceStrip({ rows }: { rows: StandingRow[] }) {
  const ranked = rows.filter((row): row is StandingRow & { points: number } => row.points !== null);
  if (ranked.length < 2) return null;
  const min = Math.min(...ranked.map((row) => row.points));
  const max = Math.max(...ranked.map((row) => row.points));
  if (max === min) return null;
  const at = (value: number) => 2 + ((value - min) / (max - min)) * 96;
  const leader = ranked.reduce((best, row) => (row.points > best.points ? row : best));
  const own = ranked.find((row) => row.self) || null;
  const anchor = (pct: number) => (pct > 82 ? "-translate-x-full" : pct < 18 ? "" : "-translate-x-1/2");
  return (
    <div className="relative mt-6 h-[4.25rem]" role="img" aria-label={`Carrera de la liga: de ${min} a ${max} puntos${own ? `; tú llevas ${own.points}` : ""}`}>
      <span className="absolute inset-x-0 top-1/2 h-px bg-white/15" aria-hidden="true" />
      {ranked.map((row) =>
        row.self || row.id === leader.id ? null : (
          <span
            key={row.id}
            title={`${row.name}: ${row.points} pts`}
            className="absolute top-1/2 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white/45"
            style={{ left: `${at(row.points)}%` }}
          />
        ),
      )}
      {!leader.self ? (
        <>
          <span className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white" style={{ left: `${at(leader.points)}%` }} aria-hidden="true" />
          <span className={`absolute top-0 whitespace-nowrap text-[11.5px] tabular-nums text-white/55 ${anchor(at(leader.points))}`} style={{ left: `${at(leader.points)}%` }}>
            {leader.name} · <span className="font-medium text-white">{leader.points}</span>
          </span>
        </>
      ) : null}
      {own ? (
        <>
          <span
            className="absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[#FFC08A] shadow-[0_0_0_4px_rgba(255,192,138,0.18)]"
            style={{ left: `${at(own.points)}%` }}
            aria-hidden="true"
          />
          <span className={`absolute bottom-0 whitespace-nowrap text-[11.5px] tabular-nums text-[#FFC08A] ${anchor(at(own.points))}`} style={{ left: `${at(own.points)}%` }}>
            Tú · <span className="font-medium">{own.points}</span>
          </span>
        </>
      ) : null}
    </div>
  );
}

/* ── Vista ──────────────────────────────────────────────────────────────── */

export function LigaView({
  squads,
  trends,
  photos,
  loading,
}: {
  squads: SquadsPayload | null;
  trends: TrendsPayload | null;
  photos: PhotoIndex;
  loading: boolean;
}) {
  const search = useSearchParams();
  const league = search.get("league");
  const race = useJson<LeagueRacePayload>("/api/league-race", league);
  const rivalIntel = useJson<RivalIntelPayload>("/api/rival-intel", league);
  const form = useJson<LeagueFormPayload>("/api/league-form", league);
  const [tab, setTab] = useState<Tab>(() => {
    const asked = search.get("tab");
    return asked === "jornadas" || asked === "duelo" || asked === "alertas" ? asked : "clasificacion";
  });
  const [selected, setSelected] = useState<string | null>(null);

  const view = useMemo(() => enrichSquadsPayload(squads, trends), [squads, trends]);
  const financials = useMemo(() => financialIndex(rivalIntel?.ok === false ? null : rivalIntel?.teams), [rivalIntel]);
  const all = useMemo(() => {
    const rows = (view?.rivals || []).map((row) => applyLiquidity(row, financials.get(String(row.team_id)))).filter((row): row is RivalSquad => row !== null);
    const own = applyLiquidity(view?.self, view?.self ? financials.get(String(view.self.team_id)) : null);
    return { rows: own ? [...rows, own] : rows, own };
  }, [view, financials]);

  const raceOk = race && race.ok !== false ? race : null;
  const mode = raceOk?.mode ?? null;
  const mine = raceOk?.my_projection ?? null;
  const ownId = all.own?.team_id != null ? String(all.own.team_id) : null;
  const ownRank = mode?.own_rank ?? all.own?.rank ?? null;
  const ownPoints = mode?.own_points ?? all.own?.points ?? null;

  const formRows = useMemo(() => (form && form.ok !== false ? form.rows || [] : []), [form]);
  const formWindow = form?.recent_window ?? 3;

  const standings = useMemo<StandingRow[]>(() => {
    const formById = new Map<string, LeagueFormRow>(formRows.filter((row) => row.team_id != null).map((row) => [String(row.team_id), row]));
    const projections = new Map<string, LeagueProjection | null | undefined>((raceOk?.rivals || []).map((row) => [String(row.team_id), row.projection]));
    return all.rows.map((squad) => {
      const id = String(squad.team_id);
      const self = ownId !== null && id === ownId;
      const name = rivalLabel(squad);
      const projection = self ? mine : projections.get(id);
      const totals = squadTotals(squad);
      const read = liquidityRead(squad);
      return {
        id,
        self,
        name,
        team: squad.fantasy_team_name && squad.fantasy_team_name !== name ? squad.fantasy_team_name : null,
        rank: typeof squad.rank === "number" ? squad.rank : null,
        points: typeof squad.points === "number" ? squad.points : null,
        gap: !self && typeof squad.points === "number" && typeof ownPoints === "number" ? squad.points - ownPoints : null,
        form: formById.get(id) ?? (self ? (formRows.find((row) => row.is_self) ?? null) : null),
        projection: typeof projection?.expected_points === "number" ? projection.expected_points : null,
        ceiling: typeof projection?.ceiling_points === "number" ? projection.ceiling_points : null,
        cash: read.calibratedCash ?? read.cash ?? squad.cash_eur ?? null,
        bidLimit: read.bidLimit,
        teamValue: totals.market_value_total,
        delta: totals.price_delta_day ?? null,
      };
    });
  }, [all, formRows, raceOk, mine, ownId, ownPoints]);

  // Si la carrera no responde, el de arriba y el de abajo salen de la
  // clasificación, que ya está en las plantillas.
  const standingEdge = (offset: -1 | 1): LeagueEdge | null => {
    const own = all.own;
    if (!own || typeof own.points !== "number") return null;
    const ranked = all.rows.filter((row) => typeof row.points === "number").sort((a, b) => (b.points as number) - (a.points as number));
    const index = ranked.findIndex((row) => String(row.team_id) === String(own.team_id));
    const other = index >= 0 ? ranked[index + offset] : undefined;
    if (!other || typeof other.points !== "number") return null;
    return { team_id: String(other.team_id), manager_name: rivalLabel(other), rank: other.rank ?? null, points: other.points, edge_points: own.points - other.points };
  };
  const above = mode?.above ?? standingEdge(-1);
  const below = mode?.below ?? standingEdge(1);

  // El cara a cara solo depende de /api/league-race. Las plantillas llegan
  // después de trends/optimize/needs (y el solver corre en cada GET de squads),
  // así que no se esperan: el duelo sale en cuanto responde la carrera.
  const headToHeadCard = raceOk ? (
    <HeadToHeadCard mine={mine} rivals={raceOk.rivals || []} defaultId={String((ownRank === 1 ? below : above)?.team_id ?? "") || null} photos={photos} />
  ) : null;

  if (loading && !squads) {
    return (
      <div className="flex min-w-0 flex-col gap-4">
        {headToHeadCard}
        <Skeleton />
      </div>
    );
  }
  if (!view || view.ok === false || !all.rows.length) {
    return <Empty title="Sin clasificación" detail="Pulsa Actualizar para leer las plantillas de tu liga." />;
  }

  const leaderGap = ownRank === 1 ? 0 : typeof mode?.gap_to_leader === "number" ? Math.abs(mode.gap_to_leader) : null;
  const posture = mode ? MODE[mode.name] : null;
  const leagueAvg = typeof raceOk?.league_projection === "number" ? raceOk.league_projection : null;
  const thin = (raceOk?.rivals || []).filter((row) => (row.thin_positions || []).length).sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999));
  const denial = raceOk?.denial || [];
  const threats = clauseThreats(all.own, all.rows);
  const selectedSquad = selected ? all.rows.find((row) => String(row.team_id) === selected) || null : null;
  const myForm = formRows.find((row) => row.is_self) || null;
  const pace = paceLines(formRows, above, below, SEASON_ROUNDS - (form?.rounds?.at(-1) ?? SEASON_ROUNDS));

  const gapLine = (() => {
    if (ownRank === 1) {
      return below && typeof below.edge_points === "number" ? `Vas líder con ${Math.abs(below.edge_points)} pts sobre ${below.manager_name || "el 2º"}.` : "Vas líder.";
    }
    if (leaderGap !== null) return `A ${leaderGap} pts del líder${mode?.leader?.manager_name ? `, ${mode.leader.manager_name}` : ""}.`;
    return null;
  })();
  const nextLine =
    typeof mine?.expected_points === "number"
      ? `Próxima jornada: tu once apunta a ${points(mine.expected_points)} pts${leagueAvg !== null ? `, frente a ${points(leagueAvg)} de media en la liga` : ""}.`
      : null;
  // La frase principal acompaña al puesto; el resto del ritmo va bajo la carrera.
  const lead = nextLine || pace[0] || null;
  const footnote = (nextLine ? pace : pace.slice(1)).join(" ");

  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: "clasificacion", label: "Clasificación" },
    { id: "jornadas", label: "Jornadas" },
    { id: "duelo", label: "Cara a cara" },
    { id: "alertas", label: "Alertas", count: threats.length || undefined },
  ];

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <section className="home-feature" aria-label="Tu posición en la liga">
        <div className="relative flex items-center justify-between gap-3">
          <p className="text-[13px] font-medium text-white/65">Tu posición</p>
          {posture ? (
            <p className="flex min-w-0 items-center gap-2 text-[12.5px] text-white/70" title={posture.text}>
              <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: posture.color }} aria-hidden="true" />
              <span className="truncate">{posture.label}</span>
            </p>
          ) : null}
        </div>
        <div className="mt-3 grid gap-5 min-[900px]:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)] min-[900px]:items-end">
          <div className="min-w-0">
            <p className="flex items-baseline gap-2.5 tabular-nums">
              <span className="text-[3.1rem] font-semibold leading-none tracking-[-0.045em] text-white">{typeof ownRank === "number" ? `${ownRank}º` : "—"}</span>
              <span className="text-base font-medium text-white/65">de {all.rows.length}</span>
            </p>
            {gapLine || lead ? (
              <p className="mt-3 max-w-[48ch] text-[13.5px] leading-snug tabular-nums text-white/65">
                {gapLine ? <span className="font-semibold text-white">{gapLine} </span> : null}
                {lead}
              </p>
            ) : null}
          </div>
          <div className="grid grid-cols-2 gap-2 min-[560px]:grid-cols-4">
            <Tile label="Tus puntos" value={typeof ownPoints === "number" ? String(ownPoints) : "—"} hint={myForm ? `${Math.round(myForm.total)} en ${formWindow} jornadas` : null} />
            <Tile
              label="Al de arriba"
              value={above && typeof above.edge_points === "number" ? `${Math.abs(above.edge_points)} pts` : "—"}
              hint={above?.manager_name || (ownRank === 1 ? "Nadie por encima" : null)}
            />
            <Tile label="Sobre el de abajo" value={below && typeof below.edge_points === "number" ? `${Math.abs(below.edge_points)} pts` : "—"} hint={below?.manager_name || null} />
            <Tile label="Tu ritmo" value={myForm ? `${points(myForm.recent_avg)} pts` : "—"} hint={myForm ? `${myForm.form_rank}º en forma` : "Sin jornadas"} />
          </div>
        </div>
        <RaceStrip rows={standings} />
        {footnote ? <p className="relative mt-4 text-[12.5px] leading-snug text-white/50">{footnote}</p> : null}
      </section>

      {race === null ? (
        <p className="px-1 text-[12px] text-white/35">Calculando la carrera de liga…</p>
      ) : race.ok === false ? (
        <p className="px-1 text-[12px] leading-relaxed text-white/35">
          La carrera de liga no ha respondido: {race.error?.message || race.message || "sin detalle"}. Sin ella no hay proyección ni cara a cara.
        </p>
      ) : null}

      <div className="desk-switch w-full !max-w-[34rem]" role="tablist" aria-label="Secciones de la liga">
        {tabs.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            className={tab === item.id ? "desk-switch__btn desk-switch__btn--on" : "desk-switch__btn"}
            onClick={() => setTab(item.id)}
          >
            <span className="truncate">{item.label}</span>
            {item.count ? <span className="ml-1.5 shrink-0 text-[12px] font-normal tabular-nums opacity-55">{item.count}</span> : null}
          </button>
        ))}
      </div>

      <div key={tab} className="row-in flex min-w-0 flex-col gap-4" role="tabpanel">
        {tab === "clasificacion" ? <StandingsTable rows={standings} window={formWindow} leaderGap={leaderGap} onOpen={setSelected} /> : null}

        {tab === "jornadas" ? <RoundsTable rounds={form && form.ok !== false ? form.my_rounds || [] : []} sources={form?.sources} /> : null}

        {tab === "duelo" ? (
          race === null ? (
            <>
              <p className="px-1 text-[13px] text-white/50">Calculando el once de cada rival… la primera vez tras una actualización puede tardar hasta un minuto.</p>
              <Skeleton />
            </>
          ) : race.ok === false ? (
            <Empty title="Cara a cara no disponible" detail={`La carrera de liga no ha respondido: ${race.error?.message || race.message || "sin detalle"}.`} />
          ) : !(race.rivals || []).length ? (
            <Empty title="Sin rivales proyectados" detail="Pulsa Actualizar para calcular los onces de tus rivales." />
          ) : (
            headToHeadCard
          )
        ) : null}

        {tab === "alertas" ? <AlertsPanel threats={threats} thin={thin} denial={denial} rivalCount={Math.max(0, all.rows.length - (all.own ? 1 : 0))} photos={photos} /> : null}
      </div>

      <RivalDialog
        squad={selectedSquad}
        self={selected !== null && selected === ownId}
        ownPoints={typeof ownPoints === "number" ? ownPoints : null}
        cash={selectedSquad ? cashOf(selectedSquad) : null}
        photos={photos}
        onClose={() => setSelected(null)}
      />
    </div>
  );
}
