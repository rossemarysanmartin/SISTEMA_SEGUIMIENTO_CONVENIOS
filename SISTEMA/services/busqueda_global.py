"""Busqueda global combinada: convenios + solicitudes, diferenciados en el
resultado (seccion 22 de la especificacion de Fase 6)."""

_EXPR_SIN_TILDES = (
    "REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LOWER({col}),"
    "'á','a'),'é','e'),'í','i'),'ó','o'),'ú','u'),'ñ','n')"
)


def _normalizar(texto: str) -> str:
    equivalencias = str.maketrans("áéíóúÁÉÍÓÚñÑ", "aeiouAEIOUnN")
    return texto.translate(equivalencias).lower()


def buscar(conn, texto: str, limite: int = 15):
    if not texto or not texto.strip():
        return {"convenios": [], "solicitudes": []}
    termino = f"%{_normalizar(texto)}%"

    convenios = conn.execute(
        f"""SELECT id_sistema, anio, codigo_original, institucion, tipo_instrumento, estado_vigencia
            FROM convenios
            WHERE clasificacion_general='CONVENIO' AND (
                  {_EXPR_SIN_TILDES.format(col="institucion")} LIKE ?
               OR {_EXPR_SIN_TILDES.format(col="COALESCE(codigo_original,'')")} LIKE ?
               OR CAST(anio AS TEXT) LIKE ?
            )
            LIMIT ?""",
        (termino, termino, f"%{texto}%", limite),
    ).fetchall()

    solicitudes = conn.execute(
        f"""SELECT id, codigo_solicitud, institucion, estado_actual, etapa_actual
            FROM solicitudes
            WHERE activo=1 AND (
                  {_EXPR_SIN_TILDES.format(col="institucion")} LIKE ?
               OR {_EXPR_SIN_TILDES.format(col="codigo_solicitud")} LIKE ?
               OR CAST(anio AS TEXT) LIKE ?
            )
            LIMIT ?""",
        (termino, termino, f"%{texto}%", limite),
    ).fetchall()

    return {"convenios": convenios, "solicitudes": solicitudes}
