/**
 * Gastos — los cargos de un mes, filtrables por tipo y categoría.
 *
 * "Fijos" son los que el detector de recurrencias marcó como periódicos
 * (arriendo, suscripciones, cuentas del hogar). "Variables" es todo lo demás.
 * Los meses y las categorías disponibles salen de los datos, no están fijos.
 */
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { Aviso } from "@/components/Aviso";
import { Chips } from "@/components/Chips";
import { EsqueletoLista } from "@/components/Esqueleto";
import { Fila, GrupoDeFilas } from "@/components/Fila";
import { FilaMovimiento } from "@/components/FilaMovimiento";
import { Nota, Pantalla } from "@/components/Pantalla";
import { Segmentos } from "@/components/Segmentos";
import { SelectorMes } from "@/components/SelectorMes";
import { colores, espacio, fuente } from "@/constants/tema";
import { useMovimientos } from "@/datos/MovimientosContexto";
import { claveMes, pesos } from "@/utils/formato";

type Tipo = "todos" | "fijos" | "variables";

const TIPOS: { valor: Tipo; etiqueta: string }[] = [
  { valor: "todos", etiqueta: "Todos" },
  { valor: "fijos", etiqueta: "Fijos" },
  { valor: "variables", etiqueta: "Variables" },
];

const TODAS = "__todas__";
const SIN_CATEGORIA = "__sin__";

