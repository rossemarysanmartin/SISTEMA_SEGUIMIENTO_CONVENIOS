"""Extraccion heuristica (regex) de datos desde el texto de un convenio.

Los convenios de UTMACH suelen usar clausulas numeradas en espanol
("PRIMERA.- ANTECEDENTES", "SEGUNDA.- OBJETO", "... VIGENCIA", "...
ADMINISTRACION DEL CONVENIO", etc.). Esta heuristica primero intenta partir
el texto por esas clausulas; si no encuentra esa estructura, busca por
ventana de contexto alrededor de palabras clave.

Ningun valor se inventa: si no hay evidencia razonable, se devuelve None y
el nivel de confianza correspondiente (o ausencia de evidencia).
"""

import re
import unicodedata
from datetime import date

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

RE_CLAUSULA = re.compile(
    r"\n\s*(PRIMERA|SEGUNDA|TERCERA|CUARTA|QUINTA|SEXTA|S[ÉE]PTIMA|OCTAVA|NOVENA|D[ÉE]CIMA(?:\s+(?:PRIMERA|SEGUNDA|TERCERA|CUARTA|QUINTA))?)"
    r"[\.\-:\)]?\s*[\.\-:]?\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ \.]{2,60})",
)

RE_FECHA_LARGA = re.compile(
    r"(\d{1,2})\s+d[ií]as?\s+del\s+mes\s+de\s+(\w+)\s+de[l]?\s+(\d{4})"
    r"|(\d{1,2})\s+de\s+(\w+)\s+de[l]?\s+(\d{4})",
    re.IGNORECASE,
)

# Formula de cierre tipica de documentos legales ecuatorianos: "...a los XX dias
# del mes de MES de AAAA...", casi siempre junto a las firmas, al final del
# documento. Se prioriza sobre cualquier otra fecha larga encontrada en el
# cuerpo del texto (que puede referirse a leyes, decretos, u otros hechos).
RE_FORMULA_CIERRE = re.compile(
    r"a\s+los\s+(\d{1,2})\s+d[ií]as?\s+del\s+mes\s+de\s+(\w+)\s+de[l]?\s+(\d{4})",
    re.IGNORECASE,
)

ANIO_MINIMO_PLAUSIBLE = 2015
ANIO_MAXIMO_PLAUSIBLE = 2027

RE_HASTA_FECHA = re.compile(
    r"(?:vigencia|vigente|plazo)[^.]{0,80}?hasta\s+el\s+(?:d[ií]a\s+)?(\d{1,2})\s+de\s+(\w+)\s+de[l]?\s+(\d{4})",
    re.IGNORECASE,
)

RE_HASTA_FECHA_NUM = re.compile(
    r"(?:vigencia|vigente|plazo)[^.]{0,80}?hasta\s+el\s+(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})",
    re.IGNORECASE,
)

RE_DURACION = re.compile(r"(\d+)\s*(años?|anos?|meses|mes|d[ií]as?)\b", re.IGNORECASE)

_NUMEROS_TEXTO = {
    "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11,
    "doce": 12, "trece": 13, "catorce": 14, "quince": 15, "veinte": 20,
}

# Duracion escrita en palabras sin digitos, p.ej. "vigencia de DOS AÑOS" o
# "CINCO (5) AÑOS" (aqui solo la parte en palabras; el digito entre parentesis
# ya lo cubre RE_DURACION).
RE_DURACION_PALABRA = re.compile(
    r"\b(" + "|".join(_NUMEROS_TEXTO.keys()) + r")\s*(?:\(\d+\)\s*)?(años?|anos?|meses|mes|d[ií]as?)\b",
    re.IGNORECASE,
)

