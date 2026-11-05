# -*- coding: utf-8 -*-
"""
Páginas del SITIO DEL BANCO simulado: inicio de sesión y consentimiento.

Es lo que en el SFA real vería el usuario en la web de su banco cuando una app
como Velvet Wallet le pide acceso a sus datos. Lo importante: el RUT y la clave
se escriben AQUÍ, en el banco, nunca en la app del participante.

HTML autocontenido (sin recursos externos). Todo lo que viene de afuera se
escapa antes de insertarlo.
"""
from __future__ import annotations

from html import escape

from app import banco

_ESTILOS = """
:root { --marino:#0B2545; --marino2:#13315C; --turquesa:#12A39A; --fondo:#EEF2F6;
        --texto:#1B2733; --suave:#5B6B7B; --linea:#D6DEE6; --error:#B42318; }
* { box-sizing:border-box; }
body { margin:0; background:var(--fondo); color:var(--texto);
       font-family: "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
.pruebas { background:#FFF4CE; color:#6B4E00; font-size:12px; text-align:center; padding:6px 16px; }
header { background:var(--marino); color:#fff; padding:18px 16px; }
.marca { max-width:440px; margin:0 auto; display:flex; align-items:center; gap:10px; }
.logo { width:34px; height:34px; border-radius:8px; background:var(--turquesa);
        display:flex; align-items:center; justify-content:center; font-weight:700; font-size:18px; }
.marca b { font-size:18px; letter-spacing:.2px; }
.marca span { display:block; font-size:12px; opacity:.75; }
main { max-width:440px; margin:24px auto; padding:0 16px; }
.tarjeta { background:#fff; border-radius:14px; padding:24px; box-shadow:0 2px 10px rgba(11,37,69,.08); }
h1 { font-size:20px; margin:0 0 6px; color:var(--marino); }
p { line-height:1.5; margin:0 0 12px; }
.suave { color:var(--suave); font-size:14px; }
label { display:block; font-size:14px; font-weight:600; margin:14px 0 6px; }
input { width:100%; padding:12px; font-size:16px; border:1px solid var(--linea); border-radius:8px; }
input:focus { outline:2px solid var(--turquesa); border-color:transparent; }
.boton { width:100%; padding:13px; margin-top:18px; border:0; border-radius:8px; font-size:16px;
         font-weight:600; cursor:pointer; background:var(--marino); color:#fff; }
.boton:hover { background:var(--marino2); }
.boton:disabled { opacity:.6; cursor:default; }
.secundario { background:#fff; color:var(--marino); border:1px solid var(--linea); margin-top:10px; }
.secundario:hover { background:var(--fondo); }
.error { background:#FEE4E2; color:var(--error); padding:10px 12px; border-radius:8px; font-size:14px; margin-top:12px; }
.pide { border-left:4px solid var(--turquesa); background:#F2FAF9; padding:10px 12px; border-radius:6px; margin:14px 0; }
ul { padding-left:20px; margin:8px 0 12px; }
li { margin:4px 0; }
.cuenta { font-family: Consolas, monospace; font-size:13px; color:var(--suave); }
footer { text-align:center; font-size:12px; color:var(--suave); margin:18px auto 30px; padding:0 16px; max-width:440px; }
"""


# Desactiva los botones al enviar, para que un doble clic no mande la decisión
# dos veces. Va en un setTimeout: así el botón presionado alcanza a viajar con
# el formulario (un botón desactivado no se envía).
_UNA_VEZ = "setTimeout(() => this.querySelectorAll('button').forEach(b => b.disabled = true), 0)"


def _pagina(titulo: str, cuerpo: str) -> str:
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(titulo)} · {escape(banco.NOMBRE)}</title>
<style>{_ESTILOS}</style></head>
<body>
<div class="pruebas">Entorno de pruebas · Entidad Financiera Simulada (EFS) del proyecto Velvet Wallet</div>
<header><div class="marca"><div class="logo">B</div>
<div><b>{escape(banco.NOMBRE)}</b><span>Banca en línea · Personas</span></div></div></header>
<main>{cuerpo}</main>
<footer>Estás en el sitio de tu banco. Tu clave nunca se comparte con otras aplicaciones.</footer>
</body></html>"""


def pagina_login(request_uri: str, participante: str, error: str | None = None, rut: str = "") -> str:
    aviso = f'<div class="error">{escape(error)}</div>' if error else ""
    return _pagina("Iniciar sesión", f"""
<div class="tarjeta">
  <h1>Inicia sesión en tu banco</h1>
  <p class="suave"><b>{escape(participante)}</b> te está pidiendo acceso a tus datos.
  Primero confirma que eres tú: ingresa con tu RUT y tu clave del banco.</p>
  <form method="post" action="/autorizar/login" autocomplete="off" onsubmit="{_UNA_VEZ}">
    <input type="hidden" name="request_uri" value="{escape(request_uri)}">
    <label for="rut">RUT</label>
    <input id="rut" name="rut" placeholder="12.345.678-9" value="{escape(rut)}" required autofocus>
    <label for="clave">Clave</label>
    <input id="clave" name="clave" type="password" placeholder="••••" required>
    {aviso}
    <button class="boton" type="submit">Ingresar</button>
  </form>
</div>""")


def pagina_consentimiento(request_uri: str, sesion: str, participante: str, nombre_cliente: str,
                          permisos: list[str], cuentas: list[tuple[str, str]], vence: str) -> str:
    lista_permisos = "".join(f"<li>{escape(p)}</li>" for p in permisos)
    lista_cuentas = "".join(
        f'<li>{escape(tipo)} <span class="cuenta">{escape(cid)}</span></li>' for tipo, cid in cuentas)
    return _pagina("Autorizar acceso", f"""
<div class="tarjeta">
  <h1>Hola, {escape(nombre_cliente)}</h1>
  <p class="suave">Revisa lo que <b>{escape(participante)}</b> quiere hacer con tus datos antes de decidir.</p>
  <div class="pide">
    <b>{escape(participante)}</b> solicita permiso para:
    <ul>{lista_permisos}</ul>
  </div>
  <p><b>Cuentas que se compartirán</b></p>
  <ul>{lista_cuentas}</ul>
  <p class="suave">El permiso vence el <b>{escape(vence)}</b> (90 días). Es solo de lectura:
  {escape(participante)} no puede mover tu dinero. Puedes revocarlo cuando quieras.</p>
  <form method="post" action="/autorizar/decision" onsubmit="{_UNA_VEZ}">
    <input type="hidden" name="request_uri" value="{escape(request_uri)}">
    <input type="hidden" name="sesion" value="{escape(sesion)}">
    <button class="boton" type="submit" name="decision" value="autorizar">Autorizar</button>
    <button class="boton secundario" type="submit" name="decision" value="rechazar">Rechazar</button>
  </form>
</div>""")


def pagina_lista(autorizo: bool) -> str:
    texto = ("Ya autorizaste esta solicitud. Puedes cerrar esta pestaña y volver a la aplicación."
             if autorizo else
             "Ya rechazaste esta solicitud. No se compartió nada. Puedes cerrar esta pestaña.")
    return _pagina("Solicitud respondida", f"""
<div class="tarjeta">
  <h1>Listo</h1>
  <p>{escape(texto)}</p>
</div>""")


def pagina_error(mensaje: str) -> str:
    return _pagina("No se pudo continuar", f"""
<div class="tarjeta">
  <h1>No se pudo continuar</h1>
  <p>{escape(mensaje)}</p>
</div>""")
