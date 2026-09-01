"""Administracion generica de catalogos (Configuracion -> Catalogos).

Nunca borra fisicamente un valor ya usado -- solo activa/desactiva, permite
editar el texto visible y reordenar. Los nombres de tabla/columna vienen de
una lista blanca fija (CATALOGOS) para poder construir SQL seguro sin
concatenar entrada de usuario en la sentencia.
"""

from services import auditoria

CATALOGOS = {
    "medios_ingreso": {
        "tabla": "catalogo_medios_ingreso", "titulo": "Medios de ingreso",
        "campo_editable": "etiqueta", "tiene_icono": True,
    },
    "actuaciones": {
        "tabla": "catalogo_actuaciones", "titulo": "Tipos de actuación",
        "campo_editable": "etiqueta", "tiene_icono": False,
    },
    "estados": {
        "tabla": "catalogo_estados_solicitud", "titulo": "Estados de solicitud",
        "campo_editable": "etiqueta", "tiene_icono": False,
    },
    "etapas": {
        "tabla": "catalogo_etapas_solicitud", "titulo": "Etapas",
        "campo_editable": "etiqueta", "tiene_icono": False,
    },
    "dependencias": {
        "tabla": "catalogo_dependencias", "titulo": "Dependencias",
        "campo_editable": "nombre", "tiene_icono": False,
    },
    "tipos_convenio": {
        "tabla": "catalogo_tipos_convenio_solicitado", "titulo": "Tipos de convenio solicitado",
        "campo_editable": "nombre", "tiene_icono": False,
    },
    "responsables": {
        "tabla": "responsables", "titulo": "Responsables",
        "campo_editable": "nombre", "tiene_icono": False,
    },
}


def _config(slug: str) -> dict:
    if slug not in CATALOGOS:
        raise ValueError(f"Catálogo desconocido: {slug}")
    return CATALOGOS[slug]


def listar(conn, slug: str):
    cfg = _config(slug)
    return conn.execute(f"SELECT * FROM {cfg['tabla']} ORDER BY COALESCE(orden, id), id").fetchall()


def cambiar_activo(conn, slug: str, id_: int, activo: bool):
    cfg = _config(slug)
    conn.execute(f"UPDATE {cfg['tabla']} SET activo = ? WHERE id = ?", (1 if activo else 0, id_))
    auditoria.registrar(conn, "ACTIVAR" if activo else "DESACTIVAR", f"catalogo:{slug}", id_)
    conn.commit()


def editar_texto(conn, slug: str, id_: int, nuevo_texto: str):
    cfg = _config(slug)
    campo = cfg["campo_editable"]
    anterior = conn.execute(f"SELECT {campo} FROM {cfg['tabla']} WHERE id = ?", (id_,)).fetchone()
    conn.execute(f"UPDATE {cfg['tabla']} SET {campo} = ? WHERE id = ?", (nuevo_texto, id_))
    if anterior and anterior[0] != nuevo_texto:
        auditoria.registrar(conn, "EDICION", f"catalogo:{slug}", id_, anterior[0], nuevo_texto)
    conn.commit()


def mover(conn, slug: str, id_: int, direccion: str):
    """direccion: 'subir' o 'bajar'. Intercambia el 'orden' con el vecino."""
    cfg = _config(slug)
    tabla = cfg["tabla"]
    filas = conn.execute(f"SELECT id, orden FROM {tabla} ORDER BY COALESCE(orden, id), id").fetchall()
    posicion = next((i for i, f in enumerate(filas) if f["id"] == id_), None)
    if posicion is None:
        return
    vecino = posicion - 1 if direccion == "subir" else posicion + 1
    if vecino < 0 or vecino >= len(filas):
        return
    a, b = filas[posicion], filas[vecino]
    orden_a = a["orden"] if a["orden"] is not None else posicion
    orden_b = b["orden"] if b["orden"] is not None else vecino
    conn.execute(f"UPDATE {tabla} SET orden = ? WHERE id = ?", (orden_b, a["id"]))
    conn.execute(f"UPDATE {tabla} SET orden = ? WHERE id = ?", (orden_a, b["id"]))
    conn.commit()


def crear(conn, slug: str, datos: dict):
    cfg = _config(slug)
    tabla = cfg["tabla"]
    campo = cfg["campo_editable"]
    maximo_orden = conn.execute(f"SELECT MAX(COALESCE(orden, 0)) FROM {tabla}").fetchone()[0] or 0

    if slug == "responsables":
        conn.execute(
            "INSERT INTO responsables (nombre, cargo, dependencia, orden) VALUES (?, ?, ?, ?)",
            (datos["nombre"], datos.get("cargo"), datos.get("dependencia"), maximo_orden + 1),
        )
    elif cfg.get("tiene_icono"):
        codigo = datos.get("codigo") or datos[campo].upper().replace(" ", "_")
        conn.execute(
            f"INSERT INTO {tabla} (codigo, {campo}, icono, orden) VALUES (?, ?, ?, ?)",
            (codigo, datos[campo], datos.get("icono"), maximo_orden + 1),
        )
    elif "codigo" in {f[1] for f in conn.execute(f"PRAGMA table_info({tabla})")}:
        codigo = datos.get("codigo") or datos[campo].upper().replace(" ", "_")
        conn.execute(f"INSERT INTO {tabla} (codigo, {campo}, orden) VALUES (?, ?, ?)", (codigo, datos[campo], maximo_orden + 1))
    else:
        conn.execute(f"INSERT INTO {tabla} ({campo}, orden) VALUES (?, ?)", (datos[campo], maximo_orden + 1))

    auditoria.registrar(conn, "CREAR", f"catalogo:{slug}", None, None, datos.get(campo) or datos.get("nombre"))
    conn.commit()
