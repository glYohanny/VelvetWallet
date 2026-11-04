/**
 * Desglose de una categoría de gasto — "¿en qué se fue, dentro de esto?".
 *
 * El panel responde en qué se va la plata **por categoría**, y ahí se detiene:
 * dice "Supermercado $386.053" y no dice en qué supermercado ni en qué compras.
 * Esa es la pregunta que queda colgando, y es la que resuelve este módulo.
 *
 * Dos decisiones que vale la pena poder defender:
 *
 *  · **Se agrupa por comercio, no se lista plano.** Treinta movimientos en una
 *    lista no explican nada; cinco comercios ordenados por monto sí. El detalle
 *    queda un nivel más abajo, para quien lo quiera.
 *
 *  · **"Otros" se desglosa por categoría y no por comercio.** No es una
 *    categoría real: es el resto que el gráfico agrupa para no mostrar quince
 *    porciones. Lo que falta saber de "Otros" es qué categorías lo componen,
 *    así que el desglose pivota un nivel distinto según lo que se abra.
 *
 * Los montos se devuelven en positivo: son gastos, y el signo lo pone la
 * pantalla. Dentro de cada grupo los movimientos van de mayor a menor, porque
 * la pregunta es dónde se fue más y no qué pasó primero.
 */
import type { Movimiento } from "@/modelo/tipos";
import { claveMes } from "@/utils/formato";
import { expandirPartes } from "@/utils/porciones";
import { OTROS, SIN_CATEGORIA } from "@/utils/resumen";

/** Cuántas categorías muestra el gráfico antes de agrupar el resto en "Otros". */
export const CATEGORIAS_EN_EL_GRAFICO = 5;

export type GrupoDeGasto = {
  /** Comercio normalizado, o la glosa del banco si no hay comercio reconocido. */
  nombre: string;
  /** No hay comercio identificado: se está mostrando la glosa en crudo. */
  sinIdentificar: boolean;
  total: number;
  cantidad: number;
  /** Fracción del total de la categoría, entre 0 y 1. */
  fraccion: number;
  /** De mayor a menor monto. */
  movimientos: Movimiento[];
};

export type Desglose = {
  categoria: string;
  total: number;
  cantidad: number;
  /** Fracción del gasto total del período, entre 0 y 1. */
  fraccionDelGasto: number;
  /** El cargo más grande de la categoría. null si no hay ninguno. */
  mayor: Movimiento | null;
  grupos: GrupoDeGasto[];
  /** Qué representa cada grupo. "Otros" se abre por categoría; el resto, por comercio. */
  agrupadoPor: "comercio" | "categoria";
};

/** Un conjunto de meses, o uno solo, como predicado sobre la clave de mes. */
function dentroDe(meses: string | Set<string>): (clave: string) => boolean {
  return typeof meses === "string" ? (m) => m === meses : (m) => meses.has(m);
}

/** Cargos del período, sin los excluidos. Los abonos no son gasto. */
function cargos(movimientos: Movimiento[], meses: string | Set<string>): Movimiento[] {
  const incluye = dentroDe(meses);
  // Un gasto dividido cuenta como sus partes, cada una en su categoría.
  return expandirPartes(
    movimientos.filter((m) => m.monto < 0 && !m.excluido && incluye(claveMes(m.fecha))),
  );
}

/** La categoría con que se muestra un movimiento. */
function categoriaDe(m: Movimiento): string {
  return m.categoria ?? SIN_CATEGORIA;
}

function sumarPor(movimientos: Movimiento[], clave: (m: Movimiento) => string): Map<string, number> {
  const totales = new Map<string, number>();
  for (const m of movimientos) {
    const k = clave(m);
    totales.set(k, (totales.get(k) ?? 0) + Math.abs(m.monto));
  }
  return totales;
}

/**
 * Las categorías que el gráfico muestra con nombre propio, de mayor a menor.
 *
 * Se necesita para resolver "Otros": lo que hay dentro es, por definición, todo
 * lo que no entró en esta lista.
 */
export function categoriasPrincipales(
  movimientos: Movimiento[],
  meses: string | Set<string>,
  maximo = CATEGORIAS_EN_EL_GRAFICO,
): string[] {
  return [...sumarPor(cargos(movimientos, meses), categoriaDe).entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, maximo)
    .map(([categoria]) => categoria);
}

/**
 * La categoría en que más se gastó en el período: el "gasto más grande".
 *
 * Devuelve null cuando no hay gasto. No se inventa una categoría vacía: un cero
 * presentado como el mayor gasto es una cifra engañosa.
 */
export function categoriaMasGrande(
  movimientos: Movimiento[],
  meses: string | Set<string>,
): { categoria: string; monto: number; fraccion: number } | null {
  const totales = sumarPor(cargos(movimientos, meses), categoriaDe);
  const total = [...totales.values()].reduce((s, n) => s + n, 0);
  if (total === 0) return null;

  const [categoria, monto] = [...totales.entries()].sort((a, b) => b[1] - a[1])[0];
  return { categoria, monto, fraccion: monto / total };
}

/**
 * Desglose de una categoría dentro del período.
 *
 * `categoria` puede ser el nombre de una categoría, "Sin categorizar", o
 * "Otros"; en ese último caso se agrupa por categoría en vez de por comercio.
 */
export function desglosar(
  movimientos: Movimiento[],
  categoria: string,
  meses: string | Set<string>,
  maximo = CATEGORIAS_EN_EL_GRAFICO,
): Desglose {
  const todos = cargos(movimientos, meses);
  const gastoDelPeriodo = todos.reduce((s, m) => s + Math.abs(m.monto), 0);

  const esOtros = categoria === OTROS;
  const principales = esOtros ? new Set(categoriasPrincipales(movimientos, meses, maximo)) : null;

  const propios = esOtros
    ? todos.filter((m) => !principales!.has(categoriaDe(m)))
    : todos.filter((m) => categoriaDe(m) === categoria);

  const total = propios.reduce((s, m) => s + Math.abs(m.monto), 0);

  // Dentro de "Otros" lo que falta saber es qué categorías hay; en una
  // categoría concreta, qué comercios.
  const clave = esOtros ? categoriaDe : (m: Movimiento) => m.comercio ?? m.glosaOriginal;

  const porGrupo = new Map<string, Movimiento[]>();
  for (const m of propios) {
    const k = clave(m);
    const items = porGrupo.get(k);
    if (items) items.push(m);
    else porGrupo.set(k, [m]);
  }

  const grupos: GrupoDeGasto[] = [...porGrupo.entries()]
    .map(([nombre, items]) => {
      const suma = items.reduce((s, m) => s + Math.abs(m.monto), 0);
      return {
        nombre,
        // En "Otros" el nombre es una categoría, y una categoría siempre está
        // identificada; el aviso de glosa en crudo solo aplica a comercios.
        sinIdentificar: !esOtros && items.every((m) => !m.comercio),
        total: suma,
        cantidad: items.length,
        fraccion: total === 0 ? 0 : suma / total,
        movimientos: [...items].sort((a, b) => Math.abs(b.monto) - Math.abs(a.monto)),
      };
    })
    .sort((a, b) => b.total - a.total);

  const mayor = propios.length === 0
    ? null
    : propios.reduce((a, b) => (Math.abs(b.monto) > Math.abs(a.monto) ? b : a));

  return {
    categoria,
    total,
    cantidad: propios.length,
    fraccionDelGasto: gastoDelPeriodo === 0 ? 0 : total / gastoDelPeriodo,
    mayor,
    grupos,
    agrupadoPor: esOtros ? "categoria" : "comercio",
  };
}
