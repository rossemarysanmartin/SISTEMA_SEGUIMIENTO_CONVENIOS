"""Pruebas basicas del visualizador (Fase 4).

Se ejecutan contra la base de datos real (BASE_DATOS/convenios.db) en modo
SOLO LECTURA -- no se modifica nada. Cubren: busqueda, filtros, calculo de
vigencia, apertura segura de rutas, y la disponibilidad de casos reales
representativos (vigente, vencido, proximo a vencer, sin fecha, con posible
adenda, coincidencia probable, PDF escaneado, firma electronica detectada).

Ejecutar con: python -m pytest tests/ -v
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import crear_app
from config import cargar_config
from services import apertura_archivos, db_visualizador
from vigencia import calcular_estado_vigencia, calcular_fecha_finalizacion


@pytest.fixture(scope="module")
def config():
    return cargar_config()


@pytest.fixture(scope="module")
def conn(config):
    conexion = db_visualizador.conectar(config.ruta_convenios_db)
    yield conexion
    conexion.close()


@pytest.fixture(scope="module")
def cliente():
    app = crear_app()
    app.config.update(TESTING=True)
    with app.test_client() as c:
        yield c


# ---------------------------------------------------------------- vigencia --

def test_vigencia_vigente():
    fin = date.today() + timedelta(days=300)
    assert calcular_estado_vigencia(fin, 90) == "VIGENTE"


def test_vigencia_proximo_a_vencer():
    fin = date.today() + timedelta(days=10)
    assert calcular_estado_vigencia(fin, 90) == "PROXIMO_A_VENCER"


def test_vigencia_vencido():
    fin = date.today() - timedelta(days=5)
    assert calcular_estado_vigencia(fin, 90) == "VENCIDO"


def test_vigencia_sin_informacion():
    assert calcular_estado_vigencia(None, 90) == "SIN_INFORMACION"


def test_calculo_fecha_finalizacion_por_duracion():
    inicio, fin, metodo = calcular_fecha_finalizacion(date(2021, 1, 1), "2 años")
    assert fin == date(2023, 1, 1)
    assert metodo == "DURACION_EXPLICITA_DESDE_FECHA_SUSCRIPCION"


def test_calculo_fecha_finalizacion_sin_informacion():
    _, fin, metodo = calcular_fecha_finalizacion(None, None)
    assert fin is None
    assert metodo == "SIN_INFORMACION_SUFICIENTE"


# --------------------------------------------------------- apertura segura --

def test_apertura_rechaza_ruta_fuera_del_repositorio(config):
    with pytest.raises(apertura_archivos.RutaNoAutorizadaError):
        apertura_archivos._validar_dentro_de_base(Path("C:/Windows/System32/cmd.exe"), config.ruta_base_convenios)


def test_apertura_acepta_ruta_dentro_del_repositorio(config):
    ruta = config.ruta_base_convenios / "SISTEMA_SEGUIMIENTO_CONVENIOS" / "CONFIGURACION" / "config.json"
    validada = apertura_archivos._validar_dentro_de_base(ruta, config.ruta_base_convenios)
    assert str(validada).startswith(str(config.ruta_base_convenios.resolve()))


# ---------------------------------------------------------- busqueda/filtros --

def test_busqueda_por_texto_no_falla_y_es_case_insensitive(conn):
    filas_min, total_min, _ = db_visualizador.buscar_y_listar_convenios(
        conn, {}, "universidad", "anio", "desc", 1
    )
    filas_mayus, total_mayus, _ = db_visualizador.buscar_y_listar_convenios(
        conn, {}, "UNIVERSIDAD", "anio", "desc", 1
    )
    assert total_min == total_mayus
    assert total_min > 0


def test_filtro_por_anio(conn):
    filas, total, _ = db_visualizador.buscar_y_listar_convenios(
        conn, {"anio": 2021}, "", "anio", "desc", 1
    )
    assert total > 0
    assert all(f["anio"] == 2021 for f in filas)


def test_filtro_estado_vigencia_vigente(conn):
    filas, total, _ = db_visualizador.buscar_y_listar_convenios(
        conn, {"estado_vigencia": "VIGENTE"}, "", "anio", "desc", 1
    )
    assert total > 0
    assert all(f["estado_vigencia"] == "VIGENTE" for f in filas)


def test_paginacion_respeta_tamano_de_pagina(conn):
    filas, total, total_paginas = db_visualizador.buscar_y_listar_convenios(
        conn, {}, "", "anio", "desc", 1
    )
    assert len(filas) <= db_visualizador.REGISTROS_POR_PAGINA
    assert total_paginas == max(1, -(-total // db_visualizador.REGISTROS_POR_PAGINA))


def test_contadores_dashboard_son_consistentes(conn):
    contadores = db_visualizador.obtener_contadores_dashboard(conn)
    suma_estados = (
        contadores["vigentes"] + contadores["proximos_a_vencer"]
        + contadores["vencidos"] + contadores["sin_informacion"]
    )
    assert suma_estados == contadores["total"]


# --------------------------------------------------- casos reales del dominio --

def _primer_id(conn, sql):
    fila = conn.execute(sql).fetchone()
    return fila[0] if fila else None


@pytest.mark.parametrize("descripcion,sql_condicion", [
    ("vigente", "estado_vigencia='VIGENTE'"),
    ("vencido", "estado_vigencia='VENCIDO'"),
    ("proximo_a_vencer", "estado_vigencia='PROXIMO_A_VENCER'"),
    ("sin_fecha", "(estado_vigencia IS NULL OR estado_vigencia='SIN_INFORMACION')"),
    ("con_posible_adenda", "tiene_adenda='SI'"),
    ("coincidencia_probable", "estado_relacion_documental='PROBABLE'"),
])
def test_ficha_individual_renderiza_para_cada_categoria(conn, cliente, descripcion, sql_condicion):
    id_sistema = _primer_id(
        conn, f"SELECT id_sistema FROM convenios WHERE clasificacion_general='CONVENIO' AND {sql_condicion} LIMIT 1"
    )
    if id_sistema is None:
        pytest.skip(f"No hay ningun registro real de tipo '{descripcion}' para probar")
    respuesta = cliente.get(f"/convenios/{id_sistema}")
    assert respuesta.status_code == 200


def test_ficha_con_pdf_escaneado(conn, cliente):
    id_sistema = _primer_id(
        conn,
        """SELECT c.id_sistema FROM convenios c JOIN documentos d ON d.id_convenio = c.id_sistema
           WHERE d.clasificacion_tecnica_pdf='POSIBLE_ESCANEADO' LIMIT 1""",
    )
    if id_sistema is None:
        pytest.skip("No hay documentos escaneados en la base para probar")
    respuesta = cliente.get(f"/convenios/{id_sistema}")
    assert respuesta.status_code == 200


def test_ficha_con_firma_electronica_detectada(conn, cliente):
    id_sistema = _primer_id(
        conn,
        """SELECT c.id_sistema FROM convenios c JOIN documentos d ON d.id_convenio = c.id_sistema
           WHERE d.cantidad_firmas > 0 LIMIT 1""",
    )
    if id_sistema is None:
        pytest.skip("No hay documentos con firma electronica detectada para probar")
    respuesta = cliente.get(f"/convenios/{id_sistema}")
    assert respuesta.status_code == 200


def test_convenio_inexistente_devuelve_404(cliente):
    respuesta = cliente.get("/convenios/999999999")
    assert respuesta.status_code == 404


# ------------------------------------------------------------------ rutas --

@pytest.mark.parametrize("ruta", [
    "/", "/convenios", "/proximos-a-vencer", "/vencidos", "/revision-pendiente", "/sincronizacion",
])
def test_rutas_principales_responden_200(cliente, ruta):
    assert cliente.get(ruta).status_code == 200


def test_abrir_documento_rechaza_ruta_no_autorizada(cliente):
    respuesta = cliente.get("/abrir-documento?ruta=C:/Windows/System32/cmd.exe")
    assert respuesta.status_code == 400
