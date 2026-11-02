"use client";

import { useMemo, useState } from "react";
import { CompararButton } from "@/components/comparador/ComparadorReal";
import { LabSection } from "@/components/mercado/LabSection";
import { Empty, Face, SectionHead, Skeleton, TONE, money, signedMoney, toneOf } from "@/components/equipo/ui";
import { photoFor, type PhotoIndex } from "@/lib/photoIndex";
import { playerName } from "@/lib/format";
import type { CatalogPlayer, TrendsPayload } from "@/lib/types";

type Owner = "all" | "libre" | "rival" | "propio";

const OWNERS: { id: Owner; label: string }[] = [
  { id: "all", label: "Todos" },
  { id: "libre", label: "Libres" },
  { id: "rival", label: "De rivales" },
  { id: "propio", label: "Tuyos" },
];

const OWNER_TONE: Record<string, { label: string; color: string }> = {
  libre: { label: "Libre", color: TONE.green },
  rival: { label: "Rival", color: TONE.amber },
  propio: { label: "Tuyo", color: TONE.blue },
};

const PAGE = 40;

/** Serie de valor en miniatura: sin tres días no se pinta. */
function MiniSpark({ points }: { points: CatalogPlayer["price_points"] }) {
  const values = (points || []).map((point) => point.market_value).filter((value): value is number => typeof value === "number").slice(-10);
  if (values.length < 3) return null;
  const min = Math.min(...values);
  const span = Math.max(...values) - min || 1;
  const line = values.map((value, index) => `${((index / (values.length - 1)) * 56).toFixed(1)},${(18 - ((value - min) / span) * 16).toFixed(1)}`).join(" ");
  const up = values.at(-1)! >= values[0];
  return (
    <svg width="56" height="20" className="hidden shrink-0 sm:block" aria-hidden="true">
      <polyline fill="none" stroke={up ? TONE.green : TONE.red} strokeWidth="1.6" strokeLinejoin="round" points={line} />
    </svg>
  );
}

export function UniversoTab({ trends, photos, loading }: { trends: TrendsPayload | null; photos: PhotoIndex; loading: boolean }) {
  const [owner, setOwner] = useState<Owner>("all");
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(PAGE);

  const catalog = useMemo(() => (Array.isArray(trends?.catalog) ? trends.catalog : []), [trends]);
  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return catalog.filter((player) => {
      if (owner !== "all" && (player.owner || "libre") !== owner) return false;
      if (!needle) return true;
      return `${player.nickname || ""} ${player.name || ""} ${player.club || ""}`.toLowerCase().includes(needle);
    });
  }, [catalog, owner, query]);

  if (loading && !catalog.length) return <Skeleton />;

  return (
    <div className="flex flex-col gap-5">
      <section className="flex flex-col gap-3">
        <SectionHead title="Todos los jugadores" meta={`${rows.length}`} />
        <div className="eq-scroll">
          {OWNERS.map((item) => (
            <button
              key={item.id}
              type="button"
              aria-pressed={owner === item.id}
              onClick={() => {
                setOwner(item.id);
                setLimit(PAGE);
              }}
              className={owner === item.id ? "eq-chip eq-chip--on" : "eq-chip"}
            >
              {item.label}
            </button>
          ))}
        </div>
        <input
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setLimit(PAGE);
          }}
          placeholder="Buscar jugador o equipo"
          aria-label="Buscar jugador o equipo"
          className="h-11 w-full rounded-2xl border border-white/[0.08] bg-white/[0.04] px-4 text-[14px] text-white outline-none transition-colors duration-200 ease-out placeholder:text-white/30 focus:border-[#FF9A5A]/60"
        />
        {rows.length ? (
          <ul className="home-glass overflow-hidden">
            {rows.slice(0, limit).map((player, index) => {
              const name = playerName(player);
              const tag = OWNER_TONE[player.owner || "libre"] || OWNER_TONE.libre;
              const forecast = (player.price_points?.length ?? 0) >= 3 ? player.own_predicted_delta : null;
              return (
                <li
                  key={String(player.player_id)}
                  className="row-in flex min-h-[3.75rem] items-center gap-3 border-b border-white/[0.06] px-4 py-2.5 last:border-b-0"
                  style={{ animationDelay: `${Math.min(index, 12) * 20}ms` }}
                >
                  <Face name={name} src={player.image_url || photoFor(photos, String(player.player_id), name)} size={40} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[15px] font-medium leading-tight text-white">{name}</span>
                    <span className="mt-0.5 block truncate text-[12.5px] text-white/45">
                      {[player.position, player.club].filter(Boolean).join(" · ")}
                      <span style={{ color: tag.color }}> · {tag.label}</span>
                    </span>
                  </span>
                  <MiniSpark points={player.price_points} />
                  {player.owner !== "propio" ? <CompararButton objetivoId={player.player_id} posicion={player.position} /> : null}
                  <span className="shrink-0 text-right">
                    <span className="block text-[15px] font-semibold tabular-nums text-white">{money(player.market_value)}</span>
                    <span className="block text-[12px] font-medium tabular-nums" style={{ color: toneOf(forecast) }}>
                      {typeof forecast === "number" ? signedMoney(forecast) : "sin previsión"}
                    </span>
                  </span>
                </li>
              );
            })}
          </ul>
        ) : (
          <Empty title="Ningún jugador" detail="Nada en este filtro. La serie sale de los días ya guardados; sin tres días no hay previsión." />
        )}
        {rows.length > limit ? (
          <button type="button" className="eq-chip self-center" onClick={() => setLimit((value) => value + PAGE)}>
            Ver {Math.min(PAGE, rows.length - limit)} más
          </button>
        ) : null}
      </section>

      <LabSection photos={photos} />
    </div>
  );
}
