# -*- coding: utf-8 -*-
"""
Conexión del usuario con los bancos (entidades financieras del SFA).

La clave del banco NUNCA entra a Velvet. Para vincular, la app manda al usuario
al SITIO DE SU BANCO; allá inicia sesión y aprueba, y el banco lo devuelve aquí
con un código de un solo uso que se canjea por el permiso (OAuth 2.0 con PAR y
PKCE, como pide el estándar del SFA / FAPI).

  POST   /api/conexiones/iniciar  -> URL de la página del banco para autorizar
  GET    /api/conexiones/retorno  -> el banco vuelve aquí con el código (callback)
  POST   /api/conexiones          -> sincroniza el banco ya autorizado
  GET    /api/conexiones          -> bancos conectados del usuario
  DELETE /api/conexiones/{id}     -> desvincula: revoca el permiso y borra sus datos

Flujo:
  app ──POST /iniciar──▶ backend ──PAR (credenciales + PKCE)──▶ banco
  app ◀── urlAutorizacion ── backend
  app ──abre──▶ sitio del banco: login + "Autorizar"
  banco ──303 ?code&state──▶ /retorno ──canje code + verifier──▶ banco (tokens)
  /retorno ──303 ?banco=vinculado──▶ app ──POST /conexiones──▶ trae los datos
"""
import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from psycopg.rows import dict_row
import psycopg

from . import bitacora, config, db
from .sesion_actual import usuario_actual

# La ingesta vive en backend/ingesta; se corre desde backend/, así que es importable.
from ingesta.cifrado import descifrar_alcance
from ingesta.importacion import ID_EFECTIVO
from ingesta.cliente_sfa import AutorizacionFallida, ClienteSFA, ReautorizacionRequerida
from ingesta.normalizador import etiqueta_tipo_cuenta
from ingesta.repositorio import Repositorio
from ingesta.sincronizar import (PERMISOS, ConexionDeOtroCliente, bancos_conectados,
                                 sincronizar_todos, sincronizar_usuario,
                                 vincular_conexion)
from ingesta import config as config_ingesta

router = APIRouter(prefix="/api", tags=["Conexiones (bancos)"])

# Vinculaciones en curso, por `state`. Viven en memoria y duran lo que la
# solicitud en el banco (10 min). Si el backend se reinicia a mitad, el usuario
# vuelve a tocar "Ir al banco". En producción esto iría en Redis o en la base.
VIGENCIA_INICIO = timedelta(minutes=10)
PENDIENTES: dict[str, dict] = {}


def _explicar_falla(e: Exception, banco: str | None = None) -> str:
    """Dice QUÉ servicio falló, para no culpar al banco de un problema de la base."""
    import httpx
    import pymongo.errors

    nombre = type(e).__name__
    if isinstance(e, pymongo.errors.PyMongoError):
        return ("No se pudo conectar con MongoDB (Atlas). Revisa que tu IP esté permitida en "
                "Network Access y que el cluster no esté pausado. (%s)" % nombre)
    if isinstance(e, psycopg.Error):
        return "No se pudo conectar con PostgreSQL (Neon). Revisa DATABASE_URL. (%s)" % nombre
    if isinstance(e, httpx.ConnectError):
        return "No se pudo conectar con %s. ¿Está corriendo su simulador? (%s)" % (
            banco or "el banco", nombre)
    if isinstance(e, httpx.HTTPStatusError):
        return "El banco respondió con error %d. (%s)" % (e.response.status_code, nombre)
    return "No se pudo sincronizar con el banco. (%s)" % nombre


def _retorno_permitido(url: str | None) -> str:
    """Solo se vuelve a destinos de la lista blanca (evita redirección abierta)."""
    if url and any(url.startswith(p) for p in config.RETORNOS_PERMITIDOS):
        return url
    return config.RETORNO_POR_DEFECTO


def _volver_a_la_app(retorno: str, **resultado) -> RedirectResponse:
    """Devuelve al usuario a la app con el resultado. Sin datos personales en la URL."""
    union = "&" if "?" in retorno else "?"
    return RedirectResponse(retorno + union + urlencode(resultado), status_code=303)


