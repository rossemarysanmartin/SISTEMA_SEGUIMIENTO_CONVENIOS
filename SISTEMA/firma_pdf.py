"""Extraccion de INDICIOS TECNICOS de firma electronica desde el binario del
PDF. Esto NUNCA es una validacion juridica de firma valida: solo reporta
metadatos que el propio archivo declara en su diccionario de firma (/Sig),
que suelen viajar como texto plano junto al /ByteRange (no van cifrados).

Solo lee el archivo en modo binario. No lo modifica.
"""

import re
from pathlib import Path

RE_BYTERANGE = re.compile(rb"/ByteRange")
RE_NAME = re.compile(rb"/Name\s*\(([^)]*)\)")
RE_REASON = re.compile(rb"/Reason\s*\(([^)]*)\)")
RE_LOCATION = re.compile(rb"/Location\s*\(([^)]*)\)")
RE_FECHA_FIRMA = re.compile(rb"/M\s*\(D:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})")
RE_SUBFILTER = re.compile(rb"/SubFilter\s*/(\S+)")

VENTANA_BYTES = 2000  # cuanto mirar alrededor de cada /ByteRange para hallar campos del mismo diccionario de firma


def _decodificar(valor: bytes) -> str:
    try:
        return valor.decode("latin-1").strip()
    except Exception:
        return ""


def analizar_firmas(ruta: Path) -> dict:
    """Devuelve dict con: cantidad_firmas, firmante_certificado, fecha_firma_metadato,
    emisor_certificado(no siempre disponible), razon_firma, subfilter, error."""
    resultado = {
        "cantidad_firmas": 0,
        "firmante_certificado": None,
        "fecha_firma_metadato": None,
        "emisor_certificado": None,
        "razon_firma": None,
        "subfilter": None,
        "error": None,
    }
    try:
        with open(ruta, "rb") as f:
            contenido = f.read()
    except OSError as e:
        resultado["error"] = str(e)
        return resultado

    posiciones = [m.start() for m in RE_BYTERANGE.finditer(contenido)]
    resultado["cantidad_firmas"] = len(posiciones)
    if not posiciones:
        return resultado

    # Analizar la primera firma encontrada para los metadatos "principales"
    inicio = max(0, posiciones[0] - VENTANA_BYTES)
    fin = min(len(contenido), posiciones[0] + VENTANA_BYTES)
    ventana = contenido[inicio:fin]

    m = RE_NAME.search(ventana)
    if m:
        resultado["firmante_certificado"] = _decodificar(m.group(1))
    m = RE_REASON.search(ventana)
    if m:
        resultado["razon_firma"] = _decodificar(m.group(1))
    m = RE_LOCATION.search(ventana)
    if m:
        resultado["emisor_certificado"] = _decodificar(m.group(1))  # aproximado: ubicacion, no siempre es el emisor real
    m = RE_FECHA_FIRMA.search(ventana)
    if m:
        y, mo, d, h, mi, s = m.groups()
        resultado["fecha_firma_metadato"] = f"{y.decode()}-{mo.decode()}-{d.decode()}T{h.decode()}:{mi.decode()}:{s.decode()}"
    m = RE_SUBFILTER.search(ventana)
    if m:
        resultado["subfilter"] = _decodificar(m.group(1))

    return resultado
