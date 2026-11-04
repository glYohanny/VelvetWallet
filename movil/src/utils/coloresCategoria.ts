/**
 * El color de cada categoría, igual en toda la app.
 *
 * **El problema.** El color vivía solo dentro del anillo y se asignaba por
 * posición en ESE gráfico: `colorDeCategoria(categoria, indice)`. Como el orden
 * cambia según el mes que estés mirando, "Supermercado" podía ser rosado en
 * octubre y rojo oscuro en septiembre. Y fuera del anillo no existía: la lista
 * de movimientos era monocromática, así que no había forma de reconocer una
 * categoría de un vistazo ni de conectar la porción del gráfico con sus cargos.
 *
 * **La regla.** El color lo fija el **ranking de gasto de todo el historial**,
 * no el del mes en pantalla. Las cinco categorías en las que más gastas se
 * llevan la paleta, en orden de intensidad; el resto va en el gris de "Otros".
 * Es la misma regla que ya usa el anillo para decidir qué muestra y qué agrupa,
 * así que anillo y listas quedan de acuerdo por construcción.
 *
 * **Lo que se pierde, dicho explícitamente.** Antes la intensidad del color
 * seguía el orden de magnitud *del mes*: la porción más gruesa era siempre la
 * más intensa. Ahora sigue el orden de magnitud *del historial*, así que dentro
 * de un mes puntual puede no coincidir. Es un intercambio deliberado: el largo
 * del arco ya dice cuánto pesa cada porción en ese mes, y gastar el color
 * también en eso era redundante. A cambio, el color pasa a significar *qué*
 * categoría es, que es información que antes no estaba en ninguna parte.
 *
 * Se mantiene dentro del rojo de la marca: la paleta es una escala del acento,
 * no colores arbitrarios.
 */
import { useMemo } from "react";

import type { Movimiento } from "@/modelo/tipos";
import { expandirPartes } from "@/utils/porciones";
import { colorOtros, paletaCategorias } from "@/constants/tema";
import { useMovimientos } from "@/datos/MovimientosContexto";
import { OTROS, SIN_CATEGORIA } from "@/utils/resumen";

/** Cuántas categorías reciben color propio. El mismo tope que usa el anillo. */
export const CON_COLOR_PROPIO = paletaCategorias.length;

export type PaletaDeCategorias = {
  /** Color de una categoría. Las que no están en el ranking caen al gris. */
  color: (categoria: string) => string;
  /** Ranking completo, de la que más gasto acumula a la que menos. */
  ranking: string[];
};

/** Gris para lo que no tiene color propio: "Otros" y la cola del ranking. */
function esNeutra(categoria: string): boolean {
  return categoria === OTROS || categoria === SIN_CATEGORIA;
}

/**
 * Construye la paleta a partir de TODOS los movimientos cargados.
 *
 * Usar todo el historial y no el mes visible es justamente lo que hace que el
 * color sea estable mientras la persona navega entre meses y pantallas.
 */
export function construirPaleta(movimientos: Movimiento[]): PaletaDeCategorias {
  const totales = new Map<string, number>();
  for (const m of expandirPartes(movimientos)) {
    if (m.monto >= 0 || m.excluido) continue;
    const clave = m.categoria ?? SIN_CATEGORIA;
    if (esNeutra(clave)) continue;
    totales.set(clave, (totales.get(clave) ?? 0) + Math.abs(m.monto));
  }

  // Desempate por nombre: con dos categorías empatadas, el orden no puede
  // depender de en qué orden llegaron los movimientos del banco.
  const ranking = [...totales.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([categoria]) => categoria);

  const asignados = new Map<string, string>();
  ranking.slice(0, CON_COLOR_PROPIO).forEach((categoria, i) => {
    asignados.set(categoria, paletaCategorias[i]);
  });

  return {
    color: (categoria: string) => asignados.get(categoria) ?? colorOtros,
    ranking,
  };
}

/**
 * La paleta del usuario, lista para usar en cualquier pantalla.
 *
 * Se recalcula solo cuando cambian los movimientos, que es cuando de verdad
 * puede cambiar el ranking.
 */
export function usePaletaCategorias(): PaletaDeCategorias {
  const { movimientos } = useMovimientos();
  return useMemo(() => construirPaleta(movimientos), [movimientos]);
}

/**
 * Fondo del avatar o del cuadro de un movimiento, teñido con su categoría.
 *
 * Es el color al 14% sobre la superficie, no el color puro: un avatar saturado
 * por fila convierte la lista en un semáforo y le quita el protagonismo al
 * monto, que es lo que la persona vino a leer.
 */
export function tinte(color: string, opacidad = 0.14): string {
  if (color.startsWith("rgba")) return color;
  const n = color.replace("#", "");
  const r = parseInt(n.slice(0, 2), 16);
  const g = parseInt(n.slice(2, 4), 16);
  const b = parseInt(n.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${opacidad})`;
}
