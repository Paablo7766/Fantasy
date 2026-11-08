"use client";

import { useCallback, useEffect, useState } from "react";
import { apiUrl } from "@/lib/core/api";

type Estado = "cargando" | "no-soportado" | "no-configurado" | "apagado" | "encendido" | "bloqueado";

function claveAUint8(base64: string): Uint8Array<ArrayBuffer> {
  const padded = (base64 + "=".repeat((4 - (base64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(padded);
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
  return out;
}

/**
 * Campana de avisos: suscribe este dispositivo a los push del servidor para que
 * el móvil avise cuando termine una actualización, con la app cerrada o el
 * teléfono bloqueado. En iPhone solo funciona con la app añadida a inicio.
 */
export function AvisosBell({ className }: { className?: string }) {
  const [estado, setEstado] = useState<Estado>("cargando");
  const [nota, setNota] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);

  useEffect(() => {
    let vivo = true;
    (async () => {
      if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
        if (vivo) setEstado("no-soportado");
        return;
      }
      try {
        const reg = await navigator.serviceWorker.register("/sw.js");
        const sub = await reg.pushManager.getSubscription();
        if (!vivo) return;
        if (Notification.permission === "denied") setEstado("bloqueado");
        else setEstado(sub ? "encendido" : "apagado");
      } catch {
        if (vivo) setEstado("no-soportado");
      }
    })();
    return () => {
      vivo = false;
    };
  }, []);

  const alternar = useCallback(async () => {
    setNota(null);
    setOcupado(true);
    try {
      const reg = await navigator.serviceWorker.ready;
      const actual = await reg.pushManager.getSubscription();
      if (actual) {
        await fetch(apiUrl("/api/push/unsubscribe"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ endpoint: actual.endpoint }),
        }).catch(() => undefined);
        await actual.unsubscribe();
        setEstado("apagado");
        return;
      }
      const info = (await fetch(apiUrl("/api/push/key"))
        .then((r) => r.json())
        .catch(() => {
          throw new Error("No se pudo contactar con el servidor.");
        })) as {
        enabled?: boolean;
        public_key?: string;
      };
      if (!info.enabled || !info.public_key) {
        setEstado("no-configurado");
        return;
      }
      const permiso = await Notification.requestPermission();
      if (permiso !== "granted") {
        setEstado(permiso === "denied" ? "bloqueado" : "apagado");
        return;
      }
      const sub = await reg.pushManager
        .subscribe({
          userVisibleOnly: true,
          applicationServerKey: claveAUint8(info.public_key),
        })
        .catch((reason: unknown) => {
          throw new Error(`El móvil rechazó la suscripción (${reason instanceof Error ? reason.message : "sin detalle"}).`);
        });
      const res = await fetch(apiUrl("/api/push/subscribe"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(sub.toJSON()),
      });
      if (!res.ok) {
        await sub.unsubscribe().catch(() => undefined);
        const body = (await res.json().catch(() => null)) as { error?: { message?: string } } | null;
        throw new Error(`El servidor no guardó el aviso (${res.status}${body?.error?.message ? `: ${body.error.message}` : ""}).`);
      }
      await fetch(apiUrl("/api/push/test"), { method: "POST" }).catch(() => undefined);
      setEstado("encendido");
      setNota("Listo: te llegará una notificación de prueba.");
    } catch (reason) {
      setNota(reason instanceof Error && reason.message ? reason.message : "No se pudieron activar los avisos.");
    } finally {
      setOcupado(false);
    }
  }, []);

  if (estado === "cargando" || estado === "no-soportado") return null;

  const encendido = estado === "encendido";
  const texto = ocupado
    ? "Un momento…"
    : estado === "bloqueado"
      ? "Avisos bloqueados en el navegador"
      : estado === "no-configurado"
        ? "Avisos sin configurar en el servidor"
        : "Avisarme al terminar";

  return (
    <>
      <button
        role="menuitem"
        type="button"
        onClick={() => void alternar()}
        disabled={ocupado || estado === "bloqueado" || estado === "no-configurado"}
        className={className}
        style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
          <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
        </svg>
        <span style={{ flex: 1 }}>{texto}</span>
        <span
          aria-hidden="true"
          style={{
            position: "relative",
            width: 30,
            height: 18,
            borderRadius: 999,
            background: encendido ? "#34d399" : "rgba(255,255,255,0.22)",
            transition: "background 160ms ease",
            flexShrink: 0,
          }}
        >
          <span
            style={{
              position: "absolute",
              top: 2,
              left: encendido ? 14 : 2,
              width: 14,
              height: 14,
              borderRadius: 999,
              background: "#fff",
              transition: "left 160ms ease",
            }}
          />
        </span>
      </button>
      {nota ? (
        <p className="mt-1 px-2 text-[11.5px] text-white/70" role="status">
          {nota}
        </p>
      ) : null}
    </>
  );
}
