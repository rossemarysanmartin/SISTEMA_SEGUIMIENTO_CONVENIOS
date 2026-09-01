from datetime import date, datetime

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from db_context import obtener_config
from services import apertura_archivos, configuracion as cfg_service, repositorio_solicitudes as repo

bp = Blueprint("solicitudes", __name__, url_prefix="/solicitudes")

# ------------------------------------------------------------ acciones rapidas --
# Cada accion rapida es un formulario reducido y contextual (seccion 4 de la
# especificacion): el usuario solo ve los campos listados en "campos"; todo lo
# demas (tipo de actuacion, estado/etapa sugeridos, requiere_respuesta) se
# completa automaticamente pero SIGUE SIENDO EDITABLE desde "Mas opciones" en
# la ficha completa -- estas son sugerencias, no automatismos irreversibles.
ACCIONES_RAPIDAS = {
    "delegar": {
        "titulo": "Delegar", "icono": "👤", "tipo_actuacion": "DELEGACION",
        "campos": ["delegado", "fecha", "descripcion"],
        "estado_sugerido": None, "etapa_sugerida": None, "requiere_respuesta_defecto": False,
    },
    "criterio": {
        "titulo": "Solicitar criterio", "icono": "📤", "tipo_actuacion": "SOLICITUD_DE_CRITERIO",
        "campos": ["dependencia_destino", "fecha", "responsable", "fecha_limite_respuesta", "descripcion"],
        "estado_sugerido": "PENDIENTE_DE_CRITERIO", "etapa_sugerida": "CRITERIOS", "requiere_respuesta_defecto": True,
    },
    "factibilidad": {
        "titulo": "Solicitar factibilidad", "icono": "📤", "tipo_actuacion": "SOLICITUD_DE_FACTIBILIDAD",
        "campos": ["dependencia_destino", "fecha", "responsable", "fecha_limite_respuesta", "descripcion"],
        "estado_sugerido": "PENDIENTE_DE_RESPUESTA", "etapa_sugerida": "FACTIBILIDAD", "requiere_respuesta_defecto": True,
    },
    "juridico": {
        "titulo": "Enviar a jurídico", "icono": "📤", "tipo_actuacion": "SOLICITUD_DE_INFORME_JURIDICO",
        "campos": ["dependencia_destino", "fecha", "responsable", "fecha_limite_respuesta", "descripcion"],
        "estado_sugerido": "EN_REVISION_JURIDICA", "etapa_sugerida": "REVISION_JURIDICA", "requiere_respuesta_defecto": True,
    },
    "contraparte": {
        "titulo": "Enviar a contraparte", "icono": "📤", "tipo_actuacion": "ENVIO_A_CONTRAPARTE",
        "campos": ["fecha", "responsable", "descripcion"],
        "estado_sugerido": "EN_CONTRAPARTE", "etapa_sugerida": "CONTRAPARTE", "requiere_respuesta_defecto": False,
    },
    "firma": {
        "titulo": "Enviar a firma", "icono": "✍️", "tipo_actuacion": "ENVIO_PARA_FIRMA",
        "campos": ["fecha", "responsable", "descripcion"],
        "estado_sugerido": "EN_FIRMA", "etapa_sugerida": "FIRMA", "requiere_respuesta_defecto": False,
    },
    "suscrito": {
        "titulo": "Marcar suscrito", "icono": "🔗", "tipo_actuacion": "SUSCRIPCION",
        "campos": ["fecha", "descripcion"],
        "estado_sugerido": "SUSCRITO", "etapa_sugerida": "SUSCRITO", "requiere_respuesta_defecto": False,
    },
    "nota": {
        "titulo": "Nota interna", "icono": "🗒", "tipo_actuacion": "NOTA_INTERNA",
        "campos": ["fecha", "descripcion"],
        "estado_sugerido": None, "etapa_sugerida": None, "requiere_respuesta_defecto": False,
    },
}

# Al registrar una respuesta desde un pendiente abierto, se sugiere el tipo de
# actuacion "recibido" correspondiente al tipo que se envio originalmente.
MAPA_RESPUESTA = {
    "SOLICITUD_DE_CRITERIO": "CRITERIO_RECIBIDO",
    "SOLICITUD_DE_INFORME_JURIDICO": "INFORME_JURIDICO_RECIBIDO",
    "SOLICITUD_DE_FACTIBILIDAD": "FACTIBILIDAD_RECIBIDA",
    "SOLICITUD_DE_DOCUMENTACION": "DOCUMENTACION_RECIBIDA",
}

