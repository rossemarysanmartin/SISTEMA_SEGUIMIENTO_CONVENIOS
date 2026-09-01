"""Migracion controlada de convenios.db para la Fase 5 (Solicitudes y Trazabilidad).

Mismo patron que db_fase3.py: respaldo obligatorio antes de tocar el esquema,
todo aditivo (CREATE TABLE IF NOT EXISTS / ALTER TABLE ADD COLUMN solo si no
existe), nunca se borra ni se sobrescribe nada de fases anteriores.
"""

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

ESQUEMA_SOLICITUDES = """
CREATE TABLE IF NOT EXISTS contadores_solicitud (
    anio INTEGER PRIMARY KEY,
    ultimo_numero INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS catalogo_medios_ingreso (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    etiqueta TEXT NOT NULL,
    icono TEXT,
    activo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS catalogo_dependencias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE,
    tipo TEXT,
    activo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS catalogo_actuaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    etiqueta TEXT NOT NULL,
    icono TEXT,
    requiere_respuesta_por_defecto INTEGER NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS catalogo_estados_solicitud (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    etiqueta TEXT NOT NULL,
    orden INTEGER,
    activo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS catalogo_etapas_solicitud (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    etiqueta TEXT NOT NULL,
    orden INTEGER,
    activo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS solicitudes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo_solicitud TEXT NOT NULL UNIQUE,
    anio INTEGER NOT NULL,
    fecha_ingreso TEXT NOT NULL,
    hora_ingreso TEXT,
    institucion TEXT NOT NULL,
    persona_contacto TEXT,
    correo_contacto TEXT,
    asunto TEXT,
    tipo_convenio_solicitado TEXT,
    dependencia_solicitante TEXT,
    medio_ingreso TEXT NOT NULL,
    responsable_actual TEXT,
    delegado_actual TEXT,
    etapa_actual TEXT,
    estado_actual TEXT NOT NULL,
    prioridad TEXT,
    fecha_ultima_actuacion TEXT,
    dias_sin_movimiento INTEGER,
    observaciones TEXT,
    activo INTEGER NOT NULL DEFAULT 1,
    fecha_creacion TEXT NOT NULL,
    fecha_actualizacion TEXT NOT NULL,
    id_convenio_suscrito INTEGER REFERENCES convenios(id_sistema),
    ruta_expediente_tramite TEXT,
    referencia_correo TEXT,
    fecha_correo TEXT,
    remitente_correo TEXT,
    numero_tramite_institucional TEXT
);

CREATE TABLE IF NOT EXISTS actuaciones_solicitud (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    id_solicitud INTEGER NOT NULL REFERENCES solicitudes(id),
    fecha TEXT NOT NULL,
    hora TEXT,
    tipo_actuacion TEXT NOT NULL,
    dependencia_origen TEXT,
    dependencia_destino TEXT,
    responsable TEXT,
    delegado TEXT,
    descripcion TEXT,
    resultado TEXT,
    estado_anterior TEXT,
    estado_nuevo TEXT,
    etapa_anterior TEXT,
    etapa_nueva TEXT,
    requiere_respuesta TEXT NOT NULL DEFAULT 'NO',
    fecha_limite_respuesta TEXT,
    respuesta_recibida TEXT NOT NULL DEFAULT 'NO',
    fecha_respuesta TEXT,
    id_actuacion_relacionada INTEGER REFERENCES actuaciones_solicitud(id),
    observaciones TEXT,
    documento_asociado TEXT,
    anulada INTEGER NOT NULL DEFAULT 0,
    fecha_registro TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documentos_tramite (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    id_solicitud INTEGER NOT NULL REFERENCES solicitudes(id),
    id_actuacion INTEGER REFERENCES actuaciones_solicitud(id),
    nombre TEXT NOT NULL,
    ruta TEXT,
    ruta_relativa TEXT,
    tipo TEXT,
    fecha TEXT,
    fecha_registro TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auditoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    hora TEXT NOT NULL,
    accion TEXT NOT NULL,
    entidad TEXT NOT NULL,
    id_entidad INTEGER,
    valor_anterior TEXT,
    valor_nuevo TEXT,
    usuario TEXT NOT NULL,
    descripcion TEXT
);

CREATE INDEX IF NOT EXISTS idx_solicitudes_anio ON solicitudes(anio);
CREATE INDEX IF NOT EXISTS idx_solicitudes_estado ON solicitudes(estado_actual);
CREATE INDEX IF NOT EXISTS idx_solicitudes_etapa ON solicitudes(etapa_actual);
CREATE INDEX IF NOT EXISTS idx_solicitudes_activo ON solicitudes(activo);
CREATE INDEX IF NOT EXISTS idx_actuaciones_solicitud ON actuaciones_solicitud(id_solicitud);
CREATE INDEX IF NOT EXISTS idx_actuaciones_pendientes ON actuaciones_solicitud(requiere_respuesta, respuesta_recibida);
CREATE INDEX IF NOT EXISTS idx_documentos_tramite_solicitud ON documentos_tramite(id_solicitud);
CREATE INDEX IF NOT EXISTS idx_auditoria_entidad ON auditoria(entidad, id_entidad);
"""

# (codigo, etiqueta, icono)
MEDIOS_INGRESO = [
    ("CORREO_ELECTRONICO", "Correo electrónico", "📧"),
    ("SISTEMA_INSTITUCIONAL", "Sistema institucional", "📝"),
    ("OFICIO", "Oficio", "📄"),
    ("SOLICITUD_INTERNA", "Solicitud interna", "🏢"),
    ("REUNION", "Reunión", "🤝"),
    ("OTRO", "Otro", "❔"),
]

