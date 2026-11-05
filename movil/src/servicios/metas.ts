/**
 * Metas de ahorro.
 *
 *   GET    /api/metas       -> metas con su proyección
 *   POST   /api/metas       -> crear
 *   PATCH  /api/metas/{id}  -> actualizar
 *   DELETE /api/metas/{id}  -> eliminar
 *
 * La proyección llega calculada desde el backend; la app no hace la
 * matemática. Es a propósito: el mismo motor que responde acá tiene que
 * responder igual en cualquier otro cliente, y una simulación duplicada en dos
 * lenguajes sería dos simulaciones que se pueden desviar sin que nadie lo note.
 */
import type { Meta } from "@/modelo/tipos";
import { tokenActual } from "@/servicios/auth";
import { api } from "@/servicios/servidor";

export class ErrorMetas extends Error {}

type Cuerpo = Record<string, unknown>;

async function pedir(ruta: string, metodo = "GET", cuerpo?: Cuerpo): Promise<unknown> {
  const token = await tokenActual();
  if (!token) throw new ErrorMetas("Tu sesión expiró. Vuelve a entrar.");

  let r: Response;
  try {
    r = await fetch(`${api()}/api/metas${ruta}`, {
      method: metodo,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: cuerpo ? JSON.stringify(cuerpo) : undefined,
    });
  } catch {
    throw new ErrorMetas("No se pudo conectar con el servidor.");
  }

  if (r.status === 204) return null;
  const datos = await r.json().catch(() => null);
  if (!r.ok) {
    const detalle = (datos as { detail?: unknown })?.detail;
    throw new ErrorMetas(typeof detalle === "string" ? detalle : "No se pudo completar la operación.");
  }
  return datos;
}

export async function listarMetas(): Promise<{ metas: Meta[]; mesesObservados: number }> {
  return (await pedir("")) as { metas: Meta[]; mesesObservados: number };
}

export type MetaNueva = {
  nombre: string;
  montoObjetivo: number;
  montoAhorrado: number;
  /** "AAAA-MM-DD". Opcional: el plazo que la persona se propone. */
  fechaObjetivo?: string | null;
};

export async function crearMeta(nueva: MetaNueva): Promise<Meta> {
  return (await pedir("", "POST", {
    nombre: nueva.nombre.trim(),
    montoObjetivo: nueva.montoObjetivo,
    montoAhorrado: nueva.montoAhorrado,
    fechaObjetivo: nueva.fechaObjetivo || null,
  })) as Meta;
}

export async function actualizarMeta(id: string, cambios: Partial<MetaNueva>): Promise<Meta> {
  return (await pedir(`/${id}`, "PATCH", cambios as Cuerpo)) as Meta;
}

export async function eliminarMeta(id: string): Promise<void> {
  await pedir(`/${id}`, "DELETE");
}
