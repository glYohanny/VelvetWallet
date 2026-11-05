# Simulador de Entidad Financiera — SFA Chile

Banco simulado que implementa la **API de Cuentas** del Sistema de Finanzas Abiertas, conforme al
OpenAPI publicado por la Comisión para el Mercado Financiero.

Existe porque el SFA entra en vigencia en julio de 2027 y no es posible conectarse a instituciones
reales. Construirlo obliga a implementar **los dos lados del estándar**, no solo el del consumidor.

---

## Cómo levantarlo

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001
```

Corre en el **puerto 8001** a propósito: el backend de Velvet Wallet usa el 8000, así que se pueden
levantar los dos al mismo tiempo.

Documentación interactiva generada por FastAPI: `http://localhost:8001/docs`

## Cómo probarlo

```bash
curl http://localhost:8001/health
curl http://localhost:8001/accounts/v1/accounts
curl "http://localhost:8001/accounts/v1/accounts/CTA-0001/transactions?pageSize=3"
curl "http://localhost:8001/accounts/v1/accounts/CTA-0001/transactions?fromDate=2026-09-04"
```

---

## Estructura

```
spec/Accounts.yaml       Especificación oficial descargada del portal de la CMF
app/modelos_sfa.py       Modelos Pydantic GENERADOS desde el spec — no editar a mano
app/generador.py         Inventa 12 meses de historial. Se corre una vez
app/datos_banco.json     Lo que produce el generador — 270 movimientos
app/datos.py             Carga el JSON y define las cuentas
app/main.py              La aplicación: endpoints, paginación y filtros
```

### Regenerar los datos

```bash
python -m app.generador
```

Usa una **semilla fija**, así que siempre produce los mismos 270 movimientos. Los datos son
irregulares a propósito: las cuentas del hogar varían ±20% de monto y ±3 días de fecha, las
suscripciones se corren si caen en fin de semana, y hay movimientos sin comercio ni categoría para
forzar la abstención del clasificador.

## Clientes del banco

La EFS tiene **varios clientes**, cada uno con su RUT, su clave del banco, sus cuentas y su propia
historia (`app/clientes.py`). Los nombres y RUT son ficticios; las claves son de demostración.

| Cliente | RUT | Clave | Perfil | Cuentas |
|---|---|---|---|---|
| Jossue Padrón | 11.111.111-1 | 1234 | profesional (el de siempre: `datos_banco.json`) | CTA-0001, CTA-0002 |
| Camila Rojas | 15.432.876-9 | 2468 | familia: dividendo, colegio, Jumbo, Ripley | CTA-15432876-1/-2 |
| Diego Muñoz | 21.004.567-8 | 1357 | estudiante: pieza, Rappi, Metro, Starbucks | CTA-21004567-1/-2 |

**Cómo se respeta que cada uno vea lo suyo:** al autorizar el consentimiento, el cliente se
identifica con RUT y clave **en la página del banco** (ver más abajo). El token de acceso queda
atado a ese cliente: `/accounts` devuelve solo sus cuentas, y pedir la cuenta de otro responde
**404** (igual que una inexistente, para no revelar nada). Junto al token se entrega un
**refresh token**: el participante lo usa (`POST /token`, `grant_type=refresh_token`) para renovar el
acceso en las sincronizaciones siguientes **sin volver a pedir la clave**.
`DELETE /accounts/v1/consents/{id}` revoca el permiso.

Si una autorización llega sin RUT (versiones anteriores del backend), se atribuye al cliente por
defecto (Jossue). Para exigir siempre el RUT: `SFA_CLIENTE_POR_DEFECTO=""`.

## Dos bancos a la vez

`SFA_BANCO` elige qué banco es esta EFS (`app/banco.py`). Sin la variable es el de siempre.

```bash
uvicorn app.main:app --port 8001                      # Banco Simulado SFA
SFA_BANCO=austral uvicorn app.main:app --port 8002    # Banco Austral
```

Son bancos distintos de verdad, no el mismo con dos nombres: otras cuentas, otros movimientos y su
propio archivo de permisos (`refresh_tokens_austral.json`), para que dos procesos no se pisen.

