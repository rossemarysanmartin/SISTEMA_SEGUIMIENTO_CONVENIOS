"""Genera un reporte de diagnostico en Markdown a partir de la base de datos
del inventario. Solo LEE la base de datos del sistema; no toca el repositorio original.

Uso:
    python reporte.py
"""

import json
import sqlite3
from datetime import datetime

from config import cargar_config


def generar_reporte():
    config = cargar_config()
    conn = sqlite3.connect(str(config.ruta_base_datos))
    conn.row_factory = sqlite3.Row

    lineas = []
    lineas.append(f"# Reporte de Inventario - Sistema de Seguimiento de Convenios UTMACH")
    lineas.append(f"\nGenerado: {datetime.now().isoformat()}\n")

    total = conn.execute("SELECT COUNT(*) FROM archivos").fetchone()[0]
    lineas.append(f"## Totales\n")
    lineas.append(f"- Total de archivos inventariados: **{total}**")

    lineas.append(f"\n### Por anio\n")
    lineas.append("| Anio | Archivos | PDFs | Matrices | Requieren revision |")
    lineas.append("|---|---|---|---|---|")
    for fila in conn.execute("""
        SELECT anio,
               COUNT(*) AS total,
               SUM(CASE WHEN extension = '.pdf' THEN 1 ELSE 0 END) AS pdfs,
               SUM(es_matriz) AS matrices,
               SUM(requiere_revision) AS revision
        FROM archivos GROUP BY anio ORDER BY anio
    """):
        lineas.append(f"| {fila['anio']} | {fila['total']} | {fila['pdfs']} | {fila['matrices']} | {fila['revision']} |")

    lineas.append(f"\n### Por extension\n")
    lineas.append("| Extension | Cantidad |")
    lineas.append("|---|---|")
    for fila in conn.execute("SELECT extension, COUNT(*) AS n FROM archivos GROUP BY extension ORDER BY n DESC"):
        lineas.append(f"| {fila['extension']} | {fila['n']} |")

    lineas.append(f"\n### Clasificacion de PDFs\n")
    lineas.append("| Tipo | Cantidad |")
    lineas.append("|---|---|")
    for fila in conn.execute("""
        SELECT tipo_pdf, COUNT(*) AS n FROM archivos
        WHERE extension = '.pdf' GROUP BY tipo_pdf ORDER BY n DESC
    """):
        lineas.append(f"| {fila['tipo_pdf']} | {fila['n']} |")

    firmas = conn.execute("SELECT COUNT(*) FROM archivos WHERE firma_electronica_detectada = 1").fetchone()[0]
    lineas.append(f"\n- PDFs con indicios de firma electronica detectados: **{firmas}** (esto es un indicio tecnico, no una validacion juridica)")

    lineas.append(f"\n### Matrices detectadas\n")
    lineas.append("| Anio | Archivo | Hojas | Notas |")
    lineas.append("|---|---|---|---|")
    for fila in conn.execute("SELECT anio, nombre_archivo, hojas_json, notas FROM matrices_detectadas ORDER BY anio"):
        hojas = ", ".join(json.loads(fila["hojas_json"])) if fila["hojas_json"] else ""
        lineas.append(f"| {fila['anio']} | {fila['nombre_archivo']} | {hojas} | {fila['notas'] or ''} |")

    lineas.append(f"\n### Documentos que requieren revision manual (muestra, maximo 50)\n")
    lineas.append("| Anio | Carpeta tipo | Archivo | Motivo |")
    lineas.append("|---|---|---|---|")
    for fila in conn.execute("""
        SELECT anio, carpeta_tipo, nombre_archivo, tipo_pdf, error_detalle
        FROM archivos WHERE requiere_revision = 1 LIMIT 50
    """):
        motivo = fila["error_detalle"] or fila["tipo_pdf"]
        lineas.append(f"| {fila['anio']} | {fila['carpeta_tipo'] or '(raiz)'} | {fila['nombre_archivo']} | {motivo} |")

    lineas.append(f"\n### Errores de lectura\n")
    for fila in conn.execute("""
        SELECT detalle FROM log_sincronizacion ORDER BY id DESC LIMIT 1
    """):
        try:
            errores = json.loads(fila["detalle"])
        except Exception:
            errores = []
        if errores:
            for e in errores:
                lineas.append(f"- {e}")
        else:
            lineas.append("- Ninguno registrado en la ultima ejecucion.")

    conn.close()

    ruta_reporte = config.ruta_reportes / f"diagnostico_inventario_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    ruta_reporte.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta_reporte, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas))

    print(f"Reporte generado en: {ruta_reporte}")
    return ruta_reporte


if __name__ == "__main__":
    generar_reporte()
