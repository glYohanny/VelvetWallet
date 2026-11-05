# -*- coding: utf-8 -*-
"""
Clientes del banco simulado.

Una EFS de verdad tiene muchos clientes, cada uno con sus cuentas y su historia.
Aquí cada cliente se identifica por su RUT y tiene una CLAVE (la que usaría para
entrar al sitio del banco). Al autorizar un consentimiento, el cliente se
identifica con RUT + clave y el token de acceso queda atado a ÉL: solo ve sus
cuentas (ver main.py).

Hay tres perfiles de vida financiera (profesional, estudiante, familia) para
que cada cliente tenga gastos distintos, y se pueden crear clientes nuevos en
vivo con POST /simulador/clientes (quedan guardados en clientes_creados.json y
se regeneran igual al reiniciar, porque la semilla sale del RUT).

Los nombres y RUT son FICTICIOS. Las claves son de demostración.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app import banco, datos
from app.generador import PERFIL_BASE, generar

# Cada banco guarda sus clientes creados en vivo por separado (ver banco.py).
ARCHIVO_CREADOS = banco.archivo("clientes_creados.json")


# ─────────────────────────── RUT ───────────────────────────
def digito_verificador(numero: int) -> str:
    """Dígito verificador del RUT chileno (módulo 11)."""
    suma, factor = 0, 2
    for d in reversed(str(numero)):
        suma += int(d) * factor
        factor = 2 if factor == 7 else factor + 1
    resto = 11 - (suma % 11)
    return "0" if resto == 11 else "K" if resto == 10 else str(resto)


def normalizar_rut(rut: str) -> str:
    """
    '12.345.678-5', '12345678-5' o '123456785' → '12345678-5'.
    Lanza ValueError si el formato o el dígito verificador no son válidos.
    """
    limpio = (rut or "").replace(".", "").replace(" ", "").upper()
    if "-" in limpio:
        cuerpo, dv = limpio.split("-", 1)
    else:
        cuerpo, dv = limpio[:-1], limpio[-1:]
    if not cuerpo.isdigit() or len(dv) != 1:
        raise ValueError("RUT con formato inválido: %r" % rut)
    if digito_verificador(int(cuerpo)) != dv:
        raise ValueError("Dígito verificador incorrecto para el RUT %r" % rut)
    return "%d-%s" % (int(cuerpo), dv)


def formatear_rut(numero: int) -> str:
    """12345678 → '12.345.678-5' (con su dígito verificador)."""
    return "{:,}".format(numero).replace(",", ".") + "-" + digito_verificador(numero)


# ─────────────────────────── perfiles ───────────────────────────
PERFILES = {
    # El cliente original de la EFS: profesional joven, arrienda, suscripciones.
    "profesional": PERFIL_BASE,

    # Estudiante: ingreso bajo, pieza en arriendo, mucho delivery y transporte.
    "estudiante": {
        "sueldo": 450_000,
        "dia_sueldo": 25,
        "glosa_sueldo": "Pago de honorarios",
        "arriendo": ("Arriendos Estudiantiles SpA", 190_000, 3, "Vivienda"),
        "glosa_arriendo": "Pago arriendo pieza",
        "suscripciones": [
            ("Spotify",         3_990, 14, "Entretenimiento"),
            ("YouTube Premium", 3_190, 9,  "Entretenimiento"),
        ],
        "cuentas_hogar": [
            ("Entel", 12_990, 20, "Telecomunicaciones"),
        ],
        "comercios": [
            ("Rappi",             "Restaurantes", 4_000, 15_000),
            ("PedidosYa",         "Restaurantes", 5_000, 14_000),
            ("Metro de Santiago", "Transporte",   1_000,  6_000),
            ("Uber",              "Transporte",   3_000,  9_000),
            ("Santa Isabel",      "Alimentos",    5_000, 25_000),
            ("Cruz Verde",        "Salud",        3_000, 12_000),
            ("Starbucks",         "Restaurantes", 3_500,  7_000),
        ],
        "compras_por_mes": (12, 22),
        "sucias_por_mes": (1, 2),
        "glosas_sucias": ["TRANSBANK*CL 4410", "PAGO PSP 9921 STGO", "MPAGO*KIOSKO 551"],
        "pendientes": 2,
    },

    # Cuenta en un segundo banco: el sueldo llega al otro, así que aquí solo
    # hay compras con la tarjeta y un par de suscripciones. Es lo que tiene
    # mucha gente: la cuenta sueldo en un banco y la tarjeta en otro.
    "secundario": {
        "sueldo": 0,
        "dia_sueldo": 30,
        "glosa_sueldo": "",
        "arriendo": None,
        "suscripciones": [
            ("Amazon Prime", 6_990, 8, "Entretenimiento"),
            ("iCloud",       2_900, 16, "Servicios"),
        ],
        "cuentas_hogar": [],
        "comercios": [
            ("Falabella",    "Vestuario",    12_000, 90_000),
            ("Lider",        "Alimentos",     8_000, 45_000),
            ("Copec",        "Transporte",   15_000, 40_000),
            ("Mercado Libre", "Hogar",        6_000, 60_000),
            ("Starbucks",    "Restaurantes",  3_500,  7_000),
        ],
        "compras_por_mes": (4, 9),
        "sucias_por_mes": (0, 1),
        "glosas_sucias": ["TRANSBANK*CL 2231", "MPAGO*FERIA 118"],
        "pendientes": 1,
    },

    # Familia: ingreso alto, dividendo, colegio, supermercado grande y retail.
    "familia": {
        "sueldo": 1_950_000,
        "dia_sueldo": 30,
        "glosa_sueldo": "Abono de remuneracion",
        "arriendo": ("Dividendo Hipotecario", 520_000, 1, "Vivienda"),
        "glosa_arriendo": "Pago dividendo hipotecario",
        "suscripciones": [
            ("Netflix",             13_900,  5, "Entretenimiento"),
            ("Disney+",              9_990, 11, "Entretenimiento"),
            ("Spotify Familiar",     9_990, 20, "Entretenimiento"),
            ("Colegio San Ignacio", 245_000,  6, "Educación"),
        ],
        "cuentas_hogar": [
            ("Enel",          62_000, 10, "Servicios"),
            ("Aguas Andinas", 28_000, 14, "Servicios"),
            ("Metrogas",      34_000, 17, "Servicios"),
            ("VTR",           32_990, 22, "Telecomunicaciones"),
        ],
        "comercios": [
            ("Jumbo",              "Alimentos",  30_000, 140_000),
            ("Tottus",             "Alimentos",  15_000,  80_000),
            ("Ripley",             "Vestuario",  20_000, 150_000),
            ("Paris",              "Vestuario",  15_000, 120_000),
            ("Shell",              "Transporte", 30_000,  60_000),
            ("Cruz Verde",         "Salud",       5_000,  40_000),
            ("Homecenter Sodimac", "Hogar",      10_000,  90_000),
        ],
        "compras_por_mes": (15, 26),
        "sucias_por_mes": (1, 3),
        "glosas_sucias": ["SERVIPAG ENEL 1123", "TRANSBANK*CL 7781", "PAC SEGURO 0042"],
        "pendientes": 3,
    },
}


# ─────────────────────────── construcción de un cliente ───────────────────────────
def _cuentas_generadas(numero: int, nombre: str, perfil: str) -> list[dict]:
    base = "%s-%d" % (banco.PREFIJO_CUENTA, numero)
    if perfil == "secundario":
        return [
            {
                "accountId": base + "-1",
                "accountType": "Cuenta Vista",
                "nickname": "Cuenta de la tarjeta",
                "status": "Activa",
                "currency": "CLP",
                "openingDate": "2024-02-01",
                "ownerName": nombre.upper(),
                "branch": "Puerto Montt",
                "productName": "Cuenta Vista con Tarjeta",
            },
            {
                "accountId": base + "-2",
                "accountType": "Cuenta de Ahorro",
                "nickname": "Ahorro",
                "status": "Activa",
                "currency": "CLP",
                "openingDate": "2024-02-01",
                "ownerName": nombre.upper(),
                "branch": "Puerto Montt",
                "productName": "Cuenta de Ahorro a la Vista",
            },
        ]
    return [
        {
            "accountId": base + "-1",
            "accountType": "Cuenta Corriente",
            "nickname": "Cuenta principal",
            "status": "Activa",
            "currency": "CLP",
            "openingDate": "2020-01-10" if perfil == "familia" else "2023-03-01",
            "ownerName": nombre.upper(),
            "branch": "Santiago Centro",
            "productName": "Cuenta Corriente Persona",
        },
        {
            "accountId": base + "-2",
            "accountType": "Cuenta Vista",
            "nickname": "Ahorro",
            "status": "Activa",
            "currency": "CLP",
            "openingDate": "2024-06-01",
            "ownerName": nombre.upper(),
            "branch": "Santiago Centro",
            "productName": "Cuenta Vista Digital",
        },
    ]


# ─────────────────────────── créditos por perfil ───────────────────────────
# Qué créditos tiene cada tipo de cliente. Van por perfil y no al azar porque
# la coherencia es lo que hace útil al simulador: una familia con dividendo
# tiene un hipotecario, un profesional joven un crédito de consumo, y un
# estudiante no tiene ninguno. Un generador que le pone un hipotecario a
# cualquiera produce datos con los que no se puede probar nada.
#
# Los campos son los del OpenAPI de Operaciones de Crédito de la CMF,
# verificados el 26-08-2026. El estándar NO entrega CAE, cuotas pagadas ni
# desglose de capital e interés: lo que falta acá falta porque falta allá.
CREDITOS_POR_PERFIL: dict[str, list[dict]] = {
    "profesional": [
        {
            "productName": "Crédito de Consumo",
            "loanType": "Consumo",
            "originalAmount": 4_500_000,
            "monthlyInstallment": 148_900,
            "loanTermMonths": 36,
            "cuotasPagadas": 14,
            "interestRate": 1.29,
            "interestRateType": "Fija",
            "purpose": "Libre disposición",
            "openingDate": "2025-08-05",
            "paymentDay": 5,
        },
    ],
    "estudiante": [],
    "secundario": [],
    "familia": [
        {
            "productName": "Mutuo Hipotecario",
            "loanType": "Hipotecario",
            "originalAmount": 95_000_000,
            "monthlyInstallment": 520_000,
            "loanTermMonths": 240,
            "cuotasPagadas": 63,
            "interestRate": 0.37,
            "interestRateType": "Fija",
            "purpose": "Adquisición de vivienda",
            "openingDate": "2021-07-01",
            "paymentDay": 1,
        },
        {
            "productName": "Crédito Automotriz",
            "loanType": "Automotriz",
            "originalAmount": 12_000_000,
            "monthlyInstallment": 295_400,
            "loanTermMonths": 48,
            "cuotasPagadas": 31,
            "interestRate": 0.89,
            "interestRateType": "Variable",
            "purpose": "Compra de vehículo",
            "openingDate": "2024-04-12",
            "paymentDay": 12,
        },
    ],
}


def _creditos_generados(numero: int, nombre: str, perfil: str) -> list[dict]:
    """
    Los créditos del cliente, en el formato del estándar.

    El saldo pendiente se calcula como lo que queda por pagar en cuotas, no
    como capital residual: el estándar entrega `currentBalance` sin decir cómo
    lo compone cada institución, y aproximarlo por cuotas es lo que un
    proveedor real haría con la información que expone.
    """
    salida = []
    for i, c in enumerate(CREDITOS_POR_PERFIL.get(perfil, []), start=1):
        restantes = max(0, c["loanTermMonths"] - c["cuotasPagadas"])
        salida.append({
            "loanID": "LOAN-%d-%d" % (numero, i),
            "productName": c["productName"],
            "loanType": c["loanType"],
            "currency": "CLP",
            "status": "Vigente" if restantes else "Pagado",
            "ownerName": nombre.upper(),
            "originalAmount": float(c["originalAmount"]),
            "monthlyInstallment": float(c["monthlyInstallment"]),
            "loanTerm": "%d meses" % c["loanTermMonths"],
            "loanTermMonths": c["loanTermMonths"],
            "remainingInstallments": restantes,
            "interestRate": c["interestRate"],
            "periodInterestRate": "Mensual",
            "interestRateType": c["interestRateType"],
            "purpose": c["purpose"],
            "openingDate": c["openingDate"],
            "paymentDay": c["paymentDay"],
            "currentBalance": float(restantes * c["monthlyInstallment"]),
            "arrears": False,
            # El estándar entrega solo un enlace al calendario del proveedor,
            # nunca los datos de la tabla de amortización.
            "amortizationScheduleLink":
                "https://%s/creditos/LOAN-%d-%d/calendario" % (banco.DOMINIO, numero, i),
        })
    return salida


def construir_cliente(rut: str, nombre: str, clave: str, perfil: str = "profesional",
                      sueldo: int | None = None, meses: int = 12,
                      creado_en_vivo: bool = False) -> dict:
    """
    Arma un cliente con historial propio, generado a partir de su perfil. La
    semilla sale del RUT: el mismo cliente produce siempre la misma historia.
    """
    if perfil not in PERFILES:
        raise ValueError("Perfil desconocido %r. Use uno de: %s" % (perfil, ", ".join(PERFILES)))
    rut_n = normalizar_rut(rut)
    numero = int(rut_n.split("-")[0])

    p = dict(PERFILES[perfil])
    if sueldo:
        p["sueldo"] = int(sueldo)

    cuentas = _cuentas_generadas(numero, nombre, perfil)
    principal, ahorro = cuentas[0]["accountId"], cuentas[1]["accountId"]
    # La semilla depende del RUT y del banco: la misma persona tiene historias
    # distintas en cada banco, y siempre la misma en cada uno.
    historial = generar(meses=meses, perfil=p, semilla=numero + banco.SEMILLA,
                        prefijo=banco.PREFIJO_MOVIMIENTO + str(numero))

    # La cuenta de ahorro: una transferencia de la cuenta principal.
    ahora = datetime.now().astimezone()
    ultima = min(historial[-1]["bookingDateTime"], ahora) if historial else ahora
    traspaso = {
        "transactionID": "TXN-%s%d-AHO-0001" % (banco.PREFIJO_MOVIMIENTO, numero),
        "bookingDateTime": ultima,
        "transactionsType": "Abono",
        "amount": float(round(p["sueldo"] * 0.1) if p["sueldo"] else 50_000),
        "currency": "CLP",
        "paymentPurposeCode": "Transferencia entre cuentas propias",
    }

    return {
        "rut": formatear_rut(numero),
        "rut_normalizado": rut_n,
        "nombre": nombre,
        "clave": clave,
        "perfil": perfil,
        "creado_en_vivo": creado_en_vivo,
        "parametros": {"rut": rut_n, "nombre": nombre, "clave": clave, "perfil": perfil,
                       "sueldo": sueldo, "meses": meses},
        "cuentas": cuentas,
        "creditos": _creditos_generados(numero, nombre, perfil),
        "movimientos": {principal: historial, ahorro: [traspaso]},
    }


def _cliente_original() -> dict:
    """El cliente de siempre de la EFS (los datos de datos_banco.json)."""
    numero = 11111111
    return {
        "rut": formatear_rut(numero),
        "rut_normalizado": normalizar_rut(formatear_rut(numero)),
        "nombre": "Jossue Padrón",
        "clave": "1234",
        "perfil": "profesional",
        "creado_en_vivo": False,
        "parametros": None,
        "cuentas": datos.CUENTAS,
        # Sus créditos sí se generan: datos_banco.json es anterior a la API de
        # Operaciones de Crédito y no los trae.
        "creditos": _creditos_generados(numero, "Jossue Padrón", "profesional"),
        "movimientos": datos.MOVIMIENTOS,
    }


# ─────────────────────────── catálogo ───────────────────────────
# Clientes de base. Clientes nuevos se agregan en vivo (ver crear_cliente).
CLIENTES: dict[str, dict] = {}       # rut normalizado → cliente
DUENO_CUENTA: dict[str, str] = {}    # accountId → rut normalizado del dueño
DUENO_CREDITO: dict[str, str] = {}   # loanID → rut normalizado del dueño

# Cliente que se usa cuando quien autoriza NO se identifica (compatibilidad con
# versiones anteriores del backend/app que no mandan RUT).
RUT_POR_DEFECTO = "11111111-1"


def _registrar(cliente: dict) -> dict:
    rut = cliente["rut_normalizado"]
    for c in cliente["cuentas"]:
        dueno = DUENO_CUENTA.get(c["accountId"])
        if dueno and dueno != rut:
            raise ValueError("La cuenta %s ya pertenece a otro cliente" % c["accountId"])
        DUENO_CUENTA[c["accountId"]] = rut
    # Mismo índice para los créditos: sin él, /loans/{id} tendría que recorrer
    # todos los clientes y un cliente podría alcanzar el crédito de otro.
    for c in cliente.get("creditos", []):
        dueno = DUENO_CREDITO.get(c["loanID"])
        if dueno and dueno != rut:
            raise ValueError("El crédito %s ya pertenece a otro cliente" % c["loanID"])
        DUENO_CREDITO[c["loanID"]] = rut
    CLIENTES[rut] = cliente
    return cliente


def _cargar_base():
    if banco.ID == "austral":
        # Las mismas personas, con la misma clave de demostración, pero otra
        # cuenta y otros gastos. Y una clienta que solo está en este banco.
        _registrar(construir_cliente(formatear_rut(15432876), "Camila Rojas", "2468", "secundario"))
        _registrar(construir_cliente(formatear_rut(21004567), "Diego Muñoz", "1357", "secundario"))
        _registrar(construir_cliente(formatear_rut(17654321), "Valentina Soto", "8642", "profesional"))
        return
    _registrar(_cliente_original())
    _registrar(construir_cliente(formatear_rut(15432876), "Camila Rojas", "2468", "familia"))
    _registrar(construir_cliente(formatear_rut(21004567), "Diego Muñoz", "1357", "estudiante"))


def _cargar_creados():
    """Reconstruye los clientes creados en vivo (sobreviven a un reinicio)."""
    if not ARCHIVO_CREADOS.exists():
        return
    for params in json.loads(ARCHIVO_CREADOS.read_text(encoding="utf-8")):
        try:
            _registrar(construir_cliente(creado_en_vivo=True, **params))
        except ValueError:
            continue  # un registro corrupto no debe botar la EFS


def _guardar_creados():
    creados = [c["parametros"] for c in CLIENTES.values() if c["creado_en_vivo"]]
    ARCHIVO_CREADOS.write_text(json.dumps(creados, ensure_ascii=False, indent=1),
                               encoding="utf-8")


def crear_cliente(rut: str, nombre: str, clave: str, perfil: str = "profesional",
                  sueldo: int | None = None, meses: int = 12) -> dict:
    """Crea un cliente nuevo en vivo. Error si el RUT ya existe."""
    rut_n = normalizar_rut(rut)
    if rut_n in CLIENTES:
        raise ValueError("Ya existe un cliente con RUT %s" % rut)
    cliente = _registrar(construir_cliente(rut_n, nombre, clave, perfil, sueldo, meses,
                                           creado_en_vivo=True))
    _guardar_creados()
    return cliente


def eliminar_cliente(rut: str) -> dict:
    """Elimina un cliente creado en vivo (los de base no se pueden borrar)."""
    rut_n = normalizar_rut(rut)
    cliente = CLIENTES.get(rut_n)
    if cliente is None:
        raise KeyError(rut)
    if not cliente["creado_en_vivo"]:
        raise ValueError("Los clientes de base no se pueden eliminar")
    for c in cliente["cuentas"]:
        DUENO_CUENTA.pop(c["accountId"], None)
    del CLIENTES[rut_n]
    _guardar_creados()
    return cliente


def cliente_por_rut(rut: str) -> dict | None:
    try:
        return CLIENTES.get(normalizar_rut(rut))
    except ValueError:
        return None


def resumen(cliente: dict) -> dict:
    """Vista pública de un cliente para los endpoints de control (sin movimientos)."""
    return {
        "rut": cliente["rut"],
        "nombre": cliente["nombre"],
        "clave_demo": cliente["clave"],
        "perfil": cliente["perfil"],
        "creado_en_vivo": cliente["creado_en_vivo"],
        "cuentas": [c["accountId"] for c in cliente["cuentas"]],
        "movimientos": sum(len(v) for v in cliente["movimientos"].values()),
    }


_cargar_base()
_cargar_creados()
