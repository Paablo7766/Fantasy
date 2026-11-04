"use client";

import { useEffect, useMemo, useState } from "react";
import { initials, jornadaEv, playerName, points, projectedLineupPoints, titularShare } from "@/lib/core/format";
import { REGLAMENTO } from "@/lib/core/reglamento";
import { signedPoints } from "@/lib/inicio/hoy";
import { bustPhotoFor } from "@/lib/core/bustPhoto";
import { photoFor, type PhotoIndex } from "@/lib/core/photoIndex";
import type { CapitanPick, Gap, OptimizePayload, PlanPayload, Player, SquadsPayload } from "@/lib/types";
import {
  Disclosure,
  Empty,
  Face,
  Fact,
  HeroStat,
  SectionHead,
  Skeleton,
  StatusBand,
  TONE,
  lastName,
  money,
  parsePct,
  ringColor,
  signedPct,
  toneOf,
} from "@/components/ui/kit";

const ROW_Y: Record<string, number> = { DEL: 15, MC: 39, DEF: 63, POR: 86 };
const LINES = ["DEL", "MC", "DEF", "POR"] as const;

type Slot = Player & { gap?: boolean; x: number; y: number; key: string };
type View = "rec" | "saved";

function xFor(index: number, count: number): number {
  if (count <= 1) return 50;
  const margin = count >= 5 ? 11 : count === 4 ? 14 : count === 3 ? 21 : 30;
  return margin + (index * (100 - margin * 2)) / (count - 1);
}

function layout(players: Player[], gaps: Gap[]): Slot[] {
  const groups: Record<string, Array<Player & { gap?: boolean }>> = { POR: [], DEF: [], MC: [], DEL: [] };
  for (const player of players) {
    const position = (player.position || "").toUpperCase();
    if (groups[position]) groups[position].push(player);
  }
  for (const gap of gaps) {
    const position = (gap.position || "").toUpperCase();
    for (let index = 0; index < (Number(gap.missing) || 0); index += 1) {
      if (groups[position]) groups[position].push({ gap: true, position });
    }
  }
  const out: Slot[] = [];
  for (const position of LINES) {
    const line = groups[position];
    line.forEach((player, index) => {
      out.push({
        ...player,
        x: xFor(index, line.length),
        y: ROW_Y[position],
        key: `${player.gap ? "gap" : player.player_id || playerName(player)}-${position}-${index}`,
      });
    });
  }
  return out;
}

function statusLabel(status: string | null | undefined): string | null {
  const folded = (status || "").trim().toLowerCase();
  if (["doubtful", "doubt", "duda"].includes(folded)) return "Duda";
  if (["injured", "injury", "lesionado", "out", "baja"].includes(folded)) return "Lesión";
  if (["suspended", "sanctioned", "sancionado"].includes(folded)) return "Sanción";
  return null;
}

function idOf(player: Player): string {
  return String(player.player_id || playerName(player));
}

type Swap = { out: Player; into: Player; gain: number | null };

/** Quién sale del once guardado y quién entra del recomendado, emparejados por línea. */
function lineupSwaps(saved: Player[], recommended: Player[]): Swap[] {
  const savedIds = new Set(saved.map(idOf));
  const recIds = new Set(recommended.map(idOf));
  const leaves = saved.filter((player) => !recIds.has(idOf(player)));
  const pool = recommended.filter((player) => !savedIds.has(idOf(player)));
  const swaps: Swap[] = [];
  for (const out of leaves) {
    const at = pool.findIndex((row) => row.position === out.position);
    const into = at >= 0 ? pool.splice(at, 1)[0] : pool.shift();
    if (!into) break;
    const a = jornadaEv(out);
    const b = jornadaEv(into);
    swaps.push({ out, into, gain: a !== null && b !== null ? b - a : null });
  }
  return swaps;
}

