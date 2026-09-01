"""
Guardas de seguridad para proteger el repositorio documental original.

El repositorio de convenios (RUTA_BASE_CONVENIOS) es de SOLO LECTURA para
todo este sistema. Ningun modulo debe escribir, mover, renombrar ni borrar
nada dentro de esa ruta. Estas funciones existen para detener con una
excepcion cualquier intento accidental de hacerlo, en vez de fallar en
silencio.
"""

from pathlib import Path


class ViolacionSoloLecturaError(Exception):
    """Se lanza si algun modulo intenta escribir dentro del repositorio original."""


def verificar_ruta_escritura_segura(ruta_destino: Path, ruta_base_convenios: Path) -> None:
    """Lanza ViolacionSoloLecturaError si ruta_destino cae dentro de ruta_base_convenios,
    salvo que sea dentro de la subcarpeta SISTEMA_SEGUIMIENTO_CONVENIOS (que es nuestra)."""
    ruta_destino = Path(ruta_destino).resolve()
    ruta_base_convenios = Path(ruta_base_convenios).resolve()
    carpeta_sistema = ruta_base_convenios / "SISTEMA_SEGUIMIENTO_CONVENIOS"

    try:
        dentro_de_base = ruta_destino.is_relative_to(ruta_base_convenios)
    except AttributeError:  # Python <3.9 fallback, no aplica aqui pero por seguridad
        dentro_de_base = str(ruta_destino).startswith(str(ruta_base_convenios))

    if dentro_de_base:
        try:
            dentro_de_sistema = ruta_destino.is_relative_to(carpeta_sistema)
        except AttributeError:
            dentro_de_sistema = str(ruta_destino).startswith(str(carpeta_sistema))

        if not dentro_de_sistema:
            raise ViolacionSoloLecturaError(
                f"Intento de escritura bloqueado dentro del repositorio original: {ruta_destino}"
            )
