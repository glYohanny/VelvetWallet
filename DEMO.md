# Guía rápida de demostración

Cómo levantar Velvet Wallet y mostrar un pago llegando. **Requiere dos terminales.**

Solo hace falta tener instalados **Python 3.11+** y **Node 18+**.

## 🔑 Credenciales de prueba

| | |
|---|---|
| **Correo** | `demo@velvetwallet.cl` |
| **Contraseña** | `velvet2026` |

Aparecen escritas en la propia pantalla de inicio de sesión, así que no hay que recordarlas. También
se puede **crear una cuenta nueva** desde el enlace *Crear una* — sirve para demostrar el registro.

> La cuenta vive dentro de la aplicación mientras no exista el backend. Al reiniciar, las cuentas
> creadas se pierden; la de prueba siempre está.

---

## 1. Preparar (solo la primera vez)

**Terminal 1 — el banco simulado:**

```bash
cd simulador
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

**Terminal 2 — la aplicación:**

```bash
cd movil
npm install
```

---

## 2. Levantar (cada vez)

**Terminal 1:**

```bash
cd simulador
.venv\Scripts\activate
uvicorn app.main:app --port 8001
```

**Terminal 2:**

```bash
cd movil
npm run web
```

Se abre el navegador en `http://localhost:8081`. Para verlo como teléfono: **F12** y luego
**Ctrl+Shift+M**.

> Si PowerShell bloquea el `activate`, corre antes:
> `Set-ExecutionPolicy -Scope Process -Bypass`

---

## 3. Entrar

Con las credenciales de prueba del principio de este documento:
`demo@velvetwallet.cl` · `velvet2026`

---

## 4. La demostración

Deja abierta una tercera pestaña del navegador en **`http://localhost:8001/docs`**: es la
documentación del banco simulado, y desde ahí se provocan los pagos con el botón *Try it out*.

| Paso | Dónde | Qué hacer | Qué se ve en la app |
|---|---|---|---|
| 1 | App, Inicio | Anotar el número de movimientos y el total | Punto de partida |
| 2 | `:8001/docs` | `POST /simulador/nuevo-pago` → **Execute** | — |
| 3 | App, Inicio | **Sincronizar** | "1 movimiento nuevo" · contador rojo en Gastos |
| 4 | App, Gastos | Mirar arriba de la lista | El pago marcado **NUEVO**, destacado |
| 5 | `:8001/docs` | `POST /simulador/avanzar` → **Execute** | — |
| 6 | App, Inicio | **Sincronizar** otra vez | "4 actualizados" |
| 7 | App, Gastos | Mirar las filas | **ACTUALIZADO** con el monto anterior debajo |

**El punto clave es el paso 7:** los montos cambiaron pero **la cantidad de movimientos no subió**.
El estándar SFA no tiene un campo que diga si un movimiento está pendiente o confirmado: cuando el
banco confirma una compra, la manda de nuevo con el **mismo identificador y otro monto**. Si se
insertara por llegada, el usuario vería el mismo gasto dos veces y su total estaría mal.

### Variantes útiles

En `POST /simulador/nuevo-pago` hay dos casillas:

- **`sin_comercio`** → el pago llega con glosa sucia y sin comercio identificado. En la app aparece
  en monoespaciada con un `?` rojo y suma al aviso de "movimientos por categorizar". Sirve para
  mostrar que el sistema **se abstiene en vez de inventar** una categoría.
- **`pendiente`** → el pago llega pre-autorizado y se confirma después con `/avanzar`.

### Dos bancos a la vez (RF-07)

Con el segundo banco levantado (`SFA_BANCO=austral`, puerto 8002; `iniciar.cmd` ya lo levanta):

| Paso | Dónde | Qué hacer | Qué se ve en la app |
|---|---|---|---|
| 1 | App, Inicio | **Conectar otro** → **Ir a Banco Austral** | El sitio del Banco Austral |
| 2 | Sitio del banco | Camila: `15.432.876-9` · `2468` → **Autorizar** | "2 bancos vinculados" |
| 3 | App, Cuentas | Mirar Instituciones | Los dos bancos, cada uno con sus cuentas |
| 4 | Terminal del 8002 | **Ctrl+C** (el banco se cae) | — |
| 5 | App, Inicio | **Sincronizar** | "Banco Austral no respondió: se muestran sus datos de la última vez" |
| 6 | App, Cuentas | Mirar Instituciones | Austral en rojo, *No responde*; el otro sigue *Al día* |

**El punto clave es el paso 5:** un banco caído no frena al otro. Cada conexión se sincroniza por
separado, y los datos del que no respondió se siguen mostrando, marcados como de la última vez.

---

## 5. Si algo falla

| Síntoma | Causa | Solución |
|---|---|---|
| "No se pudo conectar con la institución" | El simulador no está corriendo | Revisar la Terminal 1 |
| El contador no cambia | Ya se sincronizó y no hay nada nuevo | Inyectar un pago antes |
| Los datos vuelven al inicio | Se recargó la página | **No recargar durante la demo**: navegar con las pestañas de abajo |
| `uvicorn no se reconoce` | El entorno virtual no está activado | `.venv\Scripts\activate` |

---

## 6. Volver al estado inicial

**Reiniciar el simulador** (Ctrl+C y levantarlo de nuevo) y **recargar la app**. Los pagos
inyectados viven en memoria: al reiniciar desaparecen y se vuelve a los 270 movimientos del
historial. Conviene hacerlo antes de cada ensayo.