# Filtro simple de la linea de tiempo (seccion 18): agrupa tipos de actuacion
# en categorias amplias para no complicar la interfaz con un filtro por cada
# uno de los ~28 tipos posibles.
FILTROS_TIMELINE = {
    "criterios": {"SOLICITUD_DE_CRITERIO", "CRITERIO_RECIBIDO", "SOLICITUD_DE_INFORME_JURIDICO",
                  "INFORME_JURIDICO_RECIBIDO", "SOLICITUD_DE_FACTIBILIDAD", "FACTIBILIDAD_RECIBIDA"},
    "documentacion": {"SOLICITUD_DE_DOCUMENTACION", "DOCUMENTACION_RECIBIDA"},
    "delegaciones": {"DELEGACION"},
    "firma": {"ENVIO_PARA_FIRMA", "FIRMA_CONTRAPARTE", "FIRMA_UTMACH", "SUSCRIPCION"},
    "sistema": {"RECEPCION", "TRASLADO", "RECEPCION_EN_UNIDAD", "REVISION_INICIAL", "ARCHIVO",
                "CORRECCION", "NOTA_INTERNA", "OTRO", "NO_PROCEDENTE", "SUSPENDIDO"},
}


def _conn():
    """Conexion de lectura/escritura para el modulo de solicitudes, cacheada
    en el contexto de la peticion (igual patron que db_context.obtener_conexion,
    pero con permiso de escritura)."""
    if "db_rw" not in g:
        config = obtener_config()
        g.db_rw = repo.conectar_escritura(config.ruta_convenios_db, config.ruta_base_convenios)
    return g.db_rw


@bp.route("")
def lista():
    conn = _conn()
    config = cfg_service.config_efectiva(conn, obtener_config())
    filtros = {
        "anio": request.args.get("anio", type=int),
        "institucion": request.args.get("institucion") or None,
        "medio_ingreso": request.args.get("medio_ingreso") or None,
        "responsable_actual": request.args.get("responsable_actual") or None,
        "delegado_actual": request.args.get("delegado_actual") or None,
        "estado_actual": request.args.get("estado_actual") or None,
        "etapa_actual": request.args.get("etapa_actual") or None,
        "tipo_convenio_solicitado": request.args.get("tipo_convenio_solicitado") or None,
        "dependencia_solicitante": request.args.get("dependencia_solicitante") or None,
        "con_respuesta_pendiente": request.args.get("con_respuesta_pendiente") or None,
        "dias_sin_movimiento_min": request.args.get("dias_sin_movimiento_min", type=int),
    }
    busqueda = request.args.get("q", "").strip()
    orden = request.args.get("orden", "fecha_ingreso")
    direccion = request.args.get("dir", "desc")
    pagina = request.args.get("pagina", 1, type=int)

    filas, total, total_paginas = repo.listar_solicitudes(conn, filtros, busqueda, orden, direccion, pagina)
    contadores = repo.contadores_dashboard_solicitudes(conn, config)
    estados = repo.listar_catalogo(conn, "catalogo_estados_solicitud")
    etapas = repo.listar_catalogo(conn, "catalogo_etapas_solicitud")
    medios = repo.listar_catalogo(conn, "catalogo_medios_ingreso")

    filas_con_semaforo = []
    for f in filas:
        dias = repo.dias_desde(f["fecha_ultima_actuacion"])
        pendiente_actual = repo.calcular_pendiente_actual(repo.obtener_pendientes_abiertos(conn, f["id"]))
        filas_con_semaforo.append({
            **dict(f), "dias_sin_movimiento_vivo": dias, "semaforo": repo.calcular_semaforo(dias, config),
            "pendiente_actual": pendiente_actual,
        })

    return render_template(
        "solicitudes_lista.html", filas=filas_con_semaforo, total=total, total_paginas=total_paginas,
        pagina=pagina, filtros=filtros, busqueda=busqueda, orden=orden, direccion=direccion,
        contadores=contadores, estados=estados, etapas=etapas, medios=medios, config=config,
    )


