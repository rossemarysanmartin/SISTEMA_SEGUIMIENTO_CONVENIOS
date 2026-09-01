"""Genera REPORTES/REPORTE_VIGENCIA_CONVENIOS.md a partir de convenios.db."""

import sqlite3
from datetime import datetime
from pathlib import Path


def generar(ruta_db: Path, ruta_salida: Path, umbral_dias: int):
    conn = sqlite3.connect(str(ruta_db))
    conn.row_factory = sqlite3.Row

    L = ["# Reporte de Vigencia de Convenios\n", f"\nGenerado: {datetime.now().isoformat()}\n",
         f"\nUmbral 'próximo a vencer': {umbral_dias} días.\n"]

    base = "clasificacion_general='CONVENIO' AND estado_relacion_documental IN ('CONFIRMADA','PROBABLE')"
    total = conn.execute(f"SELECT COUNT(*) FROM convenios WHERE {base}").fetchone()[0]
    L.append(f"\n## Totales\n\n- Convenios analizados: **{total}**\n")
    for r in conn.execute(f"SELECT estado_vigencia, COUNT(*) n FROM convenios WHERE {base} GROUP BY estado_vigencia ORDER BY n DESC"):
        L.append(f"- {r['estado_vigencia']}: **{r['n']}**\n")

    for r in conn.execute(f"SELECT estado_revision_vigencia, COUNT(*) n FROM convenios WHERE {base} GROUP BY estado_revision_vigencia ORDER BY n DESC"):
        L.append(f"- Control `{r['estado_revision_vigencia']}`: **{r['n']}**\n")

    L.append("\n## Próximos a vencer (ordenados por menor cantidad de días restantes)\n")
    L.append("| Año | Código | Institución | Fecha fin | Días restantes | Documento |\n|---|---|---|---|---|---|\n")
    for r in conn.execute(
        f"SELECT anio, codigo_original, institucion, fecha_finalizacion, fecha_finalizacion_documento, "
        f"dias_para_vencimiento, ruta_documento_principal FROM convenios "
        f"WHERE {base} AND estado_vigencia='PROXIMO_A_VENCER' ORDER BY dias_para_vencimiento ASC"
    ):
        fecha_fin = r["fecha_finalizacion_documento"] or r["fecha_finalizacion"]
        L.append(f"| {r['anio']} | {r['codigo_original'] or ''} | {(r['institucion'] or '')[:40]} | {fecha_fin or ''} | "
                  f"{r['dias_para_vencimiento'] if r['dias_para_vencimiento'] is not None else ''} | {r['ruta_documento_principal'] or ''} |\n")

    L.append("\n## Vencidos (ordenados por fecha de finalización)\n")
    L.append("| Año | Código | Institución | Fecha fin | Documento |\n|---|---|---|---|---|\n")
    for r in conn.execute(
        f"SELECT anio, codigo_original, institucion, fecha_finalizacion, fecha_finalizacion_documento, "
        f"ruta_documento_principal FROM convenios WHERE {base} AND estado_vigencia='VENCIDO' "
        f"ORDER BY COALESCE(fecha_finalizacion_documento, fecha_finalizacion) ASC"
    ):
        fecha_fin = r["fecha_finalizacion_documento"] or r["fecha_finalizacion"]
        L.append(f"| {r['anio']} | {r['codigo_original'] or ''} | {(r['institucion'] or '')[:40]} | {fecha_fin or ''} | {r['ruta_documento_principal'] or ''} |\n")

    L.append("\n## Sin información suficiente\n")
    L.append("| Año | Código | Institución | Documento |\n|---|---|---|---|\n")
    for r in conn.execute(
        f"SELECT anio, codigo_original, institucion, ruta_documento_principal FROM convenios "
        f"WHERE {base} AND estado_vigencia='SIN_INFORMACION' ORDER BY anio"
    ):
        L.append(f"| {r['anio']} | {r['codigo_original'] or ''} | {(r['institucion'] or '')[:40]} | {r['ruta_documento_principal'] or ''} |\n")

    conn.close()
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta_salida, "w", encoding="utf-8") as fh:
        fh.writelines(L)
