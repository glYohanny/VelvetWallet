/**
 * Brechas de seguridad que afectan al titular (Ley 21.719).
 *
 * El backend entrega solo las que afectan a quien pregunta: una persona no
 * tiene por qué enterarse de una brecha que no la tocó, y mezclarlas haría
 * que la suya se pierda entre las demás.
 */
import { tokenActual } from "@/servicios/auth";
import { api } from "@/servicios/servidor";

export class ErrorIncidentes extends Error {}

export type Incidente = {
  id: string;
  titulo: string;
  descripcion: string;
  datosAfectados: string;
  medidas: string | null;
  gravedad: "baja" | "media" | "alta";
  /** Cuándo ocurrió, si se sabe. Puede ser anterior a cuándo se detectó. */
  ocurrido: string | null;
  detectado: string;
  avisado: string;
  /** Cuándo el titular leyó el aviso. null = sin leer. */
  visto: string | null;
  autoridadAvisada: string | null;
  plazo: {
    venceEn: string;
    notificado: boolean;
    dentroDePlazo: boolean;
    descripcion: string;
  };
};

async function pedir(ruta: string, metodo = "GET"): Promise<any> {
  const token = await tokenActual();
  if (!token) throw new ErrorIncidentes("Tu sesión expiró. Vuelve a entrar.");

  let r: Response;
  try {
    r = await fetch(`${api()}/api/incidentes${ruta}`, {
      method: metodo,
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    });
  } catch {
    throw new ErrorIncidentes("No se pudo conectar con el servidor.");
  }

  const datos = await r.json().catch(() => null);
  if (!r.ok) {
    const detalle = (datos as { detail?: unknown })?.detail;
    throw new ErrorIncidentes(
      typeof detalle === "string" ? detalle : `El servidor respondió ${r.status}.`,
    );
  }
  return datos;
}

export async function obtenerIncidentes(): Promise<{
  incidentes: Incidente[];
  sinLeer: number;
}> {
  return pedir("");
}

export async function marcarIncidenteVisto(id: string): Promise<void> {
  await pedir(`/${id}/visto`, "POST");
}
