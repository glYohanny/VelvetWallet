# Velvet Wallet

Aplicación móvil de finanzas personales para el mercado chileno, construida como **consumidor del
Sistema de Finanzas Abiertas (SFA)**.

Proyecto APT · Capstone APT122 · Ingeniería en Informática · Duoc UC, sede Puerto Montt

---

## De qué se trata

Los datos financieros de una persona están repartidos entre su banco, sus tarjetas y las fintech que
usa, y ninguna institución los entrega de forma que otro programa pueda leerlos. La alternativa es
anotar todo a mano, que es lo que hace abandonar cualquier aplicación de gastos.

La **Ley 21.521** creó el Sistema de Finanzas Abiertas, que obliga a las instituciones financieras a
entregar los datos del cliente por APIs estandarizadas cuando este lo autoriza. Entra en vigencia en
julio de 2027 y la Comisión para el Mercado Financiero ya publicó la especificación técnica.

Velvet Wallet es una implementación de referencia del lado que **consume** ese estándar, construida
en la ventana de preparación previa a su entrada en vigencia.

El usuario debe poder responder tres preguntas en segundos:

1. ¿Cuánto tengo disponible este mes?
2. ¿En qué se me va la plata?
3. ¿Cuándo voy a poder comprar lo que quiero?

---

## Levantar todo

Desde la carpeta del proyecto, en Windows:

```powershell
.\iniciar.cmd            # simulador (8001), backend (8000) y app (8081)
.\iniciar.cmd -SinApp    # solo simulador y backend
.\iniciar.cmd -Detener   # cierra todo
```

Cierra lo que haya quedado corriendo en esos puertos, prepara `.venv` y las
dependencias solo cuando cambian, abre una ventana por servicio y espera a que
respondan. Necesita `backend\.env` (credenciales de Neon y Atlas, no está en git).

---

## Estructura del repositorio

| Carpeta | Qué contiene | Estado |
|---|---|---|
| `simulador/` | Entidad financiera simulada conforme a la API de Cuentas del SFA | Funcional |
| `movil/` | Aplicación en React Native + Expo | Funcional |
| `BD/` | Entorno de datos: PostgreSQL, MongoDB y Redis con Docker | Funcional |
| `backend/` | API en FastAPI: ingesta, normalización y capas de inteligencia | Por iniciar |
| `Fase 1/` | Evidencias entregadas de la primera fase de la asignatura | Entregado |

La aplicación tiene hoy: registro e inicio de sesión, resumen del mes con gasto por categoría,
lista de movimientos con filtros, detalle con trazabilidad, bandeja de revisión y sincronización
con la institución. Los cálculos están cubiertos por 57 pruebas automatizadas.

### Por qué existe el simulador

El SFA no está vigente, así que no es posible conectarse a instituciones reales. El simulador
implementa el lado **proveedor** del estándar contra la especificación pública de la CMF, lo que
obliga a entender e implementar ambos lados y no solo el del consumidor.

Corre en el puerto **8001**, separado del backend, para poder levantar los dos a la vez.

---

## Cómo levantar cada parte

### Simulador

```bash
cd simulador
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001
```

Documentación interactiva en `http://localhost:8001/docs`. Detalles en
[`simulador/README.md`](simulador/README.md).

Para probar **más de un banco a la vez**, se levanta además el segundo banco, en otra terminal:

```bash
cd simulador
SFA_BANCO=austral uvicorn app.main:app --reload --port 8002
# PowerShell:  $env:SFA_BANCO="austral"; uvicorn app.main:app --reload --port 8002
```

Es otro banco de verdad (Banco Austral), con otras cuentas y otros movimientos. La app lo ofrece al
tocar **Conectar otro** en Inicio.

### Aplicación móvil

```bash
cd movil
npm install
npm run web
```

Credenciales de prueba: **`demo@velvetwallet.cl`** · **`velvet2026`** (aparecen en la propia
pantalla de inicio de sesión). Detalles en [`movil/README.md`](movil/README.md).

Para levantar las dos partes juntas y demostrar un pago llegando en vivo, ver
[`DEMO.md`](DEMO.md).

### Backend

Por iniciar.

---

## Stack

| Capa | Tecnología |
|---|---|
| Backend y simulador | Python · FastAPI · Pydantic |
| Persistencia | PostgreSQL · MongoDB · Redis |
| Inteligencia sobre los datos | scikit-learn · NumPy |
| Aplicación móvil | React Native · Expo · TypeScript |
| Estándar SFA | httpx · OAuth 2.0 (PAR + PKCE) · OpenAPI |

> **Qué del estándar está implementado y qué no.** El flujo de autorización va completo
> —PAR, PKCE, `state`, lista cerrada de URLs de retorno— y la clave del banco nunca pasa
> por Velvet: el usuario la escribe en el sitio de la institución. **Faltan a propósito las
> capas de FAPI 2.0 que no se pueden ejercitar contra un simulador propio**: mTLS entre
> participantes, firma JWS de los mensajes y registro dinámico de clientes (DCR). Están
> declaradas como pendientes en `simulador/app/main.py` y en `backend/ingesta/cliente_sfa.py`,
> que es donde entrarían.

Se usan dos bases de datos por una razón de arquitectura, no por requisito: los payloads que
entregan las instituciones no tienen esquema fijo, porque cada una responde distinto. **PostgreSQL
guarda el modelo canónico ya normalizado; MongoDB guarda el dato crudo tal como llegó**, que además
es la base de la trazabilidad que exige la Ley 21.719.

---

## Convenciones de trabajo

### Ramas

Una rama corta por tarea, integrada mediante pull request:

```
feat/    funcionalidad nueva      feat/ingesta-deduplicacion
fix/     corrección               fix/paginacion-transacciones
chore/   mantención               chore/estructura-repo
docs/    documentación            docs/manual-despliegue
```

### Commits

Se sigue [Conventional Commits](https://www.conventionalcommits.org/es/):

```
feat(simulador): agrega filtros fromDate y toDate
fix(ingesta): evita duplicar movimientos que cambian de monto
```

**Cada integrante commitea con su propia cuenta.** El historial es la evidencia de aporte individual
que evalúa la asignatura, así que nunca se usa una cuenta compartida.

---

## Equipo

| Integrante | Correo |
|---|---|
| PADRON JOSSUE | jo.padron@duocuc.cl |
| TORRES PEDRO | ped.torres@duocuc.cl |
