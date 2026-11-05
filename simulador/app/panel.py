# -*- coding: utf-8 -*-
"""
Panel de control de la EFS: hacer compras en vivo y confirmar pendientes desde
el navegador, sin pasar por /docs ni la terminal. Pensado para la demo.

    http://localhost:8001/panel

NO es parte del estándar ni de lo que vería un cliente del banco: es una
herramienta del equipo, igual que los endpoints /simulador/*, que es lo único
que usa. Página autocontenida (sin recursos externos); todo lo que llega del
servidor se inserta como texto, nunca como HTML.
"""

PANEL_HTML = r"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Panel del simulador · __BANCO__</title>
<style>
:root { --marino:#0B2545; --marino2:#13315C; --turquesa:#12A39A; --fondo:#EEF2F6;
        --texto:#1B2733; --suave:#5B6B7B; --linea:#D6DEE6; --rojo:#B42318; --ambar:#8A5A00; }
* { box-sizing:border-box; }
body { margin:0; background:var(--fondo); color:var(--texto);
       font-family:"Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
.pruebas { background:#FFF4CE; color:#6B4E00; font-size:12px; text-align:center; padding:6px 16px; }
header { background:var(--marino); color:#fff; padding:16px; }
.marca { max-width:720px; margin:0 auto; display:flex; align-items:center; gap:10px; }
.logo { width:34px; height:34px; border-radius:8px; background:var(--turquesa); display:flex;
        align-items:center; justify-content:center; font-weight:700; font-size:18px; flex:none; }
.marca b { font-size:18px; } .marca span { display:block; font-size:12px; opacity:.75; }
main { max-width:720px; margin:20px auto 40px; padding:0 16px; display:grid; gap:16px; }
.tarjeta { background:#fff; border-radius:14px; padding:20px; box-shadow:0 2px 10px rgba(11,37,69,.08); }
h2 { font-size:16px; margin:0 0 12px; color:var(--marino); }
label { display:block; font-size:13px; font-weight:600; margin:12px 0 6px; }
select, input[type=text], input[type=number] { width:100%; padding:11px; font-size:15px;
       border:1px solid var(--linea); border-radius:8px; background:#fff; color:var(--texto); }
input:disabled { background:var(--fondo); color:var(--suave); }
.fila { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
.casillas { display:flex; flex-wrap:wrap; gap:8px 20px; margin-top:14px; }
.casillas label { display:flex; align-items:center; gap:8px; margin:0; font-weight:500; }
.casillas small { display:block; color:var(--suave); font-weight:400; }
button { padding:12px 16px; border:0; border-radius:8px; font-size:15px; font-weight:600; cursor:pointer;
         background:var(--marino); color:#fff; }
button:hover { background:var(--marino2); }
button:disabled { opacity:.55; cursor:default; }
.secundario { background:#fff; color:var(--marino); border:1px solid var(--linea); }
.secundario:hover { background:var(--fondo); }
.acciones { display:flex; flex-wrap:wrap; gap:10px; margin-top:16px; }
.cuentas { display:flex; flex-wrap:wrap; gap:10px; margin-top:12px; }
.cuenta { flex:1 1 200px; border:1px solid var(--linea); border-radius:10px; padding:10px 12px; }
.cuenta small { color:var(--suave); font-family:Consolas, monospace; font-size:12px; }
.cuenta b { display:block; font-size:18px; margin-top:4px; }
.aviso { border-radius:8px; padding:10px 12px; font-size:14px; margin-top:14px; display:none; }
.aviso.ok { display:block; background:#E3F6F4; color:#0B5F59; }
.aviso.mal { display:block; background:#FEE4E2; color:var(--rojo); }
ul.movs { list-style:none; margin:0; padding:0; }
ul.movs li { display:grid; grid-template-columns:1fr auto; gap:2px 12px; padding:10px 0;
             border-top:1px solid var(--linea); }
ul.movs li:first-child { border-top:0; }
.desc { font-weight:600; overflow-wrap:anywhere; }
.meta { color:var(--suave); font-size:12px; grid-column:1; }
.monto { text-align:right; font-variant-numeric:tabular-nums; font-weight:600; }
.abono { color:#0B7A55; }
.chip { display:inline-block; font-size:11px; font-weight:700; border-radius:999px; padding:2px 8px;
        margin-left:6px; vertical-align:1px; }
.chip.pend { background:#FFF4CE; color:var(--ambar); }
.chip.vivo { background:#E3F6F4; color:#0B5F59; }
.chip.sucia { background:#F1F3F6; color:var(--suave); }
.vacio { color:var(--suave); font-size:14px; }
.nota { color:var(--suave); font-size:13px; margin:8px 0 0; line-height:1.45; }
@media (max-width:520px) { .fila { grid-template-columns:1fr; } }
</style></head>
<body>
<div class="pruebas">Herramienta de demostración del equipo · no es parte del banco ni del estándar SFA</div>
<header><div class="marca"><div class="logo">B</div>
<div><b>Panel del simulador</b><span>__BANCO__ · compras en vivo</span></div></div></header>
<main>
  <section class="tarjeta">
    <h2>Cliente</h2>
    <select id="cliente" aria-label="Cliente del banco"></select>
    <div class="cuentas" id="cuentas"></div>
  </section>

  <section class="tarjeta">
    <h2>Hacer una compra</h2>
    <div class="fila">
      <div>
        <label for="comercio">Comercio</label>
        <input id="comercio" type="text" list="comercios" placeholder="Al azar si lo dejas vacío">
        <datalist id="comercios">
          <option value="Lider"><option value="Jumbo"><option value="Ripley"><option value="Falabella">
          <option value="Copec"><option value="Uber Eats"><option value="Rappi"><option value="Starbucks">
          <option value="Farmacias Ahumada"><option value="Netflix">
        </datalist>
      </div>
      <div>
        <label for="monto">Monto (CLP)</label>
        <input id="monto" type="number" min="1" step="10" placeholder="Al azar si lo dejas vacío">
      </div>
    </div>
    <div class="fila">
      <div>
        <label for="cuenta">Cuenta</label>
        <select id="cuenta"></select>
      </div>
    </div>
    <div class="casillas">
      <label><input type="checkbox" id="pendiente">
        <span>Pendiente<small>Se confirma después con otro monto</small></span></label>
      <label><input type="checkbox" id="sucia">
        <span>Glosa sucia<small>Sin comercio: debe caer en "Por revisar"</small></span></label>
    </div>
    <div class="acciones">
      <button id="comprar">Hacer compra</button>
      <button id="confirmar" class="secundario">Confirmar pendientes</button>
    </div>
    <div id="aviso" class="aviso" role="status"></div>
    <p class="nota">Después de cada acción, toca <b>Sincronizar</b> en Velvet Wallet para que llegue.</p>
  </section>

  <section class="tarjeta">
    <h2>Créditos</h2>
    <ul class="movs" id="creditos"></ul>
    <div class="fila">
      <div>
        <label for="cr_producto">Producto</label>
        <input id="cr_producto" type="text" list="productos" placeholder="Crédito de Consumo">
        <datalist id="productos">
          <option value="Crédito de Consumo"><option value="Mutuo Hipotecario">
          <option value="Crédito Automotriz"><option value="Avance en cuotas">
        </datalist>
      </div>
      <div>
        <label for="cr_cuota">Cuota mensual (CLP)</label>
        <input id="cr_cuota" type="number" min="1" step="1000" placeholder="120000">
      </div>
    </div>
    <div class="fila">
      <div>
        <label for="cr_plazo">Plazo (meses)</label>
        <input id="cr_plazo" type="number" min="1" max="600" placeholder="24">
      </div>
      <div>
        <label for="cr_pagadas">Cuotas ya pagadas</label>
        <input id="cr_pagadas" type="number" min="0" placeholder="0">
      </div>
    </div>
    <div class="acciones">
      <button id="crear_credito">Agregar crédito</button>
    </div>
    <p class="nota">Toca una cuota de un crédito para pagarla y ver cómo baja el saldo en Velvet.</p>
  </section>

  <section class="tarjeta">
    <h2>Últimos movimientos</h2>
    <ul class="movs" id="movs"></ul>
  </section>
</main>
<script>
const $ = (id) => document.getElementById(id);
const pesos = (n) => (n < 0 ? "−" : "") + "$" + Math.abs(Math.round(n)).toLocaleString("es-CL");
const fecha = (iso) => new Date(iso).toLocaleString("es-CL",
  { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });

function el(tag, clase, texto) {
  const e = document.createElement(tag);
  if (clase) e.className = clase;
  if (texto !== undefined) e.textContent = texto;
  return e;
}

function avisar(texto, ok = true) {
  const a = $("aviso");
  a.className = "aviso " + (ok ? "ok" : "mal");
  a.textContent = texto;
}

async function pedir(url, opciones) {
  const r = await fetch(url, opciones);
  let cuerpo = null;
  try { cuerpo = await r.json(); } catch (_) {}
  if (!r.ok) throw new Error((cuerpo && (typeof cuerpo.detail === "string" ? cuerpo.detail
                              : JSON.stringify(cuerpo.detail))) || ("Error " + r.status));
  return cuerpo;
}

let clienteActual = null;

async function cargarClientes() {
  const { clientes } = await pedir("/simulador/clientes");
  const sel = $("cliente");
  sel.replaceChildren();
  for (const c of clientes) {
    const o = el("option", "", c.nombre + " · " + c.rut + (c.creado_en_vivo ? " (creado)" : ""));
    o.value = c.rut;
    sel.append(o);
  }
  let guardado = null;
  try { guardado = localStorage.getItem("panel-cliente"); } catch (_) {}
  if (guardado && clientes.some((c) => c.rut === guardado)) sel.value = guardado;
  await cargarCliente();
}

async function cargarCliente() {
  const rut = $("cliente").value;
  try { localStorage.setItem("panel-cliente", rut); } catch (_) {}
  const [detalle, movs, cred] = await Promise.all([
    pedir("/simulador/clientes/" + encodeURIComponent(rut)),
    pedir("/simulador/clientes/" + encodeURIComponent(rut) + "/movimientos?limite=15"),
    pedir("/simulador/clientes/" + encodeURIComponent(rut) + "/creditos"),
  ]);
  clienteActual = detalle;

  const cuentas = $("cuentas"), sel = $("cuenta");
  cuentas.replaceChildren(); sel.replaceChildren();
  for (const id of detalle.cuentas) {
    const caja = el("div", "cuenta");
    caja.append(el("small", "", id), el("b", "", pesos(detalle.saldos[id])));
    cuentas.append(caja);
    const o = el("option", "", id); o.value = id; sel.append(o);
  }

  const lista = $("movs");
  lista.replaceChildren();
  if (!movs.movimientos.length) lista.append(el("li", "vacio", "Sin movimientos todavía."));
  for (const m of movs.movimientos) {
    const li = el("li");
    const desc = el("div", "desc", m.descripcion);
    if (m.pendiente) desc.append(el("span", "chip pend", "PENDIENTE"));
    if (m.en_vivo) desc.append(el("span", "chip vivo", "EN VIVO"));
    if (m.sin_comercio) desc.append(el("span", "chip sucia", "GLOSA SUCIA"));
    const monto = el("div", "monto" + (m.monto > 0 ? " abono" : ""), pesos(m.monto));
    li.append(desc, monto, el("div", "meta", fecha(m.fecha) + " · " + m.cuenta));
    lista.append(li);
  }
  const pendientes = movs.pendientes;
  $("confirmar").textContent = pendientes ? "Confirmar pendientes (" + pendientes + ")" : "Confirmar pendientes";
  $("confirmar").disabled = !pendientes;

  pintarCreditos(cred.creditos);
}

/** Un crédito por fila, con el botón de pagar una cuota. */
function pintarCreditos(creditos) {
  const lista = $("creditos");
  lista.replaceChildren();
  if (!creditos.length) {
    lista.append(el("li", "vacio", "Este cliente no tiene créditos."));
    return;
  }
  for (const c of creditos) {
    const li = el("li");
    const desc = el("div", "desc", c.productName);
    if (c.arrears) desc.append(el("span", "chip pend", "EN MORA"));
    if (!c.remainingInstallments) desc.append(el("span", "chip vivo", "PAGADO"));
    li.append(desc, el("div", "monto", pesos(-c.currentBalance)));

    const meta = el("div", "meta",
      "cuota " + pesos(c.monthlyInstallment).replace("−", "") +
      " · quedan " + c.remainingInstallments + " de " + c.loanTermMonths);
    if (c.remainingInstallments) {
      const pagar = el("button", "secundario", "Pagar 1 cuota");
      pagar.style.cssText = "margin-left:10px;padding:4px 10px;font-size:12px";
      pagar.addEventListener("click", async () => {
        pagar.disabled = true;
        try {
          await pedir("/simulador/creditos/" + encodeURIComponent(c.loanID) + "/pagar?cuotas=1",
                      { method: "POST" });
          avisar("Cuota pagada en " + c.productName + ". Sincroniza en Velvet para verlo.");
          await cargarCliente();
        } catch (e) { avisar(e.message, true); pagar.disabled = false; }
      });
      meta.append(pagar);
    }
    li.append(meta);
    lista.append(li);
  }
}

$("crear_credito").addEventListener("click", async () => {
  const b = $("crear_credito"); b.disabled = true;
  try {
    const q = new URLSearchParams({ rut: $("cliente").value });
    const producto = $("cr_producto").value.trim();
    if (producto) q.set("producto", producto);
    if ($("cr_cuota").value) q.set("cuota", $("cr_cuota").value);
    if ($("cr_plazo").value) q.set("plazo", $("cr_plazo").value);
    if ($("cr_pagadas").value) q.set("pagadas", $("cr_pagadas").value);
    const r = await pedir("/simulador/clientes/" + encodeURIComponent($("cliente").value) +
                          "/creditos?" + q, { method: "POST" });
    avisar("Crédito creado: " + r.creado.productName + ". Sincroniza en Velvet para verlo.");
    await cargarCliente();
  } catch (e) { avisar(e.message, true); } finally { b.disabled = false; }
});

$("cliente").addEventListener("change", () => { $("aviso").className = "aviso"; cargarCliente(); });
$("sucia").addEventListener("change", (e) => { $("comercio").disabled = e.target.checked; });

$("comprar").addEventListener("click", async () => {
  const b = $("comprar"); b.disabled = true;
  try {
    const q = new URLSearchParams({ rut: $("cliente").value, accountID: $("cuenta").value });
    const comercio = $("comercio").value.trim(), monto = $("monto").value;
    if ($("sucia").checked) q.set("sin_comercio", "true");
    else if (comercio) q.set("comercio", comercio);
    if (monto) q.set("monto", monto);
    if ($("pendiente").checked) q.set("pendiente", "true");
    const r = await pedir("/simulador/nuevo?" + q, { method: "POST" });
    const quien = (r.creado.merchantDetails && r.creado.merchantDetails.name) || r.creado.paymentPurposeCode;
    avisar("Compra creada: " + quien + " por " + pesos(r.creado.amount) +
           (r.pendiente ? " (pendiente)" : "") + ". Ahora toca Sincronizar en la app.");
    // Cada compra parte de cero: que la siguiente no herede "pendiente" sin querer.
    $("monto").value = ""; $("comercio").value = ""; $("comercio").disabled = false;
    $("pendiente").checked = false; $("sucia").checked = false;
    await cargarCliente();
  } catch (e) { avisar(e.message, false); }
  finally { b.disabled = false; }
});

$("confirmar").addEventListener("click", async () => {
  const b = $("confirmar"); b.disabled = true;
  try {
    const r = await pedir("/simulador/avanzar?rut=" + encodeURIComponent($("cliente").value), { method: "POST" });
    avisar(r.confirmados + (r.confirmados === 1 ? " compra confirmada" : " compras confirmadas") +
           " con su monto final. Ahora toca Sincronizar en la app.");
    await cargarCliente();
  } catch (e) { avisar(e.message, false); b.disabled = false; }
});

cargarClientes().catch((e) => avisar("No se pudo cargar el simulador: " + e.message, false));
</script>
</body></html>
"""

# El nombre del banco que es esta EFS (ver banco.py). Se reemplaza aparte y no
# con un f-string porque la página trae mucho JavaScript con llaves.
from html import escape as _escape  # noqa: E402

from app import banco as _banco  # noqa: E402

PANEL_HTML = PANEL_HTML.replace("__BANCO__", _escape(_banco.NOMBRE))
