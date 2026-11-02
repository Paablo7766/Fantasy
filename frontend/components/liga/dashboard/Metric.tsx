"use client";



export function Metric({ label, value, tone, hint }: { label: string; value: string; tone?: string; hint?: string }) {
  return (
    <div>
      <p className="metric-label">{label}</p>
      <p className={`metric-value mt-1 text-lg ${tone || "text-ink"}`}>{value}</p>
      {hint ? <p className="mt-0.5 text-[11px] text-faint">{hint}</p> : null}
    </div>
  );
}
