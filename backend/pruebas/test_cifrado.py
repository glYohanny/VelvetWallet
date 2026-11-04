# -*- coding: utf-8 -*-
"""
Pruebas unitarias del cifrado en reposo (RF-31).

No necesitan base ni simulador: verifican las propiedades que se le prometen
al cifrado, que son las que habría que defender si alguien pregunta "¿y si
alguien entra a la base?":

  · lo guardado no revela el dato, y dos cifrados del mismo dato no se parecen;
  · un dato alterado no se descifra (no se entrega corrupto);
  · un dato copiado a otro registro no se descifra (el contexto lo ata);
  · sin la clave correcta no se descifra;
  · la clave se puede rotar sin perder lo cifrado con la anterior.
"""
from __future__ import annotations

import base64
import secrets

import pytest

from ingesta import cifrado as c


def _clave() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


@pytest.fixture(autouse=True)
def clave_de_prueba(monkeypatch):
    monkeypatch.setenv("VELVET_CLAVE_CIFRADO", _clave())
    monkeypatch.delenv("VELVET_CLAVES_ANTERIORES", raising=False)
    c.recargar_claves()
    yield
    c.recargar_claves()


def _alterar(valor: str) -> str:
    """Cambia un carácter del cuerpo cifrado (no del prefijo)."""
    i = len(valor) - 5
    return valor[:i] + ("A" if valor[i] != "A" else "B") + valor[i + 1:]


class TestIdaYVuelta:
    def test_lo_que_se_cifra_se_recupera_igual(self):
        token = "rt-8f2c1b3e-9d4a-4c11-b2aa-0f0e5c6d7e8f"
        guardado = c.cifrar(token, "ctx")
        assert c.descifrar(guardado, "ctx") == token

    def test_lo_guardado_no_contiene_el_dato(self):
        guardado = c.cifrar("15.432.876-9", "ctx")
        assert guardado.startswith(c.PREFIJO)
        assert "15.432.876" not in guardado and "432876" not in guardado

    def test_el_mismo_dato_cifrado_dos_veces_no_se_repite(self):
        # Nonce aleatorio: si se repitiera, quien mire la base sabría qué
        # personas tienen el mismo sueldo sin descifrar nada.
        assert c.cifrar("1500000", "ctx") != c.cifrar("1500000", "ctx")

    def test_texto_con_tildes_y_enie(self):
        assert c.descifrar(c.cifrar("Diego Muñoz Ñúñez", "ctx"), "ctx") == "Diego Muñoz Ñúñez"

    def test_none_queda_none(self):
        assert c.cifrar(None, "ctx") is None
        assert c.descifrar(None, "ctx") is None

    def test_numeros(self):
        guardado = c.cifrar_numero(1850000, "ctx")
        assert "1850000" not in guardado
        assert c.descifrar_numero(guardado, "ctx") == 1850000.0
        assert c.cifrar_numero(None, "ctx") is None

    def test_cifrar_solo_acepta_texto(self):
        with pytest.raises(TypeError):
            c.cifrar(1500000, "ctx")


class TestQueNoSePuedaAbusar:
    def test_un_dato_alterado_no_se_descifra(self):
        guardado = c.cifrar("rt-secreto", "ctx")
        with pytest.raises(c.ErrorDeCifrado):
            c.descifrar(_alterar(guardado), "ctx")

    def test_copiado_a_otro_registro_no_se_descifra(self):
        # Alguien con acceso a la base copia el sueldo de una persona en la
        # fila de otra: el contexto (campo + id) ya no calza.
        de_ana = c.cifrar_numero(3000000, c.ctx_sueldo("id-ana"))
        with pytest.raises(c.ErrorDeCifrado):
            c.descifrar_numero(de_ana, c.ctx_sueldo("id-beto"))

    def test_copiado_a_otro_campo_no_se_descifra(self):
        token = c.cifrar("rt-secreto", c.ctx_consentimiento("cx-1", "refreshToken"))
        with pytest.raises(c.ErrorDeCifrado):
            c.descifrar(token, c.ctx_consentimiento("cx-1", "rutCliente"))

    def test_con_otra_clave_no_se_descifra(self, monkeypatch):
        guardado = c.cifrar("rt-secreto", "ctx")
        monkeypatch.setenv("VELVET_CLAVE_CIFRADO", _clave())
        c.recargar_claves()
        with pytest.raises(c.ErrorDeCifrado, match="clave"):
            c.descifrar(guardado, "ctx")

    def test_formato_roto(self):
        with pytest.raises(c.ErrorDeCifrado):
            c.descifrar(c.PREFIJO + "sin-separador", "ctx")

    def test_una_clave_de_largo_incorrecto_se_rechaza(self, monkeypatch):
        monkeypatch.setenv("VELVET_CLAVE_CIFRADO",
                           base64.urlsafe_b64encode(b"corta").decode())
        c.recargar_claves()
        with pytest.raises(c.ErrorDeCifrado, match="32 bytes"):
            c.cifrar("x", "ctx")


