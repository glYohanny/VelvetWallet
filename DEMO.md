# Guía rápida de demostración

Cómo levantar Velvet Wallet y mostrar un pago llegando, dos bancos a la vez y uno que se cae.

Hace falta **Python 3.11+**, **Node 18+** y el archivo `backend\.env` (credenciales de Neon y
Atlas, y la clave de cifrado; no está en git).

## 🔑 Credenciales de prueba

| | |
|---|---|
| **Correo** | `demo@velvetwallet.cl` |
| **Contraseña** | `velvet2026` |

Aparecen escritas en la propia pantalla de inicio de sesión. La cuenta la deja lista
`python preparar_demo.py` (paso 2): la crea con esa contraseña y la vincula con los dos bancos
como la clienta Camila Rojas, así que al entrar ya hay datos. También se puede **crear una cuenta
nueva** desde el enlace *Crear una*, que sirve para demostrar el registro y la vinculación desde cero.

---

## 1. Levantar

**Con un solo comando** (Windows, desde la carpeta del proyecto):

```powershell
.\iniciar.cmd
```

Abre una ventana por servicio: los dos bancos simulados (8001 y 8002), el backend (8000) y la app
(8081). La primera vez instala las dependencias, así que tarda más.

**A mano**, una terminal por servicio (con el entorno virtual activado en las de Python):

| Terminal | Carpeta | Comando |
|---|---|---|
| 1 · Banco Simulado SFA | `simulador` | `uvicorn app.main:app --port 8001` |
| 2 · Banco Austral | `simulador` | `$env:SFA_BANCO="austral"; uvicorn app.main:app --port 8002` |
| 3 · Backend | `backend` | `uvicorn api.main:app --port 8000` |
| 4 · App | `movil` | `npm run web` |

Se abre el navegador en `http://localhost:8081`. Para verlo como teléfono: **F12** y luego
**Ctrl+Shift+M**.

> Si PowerShell bloquea el `activate`, corre antes:
> `Set-ExecutionPolicy -Scope Process -Bypass`

---

## 2. Preparar la cuenta de prueba (una vez)

Con los bancos y el backend arriba:

```bash
cd backend
python preparar_demo.py
```

Se puede correr las veces que se quiera: si la cuenta ya está, solo vuelve a traer los datos.

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
| "No se pudo conectar con la institución" | El banco simulado no está corriendo | Revisar su ventana (8001 u 8002) |
| "Correo o contraseña incorrectos" con la cuenta de prueba | La base no tiene la cuenta de prueba | `python preparar_demo.py` desde `backend/` |
| "No se pudo conectar con MongoDB (Atlas)" | La IP de este equipo no está permitida en Atlas | Agregarla en Atlas → Network Access |
| El contador no cambia | Ya se sincronizó y no hay nada nuevo | Inyectar un pago antes |
| `uvicorn no se reconoce` | El entorno virtual no está activado | `.venv\Scripts\activate` |

---

## 6. Volver al estado inicial

**Reiniciar los simuladores** (Ctrl+C y levantarlos de nuevo). Los pagos inyectados viven en su
memoria: al reiniciar desaparecen y cada banco vuelve a su historial original. Lo que ya se
sincronizó queda en la base de Velvet: para empezar de cero, desvincula los bancos desde Cuentas, o
borra la cuenta y vuelve a correr `python preparar_demo.py`. Conviene hacerlo antes de cada ensayo.
