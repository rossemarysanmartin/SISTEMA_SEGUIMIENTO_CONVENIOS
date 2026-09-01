"""Migracion controlada de convenios.db para la Fase 3 (analisis documental).

- Hace un respaldo del .db antes de tocar el esquema.
- Agrega columnas nuevas SOLO si no existen (no destruye nada de Fase 2).
- Crea la tabla evidencias_documentales.
"""

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

COLUMNAS_NUEVAS_CONVENIOS = {
    "objeto_documento_original": "TEXT",
    "objeto_documento_resumen": "TEXT",
    "fecha_suscripcion_documento": "TEXT",
    "fecha_inicio_documento": "TEXT",
    "plazo_documento": "TEXT",
    "unidad_plazo_documento": "TEXT",
    "fecha_finalizacion_documento": "TEXT",
    "metodo_calculo_vigencia_documento": "TEXT",
    "texto_fuente_vigencia": "TEXT",
    "pagina_fuente_vigencia": "INTEGER",
    "clausula_terminacion": "TEXT",
    "renovacion_clausula": "TEXT",
    "administrador_documento": "TEXT",
    "administrador_documento_pagina": "INTEGER",
    "firmantes_json": "TEXT",
    "institucion_original_documento": "TEXT",
    "institucion_normalizada": "TEXT",
    "tiene_adenda": "TEXT",
    "documento_adenda_ruta": "TEXT",
    "conflicto_fecha": "TEXT",
    "conflicto_institucion": "TEXT",
    "requiere_revision_documental": "TEXT",
    "estado_revision_vigencia": "TEXT",
    "confianza_analisis": "TEXT",
    "dias_para_vencimiento": "INTEGER",
    "hash_documento_principal": "TEXT",
    "fecha_ultimo_analisis_documento": "TEXT",
}

COLUMNAS_NUEVAS_DOCUMENTOS = {
    "cantidad_firmas": "INTEGER",
    "firmante_certificado": "TEXT",
    "fecha_firma_metadato": "TEXT",
    "emisor_certificado": "TEXT",
    "razon_firma": "TEXT",
    "tipo_documento_tecnico": "TEXT",
    "hash_ultimo_analisis": "TEXT",
    "fecha_ultimo_analisis": "TEXT",
}

ESQUEMA_EVIDENCIAS = """
CREATE TABLE IF NOT EXISTS evidencias_documentales (
    id_evidencia INTEGER PRIMARY KEY AUTOINCREMENT,
    id_convenio INTEGER,
    id_documento INTEGER,
    campo TEXT NOT NULL,
    valor_extraido TEXT,
    pagina INTEGER,
    fragmento_fuente TEXT,
    metodo_extraccion TEXT NOT NULL,
    nivel_confianza TEXT NOT NULL,
    fecha_analisis TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidencias_convenio ON evidencias_documentales(id_convenio);
"""


def _columnas_existentes(conn: sqlite3.Connection, tabla: str) -> set:
    return {fila[1] for fila in conn.execute(f"PRAGMA table_info({tabla})")}


def respaldar(ruta_db: Path) -> Path:
    ruta_respaldos = ruta_db.parent.parent / "RESPALDOS"
    ruta_respaldos.mkdir(parents=True, exist_ok=True)
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta_respaldo = ruta_respaldos / f"convenios_pre_fase3_{marca}.db"
    shutil.copy2(ruta_db, ruta_respaldo)
    return ruta_respaldo


def migrar(conn: sqlite3.Connection) -> None:
    existentes_convenios = _columnas_existentes(conn, "convenios")
    for columna, tipo in COLUMNAS_NUEVAS_CONVENIOS.items():
        if columna not in existentes_convenios:
            conn.execute(f"ALTER TABLE convenios ADD COLUMN {columna} {tipo}")

    existentes_documentos = _columnas_existentes(conn, "documentos")
    for columna, tipo in COLUMNAS_NUEVAS_DOCUMENTOS.items():
        if columna not in existentes_documentos:
            conn.execute(f"ALTER TABLE documentos ADD COLUMN {columna} {tipo}")

    conn.executescript(ESQUEMA_EVIDENCIAS)
    conn.commit()


def insertar_evidencia(conn: sqlite3.Connection, datos: dict) -> None:
    conn.execute(
        """INSERT INTO evidencias_documentales
           (id_convenio, id_documento, campo, valor_extraido, pagina, fragmento_fuente,
            metodo_extraccion, nivel_confianza, fecha_analisis)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datos.get("id_convenio"), datos.get("id_documento"), datos["campo"],
            datos.get("valor_extraido"), datos.get("pagina"), datos.get("fragmento_fuente"),
            datos["metodo_extraccion"], datos["nivel_confianza"], datos["fecha_analisis"],
        ),
    )
