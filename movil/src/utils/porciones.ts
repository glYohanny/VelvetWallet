/**
 * Un gasto dividido entre categorías (RF-14), visto desde el reparto por
 * categoría.
 *
 * Para todo lo demás —el total del mes, la lista, el saldo— un movimiento
 * dividido sigue siendo UNO, por su monto completo. Solo al agrupar por
 * categoría cuenta como sus partes: la compra de $50.000 que fue $35.000 de
 * comida y $15.000 de la casa suma 35 en Supermercado y 15 en Hogar.
 *
 * Por eso se expande en un solo punto, aquí, y lo usan los tres lugares que
 * agrupan por categoría (desglose, resumen y paleta de colores). Así no puede
 * pasar que el gráfico reparta de una forma y el detalle de la categoría de otra.
 */
import type { Movimiento } from "@/modelo/tipos";

export function porCategoria(m: Movimiento): Movimiento[] {
  if (!m.partes || m.partes.length < 2) return [m];
  return m.partes.map((p) => ({ ...m, monto: p.monto, categoria: p.categoria }));
}

export function expandirPartes(movimientos: Movimiento[]): Movimiento[] {
  return movimientos.flatMap(porCategoria);
}
