"""Modo Parón autónomo: fases por calendario, corta-hemorragias, especulación y ruta de salida."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from toolbox.engine.paron import paron_conocido
from toolbox.engine.paron_plan import (
    beneficio_especulacion,
    construir_paron,
    fase_paron,
    ruta_salida,
    valor_proyectado,
)
from toolbox.engine.strategy_layer import _days_to_kickoff

MADRID = ZoneInfo("Europe/Madrid")
CIERRE = datetime(2026, 11, 20, 21, 0, tzinfo=MADRID)
M = 1_000_000


def _fila(pid, pos, xp, valor, pct=0.0, **extra):
    return {
        "player_id": pid,
        "nombre": pid,
        "position": pos,
        "jornada": xp,
        "valor": valor,
        "pct": pct,
        "venta_eur": int(valor * 0.95),
        "elegible": True,
        "p_titular": 0.8,
        **extra,
    }


def _plantilla():
    """11 titulares + 2 suplentes (DEF y DEL)."""
    filas = [_fila("por", "POR", 5.0, 5 * M)]
    filas += [_fila(f"def{i}", "DEF", 4.0, 5 * M) for i in range(4)]
    filas += [_fila(f"mc{i}", "MC", 4.5, 6 * M) for i in range(4)]
    filas += [_fila(f"del{i}", "DEL", 5.0, 8 * M) for i in range(2)]
    filas += [_fila("banq_def", "DEF", 2.0, 4 * M, pct=-8.0), _fila("banq_del", "DEL", 2.0, 3 * M, pct=1.0)]
    return filas


def test_fases_por_calendario():
    assert fase_paron(12.3) == 1
    assert fase_paron(6.1, ciclo_paron=True) == 1
    assert fase_paron(5.0, ciclo_paron=True) == 2
    assert fase_paron(3.4, ciclo_paron=True) == 3
    assert fase_paron(5.0) is None  # semana normal: no hay modo parón
    assert fase_paron(8.0) == 1  # más de 7,5 días: parón aunque la tabla no lo sepa
    assert fase_paron(None) is None


def test_beneficio_descuenta_sobreprecio_y_peor_oferta_del_90():
    # 10 M€ que suben un 20 % en 7 días; puja un 5 % por encima del valor.
    neto = beneficio_especulacion(valor=10 * M, puja=int(10.5 * M), pct=20.0, dias_hasta_venta=7.0)
    # LaLiga ofrece entre −10 % y +10 %: se cuenta la peor oferta (90 %).
    assert neto == round(12 * M * 0.90 - 10.5 * M)
    # Sube lo mismo pero con prima alta: ya no sale a cuenta.
    assert beneficio_especulacion(valor=10 * M, puja=13 * M, pct=20.0, dias_hasta_venta=7.0) < 0


def test_valor_proyectado_escala_con_los_dias():
    fila = _fila("x", "MC", 4.0, 10 * M, pct=14.0)
    assert valor_proyectado(fila, 7.0) == int(round(10 * M * 1.14))
    assert valor_proyectado(fila, 3.5) == int(round(10 * M * 1.07))


def test_ruta_de_salida_vende_banquillo_antes_que_titulares():
    squad = _plantilla()
    ruta = ruta_salida(squad=squad, saldo_proyectado=-6 * M, dias=12.0, cierre=CIERRE)
    assert ruta["cubre"] is True
    nombres = {venta["player_id"] for venta in ruta["ventas"]}
    assert nombres <= {"banq_def", "banq_del"} | {"def0", "def1", "def2", "def3", "mc0"}
    assert ruta["xp_perdido"] <= 0.5
    assert ruta["dia_venta"] == "miércoles 18-nov"
    assert ruta["dia_venta_at"].startswith("2026-11-18T21:00")


def test_ruta_sin_deuda_no_vende():
    ruta = ruta_salida(squad=_plantilla(), saldo_proyectado=2 * M, dias=12.0, cierre=CIERRE)
    assert ruta["ventas"] == [] and ruta["cubre"] is True


def test_ruta_repone_el_hueco_cuando_vender_rompe_el_once():
    squad = _plantilla()[:11]  # justo 11: cualquier venta deja el once cojo
    barato = {"player_id": "rep", "nombre": "rep", "position": "MC", "euros": 1 * M, "jornada": 3.5, "valor": 1 * M}
    ruta = ruta_salida(
        squad=squad, saldo_proyectado=-3 * M, dias=12.0, cierre=CIERRE, reposiciones=[barato]
    )
    assert ruta["reposiciones"] and ruta["reposiciones"][0]["player_id"] == "rep"
    assert ruta["cubre"] is True


def _plan_base(saldo=1 * M):
    return {"acciones": [], "saldo_al_final": saldo, "mejora_puntos_jornada": 0.0}


def test_corta_hemorragias_vende_al_suplente_que_baja():
    bloque = construir_paron(
        fase=1,
        dias=12.0,
        cierre=CIERRE,
        saldo=1 * M,
        owned=_plantilla(),
        mercado=[],
        plan=_plan_base(),
        previos=set(),
    )
    ids = {a["player_id"] for a in bloque["corta_hemorragias"]}
    assert "banq_def" in ids
    assert "banq_del" not in ids  # sube: se mantiene
    accion = bloque["corta_hemorragias"][0]
    assert accion["tipo"] in {"ESCAPARATE", "VENDER HOY"}
    assert "Corta-hemorragias" in accion["etiqueta_paron"]


def test_no_vende_al_titular_que_baja_si_el_once_lo_echa_en_falta():
    owned = _plantilla()
    owned[1]["pct"] = -9.0  # un defensa titular, sin recambio mejor que el suplente de 2 xP
    bloque = construir_paron(
        fase=1, dias=12.0, cierre=CIERRE, saldo=1 * M, owned=owned, mercado=[], plan=_plan_base(), previos=set()
    )
    assert "def0" not in {a["player_id"] for a in bloque["corta_hemorragias"]}


def _candidato(pid, euros, valor, pct, xp=3.0, **extra):
    return {
        "player_id": pid,
        "nombre": pid,
        "position": "MC",
        "jornada": xp,
        "euros": euros,
        "valor": valor,
        "pct": pct,
        **extra,
    }


def test_especula_solo_con_beneficio_neto_claro():
    mercado = [
        _candidato("bueno", int(5.1 * M), 5 * M, 30.0),  # 6,5*0,90 - 5,1 = +0,75 M€
        _candidato("flojo", int(5.1 * M), 5 * M, 4.0),  # no cubre el 10 % ni el sobreprecio
        _candidato("alerta", int(5.1 * M), 5 * M, 30.0, af_alerta_bajada=True),
    ]
    bloque = construir_paron(
        fase=1, dias=12.0, cierre=CIERRE, saldo=2 * M, owned=_plantilla(), mercado=mercado, plan=_plan_base(2 * M), previos=set()
    )
    ids = [a["player_id"] for a in bloque["especular"]]
    assert ids == ["bueno"]
    accion = bloque["especular"][0]
    assert accion["etiqueta_paron"] == "💰 Especular (Vender antes del jueves 19-nov)"
    assert accion["ganancia_esperada_eur"] >= 500_000


def test_fase_3_apaga_la_especulacion():
    mercado = [_candidato("bueno", int(5.1 * M), 5 * M, 30.0)]
    bloque = construir_paron(
        fase=3, dias=2.9, cierre=CIERRE, saldo=2 * M, owned=_plantilla(), mercado=mercado, plan=_plan_base(2 * M), previos=set()
    )
    assert bloque["especular"] == []


def test_fase_2_solo_especula_lo_que_sube_muy_fuerte():
    mercado = [
        # A 3 días de la venta y con la peor oferta (90 %) hace falta subir mucho: 45 % a 7 días.
        _candidato("fuerte", int(20.4 * M), 20 * M, 45.0),
        _candidato("medio", int(20.4 * M), 20 * M, 10.0),
    ]
    bloque = construir_paron(
        fase=2, dias=5.0, cierre=CIERRE, saldo=25 * M, owned=_plantilla(), mercado=mercado, plan=_plan_base(25 * M), previos=set()
    )
    assert [a["player_id"] for a in bloque["especular"]] == ["fuerte"]


def test_fase_2_recoge_beneficios_del_flip_que_frena():
    owned = _plantilla()
    owned.append(_fila("flip", "MC", 2.0, 5 * M, pct=0.5))
    owned.append(_fila("sigue", "MC", 2.0, 5 * M, pct=12.0))
    bloque = construir_paron(
        fase=2,
        dias=5.0,
        cierre=CIERRE,
        saldo=1 * M,
        owned=owned,
        mercado=[],
        plan=_plan_base(),
        previos={"flip", "sigue"},
    )
    ids = {a["player_id"] for a in bloque["recoger_beneficios"]}
    assert "flip" in ids and "sigue" not in ids


def test_ruta_alimenta_la_proyeccion_con_la_deuda_del_plan():
    plan = _plan_base(-4 * M)
    bloque = construir_paron(
        fase=1, dias=12.0, cierre=CIERRE, saldo=1 * M, owned=_plantilla(), mercado=[], plan=plan, previos=set()
    )
    assert bloque["ruta_salida"]["deuda_a_saldar"] > 0
    # El suplente que baja se vende hoy (3,8 M€) y reduce la deuda de 4 M€.
    assert -4 * M < bloque["proyeccion"]["saldo_viernes_sin_ruta"] < 0


def test_calendario_conocido_sustituye_al_viernes_por_defecto():
    ahora = datetime(2026, 11, 8, 11, 0, tzinfo=timezone.utc)
    assert paron_conocido(ahora) is not None
    dias = _days_to_kickoff(None, ahora)
    assert dias is not None and 12.0 < dias < 12.5
    # Fuera del parón, el comportamiento anterior: próximo viernes.
    despues = datetime(2026, 11, 21, 11, 0, tzinfo=timezone.utc)
    assert paron_conocido(despues) is None
    assert 0 < _days_to_kickoff(None, despues) < 7.5 + timedelta(days=0).days


def test_ruta_cuenta_el_peor_caso_y_deja_holgura():
    """Cada venta cuenta al 90 % del menor entre el valor de hoy y el previsto, y la ruta busca 0,5 M€ de colchón."""
    squad = _plantilla()
    squad[-1]["pct"] = 20.0  # el suplente que sube no infla el ingreso: cuenta su valor de hoy
    ruta = ruta_salida(squad=squad, saldo_proyectado=-2 * M, dias=12.0, cierre=CIERRE)
    for venta in ruta["ventas"]:
        assert venta["ingreso"] == int(min(venta["valor_hoy"], venta["valor_proyectado"]) * 0.90)
    assert ruta["ingreso"] >= 2 * M + 500_000
    assert ruta["con_holgura"] is True
