# -*- coding: utf-8 -*-
"""
Cifra lo que quedó guardado en claro antes del cifrado en reposo (RF-31), y
re-cifra con la clave actual lo que se cifró con una anterior (rotación).

    python cifrar_datos_existentes.py            # aplica los cambios
    python cifrar_datos_existentes.py --simular  # solo cuenta, no escribe

Recorre:
  · usuario.sueldo_declarado
  · consentimiento.alcance_rar  (refreshToken, rutCliente, nombreCliente),
    también de los consentimientos revocados o expirados: el token sigue ahí.
  · payload_crudo en MongoDB

Es idempotente: lo que ya está cifrado con la clave actual no se toca, así que
correrlo dos veces no hace nada la segunda.

Para rotar la clave: poner la nueva en VELVET_CLAVE_CIFRADO, la vieja en
VELVET_CLAVES_ANTERIORES, correr este script, y recién entonces quitar la vieja.
"""
from __future__ import annotations

import json
import sys

from psycopg.types.json import Json
from pymongo import UpdateOne

from ingesta import config
from ingesta.cifrado import (cifrado_con_clave_actual, cifrar, cifrar_alcance,
                             cifrar_numero, ctx_payload, ctx_sueldo, descifrar,
                             descifrar_numero)
from ingesta.conexiones_bd import conexion, mongo

_LOTE = 500


def _sueldos(conn, simular: bool) -> int:
    filas = conn.execute(
        "SELECT id, sueldo_declarado FROM usuario WHERE sueldo_declarado IS NOT NULL"
    ).fetchall()
    cambios = 0
    for id_, valor in filas:
        if cifrado_con_clave_actual(valor):
            continue
        cambios += 1
        if not simular:
            claro = descifrar_numero(valor, ctx_sueldo(id_))
            conn.execute("UPDATE usuario SET sueldo_declarado = %s WHERE id = %s",
                         (cifrar_numero(round(claro), ctx_sueldo(id_)), id_))
    return cambios


def _consentimientos(conn, simular: bool) -> int:
    filas = conn.execute("SELECT id, conexion_id, alcance_rar FROM consentimiento").fetchall()
    cambios = 0
    for id_, conexion_id, alcance in filas:
        nuevo = cifrar_alcance(alcance, conexion_id)
        if nuevo == alcance:
            continue
        cambios += 1
        if not simular:
            conn.execute("UPDATE consentimiento SET alcance_rar = %s WHERE id = %s",
                         (Json(nuevo), id_))
    return cambios


def _payloads(simular: bool) -> int:
    coleccion = mongo()[config.MONGO_DB].payload_crudo
    cambios = 0
    lote: list[UpdateOne] = []
    for doc in coleccion.find({}, {"payload": 1, "conexion_id": 1}):
        payload = doc.get("payload")
        ctx = ctx_payload(doc["conexion_id"])
        sellado = isinstance(payload, dict) and set(payload) == {"cifrado"}
        if sellado and cifrado_con_clave_actual(payload["cifrado"]):
            continue
        cambios += 1
        if simular:
            continue
        claro = json.loads(descifrar(payload["cifrado"], ctx)) if sellado else payload
        texto = json.dumps(claro, ensure_ascii=False, sort_keys=True)
        lote.append(UpdateOne({"_id": doc["_id"]},
                              {"$set": {"payload": {"cifrado": cifrar(texto, ctx)}}}))
        if len(lote) >= _LOTE:
            coleccion.bulk_write(lote)
            lote = []
    if lote:
        coleccion.bulk_write(lote)
    return cambios


def main(simular: bool = False) -> dict:
    with conexion() as conn:
        resumen = {
            "sueldos": _sueldos(conn, simular),
            "consentimientos": _consentimientos(conn, simular),
        }
        if simular:
            conn.rollback()
        else:
            conn.commit()
    resumen["payloads"] = _payloads(simular)
    return resumen


if __name__ == "__main__":
    simular = "--simular" in sys.argv
    r = main(simular)
    verbo = "Por cifrar" if simular else "Cifrados"
    print("%s:" % verbo)
    print("  Sueldos declarados : %d" % r["sueldos"])
    print("  Consentimientos    : %d" % r["consentimientos"])
    print("  Payloads crudos    : %d" % r["payloads"])
