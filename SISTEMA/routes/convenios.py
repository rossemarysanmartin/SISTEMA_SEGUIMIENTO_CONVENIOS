from flask import Blueprint, abort, redirect, render_template, request, url_for

from db_context import obtener_conexion, obtener_config
from services import apertura_archivos, db_visualizador

bp = Blueprint("convenios", __name__)


@bp.route("/convenios")
def lista():
    conn = obtener_conexion()
    filtros = {
        "anio": request.args.get("anio", type=int),
        "tipo": request.args.get("tipo") or None,
        "estado_vigencia": request.args.get("estado_vigencia") or None,
        "administrador": request.args.get("administrador") or None,
        "tiene_adenda": request.args.get("tiene_adenda") or None,
        "requiere_revision": request.args.get("requiere_revision") or None,
        "institucion": request.args.get("institucion") or None,
    }
    busqueda = request.args.get("q", "").strip()
    orden = request.args.get("orden", "anio")
    direccion = request.args.get("dir", "desc")
    pagina = request.args.get("pagina", 1, type=int)

    filas, total, total_paginas = db_visualizador.buscar_y_listar_convenios(
        conn, filtros, busqueda, orden, direccion, pagina
    )
    disponibles = db_visualizador.obtener_filtros_disponibles(conn)

    return render_template(
        "convenios_lista.html",
        filas=filas, total=total, total_paginas=total_paginas, pagina=pagina,
        filtros=filtros, busqueda=busqueda, orden=orden, direccion=direccion,
        disponibles=disponibles,
    )


@bp.route("/convenios/<int:id_sistema>")
def ficha(id_sistema):
    conn = obtener_conexion()
    convenio = db_visualizador.obtener_convenio(conn, id_sistema)
    if convenio is None:
        abort(404)
    documentos = db_visualizador.obtener_documentos_de_convenio(conn, id_sistema)
    evidencias = db_visualizador.obtener_evidencias_de_convenio(conn, id_sistema)
    documentos_adenda = db_visualizador.obtener_adenda_documentos(conn, convenio["documento_adenda_ruta"])
    solicitud_origen = None
    if convenio["id_solicitud_origen"]:
        solicitud_origen = conn.execute(
            "SELECT id, codigo_solicitud FROM solicitudes WHERE id = ?", (convenio["id_solicitud_origen"],)
        ).fetchone()
    return render_template(
        "convenio_ficha.html",
        c=convenio, documentos=documentos, evidencias=evidencias, documentos_adenda=documentos_adenda,
        solicitud_origen=solicitud_origen,
    )


@bp.route("/proximos-a-vencer")
def proximos_a_vencer():
    conn = obtener_conexion()
    filas = db_visualizador.listar_proximos_a_vencer(conn, limite=500)
    return render_template("proximos_vencer.html", filas=filas)


@bp.route("/vencidos")
def vencidos():
    conn = obtener_conexion()
    filtros = {
        "anio": request.args.get("anio", type=int),
        "tipo": request.args.get("tipo") or None,
        "administrador": request.args.get("administrador") or None,
        "tiene_adenda": request.args.get("tiene_adenda") or None,
    }
    filas = db_visualizador.listar_vencidos(conn, filtros)
    disponibles = db_visualizador.obtener_filtros_disponibles(conn)
    return render_template("vencidos.html", filas=filas, filtros=filtros, disponibles=disponibles)


@bp.route("/revision-pendiente")
def revision_pendiente():
    conn = obtener_conexion()
    filas = db_visualizador.listar_revision_pendiente(conn)
    return render_template("revision_pendiente.html", filas=filas)


@bp.route("/abrir-documento")
def abrir_documento():
    ruta = request.args.get("ruta", "")
    config = obtener_config()
    try:
        apertura_archivos.abrir_archivo(ruta, config.ruta_base_convenios)
    except (apertura_archivos.RutaNoAutorizadaError, FileNotFoundError) as exc:
        return render_template("error_apertura.html", mensaje=str(exc)), 400
    return redirect(request.referrer or url_for("dashboard.inicio"))


@bp.route("/abrir-carpeta")
def abrir_carpeta():
    ruta = request.args.get("ruta", "")
    config = obtener_config()
    try:
        apertura_archivos.abrir_carpeta_contenedora(ruta, config.ruta_base_convenios)
    except (apertura_archivos.RutaNoAutorizadaError, FileNotFoundError) as exc:
        return render_template("error_apertura.html", mensaje=str(exc)), 400
    return redirect(request.referrer or url_for("dashboard.inicio"))
