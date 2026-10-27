"use client";

import { Suspense, type ReactNode } from "react";
import { AppShell } from "@/components/AppShell";
import { DashboardProvider } from "@/components/DashboardProvider";

export default function PanelLayout({ children }: { children: ReactNode }) {
  return (
    <DashboardProvider>
      <Suspense fallback={<div className="app-shell min-h-screen" />}>
        <AppShell>{children}</AppShell>
      </Suspense>
    </DashboardProvider>
  );
}
