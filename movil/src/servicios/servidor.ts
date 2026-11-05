/**
 * A qué servidor le habla la app (la dirección del backend).
 *
 * Todos los servicios piden la dirección aquí, con `api()`, en vez de tener
 * cada uno "http://localhost:8000" escrito. Cómo se decide está explicado en
 * utils/servidor.ts; este archivo agrega lo que tiene estado: recordar la que
 * escribió la persona y probar que responde.
 *
 * Para la presentación con un celular: el computador que hace de servidor y
 * el celular están en la misma red, y en la pantalla de inicio de sesión se
 * escribe la IP del computador (la muestra `iniciar.cmd -Presentacion`).
 */
import Constants from "expo-constants";
import { Platform } from "react-native";

import { borrar, guardar, leer } from "@/servicios/almacenamiento";
import { deducirServidor, normalizarServidor, type Servidor } from "@/utils/servidor";

const CLAVE = "velvet.servidor";

function pistasDelEntorno() {
  const pagina =
    Platform.OS === "web" && typeof window !== "undefined" && window.location?.hostname
      ? { protocolo: window.location.protocol, host: window.location.hostname }
      : null;
  return {
    compilado: process.env.EXPO_PUBLIC_API_URL ?? null,
    pagina,
    hostUri: Constants.expoConfig?.hostUri ?? null,
  };
}

let actual: Servidor = deducirServidor(pistasDelEntorno());

/** La dirección del backend, sin barra final: `${api()}/api/movimientos`. */
export function api(): string {
  return actual.url;
}

/** La dirección y de dónde salió, para mostrarla en pantalla. */
export function servidorActual(): Servidor {
  return actual;
}

/** Se llama una vez al arrancar, antes de la primera petición. */
export async function cargarServidor(): Promise<Servidor> {
  try {
    actual = deducirServidor({ ...pistasDelEntorno(), guardado: await leer(CLAVE) });
  } catch {
    // Sin almacenamiento disponible se sigue con lo deducido.
  }
  return actual;
}

/**
 * Recuerda la dirección que escribió la persona. Con null se olvida y se
 * vuelve a la deducida. Devuelve la que queda vigente.
 */
export async function elegirServidor(texto: string | null): Promise<Servidor> {
  if (texto === null) {
    await borrar(CLAVE).catch(() => {});
  } else {
    const url = normalizarServidor(texto);
    if (!url) throw new Error("Esa dirección no es válida. Escribe algo como 192.168.1.20.");
    await guardar(CLAVE, url);
  }
  return cargarServidor();
}

/**
 * ¿Responde el backend de Velvet en esa dirección? No basta con que algo
 * conteste: tiene que ser este backend (su /health se identifica).
 */
export async function probarServidor(texto: string): Promise<{ ok: boolean; mensaje: string; url: string | null }> {
  const url = normalizarServidor(texto);
  if (!url) return { ok: false, mensaje: "Esa dirección no es válida. Escribe algo como 192.168.1.20.", url: null };

  const control = new AbortController();
  const reloj = setTimeout(() => control.abort(), 5000);
  try {
    const r = await fetch(`${url}/health`, { signal: control.signal });
    const cuerpo = (await r.json().catch(() => null)) as { servicio?: string } | null;
    if (r.ok && cuerpo?.servicio === "velvet-api") return { ok: true, mensaje: "Conectado.", url };
    return { ok: false, mensaje: "Algo responde en esa dirección, pero no es el servidor de Velvet.", url };
  } catch {
    return {
      ok: false,
      mensaje:
        "No responde. Revisa que el celular y el computador estén en la misma red, que el " +
        "servidor esté corriendo y que el firewall deje pasar el puerto 8000.",
      url,
    };
  } finally {
    clearTimeout(reloj);
  }
}
