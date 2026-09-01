"""Configuracion editable desde la interfaz (tabla `configuracion_app`).

CONFIGURACION/config.json sigue siendo la fuente de los valores POR DEFECTO
(instalacion inicial), pero el usuario ya no necesita editar el archivo a
mano: cualquier valor guardado desde la pantalla Configuracion se persiste en
la base de datos y tiene prioridad sobre el default del json.
"""

from datetime import datetime
from types import SimpleNamespace

from services import auditoria

CLAVES_SEMAFORO = {
    "semaforo_normal_max": "semaforo_normal_max",
    "semaforo_atencion_max": "semaforo_atencion_max",
    "semaforo_demora_max": "semaforo_demora_max",
    "umbral_dias_habiles_pendiente_respuesta": "umbral_dias_habiles_pendiente_respuesta",
}


def obtener_valor(conn, clave: str, default=None):
    fila = conn.execute("SELECT valor FROM configuracion_app WHERE clave = ?", (clave,)).fetchone()
    return fila["valor"] if fila else default


def guardar_valor(conn, clave: str, valor, actor_descripcion: str = None):
    anterior = obtener_valor(conn, clave)
    conn.execute(
        """INSERT INTO configuracion_app (clave, valor, fecha_actualizacion) VALUES (?, ?, ?)
           ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor, fecha_actualizacion = excluded.fecha_actualizacion""",
        (clave, str(valor), datetime.now().isoformat()),
    )
    if str(anterior) != str(valor):
        auditoria.registrar(conn, "CAMBIO_CONFIGURACION", "configuracion", None, anterior, valor,
                             actor_descripcion or clave)
    conn.commit()


def config_efectiva(conn, config):
    """Devuelve un objeto con los mismos atributos que `Config` (semaforo_*,
    umbral_dias_habiles_pendiente_respuesta), pero con cualquier override
    guardado en base de datos aplicado encima del valor de config.json."""
    valores = {}
    for atributo in CLAVES_SEMAFORO.values():
        crudo = obtener_valor(conn, atributo)
        valores[atributo] = int(crudo) if crudo is not None else getattr(config, atributo)
    return SimpleNamespace(**valores)
