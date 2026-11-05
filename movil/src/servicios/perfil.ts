/**
 * Perfil financiero: el sueldo mensual (RF-36).
 *
 *   GET /api/perfil        -> lo declarado y lo detectado en los abonos
 *   PUT /api/perfil/sueldo -> declara (o borra, con null) el sueldo
 *
 * El backend detecta el sueldo mirando los abonos que se repiten, así que la
 * pantalla puede proponerlo y pedir solo una confirmación. Escribir un monto
 * es fricción evitable cuando el dato ya llegó por el estándar.
 */
import { tokenActual } from "@/servicios/auth";
import { api } from "@/servicios/servidor";

export class ErrorPerfil extends Error {}

/** El sueldo que se ve en los abonos, con la evidencia que lo respalda. */
export type SueldoDetectado = {
  monto: number;
  /** La glosa tal como la escribe el banco, para que la persona la reconozca. */
  glosa: string;
  /** En cuántos meses distintos se vio. */
  meses: number;
  desde: string;
  hasta: string;
};

export type Perfil = {
  /** Lo que declaró la persona. null si nunca lo hizo. */
  sueldoDeclarado: number | null;
  /** Lo que se infiere de los abonos. null si no hay evidencia suficiente. */
  sueldoDetectado: SueldoDetectado | null;
};

async function pedir(ruta: string, opciones: RequestInit = {}): Promise<Perfil> {
  const token = await tokenActual();
  if (!token) throw new ErrorPerfil("Tu sesión no está activa. Inicia sesión de nuevo.");

  let respuesta: Response;
  try {
    respuesta = await fetch(`${api()}${ruta}`, {
      ...opciones,
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    });
  } catch {
    throw new ErrorPerfil("No se pudo conectar con el servidor.");
  }

  if (!respuesta.ok) {
    // El backend explica por qué rechazó el monto; ese texto es para mostrarlo.
    const detalle = await respuesta.json().catch(() => null);
    throw new ErrorPerfil(detalle?.detail ?? "No se pudo guardar el sueldo.");
  }
  return (await respuesta.json()) as Perfil;
}

export function obtenerPerfil(): Promise<Perfil> {
  return pedir("/api/perfil");
}

/** Declara el sueldo. `null` lo borra y vuelve a mandar el detectado. */
export function guardarSueldo(monto: number | null): Promise<Perfil> {
  return pedir("/api/perfil/sueldo", { method: "PUT", body: JSON.stringify({ monto }) });
}
