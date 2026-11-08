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
      const info = (await fetch(apiUrl("/api/push/key")).then((r) => r.json())) as {
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
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: claveAUint8(info.public_key),
      });
      const res = await fetch(apiUrl("/api/push/subscribe"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(sub.toJSON()),
      });
      if (!res.ok) throw new Error("subscribe");
      await fetch(apiUrl("/api/push/test"), { method: "POST" }).catch(() => undefined);
      setEstado("encendido");
    } catch {
      setNota("No se pudieron activar los avisos.");
    }
  }, []);

  if (estado === "cargando" || estado === "no-soportado") return null;

  const texto =
    estado === "encendido"
      ? "Avisos al terminar · activados"
      : estado === "bloqueado"
        ? "Avisos bloqueados en el navegador"
        : estado === "no-configurado"
          ? "Avisos sin configurar en el servidor"
          : "Avisarme al terminar de actualizar";

  return (
    <>
      <button
        role="menuitem"
        type="button"
        onClick={() => void alternar()}
        disabled={estado === "bloqueado" || estado === "no-configurado"}
        className={className}
      >
        {estado === "encendido" ? "🔔 " : "🔕 "}
        {texto}
      </button>
      {nota ? <p className="mt-1 text-[11.5px] text-[#ffb3a4]" role="alert">{nota}</p> : null}
    </>
  );
}
