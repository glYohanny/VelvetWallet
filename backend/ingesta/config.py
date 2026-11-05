# -*- coding: utf-8 -*-
"""
Configuración de la ingesta.

Todo lo que cambia entre "simulador" y "banco real" vive aquí: la URL base del
proveedor SFA, las credenciales del participante y las credenciales de las
bases. Nada de esto está escrito a mano en el código de más adentro, para que
pasar a producción sea cambiar variables de entorno, no reescribir la lógica.
"""
import json
import os
from dataclasses import dataclass
from pathlib import Path

# Carga backend/.env si existe (python-dotenv). Si no está instalado o no hay
# archivo, se usan las variables de entorno del sistema y los defaults de abajo.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass


# ── Proveedor SFA (hoy la EFS; mañana el banco real) ────────────────────────
# La única diferencia con un banco real es esta URL y la autenticación
# (ver cliente_sfa.py). La EFS ya habla el mismo estándar de la CMF.
SFA_BASE_URL = os.getenv("SFA_BASE_URL", "http://localhost:8001/accounts/v1")

# ── Credenciales del participante (Client Credentials) ──────────────────────
# En ATENA se obtienen al habilitar la institución. Aquí, valores de demo que
# deben coincidir con los que espera la EFS (simulador/app/main.py).
SFA_CLIENT_ID = os.getenv("SFA_CLIENT_ID", "velvet-wallet")
SFA_CLIENT_SECRET = os.getenv("SFA_CLIENT_SECRET", "secreto-demo")

# ── Autorización en el sitio del banco (OAuth 2.0 + PAR + PKCE) ─────────────
# Página del banco a la que se manda al usuario para que inicie sesión y
# apruebe, y la URL de Velvet a la que el banco lo devuelve con el código.
# La redirect_uri tiene que estar registrada en la EFS (SFA_REDIRECT_URIS).
SFA_AUTORIZAR_URL = os.getenv("SFA_AUTORIZAR_URL", "http://localhost:8001/autorizar")
SFA_REDIRECT_URI = os.getenv("SFA_REDIRECT_URI", "http://localhost:8000/api/conexiones/retorno")

# ── Cliente del banco para la demo por línea de comandos ────────────────────
# `python -m ingesta.sincronizar` no pasa por la app, así que necesita saber a
# qué cliente de la EFS conectar. Desde la app, en cambio, el usuario inicia
# sesión en el sitio del banco y Velvet nunca ve su clave.
SFA_RUT_DEMO = os.getenv("SFA_RUT_DEMO", "11.111.111-1")
SFA_CLAVE_DEMO = os.getenv("SFA_CLAVE_DEMO", "1234")

# ── PostgreSQL (modelo canónico) ────────────────────────────────────────────
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://velvet:cambia_esto_en_local@localhost:5432/velvet_wallet",
)

# ── MongoDB (payloads crudos) ───────────────────────────────────────────────
MONGO_URL = os.getenv(
    "MONGO_URL",
    "mongodb://velvet:cambia_esto_en_local@localhost:27017/?authSource=admin",
)
MONGO_DB = os.getenv("MONGO_DB", "velvet_wallet")

# ── Bancos participantes (RF-07: más de uno a la vez) ───────────────────────
# Una persona tiene cuentas en varios bancos, y cada uno es un proveedor del
# SFA distinto: su propia URL, su propia página de autorización y las
# credenciales con que Velvet se registró en ESE banco. La conexión de cada
# persona sabe a qué banco pertenece (por el nombre de la institución) y habla
# solo con él.
#
# Por defecto, los dos bancos del simulador: el de siempre en el 8001 y el
# Banco Austral en el 8002 (simulador/app/banco.py). Para otros bancos se pasa
# la lista completa en SFA_BANCOS, como JSON:
#   [{"nombre": "...", "base_url": ".../accounts/v1", "autorizar_url": ".../autorizar",
#     "client_id": "...", "client_secret": "..."}]
@dataclass(frozen=True)
class BancoSFA:
    nombre: str
    base_url: str
    autorizar_url: str
    client_id: str
    client_secret: str


def _bancos() -> list[BancoSFA]:
    texto = os.getenv("SFA_BANCOS", "").strip()
    if texto:
        return [BancoSFA(**b) for b in json.loads(texto)]
    austral = os.getenv("SFA_AUSTRAL_URL", "http://localhost:8002")
    return [
        # El primero es el de siempre, con las variables de antes: una
        # instalación que solo configuraba un banco sigue igual.
        BancoSFA(INSTITUCION_NOMBRE, SFA_BASE_URL, SFA_AUTORIZAR_URL,
                 SFA_CLIENT_ID, SFA_CLIENT_SECRET),
        BancoSFA("Banco Austral", austral + "/accounts/v1", austral + "/autorizar",
                 SFA_CLIENT_ID, SFA_CLIENT_SECRET),
    ]


# ── Identidad de demostración ───────────────────────────────────────────────
# En producción el usuario, la institución y la conexión nacen del registro y
# del flujo de consentimiento (OAuth). Para poder correr la ingesta sin esa
# parte todavía, se siembran de forma idempotente (ver bootstrap.py).
USUARIO_EMAIL     = os.getenv("USUARIO_EMAIL", "demo@velvetwallet.cl")
USUARIO_NOMBRE    = os.getenv("USUARIO_NOMBRE", "Usuario Demo")
# La contraseña de la cuenta de prueba que muestra la pantalla de inicio de
# sesión de la app. Es pública a propósito: es para demostrar, no protege nada.
USUARIO_CLAVE     = os.getenv("USUARIO_CLAVE", "velvet2026")
INSTITUCION_NOMBRE = os.getenv("INSTITUCION_NOMBRE", "Banco Simulado SFA")

BANCOS_SFA: list[BancoSFA] = _bancos()


def banco_sfa(nombre: str | None) -> BancoSFA | None:
    """El banco participante con ese nombre (sin distinguir mayúsculas), o None."""
    if not nombre:
        return BANCOS_SFA[0]
    return next((b for b in BANCOS_SFA if b.nombre.lower() == nombre.strip().lower()), None)