@bp.route("/tablero")
def tablero():
    conn = _conn()
    config = cfg_service.config_efectiva(conn, obtener_config())
    columnas = repo.tablero_kanban(conn)
    for columna in columnas:
        columna["solicitudes"] = [
            {**dict(s), "semaforo": repo.calcular_semaforo(repo.dias_desde(s["fecha_ultima_actuacion"]), config)}
            for s in columna["solicitudes"]
        ]
    return render_template("solicitudes_tablero.html", columnas=columnas)


@bp.route("/nueva", methods=["GET", "POST"])
def nueva():
    conn = _conn()
    medios = repo.listar_catalogo(conn, "catalogo_medios_ingreso")
    dependencias = repo.listar_catalogo(conn, "catalogo_dependencias")
    tipos_convenio = repo.listar_catalogo(conn, "catalogo_tipos_convenio_solicitado")
    responsables = repo.listar_catalogo(conn, "responsables")

    if request.method == "POST":
        responsable_inicial = request.form.get("responsable_inicial") or None
        datos = {
            "fecha_ingreso": request.form.get("fecha_ingreso") or date.today().isoformat(),
            "hora_ingreso": request.form.get("hora_ingreso") or None,
            "institucion": request.form.get("institucion", "").strip(),
            "persona_contacto": request.form.get("persona_contacto") or None,
            "correo_contacto": request.form.get("correo_contacto") or None,
            "asunto": request.form.get("asunto") or None,
            "tipo_convenio_solicitado": request.form.get("tipo_convenio_solicitado") or None,
            "dependencia_solicitante": request.form.get("dependencia_solicitante") or None,
            "medio_ingreso": request.form.get("medio_ingreso"),
            "observaciones": request.form.get("observaciones") or None,
            "numero_tramite_institucional": request.form.get("numero_tramite_institucional") or None,
            "referencia_correo": request.form.get("referencia_correo") or None,
            "fecha_correo": request.form.get("fecha_correo") or None,
            "remitente_correo": request.form.get("remitente_correo") or None,
            "registrado_por": request.form.get("registrado_por") or None,
            "responsable_actual": responsable_inicial,
            "responsable_inicial": responsable_inicial,
        }
        if not datos["institucion"] or not datos["medio_ingreso"]:
            flash("Institución y medio de ingreso son obligatorios.", "error")
            return render_template("solicitud_nueva.html", medios=medios, dependencias=dependencias,
                                    tipos_convenio=tipos_convenio, responsables=responsables, datos=datos)

        recibido = request.form.get("recibido_en_vinculacion") == "on"
        creada = repo.crear_solicitud(conn, datos, recibido_en_vinculacion=recibido)
        return redirect(url_for("solicitudes.ficha", id_solicitud=creada["id"]))

    return render_template("solicitud_nueva.html", medios=medios, dependencias=dependencias,
                            tipos_convenio=tipos_convenio, responsables=responsables, datos={})


