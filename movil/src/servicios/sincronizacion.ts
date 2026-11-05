/**
 * Sincronización: trae los movimientos del usuario desde el backend.
 *
 * Las capas acordadas son:
 *
 *     app  →  backend  →  ingesta  →  cliente SFA  →  EFS / banco
 *
 * La app ya NO habla con la institución directamente ni normaliza en el
 * dispositivo: pide sus movimientos al backend, que los entrega ya en el modelo
 * canónico (clasificados, deduplicados) y SOLO los del usuario del token. Así
 * cada usuario ve únicamente lo suyo.
 */
import type { Conexion, Movimiento } from "@/modelo/tipos";
import { tokenActual } from "@/servicios/auth";
import { api } from "@/servicios/servidor";

/**
 * Error con un código opcional para que la pantalla sepa qué hacer:
 *  · "reautorizar"  → el permiso venció o nunca se dio: mandar al sitio del banco.
 *  · "otro_cliente" → ese banco ya está vinculado a otro RUT.
 */
export class ErrorSincronizacion extends Error {
  codigo?: string;
  constructor(mensaje: string, codigo?: string) {
    super(mensaje);
    this.codigo = codigo;
  }
}

/** Traduce la respuesta de error del backend a un mensaje y código claros. */
async function errorDeRespuesta(respuesta: Response, porDefecto: string): Promise<ErrorSincronizacion> {
  let detalle: unknown = null;
  try {
    detalle = ((await respuesta.json()) as { detail?: unknown }).detail;
  } catch {
    // sin cuerpo JSON
  }
  if (detalle && typeof detalle === "object" && "mensaje" in detalle) {
    const d = detalle as { mensaje: string; codigo?: string };
    return new ErrorSincronizacion(d.mensaje, d.codigo);
  }
  if (typeof detalle === "string") return new ErrorSincronizacion(detalle);
  return new ErrorSincronizacion(porDefecto);
}

/**
 * Trae los movimientos del usuario autenticado. Manda el token de sesión; el
 * backend responde solo con los datos de ese usuario (WHERE usuario_id = …).
 */
export async function obtenerMovimientos(): Promise<Movimiento[]> {
  const token = await tokenActual();
  if (!token) {
    throw new ErrorSincronizacion("Tu sesión no está activa. Inicia sesión de nuevo.");
  }

  let respuesta: Response;
  try {
    respuesta = await fetch(`${api()}/api/movimientos?limite=500`, {
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch {
    throw new ErrorSincronizacion(
      "No se pudo conectar con el servidor. Revisa que el backend esté corriendo.",
    );
  }

  if (!respuesta.ok) {
    throw new ErrorSincronizacion(`El servidor respondió ${respuesta.status}.`);
  }

  const cuerpo = (await respuesta.json()) as { movimientos: Movimiento[] };
  return cuerpo.movimientos;
}

/**
 * Guarda en el backend la categoría que eligió el usuario para un movimiento.
 * Queda registrada como corrección (el dato del banco no se toca), manda sobre
 * lo que proponga el clasificador y, si la persona consintió, sirve para
 * reentrenarlo. Devuelve el movimiento como quedó.
 */
export async function guardarCategoria(id: string, categoria: string): Promise<Movimiento> {
  const token = await tokenActual();
  if (!token) {
    throw new ErrorSincronizacion("Tu sesión no está activa. Inicia sesión de nuevo.");
  }
  let respuesta: Response;
  try {
    respuesta = await fetch(`${api()}/api/movimientos/${encodeURIComponent(id)}/categoria`, {
      method: "PUT",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ categoria }),
    });
  } catch {
    throw new ErrorSincronizacion(
      "No se pudo conectar con el servidor. Revisa que el backend esté corriendo.",
    );
  }
  if (!respuesta.ok) {
    throw await errorDeRespuesta(respuesta, "No se pudo guardar la categoría.");
  }
  return (await respuesta.json()) as Movimiento;
}

export type ResultadoConexion = {
  institucion: string;
  /** El cliente del banco con el que quedó vinculada la conexión. */
  cliente: { rut: string; nombre: string };
  cuentas: number;
  movimientosNuevos: number;
  movimientosActualizados: number;
  /**
   * Banco por banco (RF-07). Cada uno se sincroniza por separado: si uno no
   * respondió o su permiso venció, los demás llegan igual.
   */
  bancos?: ResultadoBanco[];
};

export type ResultadoBanco = {
  institucion: string;
  ok: boolean;
  movimientosNuevos?: number;
  movimientosActualizados?: number;
  /** Cuando no resultó: "sin_respuesta" (el banco no contestó) o "reautorizar". */
  codigo?: "sin_respuesta" | "reautorizar" | "otro_cliente";
  mensaje?: string;
};

/** Un banco del SFA al que Velvet se puede conectar. */
export type Institucion = { nombre: string; conectada: boolean };

export async function obtenerInstituciones(): Promise<Institucion[]> {
  const token = await tokenActual();
  if (!token) return [];
  try {
    const r = await fetch(`${api()}/api/instituciones`, { headers: { Authorization: `Bearer ${token}` } });
    if (!r.ok) return [];
    return ((await r.json()) as { instituciones: Institucion[] }).instituciones;
  } catch {
    return [];
  }
}

/**
 * Empieza la vinculación: el backend deja la solicitud en el banco (PAR + PKCE)
 * y devuelve la URL de la PÁGINA DEL BANCO. Allá el usuario inicia sesión con
 * su RUT y su clave y aprueba; Velvet nunca ve esos datos.
 *
 * `retorno` es a dónde vuelve el usuario al terminar (la URL de la app). El
 * banco vuelve al backend, y el backend redirige ahí con `?banco=vinculado`,
 * `?banco=rechazado` o `?banco=error&motivo=...`.
 */
export async function iniciarVinculacion(retorno: string, institucion?: string): Promise<string> {
  const token = await tokenActual();
  if (!token) {
    throw new ErrorSincronizacion("Tu sesión no está activa. Inicia sesión de nuevo.");
  }
  let respuesta: Response;
  try {
    respuesta = await fetch(`${api()}/api/conexiones/iniciar`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ retorno, ...(institucion ? { institucion } : {}) }),
    });
  } catch {
    throw new ErrorSincronizacion(
      "No se pudo conectar con el servidor. Revisa que el backend esté corriendo.",
    );
  }
  if (!respuesta.ok) {
    throw await errorDeRespuesta(respuesta, "No se pudo abrir el sitio del banco.");
  }
  return ((await respuesta.json()) as { urlAutorizacion: string }).urlAutorizacion;
}

