# Presentación: la app en un celular, con el PC como servidor

Cómo mostrar Velvet Wallet funcionando en un celular de verdad, con el PC haciendo de servidor:
los dos bancos simulados, el backend y las bases corren en el PC, y el celular se conecta a él por
la red.

```
  Celular (APK de Velvet)                       PC (servidor)
  ───────────────────────     misma red       ─────────────────────────────────
  app ──────────────────────────────────────▶  backend            :8000
  navegador (página del banco) ─────────────▶  Banco Simulado SFA :8001
                                               Banco Austral      :8002
                                               bases: Docker local, o Neon y Atlas
```

**Ensáyalo completo al menos una vez con el mismo celular, el mismo PC y la misma red que vas a
usar.** Casi todo lo que puede fallar el día de la presentación es de red, y se detecta en el ensayo.

---

## Tres formas de verla en el celular

| Forma | Qué necesita | Para qué |
|---|---|---|
| **APK instalada** | Compilarla una vez (gratis, con EAS) | **La recomendada**: es la app real, instalada |
| Navegador del celular | Nada: abrir `http://<IP del PC>:8081` | Plan B inmediato, con el mismo servidor |
| Expo Go | La versión de Expo Go para el **SDK 57** | Solo si ya la tienes: la de la tienda puede estar en el SDK 58 y no abrir el proyecto |

---

## Una vez, antes del día

### 1. Compilar la APK

En el PC, con Node instalado:

```bash
npm install -g eas-cli
```

```bash
cd movil
eas login
eas build -p android --profile preview
```

- La primera vez EAS pide crear el proyecto en expo.dev y una llave de firma para Android: acepta
  las dos (las genera solo).
- La compilación corre en los servidores de Expo y puede tardar entre 10 y 30 minutos según la cola.
  Hazla con días de anticipación, no el mismo día.
- Al terminar, entrega un enlace y un código QR para descargar la `.apk`. Ábrelo en el celular e
  instálala (Android va a pedir permiso para instalar apps de origen desconocido).

