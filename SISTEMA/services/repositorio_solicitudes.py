"""Capa de acceso a datos del modulo de Solicitudes y Trazabilidad (Fase 5).

Todas las consultas y escrituras relacionadas con `solicitudes`,
`actuaciones_solicitud`, `documentos_tramite` y `auditoria` viven aqui -- las
rutas Flask NUNCA deben construir SQL directamente, solo llamar a estas
funciones. Esto es intencional: cuando en el futuro se migre de SQLite a un
motor central (PostgreSQL/SQL Server), solo este modulo (y sus pares
`db_visualizador.py` / `db_maestra.py`) deberian necesitar cambios.

Todas las funciones reciben la conexion como parametro (inyeccion de
dependencia) para poder probarse contra una base SQLite temporal sin tocar
la base real, y para no acoplar la logica de negocio a una unica conexion
global.
"""

import sqlite3
from datetime import date, datetime
from pathlib import Path

from seguridad import verificar_ruta_escritura_segura
from services import auditoria
from services.current_actor import obtener_actor_actual
from services.fechas_habiles import contar_dias_habiles

MAX_INTENTOS_CODIGO = 5


def conectar_escritura(ruta_db: Path, ruta_base_convenios: Path) -> sqlite3.Connection:
    """Conexion de LECTURA/ESCRITURA para el modulo de solicitudes.

    isolation_level=None (autocommit) para poder controlar explicitamente
    BEGIN IMMEDIATE en la generacion de codigos correlativos (necesario para
    que la numeracion sea segura ante una futura concurrencia real)."""
    verificar_ruta_escritura_segura(ruta_db, ruta_base_convenios)
    conn = sqlite3.connect(str(ruta_db), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


# ------------------------------------------------------------- catalogos --

def listar_catalogo(conn, tabla: str):
    return conn.execute(f"SELECT * FROM {tabla} WHERE activo = 1 ORDER BY id").fetchall()


# --------------------------------------------------------- codigo correlativo --

def generar_codigo_solicitud(conn: sqlite3.Connection, anio: int) -> str:
    """Genera SOL-AAAA-NNNN de forma transaccional (BEGIN IMMEDIATE bloquea
    la base contra otra escritura concurrente mientras se lee y actualiza el
    contador), preparando el terreno para una futura version multiusuario."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        fila = conn.execute(
            "SELECT ultimo_numero FROM contadores_solicitud WHERE anio = ?", (anio,)
        ).fetchone()
        siguiente = (fila["ultimo_numero"] if fila else 0) + 1
        if fila is None:
            conn.execute("INSERT INTO contadores_solicitud (anio, ultimo_numero) VALUES (?, ?)", (anio, siguiente))
        else:
            conn.execute("UPDATE contadores_solicitud SET ultimo_numero = ? WHERE anio = ?", (siguiente, anio))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return f"SOL-{anio}-{siguiente:04d}"


# ------------------------------------------------------------ solicitudes --

def crear_solicitud(conn: sqlite3.Connection, datos: dict, recibido_en_vinculacion: bool = False) -> sqlite3.Row:
    fecha_ingreso = datos["fecha_ingreso"]
    anio = int(str(fecha_ingreso)[:4])
    ahora = datetime.now().isoformat()

    ultimo_error = None
    for _ in range(MAX_INTENTOS_CODIGO):
        codigo = generar_codigo_solicitud(conn, anio)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """INSERT INTO solicitudes
                   (codigo_solicitud, anio, fecha_ingreso, hora_ingreso, institucion, persona_contacto,
                    correo_contacto, asunto, tipo_convenio_solicitado, dependencia_solicitante, medio_ingreso,
                    responsable_actual, responsable_inicial, delegado_actual, etapa_actual, estado_actual, prioridad,
                    fecha_ultima_actuacion, dias_sin_movimiento, observaciones, activo,
                    fecha_creacion, fecha_actualizacion, ruta_expediente_tramite, referencia_correo,
                    fecha_correo, remitente_correo, numero_tramite_institucional)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?,?,?)""",
                (
                    codigo, anio, fecha_ingreso, datos.get("hora_ingreso"), datos["institucion"],
                    datos.get("persona_contacto"), datos.get("correo_contacto"), datos.get("asunto"),
                    datos.get("tipo_convenio_solicitado"), datos.get("dependencia_solicitante"),
                    datos["medio_ingreso"], datos.get("responsable_actual"), datos.get("responsable_inicial"),
                    datos.get("delegado_actual"),
                    "RECEPCION", "RECIBIDA", datos.get("prioridad"),
                    fecha_ingreso, 0, datos.get("observaciones"),
                    ahora, ahora, datos.get("ruta_expediente_tramite"), datos.get("referencia_correo"),
                    datos.get("fecha_correo"), datos.get("remitente_correo"), datos.get("numero_tramite_institucional"),
                ),
            )
            id_solicitud = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            auditoria.registrar(conn, "CREAR", "solicitud", id_solicitud, None, codigo, "Solicitud creada")
            conn.execute("COMMIT")
            break
        except sqlite3.IntegrityError as exc:
            conn.execute("ROLLBACK")
            ultimo_error = exc
            continue
    else:
        raise RuntimeError(f"No se pudo generar un codigo de solicitud unico tras {MAX_INTENTOS_CODIGO} intentos") from ultimo_error

    if recibido_en_vinculacion:
        registrar_actuacion(conn, id_solicitud, {
            "tipo_actuacion": "RECEPCION",
            "fecha": fecha_ingreso,
            "hora": datos.get("hora_ingreso"),
            "dependencia_destino": "Dirección de Vinculación",
            "responsable": datos.get("registrado_por"),
            "descripcion": "Recepción registrada en Dirección de Vinculación al momento del ingreso.",
            "requiere_respuesta": "NO",
        })

    return obtener_solicitud(conn, id_solicitud)


def obtener_solicitud(conn, id_solicitud: int):
    return conn.execute("SELECT * FROM solicitudes WHERE id = ?", (id_solicitud,)).fetchone()


def dias_desde(fecha_texto) -> int:
    if not fecha_texto:
        return 0
    try:
        fecha = date.fromisoformat(str(fecha_texto)[:10])
    except ValueError:
        return 0
    return max(0, (date.today() - fecha).days)


def calcular_semaforo(dias: int, config):
    if dias <= config.semaforo_normal_max:
        return {"codigo": "NORMAL", "icono": "🟢", "etiqueta": "NORMAL"}
    if dias <= config.semaforo_atencion_max:
        return {"codigo": "ATENCION", "icono": "🟡", "etiqueta": "ATENCIÓN"}
    if dias <= config.semaforo_demora_max:
        return {"codigo": "DEMORA", "icono": "🟠", "etiqueta": "DEMORA"}
    return {"codigo": "REVISAR", "icono": "🔴", "etiqueta": "REVISAR"}


_CAMPOS_BUSQUEDA = ["institucion", "codigo_solicitud", "asunto", "persona_contacto",
                    "tipo_convenio_solicitado", "responsable_actual", "delegado_actual"]
_EXPR_SIN_TILDES = (
    "REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LOWER({col}),"
    "'á','a'),'é','e'),'í','i'),'ó','o'),'ú','u'),'ñ','n')"
)


def _normalizar(texto: str) -> str:
    equivalencias = str.maketrans("áéíóúÁÉÍÓÚñÑ", "aeiouAEIOUnN")
    return texto.translate(equivalencias).lower()


REGISTROS_POR_PAGINA = 25

COLUMNAS_ORDENABLES = {
    "codigo": "codigo_solicitud", "fecha_ingreso": "fecha_ingreso", "institucion": "institucion",
    "responsable": "responsable_actual", "etapa": "etapa_actual", "estado": "estado_actual",
    "ultima_actuacion": "fecha_ultima_actuacion",
}


def listar_solicitudes(conn, filtros: dict, busqueda: str, orden: str, direccion: str, pagina: int):
    condiciones = ["activo = 1"]
    params = []
    if filtros.get("anio"):
        condiciones.append("anio = ?"); params.append(filtros["anio"])
    if filtros.get("institucion"):
        condiciones.append(_EXPR_SIN_TILDES.format(col="institucion") + " LIKE ?")
        params.append(f"%{_normalizar(filtros['institucion'])}%")
    if filtros.get("medio_ingreso"):
        condiciones.append("medio_ingreso = ?"); params.append(filtros["medio_ingreso"])
    if filtros.get("responsable_actual"):
        condiciones.append("responsable_actual = ?"); params.append(filtros["responsable_actual"])
    if filtros.get("delegado_actual"):
        condiciones.append("delegado_actual = ?"); params.append(filtros["delegado_actual"])
    if filtros.get("estado_actual"):
        condiciones.append("estado_actual = ?"); params.append(filtros["estado_actual"])
    if filtros.get("etapa_actual"):
        condiciones.append("etapa_actual = ?"); params.append(filtros["etapa_actual"])
    if filtros.get("tipo_convenio_solicitado"):
        condiciones.append("tipo_convenio_solicitado = ?"); params.append(filtros["tipo_convenio_solicitado"])
    if filtros.get("dependencia_solicitante"):
        condiciones.append("dependencia_solicitante = ?"); params.append(filtros["dependencia_solicitante"])
    if filtros.get("dias_sin_movimiento_min") is not None:
        condiciones.append("CAST(julianday('now') - julianday(fecha_ultima_actuacion) AS INTEGER) >= ?")
        params.append(filtros["dias_sin_movimiento_min"])

    if busqueda:
        termino = f"%{_normalizar(busqueda)}%"
        condiciones.append(
            "(" + " OR ".join(_EXPR_SIN_TILDES.format(col=c) + " LIKE ?" for c in _CAMPOS_BUSQUEDA)
            + " OR CAST(anio AS TEXT) LIKE ?)"
        )
        params.extend([termino] * len(_CAMPOS_BUSQUEDA))
        params.append(f"%{busqueda}%")

    if filtros.get("con_respuesta_pendiente"):
        condiciones.append(
            "id IN (SELECT id_solicitud FROM actuaciones_solicitud "
            "WHERE requiere_respuesta='SI' AND respuesta_recibida='NO' AND anulada=0)"
        )

    where_sql = " AND ".join(condiciones)
    total = conn.execute(f"SELECT COUNT(*) FROM solicitudes WHERE {where_sql}", params).fetchone()[0]

    columna_orden = COLUMNAS_ORDENABLES.get(orden, "fecha_ingreso")
    direccion_sql = "DESC" if direccion == "desc" else "ASC"
    offset = max(0, pagina - 1) * REGISTROS_POR_PAGINA

    filas = conn.execute(
        f"""SELECT * FROM solicitudes WHERE {where_sql}
            ORDER BY {columna_orden} {direccion_sql} NULLS LAST
            LIMIT ? OFFSET ?""",
        params + [REGISTROS_POR_PAGINA, offset],
    ).fetchall()

    total_paginas = max(1, -(-total // REGISTROS_POR_PAGINA))
    return filas, total, total_paginas


def contadores_dashboard_solicitudes(conn, config):
    def contar(where_sql, params=()):
        return conn.execute(f"SELECT COUNT(*) FROM solicitudes WHERE activo=1 AND {where_sql}", params).fetchone()[0]

    return {
        "total": contar("1=1"),
        "recibidas": contar("estado_actual='RECIBIDA'"),
        "en_gestion": contar("estado_actual='EN_GESTION'"),
        "pendientes_respuesta": contar(
            "estado_actual IN ('PENDIENTE_DE_RESPUESTA','PENDIENTE_DE_CRITERIO','PENDIENTE_DE_DOCUMENTACION')"
        ),
        "en_juridico": contar("estado_actual='EN_REVISION_JURIDICA' OR etapa_actual='REVISION_JURIDICA'"),
        "en_factibilidad": contar("estado_actual='EN_FACTIBILIDAD' OR etapa_actual='FACTIBILIDAD'"),
        "en_firma": contar("estado_actual='EN_FIRMA' OR etapa_actual='FIRMA'"),
        "observadas": contar("estado_actual='OBSERVADO'"),
        "suscritas": contar("estado_actual='SUSCRITO'"),
        "sin_movimiento": contar(
            "CAST(julianday('now') - julianday(fecha_ultima_actuacion) AS INTEGER) > ? "
            "AND estado_actual NOT IN ('SUSCRITO','ARCHIVADO','NO_PROCEDENTE')",
            (config.semaforo_demora_max,),
        ),
    }


# ------------------------------------------------------------- actuaciones --

_CAMPOS_QUE_ACTUALIZAN_RESPONSABLE = {"responsable"}


def registrar_actuacion(conn: sqlite3.Connection, id_solicitud: int, datos: dict) -> int:
    solicitud = obtener_solicitud(conn, id_solicitud)
    if solicitud is None:
        raise ValueError(f"Solicitud {id_solicitud} no existe")

    estado_anterior = solicitud["estado_actual"]
    etapa_anterior = solicitud["etapa_actual"]
    estado_nuevo = datos.get("estado_nuevo") or estado_anterior
    etapa_nueva = datos.get("etapa_nueva") or etapa_anterior
    fecha = datos.get("fecha") or date.today().isoformat()
    ahora = datetime.now().isoformat()

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """INSERT INTO actuaciones_solicitud
               (id_solicitud, fecha, hora, tipo_actuacion, dependencia_origen, dependencia_destino,
                responsable, delegado, descripcion, resultado, estado_anterior, estado_nuevo,
                etapa_anterior, etapa_nueva, requiere_respuesta, fecha_limite_respuesta,
                respuesta_recibida, fecha_respuesta, id_actuacion_relacionada, observaciones,
                documento_asociado, fecha_registro)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                id_solicitud, fecha, datos.get("hora"), datos["tipo_actuacion"],
                datos.get("dependencia_origen"), datos.get("dependencia_destino"),
                datos.get("responsable"), datos.get("delegado"), datos.get("descripcion"),
                datos.get("resultado"), estado_anterior, estado_nuevo, etapa_anterior, etapa_nueva,
                datos.get("requiere_respuesta", "NO"), datos.get("fecha_limite_respuesta"),
                datos.get("respuesta_recibida", "NO"), datos.get("fecha_respuesta"),
                datos.get("id_actuacion_relacionada"), datos.get("observaciones"),
                datos.get("documento_asociado"), ahora,
            ),
        )
        id_actuacion = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        responsable_actual = datos.get("responsable") or solicitud["responsable_actual"]
        delegado_actual = datos.get("delegado") if datos["tipo_actuacion"] == "DELEGACION" else solicitud["delegado_actual"]
        if datos.get("delegado") and datos["tipo_actuacion"] != "DELEGACION":
            delegado_actual = datos.get("delegado")

        conn.execute(
            """UPDATE solicitudes SET
                   etapa_actual=?, estado_actual=?, responsable_actual=?, delegado_actual=?,
                   fecha_ultima_actuacion=?, dias_sin_movimiento=0, fecha_actualizacion=?
               WHERE id=?""",
            (etapa_nueva, estado_nuevo, responsable_actual, delegado_actual, fecha, ahora, id_solicitud),
        )

        if datos.get("id_actuacion_relacionada") and datos.get("respuesta_recibida") == "SI":
            conn.execute(
                "UPDATE actuaciones_solicitud SET respuesta_recibida='SI', fecha_respuesta=? WHERE id=?",
                (fecha, datos["id_actuacion_relacionada"]),
            )
            auditoria.registrar(conn, "RESPUESTA_RECIBIDA", "actuacion_solicitud", datos["id_actuacion_relacionada"],
                                 "NO", "SI", f"Respondida por actuación #{id_actuacion}")

        if estado_nuevo != estado_anterior:
            auditoria.registrar(conn, "CAMBIO_ESTADO", "solicitud", id_solicitud, estado_anterior, estado_nuevo)
        if etapa_nueva != etapa_anterior:
            auditoria.registrar(conn, "CAMBIO_ETAPA", "solicitud", id_solicitud, etapa_anterior, etapa_nueva)
        if responsable_actual != solicitud["responsable_actual"]:
            auditoria.registrar(conn, "CAMBIO_RESPONSABLE", "solicitud", id_solicitud,
                                 solicitud["responsable_actual"], responsable_actual)
        if delegado_actual != solicitud["delegado_actual"]:
            auditoria.registrar(conn, "DELEGACION", "solicitud", id_solicitud,
                                 solicitud["delegado_actual"], delegado_actual)

        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return id_actuacion


