"""Ejecucion de la sincronizacion incremental desde el visualizador.

Reutiliza los mismos scripts ya construidos y aprobados en fases anteriores
(inventario.py, construir_base_maestra.py, analizar_documentos_principales.py),
que ya implementan la logica incremental (comparacion por tamano/fecha/hash) y
NUNCA escriben en el repositorio original. Este modulo solo los orquesta como
subprocesos y registra el resultado en la tabla `sincronizaciones`.

Se ejecuta en un hilo de fondo para no bloquear el servidor web; el estado se
consulta via `obtener_estado()`.
"""

import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

_ESTADO_LOCK = threading.Lock()
_ESTADO = {"en_progreso": False, "paso_actual": None, "inicio": None, "ultimo_resultado": None}

RUTA_SISTEMA_DIR = Path(__file__).resolve().parent.parent
PYTHON_EXE = sys.executable

PASOS = [
    ("Inventario documental (incremental)", "inventario.py"),
    ("Base maestra de convenios", "construir_base_maestra.py"),
    ("Analisis de documentos principales", "analizar_documentos_principales.py"),
]


def obtener_estado() -> dict:
    with _ESTADO_LOCK:
        return dict(_ESTADO)


def _ejecutar_paso(script_nombre: str) -> tuple:
    ruta_script = RUTA_SISTEMA_DIR / script_nombre
    resultado = subprocess.run(
        [PYTHON_EXE, str(ruta_script)],
        cwd=str(RUTA_SISTEMA_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
    )
    return resultado.returncode, resultado.stdout, resultado.stderr


def _correr(conn_factory, registrar_sincronizacion_fn):
    inicio = time.time()
    detalle_lineas = []
    errores = 0
    try:
        for etiqueta, script in PASOS:
            with _ESTADO_LOCK:
                _ESTADO["paso_actual"] = etiqueta
            codigo, stdout, stderr = _ejecutar_paso(script)
            detalle_lineas.append(f"[{etiqueta}] codigo_salida={codigo}")
            if stdout:
                detalle_lineas.append(stdout.strip()[-1500:])
            if codigo != 0:
                errores += 1
                detalle_lineas.append(f"ERROR en {script}: {stderr.strip()[-1500:]}")
                break
    except Exception as exc:  # incidente: se registra y no se detiene el servidor web
        errores += 1
        detalle_lineas.append(f"EXCEPCION durante sincronizacion: {exc}")

    duracion = time.time() - inicio
    resultado_final = "OK" if errores == 0 else "CON_ERRORES"
    detalle = "\n".join(detalle_lineas)

    try:
        conn = conn_factory()
        registrar_sincronizacion_fn(conn, {
            "fecha_hora": datetime.now().isoformat(),
            "usuario": None,
            "fase": "SINCRONIZACION_VISUALIZADOR",
            "matrices_procesadas": None,
            "registros_importados": None,
            "documentos_relacionados": None,
            "duracion_segundos": round(duracion, 1),
            "detalle": f"Resultado: {resultado_final}\n{detalle}"[:8000],
        })
        conn.close()
    except Exception:
        pass  # el historial es informativo; un fallo al registrarlo no debe ocultar el resultado real

    with _ESTADO_LOCK:
        _ESTADO["en_progreso"] = False
        _ESTADO["paso_actual"] = None
        _ESTADO["ultimo_resultado"] = resultado_final


def iniciar_sincronizacion(conn_factory, registrar_sincronizacion_fn) -> bool:
    """Devuelve False si ya habia una sincronizacion en curso (no se inicia otra)."""
    with _ESTADO_LOCK:
        if _ESTADO["en_progreso"]:
            return False
        _ESTADO["en_progreso"] = True
        _ESTADO["inicio"] = datetime.now().isoformat()
        _ESTADO["paso_actual"] = "Iniciando..."

    hilo = threading.Thread(target=_correr, args=(conn_factory, registrar_sincronizacion_fn), daemon=True)
    hilo.start()
    return True
