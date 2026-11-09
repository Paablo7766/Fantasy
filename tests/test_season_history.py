from __future__ import annotations

import json

import pytest

from toolbox import season_history as sh
from toolbox.engine import xp2


@pytest.fixture(autouse=True)
def _temporadas_cortas(monkeypatch):
    """Los ejemplos tienen pocas filas; el mínimo real se prueba aparte."""
    monkeypatch.setattr(sh, "MIN_FILAS_TEMPORADA", 1)


def _fila(jornada: int, puntos: int | None, *, cambio: str = "", goles: int = 0, asist: int = 0, estado: str = "") -> str:
    celda = (
        f'<span class="racha-box columna_puntos point mx-auto medium laliga-fantasy "> {puntos} </span>'
        if puntos is not None
        else f"<span>{estado}</span>"
    )
    eventos = ""
    if goles:
        eventos += f'<div class="estadistica">{goles} Goles <i class="fa"></i> 7 p</div>'
    if asist:
        eventos += f'<div class="estadistica">{asist} Asistencias <i class="fa"></i> 3 p</div>'
    return f"""
<tr class="plegado plegable " data-local="0">
  <td class="bold jorn-td">{jornada}</th>
  <td class="name"><div class="link">
    <span class="d-none d-md-inline-block">ATH</span> <strong class="score won">0-3</strong>
    <span class="d-none d-md-inline-block">BAR</span>
    <span class="cambio">{cambio}</span></div></td>
  <td class="data points bold d-flex">{celda}</td>
</tr>
<tr class="desglose"><td colspan="5">
  <div class="desg laliga-fantasy"><div class="estadistica">Puntos estadísticos <i class="fa"></i> 5 p</div>
    <div class="relevo-points">Puntos Relevo <i class="fa"></i> 2 p</div></div>
  <div class="desg fantasy">{eventos}</div>
  <div class="desg comunio"></div>
</td></tr>"""


def _pagina(filas: list[str], total: int) -> str:
    return "<html>" + "".join(filas) + f"<div>Total de puntos</strong> <b>{total}</b></div></html>"


def _salida(minuto: int) -> str:
    return f'<img title="Salida" alt="Salida" src="x.png"> {minuto}\''


def _entrada(minuto: int) -> str:
    return f'<img title="Entrada" alt="Entrada" src="x.png"> {minuto}\''


def test_parse_temporada_lee_puntos_minutos_goles_y_estado():
    pagina = _pagina(
        [
            _fila(1, 10, goles=1),
            _fila(2, 3, cambio=_entrada(70)),
            _fila(3, 12, cambio=_salida(60), asist=2),
            _fila(4, None, estado="Lesionado"),
        ],
        total=25,
    )
    temporada = sh.parse_temporada(pagina)
    filas = temporada["filas"]
    assert [f["j"] for f in filas] == [1, 2, 3, 4]
    assert [f["puntos"] for f in filas] == [10, 3, 12, None]
    assert [f["minutos"] for f in filas] == [90.0, 20.0, 60.0, 0.0]
    assert [f["goles"] for f in filas] == [1, 0, 0, 0]
    assert [f["asistencias"] for f in filas] == [0, 0, 2, 0]
    assert filas[3]["estado"] == "Lesionado"
    assert filas[0]["estadisticos"] == 5 and filas[0]["relevo"] == 2
    assert temporada["total_web"] == 25
    assert sh.temporada_coherente(temporada)


def test_no_confunde_goles_encajados_ni_asistencias_sin_gol_con_goles_y_asistencias():
    fila = _fila(1, 8).replace(
        '<div class="desg fantasy"></div>',
        '<div class="desg fantasy"><div class="estadistica">2 Goles encajados <i></i> -2 p</div>'
        '<div class="estadistica">1 Asistencias sin gol <i></i> 1 p</div></div>',
    )
    parsed = sh.parse_temporada(_pagina([fila], total=8))["filas"][0]
    assert parsed["goles"] == 0 and parsed["asistencias"] == 0


