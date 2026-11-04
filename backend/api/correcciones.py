# -*- coding: utf-8 -*-
"""
Las correcciones del usuario sobre un movimiento (RF-14), además de
recategorizar (que vive en api/datos.py):

  POST   /api/movimientos/{id}/excluir    -> no es gasto (transferencia entre cuentas propias…)
  POST   /api/movimientos/{id}/duplicado  -> es el mismo movimiento que otro
  DELETE /api/movimientos/{id}/exclusion  -> vuelve a contar
  PUT    /api/movimientos/{id}/division   -> repartirlo entre varias categorías
  DELETE /api/movimientos/{id}/division   -> deshacer el reparto

**El dato original no se sobrescribe nunca.** Monto, fecha, glosa y el crudo
del banco quedan como llegaron. Cada corrección es una fila nueva en
`correccion` (quién, cuándo, qué): la tabla solo crece, y deshacer también es
una fila, así que la historia completa se puede reconstruir.

Lo único que se escribe en `transaccion` es `estado = 'excluido'`, y es un
derivado de esa capa, no un dato del banco: lo leen en SQL el resumen, el
flujo, las metas y el detector de recurrencias, y por eso conviene tenerlo a
mano en vez de recalcularlo desde las correcciones en cada consulta. La
sincronización con el banco no lo toca, así que una corrección sobrevive a
las resincronizaciones.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.rows import dict_row
from psycopg.types.json import Json
from pydantic import BaseModel, Field

from . import bitacora
from .datos import _SELECT_MOVIMIENTOS, _movimiento
from .sesion_actual import usuario_actual

from clasificador.taxonomia import CATEGORIAS
from ingesta.repositorio import Repositorio
from ingesta.sincronizar import recalcular_recurrencias

router = APIRouter(prefix="/api/movimientos", tags=["Correcciones"])

MAX_PARTES = 8


def _cargar(repo: Repositorio, usuario_id: str, movimiento_id: str) -> dict:
    """El movimiento, si es de esta persona. Lo bloquea hasta el commit."""
    with repo.conn.cursor(row_factory=dict_row) as cur:
        fila = cur.execute(
            """SELECT t.id, t.monto, t.estado FROM transaccion t
               JOIN cuenta c ON c.id = t.cuenta_id
               WHERE t.id::text = %s AND c.usuario_id = %s
               FOR UPDATE OF t""",
            (movimiento_id, usuario_id),
        ).fetchone()
    if fila is None:
        # Ajeno o inexistente: misma respuesta, no se filtra nada.
        raise HTTPException(status_code=404, detail="Movimiento no encontrado.")
    return fila


def _ultima(repo: Repositorio, transaccion_id, tipos: tuple[str, ...]) -> dict | None:
    fila = repo.conn.execute(
        """SELECT tipo, valor FROM correccion
           WHERE transaccion_id = %s AND tipo = ANY(%s)
           ORDER BY created_at DESC LIMIT 1""",
        (transaccion_id, list(tipos)),
    ).fetchone()
    return {"tipo": fila[0], "valor": fila[1] or {}} if fila else None


def _anotar(repo: Repositorio, transaccion_id, usuario_id: str, tipo: str, valor: dict) -> None:
    repo.conn.execute(
        "INSERT INTO correccion (transaccion_id, usuario_id, tipo, valor) VALUES (%s, %s, %s, %s)",
        (transaccion_id, usuario_id, tipo, Json(valor)),
    )


def _duplicados_que_apuntan_a(repo: Repositorio, usuario_id: str, transaccion_id) -> int:
    """Cuántos movimientos vigentes están marcados como duplicado de este."""
    return repo.conn.execute(
        """SELECT count(*) FROM transaccion t
           JOIN cuenta c ON c.id = t.cuenta_id
           CROSS JOIN LATERAL (
               SELECT co.tipo, co.valor FROM correccion co
               WHERE co.transaccion_id = t.id AND co.tipo IN ('excluir', 'marcar_duplicado')
               ORDER BY co.created_at DESC LIMIT 1) ult
           WHERE c.usuario_id = %s AND t.estado = 'excluido'
             AND ult.tipo = 'marcar_duplicado' AND ult.valor->>'duplicado_de' = %s""",
        (usuario_id, str(transaccion_id)),
    ).fetchone()[0]


def _responder(repo: Repositorio, transaccion_id) -> dict:
    with repo.conn.cursor(row_factory=dict_row) as cur:
        fila = cur.execute(_SELECT_MOVIMIENTOS + " WHERE t.id = %s", (transaccion_id,)).fetchone()
    return _movimiento(fila)


def _excluir(repo: Repositorio, usuario_id: str, mov: dict, tipo: str, valor: dict,
             peticion: Request, accion: str, detalle: str) -> dict:
    if _duplicados_que_apuntan_a(repo, usuario_id, mov["id"]):
        raise HTTPException(
            status_code=409,
            detail="Otro movimiento está marcado como duplicado de este. Si este tampoco "
                   "cuenta, no quedaría ninguno: desmarca primero el duplicado.")
    _anotar(repo, mov["id"], usuario_id, tipo, {**valor, "estado_anterior": mov["estado"]})
    repo.conn.execute("UPDATE transaccion SET estado = 'excluido' WHERE id = %s", (mov["id"],))
    bitacora.registrar(repo.conn, usuario_id, accion, detalle, bitacora.ip_de(peticion))
    recalcular_recurrencias(repo, usuario_id)   # un cobro menos puede cortar una serie
    repo.commit()
    return _responder(repo, mov["id"])


@router.post("/{movimiento_id}/excluir", summary="No cuenta como gasto ni como ingreso")
def excluir(movimiento_id: str, peticion: Request, usuario_id: str = Depends(usuario_actual)):
    """
    Para lo que el banco registra pero no es gasto de verdad: una
    transferencia entre cuentas propias, un reembolso que se anula con otro.
    Sigue visible en la lista, atenuado, pero deja de sumar.
    """
    repo = Repositorio()
    try:
        mov = _cargar(repo, usuario_id, movimiento_id)
        actual = _ultima(repo, mov["id"], ("excluir", "marcar_duplicado"))
        if mov["estado"] == "excluido" and actual and actual["tipo"] == "excluir":
            return _responder(repo, mov["id"])   # ya estaba: doble toque, no es un error
        return _excluir(repo, usuario_id, mov, "excluir", {}, peticion,
                        "correccion.excluir", "movimiento %s" % mov["id"])
    finally:
        repo.close()


class Duplicado(BaseModel):
    duplicadoDe: str = Field(min_length=1)


@router.post("/{movimiento_id}/duplicado", summary="Es el mismo movimiento que otro")
def marcar_duplicado(movimiento_id: str, datos: Duplicado, peticion: Request,
                     usuario_id: str = Depends(usuario_actual)):
    """
    El mismo gasto quedó dos veces (anotado a mano y después llegó del banco,
    o una cartola que la deduplicación no alcanzó a reconocer). Este deja de
    contar y queda enlazado al que sí cuenta.
    """
    repo = Repositorio()
    try:
        mov = _cargar(repo, usuario_id, movimiento_id)
        if datos.duplicadoDe == str(mov["id"]):
            raise HTTPException(status_code=422, detail="Un movimiento no es duplicado de sí mismo.")
        otro = _cargar(repo, usuario_id, datos.duplicadoDe)
        if otro["estado"] == "excluido":
            raise HTTPException(status_code=422,
                                detail="Ese otro movimiento tampoco cuenta: elige uno que sí cuente.")
        if otro["monto"] != mov["monto"]:
            raise HTTPException(
                status_code=422,
                detail="Los montos no son iguales, así que no es el mismo movimiento. Si este "
                       "no corresponde, usa Excluir del gasto.")
        return _excluir(repo, usuario_id, mov, "marcar_duplicado",
                        {"duplicado_de": str(otro["id"])}, peticion,
                        "correccion.duplicado", "movimiento %s" % mov["id"])
    finally:
        repo.close()


@router.delete("/{movimiento_id}/exclusion", summary="Vuelve a contar")
def volver_a_contar(movimiento_id: str, peticion: Request,
                    usuario_id: str = Depends(usuario_actual)):
    repo = Repositorio()
    try:
        mov = _cargar(repo, usuario_id, movimiento_id)
        actual = _ultima(repo, mov["id"], ("excluir", "marcar_duplicado"))
        if mov["estado"] != "excluido" or actual is None:
            return _responder(repo, mov["id"])
        _anotar(repo, mov["id"], usuario_id, actual["tipo"], {"deshacer": True})
        repo.conn.execute("UPDATE transaccion SET estado = %s WHERE id = %s",
                          (actual["valor"].get("estado_anterior") or "confirmado", mov["id"]))
        bitacora.registrar(repo.conn, usuario_id, "correccion.deshacer",
                           "vuelve a contar el movimiento %s" % mov["id"], bitacora.ip_de(peticion))
        recalcular_recurrencias(repo, usuario_id)
        repo.commit()
        return _responder(repo, mov["id"])
    finally:
        repo.close()


class Parte(BaseModel):
    #: Positivo, como lo escribe la persona; el signo lo pone el movimiento.
    monto: float = Field(gt=0)
    categoria: str


class Division(BaseModel):
    partes: list[Parte] = Field(min_length=2, max_length=MAX_PARTES)


@router.put("/{movimiento_id}/division", summary="Repartir un gasto entre categorías")
def dividir(movimiento_id: str, datos: Division, peticion: Request,
            usuario_id: str = Depends(usuario_actual)):
    """
    Una compra del supermercado que fue mitad comida y mitad cosas de la casa.
    El movimiento sigue siendo uno, por el mismo monto; lo que cambia es cómo
    se reparte en el gasto por categoría. Las partes tienen que sumar
    exactamente el monto: si no, el reparto inventaría o escondería plata.
    """
    repo = Repositorio()
    try:
        mov = _cargar(repo, usuario_id, movimiento_id)
        if mov["monto"] >= 0:
            raise HTTPException(status_code=422, detail="Solo los gastos se reparten entre categorías.")
        if mov["estado"] == "excluido":
            raise HTTPException(status_code=422,
                                detail="Este movimiento no cuenta como gasto: no hay nada que repartir.")
        if len({p.categoria for p in datos.partes}) != len(datos.partes):
            raise HTTPException(status_code=422,
                                detail="Cada parte va en una categoría distinta.")
        for p in datos.partes:
            if p.categoria not in CATEGORIAS:
                raise HTTPException(status_code=422, detail="Categoría no válida: %s." % p.categoria)
            if p.monto != round(p.monto):
                raise HTTPException(status_code=422, detail="Los montos van en pesos, sin decimales.")
        total = round(-float(mov["monto"]))
        suma = round(sum(p.monto for p in datos.partes))
        if suma != total:
            raise HTTPException(
                status_code=422,
                detail="Las partes suman $%s y el gasto es de $%s." % (
                    f"{suma:,}".replace(",", "."), f"{total:,}".replace(",", ".")))
        _anotar(repo, mov["id"], usuario_id, "dividir", {
            "partes": [{"monto": -round(p.monto), "categoria": p.categoria} for p in datos.partes]})
        bitacora.registrar(repo.conn, usuario_id, "correccion.dividir",
                           "movimiento %s en %d partes" % (mov["id"], len(datos.partes)),
                           bitacora.ip_de(peticion))
        repo.commit()
        return _responder(repo, mov["id"])
    finally:
        repo.close()


@router.delete("/{movimiento_id}/division", summary="Deshacer el reparto")
def deshacer_division(movimiento_id: str, peticion: Request,
                      usuario_id: str = Depends(usuario_actual)):
    repo = Repositorio()
    try:
        mov = _cargar(repo, usuario_id, movimiento_id)
        actual = _ultima(repo, mov["id"], ("dividir",))
        if actual and not actual["valor"].get("deshacer"):
            _anotar(repo, mov["id"], usuario_id, "dividir", {"deshacer": True})
            bitacora.registrar(repo.conn, usuario_id, "correccion.deshacer",
                               "une de nuevo el movimiento %s" % mov["id"],
                               bitacora.ip_de(peticion))
            repo.commit()
        return _responder(repo, mov["id"])
    finally:
        repo.close()
