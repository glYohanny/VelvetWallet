# -*- coding: utf-8 -*-
"""
Lectura de cartolas en CSV (RF-12): instituciones fuera del SFA e historial
anterior a la conexión.

No hay un formato común: cada banco exporta su cartola distinto. Lo que sí se
repite, y es lo que este lector aprovecha:

  · Separador `;` (Excel en español) o `,`. Se detecta solo.
  · Unas líneas de título antes del encabezado ("Cartola Cuenta Corriente",
    el RUT, el período). Se saltan hasta encontrar la fila con los nombres de
    columna.
  · Una columna de fecha, una de descripción, y el monto en UNA columna con
    signo o en DOS (cargos y abonos).
  · Montos a la chilena: `$ 12.345`, `-12.345`, `12.345,50`.
  · Archivos en UTF-8 o en Windows-1252 (lo que guarda Excel en Windows).

Esta capa no sabe de base de datos: recibe bytes y devuelve filas ya con
fecha, monto con signo y glosa, más la lista de líneas que no pudo leer y por
qué. Una línea mala no tumba el archivo: se informa y se sigue.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

MAX_BYTES = 2 * 1024 * 1024     # una cartola de varios años pesa bastante menos
MAX_FILAS = 5000
_LINEAS_DE_TITULO = 30          # cuántas líneas se buscan antes de rendirse con el encabezado


class CartolaInvalida(Exception):
    """El archivo completo no se puede leer como cartola. El mensaje es para la persona."""


@dataclass(frozen=True)
class FilaCartola:
    linea: int          # número de línea en el archivo, para poder citarla
    fecha: date
    monto: Decimal      # con signo: negativo = cargo, positivo = abono
    glosa: str
    crudo: dict         # la fila tal como venía (encabezado → valor), para Mongo


@dataclass(frozen=True)
class LineaRechazada:
    linea: int
    motivo: str


@dataclass
class Cartola:
    filas: list[FilaCartola] = field(default_factory=list)
    rechazadas: list[LineaRechazada] = field(default_factory=list)
    columnas: dict = field(default_factory=dict)   # rol → nombre de la columna en el archivo


# ── Encabezado: qué columna es cuál ──────────────────────────────────────────

def _normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", sin_tildes.lower()).strip()


# Por rol, palabras con que los bancos nombran la columna. Se compara contra el
# encabezado normalizado (sin tildes, minúsculas). El orden importa: la primera
# palabra que calce gana, así "fecha" no se confunde con "fecha valuta".
_ROLES = {
    "fecha": ("fecha operacion", "fecha transaccion", "fecha movimiento", "fecha", "date"),
    "glosa": ("descripcion", "glosa", "detalle", "concepto", "comercio", "movimiento",
              "description"),
    "cargo": ("cargos", "cargo", "debitos", "debito", "giros", "giro"),
    "abono": ("abonos", "abono", "creditos", "credito", "depositos", "deposito"),
    "monto": ("monto", "importe", "valor", "amount"),
}


def _detectar_columnas(encabezado: list[str]) -> dict[str, int] | None:
    nombres = [_normalizar(c) for c in encabezado]
    roles: dict[str, int] = {}
    for rol, palabras in _ROLES.items():
        for palabra in palabras:
            for i, n in enumerate(nombres):
                if i in roles.values():
                    continue
                if n == palabra or n.startswith(palabra + " "):
                    roles[rol] = i
                    break
            if rol in roles:
                break
    tiene_monto = "monto" in roles or "cargo" in roles or "abono" in roles
    if "fecha" in roles and "glosa" in roles and tiene_monto:
        return roles
    return None


# ── Valores ──────────────────────────────────────────────────────────────────

_FORMATOS_FECHA = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%Y/%m/%d",
                   "%d/%m/%y", "%d-%m-%y")


def leer_fecha(texto: str) -> date:
    limpio = texto.strip().split(" ")[0].split("T")[0]
    for formato in _FORMATOS_FECHA:
        try:
            return datetime.strptime(limpio, formato).date()
        except ValueError:
            continue
    raise ValueError("fecha no reconocida: %r" % texto.strip())


def leer_monto(texto: str) -> Decimal | None:
    """
    Monto a la chilena → Decimal. None si la celda está vacía.

    '$ 12.345' → 12345 · '-12.345' → -12345 · '12.345,50' → 12345.50 ·
    '(1.200)' → -1200 · '1,234,567' → 1234567 (exportado en formato inglés).
    """
    t = texto.strip().replace("$", "").replace("CLP", "").replace(" ", "").replace(" ", "")
    if t in ("", "-"):
        return None
    negativo = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    if t.endswith("-"):                 # algunos bancos ponen el signo al final
        negativo, t = True, t[:-1]
    if t.startswith("-"):
        negativo, t = True, t[1:]
    elif t.startswith("+"):
        t = t[1:]

    if "." in t and "," in t:
        # El que aparece al final es el separador decimal.
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "." in t:
        if re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
            t = t.replace(".", "")      # 12.345 = doce mil (en CLP no hay decimales)
    elif "," in t:
        if re.fullmatch(r"\d{1,3}(,\d{3})+", t):
            t = t.replace(",", "")
        else:
            t = t.replace(",", ".")
    try:
        valor = Decimal(t)
    except InvalidOperation as e:
        raise ValueError("monto no reconocido: %r" % texto.strip()) from e
    return -valor if negativo else valor


# ── Archivo completo ─────────────────────────────────────────────────────────

def _decodificar(contenido: bytes) -> str:
    for codificacion in ("utf-8-sig", "cp1252"):
        try:
            return contenido.decode(codificacion)
        except UnicodeDecodeError:
            continue
    raise CartolaInvalida("No se pudo leer el archivo: no es texto (¿es un Excel .xlsx?).")


def _separador(texto: str) -> str:
    muestra = "\n".join(texto.splitlines()[:_LINEAS_DE_TITULO + 5])
    try:
        return csv.Sniffer().sniff(muestra, delimiters=";,\t|").delimiter
    except csv.Error:
        return max(";,\t", key=muestra.count)


def leer_cartola(contenido: bytes, hoy: date | None = None) -> Cartola:
    if not contenido or not contenido.strip():
        raise CartolaInvalida("El archivo está vacío.")
    if len(contenido) > MAX_BYTES:
        raise CartolaInvalida("El archivo pesa más de 2 MB. Exporta un período más corto.")
    hoy = hoy or date.today()

    texto = _decodificar(contenido)
    lineas = list(csv.reader(io.StringIO(texto), delimiter=_separador(texto)))

    roles = None
    inicio = 0
    for i, fila in enumerate(lineas[:_LINEAS_DE_TITULO]):
        roles = _detectar_columnas(fila)
        if roles:
            inicio = i
            break
    if roles is None:
        raise CartolaInvalida(
            "No se encontró el encabezado: la cartola necesita columnas de fecha, "
            "descripción y monto (o cargos y abonos)."
        )

    encabezado = [c.strip() for c in lineas[inicio]]
    cartola = Cartola(columnas={rol: encabezado[i] for rol, i in roles.items()})

    def celda(fila: list[str], rol: str) -> str:
        i = roles.get(rol)
        return fila[i] if i is not None and i < len(fila) else ""

    datos = lineas[inicio + 1:]
    if len(datos) > MAX_FILAS:
        raise CartolaInvalida("La cartola tiene más de %d líneas. Exporta un período más corto."
                              % MAX_FILAS)

    for desfase, fila in enumerate(datos):
        linea = inicio + 2 + desfase    # 1-based, contando el encabezado
        if not any(c.strip() for c in fila):
            continue
        texto_fecha = celda(fila, "fecha").strip()
        if not texto_fecha:
            # Totales y saldos al pie de la cartola: no son movimientos.
            continue
        try:
            fecha = leer_fecha(texto_fecha)
            if "monto" in roles:
                monto = leer_monto(celda(fila, "monto"))
            else:
                cargo = leer_monto(celda(fila, "cargo"))
                abono = leer_monto(celda(fila, "abono"))
                if cargo and abono:
                    raise ValueError("tiene cargo y abono a la vez")
                monto = -abs(cargo) if cargo else (abs(abono) if abono else None)
        except ValueError as e:
            cartola.rechazadas.append(LineaRechazada(linea, str(e)))
            continue

        if not monto:
            cartola.rechazadas.append(LineaRechazada(linea, "sin monto"))
            continue
        if fecha > hoy:
            cartola.rechazadas.append(LineaRechazada(linea, "fecha futura: %s" % fecha.isoformat()))
            continue
        glosa = " ".join(celda(fila, "glosa").split())[:255] or "Movimiento sin descripción"
        crudo = {encabezado[i] if i < len(encabezado) and encabezado[i] else "col%d" % i: v
                 for i, v in enumerate(fila)}
        cartola.filas.append(FilaCartola(linea, fecha, monto, glosa, crudo))

    return cartola
