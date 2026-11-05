/**
 * Créditos del usuario, traídos por la API de Operaciones de Crédito del SFA.
 *
 * Llegan solos con la sincronización, igual que los movimientos: no hay carga
 * manual. Lo que el estándar no entrega —CAE, cuotas ya pagadas con su
 * desglose, tabla de amortización— tampoco está acá.
 */
import { tokenActual } from "@/servicios/auth";
import { api } from "@/servicios/servidor";

export class ErrorCreditos extends Error {}

export type Credito = {
  id: string;
  idExterno: string;
  institucion: string;
  producto: string;
  tipo: string | null;
  moneda: string;
  estado: string | null;
  montoOriginal: number | null;
  cuotaMensual: number | null;
  plazoMeses: number | null;
  cuotasRestantes: number | null;
  saldoActual: number | null;
  /** Tasa del periodo, en porcentaje. */
  tasaInteres: number | null;
  tipoTasa: string | null;
  proposito: string | null;
  diaDePago: number | null;
  enMora: boolean;
  /** El estándar entrega solo el enlace al calendario del proveedor. */
  calendarioUrl: string | null;
  actualizadoEn: string | null;
};

export async function obtenerCreditos(): Promise<{
  creditos: Credito[];
  cuotaTotalMensual: number;
  saldoTotal: number;
  vigentes: number;
}> {
  const token = await tokenActual();
  if (!token) throw new ErrorCreditos("Tu sesión expiró. Vuelve a entrar.");

  let r: Response;
  try {
    r = await fetch(`${api()}/api/creditos`, {
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch {
    throw new ErrorCreditos("No se pudo conectar con el servidor.");
  }

  const datos = await r.json().catch(() => null);
  if (!r.ok) {
    const detalle = (datos as { detail?: unknown })?.detail;
    throw new ErrorCreditos(
      typeof detalle === "string" ? detalle : `El servidor respondió ${r.status}.`,
    );
  }
  return datos;
}
