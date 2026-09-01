"""Pruebas de las mejoras de usabilidad de la Fase 6 (estabilizacion).

Igual que test_solicitudes.py: se ejecutan contra una base SQLite TEMPORAL,
nunca la real.
"""

import sqlite3
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db_fase5
import db_fase6
import db_maestra
from services import busqueda_global, catalogos_admin, configuracion as cfg_service
from services import repositorio_solicitudes as repo


@pytest.fixture()
def conn():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    ruta = Path(tmp.name)
    conexion = sqlite3.connect(str(ruta), isolation_level=None)
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA foreign_keys = ON;")
    db_maestra.inicializar_esquema(conexion)
    db_fase5.migrar(conexion)
    db_fase6.migrar(conexion)
    yield conexion
    conexion.close()
    ruta.unlink(missing_ok=True)


def _datos_solicitud(**overrides):
    datos = {
        "fecha_ingreso": "2026-08-20", "institucion": "Institución de Prueba",
        "medio_ingreso": "CORREO_ELECTRONICO", "asunto": "Prueba",
    }
    datos.update(overrides)
    return datos


# --------------------------------------------------------- pendiente actual --

def test_pendiente_actual_sin_pendientes_es_texto_neutro(conn):
    s = repo.crear_solicitud(conn, _datos_solicitud())
    pendientes = repo.obtener_pendientes_abiertos(conn, s["id"])
    assert pendientes == []
    assert repo.calcular_pendiente_actual(pendientes) == "Sin pendiente registrado"


def test_pendiente_actual_se_deriva_de_actuacion_abierta(conn):
    s = repo.crear_solicitud(conn, _datos_solicitud())
    repo.registrar_actuacion(conn, s["id"], {
        "tipo_actuacion": "SOLICITUD_DE_CRITERIO", "dependencia_destino": "Procuraduría",
        "requiere_respuesta": "SI",
    })
    pendientes = repo.obtener_pendientes_abiertos(conn, s["id"])
    assert len(pendientes) == 1
    assert pendientes[0]["dias_habiles_esperando"] is not None
    texto = repo.calcular_pendiente_actual(pendientes)
    assert "Procuraduría" in texto
    assert "Solicitud De Criterio" in texto


def test_pendiente_actual_desaparece_al_responder(conn):
    s = repo.crear_solicitud(conn, _datos_solicitud())
    id_act = repo.registrar_actuacion(conn, s["id"], {
        "tipo_actuacion": "SOLICITUD_DE_CRITERIO", "requiere_respuesta": "SI",
    })
    repo.registrar_actuacion(conn, s["id"], {
        "tipo_actuacion": "CRITERIO_RECIBIDO", "id_actuacion_relacionada": id_act, "respuesta_recibida": "SI",
    })
    pendientes = repo.obtener_pendientes_abiertos(conn, s["id"])
    assert pendientes == []
    assert repo.calcular_pendiente_actual(pendientes) == "Sin pendiente registrado"


# ------------------------------------------------------------- nota interna --

def test_nota_interna_no_cambia_estado_ni_etapa(conn):
    s = repo.crear_solicitud(conn, _datos_solicitud())
    repo.registrar_actuacion(conn, s["id"], {"tipo_actuacion": "REVISION_INICIAL", "estado_nuevo": "EN_GESTION"})
    antes = repo.obtener_solicitud(conn, s["id"])
    repo.registrar_actuacion(conn, s["id"], {
        "tipo_actuacion": "NOTA_INTERNA",
        "descripcion": "Se conversó telefónicamente con la contraparte, remitirá documentación mañana.",
    })
    despues = repo.obtener_solicitud(conn, s["id"])
    assert despues["estado_actual"] == antes["estado_actual"] == "EN_GESTION"
    assert despues["etapa_actual"] == antes["etapa_actual"]
    # pero SI actualiza fecha_ultima_actuacion (es una actuacion real del historial)
    assert despues["fecha_ultima_actuacion"] is not None


# ----------------------------------------------------------- edicion auditada --

def test_editar_solicitud_actualiza_y_audita(conn):
    s = repo.crear_solicitud(conn, _datos_solicitud(institucion="Nombre Original"))
    repo.editar_solicitud(conn, s["id"], {"institucion": "Nombre Corregido", "asunto": "Prueba"})
    actualizada = repo.obtener_solicitud(conn, s["id"])
    assert actualizada["institucion"] == "Nombre Corregido"
    auditoria = conn.execute(
        "SELECT * FROM auditoria WHERE entidad='solicitud' AND id_entidad=? AND accion='EDICION'", (s["id"],)
    ).fetchall()
    assert len(auditoria) == 1
    assert auditoria[0]["valor_anterior"] == "Nombre Original"
    assert auditoria[0]["valor_nuevo"] == "Nombre Corregido"


def test_editar_solicitud_sin_cambios_no_genera_auditoria_vacia(conn):
    s = repo.crear_solicitud(conn, _datos_solicitud(institucion="Igual"))
    repo.editar_solicitud(conn, s["id"], {"institucion": "Igual"})
    auditoria = conn.execute(
        "SELECT * FROM auditoria WHERE entidad='solicitud' AND id_entidad=? AND accion='EDICION'", (s["id"],)
    ).fetchall()
    assert len(auditoria) == 0


# ----------------------------------------------------------- archivar/reactivar --