@bp.route("/<int:id_solicitud>")
def ficha(id_solicitud):
    conn = _conn()
    config = cfg_service.config_efectiva(conn, obtener_config())
    solicitud = repo.obtener_solicitud(conn, id_solicitud)
    if solicitud is None:
        abort(404)
    actuaciones = repo.obtener_actuaciones(conn, id_solicitud)
    filtro_timeline = request.args.get("filtro_timeline", "todas")
    if filtro_timeline in FILTROS_TIMELINE:
        tipos_incluidos = FILTROS_TIMELINE[filtro_timeline]
        actuaciones_mostradas = [a for a in actuaciones if a["tipo_actuacion"] in tipos_incluidos]
    else:
        actuaciones_mostradas = actuaciones
    documentos = repo.obtener_documentos_tramite(conn, id_solicitud)
    dias = repo.dias_desde(solicitud["fecha_ultima_actuacion"])
    semaforo = repo.calcular_semaforo(dias, config)

    pendientes_abiertos = repo.obtener_pendientes_abiertos(conn, id_solicitud)
    pendiente_actual = repo.calcular_pendiente_actual(pendientes_abiertos)

    resultados_convenio = []
    buscar_convenio = request.args.get("buscar_convenio", "").strip()
    if buscar_convenio:
        resultados_convenio = repo.buscar_convenios_para_vincular(conn, buscar_convenio)

    convenio_vinculado = None
    if solicitud["id_convenio_suscrito"]:
        convenio_vinculado = conn.execute(
            "SELECT id_sistema, anio, codigo_original, institucion FROM convenios WHERE id_sistema=?",
            (solicitud["id_convenio_suscrito"],),
        ).fetchone()

    catalogo_actuaciones = repo.listar_catalogo(conn, "catalogo_actuaciones")
    catalogo_estados = repo.listar_catalogo(conn, "catalogo_estados_solicitud")
    catalogo_etapas = repo.listar_catalogo(conn, "catalogo_etapas_solicitud")
    catalogo_dependencias = repo.listar_catalogo(conn, "catalogo_dependencias")

    return render_template(
        "solicitud_ficha.html", s=solicitud, actuaciones=actuaciones_mostradas,
        total_actuaciones=len(actuaciones), filtro_timeline=filtro_timeline, documentos=documentos,
        dias_sin_movimiento=dias, semaforo=semaforo,
        pendientes_abiertos=pendientes_abiertos, pendiente_actual=pendiente_actual,
        resultados_convenio=resultados_convenio, buscar_convenio=buscar_convenio,
        convenio_vinculado=convenio_vinculado, catalogo_actuaciones=catalogo_actuaciones,
        catalogo_estados=catalogo_estados, catalogo_etapas=catalogo_etapas,
        catalogo_dependencias=catalogo_dependencias, acciones_rapidas=ACCIONES_RAPIDAS,
    )


@bp.route("/<int:id_solicitud>/actuacion", methods=["POST"])
def registrar_actuacion(id_solicitud):
    conn = _conn()
    solicitud = repo.obtener_solicitud(conn, id_solicitud)
    if solicitud is None:
        abort(404)

    datos = {
        "tipo_actuacion": request.form.get("tipo_actuacion"),
        "fecha": request.form.get("fecha") or date.today().isoformat(),
        "hora": request.form.get("hora") or None,
        "dependencia_origen": request.form.get("dependencia_origen") or None,
        "dependencia_destino": request.form.get("dependencia_destino") or None,
        "responsable": request.form.get("responsable") or None,
        "delegado": request.form.get("delegado") or None,
        "descripcion": request.form.get("descripcion") or None,
        "resultado": request.form.get("resultado") or None,
        "estado_nuevo": request.form.get("estado_nuevo") or None,
        "etapa_nueva": request.form.get("etapa_nueva") or None,
        "requiere_respuesta": "SI" if request.form.get("requiere_respuesta") == "on" else "NO",
        "fecha_limite_respuesta": request.form.get("fecha_limite_respuesta") or None,
        "observaciones": request.form.get("observaciones") or None,
        "documento_asociado": request.form.get("documento_asociado") or None,
    }
    id_relacionada = request.form.get("id_actuacion_relacionada", type=int)
    if id_relacionada:
        datos["id_actuacion_relacionada"] = id_relacionada
        datos["respuesta_recibida"] = "SI"
        datos["fecha_respuesta"] = datos["fecha"]

    if not datos["tipo_actuacion"]:
        flash("Debe seleccionar un tipo de actuación.", "error")
        return redirect(url_for("solicitudes.ficha", id_solicitud=id_solicitud))

    repo.registrar_actuacion(conn, id_solicitud, datos)

    ruta_doc = request.form.get("ruta_documento") or None
    if ruta_doc:
        config = obtener_config()
        repo.registrar_documento_tramite(conn, id_solicitud, {
            "nombre": ruta_doc.split("\\")[-1].split("/")[-1],
            "ruta": ruta_doc,
            "tipo": request.form.get("tipo_actuacion"),
            "fecha": datos["fecha"],
        }, ruta_base_convenios=config.ruta_base_convenios)

    return redirect(url_for("solicitudes.ficha", id_solicitud=id_solicitud))


