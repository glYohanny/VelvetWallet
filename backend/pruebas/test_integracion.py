# -*- coding: utf-8 -*-
"""
Pruebas de integración: app → backend → simulador del banco.

Las unitarias verifican que cada pieza esté bien por dentro. Estas verifican
lo otro, que es donde fallan los sistemas de verdad: que las piezas encajen.
Recorren el camino completo con la API real y una base de datos real, sin
simular nada del medio.

Dos preguntas son las que importan:

**¿Un usuario ve solo lo suyo?** Es la garantía que sostiene todo lo demás. Se
verifica con dos personas vinculadas a clientes distintos del mismo banco, no
con un caso de laboratorio.

**¿La clave del banco pasa alguna vez por Velvet?** El flujo imita a un
navegador: la app manda al banco, el usuario escribe su RUT y su clave *en la
página del banco*, y vuelve con un código. La prueba comprueba que la clave no
aparezca en ninguna URL del recorrido.

El recorrido del navegador y los casos de aislamiento vienen del script
`prueba_e2e.py` que escribió Pedro Torres; acá quedan dentro de pytest, contra
una base desechable y saltándose solos si falta alguna pieza.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

CLAVE_VELVET = "clave-velvet-123"

# Clientes que trae el simulador, con su clave. Son datos de prueba del banco
# simulado, no credenciales de nadie.
CAMILA = ("15.432.876-9", "2468")
DIEGO = ("21.004.567-8", "1357")


# ───────────────────────────── utilidades ─────────────────────────────

def _parametros(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def registrar(api, nombre: str, email: str) -> dict:
    r = api.post("/api/auth/registro",
                 json={"nombre": nombre, "email": email, "password": CLAVE_VELVET})
    assert r.status_code in (200, 201), r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def movimientos(api, cabeceras: dict) -> list:
    return api.get("/api/movimientos?limite=500", headers=cabeceras).json()["movimientos"]


def ir_al_banco(api, efs, cabeceras, rut, clave, decision="autorizar",
                retorno="http://localhost:8081/"):
    """
    Hace de navegador: la app manda al banco, la persona entra y decide, y el
    banco la devuelve a la app. Devuelve los parámetros con que vuelve.
    """
    navegador = httpx.Client(follow_redirects=False)
    try:
        r = api.post("/api/conexiones/iniciar", json={"retorno": retorno}, headers=cabeceras)
        assert r.status_code == 200, r.text
        url = r.json()["urlAutorizacion"]
        assert url.startswith(efs + "/autorizar"), url

        pagina = navegador.get(url)
        assert "Inicia sesión en tu banco" in pagina.text

        q = _parametros(url)
        login = navegador.post(f"{efs}/autorizar/login",
                               data={"request_uri": q["request_uri"], "rut": rut, "clave": clave})
        if login.status_code != 200:
            return {"_login": login.status_code}

        sesion = re.search(r'name="sesion" value="([^"]+)"', login.text).group(1)
        vuelta = navegador.post(f"{efs}/autorizar/decision",
                                data={"request_uri": q["request_uri"], "sesion": sesion,
                                      "decision": decision})
        assert vuelta.status_code == 303, vuelta.text

        destino = vuelta.headers["location"]
        # La clave no puede viajar de vuelta ni siquiera disimulada en la URL.
        assert clave not in destino and "clave" not in destino

        ruta = urlparse(destino)
        final = api.get(ruta.path + "?" + ruta.query)
        assert final.status_code == 303, final.text
        return _parametros(final.headers["location"])
    finally:
        navegador.close()


def vincular(api, efs, cabeceras, rut, clave):
    """Autoriza en el banco y después sincroniza, como hace la app."""
    q = ir_al_banco(api, efs, cabeceras, rut, clave)
    if q.get("banco") != "vinculado":
        return q, None
    return q, api.post("/api/conexiones", json={}, headers=cabeceras)


# ───────────────────── la clave nunca pasa por Velvet ─────────────────────

class TestLaClaveNoPasaPorVelvet:
    def test_mandar_rut_y_clave_a_velvet_no_vincula_nada(self, api, efs, base_limpia):
        z = registrar(api, "Usuario Z", "z@prueba.cl")
        r = api.post("/api/conexiones", json={"rut": CAMILA[0], "clave": CAMILA[1]}, headers=z)
        # Se ignoran y se pide pasar por el banco. Si esto cambiara a 200,
        # significaría que Velvet aceptó credenciales bancarias.
        assert r.status_code == 409
        assert r.json()["detail"]["codigo"] == "reautorizar"

    def test_iniciar_devuelve_la_pagina_del_banco_sin_datos_del_usuario(self, api, efs, base_limpia):
        x = registrar(api, "Usuario X", "x@prueba.cl")
        url = api.post("/api/conexiones/iniciar", json={}, headers=x).json()["urlAutorizacion"]
        # PAR: la solicitud va por canal posterior y la URL solo lleva su
        # identificador, no los datos.
        assert "request_uri=" in url
        assert CAMILA[1] not in url and CAMILA[0] not in url

    def test_iniciar_exige_sesion_de_velvet(self, api, efs, base_limpia):
        assert api.post("/api/conexiones/iniciar", json={}).status_code == 401

    def test_la_clave_equivocada_la_rechaza_el_banco(self, api, efs, base_limpia):
        z = registrar(api, "Usuario Z", "z@prueba.cl")
        q = ir_al_banco(api, efs, z, "11.111.111-1", "9999")
        # El 401 viene de la página del banco: Velvet ni se entera del intento.
        assert q == {"_login": 401}
        assert movimientos(api, z) == []


# ───────────────────── cada usuario ve solo lo suyo ─────────────────────

class TestAislamientoEntreUsuarios:
    @pytest.fixture
    def dos_usuarios(self, api, efs, base_limpia):
        x = registrar(api, "Usuario X", "x@prueba.cl")
        y = registrar(api, "Usuario Y", "y@prueba.cl")
        assert movimientos(api, x) == [] and movimientos(api, y) == []
        _, rx = vincular(api, efs, x, *CAMILA)
        _, ry = vincular(api, efs, y, *DIEGO)
        assert rx is not None and rx.status_code == 200, "X no quedó vinculado"
        assert ry is not None and ry.status_code == 200, "Y no quedó vinculado"
        return x, y, rx.json(), ry.json()

    def test_cada_uno_queda_vinculado_a_su_cliente(self, dos_usuarios):
        _, _, rx, ry = dos_usuarios
        assert rx["cliente"]["nombre"] == "Camila Rojas"
        assert ry["cliente"]["nombre"] == "Diego Muñoz"

    def test_cada_uno_ve_solo_sus_cuentas(self, api, dos_usuarios):
        x, y, _, _ = dos_usuarios
        cuentas_x = {m["cuentaId"] for m in movimientos(api, x)}
        cuentas_y = {m["cuentaId"] for m in movimientos(api, y)}
        assert cuentas_x == {"CTA-15432876-1", "CTA-15432876-2"}
        assert cuentas_y == {"CTA-21004567-1", "CTA-21004567-2"}

    def test_no_comparten_ni_un_movimiento(self, api, dos_usuarios):
        x, y, _, _ = dos_usuarios
        assert not ({m["id"] for m in movimientos(api, x)} &
                    {m["id"] for m in movimientos(api, y)})

    def test_los_perfiles_son_distintos(self, api, dos_usuarios):
        # Camila tiene perfil de familia y Diego de estudiante: si ambos
        # vieran los mismos comercios, el aislamiento sería aparente.
        x, y, _, _ = dos_usuarios
        comercios_x = {m["comercio"] for m in movimientos(api, x)}
        comercios_y = {m["comercio"] for m in movimientos(api, y)}
        assert comercios_x != comercios_y

    def test_los_datos_de_otro_no_se_alcanzan_por_id(self, api, dos_usuarios):
        x, y, _, _ = dos_usuarios
        ajeno = movimientos(api, y)[0]["id"]
        # 404 y no 403: no se confirma siquiera que ese movimiento exista.
        r = api.put(f"/api/movimientos/{ajeno}/categoria",
                    json={"categoria": "Supermercado"}, headers=x)
        assert r.status_code == 404


# ─────────────── las capas de analisis sobre datos reales ───────────────

class TestLasCapasFuncionanSobreDatosReales:
    @pytest.fixture
    def usuario_con_datos(self, api, efs, base_limpia):
        x = registrar(api, "Usuario X", "x@prueba.cl")
        _, r = vincular(api, efs, x, *CAMILA)
        assert r is not None and r.status_code == 200
        return x

    def test_los_gastos_llegan_clasificados(self, api, usuario_con_datos):
        gastos = [m for m in movimientos(api, usuario_con_datos) if m["monto"] < 0]
        assert gastos, "El simulador no entregó gastos"
        con_categoria = [m for m in gastos if m["categoria"]]
        # No se exige el 100%: el clasificador se abstiene a propósito con las
        # glosas que no nombran un comercio.
        assert len(con_categoria) / len(gastos) > 0.5

    def test_lo_que_no_se_reconoce_queda_sin_categoria_y_no_inventado(self, api, usuario_con_datos):
        for m in movimientos(api, usuario_con_datos):
            if m["categoria"] is None:
                assert m["origenClasificacion"] is None
                assert m["estadoCategoria"] == "sin_categoria"

    def test_se_detectan_gastos_recurrentes(self, api, usuario_con_datos):
        r = api.get("/api/suscripciones", headers=usuario_con_datos)
        assert r.status_code == 200
        cuerpo = r.json()
        assert cuerpo["suscripciones"], "No se detectó ninguna recurrencia"
        assert cuerpo["comprometidoAlMes"] > 0
        # Todas nacen esperando la decisión de la persona.
        assert all(s["estado"] == "detectada" for s in cuerpo["suscripciones"])

    def test_una_meta_se_proyecta_con_el_historial_real(self, api, usuario_con_datos):
        r = api.post("/api/metas",
                     json={"nombre": "Notebook", "montoObjetivo": 400_000, "montoAhorrado": 0},
                     headers=usuario_con_datos)
        assert r.status_code == 201, r.text
        p = r.json()["proyeccion"]
        assert p["mesesObservados"] >= 3
        assert p["estado"] in ("proyectada", "improbable")
        if p["estado"] == "proyectada":
            assert p["mesesP50"] <= p["mesesP80"] <= p["mesesP95"]


# ─────────────────── los derechos del titular, de verdad ───────────────────

class TestDerechosDelTitular:
    @pytest.fixture
    def usuario(self, api, efs, base_limpia):
        x = registrar(api, "Usuario X", "x@prueba.cl")
        vincular(api, efs, x, *CAMILA)
        return x

    def test_el_consentimiento_de_tratamiento_llega_apagado(self, api, usuario):
        r = api.get("/api/privacidad/finalidades", headers=usuario)
        assert r.status_code == 200
        assert all(f["consentido"] is False for f in r.json()["finalidades"])

    def test_otorgar_y_revocar_deja_rastro(self, api, usuario):
        api.post("/api/privacidad/finalidades/entrenamiento_modelos",
                 json={"acepta": True}, headers=usuario)
        api.post("/api/privacidad/finalidades/entrenamiento_modelos",
                 json={"acepta": False}, headers=usuario)
        tratamiento = api.get("/api/privacidad/consentimientos",
                              headers=usuario).json()["tratamiento"]
        # Revocar no borra la fila: queda el registro de que existió.
        assert any(t["estado"] == "revocado" and t["revocado"] for t in tratamiento)

    def test_leer_los_movimientos_queda_en_la_bitacora(self, api, usuario):
        movimientos(api, usuario)
        eventos = api.get("/api/privacidad/bitacora", headers=usuario).json()["eventos"]
        assert any(e["accion"] == "datos.leer" for e in eventos)

    def test_la_exportacion_no_incluye_credenciales(self, api, usuario):
        r = api.get("/api/privacidad/exportar", headers=usuario)
        assert r.status_code == 200
        assert "refreshToken" not in r.text
        assert "hash_password" not in r.text
        assert r.json()["movimientos"]

    def test_borrar_la_cuenta_exige_el_correo_exacto(self, api, usuario):
        r = api.request("DELETE", "/api/privacidad/cuenta",
                        json={"confirmacion": "otro@correo.cl"}, headers=usuario)
        assert r.status_code == 400
        # Y la cuenta sigue viva.
        assert api.get("/api/resumen", headers=usuario).status_code == 200

    def test_borrar_la_cuenta_elimina_los_datos_pero_no_la_bitacora(self, api, usuario, url_base):
        import psycopg

        with psycopg.connect(url_base) as conn:
            antes = conn.execute("SELECT count(*) FROM bitacora_auditoria").fetchone()[0]

        r = api.request("DELETE", "/api/privacidad/cuenta",
                        json={"confirmacion": "x@prueba.cl"}, headers=usuario)
        assert r.status_code == 200

        with psycopg.connect(url_base) as conn:
            assert conn.execute("SELECT count(*) FROM usuario").fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM transaccion").fetchone()[0] == 0
            # La bitácora sobrevive, anonimizada: la ley obliga a demostrar
            # qué se hizo con los datos, y ese registro no puede irse con ellos.
            despues = conn.execute("SELECT count(*) FROM bitacora_auditoria").fetchone()[0]
            assert despues >= antes
            assert conn.execute(
                "SELECT count(*) FROM bitacora_auditoria WHERE usuario_id IS NOT NULL"
            ).fetchone()[0] == 0


# ───────────────── cifrado en reposo (RF-31), mirando la base ─────────────────

class TestCifradoEnReposo:
    """
    Lo que vería alguien que lee la base directamente (un respaldo filtrado,
    credenciales robadas): los datos sensibles no aparecen en claro, y la
    aplicación los sigue usando igual que antes.
    """

    @pytest.fixture
    def usuario(self, api, efs, base_limpia):
        x = registrar(api, "Usuario X", "x@prueba.cl")
        _, r = vincular(api, efs, x, *CAMILA)
        assert r is not None and r.status_code == 200
        return x

    def test_el_sueldo_queda_cifrado_y_se_sigue_leyendo(self, api, usuario, url_base):
        import psycopg

        r = api.put("/api/perfil/sueldo", json={"monto": 1234567}, headers=usuario)
        assert r.status_code == 200 and r.json()["sueldoDeclarado"] == 1234567

        with psycopg.connect(url_base) as conn:
            crudo = conn.execute("SELECT sueldo_declarado FROM usuario").fetchone()[0]
        assert crudo.startswith("enc:v1:") and "1234567" not in crudo

        assert api.get("/api/perfil", headers=usuario).json()["sueldoDeclarado"] == 1234567
        sesion = api.post("/api/auth/sesion",
                          json={"email": "x@prueba.cl", "password": CLAVE_VELVET}).json()
        assert sesion["usuario"]["sueldoDeclarado"] == 1234567
        # La copia de portabilidad es para la persona: va legible.
        exportado = api.get("/api/privacidad/exportar", headers=usuario).json()
        assert exportado["titular"]["sueldo_declarado"] == 1234567

    def test_el_token_y_el_rut_del_banco_quedan_cifrados(self, api, usuario, url_base):
        import json

        import psycopg

        with psycopg.connect(url_base) as conn:
            alcance = conn.execute("SELECT alcance_rar FROM consentimiento").fetchone()[0]
        texto = json.dumps(alcance, ensure_ascii=False)
        assert alcance["refreshToken"].startswith("enc:v1:")
        assert "15.432.876-9" not in texto and "Camila" not in texto
        assert "ReadAccountsBasic" in alcance["permisos"]   # lo que se muestra, legible

        # La app sigue viendo a qué cliente está atada la conexión...
        conexion = api.get("/api/conexiones", headers=usuario).json()["conexiones"][0]
        assert conexion["rutCliente"] == "15.432.876-9" and conexion["autorizada"]
        # ...y re-sincronizar usa el token descifrado sin pedir la clave.
        assert api.post("/api/conexiones", json={}, headers=usuario).status_code == 200

    def test_el_payload_crudo_queda_cifrado_e_intacto(self, api, usuario, url_base):
        import psycopg

        from ingesta import config
        from ingesta.conexiones_bd import mongo
        from ingesta.repositorio import Repositorio

        doc = mongo()[config.MONGO_DB].payload_crudo.find_one()
        assert set(doc["payload"]) == {"cifrado"}
        assert "transactionID" not in str(doc["payload"])

        with psycopg.connect(url_base) as conn:
            ref, id_externo = conn.execute(
                "SELECT payload_crudo_ref, id_externo FROM transaccion LIMIT 1").fetchone()
        repo = Repositorio()
        try:
            original = repo.leer_crudo(ref)
        finally:
            repo.close()
        # Se recupera el JSON tal como lo mandó el banco (RF-06).
        assert original["transactionID"] == id_externo

    def test_los_datos_anteriores_se_cifran_con_el_script(self, api, usuario, url_base):
        """Una base de antes del cifrado: columna numérica y todo en claro."""
        import importlib

        import psycopg
        from psycopg.types.json import Json

        from ingesta import config, esquema
        from ingesta.conexiones_bd import mongo
        from ingesta.repositorio import Repositorio

        repo = Repositorio()
        try:
            cx = repo.conn.execute("SELECT conexion_id FROM consentimiento").fetchone()[0]
            en_claro = repo.consentimiento_vigente(cx)
        finally:
            repo.close()
        payloads = mongo()[config.MONGO_DB].payload_crudo
        viejo = payloads.insert_one({"conexion_id": str(cx), "endpoint_origen": "/x",
                                     "payload": {"transactionID": "TX-VIEJO"},
                                     "procesado": True}).inserted_id

        with psycopg.connect(url_base) as conn:
            conn.execute("ALTER TABLE usuario ALTER COLUMN sueldo_declarado TYPE numeric(15,2) "
                         "USING NULL, ADD CONSTRAINT usuario_sueldo_declarado_check "
                         "CHECK (sueldo_declarado >= 0)")
            conn.execute("UPDATE usuario SET sueldo_declarado = 1500000")
            conn.execute("UPDATE consentimiento SET alcance_rar = %s", (Json(en_claro),))

        esquema._al_dia = False   # como un proceso recién levantado
        import cifrar_datos_existentes as script
        importlib.reload(script)
        try:
            assert script.main(simular=True) == {"sueldos": 1, "consentimientos": 1,
                                                 "payloads": 1}
            assert script.main() == {"sueldos": 1, "consentimientos": 1, "payloads": 1}
            # Idempotente: la segunda vez no queda nada por hacer.
            assert script.main() == {"sueldos": 0, "consentimientos": 0, "payloads": 0}
        finally:
            esquema._al_dia = False

        with psycopg.connect(url_base) as conn:
            sueldo, = conn.execute("SELECT sueldo_declarado FROM usuario").fetchone()
            alcance, = conn.execute("SELECT alcance_rar FROM consentimiento").fetchone()
        assert sueldo.startswith("enc:v1:") and alcance["refreshToken"].startswith("enc:v1:")
        assert set(payloads.find_one({"_id": viejo})["payload"]) == {"cifrado"}

        assert api.get("/api/perfil", headers=usuario).json()["sueldoDeclarado"] == 1500000
        assert api.post("/api/conexiones", json={}, headers=usuario).status_code == 200
        repo = Repositorio()
        try:
            assert repo.leer_crudo(str(viejo)) == {"transactionID": "TX-VIEJO"}
        finally:
            repo.close()


# ──────────── las otras fuentes: cartola CSV y carga manual (OE-1) ────────────

def _b64(texto: str) -> str:
    import base64
    return base64.b64encode(texto.encode("utf-8")).decode()


def _cartola(filas: list[tuple[str, str, int]]) -> str:
    """Cartola al estilo de un banco chileno: título, `;`, cargos y abonos aparte."""
    lineas = ["Cartola de Cuenta Corriente;;;", ";;;", "Fecha;Descripción;Cargos;Abonos"]
    for fecha, glosa, monto in filas:
        cargo, abono = (f"$ {-monto:,}".replace(",", "."), "") if monto < 0 else \
                       ("", f"$ {monto:,}".replace(",", "."))
        lineas.append(f"{fecha};{glosa};{cargo};{abono}")
    return "\n".join(lineas) + "\n"


class TestCartolasYCargaManual:
    @pytest.fixture
    def usuario(self, api, efs, base_limpia):
        x = registrar(api, "Usuario X", "x@prueba.cl")
        _, r = vincular(api, efs, x, *CAMILA)
        assert r is not None and r.status_code == 200
        return x

    def _importar(self, api, cabeceras, csv, **destino):
        return api.post("/api/cartolas", headers=cabeceras,
                        json={"contenidoBase64": _b64(csv), "nombreArchivo": "cartola.csv",
                              **destino})

    def test_banco_fuera_del_sfa_con_vista_previa(self, api, usuario):
        csv = _cartola([("01/10/2026", "COMPRA JUMBO LA FLORIDA", -45990),
                        ("02/10/2026", "TRANSFERENCIA DE JUAN PEREZ", 120000),
                        ("03/10/2026", "COMPRA JUMBO LA FLORIDA", -45990),
                        ("35/10/2026", "LINEA ROTA", -1000)])
        antes = len(movimientos(api, usuario))

        vista = self._importar(api, usuario, csv, institucion="Banco Estado", simular=True)
        assert vista.status_code == 200, vista.text
        v = vista.json()
        assert (v["simulado"], v["leidas"], v["nuevas"]) == (True, 3, 3)
        assert v["rechazadas"] == [{"linea": 7, "motivo": "fecha no reconocida: '35/10/2026'"}]
        assert len(movimientos(api, usuario)) == antes       # la vista previa no guarda nada

        r = self._importar(api, usuario, csv, institucion="Banco Estado").json()
        assert (r["nuevas"], r["fusionadas"], r["repetidas"]) == (3, 0, 0)
        de_cartola = [m for m in movimientos(api, usuario) if m["origen"] == "cartola"]
        assert len(de_cartola) == 3 and {m["institucion"] for m in de_cartola} == {"Banco Estado"}
        jumbo = next(m for m in de_cartola if m["monto"] == -45990)
        assert jumbo["categoria"] == "Supermercado"       # mismo clasificador que la API
        assert jumbo["payloadCrudoRef"]                   # y su crudo guardado (RF-06)

        # Reimportar la misma cartola no duplica nada, ni los dos Jumbo iguales.
        otra = self._importar(api, usuario, csv, institucion="banco estado").json()
        assert (otra["nuevas"], otra["repetidas"]) == (0, 3)
        assert len(movimientos(api, usuario)) == antes + 3

        # En Cuentas aparece como cartola: sin "Reautorizar", con hasta dónde llega el dato.
        cx = next(c for c in api.get("/api/conexiones", headers=usuario).json()["conexiones"]
                  if c["institucion"] == "Banco Estado")
        assert (cx["fuente"], cx["estado"], cx["datosHasta"]) == ("cartola", "al_dia",
                                                                 "2026-10-03")

    def test_historial_de_un_banco_conectado_se_fusiona_con_la_api(self, api, usuario):
        todos = movimientos(api, usuario)
        cuenta = api.get("/api/cuentas", headers=usuario).json()["cuentas"][0]
        de_la_cuenta = [m for m in todos if m["cuentaId"] == cuenta["idExterno"]][:3]
        from datetime import date, timedelta

        def un_dia_despues(m):   # la fecha contable de la cartola
            return (date.fromisoformat(m["fecha"][:10]) + timedelta(days=1)).strftime("%d/%m/%Y")

        filas = [(un_dia_despues(m), "COMPRA " + (m["comercio"] or "X").upper(), int(m["monto"]))
                 for m in de_la_cuenta]
        filas.append(("15/01/2020", "COMPRA ANTIGUA", -7000))   # anterior a la conexión
        r = self._importar(api, usuario, _cartola(filas), cuentaId=cuenta["id"]).json()
        assert (r["nuevas"], r["fusionadas"]) == (1, 3)

        despues = movimientos(api, usuario)
        assert len(despues) == len(todos) + 1                 # solo la antigua es nueva
        for m in de_la_cuenta:
            fusionado = next(x for x in despues if x["id"] == m["id"])
            assert fusionado["fuentes"] == ["sfa", "cartola"]   # RF-09: ambos orígenes
        # Re-sincronizar con el banco no las vuelve a duplicar.
        assert api.post("/api/conexiones", json={}, headers=usuario).status_code == 200
        assert len(movimientos(api, usuario)) == len(despues)

    def test_la_api_adopta_lo_que_entro_antes_por_cartola(self, api, usuario, url_base):
        import psycopg

        todos = movimientos(api, usuario)
        cuenta = api.get("/api/cuentas", headers=usuario).json()["cuentas"][0]
        m = next(x for x in todos if x["cuentaId"] == cuenta["idExterno"] and x["monto"] < 0)
        # Como si ese movimiento solo hubiera llegado por cartola (historial
        # importado antes de que la API lo trajera).
        with psycopg.connect(url_base) as conn:
            conn.execute("DELETE FROM transaccion WHERE id = %s", (m["id"],))
        fecha = m["fecha"][8:10] + "/" + m["fecha"][5:7] + "/" + m["fecha"][:4]
        r = self._importar(api, usuario, _cartola([(fecha, "CARGO EN CUENTA", int(m["monto"]))]),
                           cuentaId=cuenta["id"]).json()
        assert r["nuevas"] == 1

        assert api.post("/api/conexiones", json={}, headers=usuario).status_code == 200
        despues = movimientos(api, usuario)
        assert len(despues) == len(todos)                     # no quedó duplicado
        adoptado = next(x for x in despues if x["monto"] == m["monto"]
                        and x["fecha"] == m["fecha"] and x["origen"] == "sfa"
                        and "cartola" in x["fuentes"])
        assert adoptado["glosaOriginal"] == m["glosaOriginal"]   # manda el dato de la API

    def test_errores_que_ve_la_persona(self, api, usuario):
        assert self._importar(api, usuario, "a;b\n1;2\n",
                              institucion="Banco X").status_code == 422
        r = self._importar(api, usuario, _cartola([("01/10/2026", "X", -1)]),
                           institucion="Banco Simulado SFA")
        assert r.status_code == 422 and "elige su cuenta" in r.json()["detail"]
        r = self._importar(api, usuario, _cartola([("01/10/2026", "X", -1)]),
                           cuentaId="00000000-0000-0000-0000-000000000000")
        assert r.status_code == 422
        r = api.post("/api/cartolas", headers=usuario,
                     json={"contenidoBase64": "no es base64!", "institucion": "Banco X"})
        assert r.status_code == 422

    def test_la_cuenta_de_otro_no_sirve_de_destino(self, api, efs, usuario):
        otro = registrar(api, "Usuario Y", "y@prueba.cl")
        vincular(api, efs, otro, *DIEGO)
        ajena = api.get("/api/cuentas", headers=otro).json()["cuentas"][0]["id"]
        r = self._importar(api, usuario, _cartola([("01/10/2026", "X", -1000)]), cuentaId=ajena)
        assert r.status_code == 422
        assert all(m["origen"] != "cartola" for m in movimientos(api, otro))

    def test_gasto_en_efectivo(self, api, usuario):
        r = api.post("/api/movimientos", headers=usuario,
                     json={"monto": 3500, "glosa": "Almuerzo en la feria",
                           "fecha": "2026-10-20", "categoria": "Restaurantes"})
        assert r.status_code == 201, r.text
        m = r.json()
        assert (m["monto"], m["origen"], m["categoria"], m["institucion"]) == (
            -3500, "manual", "Restaurantes", "Efectivo")
        assert m["origenClasificacion"] == "usuario"           # lo decidió la persona
        assert m["correcciones"] == []        # pero elegirla al anotar no es una corrección
        assert any(x["id"] == m["id"] for x in movimientos(api, usuario))

        cx = next(c for c in api.get("/api/conexiones", headers=usuario).json()["conexiones"]
                  if c["institucion"] == "Efectivo")
        assert cx["fuente"] == "manual" and cx["cuentas"][0]["tipo"] == "Efectivo"

        # Sin categoría, la propone el clasificador.
        sin = api.post("/api/movimientos", headers=usuario,
                       json={"monto": 12000, "glosa": "Jumbo"}).json()
        assert sin["categoria"] == "Supermercado" and sin["origenClasificacion"] == "regla"

        ingreso = api.post("/api/movimientos", headers=usuario,
                           json={"monto": 20000, "tipo": "ingreso", "glosa": "Venta bicicleta"})
        assert ingreso.json()["monto"] == 20000

        assert api.delete(f"/api/movimientos/{m['id']}", headers=usuario).status_code == 204
        assert all(x["id"] != m["id"] for x in movimientos(api, usuario))

    def test_validaciones_del_gasto_manual(self, api, usuario):
        def anotar(**campos):
            return api.post("/api/movimientos", headers=usuario,
                            json={"monto": 1000, "glosa": "x", **campos}).status_code
        assert anotar(fecha="2099-01-01") == 422
        assert anotar(monto=0) == 422
        assert anotar(monto=-5) == 422
        assert anotar(glosa="   ") == 422
        assert anotar(categoria="Inventada") == 422
        assert anotar(monto=10**12) == 422

    def test_no_se_borra_lo_que_mando_un_banco(self, api, usuario):
        del_banco = movimientos(api, usuario)[0]["id"]
        assert api.delete(f"/api/movimientos/{del_banco}", headers=usuario).status_code == 404

    def test_borrar_la_cuenta_se_lleva_tambien_los_crudos(self, api, usuario):
        from ingesta import config
        from ingesta.conexiones_bd import mongo

        self._importar(api, usuario, _cartola([("01/10/2026", "COMPRA X", -1000)]),
                       institucion="Banco Estado")
        api.post("/api/movimientos", headers=usuario, json={"monto": 1000, "glosa": "Café"})
        crudos = mongo()[config.MONGO_DB].payload_crudo
        suyas = {"conexion_id": {"$in": [
            c["id"] for c in api.get("/api/conexiones", headers=usuario).json()["conexiones"]]}}
        # Del banco, de la cartola y del efectivo: tres conexiones con crudo.
        assert len(crudos.distinct("conexion_id", suyas)) == 3
        r = api.request("DELETE", "/api/privacidad/cuenta",
                        json={"confirmacion": "x@prueba.cl"}, headers=usuario)
        assert r.status_code == 200
        assert crudos.count_documents(suyas) == 0
