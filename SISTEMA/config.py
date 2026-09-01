"""Carga la configuracion del sistema desde CONFIGURACION/config.json."""

import json
from pathlib import Path

RUTA_SISTEMA_DIR = Path(__file__).resolve().parent          # .../SISTEMA_SEGUIMIENTO_CONVENIOS/SISTEMA
RUTA_RAIZ_SEGUIMIENTO = RUTA_SISTEMA_DIR.parent               # .../SISTEMA_SEGUIMIENTO_CONVENIOS
RUTA_CONFIG_JSON = RUTA_RAIZ_SEGUIMIENTO / "CONFIGURACION" / "config.json"


class Config:
    def __init__(self, datos: dict):
        self.ruta_base_convenios = Path(datos["ruta_base_convenios"])
        self.carpeta_sistema = datos["carpeta_sistema"]
        self.anios_analizar = list(datos["anios_analizar"])
        self.extensiones_matriz = set(e.lower() for e in datos["extensiones_matriz"])
        self.extensiones_ignoradas = set(e.lower() for e in datos["extensiones_ignoradas"])
        self.umbral_dias_proximo_vencer = int(datos["umbral_dias_proximo_vencer"])
        self.muestra_paginas_pdf = int(datos["muestra_paginas_pdf_para_clasificar"])
        self.min_caracteres_texto = int(datos["min_caracteres_texto_para_no_escaneado"])

        # Rutas derivadas, todas DENTRO de la carpeta del sistema (nunca en el repositorio original)
        self.ruta_sistema_seguimiento = self.ruta_base_convenios / self.carpeta_sistema
        self.ruta_base_datos = self.ruta_sistema_seguimiento / "BASE_DATOS" / "convenios_sistema.db"
        self.ruta_logs = self.ruta_sistema_seguimiento / "LOGS"
        self.ruta_reportes = self.ruta_sistema_seguimiento / "REPORTES"
        self.ruta_exportaciones = self.ruta_sistema_seguimiento / "EXPORTACIONES"
        self.ruta_convenios_db = self.ruta_sistema_seguimiento / "BASE_DATOS" / "convenios.db"
        self.ruta_excel_maestro = self.ruta_sistema_seguimiento / "BASE_DATOS" / "BASE_MAESTRA_CONVENIOS_2020_2026.xlsx"
        self.ruta_respaldos = self.ruta_sistema_seguimiento / "RESPALDOS"
        self.ruta_tramites = self.ruta_sistema_seguimiento / "TRAMITES"
        self.ruta_excel_solicitudes = self.ruta_sistema_seguimiento / "BASE_DATOS" / "REPORTE_SOLICITUDES.xlsx"

        # Dashboard ejecutivo portable (Fase 6.5): un unico HTML autocontenido,
        # nunca escrito fuera de esta subcarpeta.
        self.ruta_dashboard_ejecutivo = self.ruta_sistema_seguimiento / "DASHBOARD_EJECUTIVO"
        self.ruta_dashboard_ejecutivo_html = self.ruta_dashboard_ejecutivo / "DASHBOARD_CONVENIOS_UTMACH.html"
        self.ruta_dashboard_ejecutivo_historico = self.ruta_dashboard_ejecutivo / "HISTORICO"

        # Parametros de la aplicacion web (host/puerto/entorno), separados de
        # rutas de datos para no asumir siempre 127.0.0.1 (preparacion para
        # una futura version multiusuario desplegada en otro host).
        app_cfg = datos.get("aplicacion", {})
        self.app_host = app_cfg.get("host", "127.0.0.1")
        self.app_puerto = int(app_cfg.get("puerto", 5000))
        self.app_entorno = app_cfg.get("entorno", "desarrollo")

        # Parametros configurables del modulo de solicitudes (Fase 5): nunca
        # se hardcodean como normas fijas, viven en config.json.
        sol_cfg = datos.get("solicitudes", {})
        self.umbral_dias_habiles_pendiente_respuesta = int(sol_cfg.get("umbral_dias_habiles_pendiente_respuesta", 5))
        semaforo = sol_cfg.get("semaforo_dias", {})
        self.semaforo_normal_max = int(semaforo.get("normal_max", 3))
        self.semaforo_atencion_max = int(semaforo.get("atencion_max", 7))
        self.semaforo_demora_max = int(semaforo.get("demora_max", 14))


def cargar_config() -> Config:
    with open(RUTA_CONFIG_JSON, "r", encoding="utf-8") as f:
        datos = json.load(f)
    return Config(datos)
