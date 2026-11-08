"""Auditoría del XI: la previsión de una jornada solo se compara con las actas de esa jornada."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from toolbox.audit import ciclo_auditoria

IDS = [f"p{i}" for i in range(11)]
INICIO_J13 = datetime(2026, 11, 20, 20, 0, tzinfo=timezone.utc)


def _optimize(xp: float = 6.0) -> dict:
    return {"xi": [{"player_id": pid, "expected_points": xp} for pid in IDS]}


def _actas(hasta: int, puntos_ultima: float = 7.0) -> dict:
    """Actas de cada titular hasta la jornada ``hasta`` (la J11 da 9 puntos para distinguirla)."""
    actas = {}
    for pid in IDS:
        weeks = {str(j): [9.0 if j == 11 else 5.0, 90.0] for j in range(8, hasta)}
        weeks[str(hasta)] = [puntos_ultima, 90.0]
        actas[pid] = {"weeks": weeks}
    return actas


def test_guarda_la_previa_antes_del_bloqueo_y_no_audita_sin_actas_de_esa_jornada(tmp_path: Path):
    previas = tmp_path / "previas.json"
    memoria = tmp_path / "MEMORY.md"
    domingo = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
    # Domingo de J12: hay actas de la J12 y se guarda la previa de la J13 (66 puntos).
    r = ciclo_auditoria(_optimize(), _actas(12), inicio_proxima=INICIO_J13, now=domingo, previas_path=previas, memory_path=memoria)
    assert r["written"] is False
    # El 20-nov tras el saque, sin actas de la J13: no se compara con la J12.
    tras_saque = INICIO_J13 + timedelta(hours=3)
    r = ciclo_auditoria(_optimize(), _actas(12), inicio_proxima=None, now=tras_saque, previas_path=previas, memory_path=memoria)
    assert r["reason"] == "sin_actas_de_la_jornada"
    assert not memoria.exists()


def test_audita_con_las_actas_de_la_misma_jornada(tmp_path: Path):
    previas = tmp_path / "previas.json"
    memoria = tmp_path / "MEMORY.md"
    ciclo_auditoria(_optimize(), _actas(12), inicio_proxima=INICIO_J13, now=datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc),
                    previas_path=previas, memory_path=memoria)
    lunes = INICIO_J13 + timedelta(hours=72)
    r = ciclo_auditoria(_optimize(), _actas(13, puntos_ultima=7.0), inicio_proxima=None, now=lunes, previas_path=previas, memory_path=memoria)
    assert r["written"] is True and r["jornada"] == 13
    assert r["predicted_points"] == 66.0 and r["actual_points"] == 77.0  # 11 × 7 de la J13, nunca los 9 de la J11
    texto = memoria.read_text(encoding="utf-8")
    assert "jornada 13" in texto and "actas de la jornada 13" in texto
    # No se repite.
    otra = ciclo_auditoria(_optimize(), _actas(13), inicio_proxima=None, now=lunes, previas_path=previas, memory_path=memoria)
    assert otra["written"] is False