export default function Gastos() {
  const router = useRouter();
  const { movimientos, novedades, cargaInicial, marcarVistas } = useMovimientos();

  // Meses con datos, del más reciente al más antiguo.
  const meses = useMemo(
    () => [...new Set(movimientos.map((m) => claveMes(m.fecha)))].sort().reverse(),
    [movimientos],
  );

  // El mes mostrado se deriva, no se guarda: al entrar directo a esta pantalla
  // los movimientos todavía no han llegado, así que `meses` viene vacío y un
  // estado inicializado con `meses[0]` se quedaría en undefined durante el
  // render siguiente, cuando ya hay datos pero el estado aún no se actualizó.
  // Derivarlo también resuelve que una sincronización traiga un mes nuevo o se
  // lleve el elegido: siempre cae al más reciente que exista.
  const [mesElegido, setMesElegido] = useState<string | null>(null);
  const mes = mesElegido && meses.includes(mesElegido) ? mesElegido : meses[0];

  const [tipo, setTipo] = useState<Tipo>("todos");
  const [categoria, setCategoria] = useState<string>(TODAS);

  // Al salir de la pantalla, las novedades dejan de estar destacadas: ya se
  // vieron. Se hace al salir y no al entrar para que se alcancen a ver.
  useFocusEffect(useCallback(() => () => marcarVistas(), [marcarVistas]));

  const cargosDelMes = useMemo(
    () => movimientos.filter((m) => m.monto < 0 && claveMes(m.fecha) === mes),
    [movimientos, mes],
  );

  // Chips de categoría: las que existen este mes, más "Sin categorizar" si hay.
  const opcionesCategoria = useMemo(() => {
    const presentes = [...new Set(cargosDelMes.map((m) => m.categoria).filter(Boolean))] as string[];
    const opciones = [{ valor: TODAS, etiqueta: "Todas" }, ...presentes.sort().map((c) => ({ valor: c, etiqueta: c }))];
    if (cargosDelMes.some((m) => m.categoria === null)) {
      opciones.push({ valor: SIN_CATEGORIA, etiqueta: "Sin categorizar" });
    }
    return opciones;
  }, [cargosDelMes]);

  const visibles = useMemo(() => {
    let lista = cargosDelMes;
    if (tipo === "fijos") lista = lista.filter((m) => m.esRecurrente);
    if (tipo === "variables") lista = lista.filter((m) => !m.esRecurrente);
    if (categoria === SIN_CATEGORIA) lista = lista.filter((m) => m.categoria === null);
    else if (categoria !== TODAS) lista = lista.filter((m) => m.categoria === categoria);
    return lista;
  }, [cargosDelMes, tipo, categoria]);

  const total = visibles.reduce((suma, m) => suma + Math.abs(m.monto), 0);
  const sinCategorizar = cargosDelMes.filter((m) => m.estadoCategoria === "sin_categoria").length;

  // Al cambiar de mes, la categoría elegida puede no existir: se vuelve a "Todas".
  function cambiarMes(nuevo: string) {
    setMesElegido(nuevo);
    setCategoria(TODAS);
  }

  // La primera carga aún no vuelve: se reserva la forma de la lista en vez de
  // decir que no hay movimientos, que todavía no se sabe.
  if (cargaInicial) {
    return (
      <Pantalla titulo="Gastos">
        <EsqueletoLista />
      </Pantalla>
    );
  }

  // Usuario sin movimientos todavía (p. ej. recién registrado): nada que listar.
  if (movimientos.length === 0) {
    return (
      <Pantalla titulo="Gastos">
        <Nota>Aún no tienes movimientos. Sincroniza para ver tus gastos aquí.</Nota>
        <View style={estilos.fijos}>
          <GrupoDeFilas>
            <Fila
              titulo="Anotar un gasto en efectivo"
              icono="cash-outline"
              onPress={() => router.push("/gastos/nuevo")}
              ultima
            />
          </GrupoDeFilas>
        </View>
      </Pantalla>
    );
  }

  return (
    <Pantalla titulo="Gastos" accesorio={<SelectorMes meses={meses} valor={mes} onCambio={cambiarMes} />}>
      <Segmentos opciones={TIPOS} valor={tipo} onCambio={setTipo} />
      {/* key={mes}: al cambiar de mes la fila se reconstruye y vuelve al inicio */}
      <Chips key={mes} opciones={opcionesCategoria} valor={categoria} onCambio={setCategoria} />

      <View style={estilos.resumen}>
        <Text style={estilos.resumenTexto}>
          {visibles.length} {visibles.length === 1 ? "movimiento" : "movimientos"}
        </Text>
        <Text style={estilos.resumenTotal}>{pesos(total)}</Text>
      </View>

      {sinCategorizar > 0 ? (
        <Aviso
          detalle="Tócalos para asignarles una categoría."
          onPress={() => router.push("/gastos/por-revisar")}
        >
          {sinCategorizar} {sinCategorizar === 1 ? "movimiento" : "movimientos"} por categorizar.
        </Aviso>
      ) : null}

      {/* Los gastos fijos no se leen bien en una lista mes a mes: lo que
          interesa de ellos es cuánto suman y cada cuánto vuelven. */}
      <View style={estilos.fijos}>
        <GrupoDeFilas>
          <Fila
            titulo="Gastos fijos y suscripciones"
            detalle="Cuánto suman y cada cuánto vuelven"
            icono="repeat"
            onPress={() => router.push("/gastos/suscripciones")}
          />
          <Fila
            titulo="Anotar un gasto en efectivo"
            detalle="Lo que no pasa por ningún banco"
            icono="cash-outline"
            onPress={() => router.push("/gastos/nuevo")}
            ultima
          />
        </GrupoDeFilas>
      </View>

      <View style={estilos.lista}>
        {visibles.map((m) => (
          <FilaMovimiento
            key={m.id}
            movimiento={m}
            onPress={() => router.push(`/gastos/${m.id}`)}
            novedad={
              novedades.nuevos.includes(m.id)
                ? "nuevo"
                : m.id in novedades.actualizados
                  ? "actualizado"
                  : undefined
            }
            montoAnterior={novedades.actualizados[m.id]}
          />
        ))}
      </View>

      {visibles.length === 0 ? <Nota>No hay movimientos con estos filtros.</Nota> : null}
    </Pantalla>
  );
}

const estilos = StyleSheet.create({
  fijos: { marginTop: espacio.m },
  resumen: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "baseline",
    paddingBottom: espacio.s,
  },
  resumenTexto: { color: colores.texto3, fontFamily: fuente.texto, fontSize: 13 },
  resumenTotal: { color: colores.texto2, fontFamily: fuente.tituloMedio, fontSize: 15 },
  lista: { marginTop: espacio.s },
});
