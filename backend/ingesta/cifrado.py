# -*- coding: utf-8 -*-
"""
Cifrado en reposo de los datos sensibles (RF-31 / RNF-16, Ley 21.719).

Qué se cifra aquí, en la aplicación, antes de que el dato llegue a la base:

  · El refresh token de cada banco y a qué cliente corresponde (RUT y nombre),
    dentro de `consentimiento.alcance_rar`. El token es una credencial: con él
    se leen los datos de la persona en su banco sin volver a pedirle la clave.
  · El payload crudo que guarda MongoDB: es la respuesta íntegra del banco.
  · El sueldo declarado (`usuario.sueldo_declarado`).

Qué NO se cifra aquí, y por qué: los montos, fechas y glosas del modelo
canónico. Sobre ellos se calculan sumas, filtros y proyecciones en SQL, y
cifrarlos en la aplicación obligaría a traer todo a memoria para cualquier
cálculo. Esos datos quedan protegidos por el cifrado del almacenamiento que
dan los propios motores (Neon y Atlas cifran sus discos). Son dos capas
distintas: la del almacenamiento protege si alguien se lleva el disco; la de
la aplicación protege además si alguien llega a leer la base (un respaldo
filtrado, una consulta con credenciales robadas): ve texto cifrado.

**Algoritmo.** AES-256-GCM (cifrado autenticado): además de ocultar el dato,
detecta cualquier modificación. Un byte cambiado hace fallar el descifrado en
vez de entregar un dato corrupto, lo que también sirve a la trazabilidad del
payload crudo (RF-06): se puede demostrar que no se tocó.

**Cada valor queda atado a su lugar.** Se cifra con un "contexto" (el campo y
el registro al que pertenece, p. ej. `usuario.sueldo_declarado|<id>`) que va
como dato asociado (AAD) de GCM. Si alguien con acceso a la base copia el
sueldo cifrado de una persona en la fila de otra, o el token de un banco en
otra conexión, no descifra: el contexto ya no calza.

**Formato guardado:** `enc:v1:<id de clave>:<base64url(nonce || cifrado || tag)>`.
El prefijo permite reconocer lo que todavía está en claro (datos anteriores a
este cambio) y el id de clave permite rotarla: se descifra con la clave que
cifró y se vuelve a cifrar con la actual (ver `cifrar_datos_existentes.py`).

**La clave** vive en la variable de entorno VELVET_CLAVE_CIFRADO (32 bytes en
base64), nunca en la base ni en el repositorio. Todos los que usen la misma
base tienen que tener la misma clave. Para generar una:

    python -m ingesta.cifrado --generar-clave
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import config  # noqa: F401 — carga backend/.env antes de leer la clave

log = logging.getLogger(__name__)

PREFIJO = "enc:v1:"
_NONCE = 12  # bytes; el tamaño recomendado para GCM

# Solo para desarrollo: si no hay clave configurada, se usa una derivada de
# una frase fija para que el proyecto levante sin pasos extra. NO protege nada
# (está en el repositorio) y se avisa en el log. Igual que JWT_SECRET.
_FRASE_DESARROLLO = b"velvet-wallet-clave-de-desarrollo-no-usar-en-produccion"


class ErrorDeCifrado(Exception):
    """
    No se pudo descifrar un valor: la clave no es la que lo cifró, el dato fue
    alterado o se leyó en otro contexto. Nunca se devuelve un dato a medias.
    """


def _decodificar_clave(texto: str) -> bytes:
    try:
        clave = base64.urlsafe_b64decode(texto.strip() + "=" * (-len(texto.strip()) % 4))
    except (ValueError, TypeError) as e:
        raise ErrorDeCifrado("La clave de cifrado no es base64 válido.") from e
    if len(clave) != 32:
        raise ErrorDeCifrado(
            "La clave de cifrado debe tener 32 bytes (AES-256); tiene %d. "
            "Genera una con: python -m ingesta.cifrado --generar-clave" % len(clave)
        )
    return clave


def _id_de(clave: bytes) -> str:
    """Huella corta de la clave, para saber cuál cifró cada valor. No la revela."""
    return hashlib.sha256(b"velvet-kid" + clave).hexdigest()[:8]


@lru_cache(maxsize=1)
def _claves() -> tuple[str, dict[str, bytes]]:
    """(id de la clave actual, {id: clave}) con la actual y las anteriores."""
    texto = os.getenv("VELVET_CLAVE_CIFRADO", "").strip()
    if texto:
        actual = _decodificar_clave(texto)
    else:
        log.warning(
            "VELVET_CLAVE_CIFRADO no está configurada: se usa la clave de "
            "desarrollo, que NO protege los datos. Configúrala en backend/.env."
        )
        actual = hashlib.sha256(_FRASE_DESARROLLO).digest()

    claves = {_id_de(actual): actual}
    # Las anteriores solo descifran: sirven mientras se rota la clave.
    for t in os.getenv("VELVET_CLAVES_ANTERIORES", "").split(","):
        if t.strip():
            c = _decodificar_clave(t)
            claves.setdefault(_id_de(c), c)
    return _id_de(actual), claves


def recargar_claves() -> None:
    """Vuelve a leer las claves del entorno (pruebas y rotación)."""
    _claves.cache_clear()


def esta_cifrado(valor) -> bool:
    return isinstance(valor, str) and valor.startswith(PREFIJO)


def cifrado_con_clave_actual(valor) -> bool:
    """True si ya está cifrado con la clave vigente (no hay que tocarlo)."""
    return esta_cifrado(valor) and valor[len(PREFIJO):].split(":", 1)[0] == _claves()[0]


def cifrar(texto: str | None, contexto: str) -> str | None:
    """Cifra un texto. None queda None: la ausencia de dato no es un secreto."""
    if texto is None:
        return None
    if not isinstance(texto, str):
        raise TypeError("cifrar() recibe texto; usa cifrar_numero() para montos.")
    kid, claves = _claves()
    nonce = secrets.token_bytes(_NONCE)
    sellado = AESGCM(claves[kid]).encrypt(nonce, texto.encode("utf-8"), contexto.encode("utf-8"))
    cuerpo = base64.urlsafe_b64encode(nonce + sellado).decode("ascii").rstrip("=")
    return "%s%s:%s" % (PREFIJO, kid, cuerpo)


def descifrar(valor: str | None, contexto: str) -> str | None:
    """
    Descifra un valor guardado con cifrar(). Un valor que no tiene el prefijo
    se devuelve tal cual: es un dato anterior al cifrado, todavía en claro, y
    se cifra en la próxima escritura (o con cifrar_datos_existentes.py).
    """
    if valor is None or not esta_cifrado(valor):
        return valor
    try:
        kid, cuerpo = valor[len(PREFIJO):].split(":", 1)
    except ValueError as e:
        raise ErrorDeCifrado("Valor cifrado con formato inválido.") from e
    clave = _claves()[1].get(kid)
    if clave is None:
        raise ErrorDeCifrado(
            "El dato se cifró con una clave que no está configurada (id %s). "
            "¿VELVET_CLAVE_CIFRADO es la misma que usa el resto del equipo?" % kid
        )
    try:
        crudo = base64.urlsafe_b64decode(cuerpo + "=" * (-len(cuerpo) % 4))
        nonce, sellado = crudo[:_NONCE], crudo[_NONCE:]
        return AESGCM(clave).decrypt(nonce, sellado, contexto.encode("utf-8")).decode("utf-8")
    except (InvalidTag, ValueError) as e:
        raise ErrorDeCifrado(
            "No se pudo descifrar (%s): el dato fue alterado o no pertenece a "
            "este registro." % contexto.split("|", 1)[0]
        ) from e


def cifrar_numero(numero, contexto: str) -> str | None:
    if numero is None:
        return None
    return cifrar(str(numero), contexto)


def descifrar_numero(valor, contexto: str) -> float | None:
    """Devuelve float. Acepta también un número en claro (dato anterior)."""
    texto = descifrar(valor if valor is None or isinstance(valor, str) else str(valor), contexto)
    return float(texto) if texto is not None else None


# ── Contextos: un nombre por campo, atado al registro ───────────────────────
# Centralizados aquí para que escritura y lectura no puedan discrepar.

def ctx_sueldo(usuario_id) -> str:
    return "usuario.sueldo_declarado|%s" % usuario_id


def ctx_consentimiento(conexion_id, campo: str) -> str:
    return "consentimiento.alcance_rar.%s|%s" % (campo, conexion_id)


def ctx_payload(conexion_id) -> str:
    return "payload_crudo.payload|%s" % conexion_id


# Campos del alcance RAR que se guardan cifrados. Los permisos, el consentId y
# el proveedor quedan en claro: se muestran a la persona (RF-27) y no dan
# acceso a nada por sí solos.
CAMPOS_SENSIBLES_ALCANCE = ("refreshToken", "rutCliente", "nombreCliente")


def cifrar_alcance(alcance: dict | None, conexion_id) -> dict | None:
    if alcance is None:
        return None
    salida = dict(alcance)
    for campo in CAMPOS_SENSIBLES_ALCANCE:
        valor = salida.get(campo)
        if valor is not None and not cifrado_con_clave_actual(valor):
            salida[campo] = cifrar(descifrar(valor, ctx_consentimiento(conexion_id, campo)),
                                   ctx_consentimiento(conexion_id, campo))
    return salida


def descifrar_alcance(alcance: dict | None, conexion_id) -> dict | None:
    if alcance is None:
        return None
    salida = dict(alcance)
    for campo in CAMPOS_SENSIBLES_ALCANCE:
        if campo in salida:
            salida[campo] = descifrar(salida[campo], ctx_consentimiento(conexion_id, campo))
    return salida


if __name__ == "__main__":
    import sys

    if "--generar-clave" in sys.argv:
        print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii"))
    else:
        print("Uso: python -m ingesta.cifrado --generar-clave")
