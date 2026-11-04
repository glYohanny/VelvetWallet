/**
 * Cálculos del resumen del mes — la pregunta "¿cuánto tengo disponible?".
 *
 * Solo lógica, sin nada visual. Cuando exista el backend, estas mismas reglas
 * se implementan allá y la app recibe el resultado: el disponible lo necesitan
 * también el motor de proyección y las metas, y tiene que salir igual en todos.
 *
 * Reglas:
 *  · Ingresos del mes = el sueldo detectado, no los abonos recibidos ese mes.
 *    El sueldo llega a fin de mes; si se contaran abonos, hasta ese día el
 *    disponible sería negativo. Principio heredado de la v1: el sueldo se
 *    mantiene mes a mes.
 *  · Gastos del mes = cargos del mes hasta hoy, sin los excluidos.
 *  · Disponible = ingresos − gastos.
 */
import type { Conexion, Movimiento } from "@/modelo/tipos";
import { claveMes } from "@/utils/formato";
import { expandirPartes } from "@/utils/porciones";

export type ResumenMes = {
  mes: string;
  ingresos: number;
  gastos: number;
  disponible: number;
  cantidadGastos: number;
  /** Día del mes en que llega el sueldo, según el historial. */
  diaDePago: number | null;
};

/**
 * Sueldo detectado.
 *
 * Preferimos el abono ya categorizado como "Sueldo" (cuando exista el
 * clasificador). Mientras tanto, como el backend aún no categoriza, se detecta
 * por heurística: el ingreso recurrente más reciente que NO sea una
 * transferencia entre cuentas propias. Así el disponible sale bien aunque la
 * categoría todavía no exista.
 */
export function sueldoDetectado(movimientos: Movimiento[]): Movimiento | null {
  const porCategoria = movimientos.find((m) => m.monto > 0 && m.categoria === "Sueldo");
  if (porCategoria) return porCategoria;

  const esTransferencia = (m: Movimiento) =>
    /transferencia/i.test(`${m.glosaOriginal ?? ""} ${m.comercio ?? ""}`);

  const abonos = movimientos
    .filter((m) => m.monto > 0 && !m.excluido && !esTransferencia(m))
    .sort((a, b) => (a.fecha < b.fecha ? 1 : -1)); // más reciente primero

  return abonos[0] ?? null;
}

export function resumenDelMes(movimientos: Movimiento[], mes: string): ResumenMes {
  const sueldo = sueldoDetectado(movimientos);
  const cargos = movimientos.filter((m) => m.monto < 0 && !m.excluido && claveMes(m.fecha) === mes);
  const gastos = cargos.reduce((suma, m) => suma + Math.abs(m.monto), 0);
  const ingresos = sueldo?.monto ?? 0;

  return {
    mes,
    ingresos,
    gastos,
    disponible: ingresos - gastos,
    cantidadGastos: cargos.length,
    diaDePago: sueldo ? new Date(sueldo.fecha).getDate() : null,
  };
}

/** Conexiones que no están al día, para el aviso del resumen. */
export function conexionesConProblema(conexiones: Conexion[]): Conexion[] {
  return conexiones.filter((c) => c.estado !== "al_dia");
}

// ───────────────────── gasto de los últimos meses ─────────────────────

export type GastoDelMes = {
  /** Clave "AAAA-MM". */
  mes: string;
  total: number;
  cantidad: number;
  /** El mes en curso va a medias: no se puede comparar de igual a igual. */
  parcial: boolean;
};

/**
 * Gasto total de los últimos `cuantos` meses, del más antiguo al más reciente.
 *
 * Se devuelven también los meses sin gastos, con total cero: un hueco en la
 * serie dice algo, y saltárselo haría que el gráfico mienta sobre el tiempo
 * transcurrido entre barras.
 *
 * El mes en curso se marca `parcial` porque va a medias. Compararlo de igual a
 * igual con meses completos siempre lo haría parecer una caída del gasto.
 */
export function gastoUltimosMeses(
  movimientos: Movimiento[],
  cuantos = 6,
  hoy: Date = new Date(),
): GastoDelMes[] {
  const mesActual = `${hoy.getFullYear()}-${String(hoy.getMonth() + 1).padStart(2, "0")}`;

  // Se parte del mes en curso y se retrocede, para que la serie termine hoy
  // aunque el último mes todavía no tenga movimientos.
  const meses: string[] = [];
  let cursor = mesActual;
  for (let i = 0; i < cuantos; i++) {
    meses.unshift(cursor);
    cursor = mesAnterior(cursor);
  }

  return meses.map((mes) => {
    const cargos = movimientos.filter(
      (m) => m.monto < 0 && !m.excluido && claveMes(m.fecha) === mes,
    );
    return {
      mes,
      total: cargos.reduce((suma, m) => suma + Math.abs(m.monto), 0),
      cantidad: cargos.length,
      parcial: mes === mesActual,
    };
  });
}

/**
 * Promedio mensual de gasto, **excluyendo el mes en curso** por estar a medias.
 * Es la línea de referencia contra la que se lee cada barra.
 */
