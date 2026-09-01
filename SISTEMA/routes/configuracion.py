from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from db_context import obtener_config
from routes.solicitudes import _conn
from services import catalogos_admin, configuracion as cfg_service
from services import exportar_dashboard_ejecutivo as export_dashboard

bp = Blueprint("configuracion", __name__, url_prefix="/configuracion")


@bp.route("")
def inicio():
    conn = _conn()
    config_efectiva = cfg_service.config_efectiva(conn, obtener_config())
    config_sistema = obtener_config()
    return render_template(
        "configuracion_inicio.html", config=config_efectiva,
        ruta_base_convenios=config_sistema.ruta_base_convenios,
        catalogos=catalogos_admin.CATALOGOS,
    )


@bp.route("/semaforo", methods=["GET", "POST"])
def semaforo():
    conn = _conn()
    config_efectiva = cfg_service.config_efectiva(conn, obtener_config())

    if request.method == "POST":
        try:
            normal = int(request.form["semaforo_normal_max"])
            atencion = int(request.form["semaforo_atencion_max"])
            demora = int(request.form["semaforo_demora_max"])
            umbral = int(request.form["umbral_dias_habiles_pendiente_respuesta"])
        except (ValueError, KeyError):
            flash("Todos los valores deben ser números enteros.", "error")
            return redirect(url_for("configuracion.semaforo"))

        if not (0 <= normal < atencion < demora):
            flash("Los umbrales deben ser crecientes: normal < atención < demora.", "error")
            return redirect(url_for("configuracion.semaforo"))

        cfg_service.guardar_valor(conn, "semaforo_normal_max", normal, "Configuración de semáforo")
        cfg_service.guardar_valor(conn, "semaforo_atencion_max", atencion, "Configuración de semáforo")
        cfg_service.guardar_valor(conn, "semaforo_demora_max", demora, "Configuración de semáforo")
        cfg_service.guardar_valor(conn, "umbral_dias_habiles_pendiente_respuesta", umbral, "Configuración de pendientes")
        flash("Configuración guardada.", "info")
        return redirect(url_for("configuracion.semaforo"))

    return render_template("configuracion_semaforo.html", config=config_efectiva)


@bp.route("/catalogos/<slug>")
def catalogo(slug):
    conn = _conn()
    if slug not in catalogos_admin.CATALOGOS:
        abort(404)
    filas = catalogos_admin.listar(conn, slug)
    return render_template(
        "configuracion_catalogo.html", slug=slug, titulo=catalogos_admin.CATALOGOS[slug]["titulo"],
        filas=filas, es_responsables=(slug == "responsables"),
        campo_editable=catalogos_admin.CATALOGOS[slug]["campo_editable"],
    )


@bp.route("/catalogos/<slug>/crear", methods=["POST"])
def catalogo_crear(slug):
    conn = _conn()
    if slug not in catalogos_admin.CATALOGOS:
        abort(404)
    campo = catalogos_admin.CATALOGOS[slug]["campo_editable"]
    valor = request.form.get(campo, "").strip()
    if not valor:
        flash("El nombre no puede quedar vacío.", "error")
        return redirect(url_for("configuracion.catalogo", slug=slug))
    datos = {campo: valor, "cargo": request.form.get("cargo"), "dependencia": request.form.get("dependencia")}
    catalogos_admin.crear(conn, slug, datos)
    flash("Elemento agregado.", "info")
    return redirect(url_for("configuracion.catalogo", slug=slug))


@bp.route("/catalogos/<slug>/<int:id_>/activar", methods=["POST"])
def catalogo_activar(slug, id_):
    catalogos_admin.cambiar_activo(_conn(), slug, id_, True)
    return redirect(url_for("configuracion.catalogo", slug=slug))


@bp.route("/catalogos/<slug>/<int:id_>/desactivar", methods=["POST"])
def catalogo_desactivar(slug, id_):
    catalogos_admin.cambiar_activo(_conn(), slug, id_, False)
    return redirect(url_for("configuracion.catalogo", slug=slug))


@bp.route("/catalogos/<slug>/<int:id_>/editar", methods=["POST"])
def catalogo_editar(slug, id_):
    nuevo_texto = request.form.get("texto", "").strip()
    if nuevo_texto:
        catalogos_admin.editar_texto(_conn(), slug, id_, nuevo_texto)
    return redirect(url_for("configuracion.catalogo", slug=slug))


@bp.route("/catalogos/<slug>/<int:id_>/mover/<direccion>", methods=["POST"])
def catalogo_mover(slug, id_, direccion):
    if direccion in ("subir", "bajar"):
        catalogos_admin.mover(_conn(), slug, id_, direccion)
    return redirect(url_for("configuracion.catalogo", slug=slug))


@bp.route("/dashboard-ejecutivo", methods=["POST"])
def generar_dashboard_ejecutivo():
    conn = _conn()
    config = obtener_config()
    config_efectiva = cfg_service.config_efectiva(conn, config)
    guardar_historico = request.form.get("guardar_historico") == "on"
    try:
        ruta = export_dashboard.generar_dashboard_ejecutivo(conn, config, config_efectiva, guardar_historico)
        flash(f"Dashboard ejecutivo generado: {ruta.name}", "info")
    except export_dashboard.DatosSensiblesError:
        flash("No se generó el dashboard: se detectó información no permitida en el contenido. Revise con soporte técnico.", "error")
    return redirect(url_for("configuracion.inicio"))
