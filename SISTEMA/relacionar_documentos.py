"""Relaciona cada registro de convenio (extraido de las matrices) con su
expediente documental (archivo PDF) ya inventariado en convenios_sistema.db
(Fase 0/1). Estrategia progresiva y conservadora: codigo primero, institucion
despues. Nunca elige arbitrariamente entre dos PDFs igualmente probables.

No modifica ningun archivo. Solo lee convenios_sistema.db y compara texto.
"""

import re
import unicodedata
from difflib import SequenceMatcher

UMBRAL_RATIO_PROBABLE = 0.55
DELTA_UNICO = 0.12

ABREVIATURAS_POR_TIPO = {
    "MARCO DE COOPERACIÓN": ["COOP", "MARCO"],
    "ESPECÍFICO DE COOPERACIÓN": ["COOP", "ESPECIFICO", "ESP"],
    "PRÁCTICAS PREPROFESIONALES": ["PP"],
    "PASANTÍAS": ["PS"],
    "PRÁCTICAS Y PASANTÍAS": ["PP", "PS"],
    "PROYECTOS DE VINCULACIÓN": ["VS", "VINCULACION"],
    "CAPACITACIÓN": ["CAPACITACION"],
    "AVAL ACADÉMICO": ["AA", "AC"],
    "INVESTIGACIÓN": ["I"],
    "MOVILIDAD ACADÉMICA": ["MOVILIDAD"],
    "FORMACIÓN CENTROS DE TRABAJO": ["FCT"],
}


def normalizar(texto: str) -> str:
    if not texto:
        return ""
    s = unicodedata.normalize("NFKD", str(texto))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.upper()
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def extraer_digitos(texto: str):
    if not texto:
        return []
    return re.findall(r"\d+", texto)


def _quitar_ceros_izq(s: str) -> str:
    return s.lstrip("0") or "0"


def _codigo_coincide(convenio: dict, nombre_archivo_norm: str) -> bool:
    numero = convenio.get("numero_original")
    if not numero:
        return False
    numero_sin_ceros = _quitar_ceros_izq(numero)
    digitos_archivo = extraer_digitos(nombre_archivo_norm)
    if numero_sin_ceros not in [_quitar_ceros_izq(d) for d in digitos_archivo]:
        return False

    abreviaturas = ABREVIATURAS_POR_TIPO.get(convenio.get("tipo_instrumento"), [])
    if not abreviaturas:
        return True  # sin abreviatura conocida para este tipo, el numero ya es bastante especifico
    tokens = nombre_archivo_norm.split()
    return any(ab in tokens or ab in nombre_archivo_norm for ab in abreviaturas)


def _ratio_institucion(institucion: str, nombre_archivo_norm: str) -> float:
    if not institucion:
        return 0.0
    inst_norm = normalizar(institucion)
    if not inst_norm:
        return 0.0
    return SequenceMatcher(None, inst_norm, nombre_archivo_norm).ratio()


def relacionar_convenio_con_documentos(convenio: dict, documentos_candidatos: list):
    """documentos_candidatos: lista de dicts de la tabla 'archivos' (mismo anio).
    Devuelve (estado_relacion, confianza_0_100, doc_elegido_o_None, notas)."""

    disponibles = [d for d in documentos_candidatos if d.get("extension") == ".pdf"]
    if not disponibles:
        return "NO_ENCONTRADA", 0, None, "No hay documentos PDF para ese año."

    for d in disponibles:
        d["_nombre_norm"] = normalizar(d["nombre_archivo"].rsplit(".", 1)[0])

    # Paso 1: coincidencia por codigo
    coincidencias_codigo = [d for d in disponibles if _codigo_coincide(convenio, d["_nombre_norm"])]
    if len(coincidencias_codigo) == 1:
        return "CONFIRMADA", 95, coincidencias_codigo[0], "Coincidencia por código/número + tipo de instrumento."
    if len(coincidencias_codigo) > 1:
        # desempatar por institucion si es posible
        coincidencias_codigo.sort(key=lambda d: _ratio_institucion(convenio.get("institucion"), d["_nombre_norm"]), reverse=True)
        mejor, segundo = coincidencias_codigo[0], coincidencias_codigo[1]
        r1 = _ratio_institucion(convenio.get("institucion"), mejor["_nombre_norm"])
        r2 = _ratio_institucion(convenio.get("institucion"), segundo["_nombre_norm"])
        if r1 >= UMBRAL_RATIO_PROBABLE and (r1 - r2) >= DELTA_UNICO:
            return "PROBABLE", round(r1 * 85), mejor, f"Varios archivos con el mismo código; se distinguió por nombre de institución (ratio {r1:.2f})."
        return "MULTIPLES_COINCIDENCIAS", 0, None, f"{len(coincidencias_codigo)} archivos comparten el mismo código para este tipo/año."

    # Paso 2: coincidencia por institucion (fuzzy) sobre todos los candidatos del año
    puntuados = sorted(disponibles, key=lambda d: _ratio_institucion(convenio.get("institucion"), d["_nombre_norm"]), reverse=True)
    mejor = puntuados[0]
    r1 = _ratio_institucion(convenio.get("institucion"), mejor["_nombre_norm"])
    r2 = _ratio_institucion(convenio.get("institucion"), puntuados[1]["_nombre_norm"]) if len(puntuados) > 1 else 0.0

    if r1 >= UMBRAL_RATIO_PROBABLE and (r1 - r2) >= DELTA_UNICO:
        return "PROBABLE", round(r1 * 80), mejor, f"Coincidencia por similitud de nombre de institución (ratio {r1:.2f})."
    if r1 >= UMBRAL_RATIO_PROBABLE:
        empatados = [d for d in puntuados if abs(_ratio_institucion(convenio.get("institucion"), d["_nombre_norm"]) - r1) < 0.03]
        return "MULTIPLES_COINCIDENCIAS", 0, None, f"{len(empatados)} archivos con similitud de nombre parecida (ratio ~{r1:.2f}); no se elige automáticamente."

    return "NO_ENCONTRADA", 0, None, "Ningún documento del año coincide por código ni por nombre de institución."
