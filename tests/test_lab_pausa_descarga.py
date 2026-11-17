"""Durante una descarga el Laboratorio no recalcula: sirve su última respuesta."""

from __future__ import annotations

from unittest import mock

import server


def _view(calls: list[int]):
    @server._paused_during_refresh("prueba")
    def view(league: str | None = None):
        calls.append(1)
        return {"ok": True, "valor": len(calls)}

    return view


def setup_function() -> None:
    server._LAB_LAST.clear()


def test_sin_descarga_calcula_y_guarda() -> None:
    calls: list[int] = []
    view = _view(calls)
    with mock.patch.object(server, "_refresh_running_here", return_value=False):
        assert view(league="L") == {"ok": True, "valor": 1}
        assert view(league="L") == {"ok": True, "valor": 2}
    assert len(calls) == 2


def test_con_descarga_sirve_lo_ultimo_sin_recalcular() -> None:
    calls: list[int] = []
    view = _view(calls)
    with mock.patch.object(server, "_refresh_running_here", return_value=False):
        view(league="L")
    with mock.patch.object(server, "_refresh_running_here", return_value=True):
        served = view(league="L")
    assert served == {"ok": True, "valor": 1, "refreshing": True}
    assert len(calls) == 1


def test_con_descarga_y_sin_copia_responde_503() -> None:
    calls: list[int] = []
    view = _view(calls)
    with mock.patch.object(server, "_refresh_running_here", return_value=True):
        response = view(league="otra")
    assert response.status_code == 503
    assert calls == []


def test_un_fallo_no_se_guarda_como_ultima_respuesta() -> None:
    @server._paused_during_refresh("fallo")
    def view(league: str | None = None):
        return {"ok": False, "error": {"code": "x"}}

    with mock.patch.object(server, "_refresh_running_here", return_value=False):
        view(league="L")
    assert ("fallo", "L") not in server._LAB_LAST


def test_las_cinco_pantallas_llevan_el_portero() -> None:
    for fn in (
        server.api_calibration,
        server.api_post_mortem,
        server.api_model_report,
        server.api_primas,
        server.api_previa,
    ):
        names = []
        current = fn
        while hasattr(current, "__wrapped__"):
            names.append(current.__code__.co_freevars)
            current = current.__wrapped__
        assert any("name" in fv for fv in names), fn.__name__


def test_ruta_real_responde_503_durante_la_descarga() -> None:
    from fastapi.testclient import TestClient

    with mock.patch.object(server, "_refresh_running_here", return_value=True):
        response = TestClient(server.app).get("/api/laboratorio/primas?league=L")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "refreshing"
