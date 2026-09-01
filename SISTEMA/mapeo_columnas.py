"""Normalizacion de encabezados de las matrices anuales hacia un esquema comun.

Basado en inspeccion real de las 8 matrices (2020-2026): los encabezados varian
en tildes, saltos de linea y nombres, pero representan un conjunto reducido de
conceptos comunes. Este modulo NO inventa columnas: solo reconoce variantes de
texto ya observadas en las matrices reales (ver REPORTES/INSPECCION_DETALLADA_MATRICES.md).

Si aparece un encabezado nuevo no reconocido, NO se descarta: se conserva su
valor dentro de observaciones_originales con el nombre de columna original,
para no perder informacion.
"""

import re
import unicodedata

# ---------------------------------------------------------------------------
# Normalizacion de texto de encabezado
# ---------------------------------------------------------------------------

def normalizar_texto(valor) -> str:
    """Mayusculas, sin tildes, sin saltos de linea, espacios colapsados, sin ':' final."""
    if valor is None:
        return ""
    s = str(valor)
    s = s.replace("\n", " ").replace("\r", " ")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.upper().strip()
    s = re.sub(r"\s+", " ", s)
    s = s.rstrip(":").strip()
    return s


# ---------------------------------------------------------------------------
# Encabezado normalizado -> "bucket" comun
# ---------------------------------------------------------------------------

ALIASES_ENCABEZADO = {
    "CODIGO": "CODIGO",
    "RUC": "RUC",
    "NATURALEZA": "NATURALEZA",
    "AMBITO": "AMBITO",
    "SECCION": "SECCION",
    "SECTOR": "SECTOR",
    "COMPARECIENTES": "COMPARECIENTES",
    "NOMBRE COMERCIAL": "NOMBRE_COMERCIAL",
    "ACTIVIDAD DE LA EMPRESA": "ACTIVIDAD_EMPRESA",
    "ACTIVIDAD ECONOMICA": "ACTIVIDAD_EMPRESA",
    "DIRECCION": "DIRECCION",
    "REPRESENTANTE LEGAL": "REPRESENTANTE_LEGAL",
    "CONTACTO": "CONTACTO",
    "NOMBRE DEL CONTACTO": "CONTACTO",
    "EMAIL": "EMAIL",
    "TELEFONO": "TELEFONO",
    "FECHA SUSCRIPCION": "FECHA_SUSCRIPCION",
    "FECHA DE SUSCRIPCION": "FECHA_SUSCRIPCION",
    "PERIODO DE VIGENCIA": "PERIODO_VIGENCIA",
    "PERIODO VIGENCIA": "PERIODO_VIGENCIA",
    "OBJETO": "OBJETO",
    "CARRERA GESTORA": "UNIDAD_GESTORA",
    "DEPENDENCIA GESTORA": "UNIDAD_GESTORA",
    "GESTOR": "UNIDAD_GESTORA",
    "CARRERAS BENEFICIADAS": "CARRERAS_BENEFICIADAS",
    "BENEFICIARIOS": "CARRERAS_BENEFICIADAS",
    "ADMINISTRADOR DE CONVENIO": "ADMINISTRADOR",
    "ADMINISTRADOR DE CONVENIO UTMACH": "ADMINISTRADOR",
    "ADMINISTRADOR DEL CONVENIO POR LA UTMACH": "ADMINISTRADOR",
    "ESTADO": "ESTADO_ORIGINAL",
    "OBSERVACIONES": "OBSERVACIONES",
    "OBSERVACION": "OBSERVACIONES",
    "OBERVACIONES": "OBSERVACIONES",
    "ALINEACION A LOS OBJETIVOS DE DESARROLLO SOSTENIBLE (ODS)": "ALINEACION_ODS",
    "OBJETIVO ESTRATEGICO INSTITUCIONAL": "OBJETIVO_ESTRATEGICO",
    "OBJETIVO ESTRATEGICO INSTITUCIONAL." : "OBJETIVO_ESTRATEGICO",
    "DOMINIOS ACADEMICOS QUE SE VINCULA": "DOMINIOS_ACADEMICOS",
    "TRAMITE PRESENTADO POR": "TRAMITE_PRESENTADO_POR",
    "TRAMITE INICIADO POR": "TRAMITE_PRESENTADO_POR",
    "LINK AL DOCUMENTO DIGITAL DEL CONVENIO": "LINK_DOCUMENTO",
    "LINK AL DOCUMENTO DIGITAL DE LA CARTA DE INTENCION": "LINK_DOCUMENTO",
}


