# Velvet Wallet — Aplicación móvil

Cliente móvil en **React Native + Expo**, con TypeScript y Expo Router. Le habla solo al backend de
Velvet Wallet (FastAPI, puerto 8000): nunca a los bancos directamente. Lo que muestra llega ya
normalizado, clasificado y filtrado por el usuario de la sesión.

## Cómo levantarla

Necesita el backend (8000) y los bancos simulados (8001 y 8002) corriendo. Lo más simple es
levantar todo desde la raíz del proyecto con `.\iniciar.cmd`. Solo la app:

```bash
npm install
npm run web        # en el navegador, para desarrollar
npm start          # muestra un QR para abrirla en el celular con Expo Go
```

Cuenta de prueba: **`demo@velvetwallet.cl`** · **`velvet2026`** (aparece en la pantalla de inicio de
sesión). La deja lista, con los dos bancos vinculados, `python preparar_demo.py` desde `backend/`.

## Pruebas

```bash
npm test
```

141 pruebas en `src/utils/__tests__/` (archivos `*.prueba.ts`): el resumen del mes, el desglose por
categoría, los gastos divididos, la fusión al sincronizar, las sugerencias de categoría, las metas y
el formato de montos y fechas, y la dirección del servidor. Qué requisito funcional cubre cada una está en
[`../TRAZABILIDAD.md`](../TRAZABILIDAD.md).

## En un celular, con el PC como servidor

La app le habla al backend en la dirección que decide `src/utils/servidor.ts`: la que se escribió
en la pantalla de inicio de sesión (**Servidor > Cambiar**), o la de `EXPO_PUBLIC_API_URL`, o el
mismo equipo que sirvió la página (en el navegador), o el PC desde el que se cargó (en Expo Go), y si
no, `localhost`. Ningún servicio tiene la dirección escrita: todos usan `api()` de
`src/servicios/servidor.ts`.

Para compilar la APK (perfil `preview` de `eas.json`):

```bash
npm install -g eas-cli
eas login
eas build -p android --profile preview
```

El paso a paso de la presentación (red, firewall, bases en Docker) está en
[`../PRESENTACION.md`](../PRESENTACION.md).

## Estructura

```
app.json                 identidad de la app: nombre, esquema de enlaces (velvetwallet://), modo oscuro
src/
├── app/                 PANTALLAS. Cada archivo es una ruta (Expo Router)
│   ├── _layout.tsx      raíz: fuentes, sesión y a qué zona se entra
│   ├── (auth)/          inicio de sesión y registro
│   └── (tabs)/          las cinco pestañas: inicio, gastos, metas, deudas, cuentas
├── components/          piezas reutilizables: filas, gráficos, avisos, campos
├── constants/tema.ts    colores y espaciados. Ningún componente escribe un color a mano
├── modelo/tipos.ts      EL CONTRATO con el backend: lo que la API devuelve
├── servicios/           las llamadas al backend, una por área (sesión, movimientos, metas, privacidad…)
├── sesion/              la sesión; el token queda en el almacén seguro del teléfono
├── datos/               el estado compartido de movimientos e instituciones (MovimientosContexto)
└── utils/               lógica pura y probada: resumen, desglose, fusión, sugerencias, metas
```

## Pantallas

| Pestaña | Qué hay |
|---|---|
| Inicio | Disponible del mes, gasto por mes y por categoría, flujo hasta el día de pago, conectar bancos y sincronizarlos, aviso si un banco no está al día |
| Gastos | Lista con filtros; detalle con trazabilidad y correcciones (asignar categoría, dividir, marcar duplicado, excluir); Por revisar; gastos fijos y suscripciones; anotar un gasto en efectivo |
| Metas | Metas de ahorro con su proyección Monte Carlo |
| Deudas | Los créditos que entrega el estándar |
| Cuentas | Sueldo; instituciones (bancos del SFA, cartolas y efectivo); importar una cartola; privacidad de la Ley 21.719: finalidades, autorizaciones, bitácora, descarga de los datos, avisos de seguridad y eliminar la cuenta |

## Pendiente opcional — bloqueo biométrico

Si el teléfono se pierde o lo roban **con la sesión abierta**, quien lo tenga entra sin contraseña,
porque el token está guardado justamente para no pedirla cada vez. Un bloqueo por huella o rostro al
abrir la aplicación lo evita, y en Expo es un paquete (`expo-local-authentication`).

Queda como **opcional**: no está comprometido en los entregables y no bloquea nada. Encaja con el
cumplimiento de la Ley 21.719, junto con cerrar sesión en todos los dispositivos y acortar la
vigencia del token.

Lo que falta de los requisitos funcionales comprometidos está en
[`../TRAZABILIDAD.md`](../TRAZABILIDAD.md#lo-que-falta).

## Convenciones

- **Colores solo desde `tema.ts`.** Salen de los mockups de Fase 1, paleta oscura.
- **Una pantalla por archivo** dentro de `src/app/`. La lógica compartida va en `components/`, y la
  que se puede probar sin pantalla, en `utils/`.
- **El contrato con el backend vive en `modelo/tipos.ts`.** Si la API cambia lo que devuelve, se
  cambia ahí primero.
- Se usan las APIs estables de Expo Router (`Stack`, `Tabs`), no las marcadas `unstable`.

## Versiones

Expo SDK 57 · React Native 0.86 · React 19 · TypeScript 6
