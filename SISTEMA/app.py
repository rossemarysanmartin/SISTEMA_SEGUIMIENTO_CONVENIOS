"""Visualizador web de convenios UTMACH (Fase 4).

Aplicacion Flask local, de solo consulta sobre BASE_DATOS/convenios.db.
No modifica el repositorio documental original bajo ninguna circunstancia.

Ejecucion:
    python app.py
Luego abrir: http://127.0.0.1:5000
"""

import traceback

from flask import Flask, g, render_template, request
from werkzeug.exceptions import HTTPException

from config import cargar_config
from services.logger_app import obtener_logger


def crear_app():
    app = Flask(__name__)
    app.config["CONFIG_SISTEMA"] = cargar_config()
    # Solo protege la cookie de sesion usada por flash(); no hay autenticacion
    # todavia. Fijo (no aleatorio) para que los mensajes flash sobrevivan a
    # reinicios del proceso en desarrollo.
    app.secret_key = "utmach-convenios-fase5-dev"

    from routes.dashboard import bp as dashboard_bp
    from routes.convenios import bp as convenios_bp
    from routes.sincronizacion import bp as sincronizacion_bp
    from routes.solicitudes import bp as solicitudes_bp, pendientes_bp
    from routes.configuracion import bp as configuracion_bp
    from routes.busqueda import bp as busqueda_bp
    from routes.trabajo import bp as trabajo_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(convenios_bp)
    app.register_blueprint(sincronizacion_bp)
    app.register_blueprint(solicitudes_bp)
    app.register_blueprint(pendientes_bp)
    app.register_blueprint(configuracion_bp)
    app.register_blueprint(busqueda_bp)
    app.register_blueprint(trabajo_bp)

    @app.errorhandler(Exception)
    def manejar_error_inesperado(exc):
        if isinstance(exc, HTTPException):
            return exc  # 404, 400, etc: dejar que Flask los maneje normalmente
        logger = obtener_logger(app.config["CONFIG_SISTEMA"].ruta_logs)
        logger.error("Error en %s %s: %s\n%s", request.method, request.path, exc, traceback.format_exc())
        return render_template(
            "error_apertura.html",
            mensaje="No se pudo completar la operación. Revisa los datos e inténtalo nuevamente. "
                    "El detalle técnico quedó registrado en el log de la aplicación.",
        ), 500

    @app.teardown_appcontext
    def cerrar_conexion(_exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()
        conn_rw = g.pop("db_rw", None)
        if conn_rw is not None:
            conn_rw.close()

    @app.context_processor
    def inyectar_globales():
        return {
            "ICONOS_ESTADO": {
                "VIGENTE": "🟢", "PROXIMO_A_VENCER": "🟡", "VENCIDO": "🔴",
                "SIN_INFORMACION": "⚪", "REQUIERE_REVISION": "🟠", "POSIBLE_ADENDA": "🔵",
            },
            "ICONOS_ACTUACION": {
                "RECEPCION": "📩", "TRASLADO": "📤", "RECEPCION_EN_UNIDAD": "📥",
                "REVISION_INICIAL": "🔍", "DELEGACION": "👤",
                "SOLICITUD_DE_DOCUMENTACION": "📤", "DOCUMENTACION_RECIBIDA": "📥",
                "SOLICITUD_DE_CRITERIO": "📤", "CRITERIO_RECIBIDO": "📥",
                "SOLICITUD_DE_INFORME_JURIDICO": "📤", "INFORME_JURIDICO_RECIBIDO": "📥",
                "SOLICITUD_DE_FACTIBILIDAD": "📤", "FACTIBILIDAD_RECIBIDA": "📥",
                "ELABORACION_DE_BORRADOR": "📝", "REVISION_DE_BORRADOR": "📝",
                "ENVIO_A_CONTRAPARTE": "📤", "OBSERVACIONES_DE_CONTRAPARTE": "⚠️",
                "SUBSANACION": "🔧", "VALIDACION": "✅", "ENVIO_PARA_FIRMA": "✍️",
                "FIRMA_CONTRAPARTE": "✍️", "FIRMA_UTMACH": "✍️", "SUSCRIPCION": "🔗",
                "ARCHIVO": "🗄", "NO_PROCEDENTE": "❌", "SUSPENDIDO": "⏸",
                "CORRECCION": "✏️", "OTRO": "❔", "NOTA_INTERNA": "🗒",
            },
        }

    return app


app = crear_app()

if __name__ == "__main__":
    _config = cargar_config()
    print("Sistema de Seguimiento de Convenios UTMACH - Visualizador")
    print(f"Abrir en el navegador: http://{_config.app_host}:{_config.app_puerto}")
    app.run(host=_config.app_host, port=_config.app_puerto, debug=False)
