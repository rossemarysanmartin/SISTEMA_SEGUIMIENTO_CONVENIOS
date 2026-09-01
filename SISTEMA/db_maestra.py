"""Base de datos maestra de convenios (BASE_DATOS/convenios.db).

Distinta de convenios_sistema.db (que es el inventario crudo de archivos de
la Fase 0/1). Esta base contiene los REGISTROS de convenio normalizados a
partir de las matrices, con su relacion a documentos.

Todavia NO incluye tablas de solicitudes/trazabilidad (fase futura).
"""

import sqlite3
from pathlib import Path

from seguridad import verificar_ruta_escritura_segura

ESQUEMA = """
CREATE TABLE IF NOT EXISTS convenios (
    id_sistema INTEGER PRIMARY KEY AUTOINCREMENT,
    anio INTEGER NOT NULL,
    codigo_original TEXT,
    numero_original TEXT,
    institucion TEXT,
    tipo_instrumento TEXT,
    subtipo TEXT,
    clasificacion_general TEXT,
    objeto TEXT,
    fecha_suscripcion TEXT,
    fecha_inicio TEXT,
    plazo TEXT,
    fecha_finalizacion TEXT,
    metodo_calculo_vigencia TEXT,
    administrador TEXT,
    unidad_responsable TEXT,
    observaciones_originales TEXT,
    hoja_origen TEXT,
    archivo_matriz_origen TEXT,
    fila_origen INTEGER,
    ruta_expediente TEXT,
    ruta_documento_principal TEXT,
    estado_relacion_documental TEXT,
    confianza_relacion INTEGER,
    estado_vigencia TEXT,
    requiere_revision INTEGER DEFAULT 0,
    notas_sistema TEXT,
    ruc TEXT,
    ambito TEXT,
    seccion TEXT,
    sector TEXT,
    direccion TEXT,
    representante_legal TEXT,
    contacto TEXT,
    email TEXT,
    telefono TEXT,
    carreras_beneficiadas TEXT,
    estado_original TEXT,
    link_documento_matriz TEXT,
    fecha_creacion_sistema TEXT,
    fecha_actualizacion_sistema TEXT
);

CREATE TABLE IF NOT EXISTS documentos (
    id_documento INTEGER PRIMARY KEY AUTOINCREMENT,
    id_convenio INTEGER REFERENCES convenios(id_sistema),
    nombre TEXT NOT NULL,
    ruta TEXT NOT NULL UNIQUE,
    extension TEXT,
    tamano INTEGER,
    fecha_modificacion TEXT,
    anio INTEGER,
    carpeta_tipo TEXT,
    clasificacion_tecnica_pdf TEXT,
    firma_electronica_detectada TEXT,
    requiere_revision INTEGER DEFAULT 0,
    es_documento_principal INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS catalogo_tipos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo_original TEXT NOT NULL UNIQUE,
    tipo_normalizado TEXT NOT NULL,
    clasificacion_general TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sincronizaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_hora TEXT NOT NULL,
    usuario TEXT,
    fase TEXT,
    matrices_procesadas INTEGER,
    registros_importados INTEGER,
    documentos_relacionados INTEGER,
    duracion_segundos REAL,
    detalle TEXT
);

CREATE TABLE IF NOT EXISTS errores_archivos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    anio INTEGER,
    ruta TEXT,
    nombre TEXT,
    error TEXT,
    fecha_deteccion TEXT
);

CREATE INDEX IF NOT EXISTS idx_convenios_anio ON convenios(anio);
CREATE INDEX IF NOT EXISTS idx_convenios_tipo ON convenios(tipo_instrumento);
CREATE INDEX IF NOT EXISTS idx_documentos_convenio ON documentos(id_convenio);
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


def limpiar_datos_previos(conn: sqlite3.Connection) -> None:
    """Esta fase reconstruye la base maestra desde cero en cada corrida
    (las matrices son la fuente de verdad); no se acumulan duplicados."""
    conn.executescript(
        "DELETE FROM documentos; DELETE FROM convenios; DELETE FROM catalogo_tipos; DELETE FROM errores_archivos;"
    )
    conn.commit()


def insertar_convenio(conn: sqlite3.Connection, datos: dict) -> int:
    campos = [
        "anio", "codigo_original", "numero_original", "institucion", "tipo_instrumento", "subtipo",
        "clasificacion_general", "objeto", "fecha_suscripcion", "fecha_inicio", "plazo", "fecha_finalizacion",
        "metodo_calculo_vigencia", "administrador", "unidad_responsable", "observaciones_originales",
        "hoja_origen", "archivo_matriz_origen", "fila_origen", "ruta_expediente", "ruta_documento_principal",
        "estado_relacion_documental", "confianza_relacion", "estado_vigencia", "requiere_revision", "notas_sistema",
        "ruc", "ambito", "seccion", "sector", "direccion", "representante_legal", "contacto", "email", "telefono",
        "carreras_beneficiadas", "estado_original", "link_documento_matriz",
        "fecha_creacion_sistema", "fecha_actualizacion_sistema",
    ]
    valores = [datos.get(c) for c in campos]
    placeholders = ", ".join(["?"] * len(campos))
    cur = conn.execute(f"INSERT INTO convenios ({', '.join(campos)}) VALUES ({placeholders})", valores)
    conn.commit()
    return cur.lastrowid


def insertar_documento(conn: sqlite3.Connection, datos: dict) -> None:
    campos = [
        "id_convenio", "nombre", "ruta", "extension", "tamano", "fecha_modificacion", "anio", "carpeta_tipo",
        "clasificacion_tecnica_pdf", "firma_electronica_detectada", "requiere_revision", "es_documento_principal",
    ]
    valores = [datos.get(c) for c in campos]
    placeholders = ", ".join(["?"] * len(campos))
    conn.execute(
        f"INSERT OR REPLACE INTO documentos ({', '.join(campos)}) VALUES ({placeholders})",
        valores,
    )
    conn.commit()


def upsert_catalogo_tipo(conn: sqlite3.Connection, tipo_original: str, tipo_normalizado: str, clasificacion_general: str) -> None:
    if not tipo_original:
        return
    conn.execute(
        """INSERT INTO catalogo_tipos (tipo_original, tipo_normalizado, clasificacion_general)
           VALUES (?, ?, ?)
           ON CONFLICT(tipo_original) DO UPDATE SET tipo_normalizado=excluded.tipo_normalizado,
                                                     clasificacion_general=excluded.clasificacion_general""",
        (tipo_original, tipo_normalizado, clasificacion_general),
    )
    conn.commit()


def insertar_error_archivo(conn: sqlite3.Connection, datos: dict) -> None:
    conn.execute(
        "INSERT INTO errores_archivos (anio, ruta, nombre, error, fecha_deteccion) VALUES (?, ?, ?, ?, ?)",
        (datos.get("anio"), datos.get("ruta"), datos.get("nombre"), datos.get("error"), datos.get("fecha_deteccion")),
    )
    conn.commit()


def registrar_sincronizacion(conn: sqlite3.Connection, datos: dict) -> None:
    conn.execute(
        """INSERT INTO sincronizaciones
           (fecha_hora, usuario, fase, matrices_procesadas, registros_importados, documentos_relacionados,
            duracion_segundos, detalle)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datos["fecha_hora"], datos.get("usuario"), datos.get("fase"), datos.get("matrices_procesadas"),
            datos.get("registros_importados"), datos.get("documentos_relacionados"),
            datos.get("duracion_segundos"), datos.get("detalle"),
        ),
    )
    conn.commit()
