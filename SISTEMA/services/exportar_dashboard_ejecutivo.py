"""Genera el Dashboard Ejecutivo Portable (Fase 6.5): un HTML autocontenido,
de SOLO CONSULTA, con una fotografia de convenios.db en el momento de la
generacion. No depende de Internet, Python, Flask ni SQLite para abrirse.

Reglas de privacidad (seccion 5 y 24 de la especificacion): el HTML generado
NUNCA debe contener rutas absolutas del equipo, logs, trazas tecnicas,
credenciales ni configuracion interna. `verificar_sin_datos_sensibles` se
ejecuta siempre antes de escribir el archivo.
"""

import json
import re
import shutil
from datetime import date, datetime
from pathlib import Path

from seguridad import verificar_ruta_escritura_segura
from services import repositorio_solicitudes as repo

NOMBRE_ARCHIVO = "DASHBOARD_CONVENIOS_UTMACH.html"

_ETIQUETAS_ESTADO_VIGENCIA = {
    "VIGENTE": "Vigente",
    "PROXIMO_A_VENCER": "Próximo a vencer",
    "VENCIDO": "Vencido",
    "SIN_INFORMACION": "Sin información suficiente",
}

# Patrones que NUNCA deben aparecer en el HTML exportado (seccion 24).
_PATRONES_PROHIBIDOS = [
    re.compile(r"[A-Za-z]:\\Users", re.IGNORECASE),
    re.compile(r"[A-Za-z]:\\\\Users", re.IGNORECASE),
    re.compile(r"OneDrive - utmachala", re.IGNORECASE),
    re.compile(r"SECRET_KEY", re.IGNORECASE),
    re.compile(r"\bpassword\b", re.IGNORECASE),
    re.compile(r"\btraceback\b", re.IGNORECASE),
    re.compile(r"sqlite3\.\w*Error"),
    re.compile(r"\bhash\b", re.IGNORECASE),
]


class DatosSensiblesError(Exception):
    """Se lanza si el HTML generado contiene un patron prohibido."""


def _tiene_tabla(conn, nombre: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (nombre,)
    ).fetchone() is not None


def _es_revision_pendiente(fila) -> bool:
    return (
        fila["requiere_revision_documental"] == "SI"
        or fila["estado_relacion_documental"] in ("PROBABLE", "NO_ENCONTRADA", "MULTIPLES_COINCIDENCIAS")
        or fila["estado_vigencia"] in (None, "SIN_INFORMACION")
        or fila["conflicto_fecha"] == "SI"
        or fila["tiene_adenda"] == "POR_REVISAR"
    )


def _descripciones_revision(fila) -> list:
    d = []
    if fila["estado_vigencia"] in (None, "SIN_INFORMACION"):
        d.append("Falta información de vigencia")
    if fila["estado_relacion_documental"] in ("PROBABLE", "MULTIPLES_COINCIDENCIAS"):
        d.append("Relación documental por revisar")
    if fila["estado_relacion_documental"] == "NO_ENCONTRADA":
        d.append("Documento no localizado")
    if fila["tiene_adenda"] == "POR_REVISAR":
        d.append("Posible adenda")
    if fila["conflicto_fecha"] == "SI":
        d.append("Conflicto entre matriz y documento")
    return d


def _recolectar_convenios(conn) -> list:
    filas = conn.execute(
        """SELECT id_sistema, anio, codigo_original, numero_original, institucion, tipo_instrumento,
                  objeto, fecha_suscripcion, fecha_finalizacion, estado_vigencia, dias_para_vencimiento,
                  administrador, ruta_documento_principal, estado_relacion_documental,
                  requiere_revision_documental, tiene_adenda, conflicto_fecha
           FROM convenios WHERE clasificacion_general='CONVENIO'
           ORDER BY anio DESC, institucion"""
    ).fetchall()

    resultado = []
    for f in filas:
        revision = _es_revision_pendiente(f)
        resultado.append({
            "id": f["id_sistema"],
            "anio": f["anio"],
            "codigo": f["codigo_original"] or f["numero_original"] or "—",
            "institucion": f["institucion"] or "—",
            "tipo": f["tipo_instrumento"] or "—",
            "objeto": f["objeto"] or "",
            "fecha_suscripcion": f["fecha_suscripcion"],
            "fecha_terminacion": f["fecha_finalizacion"],
            "estado_vigencia": f["estado_vigencia"] or "SIN_INFORMACION",
            "estado_etiqueta": _ETIQUETAS_ESTADO_VIGENCIA.get(f["estado_vigencia"], "Sin información suficiente"),
            "dias": f["dias_para_vencimiento"],
            "administrador": f["administrador"] or "—",
            "adenda": f["tiene_adenda"] or "NO",
            "conflicto": f["conflicto_fecha"] or "NO",
            "expediente_disponible": bool(f["ruta_documento_principal"]),
            "revision": revision,
            "descripciones_revision": _descripciones_revision(f) if revision else [],
        })
    return resultado


def _contadores_convenios(convenios: list) -> dict:
    total = len(convenios)
    return {
        "total": total,
        "vigentes": sum(1 for c in convenios if c["estado_vigencia"] == "VIGENTE"),
        "proximos_a_vencer": sum(1 for c in convenios if c["estado_vigencia"] == "PROXIMO_A_VENCER"),
        "vencidos": sum(1 for c in convenios if c["estado_vigencia"] == "VENCIDO"),
        "sin_informacion": sum(1 for c in convenios if c["estado_vigencia"] == "SIN_INFORMACION"),
        "revision_pendiente": sum(1 for c in convenios if c["revision"]),
    }


def _graficos_convenios(convenios: list) -> dict:
    def contar(clave):
        conteo = {}
        for c in convenios:
            valor = c[clave] or "—"
            conteo[valor] = conteo.get(valor, 0) + 1
        return conteo

    por_anio = contar("anio")
    por_tipo = contar("tipo")
    por_estado = contar("estado_etiqueta")

    return {
        "por_anio": [{"etiqueta": str(k), "total": v} for k, v in sorted(por_anio.items(), key=lambda kv: str(kv[0]), reverse=True)],
        "por_tipo": [{"etiqueta": k, "total": v} for k, v in sorted(por_tipo.items(), key=lambda kv: kv[1], reverse=True)],
        "por_estado": [{"etiqueta": k, "total": v} for k, v in sorted(por_estado.items(), key=lambda kv: kv[1], reverse=True)],
    }


