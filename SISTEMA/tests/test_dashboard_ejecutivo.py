"""Pruebas del Dashboard Ejecutivo Portable (Fase 6.5).

Igual que test_solicitudes.py / test_fase6.py: se ejecutan contra una base
SQLite TEMPORAL y escriben el HTML en un directorio temporal -- nunca tocan
la base real ni DASHBOARD_EJECUTIVO del repositorio.
"""

import sqlite3
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db_fase3
import db_fase5
import db_fase6
import db_maestra
from services import exportar_dashboard_ejecutivo as export
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
    db_fase3.migrar(conexion)
    db_fase5.migrar(conexion)
    db_fase6.migrar(conexion)
    yield conexion
    conexion.close()
    ruta.unlink(missing_ok=True)


@pytest.fixture()
def config_efectiva():
    return SimpleNamespace(
        semaforo_normal_max=3, semaforo_atencion_max=7, semaforo_demora_max=14,
        umbral_dias_habiles_pendiente_respuesta=5,
    )


def _insertar_convenio(conn, **overrides):
    datos = {
        "anio": 2025, "codigo_original": "CONV-001", "institucion": "Universidad de Prueba",
        "tipo_instrumento": "Convenio Marco", "clasificacion_general": "CONVENIO",
        "objeto": "Cooperación académica", "fecha_suscripcion": "2025-01-10",
        "fecha_finalizacion": "2027-01-10", "estado_vigencia": "VIGENTE",
        "dias_para_vencimiento": 400, "administrador": "Juan Pérez",
        "ruta_documento_principal": None, "estado_relacion_documental": "ENCONTRADA",
        "requiere_revision_documental": "NO", "tiene_adenda": "NO", "conflicto_fecha": "NO",
    }
    datos.update(overrides)
    columnas = ", ".join(datos.keys())
    marcadores = ", ".join("?" for _ in datos)
    conn.execute(f"INSERT INTO convenios ({columnas}) VALUES ({marcadores})", list(datos.values()))
    conn.commit()


def test_recolectar_datos_incluye_fecha_de_corte(conn, config_efectiva):
    datos = export.recolectar_datos(conn, config_efectiva)
    assert "fecha_corte" in datos
    assert "/" in datos["fecha_corte"] and ":" in datos["fecha_corte"]


def test_recolectar_convenios_reales(conn, config_efectiva):
    _insertar_convenio(conn)
    _insertar_convenio(conn, codigo_original="CONV-002", institucion="Otra Institución", estado_vigencia="VENCIDO",
                        fecha_finalizacion="2024-01-01", dias_para_vencimiento=-200)
    datos = export.recolectar_datos(conn, config_efectiva)
    assert len(datos["convenios"]) == 2
    assert datos["contadores_convenios"]["total"] == 2
    assert datos["contadores_convenios"]["vencidos"] == 1


def test_convenio_con_ruta_documento_muestra_expediente_disponible(conn, config_efectiva):
    _insertar_convenio(conn, ruta_documento_principal="cualquier_ruta.pdf")
    datos = export.recolectar_datos(conn, config_efectiva)
    assert datos["convenios"][0]["expediente_disponible"] is True


def test_convenio_con_adenda_por_revisar_marca_revision(conn, config_efectiva):
    _insertar_convenio(conn, tiene_adenda="POR_REVISAR")
    datos = export.recolectar_datos(conn, config_efectiva)
    c = datos["convenios"][0]
    assert c["revision"] is True
    assert "Posible adenda" in c["descripciones_revision"]


def test_sin_solicitudes_reales_estado_vacio(conn, config_efectiva):
    datos = export.recolectar_datos(conn, config_efectiva)
    assert datos["solicitudes"] == []
    assert datos["contadores_solicitudes"]["total"] == 0
    html = export.generar_html(datos)
    assert "Actualmente no existen solicitudes registradas." in html


def test_solicitud_real_incluye_pendiente_actual_y_trazabilidad(conn, config_efectiva):
    s = repo.crear_solicitud(conn, {
        "fecha_ingreso": "2026-08-10", "institucion": "Institución con trámite",
        "medio_ingreso": "CORREO_ELECTRONICO", "asunto": "Prueba",
    })
    repo.registrar_actuacion(conn, s["id"], {
        "tipo_actuacion": "SOLICITUD_DE_CRITERIO", "dependencia_destino": "Procuraduría / Asesoría Jurídica",
        "responsable": "Ana Ríos", "requiere_respuesta": "SI",
    })
    datos = export.recolectar_datos(conn, config_efectiva)
    assert len(datos["solicitudes"]) == 1
    sol = datos["solicitudes"][0]
    assert "Solicitud De Criterio" in sol["pendiente_actual"] or "Esperando" in sol["pendiente_actual"]
    assert len(sol["trazabilidad"]) == 1
    assert sol["trazabilidad"][0]["dependencia"] == "Procuraduría / Asesoría Jurídica"


def test_verificador_detecta_ruta_absoluta_windows():
    html_contaminado = r"<p>Documento en C:\Users\alguien\CONVENIOS\archivo.pdf</p>"
    with pytest.raises(export.DatosSensiblesError):
        export.verificar_sin_datos_sensibles(html_contaminado)


def test_verificador_detecta_secret_key():
    with pytest.raises(export.DatosSensiblesError):
        export.verificar_sin_datos_sensibles("<script>SECRET_KEY = 'x'</script>")