def registrar_correccion(conn, id_solicitud: int, id_actuacion_original: int, motivo: str):
    """Nunca se edita en silencio una actuacion historica (seccion 30 de la
    especificacion): se registra una nueva actuacion CORRECCION enlazada a la
    original, y queda en auditoria."""
    id_correccion = registrar_actuacion(conn, id_solicitud, {
        "tipo_actuacion": "CORRECCION",
        "descripcion": f"Corrección sobre actuación #{id_actuacion_original}: {motivo}",
        "id_actuacion_relacionada": id_actuacion_original,
        "requiere_respuesta": "NO",
    })
    auditoria.registrar(conn, "CORRECCION", "actuacion_solicitud", id_actuacion_original, None, motivo,
                         f"Registrada como actuación #{id_correccion}")
    conn.commit()
    return id_correccion


def obtener_actuaciones(conn, id_solicitud: int):
    return conn.execute(
        "SELECT * FROM actuaciones_solicitud WHERE id_solicitud = ? ORDER BY fecha, hora, id",
        (id_solicitud,),
    ).fetchall()


def obtener_pendientes_abiertos(conn, id_solicitud: int):
    """Actuaciones de ESTA solicitud que siguen esperando respuesta, con dias
    habiles de espera ya calculados -- usado para la seccion 'PENDIENTES
    ABIERTOS' y para derivar el texto de 'PENDIENTE ACTUAL' sin duplicar
    informacion manualmente."""
    filas = conn.execute(
        """SELECT * FROM actuaciones_solicitud
           WHERE id_solicitud = ? AND requiere_respuesta='SI' AND respuesta_recibida='NO' AND anulada=0
           ORDER BY fecha""",
        (id_solicitud,),
    ).fetchall()
    hoy = date.today()
    resultado = []
    for f in filas:
        try:
            fecha_envio = date.fromisoformat(str(f["fecha"])[:10])
            dias_habiles = contar_dias_habiles(fecha_envio, hoy)
            dias_calendario = (hoy - fecha_envio).days
        except (ValueError, TypeError):
            dias_habiles = dias_calendario = None
        resultado.append({**dict(f), "dias_habiles_esperando": dias_habiles, "dias_calendario_esperando": dias_calendario})
    return resultado


