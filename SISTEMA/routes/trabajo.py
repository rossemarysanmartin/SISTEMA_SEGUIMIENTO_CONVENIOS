"""Panel de trabajo diario (seccion 31/32).

Sin autenticacion real todavia: el "responsable" se identifica con una
cookie local simple (no es un mecanismo de seguridad, solo una conveniencia
para no tener que volver a escribir el nombre en cada visita)."""

from flask import Blueprint, make_response, redirect, render_template, request, url_for

from routes.solicitudes import _conn
from services import repositorio_solicitudes as repo

bp = Blueprint("trabajo", __name__)

COOKIE_ACTOR = "actor_local"


@bp.route("/mi-trabajo")
def mi_trabajo():
    conn = _conn()
    responsable = request.args.get("responsable", "").strip() or request.cookies.get(COOKIE_ACTOR, "")

    if not responsable:
        return render_template("mi_trabajo.html", responsable=None, asignados=[], pendientes=[], actividad=[])

    asignados, pendientes = repo.trabajo_de_responsable(conn, responsable)
    actividad = repo.actividad_reciente(conn, limite=15)

    respuesta = make_response(render_template(
        "mi_trabajo.html", responsable=responsable, asignados=asignados, pendientes=pendientes, actividad=actividad,
    ))
    if request.args.get("responsable"):
        respuesta.set_cookie(COOKIE_ACTOR, responsable, max_age=60 * 60 * 24 * 90)
    return respuesta


@bp.route("/mi-trabajo/salir")
def salir():
    respuesta = redirect(url_for("trabajo.mi_trabajo"))
    respuesta.delete_cookie(COOKIE_ACTOR)
    return respuesta
