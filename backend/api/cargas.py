# -*- coding: utf-8 -*-
"""
Las dos fuentes de datos que no son la API del banco (OE-1).

  POST   /api/cartolas            -> importar una cartola CSV (RF-12), con vista previa
  POST   /api/movimientos         -> anotar un gasto o ingreso a mano (RF-13)
  DELETE /api/movimientos/{id}    -> borrar uno anotado a mano

La cartola viaja como JSON con el archivo en base64 y no como multipart: la
app la lee igual en el navegador y en el teléfono, y el backend no necesita
otra dependencia para recibir archivos.
"""
from __future__ import annotations

import base64
import binascii
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from . import bitacora
from .datos import _SELECT_MOVIMIENTOS, _movimiento
from .sesion_actual import usuario_actual

from clasificador.taxonomia import CATEGORIAS
from ingesta.cartola import MAX_BYTES
from ingesta.importacion import (TIPOS_CUENTA, ImportacionRechazada, eliminar_manual,
                                 importar_cartola, registrar_manual)
from ingesta.repositorio import Repositorio

router = APIRouter(prefix="/api", tags=["Cartolas y carga manual"])

# Un sueldo o una compra grande caben; un número mal tipeado con tres ceros de
# más, no.
MONTO_MAXIMO = 100_000_000


class Cartola(BaseModel):
    contenidoBase64: str = Field(min_length=1)
    nombreArchivo: str | None = Field(default=None, max_length=200)
    #: Una cuenta que la persona ya tiene (historial anterior de un banco
    #: conectado)...
    cuentaId: str | None = None
    #: ...o una institución fuera del SFA, que se crea si no existe.
    institucion: str | None = Field(default=None, max_length=80)
    tipoCuenta: str = "corriente"
    #: true = vista previa: dice qué pasaría, sin guardar nada.
    simular: bool = False


@router.post("/cartolas", summary="Importar una cartola CSV")
def importar(datos: Cartola, peticion: Request, usuario_id: str = Depends(usuario_actual)):
    """
    Lee la cartola, descarta lo que ya estaba (de una importación anterior o
    porque ya lo trajo la API del banco) y agrega el resto, clasificado.

    La respuesta dice cuántas filas se leyeron, cuántas son nuevas, cuántas
    coincidieron con un movimiento de otra fuente (`fusionadas`), cuántas ya
    se habían importado (`repetidas`) y qué líneas no se pudieron leer y por
    qué. Con `simular` se ve todo eso antes de confirmar.
    """
    if bool(datos.cuentaId) == bool(datos.institucion and datos.institucion.strip()):
        raise HTTPException(status_code=422,
                            detail="Indica la cuenta de destino o el nombre de la institución.")
    if datos.tipoCuenta not in TIPOS_CUENTA:
        raise HTTPException(status_code=422, detail="Tipo de cuenta no válido.")
    if len(datos.contenidoBase64) > (MAX_BYTES * 4) // 3 + 8:
        raise HTTPException(status_code=413,
                            detail="El archivo pesa más de 2 MB. Exporta un período más corto.")
    try:
        contenido = base64.b64decode(datos.contenidoBase64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail="El archivo no llegó bien. Vuelve a elegirlo.")

    repo = Repositorio()
    try:
        try:
            resumen = importar_cartola(
                repo, usuario_id, contenido, cuenta_id=datos.cuentaId,
                institucion=datos.institucion, tipo_cuenta=datos.tipoCuenta,
                nombre_archivo=datos.nombreArchivo, simular=datos.simular)
        except ImportacionRechazada as e:
            raise HTTPException(status_code=422, detail=str(e))
        if datos.simular:
            return resumen
        bitacora.registrar(repo.conn, usuario_id, "datos.importar",
                           "cartola %s: %d nuevos, %d fusionados"
                           % (resumen["cuenta"]["institucion"], resumen["nuevas"],
                              resumen["fusionadas"]),
                           bitacora.ip_de(peticion))
        repo.commit()
        return resumen
    finally:
        repo.close()


class MovimientoManual(BaseModel):
    #: Siempre positivo; el tipo dice si sale o entra.
    monto: float = Field(gt=0)
    tipo: Literal["gasto", "ingreso"] = "gasto"
    glosa: str = Field(min_length=1, max_length=120)
    #: Por defecto, hoy.
    fecha: date | None = None
    #: Si la elige la persona. Si no, la propone el clasificador.
    categoria: str | None = None


@router.post("/movimientos", status_code=201, summary="Anotar un movimiento a mano")
def anotar(datos: MovimientoManual, peticion: Request,
           usuario_id: str = Depends(usuario_actual)):
    """
    Para lo que no pasa por ningún banco: principalmente el efectivo. Queda en
    una cuenta "Efectivo" de la persona y entra a los mismos cálculos que el
    resto (resumen, flujo, metas, recurrencias).
    """
    glosa = " ".join(datos.glosa.split())
    if not glosa:
        raise HTTPException(status_code=422, detail="Escribe en qué fue el gasto.")
    if datos.monto > MONTO_MAXIMO:
        raise HTTPException(status_code=422, detail="Ese monto parece un error de tipeo.")
    fecha = datos.fecha or date.today()
    if fecha > date.today():
        raise HTTPException(status_code=422, detail="La fecha no puede ser futura.")
    if fecha.year < 2000:
        raise HTTPException(status_code=422, detail="Revisa la fecha.")
    categoria = datos.categoria.strip() if datos.categoria else None
    if categoria and (datos.tipo != "gasto" or categoria not in CATEGORIAS):
        raise HTTPException(status_code=422, detail="Categoría no válida.")

    monto = Decimal(round(datos.monto))
    if monto == 0:
        raise HTTPException(status_code=422, detail="El monto debe ser al menos $1.")
    repo = Repositorio()
    try:
        tid = registrar_manual(repo, usuario_id, monto=-monto if datos.tipo == "gasto" else monto,
                               fecha=fecha, glosa=glosa, categoria=categoria)
        bitacora.registrar(repo.conn, usuario_id, "datos.registrar_manual",
                           "movimiento %s" % tid, bitacora.ip_de(peticion))
        repo.commit()
        with repo.conn.cursor(row_factory=dict_row) as cur:
            fila = cur.execute(_SELECT_MOVIMIENTOS + " WHERE t.id = %s", (tid,)).fetchone()
        return _movimiento(fila)
    finally:
        repo.close()


@router.delete("/movimientos/{movimiento_id}", status_code=204,
               summary="Borrar un movimiento anotado a mano")
def borrar(movimiento_id: str, peticion: Request, usuario_id: str = Depends(usuario_actual)):
    repo = Repositorio()
    try:
        if not eliminar_manual(repo, usuario_id, movimiento_id):
            # Ajeno, inexistente o de un banco: misma respuesta, no se filtra nada.
            raise HTTPException(status_code=404, detail="Movimiento manual no encontrado.")
        bitacora.registrar(repo.conn, usuario_id, "datos.borrar_manual",
                           "movimiento %s" % movimiento_id, bitacora.ip_de(peticion))
        repo.commit()
    finally:
        repo.close()
