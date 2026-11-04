/**
 * Un gasto dividido entre categorías (RF-14): cuenta como sus partes al
 * repartir por categoría, y como uno solo para todo lo demás.
 */
import { desglosar } from "@/utils/desglose";
import { expandirPartes } from "@/utils/porciones";
import { repartoPorCategoria, resumenDelMes } from "@/utils/resumen";

import { movimiento } from "./ayuda";

const MES = "2026-09";

const compra = movimiento({
  monto: -50_000,
  categoria: "Supermercado",
  partes: [
    { monto: -35_000, categoria: "Supermercado" },
    { monto: -15_000, categoria: "Hogar" },
  ],
});
const otra = movimiento({ monto: -10_000, categoria: "Hogar", comercio: "Sodimac" });

describe("gasto dividido", () => {
  it("se reparte entre sus categorías", () => {
    const { porciones, total } = repartoPorCategoria([compra, otra], MES);
    const por = Object.fromEntries(porciones.map((p) => [p.categoria, p.monto]));
    expect(por).toEqual({ Supermercado: 35_000, Hogar: 25_000 });
    expect(total).toBe(60_000);
  });

  it("el total del mes no cambia por dividirlo", () => {
    const sinDividir = { ...compra, partes: null };
    expect(resumenDelMes([compra, otra], MES).gastos).toBe(resumenDelMes([sinDividir, otra], MES).gastos);
  });

  it("el detalle de una categoría muestra solo la parte que le toca", () => {
    const d = desglosar([compra, otra], "Hogar", MES);
    expect(d.total).toBe(25_000);
    expect(d.grupos.flatMap((g) => g.movimientos).map((m) => m.monto).sort((a, b) => a - b)).toEqual([-15_000, -10_000]);
  });

  it("uno sin partes, o con una sola, queda igual", () => {
    expect(expandirPartes([otra])).toEqual([otra]);
    expect(expandirPartes([{ ...otra, partes: [{ monto: -10_000, categoria: "Hogar" }] }])).toHaveLength(1);
  });

  it("un excluido no cuenta aunque esté dividido", () => {
    const { total } = repartoPorCategoria([{ ...compra, excluido: true }, otra], MES);
    expect(total).toBe(10_000);
  });
});
