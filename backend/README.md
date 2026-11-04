# Backend — Ingesta y normalización (bloque D)

Lee los datos del proveedor SFA y los deja en las dos bases: el crudo en MongoDB
y el modelo canónico en PostgreSQL.

## Diseño en capas (por qué sirve para el banco real)

El código está separado para que pasar del simulador a un banco real cambie
**solo la URL y la autenticación**, nada más:

```
ingesta/
├── config.py        URLs y credenciales (lo único que cambia entre entornos)
├── cliente_sfa.py   Habla el estándar SFA. Aquí van mTLS y OAuth del banco real
├── normalizador.py  SFA → modelo canónico (monto con signo, hash). No sabe de red ni de BD
├── repositorio.py   Escribe: crudo en Mongo, UPSERT en Postgres
├── bootstrap.py     Siembra usuario/institución/conexión (mientras no hay OAuth)
└── sincronizar.py   Orquesta todo. Punto de entrada
```

El simulador ya habla el mismo estándar de la CMF, así que `normalizador` y
`repositorio` **no se tocan** cuando llegue un banco de verdad.

## Requisitos previos

1. Bases arriba:  desde `BD/`  →  `docker compose up -d`
2. Simulador arriba:  desde `simulador/`  →  `uvicorn app.main:app --reload --port 8001`

## Puesta en marcha

```bash
cd backend
python -m venv .venv
.\.venv\Scripts\activate         # Windows PowerShell
pip install -r requirements.txt
cp .env.example .env             # ajusta credenciales si cambiaste las de BD/.env
python -m ingesta.sincronizar
```

Salida esperada (primera corrida):

```
Sincronización lista:
  Consentimiento     : urn:velvet:consent:...
  Cuentas procesadas : 2
  Movimientos nuevos : 271
  Movimientos actualizados: 0
  Sin cambios        : 0
```

Las tres cifras son distintas a propósito: **nuevos** son los que no existían,
**actualizados** los que el banco mandó distinto, y **sin cambios** los que llegaron
exactamente igual y no se tocaron. Si todo cayera en "actualizados" en cada corrida, el
número no diría nada.

## Probar el ciclo pendiente → confirmada

Esto es lo que justifica el `id_externo` y el UPSERT del esquema:

```bash
# 1. Primera ingesta (ya hecha arriba): N movimientos insertados.
# 2. Un pago nuevo que llega pre-autorizado:
curl -X POST "http://localhost:8001/simulador/nuevo-pago?pendiente=true"
python -m ingesta.sincronizar          # -> nuevos: 1
# 3. El banco lo confirma con otro monto, mismo transactionID:
curl -X POST http://localhost:8001/simulador/avanzar
python -m ingesta.sincronizar          # -> nuevos: 0, actualizados: 1
```

**"Movimientos nuevos" debe ser 0 en el paso 3**, y el total de filas no debe subir:
el movimiento cambió de monto pero es el mismo. Si el conteo de nuevos sube, el UPSERT
no está funcionando.

Comprobado con:

```bash
docker compose -f ../BD/docker-compose.yml exec postgres \
  psql -U velvet -d velvet_wallet -c "SELECT count(*), count(DISTINCT id_externo) FROM transaccion;"
```

Los dos números deben ser iguales: un movimiento del banco, una fila.

## Verificar en la base

```bash
docker compose -f ../BD/docker-compose.yml exec postgres \
  psql -U velvet -d velvet_wallet -c "SELECT count(*), sum(monto) FROM transaccion;"
```

El `sum(monto)` es, literalmente, el saldo: cargos negativos y abonos positivos.

## API para la app (puerto 8000)

```bash
uvicorn api.main:app --reload --port 8000     # desde backend/, con la EFS en el 8001
```

Todo va filtrado por el usuario del token (JWT): cada usuario ve solo lo suyo.

| Endpoint | Qué hace |
|---|---|
| `POST /api/auth/registro`, `POST /api/auth/sesion` | Cuenta de Velvet |
| `GET /api/movimientos`, `/api/cuentas`, `/api/resumen` | Datos del usuario (cada gasto ya clasificado) |
| `PUT /api/movimientos/{id}/categoria` | El usuario corrige la categoría; queda en `correccion` |
| `POST /api/conexiones/iniciar` | Deja la solicitud en el banco (PAR + PKCE) y devuelve la URL de la página del banco |
| `GET /api/conexiones/retorno` | El banco vuelve aquí con el código; se canjea y se redirige a la app con `?banco=vinculado` |
| `POST /api/conexiones` | Trae (o re-trae) los datos con el permiso guardado |
| `GET /api/conexiones`, `DELETE /api/conexiones/{id}` | Bancos vinculados; desvincular revoca el permiso y borra sus datos |
| `GET/POST/PATCH/DELETE /api/metas` | Metas de ahorro, cada una con su proyección Monte Carlo |
| `POST /api/cartolas` | Importa una cartola CSV (RF-12), a una cuenta existente o de un banco fuera del SFA; con `simular` es una vista previa |
| `POST /api/movimientos/{id}/excluir`, `/duplicado`; `DELETE .../exclusion` | No es gasto, o es duplicado de otro (RF-14); volver a contarlo |
| `PUT /api/movimientos/{id}/division`, `DELETE .../division` | Repartir un gasto entre categorías; las partes suman el monto exacto |
| `POST /api/movimientos`, `DELETE /api/movimientos/{id}` | Anotar un gasto o ingreso en efectivo (RF-13); borrar solo lo anotado a mano |
| `GET /api/privacidad/finalidades`, `POST .../{finalidad}` | Para qué se usan los datos; consentir y revocar por finalidad |