def mapear_encabezados(encabezados_raw: list) -> dict:
    """Devuelve {indice_columna: bucket_comun} y {indice_columna: texto_original}
    para las columnas reconocidas. Las columnas no reconocidas simplemente no
    aparecen en el primer dict pero SI en el segundo (para poder conservarlas)."""
    mapa_bucket = {}
    mapa_original = {}
    for idx, encabezado in enumerate(encabezados_raw):
        if encabezado is None or str(encabezado).strip() == "":
            continue
        texto_original = str(encabezado).strip()
        mapa_original[idx] = texto_original
        clave = normalizar_texto(encabezado)
        bucket = ALIASES_ENCABEZADO.get(clave)
        if bucket:
            mapa_bucket[idx] = bucket
    return mapa_bucket, mapa_original


# ---------------------------------------------------------------------------
# Filas que NO son datos de convenio (pies de pagina de las matrices)
# ---------------------------------------------------------------------------

PREFIJOS_FILA_NO_DATO = (
    "AÑO:", "AÑO ", "ELABORADO POR", "ELABORADO:", "REVISADO POR", "REVISADO:",
    "APROBADO POR", "APROBADO:", "NOTA:", "OBSERVACION GENERAL",
)


def es_fila_no_dato(valores: list) -> bool:
    no_vacias = [v for v in valores if v not in (None, "")]
    if not no_vacias:
        return True
    if len(no_vacias) == 1:
        texto = normalizar_texto(no_vacias[0])
        if any(texto.startswith(normalizar_texto(p)) for p in PREFIJOS_FILA_NO_DATO):
            return True
    return False


# ---------------------------------------------------------------------------
# Catalogo de tipos: subtipo/hoja -> tipo_normalizado -> clasificacion_general
# ---------------------------------------------------------------------------
# Basado en los nombres de hoja y valores de NATURALEZA realmente encontrados.

_CATALOGO_TIPOS = [
    # (patrones que, normalizados, deben CONTENER esta subcadena, tipo_normalizado, clasificacion_general)
    ("MARCO", "MARCO DE COOPERACIÓN", "CONVENIO"),
    ("ESPECIFIC", "ESPECÍFICO DE COOPERACIÓN", "CONVENIO"),
    ("COOP", "ESPECÍFICO DE COOPERACIÓN", "CONVENIO"),  # fallback generico "COOP" si no matcheo MARCO/ESPECIFIC antes
    ("PRACTICAS Y PASANT", "PRÁCTICAS Y PASANTÍAS", "CONVENIO"),
    ("PRAC Y PAS", "PRÁCTICAS Y PASANTÍAS", "CONVENIO"),
    ("PRACTICA", "PRÁCTICAS PREPROFESIONALES", "CONVENIO"),
    ("PASANT", "PASANTÍAS", "CONVENIO"),
    ("VINCULACION", "PROYECTOS DE VINCULACIÓN", "CONVENIO"),
    ("SERVICIO COMUNITARIO", "SERVICIO COMUNITARIO", "CONVENIO"),
    ("CAPACITACION", "CAPACITACIÓN", "CONVENIO"),
    ("AVAL ACAD", "AVAL ACADÉMICO", "AVAL"),
    ("INVESTIGACION", "INVESTIGACIÓN", "CONVENIO"),
    ("MOVILIDAD", "MOVILIDAD ACADÉMICA", "CONVENIO"),
    ("FCT", "FORMACIÓN CENTROS DE TRABAJO", "CONVENIO"),
    ("CENTROS DE TRABAJO", "FORMACIÓN CENTROS DE TRABAJO", "CONVENIO"),
    ("CARTA DE INTENCION", "CARTA DE INTENCIÓN", "CARTA"),
    ("CARTAS DE INTENCION", "CARTA DE INTENCIÓN", "CARTA"),
    ("CARTA DE ENTENDIMIENTO", "CARTA DE ENTENDIMIENTO", "CARTA"),
    ("CARTAS DE ENTENDIMIENT", "CARTA DE ENTENDIMIENTO", "CARTA"),
    ("CARTA DE COMPROMISO", "CARTA DE COMPROMISO", "CARTA"),
    ("CARTA DE COMRPROMISO", "CARTA DE COMPROMISO", "CARTA"),  # typo real encontrado en 2021
    ("ADENDA", "ADENDA", "ADENDA"),
    ("MARCOS Y ESPECIFICOS", "MARCO DE COOPERACIÓN", "CONVENIO"),  # hoja mixta 2020/2021, se afina con NATURALEZA por fila
]


