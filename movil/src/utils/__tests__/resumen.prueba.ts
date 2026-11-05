/**
 * Pruebas de los cálculos del resumen: el disponible del mes, el reparto por
 * categoría y la comparación mensual.
 *
 * De estas funciones salen todas las cifras que ve el usuario. Si el
 * disponible está mal, la aplicación entera miente.
 */
import {
  compararConMesAnterior,
  conexionesConProblema,
  gastoUltimosMeses,
  mesAnterior,
  promedioMensual,
  repartoPorCategoria,
  resumenDelMes,
  sueldoDetectado,
} from "@/utils/resumen";
import type { Conexion } from "@/modelo/tipos";

import { movimiento, sueldo } from "./ayuda";

const EN_SEPTIEMBRE = "2026-09-15T12:00:00.000Z";
const EN_AGOSTO = "2026-08-15T12:00:00.000Z";

describe("sueldoDetectado", () => {
  it("encuentra el abono categorizado como sueldo", () => {
    const movimientos = [movimiento({ monto: -5_000 }), sueldo({ fecha: EN_SEPTIEMBRE })];

    expect(sueldoDetectado(movimientos)?.monto).toBe(850_000);
  });

  it("devuelve null si no hay ningún sueldo en el historial", () => {
    expect(sueldoDetectado([movimiento({ monto: -5_000 })])).toBeNull();
  });
});

describe("resumenDelMes", () => {
  it("el disponible es el sueldo menos los gastos del mes", () => {
    const movimientos = [
      sueldo({ fecha: EN_SEPTIEMBRE }),
      movimiento({ monto: -100_000, fecha: EN_SEPTIEMBRE }),
      movimiento({ monto: -50_000, fecha: EN_SEPTIEMBRE }),
    ];

    const r = resumenDelMes(movimientos, "2026-09");

    expect(r.ingresos).toBe(850_000);
    expect(r.gastos).toBe(150_000);
    expect(r.disponible).toBe(700_000);
    expect(r.cantidadGastos).toBe(2);
  });

  it("no cuenta los gastos de otros meses", () => {
    const movimientos = [
      sueldo({ fecha: EN_SEPTIEMBRE }),
      movimiento({ monto: -100_000, fecha: EN_SEPTIEMBRE }),
      movimiento({ monto: -999_999, fecha: EN_AGOSTO }),
    ];

    expect(resumenDelMes(movimientos, "2026-09").gastos).toBe(100_000);
  });

  it("no cuenta los movimientos que el usuario excluyó del gasto", () => {
    const movimientos = [
      sueldo({ fecha: EN_SEPTIEMBRE }),
      movimiento({ monto: -100_000, fecha: EN_SEPTIEMBRE }),
      // Transferencia entre cuentas propias: no es gasto.
      movimiento({ monto: -120_000, fecha: EN_SEPTIEMBRE, excluido: true }),
    ];

    expect(resumenDelMes(movimientos, "2026-09").gastos).toBe(100_000);
  });

  it("el disponible queda negativo cuando se gastó más que el sueldo", () => {
    const movimientos = [sueldo({ fecha: EN_SEPTIEMBRE }), movimiento({ monto: -900_000, fecha: EN_SEPTIEMBRE })];

    expect(resumenDelMes(movimientos, "2026-09").disponible).toBe(-50_000);
  });

  it("detecta el día de pago desde la fecha del sueldo", () => {
    const movimientos = [sueldo({ fecha: "2026-09-30T09:05:00.000Z" })];

    expect(resumenDelMes(movimientos, "2026-09").diaDePago).toBe(30);
  });
});

