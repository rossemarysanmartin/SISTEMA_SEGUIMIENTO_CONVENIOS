"""Genera REPORTES/CONFLICTOS_MATRIZ_DOCUMENTO.md. No resuelve nada automaticamente."""

import sqlite3
from datetime import datetime
from pathlib import Path


def generar(ruta_db: Path, ruta_salida: Path):
    conn = sqlite3.connect(str(ruta_db))
    conn.row_factory = sqlite3.Row

    filas = list(conn.execute(
        """SELECT anio, codigo_original, institucion, fecha_suscripcion, fecha_suscripcion_documento,
                  fecha_finalizacion, fecha_finalizacion_documento, estado_revision_vigencia,
                  ruta_documento_principal
           FROM convenios WHERE conflicto_fecha = 'SI' ORDER BY anio"""
    ))

    L = ["# Conflictos Matriz vs Documento\n",
         f"\nGenerado: {datetime.now().isoformat()}\n",
         f"\nTotal de registros con conflicto de fecha: **{len(filas)}**\n",
         "\nNinguno de estos conflictos fue resuelto automáticamente. El campo `estado_vigencia` "
         "conserva el valor calculado en Fase 2 (matriz) hasta que la oficina revise cuál fecha es correcta.\n"]

    L.append("\n| Año | Código | Institución | Fecha suscripción (matriz) | Fecha suscripción (documento) | "
             "Fecha fin (matriz) | Fecha fin (documento) | Documento |\n")
    L.append("|---|---|---|---|---|---|---|---|\n")
    for f in filas:
        L.append(
            f"| {f['anio']} | {f['codigo_original'] or ''} | {(f['institucion'] or '')[:40]} | "
            f"{f['fecha_suscripcion'] or ''} | {f['fecha_suscripcion_documento'] or ''} | "
            f"{f['fecha_finalizacion'] or ''} | {f['fecha_finalizacion_documento'] or ''} | "
            f"{f['ruta_documento_principal'] or ''} |\n"
        )

    conn.close()
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta_salida, "w", encoding="utf-8") as fh:
        fh.writelines(L)