def _limpiar_vencidas() -> None:
    ahora = datetime.now(timezone.utc)
    for st in [s for s, p in PENDIENTES.items() if p["expira"] < ahora]:
        PENDIENTES.pop(st, None)


class SolicitudInicio(BaseModel):
    """
    · institucion: qué banco (hoy solo la EFS).
    · retorno: a dónde debe volver el usuario al terminar (URL de la app). Tiene
      que estar en VELVET_RETORNOS_PERMITIDOS; si no, se usa el de por defecto.
    """
    institucion: str | None = None
    retorno: str | None = None


@router.post("/conexiones/iniciar", summary="Empezar la vinculación en el sitio del banco")
def iniciar_vinculacion(datos: SolicitudInicio | None = None,
                        usuario_id: str = Depends(usuario_actual)):
    """
    Deja la solicitud de autorización en el banco (PAR) y devuelve la URL de la
    página del banco a la que la app debe mandar al usuario.
    """
    datos = datos or SolicitudInicio()
    _limpiar_vencidas()
    b = config_ingesta.banco_sfa(datos.institucion)
    if b is None:
        raise HTTPException(status_code=422,
                            detail="%s no es un banco del Sistema de Finanzas Abiertas." % datos.institucion)

    # PKCE: el verifier se queda aquí; al banco solo va su huella (challenge).
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    # state: ata la vuelta del banco con ESTA solicitud de ESTE usuario.
    state = secrets.token_urlsafe(24)

    try:
        with ClienteSFA(b.base_url) as banco:
            request_uri = banco.solicitar_autorizacion(
                b.client_id, b.client_secret, PERMISOS,
                config_ingesta.SFA_REDIRECT_URI, state, challenge)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=_explicar_falla(e, b.nombre))

    PENDIENTES[state] = {
        "usuario_id": usuario_id,
        "code_verifier": verifier,
        "institucion": b.nombre,
        "retorno": _retorno_permitido(datos.retorno),
        "expira": datetime.now(timezone.utc) + VIGENCIA_INICIO,
    }
    url = b.autorizar_url + "?" + urlencode({"client_id": b.client_id, "request_uri": request_uri})
    return {"urlAutorizacion": url, "expiraEn": int(VIGENCIA_INICIO.total_seconds())}


@router.get("/conexiones/retorno", summary="El banco vuelve aquí (callback OAuth)",
            include_in_schema=False)
def retorno_del_banco(state: str | None = None, code: str | None = None,
                      error: str | None = None):
    """
    No lleva JWT: lo abre el navegador del usuario, que viene del banco. Lo que
    lo identifica es el `state`, que es secreto, de un solo uso y vence.
    """
    pendiente = PENDIENTES.pop(state or "", None)
    if pendiente is None or pendiente["expira"] < datetime.now(timezone.utc):
        return _volver_a_la_app(config.RETORNO_POR_DEFECTO, banco="error", motivo="expirado")
    retorno = pendiente["retorno"]

    if error or not code:
        # access_denied = el usuario tocó "Rechazar" en su banco.
        return _volver_a_la_app(retorno, banco="rechazado" if error == "access_denied" else "error",
                                **({} if error == "access_denied" else {"motivo": "fallo"}))

    try:
        # El código se canjea en el MISMO banco que lo emitió.
        b = config_ingesta.banco_sfa(pendiente["institucion"])
        with ClienteSFA(b.base_url) as banco:
            otorgado = banco.canjear_codigo(
                b.client_id, b.client_secret, code,
                config_ingesta.SFA_REDIRECT_URI, pendiente["code_verifier"])
        vincular_conexion(pendiente["usuario_id"], otorgado, pendiente["institucion"])
        with db.conectar() as conn:
            bitacora.registrar(conn, pendiente["usuario_id"], "banco.vincular",
                               pendiente["institucion"])
            conn.commit()
    except AutorizacionFallida:
        return _volver_a_la_app(retorno, banco="error", motivo="expirado")
    except ConexionDeOtroCliente:
        return _volver_a_la_app(retorno, banco="error", motivo="otro_cliente")
    except Exception:  # noqa: BLE001
        return _volver_a_la_app(retorno, banco="error", motivo="fallo")
    return _volver_a_la_app(retorno, banco="vinculado")


