from flask import Blueprint, render_template

from db_context import obtener_conexion, obtener_config
from services import db_visualizador
from services import repositorio_solicitudes as repo

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def inicio():
    conn = obtener_conexion()
    config = obtener_config()
    contadores = db_visualizador.obtener_contadores_dashboard(conn)
    proximos = db_visualizador.listar_proximos_a_vencer(conn, limite=8)
    contadores_solicitudes = repo.contadores_dashboard_solicitudes(conn, config)
    actividad_reciente = repo.actividad_reciente(conn, limite=8)
    return render_template(
        "dashboard.html", contadores=contadores, proximos=proximos, contadores_solicitudes=contadores_solicitudes,
        actividad_reciente=actividad_reciente,
    )
