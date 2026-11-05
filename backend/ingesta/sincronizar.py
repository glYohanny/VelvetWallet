# -*- coding: utf-8 -*-
"""
Orquestador de la ingesta:
    token participante → consentimiento (RAR) → proveedor SFA →
    Mongo (crudo) → Postgres (canónico).

Dos formas de usarlo:

  · Por línea de comandos (usuario de demostración):
        python -m ingesta.sincronizar

  · Desde la API, para un usuario real que vincula su banco:
        vincular_conexion(usuario_id, tokens_del_canje)   # después de autorizar en el banco
        sincronizar_usuario(usuario_id)                   # trae / re-trae los datos

Al vincular, el usuario inicia sesión EN EL SITIO DEL BANCO (Velvet nunca ve su
clave), aprueba, y el banco entrega SOLO sus cuentas. Las sincronizaciones siguientes usan el refresh
token guardado de esa conexión: no se vuelve a pedir la clave, y no hay forma de
apuntar a otro cliente (el RUT queda fijado a la conexión).

Requisitos: la EFS (simulador) levantada (uvicorn, puerto 8001) y las bases
arriba (Postgres y Mongo; hoy en la nube: Neon y Atlas).

El flujo de seguridad va primero, alineado con la guía ATENA de la CMF:
  1. token de participante (Client Credentials) — prueba que somos Velvet (PSBI),
  2. consentimiento con alcance RAR — qué datos se piden,
  3. autorización del usuario — se emite el token de acceso,
  4. recién ahí se leen los datos. Sin ese permiso, la EFS no entrega nada.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from motor.recurrencias import Cobro, detectar

from . import config
from .bootstrap import asegurar_identidad, conexion_de_usuario
from .cliente_sfa import ClienteSFA, ReautorizacionRequerida
from .normalizador import (categoria_propuesta, credito_canonico, cuenta_canonica,
                           monto_con_signo,
                           transacciones_canonicas, _categoria_origen, _glosa)
from .dedup import TOLERANCIA_DIAS, Movimiento as Mov, emparejar
from .repositorio import Repositorio

# Qué datos se piden al banco (RAR — Rich Authorization Request). Es el alcance
# que el usuario autoriza: leer sus cuentas, saldos y movimientos.
PERMISOS = ["ReadAccountsBasic", "ReadBalances", "ReadTransactionsDetail",
            "ReadLoansBasic"]


class ConexionDeOtroCliente(Exception):
    """
    La conexión ya está atada a otro cliente del banco. Se rechaza para no
    mezclar en un mismo usuario las cuentas de dos personas distintas: primero
    hay que desvincular el banco.
    """


def _obtener_acceso(repo: Repositorio, banco: ClienteSFA, b: config.BancoSFA,
                    conexion_id: str, rut: str | None, clave: str | None,
                    otorgado: dict | None = None) -> tuple[str, dict, dict]:
    """
    Consigue el token de acceso para la conexión y arma el alcance que se
    guarda en `consentimiento.alcance_rar`. Devuelve (consentId, token, alcance).

    · `otorgado`: los tokens que el banco entregó al canjear el código, después
      de que el usuario autorizó EN EL SITIO DEL BANCO (el flujo normal).
    · Con RUT y clave: autorización directa, solo para la demo por CLI.
    · Sin nada: se renueva con el refresh token guardado (re-sincronizar).
    """
    previo = repo.consentimiento_vigente(conexion_id) or {}
    # Conexiones anteriores a este cambio no guardaban el RUT: se crearon con el
    # cliente por defecto de la EFS.
    rut_previo = previo.get("rutCliente") or (config.SFA_RUT_DEMO if previo else None)

    if otorgado or rut:
        if otorgado:
            info = otorgado
            consent_id = info["consentId"]
            banco._token = info["access_token"]
        else:
            consent_id, info = banco.obtener_acceso(
                b.client_id, b.client_secret, PERMISOS, rut, clave
            )
        cliente = info.get("cliente") or {}
        if rut_previo and cliente.get("rut") and not _mismo_rut(cliente["rut"], rut_previo):
            banco.revocar_consentimiento(consent_id)  # no dejar un permiso colgando
            raise ConexionDeOtroCliente(
                "Este banco ya está vinculado al RUT %s. Desvincúlalo antes de "
                "conectar otro cliente." % rut_previo
            )
        refresh = info.get("refresh_token")
    else:
        refresh = previo.get("refreshToken")
        if not refresh:
            raise ReautorizacionRequerida(
                "Este banco todavía no está vinculado: autoriza el acceso en el "
                "sitio de tu banco."
            )
        info = banco.renovar_acceso(b.client_id, b.client_secret, refresh)
        consent_id = info.get("consentId") or previo.get("consentId")
        cliente = info.get("cliente") or {"rut": previo.get("rutCliente"),
                                          "nombre": previo.get("nombreCliente")}

    alcance = {
        "permisos": PERMISOS,
        "consentId": consent_id,
        "proveedor": b.nombre,
        # A qué cliente del banco corresponde esta conexión.
        "rutCliente": cliente.get("rut"),
        "nombreCliente": cliente.get("nombre"),
        # Para renovar el acceso sin volver a pedir la clave. Se guarda cifrado
        # (ver Repositorio.registrar_consentimiento). La clave del banco NO se
        # guarda nunca.
        "refreshToken": refresh,
    }
    return consent_id, info, alcance


class BancoDesconocido(Exception):
    """Esa institución no es un banco participante con el que Velvet esté registrado."""


def _banco(nombre: str | None) -> config.BancoSFA:
    b = config.banco_sfa(nombre)
    if b is None:
        raise BancoDesconocido("%s no es un banco participante del SFA." % nombre)
    return b


def recalcular_recurrencias(repo: Repositorio, usuario_id: str) -> int:
    """
    Corre el detector sobre TODO el historial del usuario, venga de la fuente
    que venga: una cartola con meses antiguos puede completar una serie que la
    API sola no alcanzaba a mostrar.
    """
    cobros = [
        Cobro(id=i, fecha=f, monto=float(monto), glosa=glosa or "")
        for i, f, monto, glosa in repo.cobros_del_usuario(usuario_id)
    ]
    return repo.guardar_suscripciones(usuario_id, detectar(cobros))


def _ya_entraron_por_cartola(repo: Repositorio, cuenta_id: str, datos: list[dict]) -> dict:
    """{índice en `datos`: transaccion_id} de los que ya estaban por otra fuente."""
    if not datos:
        return {}
    margen = timedelta(days=TOLERANCIA_DIAS)
    existentes = repo.candidatos_a_fusion(cuenta_id, "sfa",
                                          min(d["fecha"] for d in datos) - margen,
                                          max(d["fecha"] for d in datos) + margen)
    if not existentes:
        return {}
    return emparejar(
        [Mov(i, d["fecha"], d["monto"], d["glosa_original"] or "") for i, d in enumerate(datos)],
        [Mov(tid, f, m, g) for tid, f, m, g in existentes],
    )


def _huella(mov: dict) -> tuple:
    """Lo que se compara con lo guardado para saber si el movimiento cambió."""
    return (monto_con_signo(mov["amount"], mov.get("transactionsType")),
            _glosa(mov), _categoria_origen(mov))


def _fecha_de(mov: dict):
    from .normalizador import _fecha
    return _fecha(mov)


def _mismo_rut(a: str, b: str) -> bool:
    limpio = lambda r: r.replace(".", "").replace(" ", "").upper()  # noqa: E731
    return limpio(a) == limpio(b)


def _sincronizar_conexion(repo: Repositorio, usuario_id: str, conexion_id: str,
                          b: config.BancoSFA, desde: str | None = None,
                          rut: str | None = None, clave: str | None = None) -> dict:
    """
    Núcleo de la sincronización para una conexión ya existente. Pide el
    consentimiento, trae del proveedor y deja todo en las dos bases. Confirma al
    final. Lo usan tanto la demo por CLI como la API.
    """
    cuentas_vistas = 0
    insertadas = 0
    actualizadas = 0
    sin_cambio = 0
    fusionadas = 0
    # Para el detector de recurrencias: por comercio, cuántas veces y en cuántos
    # meses distintos aparece como cargo.

    with ClienteSFA(b.base_url) as banco:
        # 1. Seguridad: el cliente se identifica en su banco (o se renueva el
        #    acceso con el refresh token). El token queda atado a ESE cliente.
        consent_id, info_token, alcance = _obtener_acceso(
            repo, banco, b, conexion_id, rut, clave
        )

        # 1a. Dejar registrado el consentimiento vigente en la base.
        expira = datetime.now(timezone.utc) + timedelta(
            seconds=info_token.get("expires_in", 0)
        )
        repo.registrar_consentimiento(conexion_id, alcance, expira)

        # 1b. Los créditos. Son otra familia de APIs del estándar (Operaciones
        #     de Crédito), con su propio permiso en el consentimiento. Se traen
        #     enteros en cada sincronización: son pocos y cambian de saldo cada
        #     mes, así que no hay nada que ganar trayéndolos de a poco.
        creditos = repo.upsert_creditos(
            conexion_id, usuario_id,
            [credito_canonico(c) for c in banco.listar_creditos()],
        )

        # 2. Por cada cuenta del banco...
        for cuenta in banco.listar_cuentas():
            account_id = cuenta["accountId"]
            saldo = banco.obtener_saldo(account_id)

            cuenta_id = repo.upsert_cuenta(
                conexion_id, usuario_id, cuenta_canonica(cuenta, saldo)
            )
            cuentas_vistas += 1

            # 3. Los movimientos. Se compara con lo ya guardado y se escribe
            #    SOLO lo nuevo o lo que cambió: crudo a Mongo (insert_many) y
            #    normalizado a Postgres (un solo upsert). Re-sincronizar sin
            #    novedades no escribe nada.
            endpoint = "/accounts/%s/transactions" % account_id
            movs = banco.obtener_movimientos(account_id, desde=desde)
            if movs:
                guardado = repo.estado_actual(cuenta_id)
                cambios = [m for m in movs if guardado.get(m["transactionID"]) != _huella(m)]
                sin_cambio += len(movs) - len(cambios)
                if cambios:
                    refs = repo.guardar_crudo_bulk(conexion_id, endpoint, cambios)
                    datos = transacciones_canonicas(usuario_id, account_id, cambios)
                    # 3a. Lo que la API trae por primera vez puede haber entrado
                    #     antes por una cartola (historial importado): se fusiona
                    #     con ese movimiento en vez de duplicarlo (RF-09).
                    nuevos = [i for i, m in enumerate(cambios) if m["transactionID"] not in guardado]
                    pares = _ya_entraron_por_cartola(repo, cuenta_id, [datos[i] for i in nuevos])
                    for j, transaccion_id in pares.items():
                        i = nuevos[j]
                        repo.adoptar_desde_sfa(transaccion_id, datos[i], refs[i])
                    fusionadas += len(pares)
                    if pares:
                        quedan = [i for i in range(len(datos))
                                  if i not in {nuevos[j] for j in pares}]
                        refs = [refs[i] for i in quedan]
                        datos = [datos[i] for i in quedan]
                    res = repo.upsert_transacciones_bulk(cuenta_id, refs, datos)
                    insertadas += res["insertadas"]
                    actualizadas += res["actualizadas"]
                    sin_cambio += res["sin_cambio"]


    # 4. Detectar suscripciones y gastos recurrentes sobre TODO el historial
    #    del usuario, no solo sobre lo recién traído: una serie se reconoce por
    #    su forma a lo largo del tiempo, y el mes que acaba de llegar puede
    #    cerrar una periodicidad que antes no se veía. El detector es
    #    motor/recurrencias.py, que no sabe de base de datos.
    suscripciones = 0
    if insertadas or actualizadas or fusionadas:   # sin movimientos nuevos, nada cambia
        suscripciones = recalcular_recurrencias(repo, usuario_id)

    # 4b. Gastos que siguen sin categoría (de antes del clasificador, o que un
    #     modelo reentrenado ahora sí reconoce).
    clasificados = repo.clasificar_sin_categoria(conexion_id, categoria_propuesta)

    # 5. Marcar la sincronización y confirmar todo de una.
    repo.marcar_sincronizacion(conexion_id)
    repo.commit()

    return {
        "consentimiento": consent_id,
        "cliente": {"rut": alcance["rutCliente"], "nombre": alcance["nombreCliente"]},
        "cuentas": cuentas_vistas,
        "insertadas": insertadas,
        "actualizadas": actualizadas,
        "sin_cambio": sin_cambio,
        "fusionadas": fusionadas,
        "clasificados_ahora": clasificados,
        "suscripciones": suscripciones,
        "creditos": creditos,
    }


def vincular_conexion(usuario_id: str, otorgado: dict,
                      institucion_nombre: str | None = None) -> dict:
    """
    Guarda el permiso que el usuario acaba de otorgar en el sitio del banco
    (los tokens del canje), sin traer datos todavía: así el retorno al usuario
    es inmediato y la app muestra el avance mientras se sincroniza.

    Rechaza (ConexionDeOtroCliente) si la conexión ya estaba atada a otro
    cliente del banco.
    """
    b = _banco(institucion_nombre)
    repo = Repositorio()
    try:
        conexion_id = conexion_de_usuario(repo.conn, usuario_id, b.nombre)
        with ClienteSFA(b.base_url) as banco:
            consent_id, info, alcance = _obtener_acceso(
                repo, banco, b, conexion_id, None, None, otorgado
            )
        expira = datetime.now(timezone.utc) + timedelta(seconds=info.get("expires_in", 0))
        repo.registrar_consentimiento(conexion_id, alcance, expira)
        repo.commit()
        return {"conexion_id": str(conexion_id), "consentimiento": consent_id,
                "cliente": {"rut": alcance["rutCliente"], "nombre": alcance["nombreCliente"]}}
    finally:
        repo.close()


def sincronizar_usuario(usuario_id: str, institucion_nombre: str | None = None,
                        desde: str | None = None, rut: str | None = None,
                        clave: str | None = None) -> dict:
    """
    Vincula (con RUT y clave) o re-sincroniza (sin ellos) un banco para un
    usuario YA existente. Es lo que llama la API.

    Si algo falla antes del commit final, no queda nada a medias: la conexión
    recién creada y lo leído se descartan (la transacción no se confirma).
    """
    b = _banco(institucion_nombre)
    repo = Repositorio()
    try:
        conexion_id = conexion_de_usuario(repo.conn, usuario_id, b.nombre)
        return _sincronizar_conexion(repo, usuario_id, conexion_id, b, desde, rut, clave)
    finally:
        repo.close()


def bancos_conectados(usuario_id: str) -> list[str]:
    """Los bancos del SFA que la persona tiene vinculados, por nombre."""
    repo = Repositorio()
    try:
        filas = repo.conn.execute(
            """SELECT i.nombre FROM conexion cx JOIN institucion i ON i.id = cx.institucion_id
               WHERE cx.usuario_id = %s AND i.participante_sfa ORDER BY i.nombre""",
            (usuario_id,)).fetchall()
        return [f[0] for f in filas if config.banco_sfa(f[0]) is not None]
    finally:
        repo.close()


def _marcar_estado(usuario_id: str, institucion: str, estado: str) -> None:
    repo = Repositorio()
    try:
        repo.conn.execute(
            """UPDATE conexion cx SET estado = %s FROM institucion i
               WHERE i.id = cx.institucion_id AND cx.usuario_id = %s AND i.nombre = %s""",
            (estado, usuario_id, institucion))
        repo.commit()
    finally:
        repo.close()


def sincronizar_todos(usuario_id: str) -> list[dict]:
    """
    Sincroniza cada banco vinculado de la persona POR SEPARADO (RF-07).

    Cada banco corre en su propia transacción: si uno no responde, lo que se
    trajo de los demás queda guardado igual, y ese banco queda marcado como
    "sin respuesta" (la app muestra sus datos de la última vez y lo dice). Un
    permiso vencido tampoco frena a los demás: se informa para que la persona
    lo renueve en ese banco.

    Devuelve un resultado por banco: {"institucion", "ok", "resumen" | "codigo",
    "mensaje"}.
    """
    resultados = []
    for nombre in bancos_conectados(usuario_id):
        try:
            resumen = sincronizar_usuario(usuario_id, nombre)
            resultados.append({"institucion": nombre, "ok": True, "resumen": resumen})
        except ReautorizacionRequerida as e:
            resultados.append({"institucion": nombre, "ok": False, "codigo": "reautorizar",
                               "mensaje": str(e)})
        except ConexionDeOtroCliente as e:
            resultados.append({"institucion": nombre, "ok": False, "codigo": "otro_cliente",
                               "mensaje": str(e)})
        except Exception as e:  # noqa: BLE001 — un banco caído no frena a los otros
            _marcar_estado(usuario_id, nombre, "error")
            resultados.append({"institucion": nombre, "ok": False, "codigo": "sin_respuesta",
                               "mensaje": "%s no respondió. Se muestran sus datos de la última "
                                          "vez. (%s)" % (nombre, type(e).__name__)})
    return resultados


def sincronizar(desde: str | None = None) -> dict:
    """Demo por CLI: usa el usuario de demostración y el cliente demo de la EFS."""
    repo = Repositorio()
    try:
        usuario_id, conexion_id = asegurar_identidad(repo.conn)
        return _sincronizar_conexion(repo, usuario_id, conexion_id, config.BANCOS_SFA[0], desde,
                                     config.SFA_RUT_DEMO, config.SFA_CLAVE_DEMO)
    finally:
        repo.close()


if __name__ == "__main__":
    resumen = sincronizar()
    print("Sincronización lista:")
    print("  Cliente del banco  : %s (%s)" % (resumen["cliente"]["nombre"], resumen["cliente"]["rut"]))
    print("  Consentimiento     : %s" % resumen["consentimiento"])
    print("  Cuentas procesadas : %d" % resumen["cuentas"])
    print("  Movimientos nuevos : %d" % resumen["insertadas"])
    print("  Movimientos actualizados: %d" % resumen["actualizadas"])
    print("  Sin cambios        : %d" % resumen["sin_cambio"])
