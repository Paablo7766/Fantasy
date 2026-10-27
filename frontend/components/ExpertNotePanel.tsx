"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { useDashboard } from "@/components/DashboardProvider";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { endpoint, postJsonBody } from "@/lib/api";
import { glass, playerName } from "@/lib/format";

/**
 * Nota experta + cruce de onces. Antes vivía en la vista genérica de «Mesa»;
 * ahora se queda donde pertenece: la capa de contexto.
 */
export function ExpertNotePanel() {
  const search = useSearchParams();
  const league = search.get("league");
  const { plan, refreshPlan } = useDashboard();
  // La nota se edita en local y solo se sincroniza cuando llega una nueva del
  // backend: así el usuario no pierde lo escrito al refrescar el plan.
  const [note, setNote] = useState("");
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const remoteNote = plan?.expert_note;
  if (typeof remoteNote === "string" && remoteNote !== loadedFor && !saving) {
    // Ajuste durante el render (patrón recomendado por React) en vez de un efecto.
    setLoadedFor(remoteNote);
    setNote(remoteNote);
  }

  async function save() {
    setSaving(true);
    setStatus("Guardando…");
    try {
      await postJsonBody(endpoint("/api/expert-note", league), { text: note });
      await refreshPlan();
      setStatus("Nota guardada. Solo cuenta si el nombre casa con un jugador de tu liga.");
    } catch (reason) {
      setStatus(reason instanceof Error ? reason.message : "No se pudo guardar la nota.");
    } finally {
      setSaving(false);
    }
  }

  const notes = plan?.lineup_notes || [];
  const mentions = plan?.expert_mentions || [];

  return (
    <section className={glass("p-4 md:p-5")}>
      <p className="eyebrow">Expertos</p>
      <h2 className="section-title mt-1 text-[1.15rem]">Cruce de onces y nota pegada</h2>
      <p className="section-support">
        DonQui sale de Analítica Fantasy y Bielsa de Predicted11. Azteca no publica datos: pega aquí el texto. Un nombre
        solo cuenta si casa con un jugador de tu liga, y nunca sustituye al optimizador.
      </p>

      {notes.length ? (
        <ul className="mt-3 flex flex-col gap-1.5 text-sm text-muted-strong">
          {notes.slice(0, 12).map((row) => (
            <li key={`note-${row.player_id}`} className="flex items-center gap-2.5">
              <PlayerAvatar player={row} size="sm" />
              <span className="min-w-0 truncate">{playerName(row)}</span>
              <span className="ml-auto shrink-0 text-xs text-muted">
                {row.agreement === "unanimous" ? "fuentes de acuerdo" : "fuentes divididas"}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-sm text-muted">Sin cruce de onces en esta lectura.</p>
      )}

      {mentions.length ? (
        <ul className="mt-3 flex flex-wrap gap-1.5">
          {mentions.slice(0, 16).map((row, index) => (
            <li key={`mention-${row.source}-${row.player_id}-${index}`}>
              <span className="badge badge--warn">
                {row.source} · {row.kind} · {playerName(row)}
              </span>
            </li>
          ))}
        </ul>
      ) : null}

      <label className="mt-4 block">
        <span className="metric-label">Nota manual</span>
        <textarea
          value={note}
          onChange={(event) => setNote(event.target.value)}
          rows={5}
          placeholder="Pega un texto de Azteca u otra cuenta. Sin texto, no hay señal."
          className="field mt-1.5"
        />
      </label>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <button type="button" onClick={() => void save()} disabled={saving} className="btn btn-secondary">
          {saving ? "Guardando…" : "Guardar nota"}
        </button>
        {status ? <span className="text-xs text-muted">{status}</span> : null}
      </div>
    </section>
  );
}
