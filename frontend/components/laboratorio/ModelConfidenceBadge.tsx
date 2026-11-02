"use client";

import Link from "next/link";
import type { EngineConfidence } from "@/lib/types";

function tone(band: string | null | undefined): string {
  if (band === "alta") return "badge badge--good";
  if (band === "baja") return "badge badge--bad";
  if (band === "media") return "badge badge--warn";
  return "badge";
}

export function ModelConfidenceBadge({
  confidence,
  href,
  compact = false,
}: {
  confidence: EngineConfidence | null | undefined;
  href?: string;
  compact?: boolean;
}) {
  if (!confidence || confidence.band === "unknown") return null;
  const score = typeof confidence.score === "number" ? `${confidence.score}/100` : null;
  const body = (
    <span className={tone(confidence.band)}>
      {compact ? "Motor" : "Confianza del modelo"}
      {score ? ` · ${score}` : ""}
      {!compact && confidence.label ? ` · ${confidence.label}` : ""}
    </span>
  );
  if (href) {
    return (
      <Link href={href} className="inline-flex no-underline hover:opacity-90">
        {body}
      </Link>
    );
  }
  return body;
}
