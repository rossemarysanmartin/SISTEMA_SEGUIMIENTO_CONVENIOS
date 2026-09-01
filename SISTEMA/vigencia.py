"""Calculo de vigencia de convenios.

Regla estricta pedida por el usuario: NO asumir duraciones estandar. Solo se
calcula fecha_finalizacion cuando la propia matriz aporta suficiente
informacion explicita:

  a) Un rango de fechas explicito dentro del texto de "periodo de vigencia"
     (ej. "14/06/2021al 27/08/2021"), o
  b) Una fecha de suscripcion real + una duracion explicita en el mismo campo
     "periodo de vigencia" (ej. "5 años", "12 MESES", "60 días") tal como la
     escribio la propia oficina para ESE convenio especifico (no un valor que
     nosotros inventemos).

Si no hay informacion suficiente, fecha_finalizacion queda NULL y el estado
de vigencia es SIN_INFORMACION. Nunca se aplica una duracion por defecto.
"""

import re
from datetime import date, datetime, timedelta

MESES_POR_ANIO = 12
DIAS_POR_MES_APROX = 30  # solo para sumar "N meses" a una fecha, uso estandar de calendario abajo

RE_RANGO_FECHAS = re.compile(
    r"(\d{1,2})[/\\](\d{1,2})[/\\](\d{2,4})\s*(?:al|a|-|hasta)\s*(\d{1,2})[/\\](\d{1,2})[/\\](\d{2,4})",
    re.IGNORECASE,
)

RE_DURACION = re.compile(
    r"(\d+)\s*(años?|anos?|meses|mes|dias?|días?)",
    re.IGNORECASE,
)


def _parse_fecha_corta(d, m, y) -> date:
    y = int(y)
    if y < 100:
        y += 2000
    return date(y, int(m), int(d))


def _sumar_meses(fecha: date, meses: int) -> date:
    mes_total = fecha.month - 1 + meses
    anio = fecha.year + mes_total // 12
    mes = mes_total % 12 + 1
    dia = min(fecha.day, 28)  # evita errores en meses cortos; conservador
    return date(anio, mes, dia)


def extraer_rango_fechas_de_texto(texto: str):
    """Si el texto de periodo de vigencia contiene explicitamente un rango
    'dd/mm/aaaa al dd/mm/aaaa', devuelve (fecha_inicio, fecha_fin). Si no, None."""
    if not texto:
        return None
    m = RE_RANGO_FECHAS.search(texto)
    if not m:
        return None
    try:
        inicio = _parse_fecha_corta(m.group(1), m.group(2), m.group(3))
        fin = _parse_fecha_corta(m.group(4), m.group(5), m.group(6))
        return inicio, fin
    except ValueError:
        return None


def calcular_fecha_finalizacion(fecha_suscripcion, periodo_vigencia_texto: str):
    """Devuelve (fecha_inicio_o_None, fecha_finalizacion_o_None, metodo_str).

    metodo_str documenta como se obtuvo, para trazabilidad (notas_sistema).
    """
    if periodo_vigencia_texto:
        rango = extraer_rango_fechas_de_texto(str(periodo_vigencia_texto))
        if rango:
            return rango[0], rango[1], "RANGO_EXPLICITO_EN_PERIODO_VIGENCIA"

    if fecha_suscripcion and periodo_vigencia_texto:
        m = RE_DURACION.search(str(periodo_vigencia_texto))
        if m:
            cantidad = int(m.group(1))
            unidad = m.group(2).lower()
            if isinstance(fecha_suscripcion, datetime):
                fecha_suscripcion = fecha_suscripcion.date()
            try:
                if unidad.startswith(("año", "ano")):
                    fin = _sumar_meses(fecha_suscripcion, cantidad * MESES_POR_ANIO)
                elif unidad.startswith("mes"):
                    fin = _sumar_meses(fecha_suscripcion, cantidad)
                else:  # dias/días
                    fin = fecha_suscripcion + timedelta(days=cantidad)
                return fecha_suscripcion, fin, "DURACION_EXPLICITA_DESDE_FECHA_SUSCRIPCION"
            except ValueError:
                return None, None, "ERROR_CALCULO_DURACION"

    return None, None, "SIN_INFORMACION_SUFICIENTE"


def calcular_estado_vigencia(fecha_finalizacion, umbral_dias_proximo_vencer: int, hoy=None):
    if fecha_finalizacion is None:
        return "SIN_INFORMACION"
    if hoy is None:
        hoy = date.today()
    if isinstance(fecha_finalizacion, datetime):
        fecha_finalizacion = fecha_finalizacion.date()
    dias_restantes = (fecha_finalizacion - hoy).days
    if dias_restantes < 0:
        return "VENCIDO"
    if dias_restantes <= umbral_dias_proximo_vencer:
        return "PROXIMO_A_VENCER"
    return "VIGENTE"
