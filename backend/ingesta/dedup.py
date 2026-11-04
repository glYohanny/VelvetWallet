# -*- coding: utf-8 -*-
"""
Deduplicación entre fuentes (RF-09): ¿este movimiento de la cartola es el
mismo que ya trajo la API del banco?

No sirve comparar huellas exactas. La misma compra llega distinta por cada
camino:

  · API SFA  → "Jumbo", con fecha y hora de la transacción.
  · Cartola  → "COMPRA JUMBO LA FLORIDA 0912", con la fecha contable, que
               puede ser uno o dos días después (fines de semana, feriados).

Lo que no cambia es el monto, exacto y con signo. Por eso un par es candidato
cuando el monto es idéntico y las fechas están a no más de TOLERANCIA_DIAS.
Entre candidatos gana el de fecha más cercana y, a igual distancia, el de
glosa más parecida. El emparejamiento es uno a uno: dos cafés de $3.500 el
mismo día en la cartola se emparejan con los dos de la API, no los dos con
el primero.

Esta capa no sabe de base de datos. Recibe dos listas y devuelve qué entrante
corresponde a qué existente.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

TOLERANCIA_DIAS = 3

# Palabras que ponen los bancos en casi toda glosa y no distinguen nada.
_RUIDO = {"compra", "pago", "cargo", "abono", "transferencia", "transf", "pos", "web",
          "nacional", "internacional", "de", "del", "la", "el", "en", "a", "por",
          "con", "cl", "chile", "santiago", "spa", "ltda", "sa"}


@dataclass(frozen=True)
class Movimiento:
    clave: object        # lo que identifica al movimiento para quien llama
    fecha: date
    monto: Decimal
    glosa: str


def palabras(glosa: str) -> set[str]:
    texto = unicodedata.normalize("NFKD", glosa or "").encode("ascii", "ignore").decode().lower()
    return {p for p in re.findall(r"[a-z]{2,}", texto) if p not in _RUIDO}


def parecido(a: str, b: str) -> float:
    """Jaccard de las palabras significativas: 0 nada en común, 1 iguales."""
    pa, pb = palabras(a), palabras(b)
    if not pa or not pb:
        return 0.0
    return len(pa & pb) / len(pa | pb)


def emparejar(entrantes: list[Movimiento], existentes: list[Movimiento],
              tolerancia_dias: int = TOLERANCIA_DIAS) -> dict:
    """{clave del entrante: clave del existente} para los que son el mismo movimiento."""
    por_monto: dict[Decimal, list[Movimiento]] = {}
    for e in existentes:
        por_monto.setdefault(Decimal(e.monto), []).append(e)

    candidatos = []
    for n in entrantes:
        for e in por_monto.get(Decimal(n.monto), ()):
            dias = abs((n.fecha - e.fecha).days)
            if dias <= tolerancia_dias:
                candidatos.append((dias, -parecido(n.glosa, e.glosa), n.clave, e.clave))

    # Primero los pares más seguros; cada movimiento se usa una sola vez.
    candidatos.sort(key=lambda c: (c[0], c[1]))
    pares: dict = {}
    usados: set = set()
    for _, _, n, e in candidatos:
        if n in pares or e in usados:
            continue
        pares[n] = e
        usados.add(e)
    return pares
