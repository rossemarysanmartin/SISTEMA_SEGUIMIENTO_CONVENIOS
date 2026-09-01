"""Analisis de solo lectura sobre archivos PDF.

Clasifica cada PDF como TEXTO_SELECCIONABLE, POSIBLE_ESCANEADO o ERROR_LECTURA,
y busca indicios (no confirmacion juridica) de firma electronica.

IMPORTANTE: este modulo solo ABRE archivos en modo lectura binaria ("rb").
Nunca escribe, nunca modifica el PDF original.

Cada archivo se lee UNA SOLA VEZ a memoria (leer_bytes) y ese mismo buffer se
reutiliza para el hash, la busqueda de firma y la extraccion de texto. Esto es
especialmente importante en OneDrive Files On-Demand, donde cada apertura de un
archivo no descargado localmente ("cloud-only") dispara una descarga desde la
nube: leer el archivo varias veces por separado multiplicaba innecesariamente
el tiempo de sincronizacion inicial.
"""

import hashlib
import io
from pathlib import Path

try:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
except ImportError:  # pypdf aun no instalado
    PdfReader = None
    PdfReadError = Exception

MARCADORES_FIRMA = [b"/ByteRange", b"/SubFilter", b"/Sig ", b"/Sig/", b"adbe.pkcs7", b"ETSI.CAdES"]


def leer_bytes(ruta: Path) -> bytes:
    """Lee el archivo completo en modo binario, una unica vez."""
    with open(ruta, "rb") as f:
        return f.read()


def calcular_hash_sha256(ruta: Path) -> str:
    """Atajo de conveniencia para archivos que no requieren analisis adicional
    (p. ej. las matrices .xlsx, donde una unica lectura no es un problema de rendimiento)."""
    return calcular_hash_sha256_bytes(leer_bytes(ruta))


def calcular_hash_sha256_bytes(contenido: bytes) -> str:
    return hashlib.sha256(contenido).hexdigest()


def buscar_indicios_firma_bytes(contenido: bytes) -> tuple[bool, str]:
    """Busca marcadores tipicos de firma digital/electronica en el binario del PDF.

    Esto es un INDICIO, no una validacion juridica de firma electronica valida.
    """
    encontrados = [m.decode("latin-1") for m in MARCADORES_FIRMA if m in contenido]
    if encontrados:
        return True, "Marcadores encontrados: " + ", ".join(sorted(set(encontrados)))
    return False, ""


def clasificar_pdf_bytes(contenido: bytes, num_paginas_muestra: int, min_caracteres: int) -> dict:
    """Devuelve un dict con: tipo_pdf, num_paginas, firma_detectada, indicios_firma, error_detalle."""
    resultado = {
        "tipo_pdf": "ERROR_LECTURA",
        "num_paginas": None,
        "firma_electronica_detectada": False,
        "indicios_firma": "",
        "error_detalle": None,
    }

    if PdfReader is None:
        resultado["error_detalle"] = "pypdf no esta instalado"
        return resultado

    try:
        reader = PdfReader(io.BytesIO(contenido), strict=False)
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                resultado["tipo_pdf"] = "REVIEW_REQUIRED"
                resultado["error_detalle"] = "PDF cifrado, no se pudo abrir sin contrasena"
                return resultado

        num_paginas = len(reader.pages)
        resultado["num_paginas"] = num_paginas

        texto_total = ""
        for i, pagina in enumerate(reader.pages):
            if i >= num_paginas_muestra:
                break
            try:
                texto_total += pagina.extract_text() or ""
            except Exception:
                continue

        if len(texto_total.strip()) >= min_caracteres:
            resultado["tipo_pdf"] = "TEXTO_SELECCIONABLE"
        else:
            resultado["tipo_pdf"] = "POSIBLE_ESCANEADO"

    except Exception as e:
        resultado["tipo_pdf"] = "ERROR_LECTURA"
        resultado["error_detalle"] = str(e)
        return resultado

    firma_detectada, indicios = buscar_indicios_firma_bytes(contenido)
    resultado["firma_electronica_detectada"] = firma_detectada
    resultado["indicios_firma"] = indicios

    return resultado