export function promedioMensual(serie: GastoDelMes[]): number {
  const completos = serie.filter((g) => !g.parcial && g.total > 0);
  if (completos.length === 0) return 0;
  return completos.reduce((s, g) => s + g.total, 0) / completos.length;
}

// ───────────────────── en qué se va la plata ─────────────────────

export type PorcionCategoria = {
  categoria: string;
  monto: number;
  /** Fracción del gasto total del mes, entre 0 y 1. */
  fraccion: number;
};

/** Nombre con que se muestra un movimiento que el clasificador no categorizó. */
export const SIN_CATEGORIA = "Sin categorizar";

/** Nombre de la porción que agrupa a las categorías menores del gráfico. */
export const OTROS = "Otros";

/**
 * Suma los cargos por categoría dentro de uno o varios meses.
 *
 * `meses` acepta una clave sola o un conjunto. Pasar varias permite el reparto
 * de un período completo sin recorrer los movimientos una vez por mes.
 */
function totalesPorCategoria(
  movimientos: Movimiento[],
  meses: string | Set<string>,
): Map<string, number> {
  const incluye = typeof meses === "string" ? (m: string) => m === meses : (m: string) => meses.has(m);
  const totales = new Map<string, number>();
  for (const m of expandirPartes(movimientos)) {
    if (m.monto >= 0 || m.excluido || !incluye(claveMes(m.fecha))) continue;
    const clave = m.categoria ?? SIN_CATEGORIA;
    totales.set(clave, (totales.get(clave) ?? 0) + Math.abs(m.monto));
  }
  return totales;
}

/**
 * Reparto del gasto por categoría, de un mes o de un período.
 *
 * Se muestran las `maximo` más grandes y el resto se agrupa en "Otros": un
 * gráfico con quince porciones no comunica nada.
 */
export function repartoPorCategoria(
  movimientos: Movimiento[],
  mes: string | Set<string>,
  maximo = 5,
): { porciones: PorcionCategoria[]; total: number } {
  const totales = [...totalesPorCategoria(movimientos, mes).entries()].sort((a, b) => b[1] - a[1]);
  const total = totales.reduce((suma, [, monto]) => suma + monto, 0);
  if (total === 0) return { porciones: [], total: 0 };

  const principales = totales.slice(0, maximo);
  const resto = totales.slice(maximo).reduce((suma, [, monto]) => suma + monto, 0);

  const porciones: PorcionCategoria[] = principales.map(([categoria, monto]) => ({
    categoria,
    monto,
    fraccion: monto / total,
  }));
  if (resto > 0) porciones.push({ categoria: OTROS, monto: resto, fraccion: resto / total });

  return { porciones, total };
}

export type Variacion = {
  categoria: string;
  actual: number;
  anterior: number;
  /** Cambio porcentual. null cuando no había gasto el mes anterior. */
  porcentaje: number | null;
};

/** Mes anterior a "2026-09" → "2026-08". */
export function mesAnterior(mes: string): string {
  const anio = Number(mes.slice(0, 4));
  const numero = Number(mes.slice(5, 7));
  return numero === 1
    ? `${anio - 1}-12`
    : `${anio}-${String(numero - 1).padStart(2, "0")}`;
}

/**
 * Comparación con el mes anterior, ordenada por el cambio más grande.
 *
 * Solo tiene sentido si el mes anterior está completo; con el mes en curso a
 * medias, la comparación de totales siempre saldría a la baja.
 */
export function compararConMesAnterior(
  movimientos: Movimiento[],
  mes: string,
  cuantas = 3,
): { variaciones: Variacion[]; total: Variacion } | null {
  const previo = mesAnterior(mes);
  const actuales = totalesPorCategoria(movimientos, mes);
  const anteriores = totalesPorCategoria(movimientos, previo);
  if (anteriores.size === 0) return null;

  const cambio = (actual: number, anterior: number) =>
    anterior === 0 ? null : Math.round(((actual - anterior) / anterior) * 100);

  const variaciones: Variacion[] = [...new Set([...actuales.keys(), ...anteriores.keys()])]
    .map((categoria) => {
      const actual = actuales.get(categoria) ?? 0;
      const anterior = anteriores.get(categoria) ?? 0;
      return { categoria, actual, anterior, porcentaje: cambio(actual, anterior) };
    })
    // Las que aparecen en ambos meses y más se movieron, en valor absoluto.
    .filter((v) => v.porcentaje !== null && v.anterior > 0)
    .sort((a, b) => Math.abs(b.porcentaje!) - Math.abs(a.porcentaje!))
    .slice(0, cuantas);

  const sumar = (t: Map<string, number>) => [...t.values()].reduce((s, n) => s + n, 0);
  const totalActual = sumar(actuales);
  const totalAnterior = sumar(anteriores);

  return {
    variaciones,
    total: {
      categoria: "Total del mes",
      actual: totalActual,
      anterior: totalAnterior,
      porcentaje: cambio(totalActual, totalAnterior),
    },
  };
}
