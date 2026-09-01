"""Logging de errores tecnicos de la aplicacion web (LOGS/app_errores.log).

El usuario nunca debe ver un traceback de Python en pantalla (seccion 35);
el detalle tecnico completo queda aqui para diagnostico.
"""

import logging
from pathlib import Path

_logger = None


def obtener_logger(ruta_logs: Path) -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger
    ruta_logs.mkdir(parents=True, exist_ok=True)
    _logger = logging.getLogger("utmach_convenios_web")
    _logger.setLevel(logging.ERROR)
    manejador = logging.FileHandler(str(ruta_logs / "app_errores.log"), encoding="utf-8")
    manejador.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    _logger.addHandler(manejador)
    return _logger