def calcular_pendiente_actual(pendientes_abiertos: list) -> str:
    """Texto derivado (nunca guardado por separado) para no duplicar
    informacion que ya vive en las actuaciones abiertas."""
    if not pendientes_abiertos:
        return "Sin pendiente registrado"
    p = pendientes_abiertos[0]
    etiqueta = p["tipo_actuacion"].replace("_", " ").title()
    if p.get("dependencia_destino"):
        return f"Esperando {etiqueta} de {p['dependencia_destino']}"
    return f"Esperando {etiqueta}"


def pendientes_de_respuesta(conn, umbral_dias_habiles: int):
    filas = conn.execute(
        """SELECT a.id AS id_actuacion, a.fecha AS fecha_envio, a.tipo_actuacion, a.dependencia_destino,
                  a.responsable, a.fecha_limite_respuesta, a.descripcion,
                  s.id AS id_solicitud, s.codigo_solicitud, s.institucion
           FROM actuaciones_solicitud a
           JOIN solicitudes s ON s.id = a.id_solicitud
           WHERE a.requiere_respuesta = 'SI' AND a.respuesta_recibida = 'NO' AND a.anulada = 0
                 AND s.activo = 1"""
    ).fetchall()

    resultado = []
    hoy = date.today()
    for f in filas:
        try:
            fecha_envio = date.fromisoformat(str(f["fecha_envio"])[:10])
        except (ValueError, TypeError):
            continue
        dias_habiles = contar_dias_habiles(fecha_envio, hoy)
        item = dict(f)
        item["dias_habiles_esperando"] = dias_habiles
        item["dias_calendario_esperando"] = (hoy - fecha_envio).days
        item["alerta"] = dias_habiles >= umbral_dias_habiles
        resultado.append(item)

    resultado.sort(key=lambda r: r["dias_habiles_esperando"], reverse=True)
    return resultado


