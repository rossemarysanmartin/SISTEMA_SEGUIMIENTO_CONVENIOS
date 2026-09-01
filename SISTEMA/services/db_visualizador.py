"""Capa de acceso a datos del visualizador web.

Solo hace consultas de LECTURA sobre BASE_DATOS/convenios.db (la unica
excepcion es la tabla de sincronizaciones, que registra el historial de cada
corrida del pipeline). Nunca toca el repositorio documental original.
"""

import sqlite3
from pathlib import Path

REGISTROS_POR_PAGINA = 25

COLUMNAS_ORDENABLES = {
    "codigo": "codigo_original",
    "anio": "anio",
    "institucion": "institucion",
    "tipo": "tipo_instrumento",
    "fecha_suscripcion": "fecha_suscripcion",
    "fecha_finalizacion": "fecha_finalizacion",
    "estado_vigencia": "estado_vigencia",
    "dias_para_vencimiento": "dias_para_vencimiento",
    "administrador": "administrador",
}


def conectar(ruta_db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(ruta_db))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON;")
    return conn


def _tiene_columna(conn, tabla, columna) -> bool:
    return any(f["name"] == columna for f in conn.execute(f"PRAGMA table_info({tabla})"))


def obtener_contadores_dashboard(conn) -> dict:
    total = conn.execute(
        "SELECT COUNT(*) FROM convenios WHERE clasificacion_general='CONVENIO'"
    ).fetchone()[0]

    def contar(where_sql, params=()):
        return conn.execute(
            f"SELECT COUNT(*) FROM convenios WHERE clasificacion_general='CONVENIO' AND {where_sql}", params
        ).fetchone()[0]

    return {
        "total": total,
        "vigentes": contar("estado_vigencia='VIGENTE'"),
        "proximos_a_vencer": contar("estado_vigencia='PROXIMO_A_VENCER'"),
        "vencidos": contar("estado_vigencia='VENCIDO'"),
        "sin_informacion": contar("(estado_vigencia IS NULL OR estado_vigencia='SIN_INFORMACION')"),
        "requieren_revision": contar("requiere_revision_documental='SI'"),
        "posible_adenda": contar("tiene_adenda IN ('SI','POR_REVISAR')"),
    }


def obtener_filtros_disponibles(conn) -> dict:
    def valores(col, tabla="convenios", extra_where=""):
        sql = f"SELECT DISTINCT {col} FROM {tabla} WHERE {col} IS NOT NULL AND TRIM({col})<>'' {extra_where} ORDER BY {col}"
        return [r[0] for r in conn.execute(sql)]

    return {
        "anios": [r[0] for r in conn.execute(
            "SELECT DISTINCT anio FROM convenios WHERE clasificacion_general='CONVENIO' ORDER BY anio DESC"
        )],
        "tipos": valores("tipo_instrumento", extra_where="AND clasificacion_general='CONVENIO'"),
        "estados_vigencia": ["VIGENTE", "PROXIMO_A_VENCER", "VENCIDO", "SIN_INFORMACION"],
        "administradores": valores("administrador", extra_where="AND clasificacion_general='CONVENIO'"),
        "tipos_documento_tecnico": valores("tipo_documento_tecnico", tabla="documentos"),
    }


def _normalizar_busqueda(texto: str) -> str:
    """Normaliza para busqueda tolerante a mayusculas/tildes (comparando contra
    columnas ya pasadas por lower() + reemplazo de tildes en SQL)."""
    equivalencias = str.maketrans("áéíóúÁÉÍÓÚñÑ", "aeiouAEIOUnN")
    return texto.translate(equivalencias).lower()


_EXPR_SIN_TILDES = (
    "REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LOWER({col}),"
    "'á','a'),'é','e'),'í','i'),'ó','o'),'ú','u'),'ñ','n')"
)