| Cliente del Banco Austral | RUT | Clave | Qué tiene |
|---|---|---|---|
| Camila Rojas | 15.432.876-9 | 2468 | La tarjeta: compras, Amazon Prime, iCloud y lo que se transfiere desde su cuenta sueldo |
| Diego Muñoz | 21.004.567-8 | 1357 | Lo mismo, con sus gastos |
| Valentina Soto | 17.654.321-3 | 8642 | Solo es clienta de este banco: perfil profesional completo |

Camila y Diego tienen la misma clave en los dos bancos para que la demo sea simple; en la vida real
cada banco tiene la suya.

## Autorización en el sitio del banco (OAuth 2.0 + PAR + PKCE)

El RUT y la clave del usuario **no pasan por Velvet**. Como en el SFA real, el usuario los escribe en
la página de su banco, que la EFS sirve en `/autorizar` (`app/sitio_banco.py`):

```
Velvet (backend)  ──POST /accounts/v1/par──────────▶  EFS   credenciales del participante,
                  ◀── request_uri (vence en 10 min) ──        redirect_uri, state, code_challenge
Navegador ──GET /autorizar?client_id&request_uri──▶  EFS   página de login del banco
          ──POST /autorizar/login (RUT + clave)───▶  EFS   pantalla de consentimiento:
                                                            qué pide, qué cuentas, vencimiento
          ──POST /autorizar/decision──────────────▶  EFS
          ◀── 303 redirect_uri?code&state ─────────        (o ?error=access_denied)
Velvet    ──POST /token  grant_type=authorization_code──▶ EFS   code + code_verifier (PKCE)
          ◀── access_token + refresh_token + cliente ──
```

Qué protege cada pieza:

- **PAR:** los parámetros de la solicitud no viajan en la URL del navegador; los deja el
  participante autenticado, y el navegador solo lleva un `request_uri` opaco.
- **redirect_uri registrada:** el banco solo devuelve el código a las URL inscritas para ese
  participante (`SFA_REDIRECT_URIS`, por defecto `http://localhost:8000/api/conexiones/retorno`).
- **PKCE (S256):** un código interceptado no sirve sin el `code_verifier`, que nunca salió del backend.
- **Código de un solo uso, 2 minutos.** Un intento fallido también lo quema.
- **state:** ata la vuelta a la solicitud que la originó (lo valida el participante).
- **Sesión del banco:** la decisión solo se acepta tras el login en esa misma solicitud (anti-CSRF).

```bash
python -m app.prueba_autorizacion
```

22 comprobaciones: secreto del participante, redirect_uri ajena, PKCE, escape de HTML, solo las
cuentas del cliente en el consentimiento, CSRF, código robado o reusado, rechazo y solicitud vencida.

`POST /accounts/v1/consents/{id}/authorise` con `{rut, clave}` se mantiene para las pruebas y la demo
por línea de comandos; la app ya no lo usa.

### Panel para la demo

Con la EFS corriendo, abre **http://localhost:8001/panel**: eliges el cliente, haces una compra
(comercio y monto, o al azar), la marcas como **pendiente** o con **glosa sucia**, y confirmas las
pendientes con un botón. Muestra los saldos y los últimos movimientos de ese cliente. Después de
cada acción, toca **Sincronizar** en la app. Usa los mismos endpoints `/simulador/*` de abajo.

### Simular un cliente específico

```bash
# Ver los clientes (con su clave de demo)
curl http://localhost:8001/simulador/clientes

# Crear uno nuevo con su propia historia (perfil: profesional | estudiante | familia)
curl -X POST http://localhost:8001/simulador/clientes -H "Content-Type: application/json" \
     -d '{"rut":"17.654.321-3","nombre":"Valentina Soto","clave":"9999","perfil":"estudiante","sueldo":600000,"meses":6}'

# Una compra en vivo para ese cliente (comercio y monto opcionales)
curl -X POST "http://localhost:8001/simulador/nuevo?rut=17.654.321-3&comercio=Rappi&monto=12990"

# Confirmar las compras pendientes solo de un cliente
curl -X POST "http://localhost:8001/simulador/avanzar?rut=15.432.876-9"

# Eliminar un cliente creado en vivo
curl -X DELETE http://localhost:8001/simulador/clientes/17.654.321-3
```

