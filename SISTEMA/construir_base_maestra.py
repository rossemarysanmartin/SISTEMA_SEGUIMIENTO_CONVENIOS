"""
FASE 2 - BASE MAESTRA DE CONVENIOS 2020-2026

Orquesta: lectura de matrices (solo lectura) -> normalizacion de columnas ->
clasificacion de tipo -> calculo de vigencia (sin asumir duraciones) ->
relacion con documentos ya inventariados (Fase 0/1) -> guardado en
BASE_DATOS/convenios.db -> exportacion a Excel maestro -> reportes.

NUNCA escribe dentro del repositorio original. Todo el resultado queda en
SISTEMA_SEGUIMIENTO_CONVENIOS.
"""

import getpass
import json
import re
import sqlite3
import time
from datetime import date, datetime
from pathlib import Path

import comparar_matrices_2021
import control_calidad
import db_maestra
import reporte_fase2
from config import cargar_config
from exportar_excel import generar_excel_maestro
from extraer_matrices import extraer_registros_matriz
from relacionar_documentos import relacionar_convenio_con_documentos
from vigencia import calcular_estado_vigencia, calcular_fecha_finalizacion

RE_ERROR_ARCHIVO = re.compile(r"^No se pudo leer (.+?): (.+)$")


def _localizar_matrices_por_anio(config):
    """Devuelve {anio: [rutas]} explorando la raiz de cada carpeta de anio."""
    resultado = {}
    for anio in config.anios_analizar:
        ruta_anio = config.ruta_base_convenios / str(anio)
        if not ruta_anio.is_dir():
            resultado[anio] = []
            continue
        candidatos = [
            p for p in sorted(ruta_anio.iterdir())
            if p.is_file() and p.suffix.lower() in config.extensiones_matriz
        ]
        resultado[anio] = candidatos
    return resultado


def _elegir_matriz_2021(rutas: list, ruta_reportes: Path):
    principal = next((r for r in rutas if "copia" not in r.name.lower()), rutas[0])
    copia = next((r for r in rutas if "copia" in r.name.lower()), None)

    if copia is None:
        return principal, "SOLO_UN_ARCHIVO"

    resultado = comparar_matrices_2021.comparar(principal, copia, 2021)
    veredicto = comparar_matrices_2021.generar_reporte(resultado, ruta_reportes / "COMPARACION_MATRICES_2021.md")
    return principal, veredicto


def _cargar_documentos_por_anio(ruta_db_inventario: Path, anios: list):
    conn = sqlite3.connect(str(ruta_db_inventario))
    conn.row_factory = sqlite3.Row
    pool = {a: [] for a in anios}
    for row in conn.execute(
        "SELECT anio, carpeta_tipo, ruta_completa, nombre_archivo, extension, tamano_bytes, "
        "fecha_modificacion, tipo_pdf, firma_electronica_detectada, requiere_revision "
        "FROM archivos WHERE es_matriz = 0"
    ):
        if row["anio"] in pool:
            pool[row["anio"]].append(dict(row))
    conn.close()
    return pool