@bp.route("/<int:id_solicitud>/rapida/<accion>", methods=["GET", "POST"])
def accion_rapida(id_solicitud, accion):
    conn = _conn()
    solicitud = repo.obtener_solicitud(conn, id_solicitud)
    if solicitud is None:
        abort(404)
    preset = ACCIONES_RAPIDAS.get(accion)
    if preset is None:
        abort(404)

    if request.method == "POST":
        datos = {
            "tipo_actuacion": preset["tipo_actuacion"],
            "fecha": request.form.get("fecha") or date.today().isoformat(),
            "hora": datetime.now().strftime("%H:%M"),
            "dependencia_destino": request.form.get("dependencia_destino") or None,
            "responsable": request.form.get("responsable") or solicitud["responsable_actual"],
            "delegado": request.form.get("delegado") or None,
            "descripcion": request.form.get("descripcion") or None,
            "fecha_limite_respuesta": request.form.get("fecha_limite_respuesta") or None,
            "estado_nuevo": request.form.get("estado_nuevo") or preset["estado_sugerido"],
            "etapa_nueva": request.form.get("etapa_nueva") or preset["etapa_sugerida"],
            "requiere_respuesta": "SI" if preset["requiere_respuesta_defecto"] else "NO",
        }
        repo.registrar_actuacion(conn, id_solicitud, datos)
        flash(f"{preset['titulo']} registrado.", "info")
        return redirect(url_for("solicitudes.ficha", id_solicitud=id_solicitud))

    catalogo_dependencias = repo.listar_catalogo(conn, "catalogo_dependencias")
    return render_template(
        "solicitud_accion_rapida.html", s=solicitud, accion=accion, preset=preset,
        catalogo_dependencias=catalogo_dependencias, hoy=date.today().isoformat(),
    )


@bp.route("/<int:id_solicitud>/responder/<int:id_actuacion>", methods=["GET", "POST"])
def responder(id_solicitud, id_actuacion):
    """Registrar respuesta en un clic (seccion 16): parte de una actuacion
    pendiente concreta -- el usuario nunca tiene que volver a buscar cual
    solicitud de criterio/informe/factibilidad esta respondiendo."""
    conn = _conn()
    solicitud = repo.obtener_solicitud(conn, id_solicitud)
    original = conn.execute("SELECT * FROM actuaciones_solicitud WHERE id=? AND id_solicitud=?",
                             (id_actuacion, id_solicitud)).fetchone()
    if solicitud is None or original is None:
        abort(404)

    tipo_respuesta = MAPA_RESPUESTA.get(original["tipo_actuacion"], "OTRO")

    if request.method == "POST":
        datos = {
            "tipo_actuacion": tipo_respuesta,
            "fecha": request.form.get("fecha") or date.today().isoformat(),
            "hora": datetime.now().strftime("%H:%M"),
            "dependencia_origen": original["dependencia_destino"],
            "resultado": request.form.get("resultado") or None,
            "descripcion": request.form.get("descripcion") or None,
            "estado_nuevo": request.form.get("estado_nuevo") or None,
            "etapa_nueva": request.form.get("etapa_nueva") or None,
            "id_actuacion_relacionada": id_actuacion,
            "respuesta_recibida": "SI",
            "fecha_respuesta": request.form.get("fecha") or date.today().isoformat(),
        }
        repo.registrar_actuacion(conn, id_solicitud, datos)
        flash("Respuesta registrada.", "info")
        return redirect(url_for("solicitudes.ficha", id_solicitud=id_solicitud))

    catalogo_estados = repo.listar_catalogo(conn, "catalogo_estados_solicitud")
    catalogo_etapas = repo.listar_catalogo(conn, "catalogo_etapas_solicitud")
    return render_template(
        "solicitud_responder.html", s=solicitud, original=original, tipo_respuesta=tipo_respuesta,
        catalogo_estados=catalogo_estados, catalogo_etapas=catalogo_etapas, hoy=date.today().isoformat(),
    )


@bp.route("/<int:id_solicitud>/editar", methods=["GET", "POST"])
def editar(id_solicitud):
    conn = _conn()
    solicitud = repo.obtener_solicitud(conn, id_solicitud)
    if solicitud is None:
        abort(404)

    if request.method == "POST":
        campos = {
            "institucion": request.form.get("institucion", "").strip(),
            "asunto": request.form.get("asunto") or None,
            "persona_contacto": request.form.get("persona_contacto") or None,
            "correo_contacto": request.form.get("correo_contacto") or None,
            "tipo_convenio_solicitado": request.form.get("tipo_convenio_solicitado") or None,
            "observaciones": request.form.get("observaciones") or None,
        }
        if not campos["institucion"]:
            flash("La institución no puede quedar vacía.", "error")
            return render_template("solicitud_editar.html", s=solicitud,
                                    tipos_convenio=repo.listar_catalogo(conn, "catalogo_tipos_convenio_solicitado"))
        repo.editar_solicitud(conn, id_solicitud, campos)
        flash("Solicitud actualizada.", "info")
        return redirect(url_for("solicitudes.ficha", id_solicitud=id_solicitud))

    tipos_convenio = repo.listar_catalogo(conn, "catalogo_tipos_convenio_solicitado")
    return render_template("solicitud_editar.html", s=solicitud, tipos_convenio=tipos_convenio)