**La clave del banco nunca pasa por Velvet**: el usuario la escribe en la página del banco
(ver `simulador/README.md`, "Autorización en el sitio del banco"). Velvet guarda solo el refresh
token del permiso, cifrado (ver abajo).

Si la base se creó con un esquema anterior (sin `transaccion.categoria_origen`, o con
`usuario.sueldo_declarado` numérico), el backend la pone al día solo la primera vez que se conecta
(`ingesta/esquema.py`, idempotente).

## Tres fuentes, un solo ledger (OE-1)

Los movimientos entran por la API del SFA, por cartola CSV o anotados a mano, y terminan en el
mismo modelo canónico: mismo clasificador, mismas recurrencias, mismos cálculos. `transaccion.fuente`
dice por dónde entró cada uno.

- **Cartolas** (`ingesta/cartola.py`): detecta el separador, salta los títulos hasta el
  encabezado y entiende montos a la chilena (`$ 12.345`, cargos y abonos en columnas aparte),
  fechas `dd/mm/aaaa` y archivos de Excel en Windows-1252. Una línea que no se puede leer se
  informa con su número y el motivo, y el resto entra igual.
- **Misma fuente, misma fila**: la huella `hash_dedup`. Reimportar la misma cartola, o una que se
  solapa con la anterior, no duplica nada.
- **Otra fuente, mismo movimiento** (RF-09, `ingesta/dedup.py`): la misma compra llega con otra
  glosa ("Jumbo" / "COMPRA JUMBO LA FLORIDA") y a veces con la fecha contable, uno o dos días
  después. Se considera la misma cuando el monto es idéntico y las fechas están a ≤ 3 días; entre
  candidatos gana la fecha más cercana y después la glosa más parecida, uno a uno. Queda **un**
  movimiento, y la otra fuente se anota en `transaccion_origen` con su propio crudo. Funciona en
  los dos sentidos: si el historial entró por cartola y después la API trae lo mismo, la API pasa a
  ser la fuente principal (trae el `transactionID`) y la cartola queda como origen adicional.
- **Efectivo**: lo anotado a mano va a una cuenta "Efectivo" de la persona. Si elige la
  categoría, es una decisión suya (queda como corrección); si no, la propone el clasificador.

## Correcciones del usuario (RF-14)

Recategorizar, excluir, marcar duplicado y dividir **no tocan el dato del banco**: monto, fecha,
glosa y crudo quedan como llegaron. Cada corrección es una fila nueva en `correccion`, y deshacer
también es una fila, así que la historia completa queda (`api/correcciones.py`).

- **Excluir / duplicado** dejan `transaccion.estado = 'excluido'`, que es un derivado de esa capa y
  lo que ya respetan el resumen, el flujo, las metas y las recurrencias. La sincronización no lo
  toca: la corrección sobrevive. Un duplicado exige el mismo monto y que el otro sí cuente; el
  original no se puede excluir mientras alguien sea duplicado de él (no quedaría ninguno).
- **Dividir** guarda las partes en la corrección; el total sigue siendo el del movimiento y solo
  cambia el reparto por categoría (en la app, `utils/porciones.ts`). Las partes tienen que sumar el
  monto exacto. Si el banco cambia el monto después (pendiente → confirmada), el reparto deja de
  aplicarse en vez de mostrar partes que ya no cuadran.

## Cifrado en reposo (RF-31)

Dos capas. El **almacenamiento** de Neon y Atlas cifra el disco completo: protege si alguien se
lleva el disco o un respaldo físico. La **aplicación** cifra además, antes de escribir, lo más
sensible: protege también si alguien llega a *leer* la base (un respaldo filtrado, credenciales
robadas), porque lo que ve es `enc:v1:...`.

| Qué se cifra en la aplicación | Dónde | Por qué |
|---|---|---|
| Refresh token del banco | `consentimiento.alcance_rar` | Es una credencial: con él se leen los datos de la persona en su banco |
| RUT y nombre del cliente del banco | `consentimiento.alcance_rar` | Identifican a la persona |
| Payload crudo | Mongo `payload_crudo.payload` | Es la respuesta íntegra del banco |
| Sueldo declarado | `usuario.sueldo_declarado` | Dato sensible declarado por la persona |

