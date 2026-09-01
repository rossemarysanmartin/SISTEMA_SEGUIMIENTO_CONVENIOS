"""
ANALIZADOR E INVENTARIO INICIAL - Sistema de Seguimiento de Convenios UTMACH

Recorre en modo SOLO LECTURA las carpetas 2020-2026 del repositorio de convenios,
identifica matrices, clasifica documentos PDF, y guarda todo el resultado
exclusivamente en SISTEMA_SEGUIMIENTO_CONVENIOS/BASE_DATOS/convenios_sistema.db.

NUNCA crea, modifica, mueve, renombra ni elimina nada dentro del repositorio original.

Uso:
    python inventario.py
"""

import getpass
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import db
from analisis_excel import inspeccionar_matriz
from analisis_pdf import calcular_hash_sha256, calcular_hash_sha256_bytes, clasificar_pdf_bytes, leer_bytes
from config import cargar_config
from escaneo_carpetas import escanear_anio


def procesar_documento(info: dict, conn, config) -> str:
    ruta = Path(info["ruta_completa"])
    existente = db.obtener_archivo_por_ruta(conn, info["ruta_completa"])

    necesita_reanalizar = True
    if existente is not None:
        _id, tam_prev, fecha_prev, _hash_prev = existente
        if tam_prev == info["tamano_bytes"] and fecha_prev == info["fecha_modificacion"]:
            necesita_reanalizar = False

    if not necesita_reanalizar:
        return "sin_cambios"

    try:
        contenido = leer_bytes(ruta)  # UNA sola lectura del archivo, se reutiliza abajo
        info["hash_sha256"] = calcular_hash_sha256_bytes(contenido)
    except OSError as e:
        info["hash_sha256"] = None
        contenido = None
        info["error_detalle"] = f"ERROR_LECTURA: {e}"

    if info["extension"] == ".pdf":
        if contenido is None:
            resultado_pdf = {
                "tipo_pdf": "ERROR_LECTURA",
                "num_paginas": None,
                "firma_electronica_detectada": False,
                "indicios_firma": "",
                "error_detalle": info.get("error_detalle"),
            }
        else:
            try:
                resultado_pdf = clasificar_pdf_bytes(contenido, config.muestra_paginas_pdf, config.min_caracteres_texto)
            except Exception as e:
                resultado_pdf = {
                    "tipo_pdf": "ERROR_LECTURA",
                    "num_paginas": None,
                    "firma_electronica_detectada": False,
                    "indicios_firma": "",
                    "error_detalle": str(e),
                }
        info.update(resultado_pdf)
        info["requiere_revision"] = 1 if resultado_pdf["tipo_pdf"] in (
            "ERROR_LECTURA", "REVIEW_REQUIRED", "POSIBLE_ESCANEADO",
        ) else 0
    else:
        info["tipo_pdf"] = "NO_APLICA"
        info["firma_electronica_detectada"] = False
        info["indicios_firma"] = ""
        info["requiere_revision"] = 0

    info["es_matriz"] = 0
    info["fecha_analisis"] = datetime.now().isoformat()
    return db.upsert_archivo(conn, info)


def procesar_matriz(info: dict, conn, config) -> str:
    ruta = Path(info["ruta_completa"])

    # Registrar tambien en la tabla "archivos" para que aparezca en el inventario general
    info_archivo = dict(info)
    try:
        info_archivo["hash_sha256"] = calcular_hash_sha256(ruta)
    except OSError as e:
        info_archivo["hash_sha256"] = None
        info_archivo["error_detalle"] = f"ERROR_LECTURA (hash): {e}"
    info_archivo["es_matriz"] = 1
    info_archivo["tipo_pdf"] = "NO_APLICA"
    info_archivo["firma_electronica_detectada"] = False
    info_archivo["indicios_firma"] = ""
    info_archivo["requiere_revision"] = 0
    info_archivo["fecha_analisis"] = datetime.now().isoformat()
    estado = db.upsert_archivo(conn, info_archivo)

    # Inspeccionar contenido de la matriz (hojas, encabezados) - siempre se reintenta, son pocos archivos
    try:
        resultado = inspeccionar_matriz(ruta)
        notas = resultado.get("notas")
    except Exception as e:
        resultado = {"hojas": [], "detalle_hojas": []}
        notas = f"ERROR_LECTURA: {e}"

    matriz_id = db.insertar_matriz(conn, {
        "anio": info["anio"],
        "nombre_archivo": info["nombre_archivo"],
        "ruta_completa": info["ruta_completa"],
        "tamano_bytes": info["tamano_bytes"],
        "fecha_modificacion": info["fecha_modificacion"],
        "hojas_json": json.dumps(resultado.get("hojas", []), ensure_ascii=False),
        "notas": notas,
        "fecha_analisis": datetime.now().isoformat(),
    })

    for hoja in resultado.get("detalle_hojas", []):
        db.insertar_hoja_matriz(conn, matriz_id, hoja)

    return estado


