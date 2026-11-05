# -*- coding: utf-8 -*-
"""
Entorno para las pruebas de integración.

Las pruebas unitarias (motor/) no necesitan nada: son funciones puras. Las de
integración sí recorren el sistema completo —API, ingesta, Postgres y el
simulador del banco— y por eso necesitan que esas piezas estén arriba.

Tres decisiones que vale la pena dejar escritas:

**Base de datos aparte.** Las pruebas vacían tablas entre casos, así que no
pueden correr contra la base de desarrollo: una corrida distraída borraría los
datos con que se prepara la demo. Se crea y se usa `velvet_pruebas`, que nace
y muere con las pruebas.

**Mongo en memoria.** El payload crudo se guarda en Mongo, pero para verificar
el flujo no hace falta un Mongo real: `mongomock` lo reemplaza. Menos piezas
que tener arriba, menos razones para que la prueba falle por algo que no está
probando.

**Si falta una pieza, se saltan; no se rompen.** Quien corra `pytest` sin
Docker ni simulador debe ver las pruebas unitarias en verde y las de
integración marcadas como omitidas, no una pared de errores que esconda un
fallo real.
"""
from __future__ import annotations

import os
import socket
from urllib.parse import urlparse, urlunparse

import pytest

# Base dedicada: nunca la de desarrollo.
BASE_DE_PRUEBAS = "velvet_pruebas"
EFS = os.getenv("SFA_BASE_URL", "http://localhost:8001")

_RUTA_ESQUEMA = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "BD", "db", "postgres", "init", "01_schema.sql",
)


def _url_de_pruebas() -> str:
    """La misma conexión del .env, apuntando a la base de pruebas."""
    from api import config

    partes = urlparse(config.DATABASE_URL)
    return urlunparse(partes._replace(path="/" + BASE_DE_PRUEBAS))


def _responde(url: str, segundos: float = 1.5) -> bool:
    partes = urlparse(url)
    try:
        with socket.create_connection(
            (partes.hostname, partes.port or 80), timeout=segundos
        ):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def url_base() -> str:
    """
    Crea la base de pruebas con el esquema y devuelve su URL.

    Si Postgres no responde, omite todas las pruebas que dependan de esto.
    """
    import psycopg
    from api import config

    if not _responde(config.DATABASE_URL):
        pytest.skip("Postgres no está arriba (levanta BD/ con docker compose up -d)")

    administrativa = urlunparse(urlparse(config.DATABASE_URL)._replace(path="/postgres"))
    with psycopg.connect(administrativa, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{BASE_DE_PRUEBAS}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{BASE_DE_PRUEBAS}"')

    url = _url_de_pruebas()
    with open(_RUTA_ESQUEMA, encoding="utf-8") as f:
        esquema = f.read()
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(esquema)

    yield url

    with psycopg.connect(administrativa, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{BASE_DE_PRUEBAS}" WITH (FORCE)')


@pytest.fixture(scope="session")
def efs() -> str:
    """URL del simulador del banco, o se omite la prueba si no está arriba."""
    if not _responde(EFS):
        pytest.skip(f"El simulador no está arriba en {EFS}")
    return EFS


@pytest.fixture(scope="session")
def efs_austral() -> str:
    """El segundo banco del simulador (SFA_BANCO=austral, puerto 8002)."""
    url = os.getenv("SFA_AUSTRAL_URL", "http://localhost:8002")
    if not _responde(url):
        pytest.skip(f"El Banco Austral no está arriba en {url} "
                    "(SFA_BANCO=austral uvicorn app.main:app --port 8002)")
    return url


@pytest.fixture(scope="session")
def api(url_base):
    """
    Cliente HTTP contra la API real, apuntando a la base de pruebas.

    Las variables de entorno se fijan ANTES de importar la aplicación: los
    módulos leen la configuración al importarse, así que cambiarlas después no
    tendría efecto.
    """
    os.environ["DATABASE_URL"] = url_base
    os.environ["JWT_SECRET"] = "clave-solo-para-pruebas"

    import mongomock
    import pymongo

    memoria = mongomock.MongoClient()
    pymongo.MongoClient = lambda *a, **k: memoria

    # El pool y la configuración ya pueden estar cargados de otra prueba: se
    # recargan para que tomen la base de pruebas y no la de desarrollo.
    import importlib

    from api import config as config_api
    from ingesta import config as config_ingesta

    importlib.reload(config_api)
    importlib.reload(config_ingesta)

    from ingesta import conexiones_bd

    conexiones_bd.cerrar()
    importlib.reload(conexiones_bd)
    conexiones_bd.MongoClient = lambda *a, **k: memoria

    import ingesta.repositorio as repositorio

    importlib.reload(repositorio)
    repositorio.MongoClient = lambda *a, **k: memoria

    from fastapi.testclient import TestClient

    from api.main import app

    cliente = TestClient(app, follow_redirects=False)
    yield cliente
    cliente.close()
    conexiones_bd.cerrar()


@pytest.fixture
def base_limpia(url_base):
    """Vacía los datos antes de cada prueba, para que no dependan del orden."""
    import psycopg

    with psycopg.connect(url_base, autocommit=True) as conn:
        conn.execute("TRUNCATE usuario, institucion, incidente_seguridad CASCADE")
    yield
