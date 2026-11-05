/**
 * Suscripciones y gastos recurrentes detectados.
 *
 * El detector vive en el backend (motor/recurrencias.py) y corre en cada
 * sincronización. La app no detecta nada: muestra lo detectado y recoge la
 * decisión de la persona sobre cada una.
 */
import { tokenActual } from "@/servicios/auth";
import { api } from "@/servicios/servidor";

export class ErrorSuscripciones extends Error {}

export type EstadoSuscripcion = "detectada" | "confirmada" | "descartada";

export type Suscripcion = {
  id: string;
  nombre: string;
  /** "mensual", "semanal"… null si el detector no pudo determinarla. */
  periodicidad: string | null;
  montoEsperado: number | null;
  /** "AAAA-MM-DD" del próximo cobro estimado. */
  proximaFecha: string | null;
  estado: EstadoSuscripcion;
  cobros: number;
  ultimoCobro: string | null;
};

async function pedir(ruta: string, opciones: RequestInit = {}): Promise<any> {
  const token = await tokenActual();
  if (!token) throw new ErrorSuscripciones("Tu sesión expiró. Vuelve a entrar.");

  let r: Response;
  try {
    r = await fetch(`${api()}/api/suscripciones${ruta}`, {
      ...opciones,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        ...(opciones.headers ?? {}),
      },
    });
  } catch {
    throw new ErrorSuscripciones("No se pudo conectar con el servidor.");
  }

  const datos = await r.json().catch(() => null);
  if (!r.ok) {
    const detalle = (datos as { detail?: unknown })?.detail;
    throw new ErrorSuscripciones(
      typeof detalle === "string" ? detalle : `El servidor respondió ${r.status}.`,
    );
  }
  return datos;
}

export async function obtenerSuscripciones(): Promise<{
  suscripciones: Suscripcion[];
  /** Total mensual equivalente, sin contar las descartadas. */
  comprometidoAlMes: number;
  porRevisar: number;
}> {
  return pedir("");
}

export async function decidirSuscripcion(
  id: string,
  estado: "confirmada" | "descartada",
): Promise<void> {
  await pedir(`/${id}`, { method: "PATCH", body: JSON.stringify({ estado }) });
}
