# -*- coding: utf-8 -*-
"""
Entidad Financiera Simulada (EFS) — Sistema de Finanzas Abiertas (Chile)

Finge ser una Institución Proveedora de Cuentas (IPC) participante del SFA.
Implementa la API de Cuentas conforme al OpenAPI publicado por la CMF
(spec/Accounts.yaml), siguiendo el enfoque del Sandbox Tecnológico ATENA: una
EFS contra la cual un participante (p. ej. un PSBI como Velvet Wallet) prueba la
integración, autenticación y consumo de APIs.

Flujo de seguridad simulado (alineado con la guía ATENA):
  1. El participante obtiene un token por Client Credentials  (POST /token)
  2. Solicita un consentimiento con alcance RAR                (POST /consents)
  3. El CLIENTE del banco se identifica (RUT + clave) y autoriza EN EL SITIO
     DEL BANCO: OAuth 2.0 Authorization Code con PAR y PKCE, como FAPI:
       a. el participante empuja la solicitud                   (POST /par)
       b. el usuario es redirigido a la página del banco,
          inicia sesión y aprueba el consentimiento             (GET /autorizar)
       c. el banco vuelve al participante con un código         (redirect_uri?code=...)
       d. el participante canjea el código + PKCE por tokens    (POST /token, authorization_code)
     El participante NUNCA ve la clave del cliente.
  4. Con ese token se leen los datos, SOLO los de ese cliente  (GET /accounts/...)
  5. Las siguientes veces, el participante renueva el acceso con el
     refresh token, sin volver a pedir la clave                (POST /token, grant refresh_token)

(POST /consents/{id}/authorise con RUT y clave sigue existiendo solo para
pruebas automatizadas sin navegador: simula que el cliente ya aprobó.)

La EFS tiene varios clientes (app/clientes.py), cada uno con sus cuentas e
historial. Un token nunca ve cuentas de otro cliente.

Todavía sin mTLS, sin firma JWS y sin DCR: esas capas se agregan después, sobre
algo que ya funciona (igual que en ATENA, donde los certificados son autofirmados).

Levantar con:  uvicorn app.main:app --reload --port 8001
"""
import base64
import hashlib
import json
import os
import random
import secrets
from html import escape
from datetime import date, datetime, timezone, timedelta
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Query, Path, Header, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pathlib import Path as RutaArchivo

from pydantic import BaseModel, Field

from app import banco
from app import clientes as C

# El backend de Velvet Wallet corre en el 8000. La EFS va en el 8001
# para que se puedan levantar los dos a la vez.
BASE = "http://localhost:8001/accounts/v1"

app = FastAPI(
    title="%s — Entidad Financiera Simulada (EFS) del SFA" % banco.NOMBRE,
    version="2.0.0",
    description=(
        "EFS conforme a la API de Cuentas del Sistema de Finanzas Abiertas, "
        "según el enfoque del Sandbox Tecnológico ATENA de la CMF. Simula la "
        "autenticación del participante (Client Credentials), el consentimiento "
        "con alcance RAR y el consumo de datos con token."
    ),
    root_path="",
)

# Permite que la app (que corre en otro puerto, p. ej. 8081 en web) pida datos
# a esta API desde el navegador. En desarrollo se abre a todo; un banco real
# restringiría a los orígenes autorizados.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════════════════
#  Seguridad: token del participante, consentimiento y token de acceso
#
#  Alineado con el "Marco técnico de seguridad" de la guía ATENA:
#    · Client Credentials  → token del participante (prueba de identidad).
#    · Rich Authorization Request (RAR) → alcance del consentimiento.
#    · Token de acceso emitido al autorizar el consentimiento.
#
#  Lo que en ATENA está sobre esto (DCR, firma JWS, mTLS) queda pendiente:
#  se construye encima de un flujo que ya funciona.
# ═══════════════════════════════════════════════════════════════════

# Interruptor: si está en "false", los endpoints NO exigen token (útil para que
# la vista en vivo de la app, que hoy llama sin token, siga funcionando mientras
# no se la apunte al backend). Por defecto EXIGE token.
EXIGIR_TOKEN = os.getenv("SFA_EXIGIR_TOKEN", "true").lower() in ("1", "true", "yes", "si", "sí")

# Credenciales del participante (en ATENA se obtienen al habilitarse; aquí son
# fijas para la demo). El participante es Velvet Wallet, en su rol de PSBI.
CLIENTE_ID = os.getenv("SFA_CLIENTE_ID", "velvet-wallet")
CLIENTE_SECRET = os.getenv("SFA_CLIENTE_SECRET", "secreto-demo")

# Permisos que el estándar define (RAR — Rich Authorization Requests). El
# consentimiento dice a qué datos se accede; el token de acceso hereda ese alcance.
PERMISOS_VALIDOS = {
    "ReadAccountsBasic", "ReadAccountsDetail",
    "ReadBalances",
    "ReadTransactionsBasic", "ReadTransactionsDetail",
    # API de Operaciones de Crédito: alcance propio. Pedir los créditos es
    # pedir datos nuevos, así que requiere su permiso y no viaja de polizón
    # con el de cuentas.
    "ReadLoansBasic", "ReadLoansDetail",
}

# Almacenes en memoria. Se reinician al reiniciar el servidor, igual que los
# datos (que se cargan del JSON al arrancar). No es una base de datos: es una EFS.
PARTICIPANTES: dict[str, dict] = {}     # token de participante -> {expira}
CONSENTIMIENTOS: dict[str, dict] = {}   # consentId -> datos del consentimiento
TOKENS: dict[str, dict] = {}            # token de acceso -> {consentId, expira, permisos, rut}

# Refresh tokens: lo que el participante guarda para renovar el acceso sin pedir
# otra vez la clave al cliente (como en OAuth real). Se persisten en un archivo
# para que sobrevivan a un reinicio de la EFS; si no, cada reinicio obligaría a
# todos los usuarios a volver a vincular su banco.
ARCHIVO_REFRESH = banco.archivo("refresh_tokens.json")
REFRESH: dict[str, dict] = {}           # refresh token -> {client_id, rut, consentId, permisos, expira}

# Cliente al que se atribuye una autorización que llega SIN RUT (compatibilidad
# con versiones anteriores del backend/app). Vacío = exigir siempre el RUT.
CLIENTE_POR_DEFECTO = os.getenv("SFA_CLIENTE_POR_DEFECTO", C.RUT_POR_DEFECTO)