/**
 * Trae (o vuelve a traer) los datos de los bancos ya autorizados, con el
 * permiso guardado de cada uno. Falla con codigo "reautorizar" solo si no hay
 * ningún banco que responda; si responde alguno, el detalle viene en `bancos`.
 *
 * Puede tardar unos segundos (baja el historial).
 */
export async function conectarBanco(institucion?: string): Promise<ResultadoConexion> {
  const token = await tokenActual();
  if (!token) {
    throw new ErrorSincronizacion("Tu sesión no está activa. Inicia sesión de nuevo.");
  }

  let respuesta: Response;
  try {
    respuesta = await fetch(`${api()}/api/conexiones`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      // Sin institución, el backend sincroniza TODOS los bancos vinculados.
      body: JSON.stringify(institucion ? { institucion } : {}),
    });
  } catch {
    throw new ErrorSincronizacion(
      "No se pudo conectar con el servidor. Revisa que el backend esté corriendo.",
    );
  }

  if (!respuesta.ok) {
    throw await errorDeRespuesta(respuesta, "No se pudo vincular el banco. Intenta de nuevo.");
  }
  return (await respuesta.json()) as ResultadoConexion;
}

/**
 * Lo que entrega el backend: el contrato (`Conexion`) más a qué cliente del
 * banco quedó atada. Eso último no es parte del contrato porque no describe la
 * conexión sino la vinculación, y solo lo usa el encabezado del inicio.
 */
export type ConexionBanco = Conexion & {
  rutCliente: string | null;
  nombreCliente: string | null;
  /** false si el permiso es de antes del flujo por el banco y hay que re-autorizar. */
  autorizada: boolean;
};

/** Bancos vinculados del usuario (y a qué cliente del banco está atado cada uno). */
export async function obtenerConexiones(): Promise<ConexionBanco[]> {
  const token = await tokenActual();
  if (!token) return [];
  const respuesta = await fetch(`${api()}/api/conexiones`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!respuesta.ok) return [];
  return ((await respuesta.json()) as { conexiones: ConexionBanco[] }).conexiones;
}

/**
 * Desvincula un banco: el permiso se revoca en el banco y se borran de Velvet
 * las cuentas y movimientos de esa conexión.
 */
export async function desvincularBanco(conexionId: string): Promise<void> {
  const token = await tokenActual();
  if (!token) {
    throw new ErrorSincronizacion("Tu sesión no está activa. Inicia sesión de nuevo.");
  }
  const respuesta = await fetch(`${api()}/api/conexiones/${conexionId}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!respuesta.ok) {
    throw await errorDeRespuesta(respuesta, "No se pudo desvincular el banco.");
  }
}