def test_temporada_de_reserva_de_este_ano_no_cuenta_como_pasado(monkeypatch):
    """La web devuelve la temporada en curso (12 filas, otro título) si el jugador no estuvo en LaLiga."""
    monkeypatch.setattr(sh, "MIN_FILAS_TEMPORADA", 15)
    pagina = "<title>Grimaldo - Perfil Fantasy - LaLiga 2026/27 - Alineaciones</title>" + _pagina(
        [_fila(j, 6) for j in range(1, 13)], total=72
    )
    temporada = sh.parse_temporada(pagina)
    assert temporada["temporada_pagina"] == "laliga-26-27"
    assert not sh.temporada_coherente(temporada, "laliga-24-25")  # pocas filas y otro título
    assert sh.resumen_historico({"laliga-24-25": temporada}, "DF") is None
    monkeypatch.setattr(sh, "MIN_FILAS_TEMPORADA", 1)
    assert not sh.temporada_coherente(temporada, "laliga-24-25")  # solo por el título
    assert sh.temporada_coherente(temporada, "laliga-26-27")


def test_temporada_incoherente_si_la_suma_no_cuadra_o_no_hay_filas():
    pagina = _pagina([_fila(1, 10), _fila(2, 5)], total=99)
    assert not sh.temporada_coherente(sh.parse_temporada(pagina))
    assert not sh.temporada_coherente({"filas": [], "total_web": 5})


def test_parse_plantilla_sin_repetidos_ni_ficha():
    pagina = '<a href="/jugadores/pedri-gonzalez">x</a><a href="/jugadores/ficha">y</a><a href="/jugadores/pedri-gonzalez">z</a><a href="/jugadores/raphinha">w</a>'
    assert sh.parse_plantilla(pagina) == ["pedri-gonzalez", "raphinha"]


def _temporada(filas: list[dict]) -> dict:
    total = sum(f["puntos"] for f in filas if f["puntos"] is not None)
    return {"total_web": total, "filas": filas}


def _f(j, puntos, minutos=90.0, goles=0, asist=0):
    return {"j": j, "puntos": puntos, "minutos": minutos, "goles": goles, "asistencias": asist, "estado": None}


def test_resumen_quita_goles_y_asistencias_del_suelo_y_separa_banquillo():
    temporada = _temporada([_f(1, 10, goles=1), _f(2, 9, asist=1), _f(3, 2, minutos=20.0), _f(4, None, minutos=0.0)])
    r = sh.resumen_historico({"laliga-25-26": temporada}, "DL")
    assert r["n_titular"] == 2
    # (10 - 4) y (9 - 3) -> suelo 6
    assert round(r["suelo"], 6) == 6.0
    assert round(r["goles"], 6) == 0.5
    assert round(r["asistencia"], 6) == 1.5
    assert r["revulsivo"] == 2 and r["n_revulsivo"] == 1
    assert round(r["participacion"], 6) == 0.75


def test_resumen_ignora_temporadas_incoherentes_y_pondera_la_antigua_menos():
    buena = _temporada([_f(1, 10), _f(2, 10)])
    mala = {"total_web": 999, "filas": [_f(1, 50)]}
    antigua = _temporada([_f(1, 4), _f(2, 4)])
    r = sh.resumen_historico({"laliga-25-26": buena, "laliga-24-25": antigua, "laliga-23-24": mala}, "MC")
    assert r["n_titular"] == 4
    # (2*1.0*10 + 2*0.6*4) / (2*1.0 + 2*0.6)
    assert round(r["suelo"], 6) == round((20 + 4.8) / 3.2, 6)
    assert sh.resumen_historico({"laliga-25-26": mala}, "MC") is None


def test_medias_y_prior_son_distancia_al_puesto():
    almacen = {
        "a": {"posicion": "DL", "temporadas": {"laliga-25-26": _temporada([_f(j, 12) for j in range(1, 13)])}},
        "b": {"posicion": "DL", "temporadas": {"laliga-25-26": _temporada([_f(j, 6) for j in range(1, 13)])}},
        "c": {"posicion": "DL", "temporadas": {"laliga-25-26": _temporada([_f(1, 5)])}},
    }
    resumenes = sh.resumenes_del_almacen(almacen)
    medias = sh.medias_por_puesto(resumenes)
    assert round(medias["DL"]["suelo"], 6) == 9.0  # c no llega al mínimo de titularidades
    assert round(sh.hist_prior(resumenes["a"], medias)["suelo"], 6) == 3.0
    assert round(sh.hist_prior(resumenes["b"], medias)["suelo"], 6) == -3.0


