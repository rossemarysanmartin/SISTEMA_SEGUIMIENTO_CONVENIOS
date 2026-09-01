"""
FASE 3 - Analisis del documento principal de los convenios (clasificacion_general = CONVENIO)

Orden de prioridad: CONFIRMADA -> PROBABLE -> (NO_ENCONTRADA/MULTIPLES quedan pendientes).

Solo lee los PDF originales (nunca los modifica). Todo el resultado se guarda
en BASE_DATOS/convenios.db (con respaldo previo) y se exporta a Excel/reportes
dentro de SISTEMA_SEGUIMIENTO_CONVENIOS.
"""

import getpass
import json
import sqlite3
import time
from datetime import date, datetime
from pathlib import Path

import adendas
import control_calidad_fase3
import db_fase3
import reporte_conflictos
import reporte_vigencia
from analisis_pdf import calcular_hash_sha256
from config import cargar_config
from exportar_excel import generar_excel_maestro
from extractor_clausulas import (
    detectar_mencion_adenda, dividir_en_clausulas, extraer_administrador,
    extraer_fecha_suscripcion, extraer_objeto, extraer_vigencia,
)
from firma_pdf import analizar_firmas
from lector_pdf import extraer_texto_pdf
from vigencia import calcular_estado_vigencia, calcular_fecha_finalizacion

UMBRAL_DIAS_CONFLICTO_FECHA = 2


def _fecha_texto(v):
    if v is None:
        return None
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return str(v)


def _parse_fecha_iso(texto):
    if not texto:
        return None
    try:
        return date.fromisoformat(str(texto)[:10])
    except ValueError:
        return None


def _cargar_convenios_a_procesar(conn):
    filas = list(conn.execute(
        """SELECT c.*, d.id_documento, d.ruta AS doc_ruta, d.nombre AS doc_nombre,
                  d.clasificacion_tecnica_pdf, d.tamano AS doc_tamano, d.fecha_modificacion AS doc_fecha_mod,
                  d.carpeta_tipo AS doc_carpeta_tipo
           FROM convenios c
           JOIN documentos d ON d.id_convenio = c.id_sistema
           WHERE c.clasificacion_general = 'CONVENIO'
             AND c.estado_relacion_documental IN ('CONFIRMADA', 'PROBABLE')
           ORDER BY CASE c.estado_relacion_documental WHEN 'CONFIRMADA' THEN 0 ELSE 1 END, c.anio"""
    ))
    return filas


def _cargar_documentos_por_anio(conn, anios):
    pool = {a: [] for a in anios}
    for row in conn.execute("SELECT anio, carpeta_tipo, ruta, nombre FROM documentos"):
        if row["anio"] in pool:
            pool[row["anio"]].append(dict(row))
    return pool


def _combinar_confianza(niveles: list):
    niveles = [n for n in niveles if n]
    if not niveles:
        return None
    if "BAJA" in niveles:
        return "BAJA"
    if "MEDIA" in niveles:
        return "MEDIA"
    return "ALTA"