function redLine(plan: PlanPayload | null, optimize: OptimizePayload, differs: boolean): { tone: "fail" | "warn"; items: string[] } {
  const items: string[] = [];
  let fail = false;
  const checks = plan?.red_line?.checks;
  if (checks?.length) {
    for (const check of checks) {
      if (check.key === "cash" && check.status === "fail") items.push("Caja negativa");
      if (check.key === "xi" && check.status === "fail") items.push("XI incompleto");
      if (check.key === "lineup" && check.status === "warn") items.push("Once sin guardar");
      if (check.status === "fail") fail = true;
    }
  } else {
    const reasons = optimize.matchday_void ? optimize.void_reasons || [] : [];
    if (reasons.includes("negative_cash")) items.push("Caja negativa");
    if (reasons.includes("empty_slot")) items.push("XI incompleto");
    if (reasons.length) fail = true;
    if (differs) items.push("Once sin guardar");
  }
  if (items.length) items[items.length - 1] += fail ? ": la jornada vale 0" : "";
  return { tone: fail ? "fail" : "warn", items };
}

/** Colores de camiseta de los clubes cuya foto de pecho no existe en LaLiga (id de club de Fantasy). */
const KIT: Record<string, [string, string]> = { t176: ["#8fc7f0", "#4f8fc4"] };

/** Hombros dibujados para las fotos de solo cara, con el color del club si se conoce. */
function Shoulders({ team }: { team: string | null }) {
  const [top, bottom] = (team && KIT[team]) || ["#4a423c", "#1b1613"];
  const id = `eq-shoulders-${team || "neutral"}`;
  return (
    <svg className="eq-card__shoulders" viewBox="0 0 100 56" preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={top} />
          <stop offset="1" stopColor={bottom} />
        </linearGradient>
      </defs>
      <path d="M4 56C4 36 20 28 38 25h24c18 3 34 11 34 31Z" fill={`url(#${id})`} />
      <path d="M40 25c3 6 7 9 10 9s7-3 10-9" fill="none" stroke="rgba(255,255,255,0.18)" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  );
}

const TARGET_WIDTH = 0.78;
const scaleCache = new Map<string, number>();

/**
 * Las fotos de pecho de LaLiga no vienen con el mismo zoom. Se mide el ancho de
 * hombros (mitad inferior) y se escala hasta un ancho común, con límites para
 * no deformar. Si el navegador no deja leer la imagen, se deja sin tocar.
 */
async function measureScale(url: string): Promise<number> {
  const cached = scaleCache.get(url);
  if (cached !== undefined) return cached;
  let scale = 1;
  try {
    const image = new Image();
    image.crossOrigin = "anonymous";
    image.src = url;
    await image.decode();
    const w = 64;
    const h = 70;
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (ctx) {
      ctx.drawImage(image, 0, 0, w, h);
      const data = ctx.getImageData(0, 0, w, h).data;
      let minX = w;
      let maxX = -1;
      for (let y = Math.floor(h * 0.55); y < h; y += 1) {
        for (let x = 0; x < w; x += 1) {
          if (data[(y * w + x) * 4 + 3] > 40) {
            if (x < minX) minX = x;
            if (x > maxX) maxX = x;
          }
        }
      }
      if (maxX >= minX) scale = Math.min(1.15, Math.max(0.88, TARGET_WIDTH / ((maxX - minX + 1) / w)));
    }
  } catch {
    scale = 1;
  }
  scaleCache.set(url, scale);
  return scale;
}

/** Busto del jugador: pecho con camiseta del club; si no hay, cara sobre hombros; si no, iniciales. */
function Bust({ name, src, fallback }: { name: string; src?: string | null; fallback?: string | null }) {
  const [failed, setFailed] = useState<string[]>([]);
  const [scales, setScales] = useState<Record<string, number>>({});
  const current = [src, fallback].find((url): url is string => Boolean(url) && !failed.includes(url as string));
  const isBust = Boolean(current) && current === src;

  useEffect(() => {
    if (!isBust || !current) return;
    let alive = true;
    measureScale(current).then((value) => {
      if (alive) setScales((map) => ({ ...map, [current]: value }));
    });
    return () => {
      alive = false;
    };
  }, [isBust, current]);

  if (!current) return <span className="eq-card__initials">{initials(name)}</span>;
  const img = (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={current}
      alt=""
      className={isBust ? "eq-card__img" : "eq-card__img eq-card__img--face"}
      style={isBust && scales[current] ? { transform: `scale(${scales[current]})` } : undefined}
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailed((list) => [...list, current])}
    />
  );
  if (isBust) return img;
  const team = current.match(/\/(t\d+)\//)?.[1] ?? null;
  return (
    <>
      <Shoulders team={team} />
      {img}
    </>
  );
}