def test_emparejar_exige_club_y_un_ganador_claro():
    almacen = {
        "pedri-gonzalez": {"nombre": "Pedri Gonzalez", "equipo": "barcelona"},
        "raphinha": {"nombre": "Raphinha", "equipo": "barcelona"},
        "pedri-otro": {"nombre": "Pedri Gonzalez", "equipo": "sevilla"},
    }
    indice = sh.indice_por_club(almacen)
    assert sh.emparejar("Pedri", "FC Barcelona", indice) == "pedri-gonzalez"
    assert sh.emparejar("Pedri González", "Sevilla FC", indice) == "pedri-otro"
    assert sh.emparejar("Nadie Conocido", "FC Barcelona", indice) is None


def test_leer_almacen_tolera_fichero_ausente_o_roto(tmp_path):
    assert sh.leer_almacen(tmp_path) == {}
    (tmp_path / sh.ALMACEN_HISTORICO).write_text("{no es json", encoding="utf-8")
    assert sh.leer_almacen(tmp_path) == {}
    (tmp_path / sh.ALMACEN_HISTORICO).write_text(json.dumps({"x": {"nombre": "X"}}), encoding="utf-8")
    assert sh.leer_almacen(tmp_path) == {"x": {"nombre": "X"}}


# --- xP 2.0 -----------------------------------------------------------------


def test_prior_con_historico_sin_datos_es_el_puesto():
    assert xp2.prior_con_historico({}, "DL") == (xp2.SUELO_PUESTO["DL"], xp2.GOLES_PUESTO["DL"], xp2.ASIST_PUESTO["DL"])
    assert xp2.prior_con_historico({"hist_prior": {"n": 0, "suelo": 5}}, "DL")[0] == xp2.SUELO_PUESTO["DL"]


def test_prior_con_historico_se_acerca_al_jugador_con_mas_partidos():
    poco = xp2.prior_con_historico({"hist_prior": {"n": 4, "suelo": 2.0, "goles": 0.1, "asistencia": 0.2}}, "DL")
    mucho = xp2.prior_con_historico({"hist_prior": {"n": 60, "suelo": 2.0, "goles": 0.1, "asistencia": 0.2}}, "DL")
    puesto = xp2.SUELO_PUESTO["DL"]
    assert puesto < poco[0] < mucho[0] < puesto + 2.0
    assert xp2.prior_con_historico({"hist_prior": {"n": 60, "goles": -5.0}}, "DL")[1] == 0.0


def _acta(jornada: int, suelo_extra: float = 0.0) -> dict:
    return {
        "jornada": jornada,
        "puntos": 5.0,
        "minutos": 90.0,
        "desglose": {"puntos": {"min": 2.0, "rating": 2.0 + suelo_extra, "act": 0.0, "gk": 0.0, "neg": 0.0}, "cantidades": {"goals": 0.0}},
    }


def test_xp2_con_historico_bueno_sube_y_con_historico_malo_baja():
    base = {"position": "DL", "historial": [_acta(1), _acta(2)]}
    kwargs = {"prob_titular": 1.0, "lambda_favor": 1.3, "lambda_contra": 1.3}
    sin = xp2.prediccion_xp2(base, **kwargs)["xp_condicional"]
    bueno = xp2.prediccion_xp2({**base, "hist_prior": {"n": 40, "suelo": 2.0, "goles": 0.15, "asistencia": 0.5}}, **kwargs)["xp_condicional"]
    malo = xp2.prediccion_xp2({**base, "hist_prior": {"n": 40, "suelo": -2.0, "goles": -0.05, "asistencia": -0.3}}, **kwargs)["xp_condicional"]
    assert malo < sin < bueno
