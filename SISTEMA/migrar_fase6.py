"""Ejecuta la migracion de esquema de la Fase 6 sobre la base real, con
respaldo previo obligatorio. Idempotente: puede volver a correrse sin
duplicar nada."""

import sqlite3

import db_fase6
from config import cargar_config


def main():
    config = cargar_config()
    respaldo = db_fase6.respaldar(config.ruta_convenios_db)
    print(f"Respaldo creado: {respaldo}")

    conn = sqlite3.connect(str(config.ruta_convenios_db))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    db_fase6.migrar(conn)

    # Verificacion de integridad tras la migracion
    resultado = conn.execute("PRAGMA integrity_check").fetchone()[0]
    print(f"Verificacion de integridad SQLite: {resultado}")

    conn.close()
    print("Migracion Fase 6 aplicada correctamente.")


if __name__ == "__main__":
    main()
