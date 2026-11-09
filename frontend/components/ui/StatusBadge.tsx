export function statusBadgeLabel(status: string | null | undefined): string | null {
  const folded = (status || "").trim().toLowerCase();
  if (["doubtful", "doubt", "duda"].includes(folded)) return "Duda";
  if (["injured", "injury", "lesionado", "out", "baja"].includes(folded)) return "Lesión";
  if (["suspended", "sanctioned", "sancionado"].includes(folded)) return "Sanción";
  return null;
}

/** Pastilla del estado oficial. ``ok`` no pinta nada. */
export function StatusBadge({ status }: { status?: string | null }) {
  const label = statusBadgeLabel(status);
  if (!label) return null;
  const color = label === "Duda" ? "#F59E0B" : "#F87171";
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[10.5px] font-semibold"
      style={{ color, background: `${color}22` }}
    >
      {label}
    </span>
  );
}