class SolicitudConexion(BaseModel):
    institucion: str | None = None


@router.post("/conexiones", summary="Sincronizar los bancos ya autorizados")
def conectar_banco(
    datos: SolicitudConexion | None = None,
    usuario_id: str = Depends(usuario_actual),
):
    """
    Trae (o vuelve a traer) las cuentas y movimientos con el permiso guardado.

    · Con `institucion`: solo ese banco. Si todavía no hay permiso responde
      409 `reautorizar` y la app manda a la persona a ese banco (/iniciar).
    · Sin `institucion`: TODOS los bancos vinculados, cada uno por separado
      (RF-07). Si uno no responde o su permiso venció, los demás se
      sincronizan igual y la respuesta lo dice banco por banco en `bancos`.
      Solo es un error si no hay ningún banco vinculado o si fallaron todos.
    """
    datos = datos or SolicitudConexion()
    if datos.institucion:
        if config_ingesta.banco_sfa(datos.institucion) is None:
            raise HTTPException(status_code=422, detail="%s no es un banco del SFA." % datos.institucion)
        try:
            resumen = sincronizar_usuario(usuario_id, datos.institucion)
        except ReautorizacionRequerida as e:
            raise HTTPException(status_code=409, detail={"codigo": "reautorizar", "mensaje": str(e)})
        except ConexionDeOtroCliente as e:
            raise HTTPException(status_code=409, detail={"codigo": "otro_cliente", "mensaje": str(e)})
        except Exception as e:  # noqa: BLE001 — se traduce a un error claro para la app
            raise HTTPException(status_code=502, detail=_explicar_falla(e, datos.institucion))
        resultados = [{"institucion": config_ingesta.banco_sfa(datos.institucion).nombre,
                       "ok": True, "resumen": resumen}]
    else:
        resultados = sincronizar_todos(usuario_id)
        if not resultados:
            raise HTTPException(status_code=409, detail={
                "codigo": "reautorizar",
                "mensaje": "Todavía no tienes un banco vinculado: autoriza el acceso en el "
                           "sitio de tu banco."})
        if not any(r["ok"] for r in resultados):
            # Todos fallaron: si alguno solo necesita reautorizar, eso es lo
            # que la persona puede resolver, así que se dice primero.
            primero = next((r for r in resultados if r["codigo"] == "reautorizar"), resultados[0])
            raise HTTPException(
                status_code=409 if primero["codigo"] != "sin_respuesta" else 502,
                detail={"codigo": primero["codigo"], "mensaje": primero["mensaje"],
                        "bancos": [_sin_resumen(r) for r in resultados]})

    buenos = [r["resumen"] for r in resultados if r["ok"]]
    return {
        # Los campos de siempre, sumados sobre los bancos que respondieron.
        "institucion": ", ".join(r["institucion"] for r in resultados if r["ok"]),
        "cliente": buenos[0]["cliente"],
        "cuentas": sum(b["cuentas"] for b in buenos),
        "movimientosNuevos": sum(b["insertadas"] for b in buenos),
        "movimientosActualizados": sum(b["actualizadas"] for b in buenos),
        "movimientosSinCambio": sum(b["sin_cambio"] for b in buenos),
        "creditos": sum(b.get("creditos", 0) for b in buenos),
        "suscripciones": max((b.get("suscripciones", 0) for b in buenos), default=0),
        # Y el detalle, banco por banco.
        "bancos": [_sin_resumen(r) for r in resultados],
    }


def _sin_resumen(r: dict) -> dict:
    """El resultado de un banco, como lo ve la app."""
    if r["ok"]:
        b = r["resumen"]
        return {"institucion": r["institucion"], "ok": True,
                "movimientosNuevos": b["insertadas"], "movimientosActualizados": b["actualizadas"]}
    return {"institucion": r["institucion"], "ok": False, "codigo": r["codigo"],
            "mensaje": r["mensaje"]}