class TestDatosAnterioresYRotacion:
    def test_un_dato_en_claro_se_lee_igual(self):
        # Filas escritas antes del cifrado: se leen, y se cifran después.
        assert c.descifrar("rt-viejo-en-claro", "ctx") == "rt-viejo-en-claro"
        assert c.descifrar_numero("1500000.00", "ctx") == 1500000.0

    def test_rotar_la_clave_sin_perder_lo_cifrado(self, monkeypatch):
        vieja = _clave()
        monkeypatch.setenv("VELVET_CLAVE_CIFRADO", vieja)
        c.recargar_claves()
        guardado = c.cifrar("rt-secreto", "ctx")

        monkeypatch.setenv("VELVET_CLAVE_CIFRADO", _clave())
        monkeypatch.setenv("VELVET_CLAVES_ANTERIORES", vieja)
        c.recargar_claves()
        # La anterior todavía descifra, pero ya no es la actual: hay que re-cifrar.
        assert c.descifrar(guardado, "ctx") == "rt-secreto"
        assert not c.cifrado_con_clave_actual(guardado)
        assert c.cifrado_con_clave_actual(c.cifrar("rt-secreto", "ctx"))


class TestAlcanceDelConsentimiento:
    ALCANCE = {
        "permisos": ["ReadAccountsBasic", "ReadBalances"],
        "consentId": "urn:sfa:consent:123",
        "proveedor": "Banco Simulado SFA",
        "rutCliente": "15.432.876-9",
        "nombreCliente": "Camila Rojas",
        "refreshToken": "rt-abc",
    }

    def test_cifra_solo_lo_sensible(self):
        guardado = c.cifrar_alcance(self.ALCANCE, "cx-1")
        # Lo que se le muestra a la persona (RF-27) queda legible.
        for campo in ("permisos", "consentId", "proveedor"):
            assert guardado[campo] == self.ALCANCE[campo]
        for campo in c.CAMPOS_SENSIBLES_ALCANCE:
            assert c.esta_cifrado(guardado[campo])
        assert "15.432.876-9" not in str(guardado) and "rt-abc" not in str(guardado)

    def test_ida_y_vuelta(self):
        guardado = c.cifrar_alcance(self.ALCANCE, "cx-1")
        assert c.descifrar_alcance(guardado, "cx-1") == self.ALCANCE

    def test_no_cifra_dos_veces(self):
        una = c.cifrar_alcance(self.ALCANCE, "cx-1")
        assert c.cifrar_alcance(una, "cx-1") == una

    def test_el_token_de_una_conexion_no_sirve_en_otra(self):
        guardado = c.cifrar_alcance(self.ALCANCE, "cx-1")
        with pytest.raises(c.ErrorDeCifrado):
            c.descifrar_alcance(guardado, "cx-2")

    def test_campos_ausentes_o_nulos(self):
        parcial = {"permisos": [], "refreshToken": None}
        assert c.descifrar_alcance(c.cifrar_alcance(parcial, "cx-1"), "cx-1") == parcial
        assert c.cifrar_alcance(None, "cx-1") is None
