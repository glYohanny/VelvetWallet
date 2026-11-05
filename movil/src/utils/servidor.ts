/**
 * A qué dirección le habla la app: la lógica, sin estado ni red.
 *
 * Mientras todo corría en el mismo computador bastaba con "localhost". En un
 * celular eso es el propio celular, así que la app tiene que llegar al
 * computador que hace de servidor por su IP en la red. La dirección se decide
 * así, de más a menos explícita:
 *
 *   1. La que escribió la persona en la pantalla de inicio de sesión.
 *   2. La que se fijó al compilar (EXPO_PUBLIC_API_URL).
 *   3. En el navegador: el mismo computador que sirvió la página. Abrir la app
 *      en http://192.168.1.20:8081 la conecta a http://192.168.1.20:8000.
 *   4. En Expo Go: el computador desde el que se cargó la app (su hostUri).
 *   5. localhost, como hasta ahora.
 *
 * La parte con estado (guardar, probar la conexión) está en servicios/servidor.ts.
 */

export const PUERTO_API = 8000;

export type OrigenServidor = "escrito" | "compilado" | "pagina" | "expo" | "local";

export type Servidor = { url: string; origen: OrigenServidor };

export type Pistas = {
  /** La que guardó la persona, si guardó alguna. */
  guardado?: string | null;
  /** EXPO_PUBLIC_API_URL. */
  compilado?: string | null;
  /** En web: protocolo y host de la página ("http:", "192.168.1.20"). */
  pagina?: { protocolo: string; host: string } | null;
  /** En Expo Go: Constants.expoConfig.hostUri ("192.168.1.20:8081"). */
  hostUri?: string | null;
};

/**
 * Lo que escribe la persona → una URL usable, o null si no lo es.
 *
 * "192.168.1.20" → "http://192.168.1.20:8000"
 * "192.168.1.20:9000" → "http://192.168.1.20:9000"
 * "http://192.168.1.20:8000/" → "http://192.168.1.20:8000"
 * "https://velvet.ejemplo.cl" → "https://velvet.ejemplo.cl" (con protocolo, el puerto no se adivina)
 */
export function normalizarServidor(texto: string | null | undefined): string | null {
  let t = (texto ?? "").trim();
  if (!t || /\s/.test(t)) return null;
  const conProtocolo = /^https?:\/\//i.test(t);
  if (!conProtocolo) t = "http://" + t;
  const m = t.match(/^(https?):\/\/([^/:?#]+)(?::(\d{1,5}))?(\/[^?#]*)?$/i);
  if (!m) return null;
  const [, protocolo, host, puerto, ruta] = m;
  if (!/^[a-z0-9.-]+$/i.test(host) || host.startsWith(".") || host.endsWith(".")) return null;
  if (puerto && (Number(puerto) < 1 || Number(puerto) > 65535)) return null;
  const puertoFinal = puerto ?? (conProtocolo ? "" : String(PUERTO_API));
  const base = `${protocolo.toLowerCase()}://${host.toLowerCase()}${puertoFinal ? ":" + puertoFinal : ""}`;
  const camino = (ruta ?? "").replace(/\/+$/, "");
  return base + camino;
}

/** El host de "192.168.1.20:8081" o "[::1]:8081". */
function hostDe(hostUri: string): string | null {
  const sinRuta = hostUri.split("/")[0];
  const host = sinRuta.startsWith("[") ? sinRuta.slice(0, sinRuta.indexOf("]") + 1) : sinRuta.split(":")[0];
  return host || null;
}

export function deducirServidor(p: Pistas): Servidor {
  const escrito = normalizarServidor(p.guardado);
  if (escrito) return { url: escrito, origen: "escrito" };

  const compilado = normalizarServidor(p.compilado);
  if (compilado) return { url: compilado, origen: "compilado" };

  if (p.pagina?.host) {
    const protocolo = p.pagina.protocolo === "https:" ? "https:" : "http:";
    return { url: `${protocolo}//${p.pagina.host}:${PUERTO_API}`, origen: "pagina" };
  }

  const host = p.hostUri ? hostDe(p.hostUri) : null;
  if (host && host !== "localhost" && host !== "127.0.0.1") {
    return { url: `http://${host}:${PUERTO_API}`, origen: "expo" };
  }

  return { url: `http://localhost:${PUERTO_API}`, origen: "local" };
}
