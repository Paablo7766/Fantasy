"""Reglamento de esta liga.

LaLiga Fantasy permite tres extras que aquí están apagados:

- Banquillo: nadie entra si un titular no juega. Solo puntúan los 11 alineados
  y quien se queda fuera hace 0 esa jornada. Antes del cierre sí se puede
  mover a otro de la plantilla al once: eso es cambiar la alineación, no un
  suplente automático.
- Capitán: nadie dobla sus puntos.
- Entrenador: no hay ficha de entrenador. No se ficha y no puntúa.

Los minutos de un revulsivo en su partido real siguen dentro de su xP cuando
lo alineas. Eso es fútbol, no la regla de la liga.
"""

from __future__ import annotations

BANQUILLO_ACTIVO = False
CAPITAN_ACTIVO = False
ENTRENADOR_ACTIVO = False

PUESTOS_JUGABLES = frozenset({"POR", "DEF", "MC", "DEL"})

#: Oferta automática de LaLiga: aleatoria entre el valor de mercado −10 % y +10 %
#: (soporte oficial de LaLiga). El peor caso es el 90 %: es lo que se cuenta
#: cuando una venta tiene que cubrir deuda antes del cierre.
OFERTA_LALIGA_MIN = 0.90
OFERTA_LALIGA_MAX = 1.10
#: Lo que pagó de verdad la máquina en 51 ventas reales de esta liga (veces el valor de
#: mercado). Entre lunes y miércoles la mediana fue 1,034 (p25 1,012, mínimo 0,930);
#: vendiendo el viernes la mediana se hunde a 0,974. El 0,90 es el suelo legal, no lo observado.
OFERTA_MAQUINA_MEDIANA_LUN_MIE = 1.034
OFERTA_MAQUINA_P25_LUN_MIE = 1.012
OFERTA_MAQUINA_MINIMO_HISTORICO = 0.93
OFERTA_MAQUINA_MEDIANA_VIERNES = 0.974
#: Escenario esperado de la ruta de salida si se vende lun-mié: sin contar con la prima (p25 ≈ mediana ≈ 1,0).
OFERTA_ESPERADA_VENTANA = 1.00
#: Cláusula mínima (veces el valor) para dar por segura a una pieza clave si algún rival tiene caja
#: para pagarla. En la liga real los clausulazos se pagaron hasta 1,33×–1,40× de mediana, así que
#: 1,15× no protege nada.
MULTIPLO_CLAUSULA_SEGURA = 1.35
#: Los robos llegan en cuanto se abre el candado: mediana +0,8 h, con 4 en los primeros 0–6 minutos.
MINUTOS_PELIGRO_CRITICO = 60
AVISO_PELIGRO_CANDADO = "⏱️ Peligro crítico en los primeros 60 min tras abrirse el candado"
#: ``positionId`` de la ficha de entrenador en LaLiga Fantasy.
POSITION_ID_ENTRENADOR = 5


def es_entrenador(position_id: int | None, position: str | None) -> bool:
    if position_id == POSITION_ID_ENTRENADOR:
        return True
    if isinstance(position, str) and position.strip().upper() in {"ENT", "COACH", "ENTRENADOR"}:
        return True
    return False


def ficha_jugable(position_id: int | None, position: str | None) -> bool:
    """True si esta ficha se puede alinear y puntúa con el reglamento actual."""
    if isinstance(position, str) and position.strip().upper() in PUESTOS_JUGABLES:
        return True
    if ENTRENADOR_ACTIVO and es_entrenador(position_id, position):
        return True
    return False
