# -*- coding: utf-8 -*-
"""
Identidad mínima que las claves foráneas exigen, de forma idempotente.

Una transacción necesita una cuenta; una cuenta, una conexión; una conexión,
un usuario y una institución.

  · En el flujo real, el usuario YA existe (nace del registro) y solo falta
    asegurar la institución y la conexión cuando vincula su banco:
    ver `conexion_de_usuario`.
  · Para correr la ingesta por línea de comandos sin pasar por el registro,
    `asegurar_identidad` crea además un usuario de demostración.
"""
from __future__ import annotations

import bcrypt
import psycopg

from . import config


def asegurar_institucion(conn: psycopg.Connection, nombre: str) -> str:
    """Get-or-create de la institución por nombre. Devuelve institucion_id."""
    fila = conn.execute(
        "SELECT id FROM institucion WHERE nombre = %s", (nombre,)
    ).fetchone()
    if fila:
        return fila[0]
    return conn.execute(
        """INSERT INTO institucion (nombre, tipo, participante_sfa)
           VALUES (%s, 'banco', true) RETURNING id""",
        (nombre,),
    ).fetchone()[0]


def asegurar_conexion(conn: psycopg.Connection, usuario_id: str,
                      institucion_id: str) -> str:
    """Get-or-create de la conexión del par usuario+institución. Devuelve conexion_id."""
    fila = conn.execute(
        """SELECT id FROM conexion
           WHERE usuario_id = %s AND institucion_id = %s""",
        (usuario_id, institucion_id),
    ).fetchone()
    if fila:
        return fila[0]
    return conn.execute(
        """INSERT INTO conexion (usuario_id, institucion_id, estado)
           VALUES (%s, %s, 'activa') RETURNING id""",
        (usuario_id, institucion_id),
    ).fetchone()[0]


def conexion_de_usuario(conn: psycopg.Connection, usuario_id: str,
                        institucion_nombre: str) -> str:
    """
    Para un usuario que YA existe (viene del registro/login): asegura la
    institución y la conexión, y devuelve conexion_id. Es lo que usa la API
    cuando el usuario vincula un banco.
    """
    # Lo normal (re-sincronizar) es que ya exista: una sola consulta.
    fila = conn.execute(
        """SELECT cx.id FROM conexion cx
           JOIN institucion i ON i.id = cx.institucion_id
           WHERE cx.usuario_id = %s AND i.nombre = %s""",
        (usuario_id, institucion_nombre),
    ).fetchone()
    if fila:
        return fila[0]
    institucion_id = asegurar_institucion(conn, institucion_nombre)
    return asegurar_conexion(conn, usuario_id, institucion_id)


def asegurar_usuario_demo(conn: psycopg.Connection) -> str:
    """
    La cuenta de prueba que muestra la pantalla de inicio de sesión, con su
    contraseña de verdad (hash bcrypt), para que se pueda entrar con ella.

    Si existe con un hash que no es bcrypt (versiones anteriores la creaban
    con un marcador, "demo-no-usar", con el que no se podía entrar), se
    repara. Si la persona ya le cambió la contraseña, no se toca.
    """
    fila = conn.execute(
        "SELECT id, hash_password FROM usuario WHERE email = %s", (config.USUARIO_EMAIL,)
    ).fetchone()
    hash_demo = bcrypt.hashpw(config.USUARIO_CLAVE.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    if fila is None:
        return conn.execute(
            """INSERT INTO usuario (email, nombre, hash_password)
               VALUES (%s, %s, %s) RETURNING id""",
            (config.USUARIO_EMAIL, config.USUARIO_NOMBRE, hash_demo),
        ).fetchone()[0]
    if not str(fila[1]).startswith("$2"):
        conn.execute("UPDATE usuario SET hash_password = %s WHERE id = %s", (hash_demo, fila[0]))
    return fila[0]


def asegurar_identidad(conn: psycopg.Connection) -> tuple[str, str]:
    """
    Demo por línea de comandos: crea/usa un usuario de demostración y su
    conexión. Devuelve (usuario_id, conexion_id).
    """
    usuario_id = asegurar_usuario_demo(conn)
    conexion_id = conexion_de_usuario(conn, usuario_id, config.INSTITUCION_NOMBRE)
    return usuario_id, conexion_id
