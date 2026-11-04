# -*- coding: utf-8 -*-
"""
Consentimiento por finalidad de tratamiento (Ley 21.719).

  GET  /api/privacidad/finalidades        -> qué se pide y si está consentido
  POST /api/privacidad/finalidades/{id}   -> otorgar o revocar

Por qué existe aparte del consentimiento bancario: autorizar a Velvet a LEER
los datos del banco no autoriza a USARLOS para otra cosa. Entrenar un modelo
con los gastos de alguien es una finalidad distinta de mostrárselos, y la ley
pide consentimiento específico, informado y revocable **para cada una**.

Tres reglas que el código hace cumplir, no solo declara:
  · Nadie queda consentido por omisión: sin fila, no hay permiso.
  · El consentimiento vence (90 días) y hay que renovarlo.
  · Revocar no borra la fila; la marca. Queda el registro de que existió.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import bitacora, db
from ingesta import config as config_ingesta
from ingesta.cifrado import ctx_sueldo, descifrar_numero
from ingesta import conexiones_bd
from .sesion_actual import usuario_actual

router = APIRouter(prefix="/api/privacidad", tags=["Privacidad"])

# Vigencia del consentimiento. La misma que el acceso bancario, para que la
# persona no tenga que acordarse de dos plazos distintos.
DIAS_VIGENCIA = 90

# Versión del texto que se le muestra a la persona. Si el texto cambia —si se
# amplía lo que se hace con los datos— esta versión sube y los consentimientos
# otorgados sobre el texto anterior dejan de cubrir la finalidad nueva: hay que
# volver a pedirlo. Consentir no es un "sí" permanente a lo que venga.
VERSION_TEXTO = "2026-10-1"

# Catálogo de finalidades. Cada una se consiente por separado: no existe un
# "acepto todo".
FINALIDADES = {
    "entrenamiento_modelos": {
        "titulo": "Mejorar las categorías de gasto",
        "resumen": (
            "Usar el monto y el comercio de tus transacciones para entrenar los modelos "
            "que clasifican tus gastos."
        ),
        "detalle": [
            "Nos ayuda a acertar más al identificar en qué tipo de gasto y en qué comercios "
            "concentras tu plata, y a mejorar las proyecciones que te mostramos.",
            "Es específico para este fin: no usamos estos datos para otra cosa, no los vendemos "
            "ni los compartimos con terceros.",
            "Para entrenar trabajamos con tus datos de forma anonimizada y agregada siempre que "
            "es posible.",
            "Puedes revocarlo cuando quieras, gratis, desde esta misma pantalla. Al revocar "
            "dejamos de usar tus datos para este fin y quitamos de los conjuntos de "
            "entrenamiento los que estaban asociados a ti.",
            "Es voluntario: la aplicación funciona igual si no lo activas.",
        ],
        "vigencia_dias": DIAS_VIGENCIA,
    },
}


class Decision(BaseModel):
    acepta: bool


def _vigente(conn, usuario_id: str, finalidad: str):
    """Consentimiento vigente y no vencido. None si no hay."""
    fila = conn.execute(
        """SELECT fecha_inicio, fecha_expiracion, version_texto
           FROM consentimiento_tratamiento
           WHERE usuario_id = %s AND finalidad = %s AND estado = 'vigente'""",
        (usuario_id, finalidad),
    ).fetchone()
    if fila is None:
        return None

    # Vencido: se marca y se trata como si no existiera. No se renueva solo;
    # la persona tiene que volver a decidir.
    if fila[1] <= datetime.now(timezone.utc):
        conn.execute(
            """UPDATE consentimiento_tratamiento SET estado = 'expirado'
               WHERE usuario_id = %s AND finalidad = %s AND estado = 'vigente'""",
            (usuario_id, finalidad),
        )
        conn.commit()
        return None

    return fila


@router.get("/finalidades", summary="Para qué se piden los datos y qué autorizó la persona")
def listar_finalidades(usuario_id: str = Depends(usuario_actual)):
    salida = []
    with db.conectar() as conn:
        for clave, info in FINALIDADES.items():
            fila = _vigente(conn, usuario_id, clave)
            salida.append({
                "id": clave,
                **info,
                "consentido": fila is not None,
                "desde": fila[0].isoformat() if fila else None,
                "vence": fila[1].isoformat() if fila else None,
                # El texto cambió desde que lo aceptó: hay que volver a pedirlo.
                "textoDesactualizado": bool(fila and fila[2] != VERSION_TEXTO),
                "versionTexto": VERSION_TEXTO,
            })
    return {"finalidades": salida}


@router.post("/finalidades/{finalidad}", summary="Otorgar o revocar una finalidad")
def decidir(finalidad: str, decision: Decision, peticion: Request,
            usuario_id: str = Depends(usuario_actual)):
    if finalidad not in FINALIDADES:
        raise HTTPException(status_code=404, detail="Finalidad desconocida.")

    with db.conectar() as conn:
        # Sea cual sea la decisión, lo vigente se cierra primero. Así nunca hay
        # dos consentimientos activos para la misma finalidad.
        conn.execute(
            """UPDATE consentimiento_tratamiento
               SET estado = 'revocado', revocado_at = now()
               WHERE usuario_id = %s AND finalidad = %s AND estado = 'vigente'""",
            (usuario_id, finalidad),
        )

        if decision.acepta:
            conn.execute(
                """INSERT INTO consentimiento_tratamiento
                       (usuario_id, finalidad, version_texto, fecha_expiracion)
                   VALUES (%s, %s, %s, %s)""",
                (
                    usuario_id,
                    finalidad,
                    VERSION_TEXTO,
                    datetime.now(timezone.utc) + timedelta(days=DIAS_VIGENCIA),
                ),
            )
        bitacora.registrar(
            conn, usuario_id,
            "consentimiento.otorgar" if decision.acepta else "consentimiento.revocar",
            FINALIDADES[finalidad]["titulo"], bitacora.ip_de(peticion),
        )
        conn.commit()

    return {"finalidad": finalidad, "consentido": decision.acepta}


# Los códigos de permiso del estándar, dichos como los entiende una persona.
# "ReadTransactionsDetail" no le dice nada a nadie fuera de la industria, y un
# consentimiento que no se entiende no es un consentimiento informado.
_PERMISOS = {
    "ReadAccountsBasic": "Ver qué cuentas tienes",
    "ReadLoansBasic": "Ver tus créditos",
    "ReadLoansDetail": "Ver el detalle de tus créditos",
    "ReadAccountsDetail": "Ver el detalle de tus cuentas",
    "ReadBalances": "Ver tus saldos",
    "ReadTransactionsBasic": "Ver tus movimientos",
    "ReadTransactionsDetail": "Ver tus movimientos con su detalle",
}


# ══════════════════ Derechos del titular (Ley 21.719) ══════════════════
#
# Las cuatro operaciones siguientes son derechos que la ley reconoce al titular
# de los datos, no funcionalidades opcionales del producto: saber qué autorizó,
# obtener una copia de sus datos, conocer qué se hizo con ellos y pedir que se
# eliminen.


@router.get("/consentimientos", summary="Qué autorizó la persona y hasta cuándo")
def consentimientos(usuario_id: str = Depends(usuario_actual)):
    """
    Todo lo que la persona autorizó, en un solo lugar.

    Son dos cosas distintas que la ley trata por separado y que acá se muestran
    juntas porque desde fuera se viven como una sola pregunta: qué permisos di.

      · Acceso bancario: que una institución nos entregue sus movimientos.
      · Finalidad de tratamiento: que usemos esos datos para algo más.
    """
    with db.conectar(diccionarios=True) as conn:
        bancarios = conn.execute(
            """
            SELECT c.id, c.estado, c.fecha_inicio, c.fecha_expiracion, c.alcance_rar,
                   inst.nombre AS institucion, cx.id AS conexion_id
            FROM consentimiento c
            JOIN conexion cx      ON cx.id = c.conexion_id
            JOIN institucion inst ON inst.id = cx.institucion_id
            WHERE cx.usuario_id = %s
            ORDER BY c.fecha_inicio DESC
            """,
            (usuario_id,),
        ).fetchall()

        tratamiento = conn.execute(
            """SELECT finalidad, estado, version_texto, fecha_inicio,
                      fecha_expiracion, revocado_at
               FROM consentimiento_tratamiento
               WHERE usuario_id = %s
               ORDER BY fecha_inicio DESC""",
            (usuario_id,),
        ).fetchall()

    def iso(v):
        return v.isoformat() if v else None

    return {
        "bancarios": [{
            "id": str(r["id"]),
            "institucion": r["institucion"],
            "estado": r["estado"],
            "desde": iso(r["fecha_inicio"]),
            "vence": iso(r["fecha_expiracion"]),
            # Del alcance RAR se muestra a qué da acceso, nunca el refresh token.
            "permisos": [_PERMISOS.get(p, p) for p in (r["alcance_rar"] or {}).get("permisos", [])],
        } for r in bancarios],
        "tratamiento": [{
            "finalidad": r["finalidad"],
            "titulo": FINALIDADES.get(r["finalidad"], {}).get("titulo", r["finalidad"]),
            "estado": r["estado"],
            "desde": iso(r["fecha_inicio"]),
            "vence": iso(r["fecha_expiracion"]),
            "revocado": iso(r["revocado_at"]),
            "versionTexto": r["version_texto"],
        } for r in tratamiento],
    }


@router.get("/bitacora", summary="Registro de lo que se hizo con tus datos")
def ver_bitacora(usuario_id: str = Depends(usuario_actual), limite: int = 100):
    with db.conectar(diccionarios=True) as conn:
        filas = conn.execute(
            """SELECT accion, recurso, ip_origen, ocurrido_at
               FROM bitacora_auditoria
               WHERE usuario_id = %s
               ORDER BY ocurrido_at DESC
               LIMIT %s""",
            (usuario_id, min(limite, 500)),
        ).fetchall()

    return {"eventos": [{
        "accion": r["accion"],
        "descripcion": bitacora.ACCIONES.get(r["accion"], r["accion"]),
        "recurso": r["recurso"],
        "ip": str(r["ip_origen"]) if r["ip_origen"] else None,
        "cuando": r["ocurrido_at"].isoformat(),
    } for r in filas]}


@router.get("/exportar", summary="Copia completa de los datos del titular")
def exportar(peticion: Request, usuario_id: str = Depends(usuario_actual)):
    """
    Portabilidad: todos los datos de la persona en formato estructurado.

    Se entrega como descarga JSON porque la ley pide un formato que la persona
    pueda llevarse a otro servicio, no una pantalla para mirar. Incluye lo que
    el banco envió tal cual y lo que el sistema dedujo, por separado: si la
    persona se lleva sus datos, tiene derecho a distinguir el dato original de
    nuestra interpretación de él.
    """
    with db.conectar(diccionarios=True) as conn:
        usuario = conn.execute(
            "SELECT nombre, email, sueldo_declarado, created_at FROM usuario WHERE id = %s",
            (usuario_id,),
        ).fetchone()
        if usuario:
            # La copia es para la persona: el sueldo va legible, no cifrado.
            usuario["sueldo_declarado"] = descifrar_numero(usuario["sueldo_declarado"],
                                                           ctx_sueldo(usuario_id))

        cuentas = conn.execute(
            """SELECT c.id_externo, c.tipo, c.numero_enmascarado, c.moneda, c.saldo,
                      inst.nombre AS institucion
               FROM cuenta c
               JOIN conexion cx      ON cx.id = c.conexion_id
               JOIN institucion inst ON inst.id = cx.institucion_id
               WHERE c.usuario_id = %s""",
            (usuario_id,),
        ).fetchall()

        movimientos = conn.execute(
            """SELECT t.fecha, t.monto, t.moneda, t.glosa_original, t.glosa_normalizada,
                      t.categoria_origen, cat.nombre AS categoria,
                      t.confianza_clasificacion, t.es_recurrente, t.created_at
               FROM transaccion t
               JOIN cuenta c ON c.id = t.cuenta_id
               LEFT JOIN categoria cat ON cat.id = t.categoria_id
               WHERE c.usuario_id = %s
               ORDER BY t.fecha""",
            (usuario_id,),
        ).fetchall()

        metas = conn.execute(
            """SELECT nombre, monto_objetivo, monto_ahorrado, fecha_objetivo, creada_en
               FROM meta WHERE usuario_id = %s ORDER BY creada_en""",
            (usuario_id,),
        ).fetchall()

        correcciones = conn.execute(
            "SELECT tipo, valor, created_at FROM correccion WHERE usuario_id = %s ORDER BY created_at",
            (usuario_id,),
        ).fetchall()

        bitacora.registrar(conn, usuario_id, "datos.exportar",
                           f"{len(movimientos)} movimientos", bitacora.ip_de(peticion))
        conn.commit()

    def limpiar(filas):
        salida = []
        for r in filas:
            fila = {}
            for k, v in r.items():
                fila[k] = v.isoformat() if hasattr(v, "isoformat") else (
                    float(v) if hasattr(v, "quantize") else v)
            salida.append(fila)
        return salida

    cuerpo = {
        "exportadoEn": datetime.now(timezone.utc).isoformat(),
        "titular": limpiar([usuario])[0] if usuario else None,
        "cuentas": limpiar(cuentas),
        "movimientos": limpiar(movimientos),
        "metas": limpiar(metas),
        "correcciones": limpiar(correcciones),
        "consentimientos": consentimientos(usuario_id),
        "nota": ("Copia de los datos personales asociados a esta cuenta, entregada en "
                 "ejercicio del derecho de portabilidad de la Ley 21.719. No incluye "
                 "credenciales ni tokens de acceso a instituciones financieras."),
    }
    nombre = f"velvet-wallet-datos-{datetime.now().strftime('%Y-%m-%d')}.json"
    return JSONResponse(
        cuerpo,
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


class Supresion(BaseModel):
    """Se pide el correo escrito a mano: borrar no puede ser un toque suelto."""
    confirmacion: str


@router.delete("/cuenta", summary="Eliminar la cuenta y todos los datos")
def suprimir(datos: Supresion, peticion: Request, usuario_id: str = Depends(usuario_actual)):
    """
    Derecho de supresión.

    Borra de verdad: el resto de las tablas cuelgan de `usuario` con ON DELETE
    CASCADE, así que se van cuentas, movimientos, metas, correcciones y
    consentimientos. Lo único que sobrevive es la bitácora, que pierde el
    `usuario_id` y queda anonimizada: la ley pide poder demostrar qué pasó con
    los datos, y ese registro no puede desaparecer junto con ellos.

    No es reversible y no hay papelera. Por eso se exige escribir el correo.
    """
    with db.conectar(diccionarios=True) as conn:
        fila = conn.execute("SELECT email FROM usuario WHERE id = %s", (usuario_id,)).fetchone()
        if fila is None:
            raise HTTPException(status_code=404, detail="La cuenta ya no existe.")

        if datos.confirmacion.strip().lower() != fila["email"].strip().lower():
            raise HTTPException(
                status_code=400,
                detail="Escribe tu correo exactamente como lo registraste para confirmar.",
            )

        # Se anota ANTES de borrar: después el usuario_id ya no existiría.
        bitacora.registrar(conn, usuario_id, "cuenta.suprimir", fila["email"],
                           bitacora.ip_de(peticion))
        conexiones = [str(r["id"]) for r in conn.execute(
            "SELECT id FROM conexion WHERE usuario_id = %s", (usuario_id,)).fetchall()]
        conn.execute("DELETE FROM usuario WHERE id = %s", (usuario_id,))
        conn.commit()

    # Los crudos de Mongo (lo que mandó cada banco, las cartolas, lo anotado a
    # mano) no cuelgan de la FK de Postgres: se borran aparte. Después del
    # commit, para no borrarlos si la supresión no llegó a confirmarse.
    if conexiones:
        conexiones_bd.mongo()[config_ingesta.MONGO_DB].payload_crudo.delete_many(
            {"conexion_id": {"$in": conexiones}})

    return {"eliminada": True}


def usuarios_que_consienten(conn, finalidad: str) -> list[str]:
    """
    Quiénes autorizaron esa finalidad, con consentimiento vigente y sin vencer.

    **El reentrenamiento del clasificador debe filtrar por esto.** Entrenar con
    los datos de alguien que no consintió, o cuyo consentimiento venció, es
    justamente lo que la ley prohíbe, y el consentimiento no sirve de nada si
    el código que usa los datos no lo consulta.
    """
    filas = conn.execute(
        """SELECT usuario_id FROM consentimiento_tratamiento
           WHERE finalidad = %s AND estado = 'vigente' AND fecha_expiracion > now()""",
        (finalidad,),
    ).fetchall()
    return [str(f[0]) for f in filas]
