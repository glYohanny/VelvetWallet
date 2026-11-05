# -*- coding: utf-8 -*-
"""
Generador de datos de prueba del banco simulado.

Produce meses de historial financiero de una persona ficticia, con la
irregularidad que tiene la vida real: montos que varían, fechas que se corren,
comercios con glosas sucias y movimientos sin categoría.

El historial depende de un PERFIL (cuánto gana, qué arrienda, a qué está
suscrito, dónde compra). Así la EFS puede tener varios clientes, cada uno con
una vida financiera distinta (ver app/clientes.py).

El perfil por defecto (PERFIL_BASE) es el cliente original de la EFS. Con él y
la semilla fija se genera app/datos_banco.json, idéntico a como estaba:

    python -m app.generador
"""
import calendar
import json
import random
from datetime import datetime, timezone
from pathlib import Path

UTC = timezone.utc

# Semilla fija: la secuencia parece aleatoria pero es siempre la misma.
# Sin esto, cada corrida daría datos distintos y las pruebas fallarían al azar.
SEMILLA = 42

MESES = 12          # cuántos meses de historia generar
ANIO_FIN = 2026     # el historial termina en...
MES_FIN = 10        # ...octubre de 2026 (el mes en curso queda parcial: la EFS solo entrega lo ya ocurrido)


# ─────────────────────────── catálogos (perfil base) ───────────────────────────
# Ingreso mensual fijo
SUELDO = 850_000

# (nombre, monto, día del mes, categoría)
ARRIENDO = ("Inmobiliaria Los Robles", 268_400, 5, "Vivienda")

SUSCRIPCIONES = [
    ("Netflix",   9_900,  5,  "Entretenimiento"),
    ("Spotify",   5_990,  20, "Entretenimiento"),
    ("Smart Fit", 21_990, 5,  "Salud"),
    ("iCloud",    2_700,  12, "Servicios"),
]

# Cuentas del hogar: el monto varía mes a mes, la fecha se corre
# (nombre, monto base, día aproximado, categoría)
CUENTAS_HOGAR = [
    ("CGE",       38_000, 12, "Servicios"),
    ("Essal",     21_000, 15, "Servicios"),
    ("Abastible", 18_000, 18, "Servicios"),
]

# Compras variables
# (nombre, categoría, monto mínimo, monto máximo)
COMERCIOS = [
    ("Lider",             "Alimentos",     15_000, 60_000),
    ("Unimarc",           "Alimentos",      8_000, 35_000),
    ("Uber Eats",         "Restaurantes",   6_000, 20_000),
    ("Copec",             "Transporte",    20_000, 45_000),
    ("Falabella",         "Vestuario",     15_000, 90_000),
    ("Farmacia Ahumada",  "Salud",          4_000, 25_000),
]

# Movimientos con glosa sucia y SIN merchantDetails.
# Son el caso que obliga al clasificador a abstenerse.
GLOSAS_SUCIAS = [
    "PAGO PSP 4471 STGO",
    "SERVIPAG CGE 0092",
    "TRANSBANK*CL 8829",
    "CL*SERV 2210",
]

# El perfil base reúne los catálogos de arriba. Los otros perfiles (clientes.py)
# tienen la misma forma con otros valores.
PERFIL_BASE = {
    "sueldo": SUELDO,
    "dia_sueldo": 30,
    "glosa_sueldo": "Abono de remuneracion",
    "arriendo": ARRIENDO,
    "glosa_arriendo": "Pago de arriendo",
    "suscripciones": SUSCRIPCIONES,
    "cuentas_hogar": CUENTAS_HOGAR,
    "comercios": COMERCIOS,
    "compras_por_mes": (8, 15),
    "sucias_por_mes": (1, 2),
    "glosas_sucias": GLOSAS_SUCIAS,
    "pendientes": 3,
}


