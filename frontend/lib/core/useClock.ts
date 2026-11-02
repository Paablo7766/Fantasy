"use client";

import { useSyncExternalStore } from "react";

/**
 * Reloj del navegador como store externo. `useSyncExternalStore` evita el
 * `setState` dentro de un efecto y mantiene la hidratación estable: en el
 * servidor devuelve 0 (sin cuenta atrás) y en cliente arranca al suscribirse.
 *
 * Todas las secciones comparten el mismo intervalo de un segundo.
 */
const listeners = new Set<() => void>();
let tick: number | null = null;
let current = 0;

function subscribe(onTick: () => void): () => void {
  listeners.add(onTick);
  if (tick === null) {
    current = Date.now();
    tick = window.setInterval(() => {
      current = Date.now();
      listeners.forEach((listener) => listener());
    }, 1000);
    // Primera pasada tras hidratar: evita un segundo en «--:--:--».
    queueMicrotask(() => listeners.forEach((listener) => listener()));
  }
  return () => {
    listeners.delete(onTick);
    if (listeners.size === 0 && tick !== null) {
      window.clearInterval(tick);
      tick = null;
    }
  };
}

function read(): number {
  return current;
}

function readOnServer(): number {
  return 0;
}

/** ms epoch del cliente; 0 antes de montar (render de servidor y hidratación). */
export function useNow(): number {
  return useSyncExternalStore(subscribe, read, readOnServer);
}