# ------------------------------------------------------------- documentos --

def _calcular_ruta_relativa(ruta_absoluta, ruta_base_convenios: Path):
    """Ruta relativa al repositorio raiz, para no depender de que el documento
    siempre se resuelva desde esta misma ruta absoluta local (seccion 35:
    preparacion para resolver documentos desde otro equipo o desde
    SharePoint/OneDrive sin reconstruir la base)."""
    if not ruta_absoluta:
        return None
    try:
        return str(Path(ruta_absoluta).resolve().relative_to(Path(ruta_base_convenios).resolve()))
    except ValueError:
        return None


def registrar_documento_tramite(conn, id_solicitud: int, datos: dict, id_actuacion=None, ruta_base_convenios: Path = None):
    ahora = datetime.now().isoformat()
    ruta_relativa = datos.get("ruta_relativa")
    if ruta_relativa is None and ruta_base_convenios is not None:
        ruta_relativa = _calcular_ruta_relativa(datos.get("ruta"), ruta_base_convenios)
    conn.execute(
        """INSERT INTO documentos_tramite (id_solicitud, id_actuacion, nombre, ruta, ruta_relativa, tipo, fecha, fecha_registro)
           VALUES (?,?,?,?,?,?,?,?)""",
        (id_solicitud, id_actuacion, datos["nombre"], datos.get("ruta"), ruta_relativa, datos.get("tipo"),
         datos.get("fecha"), ahora),
    )
    conn.commit()


