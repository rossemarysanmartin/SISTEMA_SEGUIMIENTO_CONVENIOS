"""Capa de acceso a la base de datos SQLite del sistema.

La base de datos vive exclusivamente dentro de SISTEMA_SEGUIMIENTO_CONVENIOS/BASE_DATOS.
Nunca se abre ni se escribe ninguna base de datos dentro del repositorio original.
"""

import sqlite3
from pathlib import Path

from seguridad import verificar_ruta_escritura_segura

ESQUEMA = """
CREATE TABLE IF NOT EXISTS archivos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    anio INTEGER NOT NULL,
    carpeta_tipo TEXT,
    ruta_relativa TEXT NOT NULL,
    ruta_completa TEXT NOT NULL UNIQUE,
    nombre_archivo TEXT NOT NULL,
    extension TEXT,
    tamano_bytes INTEGER,
    fecha_modificacion TEXT,
    hash_sha256 TEXT,
    es_matriz INTEGER DEFAULT 0,
    tipo_pdf TEXT,
    num_paginas INTEGER,
    firma_electronica_detectada INTEGER DEFAULT 0,
    indicios_firma TEXT,
    requiere_revision INTEGER DEFAULT 0,
    error_detalle TEXT,
    fecha_analisis TEXT
);

CREATE TABLE IF NOT EXISTS matrices_detectadas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    anio INTEGER NOT NULL,
    nombre_archivo TEXT NOT NULL,
    ruta_completa TEXT NOT NULL UNIQUE,
    tamano_bytes INTEGER,
    fecha_modificacion TEXT,
    hojas_json TEXT,
    notas TEXT,
    fecha_analisis TEXT
);

CREATE TABLE IF NOT EXISTS matrices_hojas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    matriz_id INTEGER NOT NULL REFERENCES matrices_detectadas(id),
    nombre_hoja TEXT NOT NULL,
    fila_encabezado_estimada INTEGER,
    encabezados_json TEXT,
    filas_con_datos_aprox INTEGER
);

CREATE TABLE IF NOT EXISTS log_sincronizacion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_hora TEXT NOT NULL,
    usuario TEXT,
    tipo_ejecucion TEXT,
    anios_analizados TEXT,
    carpetas_analizadas INTEGER,
    archivos_encontrados INTEGER,
    archivos_nuevos INTEGER,
    archivos_modificados INTEGER,
    archivos_sin_cambios INTEGER,
    errores INTEGER,
    documentos_requieren_revision INTEGER,
    duracion_segundos REAL,
    detalle TEXT
);

CREATE INDEX IF NOT EXISTS idx_archivos_anio ON archivos(anio);
CREATE INDEX IF NOT EXISTS idx_archivos_tipo ON archivos(carpeta_tipo);
CREATE INDEX IF NOT EXISTS idx_archivos_extension ON archivos(extension);
"""


def conectar(ruta_db: Path) -> sqlite3.Connection:
    verificar_ruta_escritura_segura(ruta_db, ruta_db.parents[2])
    ruta_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(ruta_db))
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def inicializar_esquema(conn: sqlite3.Connection) -> None:
    conn.executescript(ESQUEMA)
    conn.commit()


def obtener_archivo_por_ruta(conn: sqlite3.Connection, ruta_completa: str):
    cur = conn.execute(
        "SELECT id, tamano_bytes, fecha_modificacion, hash_sha256 FROM archivos WHERE ruta_completa = ?",
        (ruta_completa,),
    )
    return cur.fetchone()


def upsert_archivo(conn: sqlite3.Connection, datos: dict) -> str:
    """Inserta o actualiza un archivo. Devuelve 'nuevo', 'modificado' o 'sin_cambios'."""
    existente = obtener_archivo_por_ruta(conn, datos["ruta_completa"])
    campos = [
        "anio", "carpeta_tipo", "ruta_relativa", "ruta_completa", "nombre_archivo",
        "extension", "tamano_bytes", "fecha_modificacion", "hash_sha256", "es_matriz",
        "tipo_pdf", "num_paginas", "firma_electronica_detectada", "indicios_firma",
        "requiere_revision", "error_detalle", "fecha_analisis",
    ]
    valores = [datos.get(c) for c in campos]

    if existente is None:
        estado = "nuevo"
        placeholders = ", ".join(["?"] * len(campos))
        conn.execute(
            f"INSERT INTO archivos ({', '.join(campos)}) VALUES ({placeholders})",
            valores,
        )
    else:
        _id, tam_prev, fecha_prev, hash_prev = existente
        sin_cambios = (
            tam_prev == datos.get("tamano_bytes")
            and fecha_prev == datos.get("fecha_modificacion")
            and (hash_prev is None or hash_prev == datos.get("hash_sha256"))
        )
        estado = "sin_cambios" if sin_cambios else "modificado"
        set_clause = ", ".join(f"{c} = ?" for c in campos)
        conn.execute(
            f"UPDATE archivos SET {set_clause} WHERE ruta_completa = ?",
            valores + [datos["ruta_completa"]],
        )
    conn.commit()
    return estado