describe("repartoPorCategoria", () => {
  it("suma por categoría y calcula la fracción de cada una", () => {
    const movimientos = [
      movimiento({ monto: -60_000, categoria: "Supermercado", fecha: EN_SEPTIEMBRE }),
      movimiento({ monto: -20_000, categoria: "Supermercado", fecha: EN_SEPTIEMBRE }),
      movimiento({ monto: -20_000, categoria: "Transporte", fecha: EN_SEPTIEMBRE }),
    ];

    const r = repartoPorCategoria(movimientos, "2026-09");

    expect(r.total).toBe(100_000);
    expect(r.porciones[0]).toMatchObject({ categoria: "Supermercado", monto: 80_000, fraccion: 0.8 });
    expect(r.porciones[1]).toMatchObject({ categoria: "Transporte", monto: 20_000, fraccion: 0.2 });
  });

  it("agrupa en Otros lo que sobra del máximo de porciones", () => {
    const movimientos = ["A", "B", "C", "D"].map((categoria, i) =>
      movimiento({ monto: -(10_000 - i * 1_000), categoria, fecha: EN_SEPTIEMBRE }),
    );

    const r = repartoPorCategoria(movimientos, "2026-09", 2);

    expect(r.porciones.map((p) => p.categoria)).toEqual(["A", "B", "Otros"]);
    expect(r.porciones[2].monto).toBe(8_000 + 7_000);
  });

  it("las fracciones suman uno", () => {
    const movimientos = [
      movimiento({ monto: -33_333, categoria: "A", fecha: EN_SEPTIEMBRE }),
      movimiento({ monto: -33_333, categoria: "B", fecha: EN_SEPTIEMBRE }),
      movimiento({ monto: -33_334, categoria: "C", fecha: EN_SEPTIEMBRE }),
    ];

    const suma = repartoPorCategoria(movimientos, "2026-09").porciones.reduce((s, p) => s + p.fraccion, 0);

    expect(suma).toBeCloseTo(1);
  });

  it("los movimientos sin categoría se agrupan bajo Sin categorizar", () => {
    const movimientos = [movimiento({ monto: -10_000, categoria: null, fecha: EN_SEPTIEMBRE })];

    expect(repartoPorCategoria(movimientos, "2026-09").porciones[0].categoria).toBe("Sin categorizar");
  });

  it("un mes sin gastos devuelve el reparto vacío y no divide por cero", () => {
    const r = repartoPorCategoria([sueldo({ fecha: EN_SEPTIEMBRE })], "2026-09");

    expect(r.porciones).toHaveLength(0);
    expect(r.total).toBe(0);
  });
});

describe("mesAnterior", () => {
  it("resta un mes", () => {
    expect(mesAnterior("2026-09")).toBe("2026-08");
  });

  it("en enero retrocede al diciembre del año anterior", () => {
    expect(mesAnterior("2026-01")).toBe("2025-12");
  });
});

describe("compararConMesAnterior", () => {
  it("calcula el cambio porcentual por categoría", () => {
    const movimientos = [
      movimiento({ monto: -100_000, categoria: "Delivery", fecha: EN_AGOSTO }),
      movimiento({ monto: -140_000, categoria: "Delivery", fecha: EN_SEPTIEMBRE }),
    ];

    const r = compararConMesAnterior(movimientos, "2026-09");

    expect(r?.variaciones[0]).toMatchObject({ categoria: "Delivery", porcentaje: 40 });
    expect(r?.total.porcentaje).toBe(40);
  });

  it("un gasto que bajó da porcentaje negativo", () => {
    const movimientos = [
      movimiento({ monto: -100_000, categoria: "Salud", fecha: EN_AGOSTO }),
      movimiento({ monto: -53_000, categoria: "Salud", fecha: EN_SEPTIEMBRE }),
    ];

    expect(compararConMesAnterior(movimientos, "2026-09")?.variaciones[0].porcentaje).toBe(-47);
  });

  it("devuelve null cuando no hay mes anterior con el que comparar", () => {
    expect(compararConMesAnterior([movimiento({ fecha: EN_SEPTIEMBRE })], "2026-09")).toBeNull();
  });

  it("deja fuera las categorías que no existían el mes anterior, para no dividir por cero", () => {
    const movimientos = [
      movimiento({ monto: -50_000, categoria: "Salud", fecha: EN_AGOSTO }),
      movimiento({ monto: -50_000, categoria: "Salud", fecha: EN_SEPTIEMBRE }),
      movimiento({ monto: -80_000, categoria: "Vestuario", fecha: EN_SEPTIEMBRE }),
    ];

    const r = compararConMesAnterior(movimientos, "2026-09");

    expect(r?.variaciones.map((v) => v.categoria)).toEqual(["Salud"]);
  });
});

describe("gastoUltimosMeses", () => {
  // Un "hoy" fijo: si dependiera de la fecha real, la prueba fallaría sola
  // al cambiar de mes.
  const HOY = new Date("2026-10-20T12:00:00-03:00");

  it("devuelve tantos meses como se piden, terminando en el mes en curso", () => {
    const serie = gastoUltimosMeses([], 6, HOY);

    expect(serie).toHaveLength(6);
    expect(serie.map((g) => g.mes)).toEqual([
      "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10",
    ]);
  });

  it("marca el mes en curso como parcial y los demás no", () => {
    const serie = gastoUltimosMeses([], 3, HOY);

    expect(serie.map((g) => g.parcial)).toEqual([false, false, true]);
  });

  it("suma los cargos de cada mes por separado", () => {
    const movimientos = [
      movimiento({ monto: -100_000, fecha: "2026-09-10T12:00:00-03:00" }),
      movimiento({ monto: -50_000, fecha: "2026-09-20T12:00:00-03:00" }),
      movimiento({ monto: -30_000, fecha: "2026-10-02T12:00:00-03:00" }),
    ];

    const serie = gastoUltimosMeses(movimientos, 2, HOY);

    expect(serie[0]).toMatchObject({ mes: "2026-09", total: 150_000, cantidad: 2 });
    expect(serie[1]).toMatchObject({ mes: "2026-10", total: 30_000, cantidad: 1 });
  });

  it("incluye los meses sin gastos con total cero, para no romper la serie", () => {
    const movimientos = [movimiento({ monto: -10_000, fecha: "2026-10-02T12:00:00-03:00" })];

    const serie = gastoUltimosMeses(movimientos, 3, HOY);

    expect(serie.map((g) => g.total)).toEqual([0, 0, 10_000]);
  });

  it("no cuenta los abonos ni lo que el usuario excluyó", () => {
    const movimientos = [
      sueldo({ fecha: "2026-09-30T12:00:00-03:00" }),
      movimiento({ monto: -120_000, fecha: "2026-09-10T12:00:00-03:00", excluido: true }),
      movimiento({ monto: -40_000, fecha: "2026-09-11T12:00:00-03:00" }),
    ];

    expect(gastoUltimosMeses(movimientos, 2, HOY)[0].total).toBe(40_000);
  });

  it("cruza bien el cambio de año", () => {
    const serie = gastoUltimosMeses([], 3, new Date("2026-01-15T12:00:00-03:00"));

    expect(serie.map((g) => g.mes)).toEqual(["2025-11", "2025-12", "2026-01"]);
  });
});