def obtener_documentos_tramite(conn, id_solicitud: int):
    return conn.execute(
        "SELECT * FROM documentos_tramite WHERE id_solicitud = ? ORDER BY fecha_registro DESC", (id_solicitud,)
    ).fetchall()


# ------------------------------------------------------ vinculo con convenio --

def vincular_convenio(conn, id_solicitud: int, id_convenio: int):
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("UPDATE solicitudes SET id_convenio_suscrito = ?, fecha_actualizacion = ? WHERE id = ?",
                     (id_convenio, datetime.now().isoformat(), id_solicitud))
        conn.execute("UPDATE convenios SET id_solicitud_origen = ? WHERE id_sistema = ?",
                     (id_solicitud, id_convenio))
        auditoria.registrar(conn, "VINCULACION_CONVENIO", "solicitud", id_solicitud, None, id_convenio)
        auditoria.registrar(conn, "VINCULACION_CONVENIO", "convenio", id_convenio, None, id_solicitud)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def buscar_convenios_para_vincular(conn, texto: str, limite: int = 20):
    termino = f"%{_normalizar(texto)}%"
    return conn.execute(
        f"""SELECT id_sistema, anio, codigo_original, institucion, tipo_instrumento
            FROM convenios
            WHERE {_EXPR_SIN_TILDES.format(col="institucion")} LIKE ?
               OR {_EXPR_SIN_TILDES.format(col="COALESCE(codigo_original,'')")} LIKE ?
               OR CAST(anio AS TEXT) LIKE ?
            LIMIT ?""",
        (termino, termino, f"%{texto}%", limite),
    ).fetchall()


