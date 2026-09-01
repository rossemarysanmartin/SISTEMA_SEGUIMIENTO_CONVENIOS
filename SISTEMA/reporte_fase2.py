"""Genera REPORTES/REPORTE_FASE_BASE_MAESTRA.md a partir de convenios.db."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path


def generar(ruta_db: Path, ruta_salida: Path, veredicto_2021: str, campos_por_anio: dict):
    conn = sqlite3.connect(str(ruta_db))
    conn.row_factory = sqlite3.Row

    L = []
    L.append("# Reporte de Fase - Base Maestra de Convenios 2020-2026\n")
    L.append(f"\nGenerado: {datetime.now().isoformat()}\n")

    L.append("\n## 1. Registros importados por año\n")
    L.append("| Año | Registros |\n|---|---|\n")
    for r in conn.execute("SELECT anio, COUNT(*) n FROM convenios GROUP BY anio ORDER BY anio"):
        L.append(f"| {r['anio']} | {r['n']} |\n")

    L.append("\n## 2. Registros por tipo de instrumento\n")
    L.append("| Tipo normalizado | Registros |\n|---|---|\n")
    for r in conn.execute("SELECT tipo_instrumento, COUNT(*) n FROM convenios GROUP BY tipo_instrumento ORDER BY n DESC"):
        L.append(f"| {r['tipo_instrumento']} | {r['n']} |\n")

    total = conn.execute("SELECT COUNT(*) FROM convenios").fetchone()[0]
    L.append(f"\n## 3. Total de instrumentos importados\n\n**{total}**\n")

    L.append("\n## 4-7. Clasificación general\n")
    L.append("| Clasificación | Cantidad |\n|---|---|\n")
    for r in conn.execute("SELECT clasificacion_general, COUNT(*) n FROM convenios GROUP BY clasificacion_general ORDER BY n DESC"):
        L.append(f"| {r['clasificacion_general']} | {r['n']} |\n")

    L.append("\n## 8-9. Relación documental\n")
    L.append("| Estado de relación | Cantidad |\n|---|---|\n")
    for r in conn.execute("SELECT estado_relacion_documental, COUNT(*) n FROM convenios GROUP BY estado_relacion_documental ORDER BY n DESC"):
        L.append(f"| {r['estado_relacion_documental']} | {r['n']} |\n")

    n_sin_doc = conn.execute("SELECT COUNT(*) FROM convenios WHERE estado_relacion_documental='NO_ENCONTRADA'").fetchone()[0]
    L.append(f"\n## 10. Registros sin documento encontrado\n\n**{n_sin_doc}**\n")

    n_doc_sin_reg = conn.execute("SELECT COUNT(*) FROM documentos WHERE id_convenio IS NULL").fetchone()[0]
    L.append(f"\n## 11. Documentos sin registro de matriz\n\n**{n_doc_sin_reg}**\n")
    L.append("(Incluye adendas, cartas y otros documentos que legítimamente no están representados como fila en ninguna matriz — no implica error.)\n")

    n_revision = conn.execute("SELECT COUNT(*) FROM convenios WHERE requiere_revision=1").fetchone()[0]
    L.append(f"\n## 12. Registros que requieren revisión manual\n\n**{n_revision}**\n")

    L.append(f"\n## 13. Diferencias entre matrices de 2021\n\nVeredicto: **{veredicto_2021}**. Ver `COMPARACION_MATRICES_2021.md` para el detalle completo.\n")

    L.append("\n## 14. Campos disponibles por año (columnas reconocidas en al menos una hoja de ese año)\n")
    for anio in sorted(campos_por_anio):
        L.append(f"\n**{anio}**: {', '.join(sorted(campos_por_anio[anio]))}\n")

    L.append(
        "\n## 15. Campos que podremos obtener más adelante mediante análisis del documento (PDF)\n\n"
        "- fecha_inicio / fecha_finalizacion exacta cuando el 'periodo de vigencia' de la matriz no trae "
        "un rango de fechas explícito ni una duración interpretable.\n"
        "- Confirmación de firma (electrónica vs manuscrita) y validación del certificado, cuando se analice "
        "el contenido real del PDF (ya clasificado como texto/escaneado en la Fase 0/1, pendiente de lectura profunda).\n"
        "- RUC/dirección/contacto para los registros donde la matriz no trae esas columnas.\n"
        "- Confirmación humana de los registros en estado PROBABLE, MULTIPLES_COINCIDENCIAS o NO_ENCONTRADA.\n"
    )

    conn.close()
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta_salida, "w", encoding="utf-8") as f:
        f.writelines(L)