def insertar_matriz(conn: sqlite3.Connection, datos: dict) -> int:
    """Inserta o actualiza la matriz por ruta_completa, conservando su id.

    Antes se usaba INSERT OR REPLACE, pero al re-ejecutar la sincronizacion
    sobre una matriz ya existente eso fuerza a SQLite a BORRAR la fila previa
    antes de insertar la nueva -- y esa fila tiene hojas hijas en
    matrices_hojas con FOREIGN KEY hacia ella, asi que el borrado fallaba con
    "FOREIGN KEY constraint failed" en cuanto se sincronizaba una segunda vez.
    Actualizar en el lugar (UPDATE) evita el borrado y preserva el id."""
    cur = conn.execute("SELECT id FROM matrices_detectadas WHERE ruta_completa = ?", (datos["ruta_completa"],))
    fila = cur.fetchone()
    if fila is None:
        conn.execute(
            """INSERT INTO matrices_detectadas
               (anio, nombre_archivo, ruta_completa, tamano_bytes, fecha_modificacion, hojas_json, notas, fecha_analisis)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datos["anio"], datos["nombre_archivo"], datos["ruta_completa"],
                datos["tamano_bytes"], datos["fecha_modificacion"], datos["hojas_json"],
                datos.get("notas"), datos["fecha_analisis"],
            ),
        )
        conn.commit()
        matriz_id = conn.execute(
            "SELECT id FROM matrices_detectadas WHERE ruta_completa = ?", (datos["ruta_completa"],)
        ).fetchone()[0]
    else:
        matriz_id = fila[0]
        conn.execute(
            """UPDATE matrices_detectadas SET
                   anio=?, nombre_archivo=?, tamano_bytes=?, fecha_modificacion=?,
                   hojas_json=?, notas=?, fecha_analisis=?
               WHERE id=?""",
            (
                datos["anio"], datos["nombre_archivo"], datos["tamano_bytes"], datos["fecha_modificacion"],
                datos["hojas_json"], datos.get("notas"), datos["fecha_analisis"], matriz_id,
            ),
        )
        # Las hojas se vuelven a insertar completas en cada corrida (procesar_matriz
        # llama insertar_hoja_matriz por cada hoja detectada); se limpian las
        # anteriores para no acumular duplicados de sincronizaciones previas.
        conn.execute("DELETE FROM matrices_hojas WHERE matriz_id = ?", (matriz_id,))
        conn.commit()
    return matriz_id


def insertar_hoja_matriz(conn: sqlite3.Connection, matriz_id: int, datos: dict) -> None:
    conn.execute(
        """INSERT INTO matrices_hojas
           (matriz_id, nombre_hoja, fila_encabezado_estimada, encabezados_json, filas_con_datos_aprox)
           VALUES (?, ?, ?, ?, ?)""",
        (
            matriz_id, datos["nombre_hoja"], datos.get("fila_encabezado_estimada"),
            datos.get("encabezados_json"), datos.get("filas_con_datos_aprox"),
        ),
    )
    conn.commit()


def registrar_log_sincronizacion(conn: sqlite3.Connection, datos: dict) -> None:
    conn.execute(
        """INSERT INTO log_sincronizacion
           (fecha_hora, usuario, tipo_ejecucion, anios_analizados, carpetas_analizadas,
            archivos_encontrados, archivos_nuevos, archivos_modificados, archivos_sin_cambios,
            errores, documentos_requieren_revision, duracion_segundos, detalle)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datos["fecha_hora"], datos["usuario"], datos["tipo_ejecucion"], datos["anios_analizados"],
            datos["carpetas_analizadas"], datos["archivos_encontrados"], datos["archivos_nuevos"],
            datos["archivos_modificados"], datos["archivos_sin_cambios"], datos["errores"],
            datos["documentos_requieren_revision"], datos["duracion_segundos"], datos.get("detalle"),
        ),
    )
    conn.commit()
