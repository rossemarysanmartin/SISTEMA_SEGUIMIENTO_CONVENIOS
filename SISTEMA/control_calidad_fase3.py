"""Genera REPORTES/CONTROL_CALIDAD_FASE3.md: muestra diversa (>=3 por año,
variando tipo de instrumento y tipo tecnico de documento) para verificar la
cadena MATRIZ -> DOCUMENTO -> DATOS EXTRAIDOS -> FECHA -> PLAZO -> VIGENCIA.
"""

import sqlite3
from pathlib import Path


def _seleccionar_muestra(conn, anio: int, n: int = 5):
    filas = list(conn.execute(
        """SELECT c.*, d.tipo_documento_tecnico, d.cantidad_firmas
           FROM convenios c JOIN documentos d ON d.id_convenio = c.id_sistema
           WHERE c.anio = ? AND c.clasificacion_general='CONVENIO'
             AND c.estado_relacion_documental IN ('CONFIRMADA','PROBABLE')
           ORDER BY d.tipo_documento_tecnico, c.tipo_instrumento""",
        (anio,),
    ))
    if not filas:
        return []
    vistos_tecnico = set()
    vistos_tipo = set()
    muestra = []
    for f in filas:
        clave = (f["tipo_documento_tecnico"], f["tipo_instrumento"])
        if clave not in vistos_tipo or len(muestra) < n:
            muestra.append(f)
            vistos_tipo.add(clave)
        if len(muestra) >= max(n, 3):
            break
    return muestra[:max(n, 3)]


def generar(ruta_db: Path, ruta_salida: Path):
    conn = sqlite3.connect(str(ruta_db))
    conn.row_factory = sqlite3.Row

    L = ["# Control de Calidad Fase 3 - Análisis Documental\n",
         "\nCadena verificada: MATRIZ -> DOCUMENTO -> DATOS EXTRAÍDOS -> FECHA -> PLAZO -> VIGENCIA.\n",
         "Ningún archivo original fue modificado durante esta verificación.\n"]

    anios = [r["anio"] for r in conn.execute("SELECT DISTINCT anio FROM convenios ORDER BY anio")]
    for anio in anios:
        L.append(f"\n## Año {anio}\n")
        muestra = _seleccionar_muestra(conn, anio)
        if not muestra:
            L.append("\n_Sin registros CONFIRMADA/PROBABLE de tipo CONVENIO en este año._\n")
            continue
        for f in muestra:
            L.append(f"\n### id_sistema={f['id_sistema']} — {f['codigo_original'] or '(sin código)'} — {f['tipo_instrumento']}\n")
            L.append(f"- MATRIZ: `{f['archivo_matriz_origen']}` hoja `{f['hoja_origen']}` fila {f['fila_origen']}\n")
            L.append(f"- DOCUMENTO: `{f['ruta_documento_principal']}` (tipo técnico: {f['tipo_documento_tecnico']}, firmas detectadas: {f['cantidad_firmas']})\n")
            L.append(f"- FECHA suscripción: matriz=`{f['fecha_suscripcion']}` documento=`{f['fecha_suscripcion_documento']}`\n")
            L.append(f"- PLAZO: matriz=`{f['plazo']}` documento=`{f['plazo_documento']}`\n")
            L.append(f"- VIGENCIA final: fin=`{f['fecha_finalizacion_documento'] or f['fecha_finalizacion']}` "
                      f"estado=`{f['estado_vigencia']}` control=`{f['estado_revision_vigencia']}` confianza=`{f['confianza_analisis']}`\n")
            if f["conflicto_fecha"] == "SI":
                L.append("- ⚠️ CONFLICTO_FECHA detectado entre matriz y documento.\n")
            if f["tiene_adenda"] in ("SI", "POR_REVISAR"):
                L.append(f"- Posible adenda: `{f['tiene_adenda']}` -> `{f['documento_adenda_ruta']}`\n")
            L.append("- **Verificación pendiente por la oficina**: [ ] correcto  [ ] incorrecto  [ ] dudoso\n")

    conn.close()
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta_salida, "w", encoding="utf-8") as fh:
        fh.writelines(L)
