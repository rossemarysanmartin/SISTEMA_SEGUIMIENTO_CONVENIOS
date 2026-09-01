"""Abstraccion del actor que realiza una accion (para auditoria y campos de
'responsable'/'registrado por').

Hoy no hay autenticacion: se usa un marcador fijo 'USUARIO_LOCAL' en vez del
usuario de Windows, para que la auditoria y el resto del sistema NO queden
acoplados a `getpass.getuser()`. Cuando exista autenticacion real, solo esta
funcion debe cambiar (por ejemplo para leer el usuario de la sesion Flask).
"""

ACTOR_POR_DEFECTO = "USUARIO_LOCAL"


def obtener_actor_actual() -> str:
    return ACTOR_POR_DEFECTO
