"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

/**
 * Cifra que rueda del valor anterior al nuevo y deja un destello verde (sube)
 * o rojo (baja). Nunca anima al montarse: solo cuando el dato cambia.
 *
 * Con `memoKey` recuerda el último valor visto aunque el componente se
 * desmonte (cambio de pantalla, jugador que pasa de «pendiente» a «jugado»),
 * así lo que cambió mientras no mirabas también se nota al volver.
 */
const memory = new Map<string, number>();

/** Fija el valor de partida de una clave sin pintarla (p. ej. 0 pts antes de jugar). */
export function rememberValue(memoKey: string, value: number) {
  if (!memory.has(memoKey)) memory.set(memoKey, value);
}

type Dir = "up" | "down";

function useRolling(value: number, memoKey: string | undefined, duration: number) {
  const [start] = useState<number | null>(() => (memoKey !== undefined ? (memory.get(memoKey) ?? null) : null));
  const [shown, setShown] = useState<number>(start ?? value);
  const [pulse, setPulse] = useState<{ n: number; dir: Dir } | null>(null);
  const prev = useRef<number | null>(start);
  const live = useRef<number>(start ?? value);

  useEffect(() => {
    const from = prev.current;
    prev.current = value;
    if (memoKey !== undefined) memory.set(memoKey, value);
    if (from === null || from === value) return;

    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const dir: Dir = value > from ? "up" : "down";
    let frame = 0;
    let t0 = 0;
    const tick = (now: number) => {
      if (!t0) {
        t0 = now;
        setPulse((p) => ({ n: (p?.n ?? 0) + 1, dir }));
      }
      const p = reduced ? 1 : Math.min(1, (now - t0) / duration);
      // ease-out exponencial: arranca rápido y se posa despacio.
      const v = p === 1 ? value : from + (value - from) * (1 - Math.pow(2, -10 * p));
      live.current = v;
      setShown(v);
      if (p < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      // Si llega otro valor a mitad, el siguiente arranca desde lo que se ve.
      prev.current = live.current;
    };
  }, [value, memoKey, duration]);

  return { shown, pulse };
}

export function RollingNumber({
  value,
  format,
  render,
  memoKey,
  duration = 800,
}: {
  value: number;
  format: (v: number) => string;
  render?: (text: string) => ReactNode;
  memoKey?: string;
  duration?: number;
}) {
  const { shown, pulse } = useRolling(value, memoKey, duration);
  const text = format(shown);
  return (
    <span className="roll">
      {render ? render(text) : text}
      {pulse ? <span key={pulse.n} className="roll__flash" data-dir={pulse.dir} aria-hidden="true" /> : null}
    </span>
  );
}
