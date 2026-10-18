import type { ApiError, ClauseLock, Player } from "@/lib/types";

const MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

export function eur(value: number | null | undefined): string {
  if (typeof value !== "number") return "s/d";
  return new Intl.NumberFormat("es-ES", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(value);
}

export function points(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "s/d";
  return value.toLocaleString("es-ES", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

export function pct(value: number | null | undefined): string {
  if (typeof value !== "number") return "s/d";
  return `${Math.round(value * 100)}%`;
}

export function multiple(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "s/d";
  return `${value.toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}×`;
}

export function accel(value: number | null | undefined): string {
  if (typeof value !== "number") return "s/d";
  const sign = value > 0 ? "+" : "";
  return sign + value.toLocaleString("es-ES");
}

export function playerName(player: Player | null | undefined): string {
  return player?.nickname || player?.name || "Jugador";
}

export function initials(name: string): string {
  const parts = String(name || "?").split(/\s+/).filter(Boolean);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function stamp(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return String(iso);
  return new Intl.DateTimeFormat("es-ES", {
    timeZone: "Europe/Madrid",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function clockLabel(lock: ClauseLock | null | undefined): string {
  if (!lock || lock.present !== true || !lock.local_date || !lock.local_time) {
    return "Sin marca de la API";
  }
  const [, month, day] = String(lock.local_date).split("-");
  const monthName = MONTHS[Number(month) - 1] || month;
  const time = lock.local_clock || lock.local_time;
  const year = String(lock.local_date).split("-")[0];
  return `${Number(day)} ${monthName} ${year} · ${time}`;
}

export function glass(extra = ""): string {
  return `rounded-3xl border border-white/10 bg-white/5 shadow-[0_24px_80px_rgba(0,0,0,0.35)] backdrop-blur-md ${extra}`;
}

export function errorMessage(payload: ApiError | null | undefined): string {
  return payload?.error?.message || payload?.message || "No se pudo cargar este bloque.";
}

export function cashClass(value: number | null | undefined): string {
  if (typeof value !== "number") return "text-white/50";
  return value < 0 ? "text-rose-300" : "text-emerald-300";
}
