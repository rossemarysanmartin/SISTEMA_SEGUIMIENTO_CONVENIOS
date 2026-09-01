"""Genera REPORTES/CONTROL_CALIDAD_MUESTRA.md: 5 registros por año (2020-2026),
mostrando la cadena MATRIZ -> REGISTRO CREADO -> DOCUMENTO RELACIONADO, sin
modificar nada, para que la oficina revise si las relaciones son correctas.
"""

import sqlite3
from pathlib import Path


def _seleccionar_muestra(conn, anio: int, n: int = 5):
    filas = list(conn.execute(
        "SELECT * FROM convenios WHERE anio = ? ORDER BY id_sistema", (anio,)
    ))
    if not filas:
        return []
    if len(filas) <= n:
        return filas
    paso = len(filas) / n
    indices = sorted({int(i * paso) for i in range(n)})
    return [filas[i] for i in indices][:n]


def generar(ruta_db: Path, ruta_salida: Path, anios: list):
    conn = sqlite3.connect(str(ruta_db))
    conn.row_factory = sqlite3.Row

    L = ["# Control de Calidad - Muestra de Verificación (5 registros por año)\n"]
    L.append("\nCadena verificada por cada registro: MATRIZ (archivo/hoja/fila) -> REGISTRO CREADO -> DOCUMENTO RELACIONADO.\n")
    L.append("Ningún archivo original fue modificado durante esta verificación.\n")

    for anio in anios:
        L.append(f"\n## Año {anio}\n")
        muestra = _seleccionar_muestra(conn, anio)
        if not muestra:
            L.append("\n_No se importaron registros de este año (revisar si la matriz existe/tiene datos)._\n")
            continue

        for row in muestra:
            L.append(f"\n### Registro id_sistema={row['id_sistema']} — {row['codigo_original'] or '(sin código)'}\n")
            L.append(f"- **MATRIZ**: `{row['archivo_matriz_origen']}` — hoja `{row['hoja_origen']}` — fila {row['fila_origen']}\n")
            L.append(f"- **REGISTRO CREADO**: institución=`{row['institucion']}`, tipo=`{row['tipo_instrumento']}` "
                      f"(subtipo original: `{row['subtipo']}`), clasificación=`{row['clasificacion_general']}`, "
                      f"fecha_suscripción=`{row['fecha_suscripcion']}`, plazo=`{row['plazo']}`, "
                      f"fecha_finalización=`{row['fecha_finalizacion']}` (método: {row['metodo_calculo_vigencia'] if 'metodo_calculo_vigencia' in row.keys() else 'N/D'}), "
                      f"estado_vigencia=`{row['estado_vigencia']}`\n")
            L.append(f"- **RELACIÓN DOCUMENTAL**: estado=`{row['estado_relacion_documental']}`, confianza={row['confianza_relacion']}\n")
            if row["ruta_documento_principal"]:
                L.append(f"- **DOCUMENTO RELACIONADO**: `{row['ruta_documento_principal']}`\n")
            else:
                L.append("- **DOCUMENTO RELACIONADO**: (ninguno encontrado)\n")
            L.append(f"- notas_sistema: {row['notas_sistema']}\n")
            L.append("- **Verificación pendiente por la oficina**: [ ] correcto  [ ] incorrecto  [ ] dudoso\n")

    conn.close()
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta_salida, "w", encoding="utf-8") as f:
        f.writelines(L)
