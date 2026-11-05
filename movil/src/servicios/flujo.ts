/**
 * Excedente mensual y flujo de caja hasta el día de pago (RF-23, RF-25).
 *
 *   GET /api/flujo -> { excedente, flujo }
 *
 * Son dos respuestas distintas y la app no debe mezclarlas: el excedente dice
 * con cuánto se parte el mes y no cambia de un día para otro; la holgura dice
 * cuánto queda realmente libre hoy y cambia todos los días.
 */
import { tokenActual } from "@/servicios/auth";
import { api } from "@/servicios/servidor";

export class ErrorFlujo extends Error {}

/** Lo estructural: qué queda del sueldo después de lo comprometido. */
export type Excedente = {
  ingreso: number;
  gastosFijos: number;
  cuotas: number;
  /** ingreso − gastosFijos − cuotas. Puede ser negativo, y eso es un dato. */
  excedente: number;
  /** false si no se conoce el sueldo: entonces la cifra no se puede leer igual. */
  ingresoConocido: boolean;
};

export type Cargo = {
  nombre: string;
  monto: number;
  fecha: string;
};

/** Lo de caja: qué pasa de aquí al próximo sueldo. */
export type FlujoDeCaja = {
  saldo: number;
  proximoPago: string;
  dias: number;
  /** Cargos conocidos que caen antes del próximo sueldo. */
  comprometido: number;
  /** saldo − comprometido: lo que de verdad está libre hoy. */
  holgura: number;
  /** Estimación del gasto variable de los días que faltan. */
  gastoEstimado: number;
  /** Con qué saldo se llegaría al día de pago. */
  proyectado: number;
  /** Meses de historial que respaldan la estimación. */
  mesesObservados: number;
  proximosCargos: Cargo[];
};

export type RespuestaFlujo = {
  excedente: Excedente;
  /** null cuando no se sabe cuándo llega el sueldo: no se inventa un horizonte. */
  flujo: FlujoDeCaja | null;
};

export async function obtenerFlujo(): Promise<RespuestaFlujo> {
  const token = await tokenActual();
  if (!token) throw new ErrorFlujo("Tu sesión no está activa. Inicia sesión de nuevo.");

  let respuesta: Response;
  try {
    respuesta = await fetch(`${api()}/api/flujo`, {
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch {
    throw new ErrorFlujo("No se pudo conectar con el servidor.");
  }
  if (!respuesta.ok) throw new ErrorFlujo("No se pudo calcular tu flujo del mes.");
  return (await respuesta.json()) as RespuestaFlujo;
}