def _cargar_errores_previos(ruta_db_inventario: Path):
    conn = sqlite3.connect(str(ruta_db_inventario))
    conn.row_factory = sqlite3.Row
    fila = conn.execute("SELECT detalle FROM log_sincronizacion ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    if not fila or not fila["detalle"]:
        return []
    try:
        mensajes = json.loads(fila["detalle"])
    except Exception:
        return []
    errores = []
    for msg in mensajes:
        m = RE_ERROR_ARCHIVO.match(msg)
        if m:
            ruta, error = m.group(1), m.group(2)
            anio = None
            for token in Path(ruta).parts:
                if token.isdigit() and len(token) == 4:
                    anio = int(token)
                    break
            errores.append({"anio": anio, "ruta": ruta, "nombre": Path(ruta).name, "error": error})
    return errores


def _fecha_a_texto(valor):
    if valor is None:
        return None
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    return str(valor)


def _firma_texto(valor_bool, tipo_pdf) -> str:
    if tipo_pdf == "ERROR_LECTURA":
        return "POR_REVISAR"
    return "SI" if valor_bool else "NO"


def main():
    inicio = time.time()
    config = cargar_config()
    usuario = getpass.getuser()

    print("FASE 2 - Construyendo base maestra de convenios (solo lectura sobre el repositorio original)")

    matrices_por_anio = _localizar_matrices_por_anio(config)

    # Caso especial 2021
    ruta_matriz_2021, veredicto_2021 = _elegir_matriz_2021(matrices_por_anio[2021], config.ruta_reportes)
    print(f"2021: usando '{ruta_matriz_2021.name}' como fuente principal (veredicto comparación: {veredicto_2021})")

    documentos_pool = _cargar_documentos_por_anio(config.ruta_base_datos, config.anios_analizar)
    errores_previos = _cargar_errores_previos(config.ruta_base_datos)

    ruta_db_maestra = config.ruta_sistema_seguimiento / "BASE_DATOS" / "convenios.db"
    conn = db_maestra.conectar(ruta_db_maestra)
    db_maestra.inicializar_esquema(conn)
    db_maestra.limpiar_datos_previos(conn)

    for err in errores_previos:
        db_maestra.insertar_error_archivo(conn, {**err, "fecha_deteccion": datetime.now().isoformat()})

    campos_por_anio = {a: set() for a in config.anios_analizar}
    matrices_procesadas = 0
    registros_importados = 0
    documentos_relacionados = 0
    ahora = datetime.now().isoformat()

    for anio in config.anios_analizar:
        if anio == 2021:
            rutas = [ruta_matriz_2021]
        else:
            rutas = matrices_por_anio.get(anio, [])

        for ruta in rutas:
            matrices_procesadas += 1
            for registro in extraer_registros_matriz(ruta, anio, ruta.name):
                for campo, valor in registro.items():
                    if valor not in (None, ""):
                        campos_por_anio[anio].add(campo)

                fecha_inicio, fecha_fin, metodo = calcular_fecha_finalizacion(
                    registro.get("fecha_suscripcion"), registro.get("plazo")
                )
                registro["fecha_inicio"] = fecha_inicio
                registro["fecha_finalizacion"] = fecha_fin
                registro["metodo_calculo_vigencia"] = metodo
                estado_vigencia = calcular_estado_vigencia(fecha_fin, config.umbral_dias_proximo_vencer)

                candidatos = documentos_pool.get(anio, [])
                estado_rel, confianza, doc_elegido, notas = relacionar_convenio_con_documentos(registro, candidatos)

                requiere_revision = 1 if (
                    registro["clasificacion_general"] == "POR_REVISAR"
                    or estado_rel in ("NO_ENCONTRADA", "MULTIPLES_COINCIDENCIAS")
                ) else 0

                ruta_documento_principal = doc_elegido["ruta_completa"] if doc_elegido else None
                ruta_expediente = str(Path(doc_elegido["ruta_completa"]).parent) if doc_elegido else None

                fila_convenio = {
                    "anio": anio,
                    "codigo_original": registro["codigo_original"],
                    "numero_original": registro["numero_original"],
                    "institucion": registro["institucion"],
                    "tipo_instrumento": registro["tipo_instrumento"],
                    "subtipo": registro["subtipo"],
                    "clasificacion_general": registro["clasificacion_general"],
                    "objeto": registro["objeto"],
                    "fecha_suscripcion": _fecha_a_texto(registro["fecha_suscripcion"]),
                    "fecha_inicio": _fecha_a_texto(fecha_inicio),
                    "plazo": registro["plazo"],
                    "fecha_finalizacion": _fecha_a_texto(fecha_fin),
                    "metodo_calculo_vigencia": metodo,
                    "administrador": registro["administrador"],
                    "unidad_responsable": registro["unidad_responsable"],
                    "observaciones_originales": registro["observaciones_originales"],
                    "hoja_origen": registro["hoja_origen"],
                    "archivo_matriz_origen": registro["archivo_matriz_origen"],
                    "fila_origen": registro["fila_origen"],
                    "ruta_expediente": ruta_expediente,
                    "ruta_documento_principal": ruta_documento_principal,
                    "estado_relacion_documental": estado_rel,
                    "confianza_relacion": confianza,
                    "estado_vigencia": estado_vigencia,
                    "requiere_revision": requiere_revision,
                    "notas_sistema": notas,
                    "ruc": registro["ruc"],
                    "ambito": registro["ambito"],
                    "seccion": registro["seccion"],
                    "sector": registro["sector"],
                    "direccion": registro["direccion"],
                    "representante_legal": registro["representante_legal"],
                    "contacto": registro["contacto"],
                    "email": registro["email"],
                    "telefono": registro["telefono"],
                    "carreras_beneficiadas": registro["carreras_beneficiadas"],
                    "estado_original": registro["estado_original"],
                    "link_documento_matriz": registro["link_documento_matriz"],
                    "fecha_creacion_sistema": ahora,
                    "fecha_actualizacion_sistema": ahora,
                }
                id_sistema = db_maestra.insertar_convenio(conn, fila_convenio)
                registros_importados += 1

                db_maestra.upsert_catalogo_tipo(
                    conn, registro["subtipo"] or registro["hoja_origen"],
                    registro["tipo_instrumento"], registro["clasificacion_general"],
                )

                if doc_elegido:
                    db_maestra.insertar_documento(conn, {
                        "id_convenio": id_sistema,
                        "nombre": doc_elegido["nombre_archivo"],
                        "ruta": doc_elegido["ruta_completa"],
                        "extension": doc_elegido["extension"],
                        "tamano": doc_elegido["tamano_bytes"],
                        "fecha_modificacion": doc_elegido["fecha_modificacion"],
                        "anio": anio,
                        "carpeta_tipo": doc_elegido["carpeta_tipo"],
                        "clasificacion_tecnica_pdf": doc_elegido["tipo_pdf"],
                        "firma_electronica_detectada": _firma_texto(doc_elegido["firma_electronica_detectada"], doc_elegido["tipo_pdf"]),
                        "requiere_revision": doc_elegido["requiere_revision"],
                        "es_documento_principal": 1,
                    })
                    documentos_relacionados += 1
                    documentos_pool[anio] = [d for d in candidatos if d["ruta_completa"] != doc_elegido["ruta_completa"]]

    # Documentos que quedaron sin ningun registro de matriz asociado
    for anio, restantes in documentos_pool.items():
        for doc in restantes:
            db_maestra.insertar_documento(conn, {
                "id_convenio": None,
                "nombre": doc["nombre_archivo"],
                "ruta": doc["ruta_completa"],
                "extension": doc["extension"],
                "tamano": doc["tamano_bytes"],
                "fecha_modificacion": doc["fecha_modificacion"],
                "anio": anio,
                "carpeta_tipo": doc["carpeta_tipo"],
                "clasificacion_tecnica_pdf": doc["tipo_pdf"],
                "firma_electronica_detectada": _firma_texto(doc["firma_electronica_detectada"], doc["tipo_pdf"]),
                "requiere_revision": doc["requiere_revision"],
                "es_documento_principal": 0,
            })

    duracion = time.time() - inicio
    db_maestra.registrar_sincronizacion(conn, {
        "fecha_hora": datetime.now().isoformat(),
        "usuario": usuario,
        "fase": "BASE_MAESTRA_CONVENIOS",
        "matrices_procesadas": matrices_procesadas,
        "registros_importados": registros_importados,
        "documentos_relacionados": documentos_relacionados,
        "duracion_segundos": round(duracion, 2),
        "detalle": json.dumps({"veredicto_2021": veredicto_2021}, ensure_ascii=False),
    })
    conn.close()

    ruta_excel = config.ruta_sistema_seguimiento / "BASE_DATOS" / "BASE_MAESTRA_CONVENIOS_2020_2026.xlsx"
    generar_excel_maestro(ruta_db_maestra, ruta_excel)

    reporte_fase2.generar(
        ruta_db_maestra,
        config.ruta_reportes / "REPORTE_FASE_BASE_MAESTRA.md",
        veredicto_2021,
        campos_por_anio,
    )
    control_calidad.generar(
        ruta_db_maestra,
        config.ruta_reportes / "CONTROL_CALIDAD_MUESTRA.md",
        config.anios_analizar,
    )

    # ---- Resumen final (sin avanzar de fase) ----
    conn2 = sqlite3.connect(str(ruta_db_maestra))
    total = conn2.execute("SELECT COUNT(*) FROM convenios").fetchone()[0]
    total_convenio = conn2.execute("SELECT COUNT(*) FROM convenios WHERE clasificacion_general='CONVENIO'").fetchone()[0]
    total_con_doc = conn2.execute("SELECT COUNT(*) FROM convenios WHERE estado_relacion_documental IN ('CONFIRMADA','PROBABLE')").fetchone()[0]
    total_revision = conn2.execute("SELECT COUNT(*) FROM convenios WHERE requiere_revision=1").fetchone()[0]
    total_sin_doc = conn2.execute("SELECT COUNT(*) FROM convenios WHERE estado_relacion_documental='NO_ENCONTRADA'").fetchone()[0]
    total_doc_sin_registro = conn2.execute("SELECT COUNT(*) FROM documentos WHERE id_convenio IS NULL").fetchone()[0]
    conn2.close()

    print("\n===== RESUMEN FASE 2 (DETENIDO, no se avanza al dashboard) =====")
    print(f"Registros reales encontrados en las matrices: {total}")
    print(f"  De los cuales CONVENIO: {total_convenio}")
    print(f"Registros con documento relacionado (confirmada o probable): {total_con_doc}")
    print(f"Registros que requieren revisión manual: {total_revision}")
    print(f"Registros sin documento encontrado: {total_sin_doc}")
    print(f"Documentos que no aparecen en ninguna matriz: {total_doc_sin_registro}")
    print(f"Comparación matrices 2021: {veredicto_2021}")
    print(f"Base SQLite: {ruta_db_maestra}")
    print(f"Excel maestro: {ruta_excel}")
    print(f"Reportes en: {config.ruta_reportes}")
    print("\nNo se modificó nada del repositorio original.")


if __name__ == "__main__":
    main()
