# -*- coding: utf-8 -*-
"""
Crea el esquema (las 11 tablas) en la base de datos apuntada por DATABASE_URL.

Útil cuando la base no corre por Docker (p. ej. Neon en la nube): en Docker el
esquema se crea solo al iniciar, pero en una base externa hay que correrlo una vez.

    python crear_esquema.py

Lee el mismo DDL de siempre: BD/db/postgres/init/01_schema.sql
"""
from pathlib import Path

import psycopg

from api import config

DDL = Path(__file__).resolve().parent.parent / "BD" / "db" / "postgres" / "init" / "01_schema.sql"

# Las 11 tablas, para borrarlas antes de recrear. CASCADE se lleva también las
# llaves foráneas, así que el orden da igual; IF EXISTS evita el error si no están.
TABLAS = [
    "bitacora_auditoria",
    "correccion",
    "transaccion_origen",
    "transaccion",
    "meta",
    "suscripcion",
    "consentimiento",
    "cuenta",
    "conexion",
    "categoria",
    "institucion",
    "usuario",
]


def dividir_sentencias(sql: str) -> list[str]:
    """
    Separa el script en sentencias por ';', pero respetando el contenido:
    ignora los ';' que están dentro de un texto entre comillas ('...') o de un
    comentario de línea (-- ...). Así no se parte una sentencia por la mitad.
    """
    sentencias: list[str] = []
    buf: list[str] = []
    i, n = 0, len(sql)
    en_cadena = False
    while i < n:
        c = sql[i]
        # Comentario de línea fuera de comillas: saltar hasta el fin de línea.
        if not en_cadena and c == "-" and i + 1 < n and sql[i + 1] == "-":
            salto = sql.find("\n", i)
            if salto == -1:
                break
            i = salto
            continue
        if c == "'":
            buf.append(c)
            # Comilla escapada dentro de un texto ('' = una comilla literal).
            if en_cadena and i + 1 < n and sql[i + 1] == "'":
                buf.append(sql[i + 1])
                i += 2
                continue
            en_cadena = not en_cadena
            i += 1
            continue
        if c == ";" and not en_cadena:
            s = "".join(buf).strip()
            if s:
                sentencias.append(s)
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1

    resto = "".join(buf).strip()
    if resto:
        sentencias.append(resto)
    return sentencias


def main() -> None:
    if not DDL.exists():
        raise SystemExit("No se encontró el DDL en %s" % DDL)

    sql = DDL.read_text(encoding="utf-8")
    sentencias = [s for s in dividir_sentencias(sql) if s.upper() not in ("BEGIN", "COMMIT")]

    # Todo en una sola transacción: si algo falla, no queda el esquema a medias.
    with psycopg.connect(config.DATABASE_URL) as conn:
        # Partir de cero: se borra lo que haya y se recrea el esquema vacío.
        # Así el script se puede correr las veces que haga falta sin que choque
        # con tablas que ya existían de un intento anterior.
        conn.execute("DROP SCHEMA public CASCADE;")
        conn.execute("CREATE SCHEMA public;")
        for s in sentencias:
            conn.execute(s)
        conn.commit()

    print("Esquema creado: %d sentencias ejecutadas en la base de datos." % len(sentencias))


if __name__ == "__main__":
    main()
