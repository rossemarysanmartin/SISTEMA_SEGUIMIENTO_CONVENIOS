from pathlib import Path

from flask import Blueprint, jsonify, redirect, render_template, url_for

import db_maestra
from db_context import obtener_conexion, obtener_config
from services import db_visualizador, sincronizacion

bp = Blueprint("sincronizacion", __name__)


def _conn_factory():
    config = obtener_config()
    return db_maestra.conectar(Path(config.ruta_convenios_db))


@bp.route("/sincronizacion")
def historial():
    conn = obtener_conexion()
    historial_filas = db_visualizador.obtener_historial_sincronizaciones(conn)
    estado = sincronizacion.obtener_estado()
    return render_template("sincronizacion.html", historial=historial_filas, estado=estado)


@bp.route("/sincronizacion/ejecutar", methods=["POST"])
def ejecutar():
    sincronizacion.iniciar_sincronizacion(_conn_factory, db_maestra.registrar_sincronizacion)
    return redirect(url_for("sincronizacion.historial"))


@bp.route("/sincronizacion/estado")
def estado():
    return jsonify(sincronizacion.obtener_estado())


@bp.route("/exportar-excel", methods=["POST"])
def exportar_excel():
    from exportar_excel import generar_excel_maestro
    config = obtener_config()
    generar_excel_maestro(config.ruta_convenios_db, config.ruta_excel_maestro)
    return redirect(url_for("sincronizacion.historial"))
