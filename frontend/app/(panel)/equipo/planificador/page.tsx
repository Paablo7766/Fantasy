"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { Planificador } from "@/components/equipo/Planificador";
import { DataAge } from "@/components/ui/DataAge";
import { Skeleton } from "@/components/ui/kit";

function PlanificadorContent() {
  const search = useSearchParams();
  const league = search.get("league");
  const back = league ? `/equipo?league=${encodeURIComponent(league)}` : "/equipo";
  return (
    <div className="eq-stack reveal min-w-0">
      <div className="flex flex-col gap-2 px-1">
        <Link href={back} className="inline-flex w-fit items-center gap-1.5 text-[13px] font-medium text-white/50 transition-colors duration-200 hover:text-white">
          <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <path d="M10 3 5 8l5 5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Mi equipo
        </Link>
        <h1 className="text-[1.6rem] font-semibold leading-tight tracking-tight text-white">Planificador</h1>
        <p className="text-[13.5px] leading-snug text-white/50">Quién va a sumar más en las próximas jornadas, de quién es y si se puede fichar.</p>
      </div>
      <DataAge show={["plantillas", "titularidad"]} />
      <Planificador />
    </div>
  );
}

export default function PlanificadorPage() {
  return (
    <Suspense
      fallback={
        <div className="eq-stack">
          <Skeleton />
        </div>
      }
    >
      <PlanificadorContent />
    </Suspense>
  );
}
