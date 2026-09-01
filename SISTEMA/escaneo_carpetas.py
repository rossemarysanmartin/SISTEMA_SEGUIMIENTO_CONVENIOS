"""Recorrido de solo lectura de las carpetas anuales de convenios (2020-2026).

Este modulo SOLO usa operaciones de lectura de sistema de archivos
(os.scandir / os.walk / Path.stat). Nunca crea, borra, mueve ni renombra
nada dentro de la ruta base de convenios.
"""

import os
from datetime import datetime
from pathlib import Path

from config import Config


def _es_matriz(nombre: str, extension: str, config: Config) -> bool:
    return extension in config.extensiones_matriz


def escanear_anio(config: Config, anio: int):
    """Generador que recorre la carpeta de un anio y produce eventos:
    ('matriz', {...}) o ('documento', {...}).

    No modifica nada; solo lee metadatos con os.stat.
    """
    ruta_anio = config.ruta_base_convenios / str(anio)
    if not ruta_anio.is_dir():
        yield ("error", {"anio": anio, "mensaje": f"No existe la carpeta del anio: {ruta_anio}"})
        return

    for entrada in sorted(os.scandir(ruta_anio), key=lambda e: e.name):
        # Nunca entrar a la propia carpeta del sistema si por alguna razon quedara anidada aqui
        if entrada.name == config.carpeta_sistema:
            continue

        if entrada.is_file():
            extension = Path(entrada.name).suffix.lower()
            if extension in config.extensiones_ignoradas:
                continue
            try:
                st = entrada.stat()
            except OSError as e:
                yield ("error", {"anio": anio, "mensaje": f"No se pudo leer {entrada.path}: {e}"})
                continue

            info = {
                "anio": anio,
                "carpeta_tipo": None,  # archivo suelto en la raiz del anio
                "ruta_relativa": entrada.name,
                "ruta_completa": entrada.path,
                "nombre_archivo": entrada.name,
                "extension": extension,
                "tamano_bytes": st.st_size,
                "fecha_modificacion": datetime.fromtimestamp(st.st_mtime).isoformat(),
            }
            if _es_matriz(entrada.name, extension, config):
                yield ("matriz", info)
            else:
                yield ("documento", info)

        elif entrada.is_dir():
            carpeta_tipo = entrada.name
            for raiz, _dirs, archivos in os.walk(entrada.path):
                for nombre_archivo in sorted(archivos):
                    ruta_completa = os.path.join(raiz, nombre_archivo)
                    extension = Path(nombre_archivo).suffix.lower()
                    if extension in config.extensiones_ignoradas:
                        continue
                    try:
                        st = os.stat(ruta_completa)
                    except OSError as e:
                        yield ("error", {"anio": anio, "mensaje": f"No se pudo leer {ruta_completa}: {e}"})
                        continue

                    ruta_relativa = os.path.relpath(ruta_completa, ruta_anio)
                    info = {
                        "anio": anio,
                        "carpeta_tipo": carpeta_tipo,
                        "ruta_relativa": ruta_relativa,
                        "ruta_completa": ruta_completa,
                        "nombre_archivo": nombre_archivo,
                        "extension": extension,
                        "tamano_bytes": st.st_size,
                        "fecha_modificacion": datetime.fromtimestamp(st.st_mtime).isoformat(),
                    }
                    if _es_matriz(nombre_archivo, extension, config):
                        yield ("matriz", info)
                    else:
                        yield ("documento", info)