# Las clausulas de plazo casi siempre expresan la vigencia TOTAL en años; menciones
# de dias/meses cerca de estas palabras suelen ser plazos de AVISO PREVIO o
# TERMINACION ANTICIPADA, no la duracion del convenio, y no deben confundirse con ella.
_VENTANA_EXCLUSION_DURACION = 60
RE_EXCLUSION_DURACION = re.compile(
    r"aviso\s+previ|notificaci|previ[ao]\s+notificaci|denunci|terminaci[oó]n\s+anticipad|prorrog",
    re.IGNORECASE,
)


def _duracion_preferida(texto_busqueda: str):
    """Devuelve (cantidad, unidad, texto_fuente, match_obj) para la duracion mas
    confiable dentro de texto_busqueda, o None si no hay ninguna razonable.

    Prioriza: 1) unidad AÑOS sobre MESES/DIAS (la vigencia total casi siempre se
    expresa en años); 2) candidatos lejos de palabras de aviso/terminacion
    anticipada/prorroga (que indican que el numero no es la duracion total);
    3) el primer candidato valido que cumpla lo anterior."""
    candidatos = []
    for m in RE_DURACION.finditer(texto_busqueda):
        candidatos.append((int(m.group(1)), m.group(2).lower(), m.start(), m.end(), m.group(0)))
    for m in RE_DURACION_PALABRA.finditer(texto_busqueda):
        cantidad = _NUMEROS_TEXTO.get(_quitar_tildes(m.group(1).lower()))
        if cantidad:
            candidatos.append((cantidad, m.group(2).lower(), m.start(), m.end(), m.group(0)))
    if not candidatos:
        return None

    def es_excluido(inicio, fin):
        ventana = texto_busqueda[max(0, inicio - _VENTANA_EXCLUSION_DURACION):fin + _VENTANA_EXCLUSION_DURACION]
        return bool(RE_EXCLUSION_DURACION.search(ventana))

    candidatos.sort(key=lambda c: c[2])  # orden de aparicion en el texto
    no_excluidos = [c for c in candidatos if not es_excluido(c[2], c[3])]
    fuente = no_excluidos or candidatos

    en_anios = [c for c in fuente if c[1].startswith(("año", "ano"))]
    elegido = en_anios[0] if en_anios else fuente[0]
    cantidad, unidad, inicio, fin, texto_match = elegido
    return cantidad, unidad, texto_match, inicio

RE_ADENDA = re.compile(r"adenda|ad[eé]ndum", re.IGNORECASE)
RE_RENOVACION = re.compile(r"renovaci[oó]n|renovable|prorrog", re.IGNORECASE)


