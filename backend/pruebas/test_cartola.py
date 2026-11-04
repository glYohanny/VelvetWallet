# -*- coding: utf-8 -*-
"""
Pruebas del lector de cartolas CSV (RF-12). Unitarias: solo bytes de entrada.

Los archivos imitan cómo exportan los bancos chilenos de verdad: títulos antes
del encabezado, `;` como separador, montos con punto de miles y signo peso,
cargos y abonos en columnas separadas y archivos guardados por Excel en
Windows-1252.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from ingesta.cartola import CartolaInvalida, leer_cartola, leer_fecha, leer_monto

HOY = date(2026, 11, 4)


def leer(texto: str, codificacion: str = "utf-8"):
    return leer_cartola(texto.encode(codificacion), hoy=HOY)


class TestMontos:
    @pytest.mark.parametrize("texto,esperado", [
        ("12.345", 12345), ("$ 12.345", 12345), ("-12.345", -12345),
        ("12.345,50", Decimal("12345.50")), ("1.234.567", 1234567),
        ("(1.200)", -1200), ("1.200-", -1200), ("1,234,567", 1234567),
        ("3500", 3500), ("+3.500", 3500), ("12,5", Decimal("12.5")),
    ])
    def test_formatos_chilenos(self, texto, esperado):
        assert leer_monto(texto) == Decimal(esperado)

    def test_celda_vacia_es_none(self):
        assert leer_monto("") is None and leer_monto(" - ") is None

    def test_texto_no_es_monto(self):
        with pytest.raises(ValueError):
            leer_monto("doce mil")


class TestFechas:
    @pytest.mark.parametrize("texto", ["03/10/2026", "03-10-2026", "2026-10-03",
                                       "03/10/26", "03.10.2026", "03/10/2026 14:22"])
    def test_formatos(self, texto):
        assert leer_fecha(texto) == date(2026, 10, 3)

    def test_fecha_invalida(self):
        with pytest.raises(ValueError):
            leer_fecha("31/02/2026")


class TestArchivos:
    def test_cargos_y_abonos_con_titulos_antes(self):
        c = leer(
            "Banco Estado;;;;\n"
            "Cartola Cuenta RUT;;;;\n"
            "Período: octubre 2026;;;;\n"
            ";;;;\n"
            "Fecha;Descripción;Cargos;Abonos;Saldo\n"
            "01/10/2026;COMPRA JUMBO LA FLORIDA;$ 45.990;;$ 954.010\n"
            "02/10/2026;TRANSFERENCIA DE JUAN PEREZ;;$ 120.000;$ 1.074.010\n"
            ";Saldo final;;;$ 1.074.010\n"
        )
        assert c.columnas == {"fecha": "Fecha", "glosa": "Descripción",
                              "cargo": "Cargos", "abono": "Abonos"}
        assert [(f.fecha, f.monto, f.glosa) for f in c.filas] == [
            (date(2026, 10, 1), Decimal(-45990), "COMPRA JUMBO LA FLORIDA"),
            (date(2026, 10, 2), Decimal(120000), "TRANSFERENCIA DE JUAN PEREZ"),
        ]
        # La línea se cuenta en el archivo, para poder decirle a la persona cuál falló.
        assert c.filas[0].linea == 6
        assert c.rechazadas == []

    def test_una_columna_de_monto_con_signo_y_comas(self):
        c = leer("fecha,detalle,monto\n2026-10-05,Uber Eats,-12.990\n2026-10-06,Sueldo,1.500.000\n")
        assert [f.monto for f in c.filas] == [Decimal(-12990), Decimal(1500000)]

    def test_excel_en_windows(self):
        c = leer("Fecha;Glosa;Monto\n01/10/2026;Panadería Ñuñoa;-2.500\n", "cp1252")
        assert c.filas[0].glosa == "Panadería Ñuñoa"

    def test_bom_de_utf8(self):
        c = leer_cartola("﻿Fecha;Glosa;Monto\n01/10/2026;Café;-3.500\n".encode("utf-8"),
                         hoy=HOY)
        assert len(c.filas) == 1

    def test_las_lineas_malas_se_informan_y_el_resto_entra(self):
        c = leer(
            "Fecha;Glosa;Monto\n"
            "01/10/2026;Café;-3.500\n"
            "35/10/2026;Fecha imposible;-1.000\n"
            "02/10/2026;Sin monto;\n"
            "03/10/2026;Monto raro;abc\n"
            "01/12/2026;Del futuro;-1.000\n"
            "04/10/2026;Bien;-2.000\n"
        )
        assert [f.glosa for f in c.filas] == ["Café", "Bien"]
        assert [r.linea for r in c.rechazadas] == [3, 4, 5, 6]
        assert "futura" in c.rechazadas[-1].motivo

    def test_la_fila_cruda_se_guarda_completa(self):
        c = leer("Fecha;Glosa;Monto;N° Doc\n01/10/2026;Café;-3.500;88123\n")
        assert c.filas[0].crudo == {"Fecha": "01/10/2026", "Glosa": "Café",
                                    "Monto": "-3.500", "N° Doc": "88123"}

    def test_sin_encabezado_reconocible(self):
        with pytest.raises(CartolaInvalida, match="encabezado"):
            leer("a;b;c\n1;2;3\n")

    def test_vacio(self):
        with pytest.raises(CartolaInvalida):
            leer_cartola(b"   ", hoy=HOY)

    def test_demasiado_grande(self):
        with pytest.raises(CartolaInvalida, match="2 MB"):
            leer_cartola(b"x" * (2 * 1024 * 1024 + 1), hoy=HOY)

    def test_un_excel_binario(self):
        with pytest.raises(CartolaInvalida):
            leer_cartola(b"PK\x03\x04\x14\x00\x06\x00\x08\x00\x00\x00!\x00\xff\xfe\x81", hoy=HOY)
