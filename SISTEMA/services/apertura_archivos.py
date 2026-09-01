"""Apertura segura de archivos/carpetas del repositorio documental original.

Unica funcion central autorizada a invocar os.startfile desde el visualizador.
Valida SIEMPRE que la ruta solicitada quede dentro de la carpeta autorizada
(CONVENIOS INTERINSTITUCIONALES UTMACH) antes de abrir nada, para que la
interfaz nunca pueda usarse para abrir una ruta arbitraria del equipo.

Solo ABRE con la aplicacion predeterminada de Windows; nunca escribe, mueve,
renombra ni borra.
"""

import os
from pathlib import Path


class RutaNoAutorizadaError(Exception):
    pass


def _validar_dentro_de_base(ruta: Path, ruta_base_convenios: Path) -> Path:
    ruta = Path(ruta).resolve()
    ruta_base_convenios = Path(ruta_base_convenios).resolve()
    try:
        dentro = ruta.is_relative_to(ruta_base_convenios)
    except AttributeError:
        dentro = str(ruta).startswith(str(ruta_base_convenios))
    if not dentro:
        raise RutaNoAutorizadaError(f"Ruta fuera del repositorio autorizado: {ruta}")
    return ruta


def abrir_archivo(ruta_str: str, ruta_base_convenios: Path) -> None:
    ruta = _validar_dentro_de_base(Path(ruta_str), ruta_base_convenios)
    if not ruta.exists():
        raise FileNotFoundError(f"Archivo no encontrado: {ruta}")
    os.startfile(str(ruta))  # noqa: S606 - apertura con app predeterminada, solo lectura


def abrir_carpeta_contenedora(ruta_str: str, ruta_base_convenios: Path) -> None:
    ruta = _validar_dentro_de_base(Path(ruta_str), ruta_base_convenios)
    carpeta = ruta if ruta.is_dir() else ruta.parent
    if not carpeta.exists():
        raise FileNotFoundError(f"Carpeta no encontrada: {carpeta}")
    os.startfile(str(carpeta))  # noqa: S606
