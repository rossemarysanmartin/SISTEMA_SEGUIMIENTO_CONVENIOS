"""Genera el Dashboard Ejecutivo Portable (Fase 6.5): un unico archivo HTML
autocontenido, de solo consulta, con una fotografia de convenios.db.

Uso:
    python generar_dashboard_ejecutivo.py
    python generar_dashboard_ejecutivo.py --historico

Solo LEE convenios.db y solo ESCRIBE dentro de DASHBOARD_EJECUTIVO. No toca
el repositorio documental original ni modifica la base de datos.
"""

import argparse

from config import cargar_config
from services import configuracion as cfg_service
from services import db_visualizador
from services import exportar_dashboard_ejecutivo as export


def main():
    parser = argparse.ArgumentParser(description="Genera el dashboard ejecutivo portable.")
    parser.add_argument("--historico", action="store_true",
                         help="Ademas guarda una copia con fecha en DASHBOARD_EJECUTIVO/HISTORICO/")
    args = parser.parse_args()

    config = cargar_config()
    conn = db_visualizador.conectar(config.ruta_convenios_db)
    try:
        config_efectiva = cfg_service.config_efectiva(conn, config)
        datos = export.recolectar_datos(conn, config_efectiva)
        ruta = export.generar_dashboard_ejecutivo(conn, config, config_efectiva, guardar_historico=args.historico)
    finally:
        conn.close()

    tamano_kb = ruta.stat().st_size / 1024
    print("Dashboard ejecutivo generado correctamente.")
    print(f"Archivo:        {ruta}")
    print(f"Tamano:         {tamano_kb:.1f} KB")
    print(f"Fecha de corte: {datos['fecha_corte']}")
    print(f"Convenios incluidos:   {len(datos['convenios'])}")
    print(f"Solicitudes incluidas: {len(datos['solicitudes'])}")
    if args.historico:
        print(f"Copia historica guardada en: {config.ruta_dashboard_ejecutivo_historico}")


if __name__ == "__main__":
    main()
