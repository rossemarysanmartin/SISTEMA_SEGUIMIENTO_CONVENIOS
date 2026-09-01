"""Migracion controlada de convenios.db para la Fase 6 (Estabilizacion y usabilidad).

Mismo patron aditivo que db_fase3.py / db_fase5.py: respaldo obligatorio,
CREATE TABLE IF NOT EXISTS / ALTER TABLE ADD COLUMN solo si falta, INSERT OR
IGNORE en catalogos. Nada de fases anteriores se borra ni se sobrescribe.
"""

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

ESQUEMA_FASE6 = """
CREATE TABLE IF NOT EXISTS configuracion_app (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL,
    fecha_actualizacion TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS responsables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE,
    cargo TEXT,
    dependencia TEXT,
    orden INTEGER,
    activo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS catalogo_tipos_convenio_solicitado (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE,
    orden INTEGER,
    activo INTEGER NOT NULL DEFAULT 1
);
"""

COLUMNAS_NUEVAS_MEDIOS = {"orden": "INTEGER"}
COLUMNAS_NUEVAS_ACTUACIONES = {"orden": "INTEGER"}
COLUMNAS_NUEVAS_DEPENDENCIAS = {"orden": "INTEGER"}
COLUMNAS_NUEVAS_SOLICITUDES = {"responsable_inicial": "TEXT"}

ACTUACIONES_NUEVAS = ["NOTA_INTERNA"]

TIPOS_CONVENIO_INICIALES = [
    "COOPERACION", "MARCO", "ESPECIFICO", "PRACTICAS_PREPROFESIONALES",
    "PASANTIAS", "INVESTIGACION", "VINCULACION", "OTRO",
]


def _columnas_existentes(conn, tabla) -> set:
    return {f[1] for f in conn.execute(f"PRAGMA table_info({tabla})")}


def respaldar(ruta_db: Path) -> Path:
    ruta_respaldos = ruta_db.parent.parent / "RESPALDOS"
    ruta_respaldos.mkdir(parents=True, exist_ok=True)
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta_respaldo = ruta_respaldos / f"convenios_pre_fase6_{marca}.db"
    shutil.copy2(ruta_db, ruta_respaldo)
    return ruta_respaldo


def _agregar_columnas(conn, tabla, columnas: dict):
    existentes = _columnas_existentes(conn, tabla)
    for columna, tipo in columnas.items():
        if columna not in existentes:
            conn.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}")


def _backfill_orden(conn, tabla):
    filas = conn.execute(f"SELECT id FROM {tabla} WHERE orden IS NULL ORDER BY id").fetchall()
    for i, fila in enumerate(filas):
        conn.execute(f"UPDATE {tabla} SET orden = ? WHERE id = ?", (i, fila["id"]))


def _sembrar_tipos_convenio(conn):
    # Incluye tanto los valores iniciales sugeridos como cualquier valor ya
    # usado en solicitudes reales (para no perder datos existentes al pasar
    # de texto libre a catalogo).
    valores = list(TIPOS_CONVENIO_INICIALES)
    try:
        for fila in conn.execute(
            "SELECT DISTINCT tipo_convenio_solicitado FROM solicitudes "
            "WHERE tipo_convenio_solicitado IS NOT NULL AND TRIM(tipo_convenio_solicitado) <> ''"
        ):
            if fila[0] not in valores:
                valores.append(fila[0])
    except sqlite3.OperationalError:
        pass  # tabla solicitudes aun no existe (instalacion nueva sin Fase 5 corrida antes)

    for i, nombre in enumerate(valores):
        conn.execute(
            "INSERT OR IGNORE INTO catalogo_tipos_convenio_solicitado (nombre, orden) VALUES (?, ?)",
            (nombre, i),
        )


def migrar(conn: sqlite3.Connection) -> None:
    conn.executescript(ESQUEMA_FASE6)
    conn.commit()

    _agregar_columnas(conn, "catalogo_medios_ingreso", COLUMNAS_NUEVAS_MEDIOS)
    _agregar_columnas(conn, "catalogo_actuaciones", COLUMNAS_NUEVAS_ACTUACIONES)
    _agregar_columnas(conn, "catalogo_dependencias", COLUMNAS_NUEVAS_DEPENDENCIAS)
    _agregar_columnas(conn, "solicitudes", COLUMNAS_NUEVAS_SOLICITUDES)
    conn.commit()

    conn.row_factory = sqlite3.Row
    _backfill_orden(conn, "catalogo_medios_ingreso")
    _backfill_orden(conn, "catalogo_actuaciones")
    _backfill_orden(conn, "catalogo_dependencias")
    conn.commit()

    for codigo in ACTUACIONES_NUEVAS:
        etiqueta = codigo.replace("_", " ").title()
        conn.execute("INSERT OR IGNORE INTO catalogo_actuaciones (codigo, etiqueta) VALUES (?, ?)", (codigo, etiqueta))

    _sembrar_tipos_convenio(conn)
    conn.commit()
