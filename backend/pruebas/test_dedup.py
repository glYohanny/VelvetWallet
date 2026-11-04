# -*- coding: utf-8 -*-
"""
Pruebas del emparejamiento entre fuentes (RF-09). Unitarias.

La pregunta: ¿esta fila de la cartola es la misma compra que ya trajo la API?
Lo que más importa no es acertar los casos fáciles, sino no fusionar dos
compras distintas y no dejar sin fusionar una repetida.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from ingesta.dedup import Movimiento as M, emparejar, parecido


def d(dia: int) -> date:
    return date(2026, 10, dia)


class TestEmparejar:
    def test_la_misma_compra_con_otra_glosa_y_fecha_contable(self):
        api = [M("a1", d(3), Decimal(-45990), "Jumbo")]
        cartola = [M("c1", d(5), Decimal(-45990), "COMPRA JUMBO LA FLORIDA 0912")]
        assert emparejar(cartola, api) == {"c1": "a1"}

    def test_otro_monto_no_es_la_misma(self):
        api = [M("a1", d(3), Decimal(-45990), "Jumbo")]
        assert emparejar([M("c1", d(3), Decimal(-45900), "JUMBO")], api) == {}

    def test_muy_lejos_en_el_tiempo_no_es_la_misma(self):
        # Netflix todos los meses por el mismo monto: no se confunden.
        api = [M("a1", d(1), Decimal(-9990), "Netflix")]
        assert emparejar([M("c1", d(30), Decimal(-9990), "NETFLIX.COM")], api) == {}

    def test_uno_a_uno_con_dos_compras_iguales(self):
        api = [M("a1", d(3), Decimal(-3500), "Starbucks"),
               M("a2", d(3), Decimal(-3500), "Starbucks")]
        cartola = [M("c1", d(3), Decimal(-3500), "STARBUCKS"),
                   M("c2", d(3), Decimal(-3500), "STARBUCKS")]
        pares = emparejar(cartola, api)
        assert len(pares) == 2 and set(pares.values()) == {"a1", "a2"}

    def test_una_tercera_compra_que_la_api_no_trajo_queda_aparte(self):
        api = [M("a1", d(3), Decimal(-3500), "Starbucks")]
        cartola = [M("c1", d(3), Decimal(-3500), "STARBUCKS"),
                   M("c2", d(3), Decimal(-3500), "STARBUCKS")]
        assert len(emparejar(cartola, api)) == 1

    def test_gana_la_fecha_mas_cercana(self):
        api = [M("lunes", d(5), Decimal(-20000), "Transferencia"),
               M("jueves", d(8), Decimal(-20000), "Transferencia")]
        assert emparejar([M("c1", d(7), Decimal(-20000), "TRANSF")], api) == {"c1": "jueves"}

    def test_a_igual_distancia_gana_la_glosa_parecida(self):
        api = [M("copec", d(3), Decimal(-30000), "Copec"),
               M("lider", d(3), Decimal(-30000), "Lider")]
        assert emparejar([M("c1", d(4), Decimal(-30000), "COMPRA LIDER EXPRESS")], api) == {
            "c1": "lider"}

    def test_un_cargo_no_se_empareja_con_un_abono(self):
        api = [M("a1", d(3), Decimal(50000), "Transferencia recibida")]
        assert emparejar([M("c1", d(3), Decimal(-50000), "TRANSFERENCIA")], api) == {}

    def test_listas_vacias(self):
        assert emparejar([], []) == {}
        assert emparejar([M("c1", d(3), Decimal(-1), "x")], []) == {}


class TestParecido:
    def test_ignora_las_palabras_de_relleno_del_banco(self):
        assert parecido("COMPRA POS JUMBO", "Jumbo") == 1.0

    def test_sin_nada_en_comun(self):
        assert parecido("Copec", "Lider") == 0.0

    def test_tildes_y_mayusculas(self):
        assert parecido("PANADERÍA ÑUÑOA", "panaderia nunoa") == 1.0