function Pitch({
  slots,
  selected,
  onSelect,
  photos,
  safeId,
  boldId,
}: {
  slots: Slot[];
  selected: string | null;
  onSelect: (key: string) => void;
  photos: PhotoIndex;
  safeId: string | null;
  boldId: string | null;
}) {
  return (
    <div className="eq-pitch" role="group" aria-label="Campo con tu once">
      <svg viewBox="0 0 68 100" preserveAspectRatio="none" aria-hidden="true">
        <g fill="none" stroke="rgba(255,255,255,0.09)" strokeWidth="0.35">
          <rect x="2" y="2" width="64" height="96" rx="2" />
          <line x1="2" y1="50" x2="66" y2="50" />
          <circle cx="34" cy="50" r="7" />
          <rect x="16" y="2" width="36" height="12" />
          <rect x="16" y="86" width="36" height="12" />
          <rect x="26" y="2" width="16" height="4.5" />
          <rect x="26" y="93.5" width="16" height="4.5" />
        </g>
      </svg>
      {slots.map((slot, index) => {
        if (slot.gap) {
          return (
            <button
              key={slot.key}
              type="button"
              className="eq-token"
              style={{ left: `${slot.x}%`, top: `${slot.y}%` }}
              aria-pressed={selected === slot.key}
              aria-label={`Hueco de ${slot.position}`}
              onClick={() => onSelect(slot.key)}
            >
              <span className="eq-card row-in" style={{ animationDelay: `${index * 30}ms` }}>
                <span className="eq-card__photo eq-card__photo--gap">
                  <span className="text-2xl leading-none text-[#FC734D]">+</span>
                </span>
                <span className="eq-card__name !text-[#FFA088]">Falta {slot.position}</span>
              </span>
            </button>
          );
        }
        const name = playerName(slot);
        const id = slot.player_id ? String(slot.player_id) : null;
        const badge = id && id === safeId ? "C" : id && id === boldId ? "R" : null;
        const share = titularShare(slot.p_titular);
        return (
          <button
            key={slot.key}
            type="button"
            className="eq-token"
            style={{
              left: `${slot.x}%`,
              top: `${slot.y}%`,
              ["--ring" as string]: ringColor(share),
            }}
            aria-pressed={selected === slot.key}
            aria-label={`${name}, ${share !== null ? `${Math.round(share * 100)}% de jugar, ` : ""}${points(jornadaEv(slot))} puntos esperados`}
            onClick={() => onSelect(slot.key)}
          >
            <span className="eq-card row-in" style={{ animationDelay: `${index * 30}ms` }}>
              <span className="eq-card__photo">
                <Bust
                  name={name}
                  src={bustPhotoFor(slot.player_id)}
                  fallback={slot.image_url || photoFor(photos, slot.player_id, name)}
                />
                {badge ? (
                  <span className="eq-badge" style={{ background: badge === "C" ? "#fff" : TONE.copper, color: "#120C09" }}>
                    {badge}
                  </span>
                ) : null}
                <span className="eq-card__pct" aria-label="Probabilidad de jugar">
                  {share !== null ? `${Math.round(share * 100)}%` : "—"}
                </span>
              </span>
              <span className="eq-card__name">{lastName(name)}</span>
              <span className="eq-card__xp">{points(jornadaEv(slot))}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

function PlayerSheet({ player, photos, onClose }: { player: Slot; photos: PhotoIndex; onClose: () => void }) {
  const name = player.gap ? `Falta un ${player.position}` : playerName(player);
  const share = titularShare(player.p_titular);
  const flag = statusLabel(player.player_status);
  const ev = jornadaEv(player);
  const ifStarts = typeof player.points_if_starts === "number" ? player.points_if_starts : null;
  const trend = parsePct(player.prevision_7d_pct);
  return (
    <article className="home-glass row-in p-4" aria-live="polite">
      <div className="flex items-center gap-3">
        {player.gap ? (
          <span className="grid h-14 w-14 shrink-0 place-items-center rounded-full border-2 border-dashed border-[#FC734D] text-xl text-[#FC734D]">+</span>
        ) : (
          <Face name={name} src={player.image_url || photoFor(photos, player.player_id, name)} size={56} ring={ringColor(share)} />
        )}
        <div className="min-w-0 flex-1">
          <p className="truncate text-[16px] font-semibold text-white">{name}</p>
          <p className="truncate text-[13px] text-white/50">
            {player.gap ? "Plaza sin titular en tu plantilla" : [player.position, player.club].filter(Boolean).join(" · ")}
            {flag ? <span className="text-[#F59E0B]"> · {flag}</span> : null}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Cerrar detalle"
          className="grid h-10 w-10 shrink-0 place-items-center rounded-full text-white/50 transition-colors duration-200 ease-out hover:bg-white/[0.06] hover:text-white"
        >
          <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
            <path d="m4 4 8 8M12 4l-8 8" strokeLinecap="round" />
          </svg>
        </button>
      </div>
      {!player.gap ? (
        <>
          <div className="mt-4 grid grid-cols-3 gap-3">
            <Fact
              label="xP jornada"
              value={points(ev)}
              tone="#FFC08A"
              hint={ifStarts !== null && ev !== null && Math.abs(ifStarts - ev) >= 0.35 ? `${points(ifStarts)} si juega` : undefined}
            />
            <Fact label="Titular" value={share !== null ? `${Math.round(share * 100)}%` : "—"} tone={ringColor(share)} />
            <Fact
              label="Valor"
              value={money(player.market_value)}
              hint={trend !== null ? `${signedPct(trend)} en 7 días` : undefined}
            />
          </div>
          {typeof player.tu_once_pierde_sin_el === "number" && player.tu_once_pierde_sin_el >= 0.05 ? (
            <p className="mt-3 text-[13px] text-white/50">
              Sin él tu once pierde <span className="font-medium tabular-nums text-white">{points(player.tu_once_pierde_sin_el)} pts</span>
            </p>
          ) : null}
        </>
      ) : null}
    </article>
  );
}

function CaptainCard({ title, pick, photos, accent }: { title: string; pick: CapitanPick; photos: PhotoIndex; accent: string }) {
  const name = pick.nombre || "Jugador";
  const base = typeof pick.jornada === "number" ? pick.jornada : typeof pick.si_titular === "number" ? pick.si_titular : null;
  return (
    <article className="home-glass min-w-0 p-4">
      <p className="flex items-center gap-1.5 text-[12.5px] text-white/50">
        <span className="h-1.5 w-1.5 rounded-full" style={{ background: accent }} aria-hidden="true" />
        {title}
      </p>
      <div className="mt-3 flex items-center gap-2.5">
        <Face name={name} src={photoFor(photos, pick.player_id, name)} size={40} ring={ringColor(titularShare(pick.p_titular))} />
        <p className="min-w-0 truncate text-[15px] font-medium text-white">{lastName(name)}</p>
      </div>
      <p className="mt-3 text-[1.35rem] font-semibold leading-none tabular-nums text-white">
        <span className="text-[13px] font-medium text-white/45">x2 = </span>
        {base !== null ? points(base * 2) : "—"}
      </p>
      {typeof pick.techo === "number" ? (
        <p className="mt-1.5 text-[12.5px] tabular-nums text-white/45">Techo {points(pick.techo * 2)}</p>
      ) : null}
    </article>
  );
}

function MiniPerson({ player, photos, caption }: { player: Player; photos: PhotoIndex; caption?: string }) {
  const name = playerName(player);
  return (
    <span className="flex min-w-0 flex-1 items-center gap-2.5">
      <Face name={name} src={player.image_url || photoFor(photos, player.player_id, name)} size={36} />
      <span className="min-w-0">
        <span className="block truncate text-[14px] font-medium leading-tight text-white">{lastName(name)}</span>
        {caption ? <span className="block truncate text-[12px] tabular-nums text-white/45">{caption}</span> : null}
      </span>
    </span>
  );
}

export function OnceTab({
  plan,
  optimize,
  squads,
  photos,
  loading,
}: {
  plan: PlanPayload | null;
  optimize: OptimizePayload | null;
  squads: SquadsPayload | null;
  photos: PhotoIndex;
  loading: boolean;
}) {
  const [view, setView] = useState<View>("rec");
  const [selected, setSelected] = useState<string | null>(null);

  const model = useMemo(() => {
    if (!optimize || optimize.ok === false) return null;
    // El once trae xP; la plantilla trae valor y previsión. Se juntan por id.
    const squad = new Map<string, Player>();
    for (const row of squads?.self?.players || []) if (row.player_id) squad.set(String(row.player_id), row as Player);
    const known = new Map<string, Player>();
    for (const row of [...(optimize.excluded || []), ...(optimize.benched || []), ...(optimize.xi || [])]) {
      if (row.player_id) known.set(String(row.player_id), row);
    }
    const enrich = (row: Player): Player => {
      const id = row.player_id ? String(row.player_id) : null;
      const base = id ? known.get(id) : undefined;
      const own = id ? squad.get(id) : undefined;
      return {
        ...own,
        ...base,
        ...row,
        jornada_ev: row.jornada_ev ?? base?.jornada_ev,
        expected_points: row.expected_points ?? base?.expected_points,
        p_titular: row.p_titular ?? base?.p_titular ?? own?.p_titular,
        market_value: row.market_value ?? base?.market_value ?? own?.market_value,
        prevision_7d_pct: row.prevision_7d_pct ?? base?.prevision_7d_pct ?? own?.prevision_7d_pct,
        tu_once_pierde_sin_el: row.tu_once_pierde_sin_el ?? base?.tu_once_pierde_sin_el ?? own?.tu_once_pierde_sin_el,
      };
    };
    const recommended = (optimize.xi || []).map(enrich);
    const saved = optimize.saved_lineup?.ok ? (optimize.saved_lineup.xi || []).map(enrich) : [];
    const savedIds = new Set(saved.map(idOf));
    const same = saved.length > 0 && saved.length === recommended.length && recommended.every((row) => savedIds.has(idOf(row)));
    return {
      recommended,
      saved,
      same,
      bench: (optimize.benched || []).map(enrich),
      recPts: projectedLineupPoints(recommended) ?? optimize.expected_points ?? null,
      savedPts: saved.length ? projectedLineupPoints(saved) : (plan?.lineup?.saved_points ?? null),
      swaps: saved.length && !same ? lineupSwaps(saved, recommended) : [],
    };
  }, [optimize, squads, plan]);

  if (loading && !model) return <Skeleton />;
  if (!optimize || !model) {
    return <Empty title="Sin once calculado" detail="Pulsa Actualizar para leer tu plantilla y calcular el once." />;
  }

  const showingSaved = view === "saved" && model.saved.length > 0;
  const shown = showingSaved ? model.saved : model.recommended;
  const gaps = showingSaved ? [] : optimize.gaps || [];
  const slots = layout(shown, gaps);
  const total = showingSaved ? model.savedPts : model.recPts;
  const formation = showingSaved ? optimize.saved_lineup?.formation : optimize.formation;
  const delta = model.recPts !== null && model.savedPts !== null && model.saved.length ? model.recPts - model.savedPts : null;
  const shares = shown.map((row) => titularShare(row.p_titular)).filter((value): value is number => value !== null);
  const avgShare = shares.length ? shares.reduce((sum, value) => sum + value, 0) / shares.length : null;
  const doubts = shown.filter((row) => statusLabel(row.player_status)).length;
  const gapCount = (optimize.gaps || []).reduce((sum, gap) => sum + (Number(gap.missing) || 0), 0);
  const band = redLine(plan, optimize, Boolean(model.saved.length && !model.same));
  const active = slots.find((slot) => slot.key === selected) || null;

  const safe = REGLAMENTO.capitan ? plan?.capitan_seguro || optimize.capitan_seguro || null : null;
  const boldRaw = REGLAMENTO.capitan ? plan?.capitan_remontada || optimize.capitan_remontada || null : null;
  const bold = boldRaw?.nombre && boldRaw.nombre !== safe?.nombre ? boldRaw : null;
  const fills = (optimize.market_fills || []).filter((gap) => (gap.options || []).length);
  const excluded = optimize.excluded || [];

  const switchView = (next: View) => {
    setView(next);
    setSelected(null);
  };

  return (
    <div className="grid gap-5 min-[1100px]:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] min-[1100px]:items-start">
      <div className="flex min-w-0 flex-col gap-4">
        <section className="home-feature" aria-label="Resumen del once">
          <div className="relative flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-[13px] font-medium text-white/60">{showingSaved ? "Tu once guardado" : optimize.partial ? "Mejor once posible" : "Once recomendado"}</p>
              <p className="mt-2 flex items-baseline gap-1.5 tabular-nums">
                <span className="text-[3rem] font-semibold leading-none tracking-[-0.045em] text-white">{points(total)}</span>
                <span className="text-base font-medium text-white/55">xP</span>
              </p>
            </div>
            {formation ? (
              <span className="shrink-0 rounded-full border border-white/10 bg-black/25 px-3 py-1.5 text-[14px] font-semibold tabular-nums text-white backdrop-blur-md">
                {formation}
              </span>
            ) : null}
          </div>
          {delta !== null && Math.abs(delta) >= 0.05 ? (
            <p className="relative mt-2 text-[13.5px] tabular-nums text-white/55">
              <span className="font-semibold" style={{ color: delta > 0 ? TONE.green : TONE.red }}>
                {signedPoints(delta)} pts
              </span>{" "}
              {showingSaved ? "si aplicas el recomendado" : "frente a tu once guardado"}
            </p>
          ) : model.same ? (
            <p className="relative mt-2 flex items-center gap-1.5 text-[13.5px] text-white/55">
              <span className="h-1.5 w-1.5 rounded-full bg-[#10B981]" aria-hidden="true" />
              Coincide con tu once guardado
            </p>
          ) : null}
          <div className="relative mt-5 grid grid-cols-3 gap-2.5">
            <HeroStat value={avgShare !== null ? `${Math.round(avgShare * 100)}%` : "—"} label="Titularidad" tone={avgShare !== null ? ringColor(avgShare) : undefined} />
            <HeroStat value={String(doubts)} label={doubts === 1 ? "Duda" : "Dudas"} tone={doubts ? TONE.amber : undefined} />
            <HeroStat value={String(gapCount)} label={gapCount === 1 ? "Hueco" : "Huecos"} tone={gapCount ? TONE.red : undefined} />
          </div>
        </section>

        <StatusBand tone={band.tone} items={band.items} />

        {model.saved.length && !model.same ? (
          <div className="desk-switch !grid-cols-2" role="tablist" aria-label="Qué once ver">
            {(
              [
                ["rec", "Recomendado"],
                ["saved", "Guardado"],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={view === id}
                className={view === id ? "desk-switch__btn desk-switch__btn--on" : "desk-switch__btn"}
                onClick={() => switchView(id)}
              >
                {label}
              </button>
            ))}
          </div>
        ) : null}

        <Pitch
          slots={slots}
          selected={selected}
          onSelect={(key) => setSelected((current) => (current === key ? null : key))}
          photos={photos}
          safeId={safe?.player_id ? String(safe.player_id) : null}
          boldId={bold?.player_id ? String(bold.player_id) : null}
        />
        <p className="-mt-1 flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-[12px] text-white/45">
          {[
            [TONE.green, "≥ 80%"],
            [TONE.amber, "50–80%"],
            [TONE.red, "< 50%"],
          ].map(([color, label]) => (
            <span key={label} className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full" style={{ background: color }} aria-hidden="true" />
              {label}
            </span>
          ))}
          <span>de jugar</span>
        </p>

        {active ? <PlayerSheet player={active} photos={photos} onClose={() => setSelected(null)} /> : null}
      </div>

      <div className="flex min-w-0 flex-col gap-4">
        {safe?.nombre ? (
          <div className={bold ? "grid grid-cols-2 gap-3" : "grid"}>
            <CaptainCard title="Capitán seguro" pick={safe} photos={photos} accent="#fff" />
            {bold ? <CaptainCard title="Capitán remontada" pick={bold} photos={photos} accent={TONE.copper} /> : null}
          </div>
        ) : null}

        {model.bench.length ? (
          <section aria-label={REGLAMENTO.banquillo ? "Banquillo" : "Fuera del once"} className="flex flex-col gap-3">
            <SectionHead title={REGLAMENTO.banquillo ? "Banquillo" : "Fuera del once"} meta={`${model.bench.length}`} />
            {REGLAMENTO.banquillo ? null : (
              <p className="-mt-1 text-[12.5px] leading-relaxed text-white/45">
                No puntúan. Si un titular no juega, nadie entra por él. El número es lo que sumarían dentro del once.
              </p>
            )}
            <ul className="eq-scroll -mx-1 px-1 pb-1">
              {model.bench.map((player, index) => {
                const name = playerName(player);
                return (
                  <li
                    key={idOf(player)}
                    className="home-glass row-in flex w-[5.5rem] flex-col items-center px-2 py-3"
                    style={{ animationDelay: `${index * 30}ms` }}
                  >
                    <Face name={name} src={player.image_url || photoFor(photos, player.player_id, name)} size={44} ring={ringColor(titularShare(player.p_titular))} />
                    <span className="mt-1.5 w-full truncate text-center text-[12px] text-white/70">{lastName(name)}</span>
                    <span className="text-[12px] font-semibold tabular-nums text-[#FFC08A]">{points(jornadaEv(player))}</span>
                  </li>
                );
              })}
            </ul>
          </section>
        ) : null}

        {model.swaps.length ? (
          <Disclosure
            title="Cambios para el recomendado"
            meta={
              <>
                {model.swaps.length}
                {delta !== null ? <span style={{ color: toneOf(delta) }}> · {signedPoints(delta)}</span> : null}
              </>
            }
          >
            <ul className="space-y-3">
              {model.swaps.map((swap) => (
                <li key={`${idOf(swap.out)}-${idOf(swap.into)}`} className="flex items-center gap-2">
                  <MiniPerson player={swap.out} photos={photos} caption={`Sale · ${points(jornadaEv(swap.out))}`} />
                  <span className="shrink-0 text-white/30" aria-hidden="true">→</span>
                  <MiniPerson player={swap.into} photos={photos} caption={`Entra · ${points(jornadaEv(swap.into))}`} />
                  {swap.gain !== null ? (
                    <span className="w-12 shrink-0 text-right text-[14px] font-semibold tabular-nums" style={{ color: toneOf(swap.gain) }}>
                      {signedPoints(swap.gain)}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          </Disclosure>
        ) : null}

        {fills.length ? (
          <Disclosure title="Qué fichar para cerrar el once" meta={`${gapCount} ${gapCount === 1 ? "hueco" : "huecos"}`} defaultOpen>
            <div className="space-y-4">
              {fills.map((gap, index) => (
                <div key={`${gap.position}-${index}`}>
                  <p className="text-[12.5px] text-white/50">Falta {gap.missing || 1} {gap.position}</p>
                  <ul className="mt-2 space-y-2.5">
                    {(gap.options || []).slice(0, 4).map((option) => (
                      <li key={idOf(option)} className="flex items-center gap-2.5">
                        <MiniPerson player={option} photos={photos} caption={option.club || undefined} />
                        <span className="shrink-0 text-[14px] font-medium tabular-nums text-white">{money(option.sale_price)}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </Disclosure>
        ) : null}

        {excluded.length || optimize.calibration_note ? (
          <Disclosure title="Fuera del once y cálculo" meta={excluded.length ? `${excluded.length}` : undefined}>
            {excluded.length ? (
              <ul className="space-y-2.5">
                {excluded.slice(0, 10).map((player) => (
                  <li key={idOf(player)} className="flex items-center gap-2.5">
                    <MiniPerson player={player} photos={photos} caption={player.excluded_reason || "fuera"} />
                  </li>
                ))}
              </ul>
            ) : null}
            {optimize.calibration_note ? (
              <p className={`text-[13px] leading-relaxed text-white/50 ${excluded.length ? "mt-4 border-t border-white/[0.06] pt-3" : ""}`}>
                {optimize.calibration_note}
              </p>
            ) : null}
          </Disclosure>
        ) : null}
      </div>
    </div>
  );
}