La historia de un cliente creado se genera de forma reproducible (la semilla sale del RUT) y queda
guardada en `app/clientes_creados.json`: sobrevive a un reinicio. Los permisos otorgados quedan en
`app/refresh_tokens.json`. Ninguno de los dos se versiona; borrarlos vuelve a los clientes de base.

### Probar el aislamiento

```bash
python -m app.prueba_clientes
```

23 comprobaciones: cada cliente ve solo lo suyo, un token no lee cuentas ajenas, clave errada → 401,
refresh token del mismo cliente, revocación, cliente creado en vivo y compra en vivo por cliente.

## Endpoints de control — fuera del estándar

No son parte de la API conforme. Existen solo para poder probar la ingesta.

```bash
curl http://localhost:8001/simulador/estado          # qué está pendiente
curl -X POST http://localhost:8001/simulador/avanzar # confirma los pendientes (todos, o ?rut=)
```

Al avanzar, las compras pre-autorizadas toman su monto definitivo **manteniendo el mismo
`transactionID`**. Eso es lo que la ingesta tiene que detectar para actualizar en vez de insertar.
Para volver al estado inicial basta reiniciar el servidor: los datos se cargan del JSON al arrancar.

### Los modelos se generan, no se escriben

```bash
python -m datamodel-code-generator \
  --input spec/Accounts.yaml --input-file-type openapi \
  --output app/modelos_sfa.py --target-python-version 3.11 \
  --use-schema-description --field-constraints
```

Dos razones: evita errores al transcribir 29 estructuras a mano, y permite afirmar que los schemas
**derivan de la especificación oficial**, no de una copia. Si la CMF publica una versión nueva del
spec, se regenera.

---

## Estado

| Implementado | Pendiente |
|---|---|
| Los 6 endpoints de la API de Cuentas | mTLS y certificados |
| Envoltorio `data` / `links` / `meta` obligatorio | Firma JWS (`x-jws-signature`) |
| Paginación `page` / `pageSize` | `private_key_jwt` en vez de client_secret |
| Filtros `fromDate` / `toDate` | |
| Error 404 en cuenta inexistente | |
| Generador de 12 meses de historial | |
| Ciclo de pendiente a confirmada | |
| Varios clientes, cada uno con lo suyo | |
| Login y consentimiento en el sitio del banco (PAR + PKCE) | |
| Refresh token y revocación | |

**El orden es deliberado:** primero que el banco entregue datos, después la seguridad encima. Partir
por mTLS significa pelear con certificados durante días antes de tener una sola línea de JSON.

---

## Hallazgos de la especificación

Dos cosas que salieron al leer el contrato y que afectan el diseño del modelo canónico:

**No existe campo de estado pendiente/confirmada.** El único `status` en las 29 estructuras del spec
está en `Accounts`, no en `Transactions`. Una transición de pendiente a confirmada se manifiesta como
el mismo `transactionID` reapareciendo con otro monto entre sincronizaciones, no como una bandera.

**El banco manda su propia categoría.** `merchantDetails.category` viene con el movimiento, pero es
**opcional** y sin taxonomía común: cada institución inventa la suya. El clasificador entonces no solo
clasifica desde cero, también normaliza taxonomías inconsistentes entre proveedores. En
`app/datos.py` hay movimientos con y sin ese campo justamente para cubrir los dos casos.

**Sobre los montos:** el spec declara `amount` como `number` y así viaja en JSON. Al persistirlo hay
que convertirlo a `Decimal`, nunca dejarlo en `float`.

---

## Pendiente menor

En `/accounts` los campos `firstAvailableDateTime` y `lastAvailableDateTime` se rellenan con la hora
actual, porque las cuentas no tienen fecha de movimiento. Funciona, pero sería más correcto usar
`openingDate`.