ACTUACIONES = [
    "RECEPCION", "TRASLADO", "RECEPCION_EN_UNIDAD", "REVISION_INICIAL", "DELEGACION",
    "SOLICITUD_DE_DOCUMENTACION", "DOCUMENTACION_RECIBIDA", "SOLICITUD_DE_CRITERIO",
    "CRITERIO_RECIBIDO", "SOLICITUD_DE_INFORME_JURIDICO", "INFORME_JURIDICO_RECIBIDO",
    "SOLICITUD_DE_FACTIBILIDAD", "FACTIBILIDAD_RECIBIDA", "ELABORACION_DE_BORRADOR",
    "REVISION_DE_BORRADOR", "ENVIO_A_CONTRAPARTE", "OBSERVACIONES_DE_CONTRAPARTE",
    "SUBSANACION", "VALIDACION", "ENVIO_PARA_FIRMA", "FIRMA_CONTRAPARTE", "FIRMA_UTMACH",
    "SUSCRIPCION", "ARCHIVO", "NO_PROCEDENTE", "SUSPENDIDO", "CORRECCION", "OTRO",
]

ESTADOS = [
    "RECIBIDA", "EN_REVISION", "EN_GESTION", "PENDIENTE_DE_DOCUMENTACION",
    "PENDIENTE_DE_RESPUESTA", "PENDIENTE_DE_CRITERIO", "EN_ELABORACION",
    "EN_REVISION_JURIDICA", "EN_FACTIBILIDAD", "EN_CONTRAPARTE", "EN_FIRMA",
    "SUSCRITO", "OBSERVADO", "SUSPENDIDO", "NO_PROCEDENTE", "ARCHIVADO",
]

ETAPAS = [
    "RECEPCION", "CRITERIOS", "REVISION_JURIDICA", "FACTIBILIDAD", "ELABORACION",
    "CONTRAPARTE", "FIRMA", "SUSCRITO",
]

DEPENDENCIAS_INICIALES = [
    ("Dirección de Vinculación", "DIRECCION"),
    ("Unidad de Relaciones Interinstitucionales / Cooperación Interinstitucional", "UNIDAD"),
    ("Procuraduría / Asesoría Jurídica", "JURIDICO"),
    ("Vicerrectorado Académico", "VICERRECTORADO"),
    ("Vicerrectorado Administrativo", "VICERRECTORADO"),
    ("Rectorado", "AUTORIDAD"),
    ("Unidad Académica / Facultad", "ACADEMICA"),
    ("Otra", "OTRA"),
]

COLUMNAS_NUEVAS_CONVENIOS = {
    "id_solicitud_origen": "INTEGER",
}

COLUMNAS_NUEVAS_DOCUMENTOS_TRAMITE = {
    "ruta_relativa": "TEXT",
}


def _columnas_existentes(conn, tabla) -> set:
    return {f[1] for f in conn.execute(f"PRAGMA table_info({tabla})")}


def respaldar(ruta_db: Path) -> Path:
    ruta_respaldos = ruta_db.parent.parent / "RESPALDOS"
    ruta_respaldos.mkdir(parents=True, exist_ok=True)
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta_respaldo = ruta_respaldos / f"convenios_pre_fase5_{marca}.db"
    shutil.copy2(ruta_db, ruta_respaldo)
    return ruta_respaldo


def _sembrar_catalogo_simple(conn, tabla, campo, filas):
    for valor in filas:
        conn.execute(f"INSERT OR IGNORE INTO {tabla} ({campo}) VALUES (?)", (valor,))


def _sembrar_catalogos(conn: sqlite3.Connection) -> None:
    for codigo, etiqueta, icono in MEDIOS_INGRESO:
        conn.execute(
            "INSERT OR IGNORE INTO catalogo_medios_ingreso (codigo, etiqueta, icono) VALUES (?, ?, ?)",
            (codigo, etiqueta, icono),
        )
    for i, codigo in enumerate(ACTUACIONES):
        etiqueta = codigo.replace("_", " ").title()
        conn.execute(
            "INSERT OR IGNORE INTO catalogo_actuaciones (codigo, etiqueta) VALUES (?, ?)",
            (codigo, etiqueta),
        )
    for i, codigo in enumerate(ESTADOS):
        etiqueta = codigo.replace("_", " ").title()
        conn.execute(
            "INSERT OR IGNORE INTO catalogo_estados_solicitud (codigo, etiqueta, orden) VALUES (?, ?, ?)",
            (codigo, etiqueta, i),
        )
    for i, codigo in enumerate(ETAPAS):
        etiqueta = codigo.replace("_", " ").title()
        conn.execute(
            "INSERT OR IGNORE INTO catalogo_etapas_solicitud (codigo, etiqueta, orden) VALUES (?, ?, ?)",
            (codigo, etiqueta, i),
        )
    for nombre, tipo in DEPENDENCIAS_INICIALES:
        conn.execute(
            "INSERT OR IGNORE INTO catalogo_dependencias (nombre, tipo) VALUES (?, ?)",
            (nombre, tipo),
        )
    conn.commit()


def migrar(conn: sqlite3.Connection) -> None:
    conn.executescript(ESQUEMA_SOLICITUDES)
    conn.commit()

    existentes = _columnas_existentes(conn, "convenios")
    for columna, tipo in COLUMNAS_NUEVAS_CONVENIOS.items():
        if columna not in existentes:
            conn.execute(f"ALTER TABLE convenios ADD COLUMN {columna} {tipo}")

    existentes_doc_tramite = _columnas_existentes(conn, "documentos_tramite")
    for columna, tipo in COLUMNAS_NUEVAS_DOCUMENTOS_TRAMITE.items():
        if columna not in existentes_doc_tramite:
            conn.execute(f"ALTER TABLE documentos_tramite ADD COLUMN {columna} {tipo}")
    conn.commit()

    _sembrar_catalogos(conn)