La APK **no lleva escrita la IP del servidor**: se escribe en la propia app (ver "El día de la
presentación"), así que no hay que recompilar si la IP cambia. La configuración que la hace posible
ya está en el repositorio: `movil/eas.json` (el perfil `preview` genera una APK) y el permiso para
hablar con un servidor por HTTP en la red local (`expo-build-properties` en `movil/app.json`).

> **Alternativa sin EAS:** con Android Studio instalado, `npx expo run:android --variant release`
> desde `movil/` compila e instala la APK en un celular conectado por USB.

### 2. Abrir el firewall de Windows

Windows bloquea por defecto las conexiones que llegan desde otro equipo. Abre PowerShell **como
administrador** (clic derecho > Ejecutar como administrador), ve a la carpeta del proyecto y corre:

```powershell
.\iniciar.cmd -AbrirFirewall
```

Crea una sola regla, "Velvet Wallet (presentacion)", que deja pasar los puertos 8000, 8001, 8002 y
8081. Después de la presentación se quita con `.\iniciar.cmd -CerrarFirewall`.

### 3. (Recomendado) Docker Desktop

Con las bases en Docker (`-BaseLocal`) la presentación no depende de internet ni de la lista de IP
permitidas de MongoDB Atlas, que cambia cada vez que cambia la red. Instala Docker Desktop y déjalo
abierto. La primera vez descarga las imágenes de PostgreSQL y MongoDB, así que hazlo con internet.

---

## El día de la presentación

1. **La red.** Activa el hotspot del celular y conecta el PC a ese hotspot. Mejor que el Wi-Fi de la
   sede: las redes institucionales suelen aislar los equipos entre sí, y entonces el celular no ve
   al PC aunque los dos estén conectados.

2. **Levantar todo** desde la carpeta del proyecto:

   ```powershell
   .\iniciar.cmd -Presentacion -BaseLocal
   ```

   Sin `-BaseLocal` usa las bases de la nube (Neon y Atlas), y entonces hace falta internet y que la
   IP pública del hotspot esté permitida en Atlas.

   El script detecta la IP del PC, levanta todo escuchando en la red, deja lista la cuenta de prueba
   con los dos bancos vinculados y al final muestra algo así:

   ```
   En el celular (conectado a la misma red que este PC):
     App instalada (APK) ...... en 'Servidor > Cambiar' escribe: 192.168.43.10
     Navegador del celular .... http://192.168.43.10:8081
     Cuenta de prueba ......... demo@velvetwallet.cl · velvet2026
   ```

   Si la IP que muestra no es la de la red del hotspot (pasa con varios adaptadores de red), mírala
   con `ipconfig` y pásala a mano: `.\iniciar.cmd -Presentacion -BaseLocal -Ip 192.168.43.10`.

3. **En el celular**, abre Velvet. Abajo, en la pantalla de inicio de sesión, toca **Servidor >
   Cambiar**, escribe la IP del PC y toca **Probar y usar**. Tiene que decir **Conectado.** La app
   la recuerda para la próxima vez.

4. **Entra con la cuenta de prueba** (`demo@velvetwallet.cl` · `velvet2026`): ya tiene los dos bancos
   y sus datos. Para mostrar la vinculación desde cero, crea una cuenta nueva con **Crear una** y toca
   **Conectar mi banco**: la página del banco se abre en el navegador del celular, se entra con el
   RUT y la clave de prueba (por ejemplo `15.432.876-9` · `2468`) y se vuelve sola a la app.

5. **Para mostrar un banco caído**, cierra en el PC la ventana "Velvet - Banco Austral :8002" y toca
   **Sincronizar** en el celular: el otro banco llega igual e Inicio avisa que al total le falta uno.

---

## Si algo falla

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| "No responde" al probar el servidor | El celular no llega al PC | Revisa que estén en la misma red, que hayas corrido `-AbrirFirewall` y que la IP sea la que muestra `ipconfig` |
| "Algo responde en esa dirección, pero no es el servidor de Velvet" | Esa IP es de otro equipo | Revisa la IP del PC con `ipconfig` |
| La página del banco no carga en el celular | El servidor se levantó sin `-Presentacion` (los bancos quedan en `localhost`) | Ciérralo con `.\iniciar.cmd -Detener` y vuelve a levantarlo con `-Presentacion` |
| Después de autorizar en el banco, el celular no vuelve a la app | Se abrió la app equivocada o una versión vieja | Usa la APK compilada de esta rama; en el navegador del celular la vuelta es a la misma página |
| "No se pudo conectar con MongoDB (Atlas)" | Sin internet, o la IP del hotspot no está permitida en Atlas | Usa `-BaseLocal`, o agrega la IP en Atlas > Network Access |
| "Correo o contraseña incorrectos" con la cuenta de prueba | No se pudo preparar (un banco no estaba arriba) | Con todo arriba, desde `backend/`: `python preparar_demo.py` |
| Todo andaba y de repente "No responde" | El hotspot se reconectó y cambió la IP | Vuelve a correr `iniciar.cmd -Presentacion` y cambia el servidor en la app |

**Plan B, en este orden:** el navegador del celular en `http://<IP del PC>:8081` (mismo servidor,
sin APK), y si la red no coopera, el video del recorrido completo.

---

## Después

```powershell
.\iniciar.cmd -Detener
```

Y como administrador, `.\iniciar.cmd -CerrarFirewall` para volver a cerrar los puertos.

---

## Qué hace `-Presentacion` por dentro

Para quien tenga que mantenerlo. Desde el celular, `localhost` es el propio celular, así que todo lo
que se abre en el celular tiene que llevar la IP del PC:

| Qué | Normal | Con `-Presentacion` |
|---|---|---|
| Dónde escuchan backend y bancos | `127.0.0.1` (solo este PC) | `0.0.0.0` (toda la red) |
| Página del Banco Simulado SFA (`SFA_AUTORIZAR_URL`) | `localhost:8001` | `<IP>:8001` |
| Banco Austral (`SFA_AUSTRAL_URL`) | `localhost:8002` | `<IP>:8002` |
| Vuelta del banco al backend (`SFA_REDIRECT_URI`, y `SFA_REDIRECT_URIS` en los bancos) | `localhost:8000` | `<IP>:8000` (se aceptan las dos) |
| A dónde puede volver la persona (`VELVET_RETORNOS_PERMITIDOS`) | `localhost:8081`, la APK, Expo Go | además `<IP>:8081` |
| La app web (Expo) | solo este PC | `--lan` |

En la app, la dirección del servidor se decide en `movil/src/utils/servidor.ts`: primero la que se
escribió en la pantalla de inicio de sesión; si no, la de `EXPO_PUBLIC_API_URL` (fijada al compilar);
en el navegador, el mismo equipo que sirvió la página; en Expo Go, el PC desde el que se cargó; y si
nada de eso, `localhost` como antes. Por eso el uso normal en el PC no cambia en nada.
