"""Compara LISTADO CONVENIOS 2021.xlsx vs LISTADO CONVENIOS 2021 - Copia.xlsx
a nivel de registro (no solo metadatos de archivo), sin modificar ninguno de
los dos archivos. Genera REPORTES/COMPARACION_MATRICES_2021.md.

Regla del usuario: si hay diferencias sustantivas, NO fusionar automaticamente.
Este script solo compara y reporta; la decision de cual usar como fuente
principal para construir la base maestra se documenta explicitamente aqui.
"""

from pathlib import Path

from extraer_matrices import extraer_registros_matriz


def _firma_registro(r: dict) -> tuple:
    objeto = (r.get("objeto") or "")[:80]
    return (r["hoja_origen"], r.get("codigo_original"), r.get("institucion"), objeto)


def comparar(ruta_original: Path, ruta_copia: Path, anio: int) -> dict:
    registros_original = list(extraer_registros_matriz(ruta_original, anio, ruta_original.name))
    registros_copia = list(extraer_registros_matriz(ruta_copia, anio, ruta_copia.name))

    firmas_original = {_firma_registro(r): r for r in registros_original}
    firmas_copia = {_firma_registro(r): r for r in registros_copia}

    solo_en_original = [firmas_original[k] for k in firmas_original.keys() - firmas_copia.keys()]
    solo_en_copia = [firmas_copia[k] for k in firmas_copia.keys() - firmas_original.keys()]
    en_ambos = firmas_original.keys() & firmas_copia.keys()

    hojas_original = {r["hoja_origen"] for r in registros_original}
    hojas_copia = {r["hoja_origen"] for r in registros_copia}

    return {
        "ruta_original": ruta_original,
        "ruta_copia": ruta_copia,
        "stat_original": ruta_original.stat(),
        "stat_copia": ruta_copia.stat(),
        "total_registros_original": len(registros_original),
        "total_registros_copia": len(registros_copia),
        "hojas_original": sorted(hojas_original),
        "hojas_copia": sorted(hojas_copia),
        "registros_en_ambos": len(en_ambos),
        "solo_en_original": solo_en_original,
        "solo_en_copia": solo_en_copia,
    }


def generar_reporte(resultado: dict, ruta_salida: Path) -> str:
    r = resultado
    idénticas = not r["solo_en_original"] and not r["solo_en_copia"] and r["hojas_original"] == r["hojas_copia"]

    if idénticas:
        veredicto = "A) IDÉNTICAS a nivel de registros (mismo contenido de convenios en ambos archivos)."
        recomendacion = (
            f"Usar **{r['ruta_original'].name}** (fecha de modificación más reciente: "
            f"{r['stat_original'].st_mtime_ns}) como fuente única para construir la base maestra. "
            f"**{r['ruta_copia'].name}** se documenta como duplicado/backup y se EXCLUYE de la importación "
            f"para no duplicar registros. No se elimina ni modifica el archivo Copia."
        )
    elif r["solo_en_copia"] and not r["solo_en_original"]:
        veredicto = "B) La Copia contiene registros adicionales que NO están en el archivo principal."
        recomendacion = (
            "REQUIERE REVISIÓN MANUAL: la Copia parece tener información que el archivo principal perdió. "
            "No se fusiona automáticamente. Se importan únicamente los registros del archivo principal; "
            f"los {len(r['solo_en_copia'])} registros exclusivos de la Copia se listan abajo para que la "
            "oficina decida si deben incorporarse."
        )
    elif r["solo_en_original"] and not r["solo_en_copia"]:
        veredicto = "B) El archivo principal contiene registros adicionales que NO están en la Copia."
        recomendacion = (
            f"Se usa **{r['ruta_original'].name}** como fuente principal (ya contiene todo lo de la Copia "
            "más registros adicionales, consistente con ser la versión más actual)."
        )
    else:
        veredicto = "C) Existen diferencias en ambas direcciones — requiere decisión manual."
        recomendacion = (
            "REQUIERE REVISIÓN MANUAL antes de continuar. Por seguridad, esta fase usa el archivo principal "
            f"(**{r['ruta_original'].name}**) para construir la base maestra, pero las diferencias deben ser "
            "revisadas por la oficina de Cooperación Interinstitucional."
        )

    lineas = []
    lineas.append("# Comparación de matrices 2021\n")
    lineas.append(f"- Archivo principal: `{r['ruta_original'].name}` — {r['stat_original'].st_size} bytes\n")
    lineas.append(f"- Archivo Copia: `{r['ruta_copia'].name}` — {r['stat_copia'].st_size} bytes\n")
    lineas.append(f"- Hojas en principal: {r['hojas_original']}\n")
    lineas.append(f"- Hojas en Copia: {r['hojas_copia']}\n")
    lineas.append(f"- Registros extraídos del principal: {r['total_registros_original']}\n")
    lineas.append(f"- Registros extraídos de la Copia: {r['total_registros_copia']}\n")
    lineas.append(f"- Registros presentes en ambos (misma hoja+código+institución+inicio de objeto): {r['registros_en_ambos']}\n")
    lineas.append(f"\n## Veredicto\n\n{veredicto}\n")
    lineas.append(f"\n## Recomendación\n\n{recomendacion}\n")

    if r["solo_en_original"]:
        lineas.append(f"\n## Registros SOLO en el archivo principal ({len(r['solo_en_original'])})\n")
        for reg in r["solo_en_original"][:100]:
            lineas.append(f"- [{reg['hoja_origen']}] {reg.get('codigo_original')} — {reg.get('institucion')}\n")

    if r["solo_en_copia"]:
        lineas.append(f"\n## Registros SOLO en la Copia ({len(r['solo_en_copia'])})\n")
        for reg in r["solo_en_copia"][:100]:
            lineas.append(f"- [{reg['hoja_origen']}] {reg.get('codigo_original')} — {reg.get('institucion')}\n")

    contenido = "".join(lineas)
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta_salida, "w", encoding="utf-8") as f:
        f.write(contenido)

    return "IDENTICAS" if idénticas else ("COPIA_TIENE_EXTRA" if r["solo_en_copia"] and not r["solo_en_original"] else
                                           ("PRINCIPAL_TIENE_EXTRA" if r["solo_en_original"] and not r["solo_en_copia"] else "DIFERENCIAS_MIXTAS"))
