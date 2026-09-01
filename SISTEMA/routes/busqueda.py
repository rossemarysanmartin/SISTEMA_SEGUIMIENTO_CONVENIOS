from flask import Blueprint, render_template, request

from db_context import obtener_conexion
from services import busqueda_global

bp = Blueprint("busqueda", __name__)


@bp.route("/buscar")
def buscar():
    texto = request.args.get("q", "").strip()
    conn = obtener_conexion()
    resultados = busqueda_global.buscar(conn, texto)
    return render_template("busqueda_resultados.html", texto=texto, resultados=resultados)
