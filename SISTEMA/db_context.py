"""Conexion SQLite de solo lectura por-request, compartida entre blueprints.

Separado de app.py para evitar import circular (los blueprints necesitan
obtener_conexion() y app.py necesita registrar los blueprints)."""

import sqlite3

from flask import g

from config import cargar_config
from services import db_visualizador


def obtener_conexion() -> sqlite3.Connection:
    if "db" not in g:
        config = cargar_config()
        g.db = db_visualizador.conectar(config.ruta_convenios_db)
    return g.db


def obtener_config():
    return cargar_config()
