# -*- coding: utf-8 -*-
"""
API HTTP del backend de Velvet Wallet.

Expone la autenticación (tabla usuario), los datos del usuario (movimientos,
cuentas, resumen) y la vinculación de bancos (conexiones), todo filtrado por el
usuario del token.

Correr desde la carpeta backend/ con:

    uvicorn api.main:app --reload --port 8000

Va en el puerto 8000 (la EFS usa el 8001), así conviven los dos.
Documentación interactiva: http://localhost:8000/docs
"""
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth import router as auth_router
from .cargas import router as cargas_router
from .datos import router as datos_router
from .conexiones import router as conexiones_router
from .metas import router as metas_router
from .perfil import router as perfil_router
from .privacidad import router as privacidad_router
from .creditos import router as creditos_router
from .flujo import router as flujo_router
from .incidentes import router as incidentes_router
from .suscripciones import router as suscripciones_router

log = logging.getLogger("uvicorn.error")   # sale en la consola de uvicorn


def _precalentar() -> None:
    """
    Deja listo lo que tarda en arrancar, para que la primera petición no lo
    pague: la conexión a Postgres, el cliente de Mongo (descubrir el cluster
    de Atlas) y el modelo del clasificador (cargarlo, o entrenarlo si no está).
    Corre en segundo plano: el servidor atiende mientras tanto.
    """
    from clasificador import precalentar
    from ingesta.conexiones_bd import conexion, mongo

    def postgres():
        # Una consulta de verdad, no pool().wait(): wait() cierra el pool si no
        # alcanza a llenarlo, y entonces el precalentado dejaría al servidor
        # peor de lo que lo encontró. Esto ejercita el mismo camino que una
        # petición y, si falla, no rompe nada.
        with conexion() as conn:
            conn.execute("SELECT 1")

    for nombre, paso in (("Postgres", postgres),
                         ("MongoDB", lambda: mongo().admin.command("ping")),
                         ("clasificador", precalentar)):
        try:
            paso()
            log.info("Listo: %s", nombre)
        except Exception as e:  # noqa: BLE001 — si falla, se reintenta en la primera petición
            log.warning("No se pudo precalentar %s: %s", nombre, e)


@asynccontextmanager
async def ciclo_de_vida(_app):
    threading.Thread(target=_precalentar, name="precalentar", daemon=True).start()
    yield
    from ingesta.conexiones_bd import cerrar
    cerrar()


app = FastAPI(
    lifespan=ciclo_de_vida,
    title="Velvet Wallet — API",
    version="1.2.0",
    description="Backend de Velvet Wallet. Autenticación, datos del usuario y vinculación de bancos.",
)

# Permite que la app (que corre en otro puerto, p. ej. 8081 en web) consuma el
# API desde el navegador. En producción se restringe a los orígenes autorizados.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(datos_router)
app.include_router(cargas_router)
app.include_router(conexiones_router)
app.include_router(metas_router)
app.include_router(perfil_router)
app.include_router(privacidad_router)
app.include_router(suscripciones_router)
app.include_router(incidentes_router)
app.include_router(creditos_router)
app.include_router(flujo_router)


@app.get("/health", tags=["Operación"], summary="Comprobación de vida")
def health():
    return {"ok": True, "servicio": "velvet-api"}