def test_exportacion_real_nunca_incluye_la_ruta_absoluta_del_documento(conn, config_efectiva):
    """La ruta absoluta del documento NUNCA debe pasar al HTML -- solo un
    indicador booleano ('expediente disponible'). Este es el comportamiento
    real esperado, no algo que dependa del verificador de patrones."""
    ruta_privada = r"C:\Users\alguien\CONVENIOS\archivo.pdf"
    _insertar_convenio(conn, ruta_documento_principal=ruta_privada)
    datos = export.recolectar_datos(conn, config_efectiva)
    assert ruta_privada not in str(datos)
    html = export.generar_html(datos)
    assert ruta_privada not in html
    export.verificar_sin_datos_sensibles(html)  # no debe lanzar


def test_html_generado_sin_datos_sensibles_pasa_verificacion(conn, config_efectiva):
    _insertar_convenio(conn)
    datos = export.recolectar_datos(conn, config_efectiva)
    html = export.generar_html(datos)
    export.verificar_sin_datos_sensibles(html)  # no debe lanzar


def test_html_no_usa_cdn_externos(conn, config_efectiva):
    _insertar_convenio(conn)
    datos = export.recolectar_datos(conn, config_efectiva)
    html = export.generar_html(datos)
    assert "<script src=" not in html
    assert "cdn." not in html.lower()
    assert "http://" not in html and "https://" not in html


def test_generar_dashboard_ejecutivo_escribe_archivo_en_directorio_temporal(conn, config_efectiva, tmp_path):
    _insertar_convenio(conn)
    ruta_base_falsa = tmp_path / "CONVENIOS INTERINSTITUCIONALES UTMACH"
    config = SimpleNamespace(
        ruta_base_convenios=ruta_base_falsa,
        ruta_dashboard_ejecutivo_html=ruta_base_falsa / "SISTEMA_SEGUIMIENTO_CONVENIOS" / "DASHBOARD_EJECUTIVO" / "DASHBOARD_CONVENIOS_UTMACH.html",
        ruta_dashboard_ejecutivo_historico=ruta_base_falsa / "SISTEMA_SEGUIMIENTO_CONVENIOS" / "DASHBOARD_EJECUTIVO" / "HISTORICO",
    )
    ruta = export.generar_dashboard_ejecutivo(conn, config, config_efectiva, guardar_historico=True)
    assert ruta.exists()
    assert ruta.name == "DASHBOARD_CONVENIOS_UTMACH.html"
    historico = list(config.ruta_dashboard_ejecutivo_historico.glob("*.html"))
    assert len(historico) == 1


def test_generar_dashboard_ejecutivo_bloquea_escritura_fuera_del_sistema(conn, config_efectiva, tmp_path):
    _insertar_convenio(conn)
    ruta_base_falsa = tmp_path / "CONVENIOS INTERINSTITUCIONALES UTMACH"
    config = SimpleNamespace(
        ruta_base_convenios=ruta_base_falsa,
        ruta_dashboard_ejecutivo_html=ruta_base_falsa / "DASHBOARD_CONVENIOS_UTMACH.html",  # fuera de SISTEMA_SEGUIMIENTO_CONVENIOS
        ruta_dashboard_ejecutivo_historico=ruta_base_falsa / "HISTORICO",
    )
    from seguridad import ViolacionSoloLecturaError
    with pytest.raises(ViolacionSoloLecturaError):
        export.generar_dashboard_ejecutivo(conn, config, config_efectiva)


def test_seccion_demostrativa_solicitudes_presente_y_no_contamina_sqlite(conn, config_efectiva):
    """La seccion 'Solicitudes y trazabilidad' es estatica/demostrativa: debe
    aparecer en el HTML con su aviso, pero jamas debe insertar una fila real
    en la tabla `solicitudes` (verificado contando filas antes y despues)."""
    total_antes = conn.execute("SELECT COUNT(*) FROM solicitudes").fetchone()[0]

    _insertar_convenio(conn)
    datos = export.recolectar_datos(conn, config_efectiva)
    html = export.generar_html(datos)

    assert "Solicitudes y trazabilidad" in html
    assert "Vista demostrativa — el registro real se realiza en el Sistema de Seguimiento de Convenios." in html
    assert "EJEMPLO DEMOSTRATIVO — NO CORRESPONDE A UN TRÁMITE REAL" in html
    assert "SOL-2026-0001" in html
    assert "Esperando criterio de factibilidad" in html
    assert "Marcar como suscrito" in html
    export.verificar_sin_datos_sensibles(html)

    total_despues = conn.execute("SELECT COUNT(*) FROM solicitudes").fetchone()[0]
    assert total_despues == total_antes == 0


def test_grafico_por_anio_agrupa_correctamente(conn, config_efectiva):
    _insertar_convenio(conn, anio=2025)
    _insertar_convenio(conn, anio=2025, codigo_original="CONV-002", institucion="Otra")
    _insertar_convenio(conn, anio=2024, codigo_original="CONV-003", institucion="Tercera")
    datos = export.recolectar_datos(conn, config_efectiva)
    por_anio = {f["etiqueta"]: f["total"] for f in datos["graficos"]["por_anio"]}
    assert por_anio["2025"] == 2
    assert por_anio["2024"] == 1
