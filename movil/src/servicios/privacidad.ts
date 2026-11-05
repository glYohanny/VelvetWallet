/**
 * Privacidad y derechos del titular (Ley 21.719).
 *
 * Consentimiento por finalidad, lo que la persona autorizó, la bitácora de lo
 * que se hizo con sus datos, la copia descargable y la supresión de la cuenta.
 *
 * El consentimiento de tratamiento está separado de la vinculación del banco a
 * propósito: autorizar que Velvet LEA tus datos no autoriza a USARLOS para
 * otra cosa. Cada finalidad se consiente, vence y se revoca por su cuenta.
 */
import { tokenActual } from "@/servicios/auth";
import { api } from "@/servicios/servidor";

export class ErrorPrivacidad extends Error {}

export type Finalidad = {
  id: string;
  titulo: string;
  resumen: string;
  detalle: string[];
  vigenciaDias: number;
  consentido: boolean;
  desde: string | null;
  vence: string | null;
  /** El texto cambió desde que lo aceptó: hay que volver a preguntarle. */
  textoDesactualizado: boolean;
};

export type ConsentimientoBancario = {
  id: string;
  institucion: string;
  estado: string;
  desde: string | null;
  vence: string | null;
  permisos: string[];
};

export type ConsentimientoTratamiento = {
  finalidad: string;
  titulo: string;
  estado: string;
  desde: string | null;
  vence: string | null;
  revocado: string | null;
  versionTexto: string;
};

export type EventoBitacora = {
  accion: string;
  descripcion: string;
  recurso: string;
  ip: string | null;
  cuando: string;
};

async function pedir(ruta: string, opciones: RequestInit = {}): Promise<any> {
  const token = await tokenActual();
  if (!token) throw new ErrorPrivacidad("Tu sesión expiró. Vuelve a entrar.");

  let r: Response;
  try {
    r = await fetch(`${api()}/api/privacidad${ruta}`, {
      ...opciones,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        ...(opciones.headers ?? {}),
      },
    });
  } catch {
    throw new ErrorPrivacidad("No se pudo conectar con el servidor.");
  }

  const datos = await r.json().catch(() => null);
  if (!r.ok) {
    const detalle = (datos as { detail?: unknown })?.detail;
    throw new ErrorPrivacidad(
      typeof detalle === "string" ? detalle : `El servidor respondió ${r.status}.`,
    );
  }
  return datos;
}

export async function obtenerFinalidades(): Promise<Finalidad[]> {
  const cuerpo = await pedir("/finalidades");
  return cuerpo.finalidades.map((f: any) => ({
    id: f.id,
    titulo: f.titulo,
    resumen: f.resumen,
    detalle: f.detalle,
    vigenciaDias: f.vigencia_dias,
    consentido: f.consentido,
    desde: f.desde,
    vence: f.vence,
    textoDesactualizado: f.textoDesactualizado,
  }));
}

/** Otorga o revoca. Revocar no borra el registro de que hubo consentimiento. */
export async function decidirFinalidad(id: string, acepta: boolean): Promise<void> {
  await pedir(`/finalidades/${id}`, { method: "POST", body: JSON.stringify({ acepta }) });
}

export async function obtenerConsentimientos(): Promise<{
  bancarios: ConsentimientoBancario[];
  tratamiento: ConsentimientoTratamiento[];
}> {
  return pedir("/consentimientos");
}

export async function obtenerBitacora(): Promise<EventoBitacora[]> {
  return (await pedir("/bitacora")).eventos;
}

/**
 * Copia de los datos del titular (portabilidad).
 *
 * Devuelve el JSON ya listo para guardar. Quien llama decide qué hacer con él,
 * porque descargar un archivo no se hace igual en el navegador que en el
 * teléfono.
 */
export async function exportarDatos(): Promise<unknown> {
  return pedir("/exportar");
}

/**
 * Supresión de la cuenta. `confirmacion` debe ser el correo del titular: el
 * backend lo exige, porque un borrado irreversible no puede depender de un
 * toque suelto.
 */
export async function eliminarCuenta(confirmacion: string): Promise<void> {
  await pedir("/cuenta", { method: "DELETE", body: JSON.stringify({ confirmacion }) });
}