def test_reactivar_restaura_estado_previo_al_archivado(conn):
    s = repo.crear_solicitud(conn, _datos_solicitud())
    repo.registrar_actuacion(conn, s["id"], {"tipo_actuacion": "REVISION_INICIAL", "estado_nuevo": "EN_GESTION"})
    repo.desactivar_solicitud(conn, s["id"], "motivo de prueba")
    archivada = repo.obtener_solicitud(conn, s["id"])
    assert archivada["activo"] == 0
    assert archivada["estado_actual"] == "ARCHIVADO"

    repo.reactivar_solicitud(conn, s["id"], "reactivada por error")
    reactivada = repo.obtener_solicitud(conn, s["id"])
    assert reactivada["activo"] == 1
    assert reactivada["estado_actual"] == "EN_GESTION"  # el que tenia antes de archivar

    auditoria = conn.execute(
        "SELECT * FROM auditoria WHERE entidad='solicitud' AND id_entidad=? AND accion='REACTIVACION'", (s["id"],)
    ).fetchall()
    assert len(auditoria) == 1


# ------------------------------------------------------------- configuracion --

def test_configuracion_override_tiene_prioridad_sobre_default(conn):
    class ConfigJsonFalsa:
        semaforo_normal_max = 3
        semaforo_atencion_max = 7
        semaforo_demora_max = 14
        umbral_dias_habiles_pendiente_respuesta = 5

    config_json = ConfigJsonFalsa()
    efectiva_antes = cfg_service.config_efectiva(conn, config_json)
    assert efectiva_antes.semaforo_normal_max == 3  # sin override, usa el default

    cfg_service.guardar_valor(conn, "semaforo_normal_max", 2, "prueba")
    efectiva_despues = cfg_service.config_efectiva(conn, config_json)
    assert efectiva_despues.semaforo_normal_max == 2  # override aplicado
    assert efectiva_despues.semaforo_atencion_max == 7  # el resto sigue en default


def test_configuracion_guardar_valor_registra_auditoria_en_cambio_real(conn):
    cfg_service.guardar_valor(conn, "umbral_dias_habiles_pendiente_respuesta", 4, "prueba")
    cfg_service.guardar_valor(conn, "umbral_dias_habiles_pendiente_respuesta", 4, "prueba")  # mismo valor, no debe duplicar auditoria
    auditoria = conn.execute(
        "SELECT * FROM auditoria WHERE entidad='configuracion' AND accion='CAMBIO_CONFIGURACION'"
    ).fetchall()
    assert len(auditoria) == 1


# --------------------------------------------------------------- catalogos --

def test_catalogo_crear_activar_desactivar_editar(conn):
    catalogos_admin.crear(conn, "dependencias", {"nombre": "Facultad de Ciencias Sociales"})
    filas = catalogos_admin.listar(conn, "dependencias")
    creada = next(f for f in filas if f["nombre"] == "Facultad de Ciencias Sociales")
    assert creada["activo"] == 1

    catalogos_admin.cambiar_activo(conn, "dependencias", creada["id"], False)
    filas = catalogos_admin.listar(conn, "dependencias")
    assert next(f for f in filas if f["id"] == creada["id"])["activo"] == 0

    catalogos_admin.editar_texto(conn, "dependencias", creada["id"], "Facultad de Ciencias Sociales (renombrada)")
    filas = catalogos_admin.listar(conn, "dependencias")
    assert next(f for f in filas if f["id"] == creada["id"])["nombre"] == "Facultad de Ciencias Sociales (renombrada)"


def test_catalogo_desactivar_no_elimina_fisicamente(conn):
    catalogos_admin.crear(conn, "responsables", {"nombre": "Juan Pérez", "cargo": "Analista"})
    filas = catalogos_admin.listar(conn, "responsables")
    creado = next(f for f in filas if f["nombre"] == "Juan Pérez")
    catalogos_admin.cambiar_activo(conn, "responsables", creado["id"], False)
    filas = catalogos_admin.listar(conn, "responsables")
    assert any(f["id"] == creado["id"] for f in filas)  # sigue existiendo


def test_catalogo_mover_intercambia_orden(conn):
    filas_antes = catalogos_admin.listar(conn, "etapas")
    primero, segundo = filas_antes[0], filas_antes[1]
    catalogos_admin.mover(conn, "etapas", segundo["id"], "subir")
    filas_despues = catalogos_admin.listar(conn, "etapas")
    assert filas_despues[0]["id"] == segundo["id"]
    assert filas_despues[1]["id"] == primero["id"]


# ------------------------------------------------------------ busqueda global --

def test_busqueda_global_diferencia_convenios_y_solicitudes(conn):
    conn.execute(
        "INSERT INTO convenios (anio, institucion, clasificacion_general) VALUES (2026, 'Universidad de Loja', 'CONVENIO')"
    )
    repo.crear_solicitud(conn, _datos_solicitud(institucion="Universidad de Loja - Trámite"))

    resultados = busqueda_global.buscar(conn, "Loja")
    assert len(resultados["convenios"]) == 1
    assert len(resultados["solicitudes"]) == 1


def test_busqueda_global_vacia_no_falla(conn):
    resultados = busqueda_global.buscar(conn, "")
    assert resultados == {"convenios": [], "solicitudes": []}


# ------------------------------------------------------------ favoritos/uso --

def test_dependencias_mas_usadas_prioriza_por_frecuencia(conn):
    s = repo.crear_solicitud(conn, _datos_solicitud())
    for _ in range(3):
        repo.registrar_actuacion(conn, s["id"], {"tipo_actuacion": "SOLICITUD_DE_CRITERIO", "dependencia_destino": "Jurídico"})
    repo.registrar_actuacion(conn, s["id"], {"tipo_actuacion": "SOLICITUD_DE_FACTIBILIDAD", "dependencia_destino": "Vicerrectorado"})
    mas_usadas = repo.dependencias_mas_usadas(conn)
    assert mas_usadas[0] == "Jurídico"
