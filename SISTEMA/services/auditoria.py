"""Registro centralizado de auditoria (tabla `auditoria`).

Toda escritura de negocio relevante (cambio de estado, responsable,
delegacion, vinculacion con convenio, anulacion logica) debe pasar por
`registrar` en vez de insertar directamente, para que quede un unico punto de
verdad sobre el formato del registro de auditoria.
"""

from datetime import datetime

from services.current_actor import obtener_actor_actual


def registrar(conn, accion: str, entidad: str, id_entidad, valor_anterior=None, valor_nuevo=None, descripcion=None):
    ahora = datetime.now()
    conn.execute(
        """INSERT INTO auditoria (fecha, hora, accion, entidad, id_entidad, valor_anterior, valor_nuevo, usuario, descripcion)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            ahora.date().isoformat(), ahora.time().isoformat(timespec="seconds"),
            accion, entidad, id_entidad,
            str(valor_anterior) if valor_anterior is not None else None,
            str(valor_nuevo) if valor_nuevo is not None else None,
            obtener_actor_actual(), descripcion,
        ),
    )


def listar_por_entidad(conn, entidad: str, id_entidad: int):
    return conn.execute(
        "SELECT * FROM auditoria WHERE entidad = ? AND id_entidad = ? ORDER BY id DESC",
        (entidad, id_entidad),
    ).fetchall()