def _cargar_refresh():
    if not ARCHIVO_REFRESH.exists():
        return
    try:
        crudo = json.loads(ARCHIVO_REFRESH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for tok, info in crudo.items():
        info["expira"] = datetime.fromisoformat(info["expira"])
        REFRESH[tok] = info


def _guardar_refresh():
    ARCHIVO_REFRESH.write_text(
        json.dumps({t: {**i, "expira": i["expira"].isoformat()} for t, i in REFRESH.items()},
                   ensure_ascii=False, indent=1),
        encoding="utf-8")


_cargar_refresh()

_bearer = HTTPBearer(auto_error=False)


def exigir_token_participante(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict | None:
    """
    Valida el token del participante (el obtenido por Client Credentials). Es el
    que prueba que quien llama es un participante habilitado. Se exige para crear
    un consentimiento.
    """
    if not EXIGIR_TOKEN:
        return None
    if cred is None or not cred.credentials:
        raise HTTPException(
            status_code=401,
            detail="Falta el token del participante. Obténgalo primero en POST /token (Client Credentials).",
        )
    info = PARTICIPANTES.get(cred.credentials)
    if info is None:
        raise HTTPException(status_code=401, detail="Token de participante inválido o desconocido.")
    if info["expira"] < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="El token del participante expiró. Pida uno nuevo.")
    return info


def exigir_token_acceso(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict | None:
    """
    Valida el token de acceso a datos (el emitido al autorizar el consentimiento).
    Se exige en los endpoints de datos: sin consentimiento autorizado, no hay datos.
    """
    if not EXIGIR_TOKEN:
        return None
    if cred is None or not cred.credentials:
        raise HTTPException(
            status_code=401,
            detail="Falta el token de acceso. Se requiere un consentimiento autorizado (Authorization: Bearer).",
        )
    info = TOKENS.get(cred.credentials)
    if info is None:
        raise HTTPException(status_code=401, detail="Token de acceso inválido o desconocido.")
    if info["expira"] < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="El consentimiento expiró. Debe renovarse.")
    return info


class SolicitudToken(BaseModel):
    """
    Dos usos, como en OAuth:
      · grant_type='client_credentials' → token del participante.
      · grant_type='refresh_token'      → token de acceso nuevo para un cliente
        que ya autorizó antes (sin volver a pedirle la clave).
    """
    grant_type: str = Field("client_credentials",
                            description="'client_credentials', 'authorization_code' o 'refresh_token'.")
    client_id: str = Field(..., description="Identificador del participante.")
    client_secret: str = Field(..., description="Secreto del participante.")
    refresh_token: str | None = Field(None, description="Solo con grant_type='refresh_token'.")
    code: str | None = Field(None, description="Solo con 'authorization_code': el código recibido.")
    redirect_uri: str | None = Field(None, description="Solo con 'authorization_code': el mismo del PAR.")
    code_verifier: str | None = Field(None, description="Solo con 'authorization_code': PKCE.")
    scope: str | None = None


class SolicitudAutorizacion(BaseModel):
    """
    Lo que el CLIENTE del banco ingresa al aprobar: su RUT y su clave del banco.
    En el SFA real esto ocurre en el sitio del banco (redirección) y el
    participante nunca ve la clave; aquí se simula con esta llamada.
    """
    rut: str | None = Field(None, description="RUT del cliente, p. ej. '15.432.876-9'.")
    clave: str | None = Field(None, description="Clave del cliente en el banco.")


class NuevoCliente(BaseModel):
    """Cliente que se crea en vivo para una simulación específica."""
    rut: str = Field(..., description="RUT válido (con dígito verificador).")
    nombre: str = Field(..., min_length=2, max_length=80)
    clave: str = Field("1234", min_length=4, max_length=20)
    perfil: str = Field("profesional", description="profesional | estudiante | familia")
    sueldo: int | None = Field(None, ge=100_000, le=20_000_000,
                               description="Opcional: reemplaza el sueldo del perfil.")
    # Tope 12: la app pide hasta 500 movimientos, y una familia genera ~32 al mes.
    meses: int = Field(12, ge=1, le=12, description="Meses de historial a generar (1 a 12).")


class SolicitudConsentimiento(BaseModel):
    """Lo que la app pide: a qué datos quiere acceder y hasta cuándo (RAR)."""
    permissions: list[str] = Field(
        default_factory=lambda: ["ReadAccountsBasic", "ReadBalances", "ReadTransactionsDetail"],
        description="Permisos solicitados (RAR — Rich Authorization Request).",
    )
    expirationDateTime: datetime | None = Field(
        None, description="Hasta cuándo rige el consentimiento. Por defecto, 90 días."
    )


# ───────────────────────── utilidades ─────────────────────────
def paginar(items, page, page_size, ruta, extra=None):
    """
    Corta la lista en páginas y arma los bloques 'links' y 'meta' que el
    estándar exige en toda respuesta.
    """
    total = len(items)
    total_pages = max(1, -(-total // page_size))  # división hacia arriba
    ini = (page - 1) * page_size
    trozo = items[ini:ini + page_size]

    def url(p):
        q = dict(extra or {})
        q.update({"page": p, "pageSize": page_size})
        return "%s%s?%s" % (BASE, ruta, urlencode(q))

    links = {"self": url(page), "first": url(1), "last": url(total_pages)}
    if page > 1:
        links["prev"] = url(page - 1)
    if page < total_pages:
        links["next"] = url(page + 1)

    fechas = [i["bookingDateTime"] for i in items if "bookingDateTime" in i]
    meta = {
        "firstAvailableDateTime": min(fechas) if fechas else datetime.now().astimezone(),
        "lastAvailableDateTime": max(fechas) if fechas else datetime.now().astimezone(),
        "totalPages": total_pages,
    }
    return trozo, links, meta


def sin_internos(movimiento):
    """
    Quita los campos que empiezan con guion bajo antes de responder.

    '_pendiente' y '_monto_final' son información interna de la EFS: un banco
    real sabe que una transacción está pendiente, pero esta API no tiene campo
    para decirlo. Si los enviáramos, dejaríamos de ser conformes.
    """
    return {k: v for k, v in movimiento.items() if not k.startswith("_")}


def cliente_del_acceso(acceso: dict | None) -> dict:
    """
    El cliente dueño del token de acceso. Si la EFS no exige token (modo
    abierto), se usa el cliente por defecto.
    """
    rut = (acceso or {}).get("rut") or C.RUT_POR_DEFECTO
    cliente = C.CLIENTES.get(rut)
    if cliente is None:
        # El cliente fue eliminado después de emitir el token.
        raise HTTPException(status_code=401, detail="El cliente de este consentimiento ya no existe.")
    return cliente


def cuenta_o_404(account_id, cliente):
    """
    La cuenta, SOLO si es del cliente del token. Una cuenta de otro cliente
    responde 404 igual que una inexistente: así no se filtra ni que existe.
    """
    c = next((c for c in cliente["cuentas"] if c["accountId"] == account_id), None)
    if c is None:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    return c


def ocurridos(movs):
    """
    Solo lo que ya pasó. El historial llega hasta fin del mes en curso, pero un
    banco no informa movimientos futuros: el sueldo del 30 aparece el 30.
    """
    ahora = datetime.now(timezone.utc)
    return [m for m in movs if m["bookingDateTime"] <= ahora]


def saldo_de(cliente, account_id):
    """Saldo calculado en vivo: abonos menos cargos (cuadra con /simulador/nuevo)."""
    total = 0.0
    for m in ocurridos(cliente["movimientos"].get(account_id, [])):
        total += m["amount"] if m["transactionsType"] == "Abono" else -m["amount"]
    return {"amount": float(round(total)), "currency": "CLP", "type": "Disponible"}


def _emitir_acceso(consent_id: str, rut: str, permisos: list[str], expira) -> dict:
    """Token de acceso atado al consentimiento y al cliente."""
    token = secrets.token_urlsafe(32)
    TOKENS[token] = {"consentId": consent_id, "expira": expira,
                     "permisos": permisos, "rut": rut}
    segundos = max(0, int((expira - datetime.now(timezone.utc)).total_seconds()))
    return {"access_token": token, "token_type": "Bearer", "expires_in": segundos}


# ───────────────────────── operación ─────────────────────────
@app.get("/health", tags=["Operación"], summary="Comprobación de vida")
def health():
    return {"ok": True, "servicio": "efs-sfa", "clientes": len(C.CLIENTES),
            "cuentas": len(C.DUENO_CUENTA), "exige_token": EXIGIR_TOKEN}


# ───────────────────────── autenticación del participante ─────────────────────────
@app.post("/accounts/v1/token", tags=["Autenticación"],
          summary="0) Token del participante (Client Credentials)")
def emitir_token_participante(sol: SolicitudToken):
    """
    Paso 1 de la guía ATENA ('Crear Token del Participante'). El participante se
    autentica con su client_id/client_secret y recibe un access_token que prueba
    su identidad. Con él puede, luego, solicitar consentimientos.

    (En OAuth real este endpoint recibe los datos como formulario y vive en el
    servidor de autorización; aquí se simplifica a JSON para poder probarlo.)
    """
    if sol.grant_type not in ("client_credentials", "authorization_code", "refresh_token"):
        raise HTTPException(status_code=400, detail="grant_type no soportado (unsupported_grant_type).")
    if sol.client_id != CLIENTE_ID or sol.client_secret != CLIENTE_SECRET:
        raise HTTPException(status_code=401, detail="Credenciales de participante inválidas (invalid_client).")

    if sol.grant_type == "authorization_code":
        return _canjear_codigo(sol)

    if sol.grant_type == "refresh_token":
        # Renovar el acceso de un cliente que ya autorizó: sin pedirle la clave.
        info = REFRESH.get(sol.refresh_token or "")
        if info is None or info["client_id"] != sol.client_id:
            raise HTTPException(status_code=401, detail="refresh_token inválido (invalid_grant).")
        if info["expira"] < datetime.now(timezone.utc):
            REFRESH.pop(sol.refresh_token, None)
            _guardar_refresh()
            raise HTTPException(status_code=401,
                                detail="El consentimiento expiró: el cliente debe autorizar de nuevo.")
        if info["rut"] not in C.CLIENTES:
            raise HTTPException(status_code=401, detail="El cliente de este consentimiento ya no existe.")
        acceso = _emitir_acceso(info["consentId"], info["rut"], info["permisos"], info["expira"])
        cliente = C.CLIENTES[info["rut"]]
        return {**acceso, "consentId": info["consentId"],
                "scope": " ".join(info["permisos"]),
                "cliente": {"rut": cliente["rut"], "nombre": cliente["nombre"]}}

    token = secrets.token_urlsafe(32)
    expira = datetime.now(timezone.utc) + timedelta(hours=1)
    PARTICIPANTES[token] = {"expira": expira, "client_id": sol.client_id}
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": sol.scope or "accounts",
    }


# ───────────────────────── consentimiento ─────────────────────────
@app.post("/accounts/v1/consents", tags=["Consentimiento"],
          summary="1) Solicitar consentimiento (requiere token de participante)")
def crear_consentimiento(sol: SolicitudConsentimiento,
                         _participante: dict | None = Depends(exigir_token_participante)):
    """
    La app (ya identificada con su token de participante) declara a qué datos
    quiere acceder (RAR). La EFS registra la solicitud como 'AwaitingAuthorisation'
    (esperando que el usuario la apruebe).
    """
    invalidos = [p for p in sol.permissions if p not in PERMISOS_VALIDOS]
    if invalidos:
        raise HTTPException(status_code=422, detail="Permisos no reconocidos: %s" % invalidos)

    consent_id = "urn:velvet:consent:" + secrets.token_hex(8)
    ahora = datetime.now(timezone.utc)
    expira = sol.expirationDateTime or (ahora + timedelta(days=90))
    CONSENTIMIENTOS[consent_id] = {
        "consentId": consent_id,
        "status": "AwaitingAuthorisation",
        "permissions": sol.permissions,
        "creationDateTime": ahora,
        "expirationDateTime": expira,
    }
    _, links, meta = paginar([], 1, 1, "/consents")
    links["self"] = "%s/consents/%s" % (BASE, consent_id)
    return {"data": CONSENTIMIENTOS[consent_id], "links": links, "meta": meta}


@app.post("/accounts/v1/consents/{consentId}/authorise", tags=["Consentimiento"],
          summary="2) El cliente se identifica (RUT + clave), aprueba y se emite el token")
def autorizar_consentimiento(consentId: str = Path(...),
                             sol: SolicitudAutorizacion | None = None,
                             participante: dict | None = Depends(exigir_token_participante)):
    """
    Representa el momento en que el cliente entra a su banco y aprueba el acceso.
    En el SFA real esto es un login + redirección (flujo de autorización); aquí
    es una llamada con su RUT y su clave.

    El token de acceso que se emite queda atado a ESE cliente: con él solo se ven
    sus cuentas. Además se entrega un refresh token, para que el participante
    renueve el acceso más adelante sin pedirle de nuevo la clave.
    """
    c = CONSENTIMIENTOS.get(consentId)
    if c is None:
        raise HTTPException(status_code=404, detail="Consentimiento no encontrado.")
    if c["status"] == "Revoked":
        raise HTTPException(status_code=409, detail="El consentimiento fue revocado.")

    rut = (sol.rut if sol else None)
    if rut:
        cliente = C.cliente_por_rut(rut)
        # Mismo mensaje para RUT inexistente y clave errada: no revelar quién es cliente.
        if cliente is None or (sol.clave or "") != cliente["clave"]:
            raise HTTPException(status_code=401, detail="RUT o clave incorrectos.")
    elif CLIENTE_POR_DEFECTO:
        cliente = C.CLIENTES[C.normalizar_rut(CLIENTE_POR_DEFECTO)]
    else:
        raise HTTPException(status_code=400,
                            detail="Falta identificar al cliente: envíe su RUT y clave.")

    rut_n = cliente["rut_normalizado"]
    c["status"] = "Authorised"
    c["rut"] = cliente["rut"]
    expira = c["expirationDateTime"]
    acceso = _emitir_acceso(consentId, rut_n, c["permissions"], expira)

    refresh = secrets.token_urlsafe(32)
    REFRESH[refresh] = {"client_id": (participante or {}).get("client_id", CLIENTE_ID),
                        "rut": rut_n, "consentId": consentId,
                        "permisos": c["permissions"], "expira": expira}
    _guardar_refresh()

    return {
        **acceso,
        "refresh_token": refresh,
        "consentId": consentId,
        "scope": " ".join(c["permissions"]),
        "cliente": {"rut": cliente["rut"], "nombre": cliente["nombre"]},
    }


@app.delete("/accounts/v1/consents/{consentId}", tags=["Consentimiento"],
            summary="Revocar un consentimiento")
def revocar_consentimiento(consentId: str = Path(...)):
    """
    El cliente retira el permiso. Los tokens de acceso y de renovación de ese
    consentimiento dejan de servir de inmediato.
    """
    c = CONSENTIMIENTOS.get(consentId)
    if c is not None:
        c["status"] = "Revoked"
    for t in [t for t, i in TOKENS.items() if i["consentId"] == consentId]:
        del TOKENS[t]
    for r in [r for r, i in REFRESH.items() if i["consentId"] == consentId]:
        del REFRESH[r]
    _guardar_refresh()
    return {"consentId": consentId, "status": "Revoked"}


@app.get("/accounts/v1/consents/{consentId}", tags=["Consentimiento"],
         summary="Estado de un consentimiento")
def ver_consentimiento(consentId: str = Path(...)):
    c = CONSENTIMIENTOS.get(consentId)
    if c is None:
        raise HTTPException(status_code=404, detail="Consentimiento no encontrado.")
    return {"data": c, "links": {"self": "%s/consents/%s" % (BASE, consentId)}, "meta": {}}


# ═══════════════════════════════════════════════════════════════════
#  Autorización en el SITIO DEL BANCO (OAuth 2.0 + PAR + PKCE, como FAPI)
#
#  El cliente escribe su RUT y su clave en una página DEL BANCO, nunca en la
#  app del participante. El participante solo recibe un código de un solo uso,
#  que canjea (con PKCE) por los tokens.
# ═══════════════════════════════════════════════════════════════════
from app import sitio_banco  # noqa: E402  (páginas HTML del banco)

# Participantes registrados en la EFS. En ATENA esto sale del registro del
# participante (DCR): su nombre visible y las URL a las que se le puede volver.
PARTICIPANTES_REGISTRADOS = {
    CLIENTE_ID: {
        "nombre": "Velvet Wallet",
        "redirect_uris": [u.strip() for u in os.getenv(
            "SFA_REDIRECT_URIS", "http://localhost:8000/api/conexiones/retorno").split(",") if u.strip()],
    },
}

PAR_VIGENCIA = timedelta(minutes=10)     # tiempo para iniciar sesión y decidir
CODIGO_VIGENCIA = timedelta(minutes=2)   # el código se canjea al tiro

SOLICITUDES_PAR: dict[str, dict] = {}    # request_uri -> solicitud pendiente
CODIGOS: dict[str, dict] = {}            # código de autorización -> datos (un solo uso)
# Solicitudes ya respondidas: si el navegador reenvía la decisión (doble clic,
# botón Atrás), se muestra que ya está lista en vez de un error.
RESUELTAS: dict[str, dict] = {}          # request_uri -> {"autorizo": bool, "expira": datetime}

NOMBRE_PERMISO = {
    "ReadLoansBasic": "Ver tus créditos",
    "ReadLoansDetail": "Ver el detalle de tus créditos",
    "ReadAccountsBasic": "Ver tus cuentas",
    "ReadAccountsDetail": "Ver el detalle de tus cuentas",
    "ReadBalances": "Ver tus saldos",
    "ReadTransactionsBasic": "Ver tus movimientos",
    "ReadTransactionsDetail": "Ver el detalle de tus movimientos",
}


class SolicitudPAR(BaseModel):
    """
    Pushed Authorization Request: el participante (no el navegador) deja la
    solicitud en el banco, autenticado con sus credenciales. Así los parámetros
    no viajan expuestos en la URL y no se pueden manipular.
    """
    client_id: str
    client_secret: str
    redirect_uri: str = Field(..., description="Debe estar registrada para el participante.")
    state: str = Field(..., min_length=8, description="Valor opaco que el banco devuelve tal cual.")
    code_challenge: str = Field(..., min_length=43, description="PKCE: BASE64URL(SHA256(code_verifier)).")
    code_challenge_method: str = Field("S256", description="Solo S256.")
    permissions: list[str] = Field(
        default_factory=lambda: ["ReadAccountsBasic", "ReadBalances", "ReadTransactionsDetail"],
        description="Alcance pedido (RAR).")


def _pkce_valido(verifier: str | None, challenge: str) -> bool:
    if not verifier or not (43 <= len(verifier) <= 128):
        return False
    calculado = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return secrets.compare_digest(calculado, challenge)


def _solicitud_vigente(request_uri: str) -> dict | None:
    sol = SOLICITUDES_PAR.get(request_uri or "")
    if sol is None:
        return None
    if sol["expira"] < datetime.now(timezone.utc):
        SOLICITUDES_PAR.pop(request_uri, None)
        return None
    return sol


async def _formulario(request: Request) -> dict[str, str]:
    """Lee un formulario HTML (x-www-form-urlencoded) sin depender de python-multipart."""
    from urllib.parse import parse_qs
    cuerpo = (await request.body()).decode("utf-8", errors="replace")
    return {k: v[0] for k, v in parse_qs(cuerpo, keep_blank_values=True).items()}


def _volver(sol: dict, **params) -> RedirectResponse:
    """Redirige el navegador al participante (303: el navegador hace GET)."""
    sep = "&" if "?" in sol["redirect_uri"] else "?"
    return RedirectResponse(sol["redirect_uri"] + sep + urlencode({**params, "state": sol["state"]}),
                            status_code=303)


@app.post("/accounts/v1/par", tags=["Autorización en el banco (OAuth)"], status_code=201,
          summary="1) Solicitud de autorización (PAR), la hace el participante")
def solicitud_par(sol: SolicitudPAR):
    """
    El participante deja la solicitud de autorización en el banco: quién es, a
    qué datos pide acceso (RAR), a dónde volver y el desafío PKCE. Recibe un
    `request_uri` para mandar al usuario a la página del banco.
    """
    if sol.client_id != CLIENTE_ID or sol.client_secret != CLIENTE_SECRET:
        raise HTTPException(status_code=401, detail="Credenciales de participante inválidas (invalid_client).")
    registro = PARTICIPANTES_REGISTRADOS[sol.client_id]
    if sol.redirect_uri not in registro["redirect_uris"]:
        raise HTTPException(status_code=400, detail="redirect_uri no registrada para el participante.")
    if sol.code_challenge_method != "S256":
        raise HTTPException(status_code=400, detail="PKCE obligatorio con code_challenge_method=S256.")
    invalidos = [p for p in sol.permissions if p not in PERMISOS_VALIDOS]
    if invalidos:
        raise HTTPException(status_code=422, detail="Permisos no reconocidos: %s" % invalidos)

    ahora = datetime.now(timezone.utc)
    consent_id = "urn:velvet:consent:" + secrets.token_hex(8)
    CONSENTIMIENTOS[consent_id] = {
        "consentId": consent_id,
        "status": "AwaitingAuthorisation",
        "permissions": sol.permissions,
        "creationDateTime": ahora,
        "expirationDateTime": ahora + timedelta(days=90),
    }
    request_uri = "urn:ietf:params:oauth:request_uri:" + secrets.token_urlsafe(24)
    SOLICITUDES_PAR[request_uri] = {
        "client_id": sol.client_id,
        "redirect_uri": sol.redirect_uri,
        "state": sol.state,
        "code_challenge": sol.code_challenge,
        "permisos": sol.permissions,
        "consentId": consent_id,
        "expira": ahora + PAR_VIGENCIA,
        "rut": None,          # se llena cuando el cliente inicia sesión en el banco
        "sesion": None,       # ata la decisión al login (protege contra CSRF)
    }
    return {"request_uri": request_uri, "expires_in": int(PAR_VIGENCIA.total_seconds())}


@app.get("/autorizar", response_class=HTMLResponse, tags=["Autorización en el banco (OAuth)"],
         summary="2) Página del banco: el cliente inicia sesión")
def pagina_autorizar(request_uri: str = Query(...), client_id: str = Query(...)):
    sol = _solicitud_vigente(request_uri)
    if sol is None or sol["client_id"] != client_id:
        return HTMLResponse(sitio_banco.pagina_error(
            "Esta solicitud expiró o no es válida. Vuelve a la aplicación e inténtalo de nuevo."),
            status_code=400)
    return sitio_banco.pagina_login(request_uri, PARTICIPANTES_REGISTRADOS[client_id]["nombre"])


@app.post("/autorizar/login", response_class=HTMLResponse, include_in_schema=False)
async def autorizar_login(request: Request):
    f = await _formulario(request)
    sol = _solicitud_vigente(f.get("request_uri", ""))
    if sol is None:
        return HTMLResponse(sitio_banco.pagina_error(
            "Esta solicitud expiró. Vuelve a la aplicación e inténtalo de nuevo."), status_code=400)
    participante = PARTICIPANTES_REGISTRADOS[sol["client_id"]]["nombre"]

    cliente = C.cliente_por_rut(f.get("rut", ""))
    if cliente is None or f.get("clave", "") != cliente["clave"]:
        return HTMLResponse(sitio_banco.pagina_login(
            f["request_uri"], participante, error="RUT o clave incorrectos.", rut=f.get("rut", "")),
            status_code=401)

    sol["rut"] = cliente["rut_normalizado"]
    sol["sesion"] = secrets.token_urlsafe(16)
    expira = CONSENTIMIENTOS[sol["consentId"]]["expirationDateTime"]
    return sitio_banco.pagina_consentimiento(
        request_uri=f["request_uri"], sesion=sol["sesion"], participante=participante,
        nombre_cliente=cliente["nombre"],
        permisos=[NOMBRE_PERMISO.get(p, p) for p in sol["permisos"]],
        cuentas=[(c["accountType"], c["accountId"]) for c in cliente["cuentas"]],
        vence=expira.strftime("%d-%m-%Y"))


@app.post("/autorizar/decision", include_in_schema=False)
async def autorizar_decision(request: Request):
    f = await _formulario(request)
    sol = _solicitud_vigente(f.get("request_uri", ""))
    if sol is None:
        hecha = RESUELTAS.get(f.get("request_uri", ""))
        if hecha and hecha["expira"] > datetime.now(timezone.utc):
            # Reenvío de una decisión ya tomada: no se repite nada.
            return HTMLResponse(sitio_banco.pagina_lista(hecha["autorizo"]))
    if sol is None or not sol["sesion"] or not secrets.compare_digest(sol["sesion"], f.get("sesion", "")):
        return HTMLResponse(sitio_banco.pagina_error(
            "La sesión del banco no es válida o expiró. Vuelve a la aplicación e inténtalo de nuevo."),
            status_code=400)
    SOLICITUDES_PAR.pop(f["request_uri"], None)   # la solicitud se usa una sola vez
    ahora = datetime.now(timezone.utc)
    for r in [r for r, v in RESUELTAS.items() if v["expira"] < ahora]:
        del RESUELTAS[r]
    RESUELTAS[f["request_uri"]] = {"autorizo": f.get("decision") == "autorizar",
                                   "expira": ahora + PAR_VIGENCIA}
    consentimiento = CONSENTIMIENTOS[sol["consentId"]]

    if f.get("decision") != "autorizar":
        consentimiento["status"] = "Rejected"
        return _volver(sol, error="access_denied",
                       error_description="El cliente rechazó la solicitud")

    consentimiento["status"] = "Authorised"
    consentimiento["rut"] = C.CLIENTES[sol["rut"]]["rut"]
    codigo = secrets.token_urlsafe(32)
    CODIGOS[codigo] = {
        "client_id": sol["client_id"],
        "redirect_uri": sol["redirect_uri"],
        "code_challenge": sol["code_challenge"],
        "rut": sol["rut"],
        "consentId": sol["consentId"],
        "permisos": sol["permisos"],
        "expira": datetime.now(timezone.utc) + CODIGO_VIGENCIA,
    }
    return _volver(sol, code=codigo)


def _canjear_codigo(sol: "SolicitudToken") -> dict:
    """
    4) El participante canjea el código por los tokens. El código es de UN solo
    uso, expira en 2 minutos, y exige el code_verifier de PKCE: si alguien roba
    el código en el camino, sin el verifier no le sirve.
    """
    info = CODIGOS.pop(sol.code or "", None)
    if info is None or info["client_id"] != sol.client_id:
        raise HTTPException(status_code=400, detail="Código inválido o ya usado (invalid_grant).")
    if info["expira"] < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="El código expiró (invalid_grant).")
    if sol.redirect_uri != info["redirect_uri"]:
        raise HTTPException(status_code=400, detail="redirect_uri no coincide (invalid_grant).")
    if not _pkce_valido(sol.code_verifier, info["code_challenge"]):
        raise HTTPException(status_code=400, detail="PKCE inválido: code_verifier no corresponde (invalid_grant).")

    consentimiento = CONSENTIMIENTOS[info["consentId"]]
    expira = consentimiento["expirationDateTime"]
    acceso = _emitir_acceso(info["consentId"], info["rut"], info["permisos"], expira)
    refresh = secrets.token_urlsafe(32)
    REFRESH[refresh] = {"client_id": sol.client_id, "rut": info["rut"],
                        "consentId": info["consentId"], "permisos": info["permisos"], "expira": expira}
    _guardar_refresh()
    cliente = C.CLIENTES[info["rut"]]
    return {
        **acceso,
        "refresh_token": refresh,
        "consentId": info["consentId"],
        "scope": " ".join(info["permisos"]),
        # Equivalente a los datos del id_token de OpenID Connect: quién autorizó.
        "cliente": {"rut": cliente["rut"], "nombre": cliente["nombre"]},
    }


# ───────────────────────── cuentas (protegidas por token de acceso) ─────────────────────────
@app.get("/accounts/v1/accounts", tags=["Cuentas"],
         summary="Listado de cuentas del cliente")
def listar_cuentas(
    page: int = Query(1, ge=1),
    pageSize: int = Query(25, ge=1, le=100),
    x_fapi_interaction_id: str | None = Header(None, alias="x-fapi-interaction-id"),
    _acceso: dict | None = Depends(exigir_token_acceso),
):
    cliente = cliente_del_acceso(_acceso)
    datos, links, meta = paginar(cliente["cuentas"], page, pageSize, "/accounts")
    return {"data": {"accounts": datos}, "links": links, "meta": meta}


@app.get("/accounts/v1/accounts/{accountID}", tags=["Cuentas"],
         summary="Detalle de una cuenta")
def detalle_cuenta(accountID: str = Path(...),
                   _acceso: dict | None = Depends(exigir_token_acceso)):
    c = cuenta_o_404(accountID, cliente_del_acceso(_acceso))
    _, links, meta = paginar([c], 1, 1, "/accounts/%s" % accountID)
    return {"data": {"account": c}, "links": links, "meta": meta}


@app.get("/accounts/v1/accounts/{accountID}/balance", tags=["Cuentas"],
         summary="Saldos de la cuenta")
def saldo_cuenta(accountID: str = Path(...),
                 _acceso: dict | None = Depends(exigir_token_acceso)):
    cliente = cliente_del_acceso(_acceso)
    cuenta_o_404(accountID, cliente)
    s = saldo_de(cliente, accountID)
    _, links, meta = paginar([], 1, 1, "/accounts/%s/balance" % accountID)
    return {"data": {"balance": s}, "links": links, "meta": meta}


@app.get("/accounts/v1/accounts/{accountID}/transactions", tags=["Cuentas"],
         summary="Movimientos de la cuenta")
def movimientos_cuenta(
    accountID: str = Path(...),
    page: int = Query(1, ge=1),
    pageSize: int = Query(25, ge=1, le=100),
    fromDate: date | None = Query(None, description="Filtra desde esta fecha"),
    toDate: date | None = Query(None, description="Filtra hasta esta fecha"),
    _acceso: dict | None = Depends(exigir_token_acceso),
):
    cliente = cliente_del_acceso(_acceso)
    cuenta_o_404(accountID, cliente)
    movs = ocurridos(cliente["movimientos"].get(accountID, []))

    # Filtro por fecha: esto es lo que permite la sincronización incremental,
    # pedir solo lo nuevo desde la última consulta.
    if fromDate:
        movs = [m for m in movs if m["bookingDateTime"].date() >= fromDate]
    if toDate:
        movs = [m for m in movs if m["bookingDateTime"].date() <= toDate]

    movs.sort(key=lambda m: m["bookingDateTime"], reverse=True)

    extra = {}
    if fromDate:
        extra["fromDate"] = fromDate.isoformat()
    if toDate:
        extra["toDate"] = toDate.isoformat()

    datos, links, meta = paginar(
        movs, page, pageSize, "/accounts/%s/transactions" % accountID, extra)
    return {
        "data": {"transactions": [sin_internos(m) for m in datos]},
        "links": links,
        "meta": meta,
    }


# Los dos endpoints de sobregiro existen en el estándar pero no los usamos:
# se declaran para que la EFS sea completa, devolviendo vacío.
@app.get("/accounts/v1/accounts/{accountID}/overdraft", tags=["Cuentas"],
         summary="Movimientos de sobregiro")
def sobregiro(accountID: str = Path(...),
              _acceso: dict | None = Depends(exigir_token_acceso)):
    cuenta_o_404(accountID, cliente_del_acceso(_acceso))
    _, links, meta = paginar([], 1, 1, "/accounts/%s/overdraft" % accountID)
    return {"data": {"overdraft": []}, "links": links, "meta": meta}


@app.get("/accounts/v1/accounts/{accountID}/current-overdraft-limit",
         tags=["Cuentas"], summary="Límite de sobregiro vigente")
def limite_sobregiro(accountID: str = Path(...),
                     _acceso: dict | None = Depends(exigir_token_acceso)):
    cuenta_o_404(accountID, cliente_del_acceso(_acceso))
    _, links, meta = paginar([], 1, 1,
                             "/accounts/%s/current-overdraft-limit" % accountID)
    return {"data": {"currentOverdraftLimit": []}, "links": links, "meta": meta}


# ═══════════════════════════════════════════════════════════════════
#  API de Operaciones de Crédito
#
#  Segunda familia de APIs del estándar, aparte de la de Cuentas. Los campos
#  salen del OpenAPI "Operaciones de Crédito" publicado por la CMF, verificado
#  el 26-08-2026.
#
#  Lo que el estándar NO define, y por eso acá tampoco está: CAE, cuotas
#  pagadas con su desglose de capital e interés, y la tabla de amortización
#  (solo se entrega un enlace al calendario del proveedor). Inventar esos
#  campos haría que el consumidor se construyera contra una API que no existe.
# ═══════════════════════════════════════════════════════════════════
def credito_o_404(loan_id: str, cliente: dict) -> dict:
    """
    El crédito, SOLO si es del cliente del token. El de otro responde 404
    igual que uno inexistente: no se filtra ni que existe.
    """
    c = next((c for c in cliente.get("creditos", []) if c["loanID"] == loan_id), None)
    if c is None:
        raise HTTPException(status_code=404, detail="Crédito no encontrado")
    return c


@app.get("/accounts/v1/loans", tags=["Operaciones de Crédito"],
         summary="Listado de créditos del cliente")
def listar_creditos(
    page: int = Query(1, ge=1),
    pageSize: int = Query(25, ge=1, le=100),
    x_fapi_interaction_id: str | None = Header(None, alias="x-fapi-interaction-id"),
    _acceso: dict | None = Depends(exigir_token_acceso),
):
    cliente = cliente_del_acceso(_acceso)
    datos, links, meta = paginar(cliente.get("creditos", []), page, pageSize, "/loans")
    return {"data": {"loans": datos}, "links": links, "meta": meta}


@app.get("/accounts/v1/loans/{loanID}", tags=["Operaciones de Crédito"],
         summary="Detalle de un crédito")
def detalle_credito(loanID: str = Path(...),
                    _acceso: dict | None = Depends(exigir_token_acceso)):
    c = credito_o_404(loanID, cliente_del_acceso(_acceso))
    _, links, meta = paginar([c], 1, 1, "/loans/%s" % loanID)
    return {"data": {"loan": c}, "links": links, "meta": meta}


@app.get("/accounts/v1/loans/{loanID}/balance", tags=["Operaciones de Crédito"],
         summary="Saldo del crédito")
def saldo_credito(loanID: str = Path(...),
                  _acceso: dict | None = Depends(exigir_token_acceso)):
    c = credito_o_404(loanID, cliente_del_acceso(_acceso))
    saldo = {
        "loanID": c["loanID"],
        "currentBalance": c["currentBalance"],
        "endOfMonthBalance": c["currentBalance"],
        "currency": c["currency"],
        "remainingInstallments": c["remainingInstallments"],
        "arrears": c["arrears"],
    }
    _, links, meta = paginar([], 1, 1, "/loans/%s/balance" % loanID)
    return {"data": {"balance": saldo}, "links": links, "meta": meta}


@app.get("/accounts/v1/loans/{loanID}/current-transactions",
         tags=["Operaciones de Crédito"], summary="Pagos del crédito en el periodo")
def pagos_credito(loanID: str = Path(...),
                  _acceso: dict | None = Depends(exigir_token_acceso)):
    """
    Pagos del periodo en curso.

    Va vacío a propósito: en este simulador las cuotas se ven como cargos en
    la cuenta corriente, que es donde el usuario las paga. Duplicarlas acá
    haría que el mismo gasto se contara dos veces al sumar el mes.
    """
    credito_o_404(loanID, cliente_del_acceso(_acceso))
    _, links, meta = paginar([], 1, 1, "/loans/%s/current-transactions" % loanID)
    return {"data": {"transactions": []}, "links": links, "meta": meta}


# ═══════════════════════════════════════════════════════════════════
#  Control de la EFS
#
#  Estos endpoints NO son parte del estándar. Van bajo otro prefijo
#  justamente para dejarlo claro: un banco real no tiene un botón para
#  adelantar el tiempo ni para inventar clientes. Existen solo para poder
#  armar y probar escenarios: varios clientes, compras en vivo y movimientos
#  que cambian de monto entre sincronizaciones.
# ═══════════════════════════════════════════════════════════════════
def _cliente_o_404(rut: str) -> dict:
    cliente = C.cliente_por_rut(rut)
    if cliente is None:
        raise HTTPException(status_code=404, detail="No hay un cliente con RUT %s" % rut)
    return cliente


def _clientes_objetivo(rut: str | None) -> list[dict]:
    """Un cliente (si se pide RUT) o todos."""
    return [_cliente_o_404(rut)] if rut else list(C.CLIENTES.values())


# ───────────────────────── clientes ─────────────────────────
@app.get("/simulador/clientes", tags=["Simulador"],
         summary="Clientes del banco (RUT, clave de demo, cuentas)")
def listar_clientes():
    """
    Los clientes que existen en la EFS, con su clave de demostración, para saber
    qué RUT y clave ingresar al vincular el banco desde la app.
    """
    return {"clientes": [C.resumen(c) for c in C.CLIENTES.values()],
            "perfiles": list(C.PERFILES)}


@app.get("/simulador/clientes/{rut}", tags=["Simulador"],
         summary="Detalle de un cliente: cuentas y saldos")
def detalle_cliente(rut: str = Path(...)):
    cliente = _cliente_o_404(rut)
    return {
        **C.resumen(cliente),
        "saldos": {c["accountId"]: saldo_de(cliente, c["accountId"])["amount"]
                   for c in cliente["cuentas"]},
    }


@app.get("/simulador/clientes/{rut}/creditos", tags=["Simulador"],
         summary="Créditos de un cliente (para el panel)")
def creditos_cliente(rut: str = Path(...)):
    return {"creditos": _cliente_o_404(rut).get("creditos", [])}


@app.post("/simulador/clientes/{rut}/creditos", tags=["Simulador"], status_code=201,
          summary="Agrega un crédito a un cliente (demo en vivo)")
def agregar_credito(
    rut: str = Path(...),
    producto: str = Query("Crédito de Consumo"),
    tipo: str = Query("Consumo"),
    monto: float = Query(3_000_000, gt=0, description="Monto original en CLP"),
    cuota: float = Query(120_000, gt=0, description="Cuota mensual en CLP"),
    plazo: int = Query(24, ge=1, le=600, description="Plazo total en meses"),
    pagadas: int = Query(0, ge=0, description="Cuotas ya pagadas"),
    tasa: float = Query(1.2, description="Tasa de interés del periodo, en %"),
):
    """
    Crea un crédito para probar la pestaña Deudas sin esperar a nada.

    No es parte del estándar: un banco real no tiene un botón para inventar
    créditos. Vive bajo /simulador justamente para dejarlo claro.
    """
    cliente = _cliente_o_404(rut)
    creditos = cliente.setdefault("creditos", [])
    numero = C.normalizar_rut(cliente["rut_normalizado"]).split("-")[0]
    restantes = max(0, plazo - pagadas)

    nuevo = {
        "loanID": "LOAN-%s-%d" % (numero, len(creditos) + 1),
        "productName": producto,
        "loanType": tipo,
        "currency": "CLP",
        "status": "Vigente" if restantes else "Pagado",
        "ownerName": cliente["nombre"].upper(),
        "originalAmount": float(monto),
        "monthlyInstallment": float(cuota),
        "loanTerm": "%d meses" % plazo,
        "loanTermMonths": plazo,
        "remainingInstallments": restantes,
        "interestRate": tasa,
        "periodInterestRate": "Mensual",
        "interestRateType": "Fija",
        "purpose": "Libre disposición",
        "openingDate": datetime.now().date().isoformat(),
        "paymentDay": min(28, datetime.now().day),
        "currentBalance": float(restantes * cuota),
        "arrears": False,
        "amortizationScheduleLink":
            "https://%s/creditos/LOAN-%s-%d/calendario" % (banco.DOMINIO, numero, len(creditos) + 1),
    }
    creditos.append(nuevo)
    C.DUENO_CREDITO[nuevo["loanID"]] = cliente["rut_normalizado"]
    return {"creado": nuevo}


@app.post("/simulador/creditos/{loanID}/pagar", tags=["Simulador"],
          summary="Paga una cuota del crédito (demo en vivo)")
def pagar_cuota(loanID: str = Path(...), cuotas: int = Query(1, ge=1, le=60)):
    """
    Descuenta cuotas y recalcula el saldo.

    Sirve para ver en vivo lo que hace la sincronización: se paga acá, se
    sincroniza en la app y el saldo baja. Es la forma de comprobar que el dato
    viene del banco y no de una copia guardada.
    """
    rut = C.DUENO_CREDITO.get(loanID)
    cliente = C.CLIENTES.get(rut) if rut else None
    if cliente is None:
        raise HTTPException(status_code=404, detail="No existe el crédito %s" % loanID)

    credito = next(c for c in cliente["creditos"] if c["loanID"] == loanID)
    credito["remainingInstallments"] = max(0, credito["remainingInstallments"] - cuotas)
    credito["currentBalance"] = float(
        credito["remainingInstallments"] * credito["monthlyInstallment"]
    )
    credito["status"] = "Vigente" if credito["remainingInstallments"] else "Pagado"
    return {"credito": credito}


@app.post("/simulador/creditos/{loanID}/mora", tags=["Simulador"],
          summary="Marca o quita la mora de un crédito (demo en vivo)")
def marcar_mora(loanID: str = Path(...), en_mora: bool = Query(True)):
    rut = C.DUENO_CREDITO.get(loanID)
    cliente = C.CLIENTES.get(rut) if rut else None
    if cliente is None:
        raise HTTPException(status_code=404, detail="No existe el crédito %s" % loanID)
    credito = next(c for c in cliente["creditos"] if c["loanID"] == loanID)
    credito["arrears"] = en_mora
    return {"credito": credito}


@app.get("/simulador/clientes/{rut}/movimientos", tags=["Simulador"],
         summary="Últimos movimientos de un cliente (para el panel)")
def movimientos_cliente(rut: str = Path(...),
                        limite: int = Query(15, ge=1, le=100)):
    """
    Los movimientos más recientes de un cliente, de todas sus cuentas, ya
    ocurridos. Marca los pendientes y los creados en vivo. Es lo que muestra
    /panel; no es un endpoint del estándar (ese exige token y va por cuenta).
    """
    cliente = _cliente_o_404(rut)
    todos = [(cuenta, m) for cuenta, movs in cliente["movimientos"].items()
             for m in ocurridos(movs)]
    todos.sort(key=lambda par: par[1]["bookingDateTime"], reverse=True)
    # Los pendientes se cuentan todos (también los de fecha futura): son los que
    # confirma /simulador/avanzar.
    pendientes = sum(1 for movs in cliente["movimientos"].values()
                     for m in movs if m.get("_pendiente"))

    def describir(cuenta, m):
        comercio = (m.get("merchantDetails") or {}).get("name")
        signo = 1 if m["transactionsType"] == "Abono" else -1
        return {
            "id": m["transactionID"],
            "cuenta": cuenta,
            "fecha": m["bookingDateTime"].isoformat(),
            "descripcion": comercio or m.get("paymentPurposeCode") or m["transactionsType"],
            "monto": signo * m["amount"],
            "pendiente": bool(m.get("_pendiente")),
            "en_vivo": m["transactionID"].startswith("TXN-LIVE-"),
            "sin_comercio": comercio is None and m["transactionsType"] == "Cargo",
        }

    return {"cliente": cliente["rut"], "pendientes": pendientes,
            "movimientos": [describir(c, m) for c, m in todos[:limite]]}


@app.post("/simulador/clientes", tags=["Simulador"], status_code=201,
          summary="Crear un cliente nuevo con su propia historia")
def crear_cliente(sol: NuevoCliente):
    """
    Crea un cliente para una simulación específica: elige su RUT, nombre, clave,
    perfil (profesional, estudiante o familia), sueldo y meses de historia. La
    historia se genera al tiro y de forma reproducible (la semilla sale del RUT).
    Queda guardado: sobrevive a un reinicio de la EFS.
    """
    try:
        cliente = C.crear_cliente(sol.rut, sol.nombre, sol.clave, sol.perfil,
                                  sol.sueldo, sol.meses)
    except ValueError as e:
        texto = str(e)
        codigo = 409 if texto.startswith("Ya existe") else 422
        raise HTTPException(status_code=codigo, detail=texto)
    return C.resumen(cliente)


@app.delete("/simulador/clientes/{rut}", tags=["Simulador"],
            summary="Eliminar un cliente creado en vivo")
def eliminar_cliente(rut: str = Path(...)):
    try:
        cliente = C.eliminar_cliente(rut)
    except KeyError:
        raise HTTPException(status_code=404, detail="No hay un cliente con RUT %s" % rut)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    # Sus permisos dejan de valer.
    rut_n = cliente["rut_normalizado"]
    for t in [t for t, i in TOKENS.items() if i.get("rut") == rut_n]:
        del TOKENS[t]
    for r in [r for r, i in REFRESH.items() if i.get("rut") == rut_n]:
        del REFRESH[r]
    _guardar_refresh()
    return {"eliminado": cliente["rut"]}


# ───────────────────────── tiempo y compras ─────────────────────────
@app.get("/simulador/estado", tags=["Simulador"],
         summary="Qué movimientos están pendientes de confirmar")
def estado_simulador(rut: str | None = Query(None, description="Solo este cliente")):
    pendientes = []
    for cliente in _clientes_objetivo(rut):
        for cuenta, movs in cliente["movimientos"].items():
            for m in movs:
                if m.get("_pendiente"):
                    pendientes.append({
                        "cliente": cliente["rut"],
                        "cuenta": cuenta,
                        "transactionID": m["transactionID"],
                        "comercio": (m.get("merchantDetails") or {}).get("name"),
                        "monto_actual": m["amount"],
                        "monto_al_confirmar": m["_monto_final"],
                    })
    return {"pendientes": len(pendientes), "movimientos": pendientes}


@app.post("/simulador/avanzar", tags=["Simulador"],
          summary="Confirma los movimientos pendientes")
def avanzar_simulador(rut: str | None = Query(None, description="Solo este cliente")):
    """
    Simula el paso del tiempo: las compras pre-autorizadas se confirman y
    su monto pasa al definitivo.

    El transactionID NO cambia — es el mismo movimiento. Eso es justo lo que
    tiene que detectar la ingesta para actualizar en vez de insertar.
    """
    confirmados = []
    for cliente in _clientes_objetivo(rut):
        for cuenta, movs in cliente["movimientos"].items():
            for m in movs:
                if m.get("_pendiente"):
                    antes = m["amount"]
                    m["amount"] = m["_monto_final"]
                    m["_pendiente"] = False
                    confirmados.append({
                        "cliente": cliente["rut"],
                        "cuenta": cuenta,
                        "transactionID": m["transactionID"],
                        "monto_antes": antes,
                        "monto_despues": m["amount"],
                    })

    return {
        "confirmados": len(confirmados),
        "movimientos": confirmados,
        "nota": ("Para volver al estado inicial, reinicia el servidor: "
                 "los movimientos se regeneran al arrancar."),
    }


# Comercios de ejemplo para inventar un movimiento nuevo (demo en vivo).
_COMERCIOS_DEMO = [
    {"name": "Lider", "category": "Alimentos"},
    {"name": "Copec", "category": "Transporte"},
    {"name": "Uber Eats", "category": "Restaurantes"},
    {"name": "Falabella", "category": "Vestuario"},
    {"name": "Farmacias Ahumada", "category": "Salud"},
    {"name": "Jumbo", "category": "Alimentos"},
]
_contador_demo = {"n": 0}


# Glosas sin comercio: el caso que obliga al clasificador a abstenerse.
_GLOSAS_SUCIAS = ["PAGO PSP 4471 STGO", "TRANSBANK*CL 8829", "CL*SERV 2210"]


@app.post("/simulador/nuevo", tags=["Simulador"],
          summary="Crea un movimiento nuevo para un cliente (demo en vivo)")
@app.post("/simulador/nuevo-pago", include_in_schema=False)  # nombre anterior
def nuevo_movimiento(
    rut: str | None = Query(None, description="Cliente al que se le agrega la compra"),
    accountID: str | None = Query(None, description="Cuenta específica (opcional)"),
    comercio: str | None = Query(None, description="Nombre del comercio (opcional)"),
    monto: float | None = Query(None, gt=0, description="Monto en CLP (opcional)"),
    sin_comercio: bool = Query(False, description="Sin merchantDetails: llega con glosa sucia"),
    pendiente: bool = Query(False, description="Llega pre-autorizado; se confirma con /avanzar"),
):
    """
    Inyecta un movimiento nuevo, como si el cliente acabara de hacer una compra.
    Queda disponible de inmediato en el endpoint de movimientos.

    · Con `rut`: va a la cuenta principal de ese cliente (o a `accountID`).
    · Solo con `accountID`: va a esa cuenta, sea de quien sea.
    · Sin nada: a la cuenta principal del cliente por defecto.
    · sin_comercio → llega sin merchantDetails y con glosa sucia: el
      clasificador debe abstenerse en vez de inventar una categoría.
    · pendiente    → llega pre-autorizado con un monto y /avanzar lo confirma
      con otro, manteniendo el mismo transactionID (la ingesta debe actualizar,
      no duplicar).

    NO es parte del estándar — es un botón para demostrar el flujo. Al reiniciar
    el servidor, los datos vuelven a su estado inicial.
    """
    if rut:
        cliente = _cliente_o_404(rut)
        cuenta = cuenta_o_404(accountID, cliente)["accountId"] if accountID \
            else cliente["cuentas"][0]["accountId"]
    elif accountID:
        dueno = C.DUENO_CUENTA.get(accountID)
        if dueno is None:
            raise HTTPException(status_code=404, detail="Cuenta no encontrada")
        cliente, cuenta = C.CLIENTES[dueno], accountID
    else:
        cliente = C.CLIENTES[C.RUT_POR_DEFECTO]
        cuenta = cliente["cuentas"][0]["accountId"]

    _contador_demo["n"] += 1
    ahora = datetime.now(timezone.utc)
    detalle = ({"name": comercio, "category": None} if comercio
               else random.choice(_COMERCIOS_DEMO))

    # Se fecha "ahora": la compra recién ocurrida. Es la más reciente entre las
    # que ya pasaron, así aparece arriba en la app.
    movs = cliente["movimientos"].setdefault(cuenta, [])
    mov = {
        "transactionID": "TXN-LIVE-%s-%03d" % (ahora.strftime("%m%d%H%M%S"),
                                               _contador_demo["n"]),
        "bookingDateTime": ahora,
        "transactionsType": "Cargo",
        "amount": float(round(monto)) if monto else float(random.randrange(2000, 60000, 10)),
        "currency": "CLP",
    }
    if sin_comercio:
        mov["paymentPurposeCode"] = random.choice(_GLOSAS_SUCIAS)
    else:
        mov["merchantDetails"] = detalle
    if pendiente:
        mov["_pendiente"] = True
        mov["_monto_final"] = float(round(mov["amount"] * 1.15))
    movs.append(mov)

    return {"cliente": cliente["rut"], "cuenta": cuenta, "creado": sin_internos(mov),
            "pendiente": pendiente, "total_cuenta": len(movs)}


# ───────────────────────── panel de demostración ─────────────────────────
from app.panel import PANEL_HTML  # noqa: E402


@app.get("/panel", response_class=HTMLResponse, tags=["Simulador"],
         summary="Panel para hacer compras en vivo y confirmar pendientes")
def panel():
    """Página para manejar la demo desde el navegador (usa los endpoints /simulador/*)."""
    return HTMLResponse(PANEL_HTML)
