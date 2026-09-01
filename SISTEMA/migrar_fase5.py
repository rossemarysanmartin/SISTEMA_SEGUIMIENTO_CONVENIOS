"""Ejecuta la migracion de esquema de la Fase 5 sobre la base real,
con respaldo previo obligatorio. Ejecutar una sola vez (es idempotente:
CREATE TABLE IF NOT EXISTS / ALTER TABLE ADD COLUMN solo si falta / INSERT OR
IGNORE en catalogos, asi que volver a correrlo no duplica nada)."""

import sqlite3

import db_fase5
from config import cargar_config


def main():
    config = cargar_config()
    respaldo = db_fase5.respaldar(config.ruta_convenios_db)
    print(f"Respaldo creado: {respaldo}")

    conn = sqlite3.connect(str(config.ruta_convenios_db))
    conn.execute("PRAGMA foreign_keys = ON;")
    db_fase5.migrar(conn)
    conn.close()
    print("Migracion Fase 5 aplicada correctamente.")


if __name__ == "__main__":
    main()