@router.get("/instituciones", summary="Bancos del SFA a los que se puede conectar")
def listar_instituciones(usuario_id: str = Depends(usuario_actual)):
    """
    Los bancos participantes con los que Velvet está registrado, y si la
    persona ya tiene cada uno vinculado. Es lo que la app ofrece al conectar.
    """
    conectados = {n.lower() for n in bancos_conectados(usuario_id)}
    return {"instituciones": [
        {"nombre": b.nombre, "conectada": b.nombre.lower() in conectados}
        for b in config_ingesta.BANCOS_SFA
    ]}


# Desde cuándo el dato deja de ser confiable y la app tiene que advertirlo
# (RF-35). El estándar no lo fija: la NCG 514 no obliga al consumidor a una
# frecuencia de sincronización, así que es una decisión de producto nuestra.
HORAS_DE_FRESCURA = 24


def _estado_visible(estado_bd: str, autorizada: bool, expira, ahora) -> str:
    """
    Traduce el estado guardado al vocabulario que entiende la app (EstadoConexion).

    La base guarda el estado del VÍNCULO ('activa', 'expirada', 'revocada',
    'error') y la app muestra el estado del DATO. No son lo mismo, y el orden
    importa: un vínculo marcado activo cuyo consentimiento ya expiró necesita
    reautorización, mientras que uno que falló técnicamente sigue mostrando los
    datos de la última vez. La falta de permiso siempre gana, porque es lo único
    que el usuario puede resolver.
    """
    if estado_bd in ("expirada", "revocada") or not autorizada:
        return "autorizacion_vencida"
    if expira is not None and expira <= ahora:
        return "autorizacion_vencida"
    if estado_bd == "error":
        return "sin_respuesta"
    return "al_dia"


@router.get("/conexiones", summary="Bancos conectados del usuario")
def listar_conexiones(usuario_id: str = Depends(usuario_actual)):
    with db.conectar(diccionarios=True) as conn:
        filas = conn.execute(
            """
            SELECT cx.id, cx.estado, cx.ultima_sincronizacion,
                   inst.nombre AS institucion, inst.participante_sfa,
                   (SELECT max(t.fecha) FROM transaccion t JOIN cuenta c3 ON c3.id = t.cuenta_id
                    WHERE c3.conexion_id = cx.id) AS datos_hasta,
                   cs.alcance_rar      AS alcance,
                   cs.fecha_expiracion AS expira
            FROM conexion cx
            JOIN institucion inst ON inst.id = cx.institucion_id
            -- El consentimiento vigente más reciente. LATERAL y no dos
            -- subconsultas: así el alcance y su vencimiento salen de la MISMA
            -- fila y no pueden describir consentimientos distintos.
            LEFT JOIN LATERAL (
                SELECT c2.alcance_rar, c2.fecha_expiracion
                FROM consentimiento c2
                WHERE c2.conexion_id = cx.id AND c2.estado = 'vigente'
                ORDER BY c2.fecha_inicio DESC
                LIMIT 1
            ) cs ON TRUE
            WHERE cx.usuario_id = %s
            ORDER BY inst.nombre
            """,
            (usuario_id,),
        ).fetchall()

        cuentas = conn.execute(
            """
            SELECT conexion_id, id, id_externo, tipo, numero_enmascarado, moneda, saldo
            FROM cuenta
            WHERE usuario_id = %s
            ORDER BY tipo, id_externo
            """,
            (usuario_id,),
        ).fetchall()

    por_conexion: dict[str, list[dict]] = {}
    for c in cuentas:
        por_conexion.setdefault(str(c["conexion_id"]), []).append({
            "id": str(c["id"]),
            # El id del banco: es el que traen los movimientos (RF-05).
            "idExterno": c["id_externo"],
            "tipo": ("Efectivo" if c["id_externo"] == ID_EFECTIVO
                     else etiqueta_tipo_cuenta(c["tipo"])),
            "numeroEnmascarado": c["numero_enmascarado"],
            "moneda": c["moneda"],
            "saldo": float(c["saldo"]) if c["saldo"] is not None else None,
        })

    ahora = datetime.now(timezone.utc)
    conexiones = []
    for r in filas:
        ultima = r["ultima_sincronizacion"]
        cuentas_cx = por_conexion.get(str(r["id"]), [])
        if not r["participante_sfa"]:
            # Cartola o efectivo: no hay permiso que renovar ni banco al que
            # preguntar. El dato llega hasta donde llegó lo importado, y eso
            # es lo que se informa (RF-35).
            conexiones.append({
                "id": str(r["id"]),
                "institucion": r["institucion"],
                "fuente": ("manual" if any(c["idExterno"] == ID_EFECTIVO for c in cuentas_cx)
                           else "cartola"),
                "estado": "al_dia",
                "cuentas": cuentas_cx,
                "ultimaSincronizacion": ultima.isoformat() if ultima else None,
                "datosHasta": r["datos_hasta"].isoformat() if r["datos_hasta"] else None,
                "datoAntiguo": False,
                "rutCliente": None,
                "nombreCliente": None,
                "autorizada": False,
            })
            continue
        alcance = descifrar_alcance(r["alcance"], r["id"]) or {}
        autorizada = bool(alcance.get("refreshToken"))
        estado = _estado_visible(r["estado"], autorizada, r["expira"], ahora)
        conexiones.append({
            "fuente": "sfa",
            "datosHasta": r["datos_hasta"].isoformat() if r["datos_hasta"] else None,
            "id": str(r["id"]),
            "institucion": r["institucion"],
            "estado": estado,
            "cuentas": cuentas_cx,
            "ultimaSincronizacion": ultima.isoformat() if ultima else None,
            "autorizacionVencioEl": r["expira"].isoformat()
            if estado == "autorizacion_vencida" and r["expira"] else None,
            # Nunca se sincronizó, o lo que hay es más viejo que la ventana: la
            # app lo advierte en vez de mostrar un total que parece completo.
            "datoAntiguo": ultima is None
            or (ahora - ultima) > timedelta(hours=HORAS_DE_FRESCURA),
            # A qué cliente del banco está atada (nunca el refresh token).
            "rutCliente": alcance.get("rutCliente"),
            "nombreCliente": alcance.get("nombreCliente"),
            "autorizada": autorizada,
        })
    return {"conexiones": conexiones, "total": len(conexiones)}


