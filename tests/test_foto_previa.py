"""Foto del Marcador antes del primer saque."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from toolbox import foto_previa as fp

AHORA = datetime(2026, 11, 7, 15, 0, tzinfo=timezone.utc)


def tablero(saque: datetime, *, guardado_hace_h: float = 0.5) -> dict:
    return {
        "photo_saved_unix": (AHORA - timedelta(hours=guardado_hace_h)).timestamp(),
        "squads": {"ok": True},
        "trends": {"league_id": "L", "players": [{"fixture": {"kickoff": saque.isoformat()}}]},
        "market": {},
    }


class FotoPreviaTests(unittest.TestCase):
    def setUp(self) -> None:
        fp._ESTADO["fotos"].clear()
        fp._ESTADO["refrescos"].clear()

    def _track(self) -> mock.Mock:
        track = mock.Mock()
        track.run_snapshot.return_value = {"jornada_id": "13", "written": 120}
        return track

    def test_fuera_de_ventana_no_hace_nada(self) -> None:
        board = tablero(AHORA + timedelta(hours=10))
        self.assertEqual(fp.foto_previa(board, now=AHORA, conn=mock.Mock())["motivo"], "fuera_de_ventana")

    def test_en_ventana_guarda_una_vez_por_tablero(self) -> None:
        board = tablero(AHORA + timedelta(hours=2))
        track = self._track()
        with mock.patch("toolbox.matchday_auto._load_track", return_value=track), mock.patch(
            "toolbox.marcador.reparar_historico"
        ) as reparar:
            primera = fp.foto_previa(board, now=AHORA, conn=mock.Mock())
            reparar.assert_called_once()
            segunda = fp.foto_previa(board, now=AHORA, conn=mock.Mock())
            # Tablero nuevo (otra actualización): nueva foto, la más reciente.
            nuevo = dict(board, photo_saved_unix=AHORA.timestamp())
            tercera = fp.foto_previa(nuevo, now=AHORA, conn=mock.Mock())
        self.assertTrue(primera["hecho"])
        self.assertEqual(primera["jornada_id"], "13")
        self.assertEqual(segunda["motivo"], "ya_fotografiado")
        self.assertTrue(tercera["hecho"])
        self.assertEqual(track.run_snapshot.call_count, 2)

    def test_refresca_solo_un_tablero_viejo_y_una_vez(self) -> None:
        viejo = tablero(AHORA + timedelta(hours=2), guardado_hace_h=8)
        self.assertTrue(fp.debe_refrescar(viejo, AHORA))
        fp.marcar_refresco(viejo, AHORA)
        self.assertFalse(fp.debe_refrescar(viejo, AHORA))
        self.assertFalse(fp.debe_refrescar(tablero(AHORA + timedelta(hours=2), guardado_hace_h=1), AHORA))
        # A diez minutos del saque ya no se pide red.
        self.assertFalse(fp.debe_refrescar(tablero(AHORA + timedelta(minutes=10), guardado_hace_h=8), AHORA))
        with mock.patch.dict("os.environ", {"FOTO_PREVIA_REFRESCO": "0"}):
            self.assertFalse(fp.debe_refrescar(tablero(AHORA + timedelta(hours=1), guardado_hace_h=8), AHORA))

    def test_una_pasada_refresca_y_fotografia(self) -> None:
        viejo = tablero(AHORA + timedelta(hours=2), guardado_hace_h=8)
        refrescar = mock.Mock()
        with mock.patch.object(fp, "foto_previa", return_value={"ok": True, "hecho": True}) as foto:
            fp.una_pasada(lambda: viejo, refrescar, now=AHORA)
        refrescar.assert_called_once()
        foto.assert_called_once()


if __name__ == "__main__":
    unittest.main()
