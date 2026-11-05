# Velvet Wallet — Aplicación móvil

Cliente móvil en **React Native + Expo**, con TypeScript y Expo Router.

## Cómo levantarla

```bash
npm install
npm run web        # en el navegador, para desarrollar
npm start          # muestra un QR para abrirla en el celular con Expo Go
```

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
app.json                 identidad de la app: nombre, esquema de enlaces, modo oscuro
src/
├── app/                 PANTALLAS. Cada archivo es una ruta (Expo Router)
│   ├── _layout.tsx      raíz: pila de pantallas con el tema
│   └── (tabs)/          las cinco pestañas: inicio, gastos, metas, deudas, cuentas
├── components/          piezas reutilizables
└── constants/tema.ts    colores y espaciados. Ningún componente escribe un color a mano
```

## Pendientes anotados

Cosas decididas pero no implementadas, para no perderlas de vista.

| # | Pendiente | Cuándo |
|---|---|---|
| 1 | **Conectar al backend.** Hoy `servicios/sincronizacion.ts` llama al simulador directo y normaliza en el dispositivo. El propio archivo lista punto por punto qué cambiar | Cuando existan los endpoints |
| 2 | **Datos por usuario.** Los movimientos son un archivo dentro de la app: cualquiera que entre ve los mismos. Con backend, cada movimiento queda atado a su `usuario_id` | Junto al punto 1 |
| 3 | **Autenticación real.** `servicios/auth.ts` simula el backend; las cuentas viven en memoria y no sobreviven a reinstalar la app. Recuperar la cuenta en un teléfono nuevo requiere que los datos estén en el servidor | Junto al punto 1 |
| 4 | **Saldo proyectado.** El espacio está reservado en Inicio; se activa con el motor Monte Carlo | Semanas 12-13 |
| 5 | **Acciones de corrección.** Los cuatro botones del detalle no hacen nada: una corrección se persiste, así que necesita backend | Bloque D9 |

### Opcional — bloqueo biométrico

Si el teléfono se pierde o lo roban **con la sesión abierta**, quien lo tenga entra sin contraseña,
porque el token está guardado justamente para no pedirla cada vez. Un bloqueo por huella o rostro al
abrir la aplicación lo evita, y en Expo es un paquete (`expo-local-authentication`).

Queda como **opcional**: no está comprometido en los entregables y no bloquea nada. Encaja con el
bloque de cumplimiento de la Ley 21.719 (semanas 11-14), junto con cerrar sesión en todos los
dispositivos y acortar la vigencia del token.

## Convenciones

- **Colores solo desde `tema.ts`.** Salen de los mockups de Fase 1, paleta oscura.
- **Una pantalla por archivo** dentro de `src/app/`. La lógica compartida va en `components/`.
- Se usan las APIs estables de Expo Router (`Stack`, `Tabs`), no las marcadas `unstable`.

## Versiones

Expo SDK 57 · React Native 0.86 · React 19 · TypeScript 6
