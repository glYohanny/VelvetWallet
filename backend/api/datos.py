# -*- coding: utf-8 -*-
"""
Endpoints de datos del usuario: movimientos, cuentas y un resumen.

Todos exigen sesión (dependen de `usuario_actual`) y TODAS las consultas filtran
por el usuario del token. Ese filtro (WHERE usuario_id = <token>) es lo que
garantiza que cada usuario vea únicamente su propia información.

  GET /api/movimientos                  -> lista de movimientos del usuario
  PUT /api/movimientos/{id}/categoria   -> el usuario corrige la categoría
  GET /api/cuentas                      -> cuentas del usuario
  GET /api/resumen                      -> totales (ingresos, gastos, saldo)
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from psycopg.rows import dict_row
from psycopg.types.json import Json
from pydantic import BaseModel, Field

from . import bitacora, config, db
from .sesion_actual import usuario_actual

import psycopg

router = APIRouter(prefix="/api", tags=["Datos del usuario"])


def _conectar_dict():
    """Conexión que devuelve filas como diccionarios (más cómodo para armar JSON)."""
    return db.conectar(diccionarios=True)


# Equivalencia entre la taxonomía del banco y la nuestra. Es la **primera capa
# de la cascada** del clasificador (E2): lo que la institución ya clasificó se
# resuelve sin modelo. Cada proveedor usa su propia taxonomía y no hay
# equivalencia común, así que esta tabla es parte del trabajo de normalizar.
#
# El clasificador (backend/clasificador) llena `categoria_id` al ingerir; esta
# tabla solo cubre lo que el clasificador dejó sin categoría pero el banco sí
# mandó categorizado.
_CATEGORIA_PROPIA = {
    "Alimentos": "Supermercado",
    "Restaurantes": "Delivery",
    "Entretenimiento": "Entretención",
    "Servicios": "Servicios",
    "Vivienda": "Vivienda",
    "Transporte": "Transporte",
    "Vestuario": "Vestuario",
    "Salud": "Salud",
    "Educacion": "Educación",
    "Educación": "Educación",
}


def _movimiento(r: dict) -> dict:
    """Pasa una fila de la consulta a la forma que espera la app (camelCase)."""
    categoria_banco = r.get("categoria_origen")

    # Primero lo que diga el clasificador; si todavía no clasificó, lo que
    # mandó el banco traducido a nuestra taxonomía. Si no hay ninguna de las
    # dos, queda sin categoría: el sistema se abstiene en vez de inventar
    # (RF-17 / RNF-33) y el movimiento aparece en la bandeja Por revisar.
    categoria = r["categoria"] or _CATEGORIA_PROPIA.get(categoria_banco or "")
    tiene_categoria = categoria is not None

    # Quién decidió la categoría. Es trazabilidad de la decisión: permite
    # responder "¿por qué esto quedó en Supermercado?".
    #
    # La confianza solo tiene sentido para el modelo: una regla o una
    # corrección del usuario no son parciales, aciertan o no.
    confianza = float(r["confianza"]) if r.get("confianza") is not None else None
    corregida = bool(r.get("corregida"))
    if corregida and r["categoria"] is not None:
        origen_clasificacion = "usuario"
        confianza = None
    elif r["categoria"] is not None:
        origen_clasificacion = "modelo" if confianza is not None else "regla"
    elif tiene_categoria:
        origen_clasificacion = "banco"
    else:
        origen_clasificacion = None

    return {
        "id": str(r["id"]),
        "cuentaId": r["cuenta_externa"],
        "institucion": r["institucion"],
        "fecha": (r["fecha"].isoformat() + "T12:00:00-03:00") if r["fecha"] else None,
        "monto": float(r["monto"]),
        "moneda": r["moneda"],
        "comercio": r["glosa_normalizada"] or r["glosa_original"],
        "glosaOriginal": r["glosa_original"],
        "categoria": categoria,
        "categoriaBanco": categoria_banco,
        "estadoCategoria": ("corregida" if corregida and r["categoria"] is not None
                            else "automatica" if tiene_categoria else "sin_categoria"),
        "origenClasificacion": origen_clasificacion,
        "confianza": confianza,
        "esRecurrente": r["es_recurrente"],
        "excluido": r["estado"] == "excluido",
        # Por dónde entró primero, y todas las fuentes que lo trajeron: un
        # movimiento que llegó por la API y por una cartola es UNO (RF-09).
        "origen": r["fuente"],
        "fuentes": [r["fuente"]] + [f for f in (r.get("otras_fuentes") or [])
                                    if f != r["fuente"]],
        "recibidoEn": r["created_at"].isoformat() if r["created_at"] else None,
        "payloadCrudoRef": r["payload_crudo_ref"],
        "correcciones": r.get("correcciones") or [],
    }


# Lo que se lee de cada movimiento. `corr` trae las correcciones del usuario:
# si recategorizó, la categoría es la de él (origen "usuario").
_SELECT_MOVIMIENTOS = """
    SELECT t.id, t.monto, t.moneda, t.fecha, t.glosa_original,
           t.glosa_normalizada, t.estado, t.es_recurrente,
           t.payload_crudo_ref, t.created_at, t.categoria_origen, t.fuente,
           ARRAY(SELECT DISTINCT o.fuente FROM transaccion_origen o
                 WHERE o.transaccion_id = t.id) AS otras_fuentes,
           t.confianza_clasificacion AS confianza,
           c.id_externo        AS cuenta_externa,
           cat.nombre          AS categoria,
           inst.nombre         AS institucion,
           inst.participante_sfa,
           corr.corregida, corr.correcciones
    FROM transaccion t
    JOIN cuenta c         ON c.id  = t.cuenta_id
    JOIN conexion cx      ON cx.id = c.conexion_id
    JOIN institucion inst ON inst.id = cx.institucion_id
    LEFT JOIN categoria cat ON cat.id = t.categoria_id
    LEFT JOIN LATERAL (
        SELECT bool_or(co.tipo = 'recategorizar') AS corregida,
               json_agg(json_build_object(
                   'tipo', co.tipo,
                   'fecha', to_char(co.created_at AT TIME ZONE 'UTC',
                                    'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
                   'detalle', co.valor->>'categoria')
                   ORDER BY co.created_at)
               -- Elegir la categoría al anotar un gasto a mano no es corregir
               -- nada: cuenta como decisión de la persona, pero no se lista.
               FILTER (WHERE NOT COALESCE((co.valor->>'al_registrar')::boolean, false))
               AS correcciones
        FROM correccion co WHERE co.transaccion_id = t.id
    ) corr ON true
"""


@router.get("/movimientos", summary="Movimientos del usuario autenticado")
def listar_movimientos(
    peticion: Request,
    usuario_id: str = Depends(usuario_actual),
    limite: int = Query(100, ge=1, le=500),
    desplazamiento: int = Query(0, ge=0),
):
    with _conectar_dict() as conn:
        filas = conn.execute(
            _SELECT_MOVIMIENTOS + """
            WHERE c.usuario_id = %s
            ORDER BY t.fecha DESC, t.created_at DESC
            LIMIT %s OFFSET %s
            """,
            (usuario_id, limite, desplazamiento),
        ).fetchall()

        # Leer los movimientos es un tratamiento de datos personales y queda
        # registrado (Ley 21.719). Solo la primera página —paginar hacia abajo
        # es la misma consulta— y agrupado por media hora, porque la app
        # recarga esta lista cada vez que se abre y una entrada por recarga
        # haría la bitácora ilegible para la persona.
        if desplazamiento == 0:
            bitacora.registrar(conn, usuario_id, "datos.leer",
                               f"{len(filas)} movimientos", bitacora.ip_de(peticion),
                               agrupar_minutos=30)
            conn.commit()

    return {"movimientos": [_movimiento(r) for r in filas], "total": len(filas)}


class NuevaCategoria(BaseModel):
    categoria: str = Field(min_length=1, max_length=80)


@router.put("/movimientos/{movimiento_id}/categoria",
            summary="Corregir (o asignar) la categoría de un movimiento")
def corregir_categoria(movimiento_id: str, datos: NuevaCategoria, peticion: Request,
                       usuario_id: str = Depends(usuario_actual)):
    """
    El usuario decide la categoría, por ejemplo en "Por revisar". El dato del
    banco no se toca: la decisión queda en `correccion` (quién, cuándo, de qué
    a qué) y la categoría del movimiento pasa a ser la de él. Ni una
    re-sincronización ni un modelo nuevo la vuelven a cambiar.

    Esas correcciones son los ejemplos con que se reentrena el clasificador,
    solo de quienes consintieron esa finalidad (ver /api/privacidad).
    """
    nombre = datos.categoria.strip()
    if not nombre:
        raise HTTPException(status_code=422, detail="La categoría no puede quedar vacía.")
    with _conectar_dict() as conn:
        actual = conn.execute(
            """
            SELECT t.id, cat.nombre AS categoria, t.confianza_clasificacion
            FROM transaccion t
            JOIN cuenta c ON c.id = t.cuenta_id
            LEFT JOIN categoria cat ON cat.id = t.categoria_id
            WHERE t.id::text = %s AND c.usuario_id = %s
            """,
            (movimiento_id, usuario_id),
        ).fetchone()
        if actual is None:
            # Ajeno o inexistente: misma respuesta, no se filtra nada.
            raise HTTPException(status_code=404, detail="Movimiento no encontrado.")

        fila = conn.execute(
            "SELECT id FROM categoria WHERE nombre = %s AND tipo = 'gasto' ORDER BY id LIMIT 1",
            (nombre,)).fetchone()
        if fila is None:
            fila = conn.execute(
                "INSERT INTO categoria (nombre, tipo) VALUES (%s, 'gasto') RETURNING id",
                (nombre,)).fetchone()
        conn.execute(
            "INSERT INTO correccion (transaccion_id, usuario_id, tipo, valor) "
            "VALUES (%s, %s, 'recategorizar', %s)",
            (actual["id"], usuario_id, Json({
                "categoria": nombre,
                "anterior": actual["categoria"],
                "confianza_anterior": float(actual["confianza_clasificacion"])
                if actual["confianza_clasificacion"] is not None else None,
            })))
        conn.execute(
            "UPDATE transaccion SET categoria_id = %s, confianza_clasificacion = NULL "
            "WHERE id = %s", (fila["id"], actual["id"]))
        bitacora.registrar(conn, usuario_id, "categoria.corregir",
                           f"{actual['categoria'] or 'sin categoría'} → {nombre}",
                           bitacora.ip_de(peticion))
        r = conn.execute(_SELECT_MOVIMIENTOS + " WHERE t.id = %s", (actual["id"],)).fetchone()
    return _movimiento(r)


@router.get("/cuentas", summary="Cuentas del usuario autenticado")
def listar_cuentas(usuario_id: str = Depends(usuario_actual)):
    with _conectar_dict() as conn:
        filas = conn.execute(
            """
            SELECT c.id, c.id_externo, c.tipo, c.numero_enmascarado,
                   c.moneda, c.saldo, c.actualizado_at,
                   inst.nombre AS institucion
            FROM cuenta c
            JOIN conexion cx      ON cx.id = c.conexion_id
            JOIN institucion inst ON inst.id = cx.institucion_id
            WHERE c.usuario_id = %s
            ORDER BY inst.nombre, c.id_externo
            """,
            (usuario_id,),
        ).fetchall()

    cuentas = [
        {
            "id": str(r["id"]),
            "idExterno": r["id_externo"],
            "institucion": r["institucion"],
            "tipo": r["tipo"],
            "numeroEnmascarado": r["numero_enmascarado"],
            "moneda": r["moneda"],
            "saldo": float(r["saldo"]) if r["saldo"] is not None else None,
            "actualizadoEn": r["actualizado_at"].isoformat() if r["actualizado_at"] else None,
        }
        for r in filas
    ]
    return {"cuentas": cuentas, "total": len(cuentas)}


@router.get("/resumen", summary="Totales del usuario autenticado")
def resumen(usuario_id: str = Depends(usuario_actual)):
    with _conectar_dict() as conn:
        tot = conn.execute(
            """
            SELECT
              COALESCE(SUM(CASE WHEN t.monto > 0 THEN t.monto ELSE 0 END), 0) AS ingresos,
              COALESCE(SUM(CASE WHEN t.monto < 0 THEN -t.monto ELSE 0 END), 0) AS gastos,
              COUNT(*) AS movimientos
            FROM transaccion t
            JOIN cuenta c ON c.id = t.cuenta_id
            WHERE c.usuario_id = %s AND t.estado <> 'excluido'
            """,
            (usuario_id,),
        ).fetchone()

        saldo = conn.execute(
            "SELECT COALESCE(SUM(saldo), 0) AS saldo_total FROM cuenta WHERE usuario_id = %s",
            (usuario_id,),
        ).fetchone()

    return {
        "ingresos": float(tot["ingresos"]),
        "gastos": float(tot["gastos"]),
        "balance": float(tot["ingresos"]) - float(tot["gastos"]),
        "saldoTotal": float(saldo["saldo_total"]),
        "movimientos": tot["movimientos"],
    }