def buscar_y_listar_convenios(conn, filtros: dict, busqueda: str, orden: str, direccion: str, pagina: int):
    condiciones = ["clasificacion_general='CONVENIO'"]
    params = []

    if filtros.get("anio"):
        condiciones.append("anio = ?")
        params.append(filtros["anio"])
    if filtros.get("tipo"):
        condiciones.append("tipo_instrumento = ?")
        params.append(filtros["tipo"])
    if filtros.get("estado_vigencia"):
        if filtros["estado_vigencia"] == "SIN_INFORMACION":
            condiciones.append("(estado_vigencia IS NULL OR estado_vigencia='SIN_INFORMACION')")
        else:
            condiciones.append("estado_vigencia = ?")
            params.append(filtros["estado_vigencia"])
    if filtros.get("administrador"):
        condiciones.append("administrador = ?")
        params.append(filtros["administrador"])
    if filtros.get("tiene_adenda"):
        condiciones.append("tiene_adenda = ?")
        params.append(filtros["tiene_adenda"])
    if filtros.get("requiere_revision"):
        condiciones.append("requiere_revision_documental = ?")
        params.append(filtros["requiere_revision"])
    if filtros.get("institucion"):
        condiciones.append(_EXPR_SIN_TILDES.format(col="institucion") + " LIKE ?")
        params.append(f"%{_normalizar_busqueda(filtros['institucion'])}%")

    if busqueda:
        termino = f"%{_normalizar_busqueda(busqueda)}%"
        campos_busqueda = ["institucion", "codigo_original", "numero_original", "tipo_instrumento",
                           "administrador", "objeto"]
        condiciones.append(
            "(" + " OR ".join(_EXPR_SIN_TILDES.format(col=c) + " LIKE ?" for c in campos_busqueda)
            + " OR CAST(anio AS TEXT) LIKE ?)"
        )
        params.extend([termino] * len(campos_busqueda))
        params.append(f"%{busqueda}%")

    where_sql = " AND ".join(condiciones)
    total = conn.execute(f"SELECT COUNT(*) FROM convenios WHERE {where_sql}", params).fetchone()[0]

    columna_orden = COLUMNAS_ORDENABLES.get(orden, "anio")
    direccion_sql = "DESC" if direccion == "desc" else "ASC"
    offset = max(0, (pagina - 1)) * REGISTROS_POR_PAGINA

    filas = conn.execute(
        f"""SELECT id_sistema, codigo_original, numero_original, anio, institucion, tipo_instrumento,
                   fecha_suscripcion, fecha_finalizacion, estado_vigencia, dias_para_vencimiento,
                   administrador, ruta_documento_principal, estado_relacion_documental,
                   requiere_revision_documental, tiene_adenda, conflicto_fecha
            FROM convenios
            WHERE {where_sql}
            ORDER BY {columna_orden} {direccion_sql} NULLS LAST
            LIMIT ? OFFSET ?""",
        params + [REGISTROS_POR_PAGINA, offset],
    ).fetchall()

    total_paginas = max(1, (total + REGISTROS_POR_PAGINA - 1) // REGISTROS_POR_PAGINA)
    return filas, total, total_paginas


def obtener_convenio(conn, id_sistema: int):
    return conn.execute("SELECT * FROM convenios WHERE id_sistema = ?", (id_sistema,)).fetchone()


def obtener_documentos_de_convenio(conn, id_sistema: int):
    return conn.execute(
        """SELECT id_documento, nombre, ruta, extension, tamano, fecha_modificacion, carpeta_tipo,
                  clasificacion_tecnica_pdf, firma_electronica_detectada, requiere_revision,
                  es_documento_principal, tipo_documento_tecnico, cantidad_firmas, fecha_firma_metadato
           FROM documentos WHERE id_convenio = ? ORDER BY es_documento_principal DESC, nombre""",
        (id_sistema,),
    ).fetchall()


def obtener_evidencias_de_convenio(conn, id_sistema: int):
    return conn.execute(
        """SELECT campo, valor_extraido, pagina, fragmento_fuente, metodo_extraccion, nivel_confianza,
                  fecha_analisis
           FROM evidencias_documentales WHERE id_convenio = ? ORDER BY campo""",
        (id_sistema,),
    ).fetchall()


def obtener_adenda_documentos(conn, ruta_adenda: str):
    if not ruta_adenda:
        return []
    return conn.execute(
        "SELECT id_documento, nombre, ruta, fecha_modificacion FROM documentos WHERE ruta = ?",
        (ruta_adenda,),
    ).fetchall()


def listar_proximos_a_vencer(conn, limite: int = 200):
    return conn.execute(
        """SELECT id_sistema, codigo_original, anio, institucion, tipo_instrumento, fecha_finalizacion,
                  dias_para_vencimiento, administrador
           FROM convenios
           WHERE clasificacion_general='CONVENIO' AND estado_vigencia='PROXIMO_A_VENCER'
           ORDER BY dias_para_vencimiento ASC LIMIT ?""",
        (limite,),
    ).fetchall()


def listar_vencidos(conn, filtros: dict):
    condiciones = ["clasificacion_general='CONVENIO'", "estado_vigencia='VENCIDO'"]
    params = []
    if filtros.get("anio"):
        condiciones.append("anio = ?")
        params.append(filtros["anio"])
    if filtros.get("tipo"):
        condiciones.append("tipo_instrumento = ?")
        params.append(filtros["tipo"])
    if filtros.get("administrador"):
        condiciones.append("administrador = ?")
        params.append(filtros["administrador"])
    if filtros.get("tiene_adenda"):
        condiciones.append("tiene_adenda = ?")
        params.append(filtros["tiene_adenda"])
    where_sql = " AND ".join(condiciones)
    return conn.execute(
        f"""SELECT id_sistema, codigo_original, anio, institucion, tipo_instrumento, fecha_finalizacion,
                   dias_para_vencimiento, administrador, tiene_adenda
            FROM convenios WHERE {where_sql} ORDER BY fecha_finalizacion ASC""",
        params,
    ).fetchall()


def listar_revision_pendiente(conn):
    return conn.execute(
        """SELECT id_sistema, codigo_original, anio, institucion, tipo_instrumento,
                  estado_relacion_documental, estado_revision_vigencia, conflicto_fecha,
                  tiene_adenda, estado_vigencia
           FROM convenios
           WHERE clasificacion_general='CONVENIO' AND (
                 requiere_revision_documental='SI'
                 OR estado_relacion_documental IN ('PROBABLE','NO_ENCONTRADA','MULTIPLES_COINCIDENCIAS')
                 OR estado_vigencia IS NULL OR estado_vigencia='SIN_INFORMACION'
                 OR conflicto_fecha='SI' OR tiene_adenda='POR_REVISAR'
           )
           ORDER BY anio DESC"""
    ).fetchall()


def obtener_historial_sincronizaciones(conn, limite: int = 50):
    if not _tiene_columna(conn, "sincronizaciones", "fecha_hora"):
        return []
    return conn.execute(
        "SELECT * FROM sincronizaciones ORDER BY id DESC LIMIT ?", (limite,)
    ).fetchall()
