# -*- coding: utf-8 -*-
"""
Deja lista la cuenta de prueba que muestra la app en su pantalla de inicio de
sesión (demo@velvetwallet.cl · velvet2026), con datos para mostrar.

    python preparar_demo.py

Hace dos cosas, y se puede correr las veces que se quiera:

  1. Crea la cuenta de prueba con su contraseña (o la repara, si quedó de
     una versión anterior con la que no se podía entrar).
  2. La vincula con cada banco del simulador que esté corriendo (8001 y
     8002), como la clienta Camila Rojas, y trae sus datos.

Para vincular usa la autorización directa con RUT y clave, que existe solo
para preparar demostraciones por línea de comandos. Desde la app, la persona
autoriza siempre en el sitio de su banco y Velvet nunca ve su clave.

Necesita las bases arriba y al menos un banco simulado corriendo.
"""
from __future__ import annotations

import os
import sys

from ingesta import config
from ingesta.bootstrap import asegurar_usuario_demo
from ingesta.conexiones_bd import conexion
from ingesta.sincronizar import sincronizar_usuario

# Clienta del simulador con cuenta en los dos bancos (ver simulador/README.md).
RUT = os.getenv("DEMO_RUT", "15.432.876-9")
CLAVE_BANCO = os.getenv("DEMO_CLAVE_BANCO", "2468")


def main() -> int:
    with conexion() as conn:
        usuario_id = str(asegurar_usuario_demo(conn))
        conn.commit()
    print("Cuenta de prueba: %s · %s" % (config.USUARIO_EMAIL, config.USUARIO_CLAVE))

    vinculados = 0
    for banco in config.BANCOS_SFA:
        try:
            r = sincronizar_usuario(usuario_id, banco.nombre, rut=RUT, clave=CLAVE_BANCO)
        except Exception as e:  # noqa: BLE001 — un banco apagado no impide preparar los otros
            print("  %-20s no se pudo vincular: %s. Revisa que ese banco y las bases "
                  "(Postgres y MongoDB) estén arriba." % (banco.nombre, type(e).__name__))
            continue
        vinculados += 1
        print("  %-20s vinculado como %s: %d movimientos nuevos, %d cuentas"
              % (banco.nombre, r["cliente"]["nombre"], r["insertadas"], r["cuentas"]))

    if not vinculados:
        print("No se vinculó ningún banco. Levanta el simulador (puerto 8001) y vuelve a correrlo.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
