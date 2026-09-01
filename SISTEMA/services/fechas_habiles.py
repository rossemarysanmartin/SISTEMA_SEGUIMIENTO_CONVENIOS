"""Calculo simple de dias habiles (excluye sabados y domingos).

No incluye calendario de feriados institucionales -- se puede agregar despues
si se necesita mayor precision; por ahora es una aproximacion administrativa
razonable y explicitamente configurable desde config.json (umbral en dias
habiles), no una norma legal.
"""

from datetime import date, timedelta


def contar_dias_habiles(fecha_inicio: date, fecha_fin: date) -> int:
    if fecha_fin <= fecha_inicio:
        return 0
    dias = 0
    actual = fecha_inicio
    while actual < fecha_fin:
        actual += timedelta(days=1)
        if actual.weekday() < 5:  # lunes=0 ... viernes=4
            dias += 1
    return dias
