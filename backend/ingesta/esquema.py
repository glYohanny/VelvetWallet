# -*- coding: utf-8 -*-
"""
Ajustes de esquema para bases creadas con una versión anterior del DDL.

El DDL de `BD/db/postgres/init/01_schema.sql` solo corre con la base vacía, y
la de la nube (Neon) ya tiene datos. Lo que cambió después se aplica aquí, una
vez por proceso y de forma idempotente: correrlo de nuevo no hace nada.
"""
from __future__ import annotations

import threading

from psycopg.rows import tuple_row

_candado = threading.Lock()
_al_dia = False


def asegurar(conn) -> None:
    global _al_dia
    if _al_dia:
        return
    with _candado:
        if _al_dia:
            return
        # Columna agregada después del esquema inicial.
        conn.execute("ALTER TABLE transaccion ADD COLUMN IF NOT EXISTS categoria_origen varchar(80)")

        # RF-09 / RF-12 / RF-13: por dónde entró cada movimiento, y las otras
        # fuentes que trajeron el mismo.
        conn.execute("ALTER TABLE transaccion ADD COLUMN IF NOT EXISTS fuente varchar(20) "
                     "NOT NULL DEFAULT 'sfa' CHECK (fuente IN ('sfa','cartola','manual'))")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transaccion_origen (
                id                uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
                transaccion_id    uuid         NOT NULL REFERENCES transaccion(id) ON DELETE CASCADE,
                fuente            varchar(20)  NOT NULL CHECK (fuente IN ('sfa','cartola','manual')),
                payload_crudo_ref varchar(24),
                hash_dedup        varchar(64)  NOT NULL UNIQUE,
                recibido_at       timestamptz  NOT NULL DEFAULT now()
            )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_transaccion_origen_tx "
                     "ON transaccion_origen (transaccion_id)")

        # RF-31: el sueldo declarado se guarda cifrado, que es texto y no un
        # número. El CHECK (>= 0) se va con el cambio de tipo: la validación
        # del monto ya la hace la API antes de cifrar (api/perfil.py).
        tipo = conn.cursor(row_factory=tuple_row).execute(
            """SELECT data_type FROM information_schema.columns
               WHERE table_name = 'usuario' AND column_name = 'sueldo_declarado'"""
        ).fetchone()
        if tipo and tipo[0] != "text":
            conn.execute("ALTER TABLE usuario DROP CONSTRAINT IF EXISTS usuario_sueldo_declarado_check")
            conn.execute("ALTER TABLE usuario ALTER COLUMN sueldo_declarado TYPE text "
                         "USING sueldo_declarado::text")
        conn.commit()
        _al_dia = True