# -------------------------------------------------------- eliminacion logica --

def desactivar_solicitud(conn, id_solicitud: int, motivo: str):
    solicitud = obtener_solicitud(conn, id_solicitud)
    if solicitud is None:
        raise ValueError(f"Solicitud {id_solicitud} no existe")
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE solicitudes SET activo = 0, estado_actual = 'ARCHIVADO', fecha_actualizacion = ? WHERE id = ?",
            (datetime.now().isoformat(), id_solicitud),
        )
        auditoria.registrar(conn, "ELIMINACION_LOGICA", "solicitud", id_solicitud,
                             solicitud["estado_actual"], "ARCHIVADO", motivo)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def reactivar_solicitud(conn, id_solicitud: int, motivo: str):
    """Deshace un archivado: restaura el estado que tenia justo antes de
    archivarse (tomado de la propia auditoria, para no inventar un estado
    nuevo), y deja constancia de la reactivacion."""
    solicitud = obtener_solicitud(conn, id_solicitud)
    if solicitud is None:
        raise ValueError(f"Solicitud {id_solicitud} no existe")

    ultimo_archivado = conn.execute(
        "SELECT valor_anterior FROM auditoria WHERE entidad='solicitud' AND id_entidad=? "
        "AND accion='ELIMINACION_LOGICA' ORDER BY id DESC LIMIT 1",
        (id_solicitud,),
    ).fetchone()
    estado_restaurado = ultimo_archivado["valor_anterior"] if ultimo_archivado and ultimo_archivado["valor_anterior"] else "EN_GESTION"

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE solicitudes SET activo = 1, estado_actual = ?, fecha_actualizacion = ? WHERE id = ?",
            (estado_restaurado, datetime.now().isoformat(), id_solicitud),
        )
        auditoria.registrar(conn, "REACTIVACION", "solicitud", id_solicitud, "ARCHIVADO", estado_restaurado, motivo)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