def main():
    inicio = time.time()
    config = cargar_config()
    usuario = getpass.getuser()
    ahora = datetime.now().isoformat()

    ruta_db = config.ruta_sistema_seguimiento / "BASE_DATOS" / "convenios.db"
    ruta_respaldo = db_fase3.respaldar(ruta_db)
    print(f"Respaldo creado: {ruta_respaldo}")

    conn = sqlite3.connect(str(ruta_db))
    conn.row_factory = sqlite3.Row
    db_fase3.migrar(conn)

    filas = _cargar_convenios_a_procesar(conn)
    print(f"Convenios a procesar (CONFIRMADA+PROBABLE, CONVENIO): {len(filas)}")

    documentos_por_anio = _cargar_documentos_por_anio(conn, config.anios_analizar)
    indice_adendas = adendas.construir_indice_adendas(documentos_por_anio)

    contadores = {
        "con_texto": 0, "necesito_ocr": 0, "ocr_exitoso": 0, "ocr_no_disponible": 0,
        "no_analizables": 0, "fecha_suscripcion_doc_obtenida": 0, "fecha_finalizacion_doc_obtenida": 0,
        "vigente": 0, "proximo_a_vencer": 0, "vencido": 0, "sin_informacion": 0,
        "posibles_adendas": 0, "conflictos": 0, "administradores_identificados": 0,
        "firmas_electronicas_detectadas": 0, "requiere_revision": 0,
    }

    for fila in filas:
        id_sistema = fila["id_sistema"]
        ruta_doc = Path(fila["doc_ruta"])
        tipo_pdf = fila["clasificacion_tecnica_pdf"]
        fecha_fin_matriz = _parse_fecha_iso(fila["fecha_finalizacion"])
        fecha_susc_matriz = _parse_fecha_iso(fila["fecha_suscripcion"])

        # ---- decidir si hace falta leer el contenido (evitar OCR/lectura innecesaria) ----
        necesita_lectura = True
        if tipo_pdf == "POSIBLE_ESCANEADO" and fecha_fin_matriz is not None:
            necesita_lectura = False  # la matriz ya aporta vigencia suficiente; no forzamos OCR

        resultado_texto = None
        clausulas = {}
        if necesita_lectura:
            resultado_texto = extraer_texto_pdf(ruta_doc)
            if resultado_texto["metodo"] == "TEXTO_PDF":
                contadores["con_texto"] += 1
            elif resultado_texto["metodo"] == "OCR":
                contadores["necesito_ocr"] += 1
                contadores["ocr_exitoso"] += 1
            elif resultado_texto["metodo"] == "OCR_NO_DISPONIBLE":
                contadores["necesito_ocr"] += 1
                contadores["ocr_no_disponible"] += 1
            else:
                contadores["no_analizables"] += 1

            if resultado_texto["paginas"]:
                clausulas = dividir_en_clausulas(resultado_texto["paginas"])

        # ---- extraccion de campos desde el documento (si hubo lectura util) ----
        fecha_susc_doc = fragmento_susc = pagina_susc = confianza_susc = None
        vigencia_doc = {}
        admin_doc = admin_pagina = admin_conf = None
        objeto_doc = objeto_resumen = objeto_pagina = objeto_conf = None
        tiene_adenda_mencion, adenda_mencion_info = False, None

        if resultado_texto and resultado_texto["paginas"]:
            fecha_susc_doc, fragmento_susc, pagina_susc, confianza_susc = extraer_fecha_suscripcion(resultado_texto["paginas"])
            vigencia_doc = extraer_vigencia(resultado_texto["paginas"], clausulas)
            admin_doc, admin_pagina, admin_conf = extraer_administrador(resultado_texto["paginas"], clausulas)
            objeto_doc, objeto_resumen, objeto_pagina, objeto_conf = extraer_objeto(resultado_texto["paginas"], clausulas)
            tiene_adenda_mencion, adenda_mencion_info = detectar_mencion_adenda(resultado_texto["paginas"])

        # ---- calculo de fecha_finalizacion_documento ----
        fecha_fin_doc = vigencia_doc.get("fecha_fin")
        metodo_vig_doc = vigencia_doc.get("metodo", "SIN_INFORMACION_SUFICIENTE")
        texto_fuente_vig = vigencia_doc.get("texto_fuente")
        pagina_fuente_vig = vigencia_doc.get("pagina")
        plazo_doc = vigencia_doc.get("plazo_texto")
        unidad_doc = vigencia_doc.get("unidad")

        if fecha_fin_doc is None and plazo_doc:
            fecha_base = fecha_susc_doc or fecha_susc_matriz
            if fecha_base:
                _, fecha_fin_calc, metodo_calc = calcular_fecha_finalizacion(fecha_base, plazo_doc)
                # Cota de plausibilidad: ningun convenio interinstitucional de este
                # archivo dura menos de 0 ni mas de ~20 años. Si la clausula de
                # plazo detectada produce algo fuera de rango, es señal de que se
                # capturo el numero equivocado (p.ej. un plazo administrativo
                # ajeno a la vigencia) y es mas seguro no reportar nada que
                # reportar una fecha fabricada por un mal parseo.
                if fecha_fin_calc and 0 <= (fecha_fin_calc - fecha_base).days <= 20 * 366:
                    fecha_fin_doc = fecha_fin_calc
                    metodo_vig_doc = "DURACION_EXPLICITA_DESDE_FECHA_SUSCRIPCION (documento)"
                elif fecha_fin_calc:
                    metodo_vig_doc = "DURACION_DETECTADA_FUERA_DE_RANGO_PLAUSIBLE"
                    plazo_doc = None

        if fecha_susc_doc:
            contadores["fecha_suscripcion_doc_obtenida"] += 1
        if fecha_fin_doc:
            contadores["fecha_finalizacion_doc_obtenida"] += 1
        if admin_doc:
            contadores["administradores_identificados"] += 1

        # ---- conflictos matriz vs documento ----
        conflicto_fecha = "NO"
        if fecha_susc_doc and fecha_susc_matriz and abs((fecha_susc_doc - fecha_susc_matriz).days) > UMBRAL_DIAS_CONFLICTO_FECHA:
            conflicto_fecha = "SI"
        if fecha_fin_doc and fecha_fin_matriz and abs((fecha_fin_doc - fecha_fin_matriz).days) > UMBRAL_DIAS_CONFLICTO_FECHA:
            conflicto_fecha = "SI"
        if conflicto_fecha == "SI":
            contadores["conflictos"] += 1

        # ---- estado_vigencia final (jerarquia de fuentes, sin sobrescribir en conflicto) ----
        estado_vigencia_final = fila["estado_vigencia"]  # el de Fase 2, por defecto se conserva
        fecha_fin_para_estado = fecha_fin_matriz
        if conflicto_fecha == "NO" and fecha_fin_matriz is None and fecha_fin_doc is not None:
            fecha_fin_para_estado = fecha_fin_doc
            estado_vigencia_final = calcular_estado_vigencia(fecha_fin_doc, config.umbral_dias_proximo_vencer)

        if estado_vigencia_final == "VIGENTE":
            contadores["vigente"] += 1
        elif estado_vigencia_final == "PROXIMO_A_VENCER":
            contadores["proximo_a_vencer"] += 1
        elif estado_vigencia_final == "VENCIDO":
            contadores["vencido"] += 1
        else:
            contadores["sin_informacion"] += 1

        dias_para_vencimiento = (fecha_fin_para_estado - date.today()).days if fecha_fin_para_estado else None

        # ---- adenda (mencion en texto + busqueda en carpeta de adendas del anio) ----
        tiene_adenda, ruta_adenda, motivo_adenda = adendas.buscar_posible_adenda(
            fila["anio"], fila["codigo_original"], fila["institucion"], indice_adendas
        )
        if tiene_adenda == "NO" and tiene_adenda_mencion:
            tiene_adenda = "POR_REVISAR"
        if tiene_adenda in ("SI", "POR_REVISAR"):
            contadores["posibles_adendas"] += 1

        # ---- estado_revision_vigencia ----
        if estado_vigencia_final == "VENCIDO" and tiene_adenda == "SI":
            estado_revision = "VIGENCIA_REQUIERE_VALIDAR_ADENDA"
        elif conflicto_fecha == "SI":
            estado_revision = "CONFLICTO_MATRIZ_DOCUMENTO"
        elif fecha_fin_para_estado is None and fecha_susc_matriz is None and fecha_susc_doc is None:
            estado_revision = "FALTA_FECHA"
        elif fecha_fin_para_estado is None:
            estado_revision = "FALTA_PLAZO"
        else:
            estado_revision = "COMPLETA"

        requiere_revision_doc = "SI" if estado_revision in (
            "CONFLICTO_MATRIZ_DOCUMENTO", "VIGENCIA_REQUIERE_VALIDAR_ADENDA",
        ) or (confianza_susc == "BAJA") else "NO"
        if requiere_revision_doc == "SI":
            contadores["requiere_revision"] += 1

        confianza_analisis = _combinar_confianza([confianza_susc, vigencia_doc.get("confianza"), admin_conf, objeto_conf])

        institucion_normalizada = " ".join((fila["institucion"] or "").split())

        # ---- firma electronica (metadatos tecnicos) ----
        firma = analizar_firmas(ruta_doc)
        if firma["cantidad_firmas"] > 0:
            tipo_doc_tecnico = "FIRMA_ELECTRONICA_DETECTADA"
            contadores["firmas_electronicas_detectadas"] += 1
        elif tipo_pdf == "POSIBLE_ESCANEADO":
            tipo_doc_tecnico = "DOCUMENTO_ESCANEADO"
        elif tipo_pdf == "TEXTO_SELECCIONABLE":
            tipo_doc_tecnico = "DOCUMENTO_DIGITAL_SIN_FIRMA_DETECTADA"
        else:
            tipo_doc_tecnico = "POR_REVISAR"

        try:
            hash_doc = calcular_hash_sha256(ruta_doc)
        except OSError:
            hash_doc = None

        # ---- guardar en convenios ----
        conn.execute(
            """UPDATE convenios SET
                objeto_documento_original=?, objeto_documento_resumen=?,
                fecha_suscripcion_documento=?, plazo_documento=?, unidad_plazo_documento=?,
                fecha_finalizacion_documento=?, metodo_calculo_vigencia_documento=?,
                texto_fuente_vigencia=?, pagina_fuente_vigencia=?,
                renovacion_clausula=?, administrador_documento=?, administrador_documento_pagina=?,
                institucion_normalizada=?, tiene_adenda=?, documento_adenda_ruta=?,
                conflicto_fecha=?, requiere_revision_documental=?, estado_revision_vigencia=?,
                confianza_analisis=?, dias_para_vencimiento=?, hash_documento_principal=?,
                fecha_ultimo_analisis_documento=?, estado_vigencia=?
               WHERE id_sistema=?""",
            (
                objeto_doc, objeto_resumen,
                _fecha_texto(fecha_susc_doc), plazo_doc, unidad_doc,
                _fecha_texto(fecha_fin_doc), metodo_vig_doc,
                texto_fuente_vig, pagina_fuente_vig,
                (vigencia_doc.get("texto_renovacion") if vigencia_doc.get("renovacion_detectada") else None),
                admin_doc, admin_pagina,
                institucion_normalizada, tiene_adenda, ruta_adenda,
                conflicto_fecha, requiere_revision_doc, estado_revision,
                confianza_analisis, dias_para_vencimiento, hash_doc,
                ahora, estado_vigencia_final,
                id_sistema,
            ),
        )

        conn.execute(
            """UPDATE documentos SET
                cantidad_firmas=?, firmante_certificado=?, fecha_firma_metadato=?, emisor_certificado=?,
                razon_firma=?, tipo_documento_tecnico=?, hash_ultimo_analisis=?, fecha_ultimo_analisis=?
               WHERE id_documento=?""",
            (
                firma["cantidad_firmas"], firma["firmante_certificado"], firma["fecha_firma_metadato"],
                firma["emisor_certificado"], firma["razon_firma"], tipo_doc_tecnico, hash_doc, ahora,
                fila["id_documento"],
            ),
        )

        for campo, valor, pagina, fragmento, metodo, confianza in [
            ("fecha_suscripcion_documento", _fecha_texto(fecha_susc_doc), pagina_susc, fragmento_susc,
             resultado_texto["metodo"] if resultado_texto else None, confianza_susc),
            ("fecha_finalizacion_documento", _fecha_texto(fecha_fin_doc), pagina_fuente_vig, texto_fuente_vig,
             resultado_texto["metodo"] if resultado_texto else None, vigencia_doc.get("confianza")),
            ("administrador_documento", admin_doc, admin_pagina, admin_doc, "TEXTO_PDF", admin_conf),
            ("objeto_documento", objeto_doc, objeto_pagina, (objeto_doc or "")[:300], "TEXTO_PDF", objeto_conf),
        ]:
            if valor:
                db_fase3.insertar_evidencia(conn, {
                    "id_convenio": id_sistema, "id_documento": fila["id_documento"], "campo": campo,
                    "valor_extraido": str(valor)[:500], "pagina": pagina, "fragmento_fuente": (fragmento or "")[:500],
                    "metodo_extraccion": metodo or "TEXTO_PDF", "nivel_confianza": confianza or "MEDIA",
                    "fecha_analisis": ahora,
                })

        conn.commit()

    # Priority 3: dejar pendientes, marcados explicitamente
    conn.execute(
        """UPDATE convenios SET estado_revision_vigencia='REQUIERE_REVISION', requiere_revision_documental='SI',
                                fecha_ultimo_analisis_documento=?
           WHERE clasificacion_general='CONVENIO' AND estado_relacion_documental IN ('NO_ENCONTRADA','MULTIPLES_COINCIDENCIAS')""",
        (ahora,),
    )
    conn.commit()

    duracion = time.time() - inicio

    conn.execute(
        """INSERT INTO sincronizaciones (fecha_hora, usuario, fase, matrices_procesadas, registros_importados,
                                          documentos_relacionados, duracion_segundos, detalle)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (datetime.now().isoformat(), usuario, "ANALISIS_DOCUMENTO_PRINCIPAL", 0, len(filas), len(filas),
         round(duracion, 2), json.dumps(contadores, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()

    # ---- exportar Excel actualizado ----
    ruta_excel = config.ruta_sistema_seguimiento / "BASE_DATOS" / "BASE_MAESTRA_CONVENIOS_2020_2026.xlsx"
    generar_excel_maestro(ruta_db, ruta_excel)

    # ---- reportes ----
    reporte_conflictos.generar(ruta_db, config.ruta_reportes / "CONFLICTOS_MATRIZ_DOCUMENTO.md")
    reporte_vigencia.generar(ruta_db, config.ruta_reportes / "REPORTE_VIGENCIA_CONVENIOS.md", config.umbral_dias_proximo_vencer)
    control_calidad_fase3.generar(ruta_db, config.ruta_reportes / "CONTROL_CALIDAD_FASE3.md")

    print("\n===== RESUMEN FASE 3 (DETENIDO, no se avanza al dashboard) =====")
    print(f"1. Convenios analizados: {len(filas)}")
    print(f"2. Documentos con texto seleccionable: {contadores['con_texto']}")
    print(f"3. Documentos que necesitaron OCR: {contadores['necesito_ocr']}")
    print(f"4. OCR satisfactorio: {contadores['ocr_exitoso']}")
    print(f"5. Documentos que no pudieron analizarse (incl. OCR no disponible): {contadores['no_analizables'] + contadores['ocr_no_disponible']}")
    print(f"6. Fechas de suscripción obtenidas del documento: {contadores['fecha_suscripcion_doc_obtenida']}")
    print(f"7. Fechas de terminación obtenidas (documento): {contadores['fecha_finalizacion_doc_obtenida']}")
    print(f"8. Vigentes: {contadores['vigente']}")
    print(f"9. Próximos a vencer: {contadores['proximo_a_vencer']}")
    print(f"10. Vencidos: {contadores['vencido']}")
    print(f"11. Sin información suficiente: {contadores['sin_informacion']}")
    print(f"12. Posibles adendas: {contadores['posibles_adendas']}")
    print(f"13. Conflictos matriz-documento: {contadores['conflictos']}")
    print(f"14. Administradores identificados: {contadores['administradores_identificados']}")
    print(f"15. Firmas electrónicas detectadas: {contadores['firmas_electronicas_detectadas']}")
    print(f"16. Registros que requieren revisión: {contadores['requiere_revision']}")
    print(f"17. Tiempo total de procesamiento: {round(duracion, 1)} segundos")
    print(f"\nRespaldo previo: {ruta_respaldo}")
    print(f"SQLite actualizado: {ruta_db}")
    print(f"Excel maestro actualizado: {ruta_excel}")
    print(f"Reporte de vigencia: {config.ruta_reportes / 'REPORTE_VIGENCIA_CONVENIOS.md'}")
    print(f"Reporte de conflictos: {config.ruta_reportes / 'CONFLICTOS_MATRIZ_DOCUMENTO.md'}")
    print(f"Control de calidad: {config.ruta_reportes / 'CONTROL_CALIDAD_FASE3.md'}")
    print("\nNo se modificó nada del repositorio original.")


if __name__ == "__main__":
    main()
