"use client";

import { useMemo, useState } from "react";
import { Skeleton, TONE, money, signedMoney } from "@/components/ui/kit";
import { playerName, points } from "@/lib/core/format";
import { photoFor, type PhotoIndex } from "@/lib/core/photoIndex";
import { buildSignalDiscrepancies } from "@/lib/laboratorio/signalDiscrepancies";
import type { Player, TrendsPayload } from "@/lib/types";
import { ExpertNotePanel } from "./ExpertNotePanel";
import { List, Row } from "./RadarSimple";

type View = "precio" | "puntos" | "chollos" | "racha" | "lesiones" | "choque" | "expertos";

const pctText = (value: number | null | undefined) => (typeof value === "number" ? `${Math.round(value * 100)} %` : "—");

/**
 * Señales externas (sobre todo Analítica Fantasy) en lenguaje llano: una
 * pregunta por sub-pestaña, una lista corta por pregunta.
 */
export function SenalesSimple({ trends, loading, photos }: { trends: TrendsPayload | null; loading: boolean; photos: PhotoIndex }) {
  const [view, setView] = useState<View>("precio");
  const [direction, setDirection] = useState<"sube" | "baja">("sube");
  const clashes = useMemo(() => buildSignalDiscrepancies(trends), [trends]);

  if (loading && !trends) return <Skeleton />;
  const t = trends && trends.ok !== false ? trends : null;
  const injuries = (t?.availability ?? []).filter((p) => p.af_injury || p.af_suspension);

  const views: { id: View; label: string; hint: string; hidden?: boolean }[] = [
    { id: "precio", label: "Precio mañana", hint: "Lo que Analítica Fantasy cree que subirá o bajará de valor mañana." },
    { id: "puntos", label: "Más puntos", hint: "Los que más puntos se esperan en la próxima jornada según Analítica Fantasy." },
    { id: "chollos", label: "Chollos", hint: "Más puntos esperados por cada millón que cuestan." },
    { id: "racha", label: "En racha", hint: "Jugadores que vienen puntuando por encima de lo normal." },
    { id: "lesiones", label: "Lesiones", hint: "Lesionados y sancionados con el motivo." },
    { id: "choque", label: "No coinciden", hint: "Jugadores en los que Analítica Fantasy y tu modelo dicen cosas opuestas: revísalos antes de pujar.", hidden: !clashes.length },
    { id: "expertos", label: "Expertos", hint: "Onces de expertos cruzados con tu liga, y tu nota manual." },
  ];
  const visible = views.filter((v) => !v.hidden);
  const active = visible.some((v) => v.id === view) ? view : "precio";
  const current = visible.find((v) => v.id === active)!;

  const row = (p: Player, i: number, value: string, note?: string, tone?: string, meta?: string) => {
    const name = playerName(p);
    return (
      <Row
        key={`${active}-${p.player_id}-${i}`}
        index={i}
        name={name}
        photo={photoFor(photos, String(p.player_id), name)}
        meta={meta ?? [p.position, p.club].filter(Boolean).join(" · ")}
        value={value}
        valueTone={tone}
        note={note}
      />
    );
  };
  const noData = "Analítica Fantasy no ha mandado este dato en la última foto.";

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="eq-scroll -mx-1 flex gap-1.5 px-1" role="tablist" aria-label="Vistas de señales">
        {visible.map((v) => (
          <button key={v.id} type="button" role="tab" aria-selected={active === v.id} className={active === v.id ? "eq-chip eq-chip--on" : "eq-chip"} onClick={() => setView(v.id)}>
            {v.label}
            {v.id === "choque" ? <span className="ml-1 tabular-nums text-amber-warn">{clashes.length}</span> : null}
          </button>
        ))}
      </div>
      <p className="-mt-1 px-1 text-[13px] text-white/50">{current.hint}</p>

      <div key={active + direction} className="row-in min-w-0">
        {active === "expertos" ? (
          <ExpertNotePanel />
        ) : !t ? (
          <p className="home-glass px-4 py-6 text-center text-[13.5px] text-white/50">Sin señales en esta foto. Actualiza desde Inicio.</p>
        ) : active === "precio" ? (
          <div className="flex flex-col gap-2">
            <div className="flex gap-1.5">
              <button type="button" className={direction === "sube" ? "eq-chip eq-chip--on" : "eq-chip"} onClick={() => setDirection("sube")}>
                Suben
              </button>
              <button type="button" className={direction === "baja" ? "eq-chip eq-chip--on" : "eq-chip"} onClick={() => setDirection("baja")}>
                Bajan
              </button>
            </div>
            <List
              rows={direction === "sube" ? t.af_prediction_rising ?? [] : t.af_prediction_falling ?? []}
              empty={noData}
              render={(p, i) => row(p, i, signedMoney(p.af_predicted_delta), "previsto mañana", direction === "sube" ? TONE.green : TONE.red)}
            />
          </div>
        ) : active === "puntos" ? (
          <List rows={t.af_oracle_points ?? []} empty={noData} render={(p, i) => row(p, i, `${points(p.af_expected_points)} pts`, `titular ${pctText(p.p_titular)}`)} />
        ) : active === "chollos" ? (
          <List
            rows={t.af_oracle_chollos ?? []}
            empty={noData}
            render={(p, i) => row(p, i, `${points(p.af_points_per_million)} pts/M`, money(p.af_market_value ?? p.market_value), TONE.green)}
          />
        ) : active === "racha" ? (
          <List
            rows={t.af_in_form ?? []}
            empty={noData}
            render={(p, i) => row(p, i, `${points(p.af_form?.recent_average ?? null)} pts`, "de media reciente", TONE.copper)}
          />
        ) : active === "lesiones" ? (
          <List
            rows={injuries}
            empty="No hay lesionados ni sancionados destacados."
            render={(p, i) => {
              const why = p.af_injury?.info || p.af_injury?.report || p.af_suspension?.info || p.fitness_detail || p.fitness || "Baja";
              return row(p, i, p.af_suspension ? "Sancionado" : "Lesionado", undefined, TONE.red, `${[p.position, p.club].filter(Boolean).join(" · ")} · ${String(why)}`);
            }}
          />
        ) : (
          <List
            rows={clashes}
            empty="Ninguna contradicción."
            render={(c, i) => row(c.player, i, c.inMarket ? "En mercado" : "", undefined, undefined, c.headline)}
          />
        )}
      </div>
    </div>
  );
}
