"use client";

import { AvisosBell } from "@/components/AvisosBell";
import { useDashboard } from "@/components/DashboardProvider";

function Row({ title, detail, children }: { title: string; detail: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 py-4">
      <div className="min-w-0 flex-1">
        <p className="text-[14.5px] font-medium text-white">{title}</p>
        <p className="mt-0.5 text-[12.5px] leading-snug text-white/50">{detail}</p>
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

/** Foto guardada, conexión de la cuenta y avisos del dispositivo. */
export function CuentaPanel() {
  const { photoLine, refreshError, connecting, busy, connectAccount, trends } = useDashboard();
  return (
    <section className="home-glass px-4 py-1 sm:px-5" aria-label="Cuenta y dispositivo">
      <div className="divide-y divide-white/[0.06]">
        <Row title="Foto guardada" detail="Cuándo se descargaron los datos que ves en la app.">
          <p className="font-mono text-[12px] text-white/70">{photoLine}</p>
        </Row>
        {refreshError || trends?.partial ? (
          <Row title="Estado de la lectura" detail={refreshError || "La última descarga quedó incompleta."}>
            <span className="rounded-full bg-[#F59E0B]/15 px-2.5 py-1 text-[11.5px] font-semibold text-[#F59E0B]">{refreshError ? "Con error" : "Parcial"}</span>
          </Row>
        ) : null}
        <Row title="Conectar cuenta" detail="Elige tu cuenta de LaLiga Fantasy en Chrome para leer tu liga.">
          <button type="button" className="btn btn-ghost" disabled={connecting || busy} onClick={() => void connectAccount()}>
            {connecting ? "Elige tu cuenta en Chrome…" : "Conectar"}
          </button>
        </Row>
        <Row title="Avisos" detail="Un aviso en este dispositivo cuando termine una actualización.">
          <AvisosBell className="btn btn-ghost" />
        </Row>
      </div>
    </section>
  );
}
