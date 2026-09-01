"""Genera el Dashboard Ejecutivo y Web Pública (HTML autocontenido).
Refleja con total fidelidad la interfaz completa del Visualizador Web de Convenios UTMACH.
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
        "requieren_revision": sum(1 for c in convenios if c["revision"]),
        "posible_adenda": sum(1 for c in convenios if c["adenda"] in ("SI", "POR_REVISAR")),
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
        return [], {"total": 0, "recibidas": 0, "en_gestion": 0, "pendientes_respuesta": 0, "en_juridico": 0,
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
            "estado_codigo": f["estado_actual"],
            "etapa": f["etapa_etiqueta"],
            "etapa_codigo": f["etapa_actual"],
            "dias_sin_movimiento": dias_sin_movimiento if dias_sin_movimiento is not None else "—",
            "semaforo": semaforo,
            "trazabilidad": trazabilidad,
        })

    contadores = repo.contadores_dashboard_solicitudes(conn, config_efectiva)
    return resultado, dict(contadores)


def recolectar_datos(conn, config_efectiva) -> dict:
    convenios = _recolectar_convenios(conn)
    solicitudes, contadores_solicitudes = _recolectar_solicitudes(conn, config_efectiva)

    anios = sorted(list({c["anio"] for c in convenios if c["anio"]}), reverse=True)
    tipos = sorted(list({c["tipo"] for c in convenios if c["tipo"] and c["tipo"] != "—"}))
    estados = ["VIGENTE", "PROXIMO_A_VENCER", "VENCIDO", "SIN_INFORMACION"]
    administradores = sorted(list({c["administrador"] for c in convenios if c["administrador"] and c["administrador"] != "—"}))

    proximos = [c for c in convenios if c["dias"] is not None and c["estado_vigencia"] == "PROXIMO_A_VENCER"]
    proximos.sort(key=lambda x: int(x["dias"]))

    return {
        "fecha_corte": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "convenios": convenios,
        "contadores_convenios": _contadores_convenios(convenios),
        "graficos": _graficos_convenios(convenios),
        "solicitudes": solicitudes,
        "contadores_solicitudes": contadores_solicitudes,
        "disponibles": {
            "anios": anios,
            "tipos": tipos,
            "estados": estados,
            "administradores": administradores,
        },
        "proximos_top": proximos[:15],
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
<title>Sistema de Seguimiento de Convenios — UTMACH</title>
<style>
:root {
    --azul-utmach: #1b3a63;
    --azul-oscuro: #10233d;
    --gris-fondo: #f4f6f8;
    --gris-borde: #d9dfe4;
    --gris-texto: #2b2f33;
    --verde: #1f8a4c;
    --amarillo: #b8860b;
    --rojo: #b3261e;
    --naranja: #c2660d;
    --azul-info: #2563a8;
    --blanco: #ffffff;
}
* { box-sizing: border-box; }
body {
    margin: 0;
    font-family: "Segoe UI", Arial, sans-serif;
    background: var(--gris-fondo);
    color: var(--gris-texto);
    font-size: 14px;
    line-height: 1.45;
}
.cabecera {
    background: var(--azul-utmach);
    color: var(--blanco);
    padding: 14px 24px;
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
}
.cabecera-marca { display: flex; flex-direction: column; }
.cabecera-titulo { font-size: 1.2rem; font-weight: 600; display: block; letter-spacing: -0.2px; }
.cabecera-subtitulo { font-size: 0.82rem; opacity: 0.85; }

.nav-principal { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.nav-principal a {
    color: var(--blanco);
    text-decoration: none;
    padding: 8px 12px;
    border-radius: 4px;
    font-size: 0.88rem;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.15s ease;
}
.nav-principal a:hover { background: rgba(255,255,255,0.15); }
.nav-principal a.activo { background: rgba(255,255,255,0.25); font-weight: 600; }

.busqueda-global { display: flex; gap: 0; }
.busqueda-global input {
    padding: 7px 12px;
    border: 1px solid transparent;
    border-radius: 4px 0 0 4px;
    font-size: 0.84rem;
    min-width: 220px;
    outline: none;
}
.busqueda-global button {
    border: none;
    background: rgba(255,255,255,0.2);
    color: var(--blanco);
    border-radius: 0 4px 4px 0;
    padding: 0 14px;
    cursor: pointer;
    font-size: 0.95rem;
}
.busqueda-global button:hover { background: rgba(255,255,255,0.35); }

.franja-corte {
    background: #e9eef3;
    border-bottom: 1px solid var(--gris-borde);
    padding: 8px 24px;
    font-size: 0.82rem;
    color: #515c68;
    display: flex;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 8px;
}
.franja-corte strong { color: var(--azul-utmach); }

.contenido { max-width: 1320px; margin: 0 auto; padding: 22px 24px; }
.seccion { display: none; }
.seccion.activa { display: block; animation: fadeIn 0.15s ease; }
@keyframes fadeIn { from { opacity: 0.8; } to { opacity: 1; } }

h1 { font-size: 1.35rem; margin: 0 0 16px; color: var(--azul-oscuro); font-weight: 600; }
h2 { font-size: 1.1rem; margin: 24px 0 12px; color: var(--azul-oscuro); font-weight: 600; }

.tarjetas {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 12px;
    margin-bottom: 24px;
}
.tarjeta {
    background: var(--blanco);
    border: 1px solid var(--gris-borde);
    border-radius: 8px;
    padding: 14px 16px;
    text-decoration: none;
    color: inherit;
    display: block;
    cursor: pointer;
    transition: transform 0.1s ease, border-color 0.15s ease, box-shadow 0.15s ease;
    box-shadow: 0 1px 3px rgba(0,0,0,0.03);
}
.tarjeta:hover {
    border-color: var(--azul-utmach);
    transform: translateY(-1px);
    box-shadow: 0 3px 6px rgba(0,0,0,0.06);
}
.tarjeta-valor { font-size: 1.75rem; font-weight: 700; color: var(--azul-oscuro); }
.tarjeta-etiqueta { font-size: 0.78rem; color: #5a6472; margin-top: 4px; font-weight: 600; text-transform: uppercase; }

.panel {
    background: var(--blanco);
    border: 1px solid var(--gris-borde);
    border-radius: 8px;
    padding: 18px;
    margin-bottom: 22px;
    overflow-x: auto;
    box-shadow: 0 1px 2px rgba(0,0,0,0.02);
}

.form-filtros { display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-end; margin-bottom: 16px; }
.form-filtros .campo { display: flex; flex-direction: column; gap: 4px; font-size: 0.8rem; }
.form-filtros label { color: #5a6472; font-weight: 600; }
.form-filtros select, .form-filtros input {
    padding: 7px 10px;
    border: 1px solid var(--gris-borde);
    border-radius: 4px;
    font-size: 0.85rem;
    min-width: 140px;
    background: #fff;
    outline: none;
}
.form-filtros input[type=text].busqueda { min-width: 260px; }

.btn {
    background: var(--azul-utmach);
    color: var(--blanco);
    border: 1px solid var(--azul-utmach);
    padding: 7px 16px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 0.85rem;
    font-weight: 600;
    text-decoration: none;
    display: inline-block;
}
.btn:hover { background: var(--azul-oscuro); border-color: var(--azul-oscuro); }
.btn-secundario { background: var(--blanco); color: var(--azul-utmach); border: 1px solid var(--azul-utmach); }
.btn-secundario:hover { background: #eef2f7; }

table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
th, td { padding: 9px 12px; border-bottom: 1px solid var(--gris-borde); text-align: left; }
th { background: #eef1f4; color: var(--azul-oscuro); position: sticky; top: 0; font-weight: 600; cursor: pointer; user-select: none; }
th:hover { background: #e3e8ed; }
tr:hover td { background: #f6f9fc; }
td.col-institucion { min-width: 240px; font-weight: 500; }

.estado { display: inline-flex; align-items: center; gap: 5px; font-size: 0.8rem; font-weight: 600; }
.estado.vigente { color: var(--verde); }
.estado.proximo { color: var(--amarillo); }
.estado.vencido { color: var(--rojo); }
.estado.sin-info { color: #6b7480; }

.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 0.72rem; font-weight: 600; margin-right: 4px; }
.badge-vigente { background: #e6f4ea; color: var(--verde); }
.badge-proximo { background: #fef7e0; color: var(--amarillo); }
.badge-vencido { background: #fce8e6; color: var(--rojo); }
.badge-sin_informacion { background: #eceff1; color: #5b6b78; }
.badge-revision { background: #fdecea; color: var(--naranja); }
.badge-adenda { background: #e8f0fb; color: var(--azul-info); }
.badge-conflicto { background: #fdecea; color: var(--rojo); }

.paginacion { display: flex; gap: 6px; margin-top: 16px; align-items: center; flex-wrap: wrap; font-size: 0.85rem; }
.paginacion button, .paginacion span {
    padding: 5px 11px;
    border: 1px solid var(--gris-borde);
    border-radius: 4px;
    background: #fff;
    cursor: pointer;
    font-size: 0.82rem;
}
.paginacion button:hover { background: #eef2f7; }
.paginacion .activa { background: var(--azul-utmach); color: var(--blanco); border-color: var(--azul-utmach); font-weight: 600; }

.grafico-barra { display: flex; align-items: center; gap: 10px; margin-bottom: 9px; }
.grafico-barra .etiqueta { width: 170px; font-size: 0.84rem; flex-shrink: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.grafico-barra .pista { flex: 1; background: #eef1f3; border-radius: 4px; height: 16px; overflow: hidden; }
.grafico-barra .relleno { background: var(--azul-utmach); height: 100%; border-radius: 4px; }
.grafico-barra .total { width: 42px; text-align: right; font-size: 0.82rem; color: #5a6472; font-weight: 600; }
.graficos-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 18px; margin-top: 14px; }

/* Modal */
.modal-fondo {
    display: none; position: fixed; inset: 0; background: rgba(16, 35, 61, 0.55); z-index: 1000;
    align-items: center; justify-content: center; padding: 20px;
}
.modal-fondo.visible { display: flex; }
.modal {
    background: #fff; border-radius: 8px; max-width: 720px; width: 100%; max-height: 88vh; overflow-y: auto;
    padding: 24px 28px; box-shadow: 0 10px 30px rgba(0,0,0,0.25);
}
.modal h3 { margin-top: 0; color: var(--azul-oscuro); font-size: 1.2rem; border-bottom: 2px solid var(--gris-borde); padding-bottom: 8px; }
.modal dl { display: grid; grid-template-columns: 170px 1fr; gap: 10px 14px; font-size: 0.88rem; margin: 16px 0; }
.modal dt { color: #5a6472; font-weight: 600; }
.modal dd { margin: 0; word-break: break-word; }
.modal .cerrar { float: right; background: none; border: none; font-size: 1.4rem; cursor: pointer; color: #5a6472; }

/* Tablero Kanban Solicitudes */
.kanban-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-top: 14px; }
.kanban-col { background: #edf1f5; border-radius: 6px; padding: 12px; min-height: 300px; }
.kanban-col h4 { margin: 0 0 10px; font-size: 0.88rem; color: var(--azul-oscuro); border-bottom: 2px solid var(--gris-borde); padding-bottom: 6px; display: flex; justify-content: space-between; }
.kanban-card { background: #fff; border: 1px solid var(--gris-borde); border-radius: 6px; padding: 10px; margin-bottom: 8px; font-size: 0.82rem; cursor: pointer; box-shadow: 0 1px 2px rgba(0,0,0,0.03); }
.kanban-card:hover { border-color: var(--azul-utmach); }
.kanban-card strong { display: block; color: var(--azul-oscuro); margin-bottom: 4px; font-size: 0.86rem; }

.semaforo-dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 4px; }
.semaforo-VERDE { background-color: var(--verde); }
.semaforo-AMARILLO { background-color: var(--amarillo); }
.semaforo-NARANJA { background-color: var(--naranja); }
.semaforo-ROJO { background-color: var(--rojo); }

.pie {
    text-align: center; padding: 20px 24px; color: #6b7480; font-size: 0.8rem;
    border-top: 1px solid var(--gris-borde); margin-top: 40px; background: #fff;
}
.alerta-box { padding: 12px 16px; border-radius: 6px; margin-bottom: 16px; font-size: 0.88rem; }
.alerta-info-box { background: #e8f0fb; border: 1px solid #bcd3ee; color: #1c4a7a; }
.alerta-warning-box { background: #fff4e5; border: 1px solid #fed7a2; color: #8a4b08; }
</style>
</head>
<body>

<header class="cabecera">
    <div class="cabecera-marca">
        <span class="cabecera-titulo">Sistema de Seguimiento de Convenios</span>
        <span class="cabecera-subtitulo">Universidad Técnica de Machala</span>
    </div>
    <nav class="nav-principal" id="navPrincipal">
        <a class="nav-link activo" onclick="cambiarVista('inicio')">Inicio</a>
        <a class="nav-link" onclick="cambiarVista('convenios')">Convenios</a>
        <a class="nav-link" onclick="cambiarVista('solicitudes')">📩 Solicitudes</a>
        <a class="nav-link" onclick="cambiarVista('pendientes')">⏳ Pendientes</a>
        <a class="nav-link" onclick="cambiarVista('mi-trabajo')">🗓 Mi trabajo</a>
        <a class="nav-link" onclick="cambiarVista('proximos-vencer')">Próximos a vencer</a>
        <a class="nav-link" onclick="cambiarVista('vencidos')">Vencidos</a>
        <a class="nav-link" onclick="cambiarVista('revision')">Revisión</a>
        <a class="nav-link" onclick="cambiarVista('sincronizacion')">Sincronización</a>
        <a class="nav-link" onclick="cambiarVista('configuracion')">⚙️ Configuración</a>
    </nav>
    <form class="busqueda-global" onsubmit="event.preventDefault(); buscarGlobal(this.q.value);">
        <input type="text" name="q" id="headerSearchInput" placeholder="Buscar convenio o solicitud...">
        <button type="submit" aria-label="Buscar">🔍</button>
    </form>
</header>

<div class="franja-corte">
    <span>Fotografía de consulta institucional — <strong>Repositorio de Solo Lectura</strong></span>
    <span>Fecha de corte: <strong>__FECHA_CORTE__</strong></span>
</div>

<main class="contenido">

    <!-- 1. VISTA INICIO -->
    <section id="vista-inicio" class="seccion activa">
        <h1>Convenios suscritos</h1>
        <div class="tarjetas">
            <div class="tarjeta" onclick="filtrarConvenios('todos')">
                <div class="tarjeta-valor" id="cnt-total">0</div>
                <div class="tarjeta-etiqueta">TOTAL DE CONVENIOS</div>
            </div>
            <div class="tarjeta" onclick="filtrarConvenios('VIGENTE')">
                <div class="tarjeta-valor" id="cnt-vigentes">🟢 0</div>
                <div class="tarjeta-etiqueta">VIGENTES</div>
            </div>
            <div class="tarjeta" onclick="cambiarVista('proximos-vencer')">
                <div class="tarjeta-valor" id="cnt-proximos">🟡 0</div>
                <div class="tarjeta-etiqueta">PRÓXIMOS A VENCER</div>
            </div>
            <div class="tarjeta" onclick="cambiarVista('vencidos')">
                <div class="tarjeta-valor" id="cnt-vencidos">🔴 0</div>
                <div class="tarjeta-etiqueta">VENCIDOS</div>
            </div>
            <div class="tarjeta" onclick="filtrarConvenios('SIN_INFORMACION')">
                <div class="tarjeta-valor" id="cnt-sin_info">⚪ 0</div>
                <div class="tarjeta-etiqueta">SIN INFORMACIÓN</div>
            </div>
            <div class="tarjeta" onclick="cambiarVista('revision')">
                <div class="tarjeta-valor" id="cnt-revision">🟠 0</div>
                <div class="tarjeta-etiqueta">REQUIEREN REVISIÓN</div>
            </div>
            <div class="tarjeta" onclick="filtrarConvenios('adenda')">
                <div class="tarjeta-valor" id="cnt-adenda">🔵 0</div>
                <div class="tarjeta-etiqueta">POSIBLE ADENDA</div>
            </div>
        </div>

        <h2>Próximos a vencer (menor días restantes primero)</h2>
        <div class="panel">
            <table id="tabla-proximos-top">
                <thead>
                    <tr><th>Institución</th><th>Tipo</th><th>Vencimiento</th><th>Días restantes</th><th>Administrador</th></tr>
                </thead>
                <tbody id="tbody-proximos-top"></tbody>
            </table>
            <p style="margin-top:12px;"><button class="btn btn-secundario" onclick="cambiarVista('proximos-vencer')">Ver todos los próximos a vencer</button></p>
        </div>

        <h1>Solicitudes en trámite</h1>
        <p style="color:#5a6472; margin:-8px 0 14px; font-size:0.86rem;">Universo independiente de convenios suscritos — trámites previos a firma.</p>
        <div class="tarjetas">
            <div class="tarjeta" onclick="cambiarVista('solicitudes')">
                <div class="tarjeta-valor" id="cnt-sol-total">0</div>
                <div class="tarjeta-etiqueta">TOTAL EN TRÁMITE</div>
            </div>
            <div class="tarjeta" onclick="cambiarVista('solicitudes')">
                <div class="tarjeta-valor" id="cnt-sol-recibidas">0</div>
                <div class="tarjeta-etiqueta">RECIBIDAS</div>
            </div>
            <div class="tarjeta" onclick="cambiarVista('solicitudes')">
                <div class="tarjeta-valor" id="cnt-sol-gestion">0</div>
                <div class="tarjeta-etiqueta">EN GESTIÓN</div>
            </div>
            <div class="tarjeta" onclick="cambiarVista('pendientes')">
                <div class="tarjeta-valor" id="cnt-sol-pendientes">⏳ 0</div>
                <div class="tarjeta-etiqueta">PENDIENTES</div>
            </div>
            <div class="tarjeta" onclick="cambiarVista('solicitudes')">
                <div class="tarjeta-valor" id="cnt-sol-juridico">0</div>
                <div class="tarjeta-etiqueta">EN JURÍDICO</div>
            </div>
            <div class="tarjeta" onclick="cambiarVista('solicitudes')">
                <div class="tarjeta-valor" id="cnt-sol-factibilidad">0</div>
                <div class="tarjeta-etiqueta">EN FACTIBILIDAD</div>
            </div>
            <div class="tarjeta" onclick="cambiarVista('solicitudes')">
                <div class="tarjeta-valor" id="cnt-sol-firma">0</div>
                <div class="tarjeta-etiqueta">EN FIRMA</div>
            </div>
            <div class="tarjeta" onclick="cambiarVista('solicitudes')">
                <div class="tarjeta-valor" id="cnt-sol-sinmov">🔴 0</div>
                <div class="tarjeta-etiqueta">SIN MOVIMIENTO</div>
            </div>
        </div>

        <h2>Estadísticas de convenios</h2>
        <div class="graficos-grid">
            <div class="panel">
                <h3 style="margin-top:0; color:var(--azul-oscuro); font-size:0.95rem;">Distribución por Año</h3>
                <div id="grafico-anios"></div>
            </div>
            <div class="panel">
                <h3 style="margin-top:0; color:var(--azul-oscuro); font-size:0.95rem;">Distribución por Tipo</h3>
                <div id="grafico-tipos"></div>
            </div>
            <div class="panel">
                <h3 style="margin-top:0; color:var(--azul-oscuro); font-size:0.95rem;">Distribución por Estado</h3>
                <div id="grafico-estados"></div>
            </div>
        </div>
    </section>

    <!-- 2. VISTA CONVENIOS -->
    <section id="vista-convenios" class="seccion">
        <h1>Convenios (<span id="total-convenios-filtrados">0</span>)</h1>

        <form class="form-filtros" id="form-filtros-convenios" onsubmit="event.preventDefault(); aplicarFiltros();">
            <div class="campo">
                <label>Buscar</label>
                <input type="text" class="busqueda" id="filtro-q" placeholder="institución, código, tipo, administrador...">
            </div>
            <div class="campo">
                <label>Año</label>
                <select id="filtro-anio"><option value="">Todos</option></select>
            </div>
            <div class="campo">
                <label>Tipo</label>
                <select id="filtro-tipo"><option value="">Todos</option></select>
            </div>
            <div class="campo">
                <label>Estado de vigencia</label>
                <select id="filtro-estado">
                    <option value="">Todos</option>
                    <option value="VIGENTE">Vigente</option>
                    <option value="PROXIMO_A_VENCER">Próximo a vencer</option>
                    <option value="VENCIDO">Vencido</option>
                    <option value="SIN_INFORMACION">Sin información suficiente</option>
                </select>
            </div>
            <div class="campo">
                <label>Administrador</label>
                <select id="filtro-admin"><option value="">Todos</option></select>
            </div>
            <div class="campo">
                <label>Tiene adenda</label>
                <select id="filtro-adenda">
                    <option value="">Todos</option>
                    <option value="SI">Sí</option>
                    <option value="POR_REVISAR">Por revisar</option>
                    <option value="NO">No</option>
                </select>
            </div>
            <div class="campo">
                <label>Requiere revisión</label>
                <select id="filtro-revision">
                    <option value="">Todos</option>
                    <option value="SI">Sí</option>
                    <option value="NO">No</option>
                </select>
            </div>
            <button class="btn" type="submit">Filtrar</button>
            <button class="btn btn-secundario" type="button" onclick="limpiarFiltros()">Limpiar filtros</button>
        </form>

        <div class="panel">
            <table>
                <thead>
                    <tr>
                        <th onclick="ordenarPor('codigo')">Código <span id="sort-codigo"></span></th>
                        <th onclick="ordenarPor('anio')">Año <span id="sort-anio"></span></th>
                        <th onclick="ordenarPor('institucion')">Institución <span id="sort-institucion"></span></th>
                        <th onclick="ordenarPor('tipo')">Tipo <span id="sort-tipo"></span></th>
                        <th onclick="ordenarPor('fecha_suscripcion')">F. suscripción <span id="sort-fecha_suscripcion"></span></th>
                        <th onclick="ordenarPor('fecha_terminacion')">F. terminación <span id="sort-fecha_terminacion"></span></th>
                        <th onclick="ordenarPor('estado_vigencia')">Estado <span id="sort-estado_vigencia"></span></th>
                        <th onclick="ordenarPor('dias')">Días <span id="sort-dias"></span></th>
                        <th onclick="ordenarPor('administrador')">Administrador <span id="sort-administrador"></span></th>
                        <th>Documento</th>
                        <th>Revisión</th>
                    </tr>
                </thead>
                <tbody id="tbody-convenios"></tbody>
            </table>
            <div class="paginacion" id="paginacion-convenios"></div>
        </div>
    </section>

    <!-- 3. VISTA SOLICITUDES -->
    <section id="vista-solicitudes" class="seccion">
        <h1>📩 Solicitudes en trámite (<span id="total-solicitudes">0</span>)</h1>
        <div class="alerta-box alerta-info-box">
            Módulo de trazabilidad y gestión de convenios desde su ingreso hasta la suscripción.
        </div>
        <div class="kanban-grid" id="kanban-solicitudes"></div>
    </section>

    <!-- 4. VISTA PENDIENTES -->
    <section id="vista-pendientes" class="seccion">
        <h1>⏳ Pendientes de respuesta</h1>
        <div class="panel">
            <div id="lista-pendientes-contenido">
                <p style="color:#5a6472;">No hay trámites pendientes con criterio en espera de respuesta en este momento.</p>
            </div>
        </div>
    </section>

    <!-- 5. VISTA MI TRABAJO -->
    <section id="vista-mi-trabajo" class="seccion">
        <h1>🗓 Mi trabajo y alertas prioritarias</h1>
        <div class="panel">
            <h3 style="margin-top:0; color:var(--azul-oscuro);">Atención prioritaria de convenios y trámites</h3>
            <p>Se listan a continuación los convenios con vencimiento más inmediato y las alertas activas:</p>
            <table id="tabla-mi-trabajo">
                <thead>
                    <tr><th>Tipo</th><th>Institución</th><th>Estado</th><th>Detalle de atención</th></tr>
                </thead>
                <tbody id="tbody-mi-trabajo"></tbody>
            </table>
        </div>
    </section>

    <!-- 6. VISTA PRÓXIMOS A VENCER -->
    <section id="vista-proximos-vencer" class="seccion">
        <h1>🟡 Convenios próximos a vencer</h1>
        <div class="panel">
            <table>
                <thead>
                    <tr><th>Código</th><th>Institución</th><th>Tipo</th><th>F. Terminación</th><th>Días restantes</th><th>Administrador</th></tr>
                </thead>
                <tbody id="tbody-proximos-lista"></tbody>
            </table>
        </div>
    </section>

    <!-- 7. VISTA VENCIDOS -->
    <section id="vista-vencidos" class="seccion">
        <h1>🔴 Convenios vencidos</h1>
        <div class="panel">
            <table>
                <thead>
                    <tr><th>Código</th><th>Año</th><th>Institución</th><th>Tipo</th><th>F. Terminación</th><th>Administrador</th></tr>
                </thead>
                <tbody id="tbody-vencidos-lista"></tbody>
            </table>
        </div>
    </section>

    <!-- 8. VISTA REVISIÓN PENDIENTE -->
    <section id="vista-revision" class="seccion">
        <h1>🟠 Convenios que requieren revisión</h1>
        <div class="panel">
            <table>
                <thead>
                    <tr><th>Código</th><th>Año</th><th>Institución</th><th>Motivo de revisión</th><th>Administrador</th></tr>
                </thead>
                <tbody id="tbody-revision-lista"></tbody>
            </table>
        </div>
    </section>

    <!-- 9. VISTA SINCRONIZACIÓN -->
    <section id="vista-sincronizacion" class="seccion">
        <h1>🔄 Estado de Sincronización documental</h1>
        <div class="panel">
            <h3 style="margin-top:0; color:var(--azul-oscuro);">Base de datos maestra SQLite</h3>
            <p><strong>Fuente institucional:</strong> <code>BASE_DATOS/convenios.db</code></p>
            <p><strong>Total de convenios catalogados:</strong> <span id="sync-total-convenios"></span></p>
            <p><strong>Fecha de corte:</strong> __FECHA_CORTE__</p>
            <div class="alerta-box alerta-info-box">
                El repositorio documental es de <strong>SOLO LECTURA</strong>. Todas las extracciones, auditorías y cruces se realizan preservando los documentos originales intactos.
            </div>
        </div>
    </section>

    <!-- 10. VISTA CONFIGURACIÓN -->
    <section id="vista-configuracion" class="seccion">
        <h1>⚙️ Configuración del Sistema</h1>
        <div class="panel">
            <h3 style="margin-top:0; color:var(--azul-oscuro);">Semáforos y Umbrales Institucionales</h3>
            <dl style="display:grid; grid-template-columns: 240px 1fr; gap:10px; font-size:0.9rem;">
                <dt>🟡 Próximo a vencer:</dt><dd>Convenios a 90 días o menos de su fecha de terminación.</dd>
                <dt>🟢 Trámite en tiempo normal:</dt><dd>Hasta 5 días sin movimiento.</dd>
                <dt>🟡 Trámite en atención:</dt><dd>De 6 a 14 días sin movimiento.</dd>
                <dt>🔴 Trámite demorado:</dt><dd>Más de 14 días sin movimiento.</dd>
                <dt>Motor de visualización:</dt><dd>Web de Consulta Autocontenida (Fase 6.5 & GitHub Pages).</dd>
            </dl>
        </div>
    </section>

</main>

<!-- Modal Ficha de Convenio -->
<div class="modal-fondo" id="modal-convenio" onclick="if(event.target===this) cerrarModal();">
    <div class="modal">
        <button class="cerrar" onclick="cerrarModal()">&times;</button>
        <h3 id="modal-titulo">Ficha del Convenio</h3>
        <dl id="modal-datos"></dl>
        <div id="modal-alertas"></div>
        <div style="text-align:right; margin-top:20px;">
            <button class="btn" onclick="cerrarModal()">Cerrar</button>
        </div>
    </div>
</div>

<footer class="pie">
    Sistema de Seguimiento de Convenios — Universidad Técnica de Machala (UTMACH)<br>
    Fuente documental de solo lectura — ningún archivo original es modificado por este sistema.
</footer>

<script>
const DATOS = __DATOS_JSON__;

let vistaActual = 'inicio';
let conveniosFiltrados = [...DATOS.convenios];
let paginaActual = 1;
const POR_PAGINA = 50;
let campoOrden = 'anio';
let direccionOrden = 'desc';

function init() {
    // Rellenar contadores
    const c = DATOS.contadores_convenios;
    document.getElementById('cnt-total').textContent = c.total;
    document.getElementById('cnt-vigentes').textContent = '🟢 ' + c.vigentes;
    document.getElementById('cnt-proximos').textContent = '🟡 ' + c.proximos_a_vencer;
    document.getElementById('cnt-vencidos').textContent = '🔴 ' + c.vencidos;
    document.getElementById('cnt-sin_info').textContent = '⚪ ' + c.sin_informacion;
    document.getElementById('cnt-revision').textContent = '🟠 ' + c.requieren_revision;
    document.getElementById('cnt-adenda').textContent = '🔵 ' + c.posible_adenda;

    const cs = DATOS.contadores_solicitudes;
    document.getElementById('cnt-sol-total').textContent = cs.total;
    document.getElementById('cnt-sol-recibidas').textContent = cs.recibidas || 0;
    document.getElementById('cnt-sol-gestion').textContent = cs.en_gestion || 0;
    document.getElementById('cnt-sol-pendientes').textContent = '⏳ ' + (cs.pendientes_respuesta || 0);
    document.getElementById('cnt-sol-juridico').textContent = cs.en_juridico || 0;
    document.getElementById('cnt-sol-factibilidad').textContent = cs.en_factibilidad || 0;
    document.getElementById('cnt-sol-firma').textContent = cs.en_firma || 0;
    document.getElementById('cnt-sol-sinmov').textContent = '🔴 ' + (cs.sin_movimiento || 0);
    document.getElementById('total-solicitudes').textContent = cs.total;
    document.getElementById('sync-total-convenios').textContent = c.total;

    // Rellenar selectores de filtro
    const selAnio = document.getElementById('filtro-anio');
    DATOS.disponibles.anios.forEach(a => {
        selAnio.innerHTML += `<option value="${a}">${a}</option>`;
    });

    const selTipo = document.getElementById('filtro-tipo');
    DATOS.disponibles.tipos.forEach(t => {
        selTipo.innerHTML += `<option value="${t}">${t}</option>`;
    });

    const selAdmin = document.getElementById('filtro-admin');
    DATOS.disponibles.administradores.forEach(adm => {
        selAdmin.innerHTML += `<option value="${adm}">${adm}</option>`;
    });

    // Renderizar tablas
    renderizarProximosTop();
    renderizarGraficos();
    renderizarConvenios();
    renderizarSolicitudesKanban();
    renderizarVistasEspeciales();

    // Comprobar fragmento en URL
    const partesUrl = window.location.href.split('#');
    if (partesUrl.length > 1 && partesUrl[1]) {
        cambiarVista(partesUrl[1]);
    }
}

function cambiarVista(nombre) {
    vistaActual = nombre;
    document.querySelectorAll('.seccion').forEach(s => s.classList.remove('activa'));
    const sec = document.getElementById('vista-' + nombre);
    if (sec) sec.classList.add('activa');

    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('activo'));
    document.querySelectorAll('.nav-link').forEach(l => {
        if (l.getAttribute('onclick') && l.getAttribute('onclick').includes(nombre)) {
            l.classList.add('activo');
        }
    });

    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function renderizarProximosTop() {
    const tbody = document.getElementById('tbody-proximos-top');
    tbody.innerHTML = '';
    if (!DATOS.proximos_top || DATOS.proximos_top.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:#5a6472;">No hay convenios próximos a vencer.</td></tr>';
        return;
    }
    DATOS.proximos_top.forEach(c => {
        const tr = document.createElement('tr');
        tr.style.cursor = 'pointer';
        tr.onclick = () => abrirModal(c);
        tr.innerHTML = `
            <td class="col-institucion">${escapeHtml(c.institucion)}</td>
            <td>${escapeHtml(c.tipo)}</td>
            <td>${c.fecha_terminacion || '—'}</td>
            <td><strong>${c.dias}</strong></td>
            <td>${escapeHtml(c.administrador)}</td>
        `;
        tbody.appendChild(tr);
    });
}

function renderizarGraficos() {
    function dibujarBarras(contenedorId, lista) {
        const cont = document.getElementById(contenedorId);
        if (!cont) return;
        cont.innerHTML = '';
        const max = Math.max(...lista.map(i => i.total), 1);
        lista.slice(0, 7).forEach(i => {
            const pct = Math.round((i.total / max) * 100);
            cont.innerHTML += `
                <div class="grafico-barra">
                    <div class="etiqueta" title="${escapeHtml(i.etiqueta)}">${escapeHtml(i.etiqueta)}</div>
                    <div class="pista"><div class="relleno" style="width:${pct}%"></div></div>
                    <div class="total">${i.total}</div>
                </div>
            `;
        });
    }
    dibujarBarras('grafico-anios', DATOS.graficos.por_anio);
    dibujarBarras('grafico-tipos', DATOS.graficos.por_tipo);
    dibujarBarras('grafico-estados', DATOS.graficos.por_estado);
}

function filtrarConvenios(estado) {
    limpiarFiltros(false);
    if (estado === 'VIGENTE' || estado === 'PROXIMO_A_VENCER' || estado === 'VENCIDO' || estado === 'SIN_INFORMACION') {
        document.getElementById('filtro-estado').value = estado;
    } else if (estado === 'adenda') {
        document.getElementById('filtro-adenda').value = 'SI';
    }
    aplicarFiltros();
    cambiarVista('convenios');
}

function aplicarFiltros() {
    const q = document.getElementById('filtro-q').value.trim().toLowerCase();
    const anio = document.getElementById('filtro-anio').value;
    const tipo = document.getElementById('filtro-tipo').value;
    const estado = document.getElementById('filtro-estado').value;
    const admin = document.getElementById('filtro-admin').value;
    const adenda = document.getElementById('filtro-adenda').value;
    const revision = document.getElementById('filtro-revision').value;

    conveniosFiltrados = DATOS.convenios.filter(c => {
        if (q) {
            const txt = `${c.codigo} ${c.institucion} ${c.tipo} ${c.administrador} ${c.objeto} ${c.anio}`.toLowerCase();
            if (!txt.includes(q)) return false;
        }
        if (anio && String(c.anio) !== anio) return false;
        if (tipo && c.tipo !== tipo) return false;
        if (estado && c.estado_vigencia !== estado) return false;
        if (admin && c.administrador !== admin) return false;
        if (adenda && c.adenda !== adenda) return false;
        if (revision === 'SI' && !c.revision) return false;
        if (revision === 'NO' && c.revision) return false;
        return true;
    });

    paginaActual = 1;
    ordenarLista();
    renderizarConvenios();
}

function limpiarFiltros(render = true) {
    document.getElementById('filtro-q').value = '';
    document.getElementById('filtro-anio').value = '';
    document.getElementById('filtro-tipo').value = '';
    document.getElementById('filtro-estado').value = '';
    document.getElementById('filtro-admin').value = '';
    document.getElementById('filtro-adenda').value = '';
    document.getElementById('filtro-revision').value = '';
    conveniosFiltrados = [...DATOS.convenios];
    paginaActual = 1;
    if (render) {
        ordenarLista();
        renderizarConvenios();
    }
}

function ordenarPor(campo) {
    if (campoOrden === campo) {
        direccionOrden = direccionOrden === 'asc' ? 'desc' : 'asc';
    } else {
        campoOrden = campo;
        direccionOrden = (campo === 'anio' || campo === 'fecha_suscripcion' || campo === 'fecha_terminacion') ? 'desc' : 'asc';
    }
    ordenarLista();
    renderizarConvenios();
}

function ordenarLista() {
    ['codigo', 'anio', 'institucion', 'tipo', 'fecha_suscripcion', 'fecha_terminacion', 'estado_vigencia', 'dias', 'administrador'].forEach(c => {
        const el = document.getElementById('sort-' + c);
        if (el) el.textContent = (campoOrden === c) ? (direccionOrden === 'asc' ? '▲' : '▼') : '';
    });

    conveniosFiltrados.sort((a, b) => {
        let va = a[campoOrden] ?? '';
        let vb = b[campoOrden] ?? '';
        if (campoOrden === 'dias') {
            va = a.dias !== null ? a.dias : 999999;
            vb = b.dias !== null ? b.dias : 999999;
            return direccionOrden === 'asc' ? va - vb : vb - va;
        }
        if (typeof va === 'number' && typeof vb === 'number') {
            return direccionOrden === 'asc' ? va - vb : vb - va;
        }
        return direccionOrden === 'asc' ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
    });
}

function renderizarConvenios() {
    document.getElementById('total-convenios-filtrados').textContent = conveniosFiltrados.length;
    const tbody = document.getElementById('tbody-convenios');
    tbody.innerHTML = '';

    if (conveniosFiltrados.length === 0) {
        tbody.innerHTML = '<tr><td colspan="11" style="text-align:center; padding:24px; color:#5a6472;">No se encontraron convenios con los filtros seleccionados.</td></tr>';
        document.getElementById('paginacion-convenios').innerHTML = '';
        return;
    }

    const inicio = (paginaActual - 1) * POR_PAGINA;
    const paginaItems = conveniosFiltrados.slice(inicio, inicio + POR_PAGINA);

    paginaItems.forEach(c => {
        const tr = document.createElement('tr');
        tr.style.cursor = 'pointer';
        tr.onclick = () => abrirModal(c);

        let badgeEstado = `<span class="badge badge-${c.estado_vigencia.toLowerCase()}">${c.estado_etiqueta}</span>`;
        let badgeRevision = c.revision ? `<span class="badge badge-revision">Revisión</span>` : '—';
        if (c.adenda === 'SI' || c.adenda === 'POR_REVISAR') {
            badgeRevision += ` <span class="badge badge-adenda">Adenda</span>`;
        }
        if (c.conflicto === 'SI') {
            badgeRevision += ` <span class="badge badge-conflicto">Conflicto</span>`;
        }

        tr.innerHTML = `
            <td>${escapeHtml(c.codigo)}</td>
            <td>${c.anio || '—'}</td>
            <td class="col-institucion">${escapeHtml(c.institucion)}</td>
            <td>${escapeHtml(c.tipo)}</td>
            <td>${c.fecha_suscripcion || '—'}</td>
            <td>${c.fecha_terminacion || '—'}</td>
            <td>${badgeEstado}</td>
            <td>${c.dias !== null ? c.dias : '—'}</td>
            <td>${escapeHtml(c.administrador)}</td>
            <td>${c.expediente_disponible ? '📄 Sí' : '—'}</td>
            <td>${badgeRevision}</td>
        `;
        tbody.appendChild(tr);
    });

    renderizarPaginacion();
}

function renderizarPaginacion() {
    const totalPaginas = Math.ceil(conveniosFiltrados.length / POR_PAGINA);
    const pagCont = document.getElementById('paginacion-convenios');
    if (totalPaginas <= 1) {
        pagCont.innerHTML = `<span>Mostrando ${conveniosFiltrados.length} convenios</span>`;
        return;
    }

    let html = `<span>Página ${paginaActual} de ${totalPaginas} (${conveniosFiltrados.length} convenios):</span> `;
    if (paginaActual > 1) {
        html += `<button onclick="irAPagina(${paginaActual - 1})">« Anterior</button> `;
    }

    let pMin = Math.max(1, paginaActual - 3);
    let pMax = Math.min(totalPaginas, paginaActual + 3);
    for (let p = pMin; p <= pMax; p++) {
        html += `<button class="${p === paginaActual ? 'activa' : ''}" onclick="irAPagina(${p})">${p}</button> `;
    }

    if (paginaActual < totalPaginas) {
        html += `<button onclick="irAPagina(${paginaActual + 1})">Siguiente »</button>`;
    }
    pagCont.innerHTML = html;
}

function irAPagina(p) {
    paginaActual = p;
    renderizarConvenios();
    document.getElementById('tbody-convenios').scrollIntoView({ behavior: 'smooth' });
}

function renderizarSolicitudesKanban() {
    const grid = document.getElementById('kanban-solicitudes');
    grid.innerHTML = '';
    const etapas = [
        { key: 'RECIBIDA', titulo: 'Recibida' },
        { key: 'EN_GESTION', titulo: 'En Gestión' },
        { key: 'REVISION_JURIDICA', titulo: 'Revisión Jurídica' },
        { key: 'FACTIBILIDAD', titulo: 'Factibilidad' },
        { key: 'FIRMA', titulo: 'Firma' },
        { key: 'SUSCRITO', titulo: 'Suscrito' },
    ];

    etapas.forEach(e => {
        const col = document.createElement('div');
        col.className = 'kanban-col';
        const items = DATOS.solicitudes.filter(s => (s.etapa_codigo === e.key || s.estado_codigo === e.key));
        col.innerHTML = `<h4>${e.titulo} <span>(${items.length})</span></h4>`;
        if (items.length === 0) {
            col.innerHTML += `<div style="color:#5a6472; font-style:italic; font-size:0.78rem; padding:10px 0;">Sin trámites en esta etapa</div>`;
        } else {
            items.forEach(s => {
                col.innerHTML += `
                    <div class="kanban-card">
                        <strong>${escapeHtml(s.institucion)}</strong>
                        <div>Código: ${escapeHtml(s.codigo)}</div>
                        <div>Resp: ${escapeHtml(s.responsable)}</div>
                        <div style="margin-top:4px;"><span class="semaforo-dot semaforo-${s.semaforo}"></span> ${s.dias_sin_movimiento} días sin mov.</div>
                    </div>
                `;
            });
        }
        grid.appendChild(col);
    });
}

function renderizarVistasEspeciales() {
    // 1. Proximos a vencer
    const tbodyProx = document.getElementById('tbody-proximos-lista');
    const proximos = DATOS.convenios.filter(c => c.estado_vigencia === 'PROXIMO_A_VENCER').sort((a,b) => (a.dias||0) - (b.dias||0));
    tbodyProx.innerHTML = '';
    proximos.forEach(c => {
        tbodyProx.innerHTML += `
            <tr style="cursor:pointer;" onclick="abrirModalPorId('${c.id}')">
                <td>${escapeHtml(c.codigo)}</td>
                <td class="col-institucion">${escapeHtml(c.institucion)}</td>
                <td>${escapeHtml(c.tipo)}</td>
                <td>${c.fecha_terminacion || '—'}</td>
                <td><strong>🟡 ${c.dias} días</strong></td>
                <td>${escapeHtml(c.administrador)}</td>
            </tr>
        `;
    });

    // 2. Vencidos
    const tbodyVenc = document.getElementById('tbody-vencidos-lista');
    const vencidos = DATOS.convenios.filter(c => c.estado_vigencia === 'VENCIDO');
    tbodyVenc.innerHTML = '';
    vencidos.slice(0, 100).forEach(c => {
        tbodyVenc.innerHTML += `
            <tr style="cursor:pointer;" onclick="abrirModalPorId('${c.id}')">
                <td>${escapeHtml(c.codigo)}</td>
                <td>${c.anio}</td>
                <td class="col-institucion">${escapeHtml(c.institucion)}</td>
                <td>${escapeHtml(c.tipo)}</td>
                <td>${c.fecha_terminacion || '—'}</td>
                <td>${escapeHtml(c.administrador)}</td>
            </tr>
        `;
    });

    // 3. Revision
    const tbodyRev = document.getElementById('tbody-revision-lista');
    const revisiones = DATOS.convenios.filter(c => c.revision);
    tbodyRev.innerHTML = '';
    revisiones.forEach(c => {
        const motivos = c.descripciones_revision.join(', ') || 'Revisión documental';
        tbodyRev.innerHTML += `
            <tr style="cursor:pointer;" onclick="abrirModalPorId('${c.id}')">
                <td>${escapeHtml(c.codigo)}</td>
                <td>${c.anio}</td>
                <td class="col-institucion">${escapeHtml(c.institucion)}</td>
                <td><span class="badge badge-revision">${escapeHtml(motivos)}</span></td>
                <td>${escapeHtml(c.administrador)}</td>
            </tr>
        `;
    });

    // 4. Mi trabajo
    const tbodyTrab = document.getElementById('tbody-mi-trabajo');
    tbodyTrab.innerHTML = '';
    proximos.slice(0, 10).forEach(c => {
        tbodyTrab.innerHTML += `
            <tr style="cursor:pointer;" onclick="abrirModalPorId('${c.id}')">
                <td>Convenio</td>
                <td class="col-institucion">${escapeHtml(c.institucion)}</td>
                <td><span class="badge badge-proximo">🟡 Próximo a vencer</span></td>
                <td>Vence en <strong>${c.dias} días</strong> (${c.fecha_terminacion})</td>
            </tr>
        `;
    });
}

function abrirModal(c) {
    document.getElementById('modal-titulo').textContent = c.institucion + ' (' + (c.codigo || 'S/N') + ')';
    const dl = document.getElementById('modal-datos');
    dl.innerHTML = `
        <dt>Institución:</dt><dd>${escapeHtml(c.institucion)}</dd>
        <dt>Código / Número:</dt><dd>${escapeHtml(c.codigo)}</dd>
        <dt>Año:</dt><dd>${c.anio || '—'}</dd>
        <dt>Tipo de instrumento:</dt><dd>${escapeHtml(c.tipo)}</dd>
        <dt>Estado de vigencia:</dt><dd><span class="badge badge-${c.estado_vigencia.toLowerCase()}">${c.estado_etiqueta}</span></dd>
        <dt>Fecha suscripción:</dt><dd>${c.fecha_suscripcion || '—'}</dd>
        <dt>Fecha terminación:</dt><dd>${c.fecha_terminacion || '—'} ${c.dias !== null ? `(${c.dias} días restantes)` : ''}</dd>
        <dt>Administrador:</dt><dd>${escapeHtml(c.administrador)}</dd>
        <dt>Objeto:</dt><dd>${escapeHtml(c.objeto) || '—'}</dd>
        <dt>Expediente digital:</dt><dd>${c.expediente_disponible ? 'Disponible en repositorio institucional' : 'No localizado'}</dd>
    `;

    const divAlertas = document.getElementById('modal-alertas');
    divAlertas.innerHTML = '';
    if (c.revision && c.descripciones_revision.length > 0) {
        divAlertas.innerHTML = `
            <div class="alerta-box alerta-warning-box" style="margin-top:14px;">
                <strong>Observaciones de control de calidad:</strong>
                <ul style="margin:6px 0 0; padding-left:20px;">
                    ${c.descripciones_revision.map(m => `<li>${escapeHtml(m)}</li>`).join('')}
                </ul>
            </div>
        `;
    }

    document.getElementById('modal-convenio').classList.add('visible');
}

function abrirModalPorId(id) {
    const c = DATOS.convenios.find(item => String(item.id) === String(id));
    if (c) abrirModal(c);
}

function cerrarModal() {
    document.getElementById('modal-convenio').classList.remove('visible');
}

function buscarGlobal(texto) {
    if (!texto.trim()) return;
    document.getElementById('filtro-q').value = texto;
    aplicarFiltros();
    cambiarVista('convenios');
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

window.addEventListener('DOMContentLoaded', init);
</script>
</body>
</html>
"""