_CAMPOS_EDITABLES_SOLICITUD = [
    "institucion", "asunto", "persona_contacto", "correo_contacto", "tipo_convenio_solicitado", "observaciones",
]


def editar_solicitud(conn, id_solicitud: int, campos: dict):
    """Corrige datos basicos (no de trazabilidad). Cada campo modificado
    queda en auditoria con su valor anterior y nuevo -- nunca se sobreescribe
    en silencio."""
    solicitud = obtener_solicitud(conn, id_solicitud)
    if solicitud is None:
        raise ValueError(f"Solicitud {id_solicitud} no existe")

    cambios = {c: v for c, v in campos.items() if c in _CAMPOS_EDITABLES_SOLICITUD and v != solicitud[c]}
    if not cambios:
        return

    conn.execute("BEGIN IMMEDIATE")
    try:
        set_sql = ", ".join(f"{c} = ?" for c in cambios)
        conn.execute(
            f"UPDATE solicitudes SET {set_sql}, fecha_actualizacion = ? WHERE id = ?",
            list(cambios.values()) + [datetime.now().isoformat(), id_solicitud],
        )
        for campo, nuevo in cambios.items():
            auditoria.registrar(conn, "EDICION", "solicitud", id_solicitud, solicitud[campo], nuevo, f"Campo: {campo}")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def actividad_reciente(conn, limite: int = 15):
    return conn.execute(
        """SELECT a.fecha, a.hora, a.tipo_actuacion, a.descripcion, a.fecha_registro,
                  s.id AS id_solicitud, s.codigo_solicitud, s.institucion
           FROM actuaciones_solicitud a
           JOIN solicitudes s ON s.id = a.id_solicitud
           ORDER BY a.fecha_registro DESC LIMIT ?""",
        (limite,),
    ).fetchall()


def trabajo_de_responsable(conn, responsable: str):
    asignados = conn.execute(
        "SELECT * FROM solicitudes WHERE activo=1 AND (responsable_actual = ? OR delegado_actual = ?) "
        "ORDER BY fecha_ultima_actuacion",
        (responsable, responsable),
    ).fetchall()
    pendientes = [p for p in pendientes_de_respuesta(conn, 999) if p["responsable"] == responsable]
    return asignados, pendientes


# ------------------------------------------------------------------ kanban --

def tablero_kanban(conn):
    etapas = conn.execute("SELECT codigo, etiqueta FROM catalogo_etapas_solicitud WHERE activo=1 ORDER BY orden").fetchall()
    columnas = []
    for etapa in etapas:
        filas = conn.execute(
            "SELECT id, codigo_solicitud, institucion, responsable_actual, fecha_ultima_actuacion "
            "FROM solicitudes WHERE activo=1 AND etapa_actual=? ORDER BY fecha_ultima_actuacion",
            (etapa["codigo"],),
        ).fetchall()
        columnas.append({"etapa": etapa["etiqueta"], "codigo": etapa["codigo"], "solicitudes": filas})
    return columnas


# ------------------------------------------------------------------ informes --

def informe_por_mes(conn):
    return conn.execute(
        "SELECT strftime('%Y-%m', fecha_ingreso) AS mes, COUNT(*) AS total "
        "FROM solicitudes WHERE activo=1 GROUP BY mes ORDER BY mes"
    ).fetchall()


def informe_por_medio_ingreso(conn):
    return conn.execute(
        "SELECT medio_ingreso, COUNT(*) AS total FROM solicitudes WHERE activo=1 GROUP BY medio_ingreso"
    ).fetchall()


def informe_por_responsable(conn):
    return conn.execute(
        "SELECT responsable_actual, COUNT(*) AS total FROM solicitudes WHERE activo=1 "
        "AND responsable_actual IS NOT NULL GROUP BY responsable_actual ORDER BY total DESC"
    ).fetchall()


def informe_por_estado(conn):
    return conn.execute(
        "SELECT estado_actual, COUNT(*) AS total FROM solicitudes WHERE activo=1 GROUP BY estado_actual"
    ).fetchall()


def informe_por_etapa(conn):
    return conn.execute(
        "SELECT etapa_actual, COUNT(*) AS total FROM solicitudes WHERE activo=1 GROUP BY etapa_actual"
    ).fetchall()


_ESTADOS_CERRADOS = ("SUSCRITO", "ARCHIVADO", "NO_PROCEDENTE")