# ─────────────────────────── utilidades ───────────────────────────
def dia_valido(anio, mes, dia):
    """
    Ajusta un día para que exista en ese mes.

    Si pedimos el 30 de febrero, devuelve el 28 (o 29 en año bisiesto).
    calendar.monthrange devuelve (día de la semana del 1º, cantidad de días).
    """
    ultimo = calendar.monthrange(anio, mes)[1]
    return min(dia, ultimo)


def correr_si_finde(anio, mes, dia):
    """
    Si la fecha cae sábado o domingo, la mueve al lunes siguiente.

    weekday() devuelve 0 para lunes y 6 para domingo.
    Es lo que pasa con los cobros automáticos: no se cursan el fin de semana.
    """
    d = datetime(anio, mes, dia)
    if d.weekday() == 5:            # sábado
        dia += 2
    elif d.weekday() == 6:          # domingo
        dia += 1
    return dia_valido(anio, mes, dia)


def fecha(anio, mes, dia, hora=12, minuto=0):
    """Arma un datetime CON zona horaria, como exige el estándar."""
    return datetime(anio, mes, dia_valido(anio, mes, dia), hora, minuto, tzinfo=UTC)


def variar(rng, monto, pct=0.20):
    """
    Devuelve el monto con una variación aleatoria de hasta ±pct.

    Es lo que convierte la cuenta de la luz en un problema real para el
    detector de recurrencias: si siempre fuera $38.000 exactos, encontrarla
    sería trivial y el algoritmo no demostraría nada.
    """
    factor = 1 + rng.uniform(-pct, pct)
    return float(round(monto * factor))


def movimiento(tid, cuando, tipo, monto, comercio=None, categoria=None, glosa=None):
    """
    Construye un movimiento en el formato del estándar.

    Los cinco primeros campos son los obligatorios según el spec de la CMF.
    merchantDetails y paymentPurposeCode son opcionales.
    """
    m = {
        "transactionID": tid,
        "bookingDateTime": cuando,
        "transactionsType": tipo,
        "amount": float(round(monto)),
        "currency": "CLP",
    }
    if glosa:
        m["paymentPurposeCode"] = glosa
    if comercio or categoria:
        m["merchantDetails"] = {"name": comercio, "category": categoria}
    return m


# ─────────────────────────── un mes ───────────────────────────
def movimientos_del_mes(anio, mes, rng, contador, perfil=None, prefijo=None):
    """
    Genera todos los movimientos de un mes para un perfil.

    'contador' es una lista de un elemento que usamos para numerar los IDs de
    forma correlativa a lo largo de toda la generación. Se pasa así porque las
    listas son mutables: lo que modificamos acá se ve afuera.

    'prefijo' distingue los transactionID de cada cliente (TXN-<prefijo>-...).
    Sin prefijo, el formato es el original (TXN-AAAAMM-NNNN).
    """
    p = perfil or PERFIL_BASE
    movs = []

    def sig_id():
        contador[0] += 1
        if prefijo:
            return "TXN-%s-%d%02d-%04d" % (prefijo, anio, mes, contador[0])
        return "TXN-%d%02d-%04d" % (anio, mes, contador[0])

    # 1. El sueldo (o el último día del mes si es más corto). Una cuenta
    #    secundaria en otro banco puede no recibirlo: el sueldo llega a uno solo.
    if p.get("sueldo"):
        movs.append(movimiento(
            sig_id(), fecha(anio, mes, p["dia_sueldo"], 9, 5), "Abono", p["sueldo"],
            glosa=p["glosa_sueldo"]))

    # 2. El arriendo / dividendo: monto fijo, día fijo (si el perfil tiene)
    if p.get("arriendo"):
        nombre, monto, dia, cat = p["arriendo"]
        movs.append(movimiento(
            sig_id(), fecha(anio, mes, dia, 10), "Cargo", monto,
            comercio=nombre, categoria=cat, glosa=p.get("glosa_arriendo")))

    # 3. Suscripciones: monto fijo, pero la fecha se corre si cae fin de semana
    for nombre, monto, dia, cat in p["suscripciones"]:
        d = correr_si_finde(anio, mes, dia)
        movs.append(movimiento(
            sig_id(), fecha(anio, mes, d, rng.randint(8, 22)), "Cargo", monto,
            comercio=nombre, categoria=cat))

    # 4. Cuentas del hogar: monto variable ±20%, día variable ±3
    for nombre, base, dia, cat in p["cuentas_hogar"]:
        d = dia_valido(anio, mes, dia + rng.randint(-3, 3))
        movs.append(movimiento(
            sig_id(), fecha(anio, mes, d, rng.randint(9, 20)), "Cargo",
            variar(rng, base), comercio=nombre, categoria=cat))

    # 5. Compras variables repartidas por el mes
    minimo_c, maximo_c = p["compras_por_mes"]
    for _ in range(rng.randint(minimo_c, maximo_c)):
        nombre, cat, minimo, maximo = rng.choice(p["comercios"])
        movs.append(movimiento(
            sig_id(),
            fecha(anio, mes, rng.randint(1, 28), rng.randint(8, 22), rng.choice([0, 15, 30, 45])),
            "Cargo", rng.randint(minimo, maximo),
            comercio=nombre, categoria=cat))

    # 6. Movimientos con glosa sucia y SIN comercio ni categoría.
    #    Este es el caso donde el clasificador tiene que abstenerse.
    minimo_s, maximo_s = p["sucias_por_mes"]
    for _ in range(rng.randint(minimo_s, maximo_s)):
        movs.append(movimiento(
            sig_id(),
            fecha(anio, mes, rng.randint(1, 28), rng.randint(8, 22)),
            "Cargo", rng.randint(3_000, 40_000),
            glosa=rng.choice(p["glosas_sucias"])))

    movs.sort(key=lambda m: m["bookingDateTime"])
    return movs


