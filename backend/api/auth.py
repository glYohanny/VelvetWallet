# -*- coding: utf-8 -*-
"""
Endpoints de autenticación — el contrato que acordó la app (servicios/auth.ts):

  POST /api/auth/registro  { nombre, email, password }  -> SesionIniciada
  POST /api/auth/sesion    { email, password }          -> SesionIniciada

SesionIniciada = { token, expiraEn, usuario }
usuario        = { id, nombre, email, sueldoDeclarado, creadoEn }

Trabaja contra la tabla `usuario` del modelo canónico. La respuesta usa los
nombres en camelCase que espera la app (sueldoDeclarado, creadoEn), distintos
de las columnas (sueldo_declarado, created_at): la traducción va aquí.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import db, seguridad
from ingesta.cifrado import ctx_sueldo, descifrar_numero

router = APIRouter(prefix="/api/auth", tags=["Autenticación"])


class DatosRegistro(BaseModel):
    nombre: str
    email: str
    password: str


class Credenciales(BaseModel):
    email: str
    password: str


def _armar_sesion(fila) -> dict:
    """fila = (id, nombre, email, sueldo_declarado, created_at) -> SesionIniciada."""
    id_, nombre, email, sueldo, creado = fila
    token, expira = seguridad.crear_token(str(id_))
    return {
        "token": token,
        "expiraEn": expira,
        "usuario": {
            "id": str(id_),
            "nombre": nombre,
            "email": str(email),
            "sueldoDeclarado": descifrar_numero(sueldo, ctx_sueldo(id_)),
            "creadoEn": creado.isoformat() if hasattr(creado, "isoformat") else str(creado),
        },
    }


@router.post("/registro", summary="Crear una cuenta")
def registrar(datos: DatosRegistro):
    nombre = datos.nombre.strip()
    email = datos.email.strip().lower()

    # Las mismas validaciones que el front: validar solo en el cliente no basta,
    # porque se puede llamar al API directamente.
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre es obligatorio.")
    if len(datos.password) < 8:
        raise HTTPException(status_code=400, detail="La contraseña debe tener al menos 8 caracteres.")

    with db.conectar() as conn:
        existe = conn.execute(
            "SELECT 1 FROM usuario WHERE email = %s", (email,)
        ).fetchone()
        if existe:
            raise HTTPException(status_code=409, detail="Ya existe una cuenta con este correo.")

        fila = conn.execute(
            """INSERT INTO usuario (email, nombre, hash_password)
               VALUES (%s, %s, %s)
               RETURNING id, nombre, email, sueldo_declarado, created_at""",
            (email, nombre, seguridad.hashear_password(datos.password)),
        ).fetchone()
        conn.commit()

    return _armar_sesion(fila)


@router.post("/sesion", summary="Iniciar sesión")
def iniciar_sesion(cred: Credenciales):
    email = cred.email.strip().lower()

    with db.conectar() as conn:
        fila = conn.execute(
            """SELECT id, nombre, email, sueldo_declarado, created_at, hash_password
               FROM usuario WHERE email = %s""",
            (email,),
        ).fetchone()

    # Mensaje único a propósito (igual que el front): no revelar si el correo
    # existe, porque distinguirlo permitiría averiguar qué correos hay registrados.
    if fila is None or not seguridad.verificar_password(cred.password, fila[5]):
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos.")

    return _armar_sesion(fila[:5])