def clasificar_tipo(subtipo_original: str, nombre_hoja: str):
    """Devuelve (tipo_normalizado, clasificacion_general).

    Prioriza el valor de NATURALEZA (subtipo_original) de la fila si existe y
    es reconocible; si no, usa el nombre de la hoja. Si nada coincide, marca
    OTRO_INSTRUMENTO / POR_REVISAR en vez de adivinar.
    """
    candidatos = []
    if subtipo_original:
        candidatos.append(normalizar_texto(subtipo_original))
    if nombre_hoja:
        candidatos.append(normalizar_texto(nombre_hoja))

    for candidato in candidatos:
        # Reglas especificas primero (para no dejar que "COOP" generico se coma casos MARCO/ESPECIFICO)
        if "MARCO" in candidato:
            return "MARCO DE COOPERACIÓN", "CONVENIO"
        if "ESPECIFIC" in candidato:
            return "ESPECÍFICO DE COOPERACIÓN", "CONVENIO"
        if "PRACTICAS Y PASANT" in candidato or "PRAC Y PAS" in candidato:
            return "PRÁCTICAS Y PASANTÍAS", "CONVENIO"
        if "PRACTICA" in candidato:
            return "PRÁCTICAS PREPROFESIONALES", "CONVENIO"
        if "PASANT" in candidato:
            return "PASANTÍAS", "CONVENIO"
        if "VINCULACION" in candidato:
            return "PROYECTOS DE VINCULACIÓN", "CONVENIO"
        if "SERVICIO COMUNITARIO" in candidato:
            return "SERVICIO COMUNITARIO", "CONVENIO"
        if "CAPACITACION" in candidato:
            return "CAPACITACIÓN", "CONVENIO"
        if "AVAL ACAD" in candidato:
            return "AVAL ACADÉMICO", "AVAL"
        if "INVESTIGACION" in candidato:
            return "INVESTIGACIÓN", "CONVENIO"
        if "MOVILIDAD" in candidato:
            return "MOVILIDAD ACADÉMICA", "CONVENIO"
        if "FCT" in candidato or "CENTROS DE TRABAJO" in candidato or "CENTROS DE FORMACION" in candidato:
            return "FORMACIÓN CENTROS DE TRABAJO", "CONVENIO"
        if "CARTA" in candidato and "INTENCION" in candidato:
            return "CARTA DE INTENCIÓN", "CARTA"
        if "CARTA" in candidato and "ENTENDIMIENT" in candidato:
            return "CARTA DE ENTENDIMIENTO", "CARTA"
        if "CARTA" in candidato and ("COMPROMISO" in candidato or "COMRPROMISO" in candidato):
            return "CARTA DE COMPROMISO", "CARTA"
        if "ADENDA" in candidato or "ADENDUM" in candidato:
            return "ADENDA", "ADENDA"
        if "COOP" in candidato:
            return "ESPECÍFICO DE COOPERACIÓN", "CONVENIO"

    return "OTRO_INSTRUMENTO", "POR_REVISAR"