def _recolectar_solicitudes(conn, config_efectiva) -> tuple:
    if not _tiene_tabla(conn, "solicitudes"):
        return [], {"total": 0, "en_gestion": 0, "pendientes_respuesta": 0, "en_juridico": 0,
                     "en_factibilidad": 0, "en_firma": 0, "sin_movimiento": 0, "suscritas": 0}

    etiquetas_actuacion = {r["codigo"]: r["etiqueta"] for r in conn.execute("SELECT codigo, etiqueta FROM catalogo_actuaciones")}

    filas = conn.execute(
        """SELECT s.id, s.codigo_solicitud, s.institucion, s.fecha_ingreso, s.medio_ingreso,
                  COALESCE(m.etiqueta, s.medio_ingreso) AS medio_etiqueta,
                  s.responsable_actual, s.estado_actual,
                  COALESCE(e.etiqueta, s.estado_actual) AS estado_etiqueta,
                  s.etapa_actual, COALESCE(et.etiqueta, s.etapa_actual) AS etapa_etiqueta,
                  s.fecha_ultima_actuacion
           FROM solicitudes s
           LEFT JOIN catalogo_medios_ingreso m ON m.codigo = s.medio_ingreso
           LEFT JOIN catalogo_estados_solicitud e ON e.codigo = s.estado_actual
           LEFT JOIN catalogo_etapas_solicitud et ON et.codigo = s.etapa_actual
           WHERE s.activo = 1
           ORDER BY s.fecha_ingreso DESC"""
    ).fetchall()

    hoy = date.today()
    resultado = []
    for f in filas:
        pendientes_abiertos = repo.obtener_pendientes_abiertos(conn, f["id"])
        pendiente_actual = repo.calcular_pendiente_actual(pendientes_abiertos)
        try:
            fecha_ult = date.fromisoformat(str(f["fecha_ultima_actuacion"])[:10]) if f["fecha_ultima_actuacion"] else None
            dias_sin_movimiento = (hoy - fecha_ult).days if fecha_ult else None
        except ValueError:
            dias_sin_movimiento = None
        semaforo = repo.calcular_semaforo(dias_sin_movimiento or 0, config_efectiva)

        trazabilidad = []
        for a in repo.obtener_actuaciones(conn, f["id"]):
            if a["anulada"]:
                continue
            trazabilidad.append({
                "fecha": a["fecha"],
                "actuacion": etiquetas_actuacion.get(a["tipo_actuacion"], a["tipo_actuacion"].replace("_", " ").title()),
                "dependencia": a["dependencia_destino"] or a["dependencia_origen"] or "—",
                "responsable": a["responsable"] or "—",
                "resultado": a["resultado"] or a["descripcion"] or "—",
            })

        resultado.append({
            "id": f["id"],
            "codigo": f["codigo_solicitud"],
            "institucion": f["institucion"],
            "fecha_ingreso": f["fecha_ingreso"],
            "medio": f["medio_etiqueta"],
            "responsable": f["responsable_actual"] or "—",
            "pendiente_actual": pendiente_actual,
            "estado": f["estado_etiqueta"],
            "etapa": f["etapa_etiqueta"],
            "dias_sin_movimiento": dias_sin_movimiento if dias_sin_movimiento is not None else "—",
            "semaforo": semaforo,
            "trazabilidad": trazabilidad,
        })

    contadores = repo.contadores_dashboard_solicitudes(conn, config_efectiva)
    return resultado, dict(contadores)


def recolectar_datos(conn, config_efectiva) -> dict:
    convenios = _recolectar_convenios(conn)
    solicitudes, contadores_solicitudes = _recolectar_solicitudes(conn, config_efectiva)
    return {
        "fecha_corte": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "convenios": convenios,
        "contadores_convenios": _contadores_convenios(convenios),
        "graficos": _graficos_convenios(convenios),
        "solicitudes": solicitudes,
        "contadores_solicitudes": contadores_solicitudes,
    }


def verificar_sin_datos_sensibles(html_texto: str) -> None:
    for patron in _PATRONES_PROHIBIDOS:
        coincidencia = patron.search(html_texto)
        if coincidencia:
            raise DatosSensiblesError(
                f"El dashboard ejecutivo contiene un patrón no permitido: {patron.pattern!r} "
                f"(coincidencia: {coincidencia.group(0)!r})"
            )


def generar_html(datos: dict) -> str:
    datos_json = json.dumps(datos, ensure_ascii=False, default=str)
    html = _PLANTILLA_HTML.replace("__DATOS_JSON__", datos_json)
    html = html.replace("__FECHA_CORTE__", datos["fecha_corte"])
    return html


def generar_dashboard_ejecutivo(conn, config, config_efectiva, guardar_historico: bool = False) -> Path:
    """Orquesta la exportacion completa: recolectar -> generar HTML -> verificar
    privacidad -> escribir SOLO dentro de DASHBOARD_EJECUTIVO. Nunca toca la
    base de datos ni el repositorio original (solo lee)."""
    datos = recolectar_datos(conn, config_efectiva)
    html = generar_html(datos)
    verificar_sin_datos_sensibles(html)

    ruta_salida = config.ruta_dashboard_ejecutivo_html
    verificar_ruta_escritura_segura(ruta_salida, config.ruta_base_convenios)
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    ruta_salida.write_text(html, encoding="utf-8")

    if guardar_historico:
        ruta_historico_dir = config.ruta_dashboard_ejecutivo_historico
        verificar_ruta_escritura_segura(ruta_historico_dir, config.ruta_base_convenios)
        ruta_historico_dir.mkdir(parents=True, exist_ok=True)
        nombre_historico = f"DASHBOARD_CONVENIOS_UTMACH_{date.today().isoformat()}.html"
        shutil.copy2(ruta_salida, ruta_historico_dir / nombre_historico)

    # Mantener sincronizado index.html en la raiz para GitHub Pages
    try:
        ruta_index_raiz = config.ruta_sistema_seguimiento / "index.html"
        shutil.copy2(ruta_salida, ruta_index_raiz)
    except Exception:
        pass

    return ruta_salida


