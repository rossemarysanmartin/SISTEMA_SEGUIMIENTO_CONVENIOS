"""Lectura de solo lectura del contenido de un PDF (texto y, si es necesario y
posible, OCR de un numero acotado de paginas). Nunca escribe ni modifica el
PDF original.
"""

import shutil
from pathlib import Path

import fitz  # PyMuPDF

_TESSERACT_DISPONIBLE = None


def tesseract_disponible() -> bool:
    global _TESSERACT_DISPONIBLE
    if _TESSERACT_DISPONIBLE is None:
        _TESSERACT_DISPONIBLE = shutil.which("tesseract") is not None
    return _TESSERACT_DISPONIBLE


def extraer_texto_pdf(ruta: Path, max_paginas_ocr: int = 6):
    """Devuelve dict: {metodo, paginas: [(num, texto)], error, paginas_ocr_intentadas}.

    metodo: TEXTO_PDF | OCR | OCR_NO_DISPONIBLE | ERROR_LECTURA
    """
    try:
        doc = fitz.open(str(ruta))
    except Exception as e:
        return {"metodo": "ERROR_LECTURA", "paginas": [], "error": str(e)}

    paginas_texto = []
    try:
        for i in range(len(doc)):
            texto = doc[i].get_text("text") or ""
            paginas_texto.append((i + 1, texto))
    except Exception as e:
        doc.close()
        return {"metodo": "ERROR_LECTURA", "paginas": [], "error": str(e)}

    texto_total = "".join(t for _, t in paginas_texto).strip()
    if len(texto_total) >= 30:
        doc.close()
        return {"metodo": "TEXTO_PDF", "paginas": paginas_texto, "error": None}

    # Poco o ningun texto -> intentar OCR si esta disponible
    if not tesseract_disponible():
        doc.close()
        return {"metodo": "OCR_NO_DISPONIBLE", "paginas": paginas_texto, "error": "Tesseract no instalado en este equipo"}

    import pytesseract
    from PIL import Image
    import io

    paginas_ocr = []
    try:
        for i in range(min(len(doc), max_paginas_ocr)):
            pix = doc[i].get_pixmap(dpi=200)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            texto_ocr = pytesseract.image_to_string(img, lang="spa+eng")
            paginas_ocr.append((i + 1, texto_ocr))
    except Exception as e:
        doc.close()
        return {"metodo": "ERROR_LECTURA", "paginas": paginas_texto, "error": f"Fallo OCR: {e}"}

    doc.close()
    return {"metodo": "OCR", "paginas": paginas_ocr, "error": None}


def contar_paginas(ruta: Path):
    try:
        doc = fitz.open(str(ruta))
        n = len(doc)
        doc.close()
        return n
    except Exception:
        return None
