# -*- coding: utf-8 -*-
"""
Conexiones a las bases, reutilizadas entre peticiones.

Abrir una conexión nueva a una base en la nube cuesta caro: con Neon (Postgres)
son varias idas y vueltas de TCP + TLS + autenticación, y con Atlas (Mongo) el
cliente además tiene que descubrir el cluster. Antes se pagaba en CADA
petición; ahora se abre una vez y se reutiliza:

  · Postgres: un pool de conexiones (psycopg_pool). Antes de entregar una se
    comprueba que siga viva, porque Neon corta las inactivas.
  · Mongo: un solo MongoClient por proceso (ya es un pool por dentro, y es
    seguro entre hilos; es lo que recomienda el propio driver).

Uso:
    with conexion() as conn:              # filas como tuplas
    with conexion(diccionarios=True) as conn:
Al salir del `with` sin error se confirma (commit); con error, se deshace.
"""
from __future__ import annotations

import atexit
import threading
from contextlib import contextmanager

from psycopg.rows import dict_row, tuple_row
from psycopg_pool import ConnectionPool
from pymongo import MongoClient

from . import config, esquema

_candado = threading.Lock()
_pool: ConnectionPool | None = None
_mongo: MongoClient | None = None


def pool() -> ConnectionPool:
    global _pool
    with _candado:
        # Un pool cerrado se reemplaza en vez de reutilizarse. Pasa cuando algo
        # lo cierra sin pasar por `cerrar()`: psycopg_pool.wait(), por ejemplo,
        # cierra el pool si no alcanza a llenarlo en el tiempo dado. Sin esto el
        # proceso queda inservible —toda petición responde PoolClosed— hasta que
        # alguien reinicie el servidor.
        if _pool is not None and _pool.closed:
            _pool = None
        if _pool is None:
            _pool = ConnectionPool(
                config.DATABASE_URL,
                min_size=1,
                max_size=8,
                # Neon cierra conexiones ociosas (y suspende el cómputo): se
                # comprueba antes de entregarla y se descartan las viejas.
                check=ConnectionPool.check_connection,
                max_idle=240,
                open=True,
                name="velvet",
            )
        return _pool


@contextmanager
def conexion(diccionarios: bool = False):
    with pool().connection() as conn:
        esquema.asegurar(conn)   # una vez por proceso; después no hace nada
        conn.row_factory = dict_row if diccionarios else tuple_row
        try:
            yield conn
        finally:
            conn.row_factory = tuple_row


def mongo() -> MongoClient:
    global _mongo
    with _candado:
        if _mongo is None:
            _mongo = MongoClient(config.MONGO_URL, serverSelectionTimeoutMS=10000)
        return _mongo


def cerrar() -> None:
    """Para el apagado del servidor (y las pruebas)."""
    global _pool, _mongo
    with _candado:
        if _pool is not None:
            _pool.close()
            _pool = None
        if _mongo is not None:
            _mongo.close()
            _mongo = None


# Scripts (CLI, pruebas): cerrar el pool al terminar, sin esperar a sus hilos.
atexit.register(cerrar)