_PLANTILLA_HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dashboard Ejecutivo — Convenios UTMACH</title>
<style>
:root {
    --azul: #1c3d5a; --azul-claro: #2f6690; --gris-fondo: #f4f6f8; --gris-borde: #dbe1e6;
    --texto: #22303c; --texto-suave: #5b6b78; --verde: #2e7d32; --amarillo: #b8860b;
    --naranja: #c1622a; --rojo: #b3261e; --blanco: #ffffff;
}
* { box-sizing: border-box; }
body {
    margin: 0; font-family: "Segoe UI", Calibri, Arial, sans-serif; background: var(--gris-fondo);
    color: var(--texto); line-height: 1.45;
}
header.cabecera {
    background: linear-gradient(135deg, var(--azul), var(--azul-claro)); color: #fff;
    padding: 20px 28px;
}
header.cabecera h1 { margin: 0 0 4px; font-size: 1.5rem; }
header.cabecera p.subtitulo { margin: 0; opacity: 0.9; font-size: 0.95rem; }
.franja-corte {
    background: #eef3f7; border-bottom: 1px solid var(--gris-borde); padding: 8px 28px;
    font-size: 0.85rem; color: var(--texto-suave);
}
.franja-corte strong { color: var(--azul); }
nav.menu {
    display: flex; flex-wrap: wrap; gap: 4px; background: #fff; border-bottom: 1px solid var(--gris-borde);
    padding: 0 20px; position: sticky; top: 0; z-index: 10;
}
nav.menu button {
    border: none; background: none; padding: 12px 16px; cursor: pointer; font-size: 0.92rem;
    color: var(--texto-suave); border-bottom: 3px solid transparent; font-weight: 600;
}
nav.menu button:hover { color: var(--azul); }
nav.menu button.activo { color: var(--azul); border-bottom-color: var(--azul-claro); }
main { padding: 24px 28px 60px; max-width: 1200px; margin: 0 auto; }
.seccion { display: none; }
.seccion.activa { display: block; }
h2.titulo-seccion { color: var(--azul); border-bottom: 2px solid var(--gris-borde); padding-bottom: 8px; margin-top: 0; }
.tarjetas { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 14px; margin: 16px 0 28px; }
.tarjeta {
    background: #fff; border: 1px solid var(--gris-borde); border-radius: 10px; padding: 16px;
    text-align: center; box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
.tarjeta .valor { font-size: 1.9rem; font-weight: 700; color: var(--azul); }
.tarjeta .etiqueta { font-size: 0.82rem; color: var(--texto-suave); margin-top: 4px; }
.tarjeta.vigente .valor { color: var(--verde); }
.tarjeta.atencion .valor { color: var(--amarillo); }
.tarjeta.riesgo .valor { color: var(--naranja); }
.tarjeta.critico .valor { color: var(--rojo); }
.panel { background: #fff; border: 1px solid var(--gris-borde); border-radius: 10px; padding: 18px; margin-bottom: 22px; }
.panel h3 { margin-top: 0; color: var(--azul); font-size: 1.05rem; }
.controles { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 14px; align-items: center; }
.controles input[type=text], .controles select {
    padding: 8px 10px; border: 1px solid var(--gris-borde); border-radius: 6px; font-size: 0.9rem;
}
.controles input[type=text] { min-width: 240px; flex: 1; }
.btn {
    padding: 8px 14px; border-radius: 6px; border: 1px solid var(--azul-claro); background: var(--azul-claro);
    color: #fff; cursor: pointer; font-size: 0.88rem; font-weight: 600;
}
.btn.secundario { background: #fff; color: var(--azul-claro); }
table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
table th, table td { padding: 9px 10px; border-bottom: 1px solid var(--gris-borde); text-align: left; }
table th { color: var(--texto-suave); font-weight: 600; background: #f8fafb; }
table tbody tr { cursor: pointer; }
table tbody tr:hover { background: #f2f7fb; }
.envoltura-tabla { overflow-x: auto; }
.badge { display: inline-block; padding: 2px 9px; border-radius: 12px; font-size: 0.78rem; font-weight: 600; }
.badge-vigente { background: #e3f2e5; color: var(--verde); }
.badge-proximo { background: #fff3d6; color: var(--amarillo); }
.badge-vencido { background: #fde3e1; color: var(--rojo); }
.badge-sin_informacion { background: #eceff1; color: var(--texto-suave); }
.badge-adenda { background: #fdeee1; color: var(--naranja); }
.texto-vacio { color: var(--texto-suave); font-style: italic; padding: 18px 0; }
.grafico-barra { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.grafico-barra .etiqueta { width: 190px; font-size: 0.85rem; flex-shrink: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.grafico-barra .pista { flex: 1; background: #eef1f3; border-radius: 5px; height: 16px; overflow: hidden; }
.grafico-barra .relleno { background: var(--azul-claro); height: 100%; border-radius: 5px; }
.grafico-barra .total { width: 34px; text-align: right; font-size: 0.82rem; color: var(--texto-suave); }
.graficos-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
.modal-fondo {
    display: none; position: fixed; inset: 0; background: rgba(20,30,40,0.55); z-index: 100;
    align-items: center; justify-content: center; padding: 20px;
}
.modal-fondo.visible { display: flex; }
.modal {
    background: #fff; border-radius: 10px; max-width: 640px; width: 100%; max-height: 85vh; overflow-y: auto;
    padding: 22px 26px;
}
.modal h3 { margin-top: 0; color: var(--azul); }
.modal dl { display: grid; grid-template-columns: 160px 1fr; gap: 8px 12px; font-size: 0.9rem; }
.modal dt { color: var(--texto-suave); }
.modal .cerrar { float: right; background: none; border: none; font-size: 1.3rem; cursor: pointer; color: var(--texto-suave); }
.timeline-item { border-left: 3px solid var(--azul-claro); padding: 6px 0 6px 14px; margin-bottom: 8px; font-size: 0.87rem; }
.timeline-item .fecha { color: var(--texto-suave); font-size: 0.8rem; }
.aviso-alerta { background: #fdeee1; border: 1px solid #f0c39a; color: #7a3c10; border-radius: 8px; padding: 10px 14px; font-size: 0.85rem; margin-bottom: 14px; }
footer.pie { text-align: center; padding: 20px; color: var(--texto-suave); font-size: 0.8rem; }
.leyenda-consulta { text-align: center; font-size: 0.82rem; color: var(--texto-suave); padding: 6px 0 0; }

/* --- Seccion demostrativa "Solicitudes y trazabilidad" (Fase 6.5 - ajuste) --- */
.lista-conoce { columns: 2; column-gap: 30px; padding-left: 20px; font-size: 0.9rem; }
.lista-conoce li { margin-bottom: 6px; }
.aviso-demo {
    display: inline-block; background: #fff3d6; color: #8a6d1f; border: 1px solid #f0d98c;
    border-radius: 6px; padding: 6px 12px; font-size: 0.82rem; font-weight: 600; margin-bottom: 14px;
}
.demo-formulario { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; }
.demo-campo-ancho { grid-column: 1 / -1; }
.demo-campo label { display: block; font-size: 0.78rem; color: var(--texto-suave); margin-bottom: 4px; }
.demo-campo input, .demo-campo select {
    width: 100%; padding: 7px 9px; border: 1px solid var(--gris-borde); border-radius: 6px;
    background: #f8fafb; font-size: 0.87rem; color: var(--texto);
}
.demo-grupo-condicional {
    grid-column: 1 / -1; display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 14px; border-top: 1px dashed var(--gris-borde); padding-top: 14px; margin-top: 4px;
}
.demo-ficha-solicitud {
    background: #f8fafb; border: 1px solid var(--gris-borde); border-radius: 8px; padding: 14px;
    margin-bottom: 16px; font-size: 0.9rem; display: grid; gap: 6px;
}
.demo-timeline { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 6px; margin-bottom: 14px; }
.demo-timeline-paso { background: var(--azul-claro); color: #fff; padding: 7px 12px; border-radius: 6px; font-size: 0.78rem; font-weight: 600; }
.demo-timeline-paso:not(:last-child)::after { content: "→"; margin-left: 10px; color: var(--texto-suave); font-weight: 400; }
.chips-grid { display: flex; flex-wrap: wrap; gap: 8px; }
.chip { background: #eef3f7; color: var(--azul); border: 1px solid var(--gris-borde); border-radius: 16px; padding: 6px 14px; font-size: 0.83rem; font-weight: 600; }

@media (max-width: 640px) {
    .grafico-barra .etiqueta { width: 110px; }
    .modal dl { grid-template-columns: 1fr; }
    .lista-conoce { columns: 1; }
}
</style>
</head>
<body>

<header class="cabecera">
    <h1>Sistema de Seguimiento de Convenios Interinstitucionales — UTMACH</h1>
    <p class="subtitulo">Dashboard Ejecutivo Portable · Versión de consulta</p>
</header>
<div class="franja-corte">
    Información actualizada al: <strong>__FECHA_CORTE__</strong> · Versión de consulta. Los datos corresponden a la fecha de actualización indicada. No se actualiza automáticamente.
</div>

<nav class="menu">
    <button data-seccion="resumen" class="activo">Resumen</button>
    <button data-seccion="convenios">Convenios</button>
    <button data-seccion="proximos">Próximos a vencer</button>
    <button data-seccion="vencidos">Vencidos</button>
    <button data-seccion="revision">Revisión pendiente</button>
    <button data-seccion="solicitudes">Solicitudes</button>
    <button data-seccion="modulo-solicitudes">Solicitudes y trazabilidad</button>
</nav>

<main>

<section id="seccion-resumen" class="seccion activa">
    <h2 class="titulo-seccion">Resumen ejecutivo</h2>

    <h3>Convenios suscritos</h3>
    <div class="tarjetas" id="tarjetas-convenios"></div>

    <h3>Solicitudes en trámite</h3>
    <div class="tarjetas" id="tarjetas-solicitudes"></div>
    <p class="texto-vacio" id="mensaje-sin-solicitudes-resumen" style="display:none;">Actualmente no existen solicitudes registradas.</p>

    <div class="graficos-grid">
        <div class="panel">
            <h3>Convenios por año</h3>
            <div id="grafico-anio"></div>
        </div>
        <div class="panel">
            <h3>Convenios por tipo</h3>
            <div id="grafico-tipo"></div>
        </div>
        <div class="panel">
            <h3>Distribución por estado de vigencia</h3>
            <div id="grafico-estado"></div>
        </div>
    </div>
</section>

<section id="seccion-convenios" class="seccion">
    <h2 class="titulo-seccion">Convenios</h2>
    <div class="controles">
        <input type="text" id="buscar-convenios" placeholder="Buscar por institución, código, tipo o administrador…">
        <select id="filtro-anio"><option value="">Año (todos)</option></select>
        <select id="filtro-tipo"><option value="">Tipo (todos)</option></select>
        <select id="filtro-estado">
            <option value="">Estado de vigencia (todos)</option>
            <option value="VIGENTE">Vigente</option>
            <option value="PROXIMO_A_VENCER">Próximo a vencer</option>
            <option value="VENCIDO">Vencido</option>
            <option value="SIN_INFORMACION">Sin información suficiente</option>
        </select>
        <button class="btn secundario" id="limpiar-filtros-convenios">Limpiar filtros</button>
    </div>
    <div class="envoltura-tabla panel">
        <table id="tabla-convenios">
            <thead><tr>
                <th>Año</th><th>Código</th><th>Institución</th><th>Tipo</th>
                <th>Fecha suscripción</th><th>Fecha terminación</th><th>Estado</th><th>Administrador</th>
            </tr></thead>
            <tbody></tbody>
        </table>
        <p class="texto-vacio" id="mensaje-sin-convenios" style="display:none;">No hay convenios que coincidan con la búsqueda o los filtros aplicados.</p>
    </div>
</section>

<section id="seccion-proximos" class="seccion">
    <h2 class="titulo-seccion">Convenios próximos a vencer</h2>
    <div class="envoltura-tabla panel">
        <table>
            <thead><tr><th>Institución</th><th>Tipo</th><th>Fecha de terminación</th><th>Días restantes</th><th>Administrador</th></tr></thead>
            <tbody id="tabla-proximos"></tbody>
        </table>
        <p class="texto-vacio" id="mensaje-sin-proximos" style="display:none;">No hay convenios próximos a vencer.</p>
    </div>
</section>

<section id="seccion-vencidos" class="seccion">
    <h2 class="titulo-seccion">Convenios vencidos</h2>
    <div class="envoltura-tabla panel">
        <table>
            <thead><tr><th>Institución</th><th>Tipo</th><th>Fecha de terminación</th><th>Administrador</th><th>Observación</th></tr></thead>
            <tbody id="tabla-vencidos"></tbody>
        </table>
        <p class="texto-vacio" id="mensaje-sin-vencidos" style="display:none;">No hay convenios vencidos.</p>
    </div>
</section>

<section id="seccion-revision" class="seccion">
    <h2 class="titulo-seccion">Registros que requieren revisión</h2>
    <div class="envoltura-tabla panel">
        <table>
            <thead><tr><th>Institución</th><th>Año</th><th>Tipo</th><th>Motivo de revisión</th></tr></thead>
            <tbody id="tabla-revision"></tbody>
        </table>
        <p class="texto-vacio" id="mensaje-sin-revision" style="display:none;">No hay registros pendientes de revisión.</p>
    </div>
</section>

<section id="seccion-solicitudes" class="seccion">
    <h2 class="titulo-seccion">Solicitudes en trámite</h2>
    <div class="controles">
        <input type="text" id="buscar-solicitudes" placeholder="Buscar por institución, código o responsable…">
        <select id="filtro-estado-solicitud"><option value="">Estado (todos)</option></select>
        <button class="btn secundario" id="limpiar-filtros-solicitudes">Limpiar filtros</button>
    </div>
    <div class="envoltura-tabla panel">
        <table id="tabla-solicitudes">
            <thead><tr>
                <th>Código</th><th>Institución</th><th>Fecha ingreso</th><th>Medio</th><th>Responsable</th>
                <th>Pendiente actual</th><th>Estado</th><th>Días s/mov.</th>
            </tr></thead>
            <tbody></tbody>
        </table>
        <p class="texto-vacio" id="mensaje-sin-solicitudes" style="display:none;">Actualmente no existen solicitudes registradas.</p>
    </div>
</section>

<section id="seccion-modulo-solicitudes" class="seccion">
    <h2 class="titulo-seccion">Solicitudes y trazabilidad</h2>
    <p>El módulo de solicitudes permite registrar los pedidos de nuevos convenios desde su ingreso y conservar la trazabilidad de las actuaciones realizadas durante su gestión, especialmente en los trámites recibidos por correo electrónico.</p>

    <div class="panel">
        <h3>Este módulo permite conocer</h3>
        <ul class="lista-conoce">
            <li>Cuándo ingresó</li>
            <li>Por qué medio</li>
            <li>A quién se delegó</li>
            <li>Qué criterio se solicitó</li>
            <li>A qué dependencia</li>
            <li>Qué respuesta está pendiente</li>
            <li>Cuánto tiempo lleva sin movimiento</li>
            <li>En qué etapa se encuentra</li>
            <li>Si finalmente fue suscrito</li>
        </ul>
    </div>

    <div class="panel">
        <h3>1. Registro de una nueva solicitud</h3>
        <p class="aviso-demo">Vista demostrativa — el registro real se realiza en el Sistema de Seguimiento de Convenios.</p>
        <div class="demo-formulario">
            <div class="demo-campo"><label>Fecha de ingreso</label><input type="text" value="26/08/2026" disabled></div>
            <div class="demo-campo">
                <label>Medio de ingreso</label>
                <select id="demo-medio-ingreso">
                    <option value="correo">Correo electrónico</option>
                    <option value="sistema">Sistema institucional</option>
                </select>
            </div>
            <div class="demo-campo"><label>Institución / contraparte</label><input type="text" value="Institución de ejemplo" disabled></div>
            <div class="demo-campo"><label>Asunto</label><input type="text" value="Solicitud de convenio de cooperación" disabled></div>
            <div class="demo-campo"><label>Tipo de convenio</label><input type="text" value="Convenio Marco" disabled></div>
            <div class="demo-campo"><label>Dependencia solicitante</label><input type="text" value="Unidad Académica / Facultad" disabled></div>
            <div class="demo-campo"><label>Responsable</label><input type="text" value="Responsable de ejemplo" disabled></div>
            <div class="demo-campo demo-campo-ancho"><label>Observación</label><input type="text" value="Ejemplo de observación breve." disabled></div>

            <div id="demo-grupo-correo" class="demo-grupo-condicional">
                <div class="demo-campo"><label>Remitente</label><input type="text" value="Nombre de ejemplo" disabled></div>
                <div class="demo-campo"><label>Correo</label><input type="text" value="ejemplo@institucion.edu" disabled></div>
                <div class="demo-campo"><label>Asunto del correo</label><input type="text" value="Solicitud de convenio" disabled></div>
                <div class="demo-campo"><label>Fecha del correo</label><input type="text" value="24/08/2026" disabled></div>
            </div>
            <div id="demo-grupo-sistema" class="demo-grupo-condicional" style="display:none;">
                <div class="demo-campo"><label>Número de trámite</label><input type="text" value="TR-2026-000123" disabled></div>
                <div class="demo-campo"><label>Fecha del trámite</label><input type="text" value="24/08/2026" disabled></div>
            </div>
        </div>
    </div>

    <div class="panel">
        <h3>2. Ejemplo de trazabilidad</h3>
        <p class="aviso-demo">EJEMPLO DEMOSTRATIVO — NO CORRESPONDE A UN TRÁMITE REAL</p>
        <div class="demo-ficha-solicitud">
            <div><strong>SOL-2026-0001</strong> — EJEMPLO DEMOSTRATIVO</div>
            <div>Estado: <span class="badge badge-proximo">PENDIENTE DE RESPUESTA</span></div>
            <div>Pendiente actual: <em>Esperando criterio de factibilidad</em></div>
        </div>
        <div class="demo-timeline">
            <div class="demo-timeline-paso">RECEPCIÓN</div>
            <div class="demo-timeline-paso">RECIBIDO EN LA UNIDAD</div>
            <div class="demo-timeline-paso">DELEGACIÓN</div>
            <div class="demo-timeline-paso">SOLICITUD DE CRITERIO</div>
            <div class="demo-timeline-paso">RESPUESTA RECIBIDA</div>
            <div class="demo-timeline-paso">ENVÍO A CONTRAPARTE</div>
            <div class="demo-timeline-paso">FIRMA</div>
            <div class="demo-timeline-paso">SUSCRIPCIÓN</div>
        </div>
        <p class="texto-vacio">El flujo no es rígido: las actuaciones se registran según corresponda a cada trámite; no todos los pasos ocurren siempre ni en el mismo orden.</p>
    </div>

    <div class="panel">
        <h3>¿Qué se puede registrar?</h3>
        <div class="chips-grid">
            <span class="chip">Delegar</span>
            <span class="chip">Solicitar criterio</span>
            <span class="chip">Solicitar factibilidad</span>
            <span class="chip">Enviar a jurídico</span>
            <span class="chip">Registrar respuesta</span>
            <span class="chip">Enviar a contraparte</span>
            <span class="chip">Enviar a firma</span>
            <span class="chip">Marcar como suscrito</span>
            <span class="chip">Nota interna</span>
        </div>
    </div>
</section>

</main>

<footer class="pie">
    Sistema de Seguimiento de Convenios Interinstitucionales — Universidad Técnica de Machala (UTMACH)
    <p class="leyenda-consulta">Dashboard ejecutivo de consulta — no permite modificar información.<br>
    Para gestión y actualización de datos debe utilizarse el Sistema de Seguimiento de Convenios.</p>
</footer>

<div class="modal-fondo" id="modal-fondo">
    <div class="modal" id="modal-contenido"></div>
</div>

<script>
const DATOS = __DATOS_JSON__;

function escapar(t) {
    if (t === null || t === undefined) return "";
    const div = document.createElement("div");
    div.textContent = String(t);
    return div.innerHTML;
}

function badgeEstado(codigo, etiqueta) {
    const clases = {VIGENTE: "badge-vigente", PROXIMO_A_VENCER: "badge-proximo", VENCIDO: "badge-vencido", SIN_INFORMACION: "badge-sin_informacion"};
    return `<span class="badge ${clases[codigo] || 'badge-sin_informacion'}">${escapar(etiqueta)}</span>`;
}

// ---------------------------------------------------------------- navegacion
document.querySelectorAll("nav.menu button").forEach(btn => {
    btn.addEventListener("click", () => {
        document.querySelectorAll("nav.menu button").forEach(b => b.classList.remove("activo"));
        document.querySelectorAll("main .seccion").forEach(s => s.classList.remove("activa"));
        btn.classList.add("activo");
        document.getElementById("seccion-" + btn.dataset.seccion).classList.add("activa");
    });
});

// -------------------------------------------------------------- tarjetas resumen
function pintarTarjetasConvenios() {
    const c = DATOS.contadores_convenios;
    const cont = document.getElementById("tarjetas-convenios");
    const items = [
        ["total", "Total"], ["vigentes", "Vigentes", "vigente"], ["proximos_a_vencer", "Próximos a vencer", "atencion"],
        ["vencidos", "Vencidos", "critico"], ["sin_informacion", "Sin información suficiente"],
        ["revision_pendiente", "Revisión pendiente", "riesgo"],
    ];
    cont.innerHTML = items.map(([clave, etiqueta, extra]) =>
        `<div class="tarjeta ${extra || ''}"><div class="valor">${c[clave]}</div><div class="etiqueta">${etiqueta}</div></div>`
    ).join("");
}

function pintarTarjetasSolicitudes() {
    const c = DATOS.contadores_solicitudes;
    const cont = document.getElementById("tarjetas-solicitudes");
    if (!c.total) {
        cont.innerHTML = "";
        document.getElementById("mensaje-sin-solicitudes-resumen").style.display = "block";
        return;
    }
    const items = [
        ["total", "Total"], ["en_gestion", "En gestión"], ["pendientes_respuesta", "Pendientes de respuesta"],
        ["en_juridico", "En jurídico"], ["en_factibilidad", "En factibilidad"], ["en_firma", "En firma"],
        ["sin_movimiento", "Sin movimiento", "riesgo"], ["suscritas", "Suscritas", "vigente"],
    ];
    cont.innerHTML = items.map(([clave, etiqueta, extra]) =>
        `<div class="tarjeta ${extra || ''}"><div class="valor">${c[clave] || 0}</div><div class="etiqueta">${etiqueta}</div></div>`
    ).join("");
}

// -------------------------------------------------------------------- graficos
function pintarBarra(contenedorId, filas, maxItems) {
    const cont = document.getElementById(contenedorId);
    if (!filas.length) { cont.innerHTML = '<p class="texto-vacio">Sin datos disponibles.</p>'; return; }
    const datos = filas.slice(0, maxItems || filas.length);
    const max = Math.max(...datos.map(f => f.total));
    cont.innerHTML = datos.map(f => `
        <div class="grafico-barra">
            <div class="etiqueta" title="${escapar(f.etiqueta)}">${escapar(f.etiqueta)}</div>
            <div class="pista"><div class="relleno" style="width:${max ? (f.total / max * 100) : 0}%"></div></div>
            <div class="total">${f.total}</div>
        </div>`).join("");
}

// -------------------------------------------------------------------- convenios
function opcionesUnicas(selectId, valores, placeholder) {
    const select = document.getElementById(selectId);
    const unicos = [...new Set(valores)].filter(v => v && v !== "—").sort();
    unicos.forEach(v => {
        const opt = document.createElement("option");
        opt.value = v; opt.textContent = v;
        select.appendChild(opt);
    });
}

function filaConvenio(c) {
    return `<tr data-id="${c.id}" data-tipo="convenio">
        <td>${c.anio}</td><td>${escapar(c.codigo)}</td><td>${escapar(c.institucion)}</td><td>${escapar(c.tipo)}</td>
        <td>${escapar(c.fecha_suscripcion) || "—"}</td><td>${escapar(c.fecha_terminacion) || "—"}</td>
        <td>${badgeEstado(c.estado_vigencia, c.estado_etiqueta)}</td><td>${escapar(c.administrador)}</td>
    </tr>`;
}

function aplicarFiltrosConvenios() {
    const texto = document.getElementById("buscar-convenios").value.trim().toLowerCase();
    const anio = document.getElementById("filtro-anio").value;
    const tipo = document.getElementById("filtro-tipo").value;
    const estado = document.getElementById("filtro-estado").value;

    let filtrados = DATOS.convenios.filter(c => {
        if (anio && String(c.anio) !== anio) return false;
        if (tipo && c.tipo !== tipo) return false;
        if (estado && c.estado_vigencia !== estado) return false;
        if (texto) {
            const campo = `${c.institucion} ${c.codigo} ${c.tipo} ${c.administrador}`.toLowerCase();
            if (!campo.includes(texto)) return false;
        }
        return true;
    });

    const tbody = document.querySelector("#tabla-convenios tbody");
    tbody.innerHTML = filtrados.map(filaConvenio).join("");
    document.getElementById("mensaje-sin-convenios").style.display = filtrados.length ? "none" : "block";
}

// ------------------------------------------------------------------ solicitudes
function filaSolicitud(s) {
    return `<tr data-id="${s.id}" data-tipo="solicitud">
        <td>${escapar(s.codigo)}</td><td>${escapar(s.institucion)}</td><td>${escapar(s.fecha_ingreso)}</td>
        <td>${escapar(s.medio)}</td><td>${escapar(s.responsable)}</td><td>${escapar(s.pendiente_actual)}</td>
        <td>${s.semaforo.icono} ${escapar(s.estado)}</td><td>${escapar(s.dias_sin_movimiento)}</td>
    </tr>`;
}

function aplicarFiltrosSolicitudes() {
    const texto = document.getElementById("buscar-solicitudes").value.trim().toLowerCase();
    const estado = document.getElementById("filtro-estado-solicitud").value;
    let filtrados = DATOS.solicitudes.filter(s => {
        if (estado && s.estado !== estado) return false;
        if (texto) {
            const campo = `${s.institucion} ${s.codigo} ${s.responsable}`.toLowerCase();
            if (!campo.includes(texto)) return false;
        }
        return true;
    });
    const tbody = document.querySelector("#tabla-solicitudes tbody");
    tbody.innerHTML = filtrados.map(filaSolicitud).join("");
    const sinDatos = document.getElementById("mensaje-sin-solicitudes");
    if (!DATOS.solicitudes.length) {
        sinDatos.textContent = "Actualmente no existen solicitudes registradas.";
        sinDatos.style.display = "block";
    } else {
        sinDatos.textContent = "No hay solicitudes que coincidan con la búsqueda o los filtros aplicados.";
        sinDatos.style.display = filtrados.length ? "none" : "block";
    }
}

// ----------------------------------------------------------------------- modal
function abrirModalConvenio(id) {
    const c = DATOS.convenios.find(x => x.id === id);
    if (!c) return;
    const expediente = c.expediente_disponible ? "Documento disponible en repositorio institucional" : "Expediente documental no localizado";
    const adenda = (c.adenda === "SI" || c.adenda === "POR_REVISAR")
        ? `<p class="aviso-alerta">Vigencia pendiente de validar por posible adenda.</p>` : "";
    document.getElementById("modal-contenido").innerHTML = `
        <button class="cerrar" id="cerrar-modal">&times;</button>
        <h3>${escapar(c.institucion)}</h3>
        ${adenda}
        <dl>
            <dt>Código</dt><dd>${escapar(c.codigo)}</dd>
            <dt>Tipo</dt><dd>${escapar(c.tipo)}</dd>
            <dt>Año</dt><dd>${c.anio}</dd>
            <dt>Objeto</dt><dd>${escapar(c.objeto) || "—"}</dd>
            <dt>Fecha de suscripción</dt><dd>${escapar(c.fecha_suscripcion) || "—"}</dd>
            <dt>Fecha de terminación</dt><dd>${escapar(c.fecha_terminacion) || "—"}</dd>
            <dt>Vigencia</dt><dd>${badgeEstado(c.estado_vigencia, c.estado_etiqueta)}</dd>
            <dt>Administrador</dt><dd>${escapar(c.administrador)}</dd>
            <dt>Estado documental</dt><dd>${expediente}</dd>
        </dl>`;
    document.getElementById("cerrar-modal").addEventListener("click", cerrarModal);
    document.getElementById("modal-fondo").classList.add("visible");
}

function abrirModalSolicitud(id) {
    const s = DATOS.solicitudes.find(x => x.id === id);
    if (!s) return;
    const timeline = s.trazabilidad.length
        ? s.trazabilidad.map(t => `<div class="timeline-item"><div class="fecha">${escapar(t.fecha)}</div>
            <strong>${escapar(t.actuacion)}</strong> — ${escapar(t.dependencia)} · ${escapar(t.responsable)}<br>
            <span>${escapar(t.resultado)}</span></div>`).join("")
        : '<p class="texto-vacio">Sin actuaciones registradas.</p>';
    document.getElementById("modal-contenido").innerHTML = `
        <button class="cerrar" id="cerrar-modal">&times;</button>
        <h3>${escapar(s.codigo)} — ${escapar(s.institucion)}</h3>
        <dl>
            <dt>Fecha de ingreso</dt><dd>${escapar(s.fecha_ingreso)}</dd>
            <dt>Medio</dt><dd>${escapar(s.medio)}</dd>
            <dt>Responsable</dt><dd>${escapar(s.responsable)}</dd>
            <dt>Etapa</dt><dd>${escapar(s.etapa)}</dd>
            <dt>Estado</dt><dd>${s.semaforo.icono} ${escapar(s.estado)}</dd>
            <dt>Pendiente actual</dt><dd>${escapar(s.pendiente_actual)}</dd>
        </dl>
        <h3>Trazabilidad</h3>
        ${timeline}`;
    document.getElementById("cerrar-modal").addEventListener("click", cerrarModal);
    document.getElementById("modal-fondo").classList.add("visible");
}

function cerrarModal() { document.getElementById("modal-fondo").classList.remove("visible"); }
document.getElementById("modal-fondo").addEventListener("click", (e) => { if (e.target.id === "modal-fondo") cerrarModal(); });

document.addEventListener("click", (e) => {
    const fila = e.target.closest("tr[data-id]");
    if (!fila) return;
    const id = parseInt(fila.dataset.id, 10);
    if (fila.dataset.tipo === "convenio") abrirModalConvenio(id);
    else abrirModalSolicitud(id);
});

// ------------------------------------------------------------------- inicio
function inicializar() {
    pintarTarjetasConvenios();
    pintarTarjetasSolicitudes();
    pintarBarra("grafico-anio", DATOS.graficos.por_anio, 8);
    pintarBarra("grafico-tipo", DATOS.graficos.por_tipo, 8);
    pintarBarra("grafico-estado", DATOS.graficos.por_estado);

    opcionesUnicas("filtro-anio", DATOS.convenios.map(c => c.anio));
    opcionesUnicas("filtro-tipo", DATOS.convenios.map(c => c.tipo));
    opcionesUnicas("filtro-estado-solicitud", DATOS.solicitudes.map(s => s.estado));

    ["buscar-convenios", "filtro-anio", "filtro-tipo", "filtro-estado"].forEach(id =>
        document.getElementById(id).addEventListener("input", aplicarFiltrosConvenios));
    document.getElementById("limpiar-filtros-convenios").addEventListener("click", () => {
        document.getElementById("buscar-convenios").value = "";
        document.getElementById("filtro-anio").value = "";
        document.getElementById("filtro-tipo").value = "";
        document.getElementById("filtro-estado").value = "";
        aplicarFiltrosConvenios();
    });
    aplicarFiltrosConvenios();

    ["buscar-solicitudes", "filtro-estado-solicitud"].forEach(id =>
        document.getElementById(id).addEventListener("input", aplicarFiltrosSolicitudes));
    document.getElementById("limpiar-filtros-solicitudes").addEventListener("click", () => {
        document.getElementById("buscar-solicitudes").value = "";
        document.getElementById("filtro-estado-solicitud").value = "";
        aplicarFiltrosSolicitudes();
    });
    aplicarFiltrosSolicitudes();

    const tProximos = document.getElementById("tabla-proximos");
    const proximos = DATOS.convenios.filter(c => c.estado_vigencia === "PROXIMO_A_VENCER").sort((a, b) => (a.dias ?? 9999) - (b.dias ?? 9999));
    tProximos.innerHTML = proximos.map(c => `<tr data-id="${c.id}" data-tipo="convenio">
        <td>${escapar(c.institucion)}</td><td>${escapar(c.tipo)}</td><td>${escapar(c.fecha_terminacion) || "—"}</td>
        <td>${c.dias ?? "—"}</td><td>${escapar(c.administrador)}</td></tr>`).join("");
    document.getElementById("mensaje-sin-proximos").style.display = proximos.length ? "none" : "block";

    const tVencidos = document.getElementById("tabla-vencidos");
    const vencidos = DATOS.convenios.filter(c => c.estado_vigencia === "VENCIDO");
    tVencidos.innerHTML = vencidos.map(c => {
        const obs = (c.adenda === "SI" || c.adenda === "POR_REVISAR")
            ? '<span class="badge badge-adenda">Vigencia pendiente de validar por posible adenda</span>' : "—";
        return `<tr data-id="${c.id}" data-tipo="convenio">
        <td>${escapar(c.institucion)}</td><td>${escapar(c.tipo)}</td><td>${escapar(c.fecha_terminacion) || "—"}</td>
        <td>${escapar(c.administrador)}</td><td>${obs}</td></tr>`;
    }).join("");
    document.getElementById("mensaje-sin-vencidos").style.display = vencidos.length ? "none" : "block";

    const tRevision = document.getElementById("tabla-revision");
    const revision = DATOS.convenios.filter(c => c.revision);
    tRevision.innerHTML = revision.map(c => `<tr data-id="${c.id}" data-tipo="convenio">
        <td>${escapar(c.institucion)}</td><td>${c.anio}</td><td>${escapar(c.tipo)}</td>
        <td>${c.descripciones_revision.map(d => `<span class="badge badge-sin_informacion">${escapar(d)}</span>`).join(" ")}</td></tr>`).join("");
    document.getElementById("mensaje-sin-revision").style.display = revision.length ? "none" : "block";
}

inicializar();

// --- Seccion demostrativa "Solicitudes y trazabilidad" (Fase 6.5 - ajuste) ---
// Aislada de la logica de datos reales: solo alterna dos bloques de campos
// visuales, no lee ni escribe en DATOS y no envia nada a ningun servidor.
function inicializarDemoSolicitudes() {
    const selectMedio = document.getElementById("demo-medio-ingreso");
    if (!selectMedio) return;
    const grupoCorreo = document.getElementById("demo-grupo-correo");
    const grupoSistema = document.getElementById("demo-grupo-sistema");
    selectMedio.addEventListener("change", () => {
        const esCorreo = selectMedio.value === "correo";
        grupoCorreo.style.display = esCorreo ? "grid" : "none";
        grupoSistema.style.display = esCorreo ? "none" : "grid";
    });
}
inicializarDemoSolicitudes();
</script>
</body>
</html>
"""