@bp.route("/<int:id_solicitud>/reactivar", methods=["POST"])
def reactivar(id_solicitud):
    conn = _conn()
    motivo = request.form.get("motivo", "Sin motivo especificado")
    repo.reactivar_solicitud(conn, id_solicitud, motivo)
    flash("Solicitud reactivada.", "info")
    return redirect(url_for("solicitudes.ficha", id_solicitud=id_solicitud))


@bp.route("/<int:id_solicitud>/vincular-convenio", methods=["POST"])
def vincular_convenio(id_solicitud):
    conn = _conn()
    id_convenio = request.form.get("id_convenio", type=int)
    if not id_convenio:
        flash("Debe seleccionar un convenio.", "error")
        return redirect(url_for("solicitudes.ficha", id_solicitud=id_solicitud))
    repo.vincular_convenio(conn, id_solicitud, id_convenio)
    return redirect(url_for("solicitudes.ficha", id_solicitud=id_solicitud))


@bp.route("/<int:id_solicitud>/desactivar", methods=["POST"])
def desactivar(id_solicitud):
    conn = _conn()
    motivo = request.form.get("motivo", "Sin motivo especificado")
    repo.desactivar_solicitud(conn, id_solicitud, motivo)
    return redirect(url_for("solicitudes.lista"))


@bp.route("/<int:id_solicitud>/corregir/<int:id_actuacion>", methods=["POST"])
def corregir_actuacion(id_solicitud, id_actuacion):
    conn = _conn()
    motivo = request.form.get("motivo", "").strip()
    if not motivo:
        flash("Debe indicar el motivo de la corrección.", "error")
        return redirect(url_for("solicitudes.ficha", id_solicitud=id_solicitud))
    repo.registrar_correccion(conn, id_solicitud, id_actuacion, motivo)
    return redirect(url_for("solicitudes.ficha", id_solicitud=id_solicitud))


@bp.route("/informes")
def informes():
    conn = _conn()
    return render_template(
        "solicitudes_informes.html",
        por_mes=repo.informe_por_mes(conn),
        por_medio=repo.informe_por_medio_ingreso(conn),
        por_responsable=repo.informe_por_responsable(conn),
        por_estado=repo.informe_por_estado(conn),
        por_etapa=repo.informe_por_etapa(conn),
        por_semana=repo.informe_ingresadas_por_semana(conn),
        abiertas_cerradas=repo.informe_abiertas_cerradas(conn),
        tiempo_primera_actuacion=repo.informe_tiempo_promedio_primera_actuacion(conn),
        tiempo_total=repo.informe_tiempo_promedio_total(conn),
        pendientes_por_dependencia=repo.informe_pendientes_por_dependencia(conn),
        carga_por_responsable=repo.informe_carga_por_responsable(conn),
    )


@bp.route("/exportar-excel", methods=["POST"])
def exportar_excel():
    from services.exportar_excel_solicitudes import generar_excel_solicitudes
    config = obtener_config()
    generar_excel_solicitudes(config.ruta_convenios_db, config.ruta_excel_solicitudes)
    return redirect(url_for("solicitudes.lista"))


pendientes_bp = Blueprint("pendientes", __name__)


@pendientes_bp.route("/pendientes-de-respuesta")
def pendientes_de_respuesta():
    conn = _conn()
    config = cfg_service.config_efectiva(conn, obtener_config())
    pendientes = repo.pendientes_de_respuesta(conn, config.umbral_dias_habiles_pendiente_respuesta)
    return render_template("pendientes_respuesta.html", pendientes=pendientes,
                           umbral=config.umbral_dias_habiles_pendiente_respuesta)