@router.delete("/conexiones/{conexion_id}", summary="Desvincular un banco")
def desvincular_banco(conexion_id: str, peticion: Request,
                      usuario_id: str = Depends(usuario_actual)):
    """
    Retira el permiso: lo revoca en el banco (si se puede) y borra la conexión
    con sus cuentas, movimientos y payloads crudos. Solo el dueño puede hacerlo.
    """
    repo = Repositorio()
    try:
        fila = repo.conn.execute(
            "SELECT id FROM conexion WHERE id = %s AND usuario_id = %s",
            (conexion_id, usuario_id),
        ).fetchone()
        if fila is None:
            # Ajena o inexistente: misma respuesta, no se filtra nada.
            raise HTTPException(status_code=404, detail="Conexión no encontrada.")

        alcance = repo.consentimiento_vigente(conexion_id) or {}
        # Se revoca en el banco al que pertenece ESTA conexión.
        b = config_ingesta.banco_sfa(repo.conn.execute(
            """SELECT i.nombre FROM conexion cx JOIN institucion i ON i.id = cx.institucion_id
               WHERE cx.id = %s""", (conexion_id,)).fetchone()[0])
        if alcance.get("consentId") and b is not None:
            try:  # mejor esfuerzo: si la EFS no está, igual se borra de nuestro lado
                with ClienteSFA(b.base_url) as banco:
                    banco.obtener_token_participante(b.client_id, b.client_secret)
                    banco.revocar_consentimiento(alcance["consentId"])
            except Exception:  # noqa: BLE001
                pass

        bitacora.registrar(repo.conn, usuario_id, "banco.desvincular",
                           f"conexión {conexion_id}", bitacora.ip_de(peticion))
        repo.eliminar_conexion(conexion_id)
        repo.commit()
    finally:
        repo.close()
    return {"desvinculada": conexion_id}