def _quitar_tildes(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def _texto_completo_con_paginas(paginas: list) -> str:
    return "\n".join(f"\n[[PAGINA {n}]]\n{t}" for n, t in paginas)


def _pagina_de_offset(texto_con_marcas: str, offset: int) -> int:
    fragmento = texto_con_marcas[:offset]
    marcas = re.findall(r"\[\[PAGINA (\d+)\]\]", fragmento)
    return int(marcas[-1]) if marcas else 1


def dividir_en_clausulas(paginas: list) -> dict:
    """Devuelve {titulo_normalizado: (texto_clausula, pagina)}. Vacio si no hay estructura reconocible."""
    texto = _texto_completo_con_paginas(paginas)
    coincidencias = list(RE_CLAUSULA.finditer(texto))
    clausulas = {}
    for i, m in enumerate(coincidencias):
        titulo = _quitar_tildes(m.group(2)).strip().upper()
        inicio_cuerpo = m.end()
        fin_cuerpo = coincidencias[i + 1].start() if i + 1 < len(coincidencias) else len(texto)
        cuerpo = texto[inicio_cuerpo:fin_cuerpo].strip()
        pagina = _pagina_de_offset(texto, m.start())
        clausulas[titulo] = (cuerpo, pagina)
    return clausulas


def _buscar_clausula_por_palabra(clausulas: dict, *palabras):
    for titulo, (cuerpo, pagina) in clausulas.items():
        if any(p in titulo for p in palabras):
            return titulo, cuerpo, pagina
    return None, None, None


def _parsear_fecha_larga(match) -> date:
    grupos = match.groups()
    if grupos[0] is not None:
        dia, mes_txt, anio = grupos[0], grupos[1], grupos[2]
    else:
        dia, mes_txt, anio = grupos[3], grupos[4], grupos[5]
    mes = MESES.get(_quitar_tildes(mes_txt.lower()))
    if not mes:
        return None
    try:
        return date(int(anio), mes, int(dia))
    except ValueError:
        return None


def _anio_plausible(fecha: date) -> bool:
    return ANIO_MINIMO_PLAUSIBLE <= fecha.year <= ANIO_MAXIMO_PLAUSIBLE


def extraer_fecha_suscripcion(paginas: list):
    """Prioriza la formula de cierre legal 'a los X dias del mes de MES de AAAA'
    (tipicamente junto a las firmas). Si no aparece, cae a una fecha larga generica
    pero solo dentro del ultimo tramo del documento y con año dentro de un rango
    plausible (evita capturar decretos, antecedentes o membretes historicos, p.ej.
    la fecha de creacion de la universidad '14 de abril de 1969')."""
    texto = _texto_completo_con_paginas(paginas)

    candidatos_formula = []
    for m in RE_FORMULA_CIERRE.finditer(texto):
        dia, mes_txt, anio = m.group(1), m.group(2), m.group(3)
        mes = MESES.get(_quitar_tildes(mes_txt.lower()))
        if not mes:
            continue
        try:
            fecha = date(int(anio), mes, int(dia))
        except ValueError:
            continue
        if not _anio_plausible(fecha):
            continue
        pagina = _pagina_de_offset(texto, m.start())
        fragmento = texto[max(0, m.start() - 60):m.end() + 10].replace("\n", " ").strip()
        candidatos_formula.append((fecha, fragmento, pagina))
    if candidatos_formula:
        fecha, fragmento, pagina = candidatos_formula[-1]
        confianza = "ALTA" if len(candidatos_formula) == 1 else "MEDIA"
        return fecha, fragmento, pagina, confianza

    # Sin formula de cierre: buscar fecha larga generica, pero solo en el ultimo
    # 30% del texto (zona de firmas) y con año plausible para un convenio 2020-2026.
    inicio_zona_firma = int(len(texto) * 0.7)
    mejores = []
    for m in RE_FECHA_LARGA.finditer(texto):
        if m.start() < inicio_zona_firma:
            continue
        fecha = _parsear_fecha_larga(m)
        if fecha and _anio_plausible(fecha):
            pagina = _pagina_de_offset(texto, m.start())
            fragmento = texto[max(0, m.start() - 60):m.end() + 10].replace("\n", " ").strip()
            mejores.append((fecha, fragmento, pagina))
    if not mejores:
        return None, None, None, None
    fecha, fragmento, pagina = mejores[-1]
    confianza = "MEDIA" if len(mejores) == 1 else "BAJA"
    return fecha, fragmento, pagina, confianza


def extraer_vigencia(paginas: list, clausulas: dict):
    """Devuelve dict: fecha_fin, metodo, texto_fuente, pagina, plazo_texto, unidad, confianza."""
    resultado = {
        "fecha_fin": None, "metodo": "SIN_INFORMACION_SUFICIENTE", "texto_fuente": None,
        "pagina": None, "plazo_texto": None, "unidad": None, "confianza": None,
    }

    titulo, cuerpo, pagina = _buscar_clausula_por_palabra(clausulas, "VIGENCIA")
    texto_busqueda = cuerpo if cuerpo else _texto_completo_con_paginas(paginas)
    texto_con_marcas = _texto_completo_con_paginas(paginas)

    # Caso A: fecha explicita "hasta el ..."
    m = RE_HASTA_FECHA.search(texto_busqueda)
    mes_num = MESES.get(_quitar_tildes(m.group(2).lower())) if m else None
    if m and mes_num:
        try:
            fecha = date(int(m.group(3)), mes_num, int(m.group(1)))
            resultado.update({
                "fecha_fin": fecha, "metodo": "FECHA_EXPLICITA_EN_CLAUSULA",
                "texto_fuente": m.group(0), "pagina": pagina or _pagina_de_offset(texto_con_marcas, texto_con_marcas.find(m.group(0))),
                "confianza": "ALTA",
            })
            return resultado
        except ValueError:
            pass

    m = RE_HASTA_FECHA_NUM.search(texto_busqueda)
    if m:
        try:
            anio = int(m.group(3)); anio = anio + 2000 if anio < 100 else anio
            fecha = date(anio, int(m.group(2)), int(m.group(1)))
            resultado.update({
                "fecha_fin": fecha, "metodo": "FECHA_EXPLICITA_EN_CLAUSULA",
                "texto_fuente": m.group(0), "pagina": pagina, "confianza": "ALTA",
            })
            return resultado
        except ValueError:
            pass

    # Caso B/C: duracion en la propia clausula de vigencia (se prefiere la
    # expresada en años, y se evitan plazos de aviso previo/terminacion
    # anticipada que no son la duracion total del convenio)
    preferida = _duracion_preferida(texto_busqueda)
    if preferida:
        cantidad, unidad, texto_match, offset_local = preferida
        # Se normaliza a forma numerica ("N unidad") para que vigencia.calcular_fecha_finalizacion
        # (que solo reconoce digitos) la parsee sin depender de si el documento
        # escribio el numero en palabras (p.ej. "dos años" sin digito).
        resultado["plazo_texto"] = f"{cantidad} {unidad}"
        resultado["unidad"] = unidad
        resultado["texto_fuente"] = texto_busqueda[max(0, offset_local - 60):offset_local + len(texto_match) + 60].replace("\n", " ").strip()
        resultado["pagina"] = pagina
        resultado["metodo"] = "DURACION_EN_CLAUSULA_VIGENCIA" if titulo else "DURACION_EN_TEXTO_GENERAL"
        resultado["confianza"] = "ALTA" if titulo else "MEDIA"
        # el calculo real de fecha_fin se hace afuera (necesita fecha_suscripcion)

    if RE_RENOVACION.search(texto_busqueda):
        resultado["renovacion_detectada"] = True
        resultado["texto_renovacion"] = texto_busqueda[:400].replace("\n", " ").strip()
    else:
        resultado["renovacion_detectada"] = False

    return resultado


def extraer_administrador(paginas: list, clausulas: dict):
    titulo, cuerpo, pagina = _buscar_clausula_por_palabra(clausulas, "ADMINISTRACION", "ADMINISTRADOR")
    if cuerpo:
        fragmento = cuerpo[:500].replace("\n", " ").strip()
        return fragmento, pagina, "ALTA"

    texto = _texto_completo_con_paginas(paginas)
    m = re.search(r"[Aa]dministrador(?:a)?\s+del\s+[Cc]onvenio[^.]{0,200}\.", texto)
    if m:
        pagina = _pagina_de_offset(texto, m.start())
        return m.group(0).replace("\n", " ").strip(), pagina, "MEDIA"

    return None, None, None


def extraer_objeto(paginas: list, clausulas: dict):
    titulo, cuerpo, pagina = _buscar_clausula_por_palabra(clausulas, "OBJETO")
    if cuerpo:
        objeto_original = cuerpo.strip()
        resumen = objeto_original[:300].strip()
        return objeto_original, resumen, pagina, "ALTA"
    return None, None, None, None


def detectar_mencion_adenda(paginas: list):
    texto = _texto_completo_con_paginas(paginas)
    m = RE_ADENDA.search(texto)
    if not m:
        return False, None
    pagina = _pagina_de_offset(texto, m.start())
    fragmento = texto[max(0, m.start() - 60):m.end() + 60].replace("\n", " ").strip()
    return True, (fragmento, pagina)