# ─────────────────────────── todo el historial ───────────────────────────
def generar(meses=MESES, perfil=None, semilla=SEMILLA, prefijo=None):
    """Genera 'meses' meses hacia atrás desde ANIO_FIN / MES_FIN para un perfil."""
    p = perfil or PERFIL_BASE
    rng = random.Random(semilla)
    contador = [0]
    todos = []

    # Recorremos de más antiguo a más nuevo
    for i in range(meses - 1, -1, -1):
        mes_abs = (ANIO_FIN * 12 + MES_FIN - 1) - i
        anio, mes = mes_abs // 12, mes_abs % 12 + 1
        todos.extend(movimientos_del_mes(anio, mes, rng, contador, p, prefijo))

    # Las últimas compras con tarjeta quedan como "pendientes": su monto va a
    # cambiar cuando se llame a /simulador/avanzar. Los campos con guion bajo
    # son internos y NO se envían en la respuesta de la API.
    #
    # Solo se marcan cargos con comercio: son los únicos que en la vida real se
    # pre-autorizan y después se confirman por otro monto (propina, ajuste del
    # comercio, conversión de moneda). Un sueldo o un arriendo no hacen eso.
    candidatos = [m for m in todos
                  if m["transactionsType"] == "Cargo" and "merchantDetails" in m]
    n = p.get("pendientes", 3)
    if n:
        for m in candidatos[-n:]:
            m["_pendiente"] = True
            m["_monto_final"] = float(round(m["amount"] * rng.uniform(1.05, 1.20)))

    return todos


def main():
    movs = generar()
    salida = Path(__file__).parent / "datos_banco.json"

    # default=str convierte los datetime a texto ISO, que es como viajan en JSON
    salida.write_text(
        json.dumps(movs, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")

    print("Generados %d movimientos en %d meses" % (len(movs), MESES))
    print("Archivo: %s" % salida)
    print()
    print("Primeros 3:")
    for m in movs[:3]:
        print("  ", m["transactionID"], m["bookingDateTime"].date(),
              "%9.0f" % m["amount"],
              m.get("merchantDetails", {}).get("name") or m.get("paymentPurposeCode"))


if __name__ == "__main__":
    main()