describe("promedioMensual", () => {
  const HOY = new Date("2026-10-20T12:00:00-03:00");

  it("deja fuera el mes en curso, porque va a medias", () => {
    const movimientos = [
      movimiento({ monto: -800_000, fecha: "2026-08-10T12:00:00-03:00" }),
      movimiento({ monto: -900_000, fecha: "2026-09-10T12:00:00-03:00" }),
      // Octubre lleva poco: si entrara al promedio lo hundiría.
      movimiento({ monto: -50_000, fecha: "2026-10-02T12:00:00-03:00" }),
    ];

    const serie = gastoUltimosMeses(movimientos, 3, HOY);

    expect(promedioMensual(serie)).toBe(850_000);
  });

  it("sin meses completos devuelve cero y no divide por cero", () => {
    expect(promedioMensual(gastoUltimosMeses([], 3, HOY))).toBe(0);
  });
});

describe("repartoPorCategoria sobre varios meses", () => {
  it("acumula el período completo, no solo un mes", () => {
    const movimientos = [
      movimiento({ monto: -60_000, categoria: "Vivienda", fecha: "2026-08-05T12:00:00-03:00" }),
      movimiento({ monto: -40_000, categoria: "Vivienda", fecha: "2026-09-05T12:00:00-03:00" }),
      movimiento({ monto: -150_000, categoria: "Supermercado", fecha: "2026-09-12T12:00:00-03:00" }),
    ];

    const r = repartoPorCategoria(movimientos, new Set(["2026-08", "2026-09"]));

    // Vivienda suma 100.000 entre los dos meses; Supermercado 150.000 en uno.
    // Ordena por monto, así que Supermercado va primero.
    expect(r.total).toBe(250_000);
    expect(r.porciones[0]).toMatchObject({ categoria: "Supermercado", monto: 150_000 });
    expect(r.porciones[1]).toMatchObject({ categoria: "Vivienda", monto: 100_000 });
  });

  it("un mes suelto sigue funcionando igual que antes", () => {
    const movimientos = [
      movimiento({ monto: -60_000, categoria: "Vivienda", fecha: "2026-08-05T12:00:00-03:00" }),
      movimiento({ monto: -40_000, categoria: "Vivienda", fecha: "2026-09-05T12:00:00-03:00" }),
    ];

    expect(repartoPorCategoria(movimientos, "2026-09").total).toBe(40_000);
  });
});

describe("conexionesConProblema", () => {
  const conexion = (estado: Conexion["estado"]): Conexion => ({
    id: estado,
    institucion: "Banco",
    estado,
    ultimaSincronizacion: EN_SEPTIEMBRE,
    cuentas: [],
  });

  it("devuelve las que no están al día", () => {
    const todas = [conexion("al_dia"), conexion("sin_respuesta"), conexion("autorizacion_vencida")];

    expect(conexionesConProblema(todas).map((c) => c.estado)).toEqual([
      "sin_respuesta",
      "autorizacion_vencida",
    ]);
  });

  it("un banco con permiso vigente pero con el dato viejo también cuenta (RF-35)", () => {
    const viejo = { ...conexion("al_dia"), datoAntiguo: true };
    expect(conexionesConProblema([viejo])).toHaveLength(1);
  });

  it("las cartolas y el efectivo no se reportan: no hay banco al que preguntarle", () => {
    const cartola = { ...conexion("al_dia"), fuente: "cartola" as const, datoAntiguo: true };
    const efectivo = { ...conexion("al_dia"), fuente: "manual" as const };
    expect(conexionesConProblema([cartola, efectivo])).toEqual([]);
  });
});