def informe_ingresadas_por_semana(conn):
    return conn.execute(
        "SELECT strftime('%Y-W%W', fecha_ingreso) AS semana, COUNT(*) AS total "
        "FROM solicitudes GROUP BY semana ORDER BY semana"
    ).fetchall()


def informe_abiertas_cerradas(conn):
    abiertas = conn.execute(
        f"SELECT COUNT(*) FROM solicitudes WHERE activo=1 AND estado_actual NOT IN {_ESTADOS_CERRADOS}"
    ).fetchone()[0]
    cerradas = conn.execute(
        f"SELECT COUNT(*) FROM solicitudes WHERE estado_actual IN {_ESTADOS_CERRADOS}"
    ).fetchone()[0]
    return {"abiertas": abiertas, "cerradas": cerradas}


def informe_tiempo_promedio_primera_actuacion(conn):
    """Dias promedio entre el ingreso y la PRIMERA actuacion registrada
    (excluyendo la propia solicitud recien creada sin ninguna actuacion aun)."""
    fila = conn.execute(
        """SELECT AVG(julianday(primera.fecha) - julianday(s.fecha_ingreso)) AS promedio
           FROM solicitudes s
           JOIN (SELECT id_solicitud, MIN(fecha) AS fecha FROM actuaciones_solicitud GROUP BY id_solicitud) primera
                ON primera.id_solicitud = s.id"""
    ).fetchone()
    return round(fila["promedio"], 1) if fila and fila["promedio"] is not None else None


def informe_tiempo_promedio_total(conn):
    """Dias promedio entre ingreso y ultima actuacion, solo para solicitudes
    ya cerradas (suscrito/archivado/no procedente)."""
    fila = conn.execute(
        f"""SELECT AVG(julianday(fecha_ultima_actuacion) - julianday(fecha_ingreso)) AS promedio
            FROM solicitudes WHERE estado_actual IN {_ESTADOS_CERRADOS} AND fecha_ultima_actuacion IS NOT NULL"""
    ).fetchone()
    return round(fila["promedio"], 1) if fila and fila["promedio"] is not None else None


def informe_pendientes_por_dependencia(conn):
    return conn.execute(
        """SELECT COALESCE(dependencia_destino, 'Sin dependencia') AS dependencia, COUNT(*) AS total
           FROM actuaciones_solicitud
           WHERE requiere_respuesta='SI' AND respuesta_recibida='NO' AND anulada=0
           GROUP BY dependencia ORDER BY total DESC"""
    ).fetchall()


def informe_carga_por_responsable(conn):
    return conn.execute(
        f"""SELECT responsable_actual, COUNT(*) AS total FROM solicitudes
            WHERE activo=1 AND responsable_actual IS NOT NULL AND estado_actual NOT IN {_ESTADOS_CERRADOS}
            GROUP BY responsable_actual ORDER BY total DESC"""
    ).fetchall()


# ------------------------------------------------------- favoritos/frecuentes --

def dependencias_mas_usadas(conn, limite: int = 8):
    return [r["valor"] for r in conn.execute(
        """SELECT valor, COUNT(*) AS total FROM (
               SELECT dependencia_origen AS valor FROM actuaciones_solicitud WHERE dependencia_origen IS NOT NULL
               UNION ALL
               SELECT dependencia_destino AS valor FROM actuaciones_solicitud WHERE dependencia_destino IS NOT NULL
           ) GROUP BY valor ORDER BY total DESC LIMIT ?""",
        (limite,),
    ).fetchall()]


def actuaciones_mas_usadas(conn, limite: int = 8):
    return [r["tipo_actuacion"] for r in conn.execute(
        "SELECT tipo_actuacion, COUNT(*) AS total FROM actuaciones_solicitud "
        "GROUP BY tipo_actuacion ORDER BY total DESC LIMIT ?",
        (limite,),
    ).fetchall()]


def ordenar_catalogo_por_uso(catalogo: list, campo_codigo: str, mas_usados: list):
    """Reordena una lista de filas de catalogo poniendo primero los valores
    mas usados (sin IA: solo frecuencia de uso local), conservando el resto
    en su orden original."""
    prioridad = {codigo: i for i, codigo in enumerate(mas_usados)}
    return sorted(catalogo, key=lambda fila: prioridad.get(fila[campo_codigo], len(mas_usados) + fila["id"]))