Los montos, fechas y glosas del modelo canónico **no** se cifran en la aplicación: sobre ellos se
suman, filtran y proyectan en SQL, y cifrarlos obligaría a traer todo a memoria para cada cálculo.
Quedan cubiertos por la capa del almacenamiento.

- **AES-256-GCM** (`ingesta/cifrado.py`, librería `cryptography`): cifrado autenticado. Un dato
  alterado no se descifra, en vez de entregarse corrupto, y por eso el payload crudo sigue sirviendo
  como prueba de lo que mandó el banco (RF-06). `Repositorio.leer_crudo(ref)` lo devuelve idéntico.
- **Cada valor queda atado a su registro**: el campo y el id van como dato asociado (AAD). El sueldo
  cifrado de una persona copiado en la fila de otra, o el token de un banco copiado en otra
  conexión, no se descifra.
- **La clave no está en la base ni en el repo**: va en `VELVET_CLAVE_CIFRADO` en `backend/.env`.
  **Todos los que usen la misma base necesitan la misma clave.** Sin clave configurada se usa una
  de desarrollo que no protege nada, y el log lo avisa.

```bash
python -m ingesta.cifrado --generar-clave     # una clave nueva, para el .env
python cifrar_datos_existentes.py --simular   # cuántos datos siguen en claro
python cifrar_datos_existentes.py             # cifrarlos (idempotente)
```

**Rotar la clave:** la nueva en `VELVET_CLAVE_CIFRADO`, la vieja en `VELVET_CLAVES_ANTERIORES`,
correr `cifrar_datos_existentes.py` y recién entonces quitar la vieja. Cada valor guarda la huella
de la clave que lo cifró, así que conviven mientras dura la rotación.

Lo que se le entrega a la persona (la app y la exportación de portabilidad) va descifrado: el
cifrado protege el dato guardado, no se lo esconde a su dueño.

## Motor de proyección (Monte Carlo)

`motor/proyeccion.py` responde "¿cuándo alcanzo esta meta?" simulando 10.000 futuros
posibles con los excedentes mensuales que la persona realmente tuvo, en distinto orden.
La respuesta no es un plazo sino una probabilidad por mes: *8 meses con 80%, 11 con 95%*.

No toca la base ni la red, así que se prueba solo:

```bash
pip install -r requirements-dev.txt
python -m pytest                      # desde backend/
```

Las 21 pruebas verifican propiedades, no números mágicos: que la curva nunca baje, que
ahorrar más nunca empeore el plazo, que dos personas con el mismo excedente *promedio*
pero distinta variabilidad no reciban la misma respuesta, y que el motor **se abstenga**
cuando hay menos de tres meses de historial en vez de inventar un plazo.

El generador va sembrado (`numpy.random.default_rng(42)`): la misma entrada da siempre
la misma salida, que es lo que hace verificable una simulación aleatoria.

## Clasificador de gastos

La ingesta clasifica cada gasto al guardarlo (reglas → modelo → abstención). Lo
que no reconoce queda sin categoría y aparece en "Por revisar". Detalle,
resultados y reentrenamiento en [`clasificador/README.md`](clasificador/README.md).

```bash
python -m clasificador.reentrenar     # reentrena con las correcciones consentidas
```

Prueba de punta a punta (base LOCAL, borra datos; EFS en :8001):

```bash
python prueba_clasificador_e2e.py
```

## Rendimiento

Las bases están en la nube (Neon y Atlas), así que lo caro son las idas y
vueltas por la red, no el cómputo. Por eso:

- **Conexiones reutilizadas** (`ingesta/conexiones_bd.py`): un pool de Postgres
  y un solo cliente de Mongo por proceso, en vez de abrir una conexión nueva en
  cada petición.
- **La sincronización escribe solo lo que cambió**: compara con lo guardado y
  manda a Mongo y Postgres únicamente lo nuevo o modificado. Re-sincronizar
  sin novedades no escribe nada.
- **El clasificador predice en lote** y el modelo se carga (o entrena) al
  arrancar el servidor, en segundo plano.

Con latencia simulada de nube (0,4 s por conexión, 0,1 s por ida y vuelta):

| | Antes | Ahora |
|---|---|---|
| Botón Sincronizar (sincronizar + traer la lista) | 4,0 s | 1,3 s |
| Re-sincronizar sin cambios | 3,5 s | 1,1 s |
| Re-sincronizar con 1 compra nueva | 3,5 s | 1,5 s |
| Primera sincronización | 4,6 s | 2,8 s |
| Traer los movimientos | 0,54 s | 0,23 s |
