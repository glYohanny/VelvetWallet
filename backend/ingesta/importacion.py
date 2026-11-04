# -*- coding: utf-8 -*-
"""
Las otras dos fuentes del pipeline de ingesta (OE-1), además de la API del SFA:

  · Cartola CSV (RF-12): para instituciones que no están en el SFA y para el
    historial anterior a la conexión.
  · Carga manual (RF-13): principalmente gastos en efectivo.

Las tres fuentes terminan en el mismo modelo canónico (RF-08): mismas tablas,
mismo clasificador, mismo detector de recurrencias. Lo que cambia es cómo se
reconoce un duplicado:

  · Misma fuente, misma fila → la huella `hash_dedup`. Reimportar la misma
    cartola (o una que se solapa con la anterior) no duplica nada.
  · Otra fuente, mismo movimiento → `dedup.emparejar` (monto exacto, fechas
    cercanas). Queda UN movimiento con las dos fuentes anotadas (RF-09).

Igual que en la API del banco, la fila cruda se guarda en MongoDB (cifrada)
tal como llegó, antes de normalizarla (RF-06).
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import date, timedelta
from decimal import Decimal

from bson import ObjectId
from psycopg.types.json import Json

from clasificador import clasificar_lote

from .cartola import CartolaInvalida, leer_cartola
from .dedup import TOLERANCIA_DIAS, Movimiento, emparejar
from .repositorio import Repositorio
from .sincronizar import recalcular_recurrencias

EFECTIVO = "Efectivo"
ID_EFECTIVO = "EFECTIVO"
ID_CARTOLA = "CARTOLA"
TIPOS_CUENTA = ("corriente", "vista", "ahorro", "credito", "tarjeta", "otro")


class ImportacionRechazada(Exception):
    """La importación no se puede hacer. El mensaje es para la persona."""


def _huella(*partes) -> str:
    return hashlib.sha256("|".join(str(p) for p in partes).encode("utf-8")).hexdigest()


def huellas_cartola(usuario_id: str, cuenta_id: str, filas) -> list[str]:
    """
    Huella de cada fila de la cartola. Incluye cuántas veces se repite la
    misma fila en el archivo: dos cafés iguales el mismo día son dos
    movimientos, y en la siguiente importación vuelven a dar las mismas dos
    huellas, así que tampoco se duplican.
    """
    vistas: dict[tuple, int] = {}
    huellas = []
    for f in filas:
        clave = (f.fecha.isoformat(), str(f.monto), " ".join(f.glosa.upper().split()))
        vistas[clave] = vistas.get(clave, 0) + 1
        huellas.append(_huella(usuario_id, cuenta_id, "cartola", *clave, vistas[clave]))
    return huellas


def _clasificar(glosas_y_montos: list[tuple[str, Decimal]]) -> list[tuple[str | None, float | None]]:
    """Solo los gastos se categorizan, igual que en la ingesta del SFA."""
    salida: list[tuple[str | None, float | None]] = [(None, None)] * len(glosas_y_montos)
    gastos = [i for i, (g, m) in enumerate(glosas_y_montos) if m < 0 and g]
    for i, r in zip(gastos, clasificar_lote([glosas_y_montos[i][0] for i in gastos])):
        if r.categoria is not None:
            salida[i] = (r.categoria, round(r.confianza, 4) if r.confianza is not None else None)
    return salida


# ── Cartola ──────────────────────────────────────────────────────────────────

def _cuenta_destino(repo: Repositorio, usuario_id: str, cuenta_id: str | None,
                    institucion: str | None, tipo_cuenta: str, crear: bool) -> dict | None:
    """
    La cuenta a la que va la cartola: una que la persona ya tiene (historial
    anterior de un banco conectado), o una nueva de un banco fuera del SFA.
    None solo en simulación de una cuenta que todavía no existe.
    """
    if cuenta_id:
        cuenta = repo.cuenta_del_usuario(usuario_id, cuenta_id)
        if cuenta is None:
            raise ImportacionRechazada("Esa cuenta no existe.")
        if cuenta["id_externo"] == ID_EFECTIVO:
            raise ImportacionRechazada("El efectivo no tiene cartola: registra esos gastos a mano.")
        return cuenta

    nombre = " ".join((institucion or "").split())
    if not 2 <= len(nombre) <= 80:
        raise ImportacionRechazada("Escribe el nombre de la institución (entre 2 y 80 caracteres).")
    if nombre.lower() == EFECTIVO.lower():
        raise ImportacionRechazada("El efectivo no tiene cartola: registra esos gastos a mano.")
    if tipo_cuenta not in TIPOS_CUENTA:
        raise ImportacionRechazada("Tipo de cuenta no válido.")
    existente = repo.institucion_por_nombre(nombre)
    if existente is not None and existente[2]:
        # Un banco del SFA tiene sus cuentas por la API: la cartola va a esa
        # cuenta, no a una paralela que duplicaría todo.
        raise ImportacionRechazada(
            "%s está conectado por el Sistema de Finanzas Abiertas: elige su cuenta "
            "en vez de crear una nueva." % existente[1])
    if not crear:
        fila = repo.conn.execute(
            """SELECT c.id FROM cuenta c
               JOIN conexion cx ON cx.id = c.conexion_id
               JOIN institucion i ON i.id = cx.institucion_id
               WHERE c.usuario_id = %s AND lower(i.nombre) = lower(%s) AND c.id_externo = %s""",
            (usuario_id, nombre, ID_CARTOLA)).fetchone()
        return repo.cuenta_del_usuario(usuario_id, str(fila[0])) if fila else None
    return repo.cuenta_fuera_del_sfa(usuario_id, nombre, ID_CARTOLA, "banco", tipo_cuenta)


def importar_cartola(repo: Repositorio, usuario_id: str, contenido: bytes, *,
                     cuenta_id: str | None = None, institucion: str | None = None,
                     tipo_cuenta: str = "corriente", nombre_archivo: str | None = None,
                     simular: bool = False) -> dict:
    """
    Lee la cartola y la incorpora al ledger. Con `simular=True` no escribe
    nada: devuelve lo mismo que pasaría, para que la persona lo vea antes de
    confirmar. No hace commit: lo hace quien llama, junto con la bitácora.
    """
    try:
        cartola = leer_cartola(contenido)
    except CartolaInvalida as e:
        raise ImportacionRechazada(str(e)) from e

    cuenta = _cuenta_destino(repo, usuario_id, cuenta_id, institucion, tipo_cuenta,
                             crear=not simular)
    filas = cartola.filas
    resumen = {
        "simulado": simular,
        "cuenta": ({"id": cuenta["id"], "institucion": cuenta["institucion"],
                    "idExterno": cuenta["id_externo"]} if cuenta else None),
        "columnas": cartola.columnas,
        "leidas": len(filas),
        "nuevas": 0, "fusionadas": 0, "repetidas": 0,
        "rechazadas": [{"linea": r.linea, "motivo": r.motivo} for r in cartola.rechazadas],
        "desde": min(f.fecha for f in filas).isoformat() if filas else None,
        "hasta": max(f.fecha for f in filas).isoformat() if filas else None,
    }
    if not filas:
        return resumen

    # Sin cuenta todavía (simulación de un banco nuevo): todo sería nuevo.
    if cuenta is None:
        resumen["nuevas"] = len(filas)
        return resumen

    huellas = huellas_cartola(usuario_id, cuenta["id"], filas)
    conocidas = repo.hashes_conocidos(huellas)
    pendientes = [i for i, h in enumerate(huellas) if h not in conocidas]
    resumen["repetidas"] = len(filas) - len(pendientes)

    # ¿Alguna ya la trajo la API del banco? Entonces es el mismo movimiento.
    existentes = []
    if pendientes:
        margen = timedelta(days=TOLERANCIA_DIAS)
        existentes = repo.candidatos_a_fusion(
            cuenta["id"], "cartola",
            min(filas[i].fecha for i in pendientes) - margen,
            max(filas[i].fecha for i in pendientes) + margen)
    pares = emparejar(
        [Movimiento(i, filas[i].fecha, filas[i].monto, filas[i].glosa) for i in pendientes],
        [Movimiento(tid, f, m, g) for tid, f, m, g in existentes],
    )
    nuevas = [i for i in pendientes if i not in pares]
    resumen["fusionadas"] = len(pares)
    resumen["nuevas"] = len(nuevas)
    if simular or not pendientes:
        return resumen

    # El crudo primero, tal como venía cada fila (RF-06).
    crudos = [dict(filas[i].crudo, _linea=filas[i].linea, _archivo=nombre_archivo)
              for i in pendientes]
    refs = dict(zip(pendientes, repo.guardar_crudo_bulk(cuenta["conexion_id"], "cartola-csv",
                                                         crudos)))
    for i, transaccion_id in pares.items():
        repo.registrar_origen(transaccion_id, "cartola", refs[i], huellas[i])

    categorias = _clasificar([(filas[i].glosa, filas[i].monto) for i in nuevas])
    repo.insertar_sin_id(cuenta["id"], "cartola", [
        {"hash_dedup": huellas[i], "payload_crudo_ref": refs[i], "monto": filas[i].monto,
         "fecha": filas[i].fecha, "glosa_original": filas[i].glosa,
         "categoria_nombre": cat, "confianza_clasificacion": conf}
        for i, (cat, conf) in zip(nuevas, categorias)
    ])
    repo.marcar_sincronizacion(cuenta["conexion_id"])
    if nuevas:
        recalcular_recurrencias(repo, usuario_id)
    return resumen


# ── Carga manual ─────────────────────────────────────────────────────────────

def cuenta_efectivo(repo: Repositorio, usuario_id: str) -> dict:
    return repo.cuenta_fuera_del_sfa(usuario_id, EFECTIVO, ID_EFECTIVO, "otro", "otro")


def registrar_manual(repo: Repositorio, usuario_id: str, *, monto: Decimal, fecha: date,
                     glosa: str, categoria: str | None) -> str:
    """
    Un movimiento que la persona anota a mano, en su cuenta de efectivo.
    Devuelve el id. Si eligió la categoría, esa decisión es suya y queda como
    tal (igual que una corrección); si no, la propone el clasificador.
    """
    cuenta = cuenta_efectivo(repo, usuario_id)
    ref = repo.guardar_crudo_bulk(cuenta["conexion_id"], "carga-manual", [{
        "monto": str(monto), "fecha": fecha.isoformat(), "glosa": glosa, "categoria": categoria,
    }])[0]
    if categoria:
        propuesta = (categoria, None)
    else:
        propuesta = _clasificar([(glosa, monto)])[0]
    # Una huella única por registro: dos gastos iguales en efectivo el mismo
    # día son dos gastos (no hay una segunda fuente con qué confundirlos).
    transaccion_id = repo.insertar_sin_id(cuenta["id"], "manual", [{
        "hash_dedup": _huella(usuario_id, "manual", uuid.uuid4()), "payload_crudo_ref": ref,
        "monto": monto, "fecha": fecha, "glosa_original": glosa,
        "categoria_nombre": propuesta[0], "confianza_clasificacion": propuesta[1],
    }])[0]
    if categoria:
        repo.conn.execute(
            """INSERT INTO correccion (transaccion_id, usuario_id, tipo, valor)
               VALUES (%s, %s, 'recategorizar', %s)""",
            (transaccion_id, usuario_id, Json({"categoria": categoria, "al_registrar": True})),
        )
    repo.marcar_sincronizacion(cuenta["conexion_id"])
    if monto < 0:
        recalcular_recurrencias(repo, usuario_id)
    return transaccion_id


def eliminar_manual(repo: Repositorio, usuario_id: str, transaccion_id: str) -> bool:
    """
    Borra un movimiento anotado a mano (la persona se equivocó). Solo los
    manuales: lo que mandó un banco no se borra, se corrige o se excluye.
    """
    fila = repo.conn.execute(
        """SELECT t.id, t.payload_crudo_ref FROM transaccion t
           JOIN cuenta c ON c.id = t.cuenta_id
           WHERE t.id::text = %s AND c.usuario_id = %s AND t.fuente = 'manual'""",
        (transaccion_id, usuario_id),
    ).fetchone()
    if fila is None:
        return False
    if fila[1]:
        repo.db.payload_crudo.delete_one({"_id": ObjectId(fila[1])})
    repo.conn.execute("DELETE FROM transaccion WHERE id = %s", (fila[0],))
    recalcular_recurrencias(repo, usuario_id)
    return True
