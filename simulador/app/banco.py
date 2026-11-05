# -*- coding: utf-8 -*-
"""
Qué banco es esta EFS.

Una persona real tiene cuentas en más de un banco, y Velvet tiene que poder
conectarse a varios a la vez (RF-07: cada conexión se sincroniza por separado,
y la caída de una no afecta a las demás). Para probarlo hacen falta dos
bancos distintos de verdad: otro nombre, otros clientes, otras cuentas y otros
movimientos. No el mismo banco con dos nombres.

Por eso el simulador se levanta como uno u otro banco según SFA_BANCO:

    uvicorn app.main:app --port 8001                      # Banco Simulado SFA (el de siempre)
    SFA_BANCO=austral uvicorn app.main:app --port 8002    # Banco Austral

En PowerShell:  $env:SFA_BANCO="austral"; uvicorn app.main:app --port 8002

Cada banco guarda sus archivos (refresh tokens, clientes creados en vivo) por
separado: dos procesos escribiendo el mismo archivo se pisarían.
"""
from __future__ import annotations

import os
from pathlib import Path

_CARPETA = Path(__file__).parent

BANCOS = {
    # El de siempre. Sus archivos conservan el nombre original para no perder
    # los permisos ni los clientes que ya existen.
    "simulado": {
        "nombre": "Banco Simulado SFA",
        "prefijo_cuenta": "CTA",
        "prefijo_movimiento": "",
        "dominio": "banco-simulado.cl",
        "semilla": 0,
        "sufijo_archivos": "",
    },
    # Un segundo banco: Camila y Diego tienen además una cuenta aquí, con
    # otros gastos, y hay una clienta que solo es de este banco.
    "austral": {
        "nombre": "Banco Austral",
        "prefijo_cuenta": "AUS",
        "prefijo_movimiento": "AUS",
        "dominio": "banco-austral.cl",
        "semilla": 7919,
        "sufijo_archivos": "_austral",
    },
}

ID = os.getenv("SFA_BANCO", "simulado").strip().lower()
if ID not in BANCOS:
    raise SystemExit("SFA_BANCO=%r no existe. Use uno de: %s" % (ID, ", ".join(BANCOS)))

_B = BANCOS[ID]
NOMBRE: str = os.getenv("SFA_BANCO_NOMBRE", _B["nombre"])
PREFIJO_CUENTA: str = _B["prefijo_cuenta"]
PREFIJO_MOVIMIENTO: str = _B["prefijo_movimiento"]
DOMINIO: str = _B["dominio"]
SEMILLA: int = _B["semilla"]


def archivo(nombre: str) -> Path:
    """'refresh_tokens.json' → el archivo de ESTE banco."""
    base, punto, extension = nombre.rpartition(".")
    return _CARPETA / ("%s%s%s%s" % (base, _B["sufijo_archivos"], punto, extension))