def main():
    inicio = time.time()
    config = cargar_config()

    print(f"Repositorio origen (SOLO LECTURA): {config.ruta_base_convenios}")
    print(f"Anios a analizar: {config.anios_analizar}")
    print(f"Base de datos del sistema: {config.ruta_base_datos}\n")

    conn = db.conectar(config.ruta_base_datos)
    db.inicializar_esquema(conn)

    contadores = {"nuevo": 0, "modificado": 0, "sin_cambios": 0}
    errores = []
    matrices_encontradas = 0
    documentos_requieren_revision = 0
    carpetas_analizadas = 0

    for anio in config.anios_analizar:
        print(f"--- Analizando anio {anio} ---")
        contador_anio = 0
        for evento, info in escanear_anio(config, anio):
            if evento == "error":
                errores.append(info["mensaje"])
                print(f"  [ERROR] {info['mensaje']}")
                continue

            if evento == "matriz":
                matrices_encontradas += 1
                estado = procesar_matriz(info, conn, config)
                print(f"  [MATRIZ] {info['nombre_archivo']} -> {estado}")
            else:
                try:
                    estado = procesar_documento(info, conn, config)
                except Exception as e:
                    errores.append(f"{info['ruta_completa']}: {e}")
                    print(f"  [ERROR] No se pudo procesar {info['nombre_archivo']}: {e}")
                    continue

            contadores[estado] = contadores.get(estado, 0) + 1
            contador_anio += 1

            if contador_anio % 50 == 0:
                print(f"  ... {contador_anio} archivos procesados en {anio}")

        carpetas_analizadas += 1
        print(f"  Total procesados en {anio}: {contador_anio}\n")

    cur = conn.execute("SELECT COUNT(*) FROM archivos WHERE requiere_revision = 1")
    documentos_requieren_revision = cur.fetchone()[0]

    duracion = time.time() - inicio
    total_archivos = sum(contadores.values())

    db.registrar_log_sincronizacion(conn, {
        "fecha_hora": datetime.now().isoformat(),
        "usuario": getpass.getuser(),
        "tipo_ejecucion": "INVENTARIO_INICIAL",
        "anios_analizados": json.dumps(config.anios_analizar),
        "carpetas_analizadas": carpetas_analizadas,
        "archivos_encontrados": total_archivos,
        "archivos_nuevos": contadores.get("nuevo", 0),
        "archivos_modificados": contadores.get("modificado", 0),
        "archivos_sin_cambios": contadores.get("sin_cambios", 0),
        "errores": len(errores),
        "documentos_requieren_revision": documentos_requieren_revision,
        "duracion_segundos": round(duracion, 2),
        "detalle": json.dumps(errores[:200], ensure_ascii=False),
    })

    conn.close()

    print("\n===== RESUMEN =====")
    print(f"Archivos totales procesados: {total_archivos}")
    print(f"  Nuevos: {contadores.get('nuevo', 0)}")
    print(f"  Modificados: {contadores.get('modificado', 0)}")
    print(f"  Sin cambios: {contadores.get('sin_cambios', 0)}")
    print(f"Matrices encontradas: {matrices_encontradas}")
    print(f"Documentos que requieren revision: {documentos_requieren_revision}")
    print(f"Errores: {len(errores)}")
    print(f"Duracion: {round(duracion, 1)} segundos")
    print(f"\nNo se modifico ni escribio nada dentro del repositorio original.")

    # Escribir tambien un log de texto plano con el detalle de errores
    log_path = config.ruta_logs / f"sync_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"Fecha: {datetime.now().isoformat()}\n")
        f.write(f"Usuario: {getpass.getuser()}\n")
        f.write(f"Archivos totales: {total_archivos}\n")
        f.write(f"Nuevos: {contadores.get('nuevo', 0)}\n")
        f.write(f"Modificados: {contadores.get('modificado', 0)}\n")
        f.write(f"Sin cambios: {contadores.get('sin_cambios', 0)}\n")
        f.write(f"Matrices encontradas: {matrices_encontradas}\n")
        f.write(f"Documentos que requieren revision: {documentos_requieren_revision}\n")
        f.write(f"Errores ({len(errores)}):\n")
        for e in errores:
            f.write(f"  - {e}\n")

    print(f"Log guardado en: {log_path}")


if __name__ == "__main__":
    sys.exit(main())
