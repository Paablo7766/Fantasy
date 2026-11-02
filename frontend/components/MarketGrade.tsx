"use client";

/** Verde desde 8, azul desde 7, ámbar en el parche y gris por debajo de 6. */
export function gradeColor(note: number): string {
  if (note >= 8) return "#10B981";
  if (note >= 7) return "#0297DE";
  if (note < 6) return "#8B9EB0";
  return "#F59E0B";
}

export function GradeBadge({ note }: { note: number }) {
  const color = gradeColor(note);
  const text = note.toLocaleString("es-ES", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return (
    <span
      className="inline-flex h-6 min-w-[2.15rem] shrink-0 items-center justify-center rounded-full px-1.5 font-mono text-[11px] font-semibold tabular-nums"
      style={{ color, background: `${color}22`, boxShadow: `inset 0 0 0 1px ${color}66` }}
      title={`Nota de fichaje ${text}`}
    >
      {text}
    </span>
  );
}

export function GradeLabel({ note, label }: { note: number; label: string }) {
  return (
    <span className="shrink-0 font-mono text-[10px] uppercase tracking-wider" style={{ color: gradeColor(note) }}>
      {label}
    </span>
  );
}
