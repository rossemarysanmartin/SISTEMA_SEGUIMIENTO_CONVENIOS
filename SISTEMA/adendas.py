"""Deteccion (no exhaustiva) de posibles adendas asociadas a un convenio,
buscando en las carpetas de tipo 'ADENDA/ADENDAS' del mismo año documentos
cuyo nombre se parezca al codigo o a la institucion del convenio.

Esto es solo una SEÑAL (TIENE_ADENDA = SI/NO/POR_REVISAR), no una relacion
definitiva; la trazabilidad completa de adendas es una fase posterior.
"""

import re

from relacionar_documentos import normalizar, extraer_digitos, _quitar_ceros_izq
from difflib import SequenceMatcher

# Umbrales altos a proposito: el pool de nombres de archivo en cada carpeta
# ADENDA/año es pequeño, y sufijos societarios compartidos (CIA LTDA, S A,
# COMPANIA LIMITADA...) inflan artificialmente el ratio de similitud entre
# instituciones completamente distintas si no se eliminan antes de comparar.
UMBRAL_RATIO_ADENDA = 0.75
UMBRAL_RATIO_POR_REVISAR = 0.6
LONGITUD_MINIMA_COMPARACION = 6

_SUFIJOS_SOCIETARIOS = re.compile(
    r"\b(cia|compania|ltda|limitada|sa|s a|anonima|ep|cem|ecuador"
    # palabras institucionales genericas: "GOBIERNO AUTONOMO DESCENTRALIZADO DE
    # CANTON X" comparte casi todo el texto entre decenas de GAD distintos; lo
    # unico distintivo suele ser el nombre propio del canton/parroquia al final.
    r"|gobierno|autonomo|descentralizado|municipal|municipio|parroquial|provincial"
    r"|canton|consejo|nacional|de|del|la|las|el|los)\b",
    re.IGNORECASE,
)


def _nombre_significativo(texto_normalizado: str) -> str:
    """Quita sufijos societarios genericos que no aportan señal de identidad
    (p.ej. 'CIA LTDA' aparece en decenas de instituciones distintas)."""
    sin_sufijos = _SUFIJOS_SOCIETARIOS.sub(" ", texto_normalizado)
    return re.sub(r"\s+", " ", sin_sufijos).strip()


def construir_indice_adendas(documentos_por_anio: dict) -> dict:
    """documentos_por_anio: {anio: [dict de la tabla documentos]}.
    Devuelve {anio: [ (nombre_norm, ruta) ]} solo para carpeta_tipo que contenga ADENDA."""
    indice = {}
    for anio, docs in documentos_por_anio.items():
        candidatos = []
        for d in docs:
            carpeta = normalizar(d.get("carpeta_tipo") or "")
            if "ADENDA" in carpeta:
                nombre_norm = normalizar(d["nombre"].rsplit(".", 1)[0])
                candidatos.append((nombre_norm, d["ruta"]))
        indice[anio] = candidatos
    return indice


def buscar_posible_adenda(anio: int, codigo_original: str, institucion: str, indice_adendas: dict):
    candidatos = indice_adendas.get(anio, [])
    if not candidatos:
        return "NO", None, None

    numero = _quitar_ceros_izq(codigo_original) if codigo_original else None
    inst_norm = normalizar(institucion or "")
    inst_significativa = _nombre_significativo(inst_norm)

    mejor_ruta, mejor_ratio, mejor_motivo = None, 0.0, None
    for nombre_norm, ruta in candidatos:
        if numero and numero != "0":
            digitos = [_quitar_ceros_izq(d) for d in extraer_digitos(nombre_norm)]
            if numero in digitos:
                return "SI", ruta, f"Coincidencia de código '{numero}' en carpeta de adendas"
        if len(inst_significativa) < LONGITUD_MINIMA_COMPARACION:
            continue
        nombre_significativo = _nombre_significativo(nombre_norm)
        if len(nombre_significativo) < LONGITUD_MINIMA_COMPARACION:
            continue
        ratio = SequenceMatcher(None, inst_significativa, nombre_significativo).ratio()
        if ratio > mejor_ratio:
            mejor_ratio, mejor_ruta, mejor_motivo = ratio, ruta, f"similitud de institución (ratio {ratio:.2f})"

    if mejor_ratio >= UMBRAL_RATIO_ADENDA:
        return "SI", mejor_ruta, mejor_motivo
    if mejor_ratio >= UMBRAL_RATIO_POR_REVISAR:
        return "POR_REVISAR", mejor_ruta, mejor_motivo
    return "NO", None, None
