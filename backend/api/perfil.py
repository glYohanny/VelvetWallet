# -*- coding: utf-8 -*-
"""
Perfil financiero del usuario — el sueldo (RF-36).

  GET /api/perfil        -> lo declarado y lo detectado
  PUT /api/perfil/sueldo -> declara (o borra) el sueldo

El principio del proyecto es cero fricción mensual: lo que no cambia no se
vuelve a escribir. El sueldo es el caso puro de eso, así que se configura una
vez y se mantiene. Más todavía: como el abono ya llega por el estándar, la app
no pide escribirlo sino CONFIRMAR el que se detectó.

Por qué se guarda el declarado aunque se sepa detectar: el detectado es una
inferencia y cambia si el banco cambia la glosa o si hay un mes raro; el
declarado es una afirmación de la persona y no se mueve solo. La proyección de
metas prefiere el declarado y solo cae al detectado si no hay ninguno.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from . import bitacora, db
from ingesta.cifrado import ctx_sueldo, cifrar_numero, descifrar_numero
from .sesion_actual import usuario_actual

from motor.sueldo import Abono, Sueldo, detectar

router = APIRouter(prefix="/api/perfil", tags=["Perfil"])

# Tope de cordura al declarar. No es una regla del negocio sino una defensa
# contra el dedo pegado en el cero: un sueldo de mil millones rompería la
# proyección de metas sin que nadie se diera cuenta de por qué.
MAXIMO = 1_000_000_000


class SueldoDeclarado(BaseModel):
    #: null borra lo declarado y vuelve a dejar mandando lo detectado.
    monto: float | None


def _abonos(conn, usuario_id: str) -> list[Abono]:
    """
    Candidatos a sueldo: los abonos del usuario, sin los traspasos propios.

    La exclusión de transferencias va aquí y no en el motor porque depende de
    cómo glosa cada institución, que es conocimiento de la ingesta, no del
    algoritmo.
    """
    filas = conn.execute(
        """
        SELECT t.fecha, t.glosa_original, t.monto
        FROM transaccion t
        JOIN cuenta c ON c.id = t.cuenta_id
        WHERE c.usuario_id = %s
          AND t.monto > 0
          AND t.estado <> 'excluido'
          AND t.glosa_original !~* 'transferencia'
        """,
        (usuario_id,),
    ).fetchall()
    return [Abono(fecha=f["fecha"], glosa=f["glosa_original"], monto=float(f["monto"]))
            for f in filas]


def sueldo_detectado(conn, usuario_id: str) -> Sueldo | None:
    """El sueldo que se ve en los abonos, o None si no hay evidencia."""
    return detectar(_abonos(conn, usuario_id))


def sueldo_mensual(conn, usuario_id: str) -> float:
    """
    Cuánto entra al mes, para la proyección de metas.

    Manda lo declarado por la persona; si no declaró, lo detectado; si tampoco
    hay evidencia, cero —y la proyección se abstiene, que es la respuesta
    correcta cuando no se sabe.

    Es un ingreso CONSTANTE y no los abonos mes a mes, por el mismo motivo que
    el resumen del panel: el sueldo llega a fin de mes, así que contar abonos
    reales dejaría casi todos los meses en rojo hasta el día de pago.
    """
    fila = conn.execute(
        "SELECT sueldo_declarado FROM usuario WHERE id = %s", (usuario_id,)
    ).fetchone()
    if fila and fila["sueldo_declarado"] is not None:
        return descifrar_numero(fila["sueldo_declarado"], ctx_sueldo(usuario_id))
    s = sueldo_detectado(conn, usuario_id)
    return s.monto if s else 0.0


def _describir(s: Sueldo | None) -> dict | None:
    if s is None:
        return None
    return {
        "monto": s.monto,
        "glosa": s.glosa,
        "meses": s.meses,
        "desde": s.desde.isoformat() if isinstance(s.desde, date) else str(s.desde),
        "hasta": s.hasta.isoformat() if isinstance(s.hasta, date) else str(s.hasta),
    }


@router.get("", summary="Sueldo declarado y sueldo detectado")
def ver_perfil(usuario_id: str = Depends(usuario_actual)):
    with db.conectar(diccionarios=True) as conn:
        fila = conn.execute(
            "SELECT sueldo_declarado FROM usuario WHERE id = %s", (usuario_id,)
        ).fetchone()
        if fila is None:
            raise HTTPException(status_code=404, detail="Usuario no encontrado.")
        detectado = sueldo_detectado(conn, usuario_id)

    return {
        "sueldoDeclarado": descifrar_numero(fila["sueldo_declarado"], ctx_sueldo(usuario_id)),
        "sueldoDetectado": _describir(detectado),
    }


@router.put("/sueldo", summary="Declarar el sueldo mensual")
def declarar_sueldo(datos: SueldoDeclarado, peticion: Request,
                    usuario_id: str = Depends(usuario_actual)):
    monto = datos.monto
    if monto is not None:
        if monto <= 0:
            raise HTTPException(status_code=400, detail="El sueldo debe ser mayor que cero.")
        if monto > MAXIMO:
            raise HTTPException(status_code=400, detail="Ese monto no parece un sueldo.")
        monto = round(monto)

    with db.conectar(diccionarios=True) as conn:
        fila = conn.execute(
            """UPDATE usuario SET sueldo_declarado = %s WHERE id = %s
               RETURNING sueldo_declarado""",
            # Cifrado en la aplicación (RF-31): en la base queda texto ilegible.
            (cifrar_numero(monto, ctx_sueldo(usuario_id)), usuario_id),
        ).fetchone()
        if fila is None:
            raise HTTPException(status_code=404, detail="Usuario no encontrado.")
        # Dato personal que cambia por voluntad del titular: queda en el
        # registro de actividades de tratamiento (Ley 21.719).
        bitacora.registrar(conn, usuario_id, "perfil.actualizar", "usuario",
                           ip=bitacora.ip_de(peticion))
        detectado = sueldo_detectado(conn, usuario_id)

    return {
        "sueldoDeclarado": descifrar_numero(fila["sueldo_declarado"], ctx_sueldo(usuario_id)),
        "sueldoDetectado": _describir(detectado),
    }
