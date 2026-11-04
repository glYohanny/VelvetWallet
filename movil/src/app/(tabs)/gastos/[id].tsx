/**
 * Detalle de un movimiento: lo que dijo el banco, lo que entendió el sistema,
 * las acciones de corrección y la trazabilidad.
 *
 * La regla que esta pantalla hace visible: la corrección del usuario se guarda
 * aparte y el dato original del banco nunca se modifica (RF-14 / RNF-31).
 */
import { useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { Boton } from "@/components/Boton";
import { Ficha } from "@/components/Ficha";
import { Tocable } from "@/components/Movimiento";
import { Nota, Pantalla, Seccion } from "@/components/Pantalla";
import { colores, espacio, fuente, radio } from "@/constants/tema";
import { useMovimientos } from "@/datos/MovimientosContexto";
import type { Conexion, Correccion, Movimiento, OrigenMovimiento } from "@/modelo/tipos";
import { CATEGORIAS_DE_GASTO } from "@/datos/categorias";
import {
  borrarMovimiento,
  excluirMovimiento,
  marcarDuplicado,
  unirMovimiento,
  volverAContar,
} from "@/servicios/cargas";
import { fechaCorta, fechaHora, pesos } from "@/utils/formato";

const ORIGEN: Record<OrigenMovimiento, string> = {
  sfa: "API SFA",
  cartola: "Cartola CSV",
  manual: "Carga manual",
};

const TIPO_CORRECCION: Record<Correccion["tipo"], string> = {
  recategorizar: "Recategorizado",
  marcar_duplicado: "Marcado duplicado",
  excluir: "Excluido",
  dividir: "Dividido",
};

/** Cuántos días de distancia se aceptan para proponer un duplicado. */
const DIAS_DUPLICADO = 10;

/**
 * Los que podrían ser el mismo movimiento: mismo monto, fechas cercanas, y que
 * sí cuentan (marcar duplicado de uno que tampoco cuenta dejaría ninguno).
 */
function candidatosADuplicado(m: Movimiento, todos: Movimiento[]): Movimiento[] {
  const t = new Date(m.fecha).getTime();
  return todos
    .filter(
      (x) =>
        x.id !== m.id &&
        !x.excluido &&
        x.monto === m.monto &&
        Math.abs(new Date(x.fecha).getTime() - t) <= DIAS_DUPLICADO * 86_400_000,
    )
    .sort((a, b) => Math.abs(new Date(a.fecha).getTime() - t) - Math.abs(new Date(b.fecha).getTime() - t));
}

/**
 * Tipo de la cuenta a la que pertenece el movimiento ("Cuenta Corriente").
 *
 * El cruce va por `idExterno` y no por `id`: el movimiento trae el
 * identificador que le puso la institución, no el nuestro.
 */
function tipoCuenta(m: Movimiento, conexiones: Conexion[]): string | undefined {
  for (const c of conexiones) {
    const cuenta = c.cuentas.find((x) => x.idExterno === m.cuentaId);
    if (cuenta) return cuenta.tipo;
  }
}

/**
 * Cómo se decidió la categoría, en lenguaje natural.
 *
 * Es trazabilidad de la decisión, no una métrica: responde "¿por qué esto
 * quedó en Supermercado?". Y cuando el sistema no alcanzó la confianza
 * mínima, lo dice en vez de callarlo: la abstención es una decisión, no un
 * vacío (RNF-33).
 */
function describirClasificacion(m: Movimiento): string {
  if (m.estadoCategoria === "corregida") {
    // En lo anotado a mano no hubo nada que corregir: la eligió al anotarlo.
    return m.origen === "manual" && m.correcciones.length === 0
      ? "La elegiste tú al anotarlo"
      : "Lo corregiste tú";
  }
  if (m.categoria === null) return "El sistema no alcanzó la confianza mínima";

  switch (m.origenClasificacion) {
    case "modelo":
      return m.confianza !== null
        ? `El modelo, con ${Math.min(99, Math.round(m.confianza * 100))}% de confianza`
        : "El modelo";
    case "regla":
      return "Una regla: comercio conocido";
    case "banco":
      return "La categoría que mandó la institución";
    case "usuario":
      return "Lo corregiste tú";
    default:
      return "Sin información de quién la decidió";
  }
}

function resumenCorrecciones(lista: Correccion[]): string {
  if (lista.length === 0) return "Ninguna";
  if (lista.length === 1) return TIPO_CORRECCION[lista[0].tipo];
  // Deshacer no borra la corrección anterior: las dos quedan en la historia.
  return `${lista.length} correcciones`;
}

type Panel = null | "categoria" | "duplicado";

export default function DetalleMovimiento() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { movimientos, conexiones, quitarMovimiento, reemplazarMovimiento, corregirCategoria } =
    useMovimientos();
  const m = movimientos.find((x) => x.id === id);
  const [panel, setPanel] = useState<Panel>(null);
  const [trabajando, setTrabajando] = useState(false);
  const [errorCorregir, setErrorCorregir] = useState<string | null>(null);

  /** Cada corrección devuelve el movimiento como quedó: se pone tal cual. */
  async function corregir(accion: () => Promise<Movimiento>) {
    setTrabajando(true);
    setErrorCorregir(null);
    try {
      reemplazarMovimiento(await accion());
      setPanel(null);
    } catch (e) {
      setErrorCorregir(e instanceof Error ? e.message : "No se pudo guardar la corrección.");
    } finally {
      setTrabajando(false);
    }
  }
  const [confirmarBorrar, setConfirmarBorrar] = useState(false);
  const [borrando, setBorrando] = useState(false);
  const [errorBorrar, setErrorBorrar] = useState<string | null>(null);

  async function borrar() {
    if (!m) return;
    setBorrando(true);
    setErrorBorrar(null);
    try {
      await borrarMovimiento(m.id);
      router.back();
      quitarMovimiento(m.id);
    } catch (e) {
      setErrorBorrar(e instanceof Error ? e.message : "No se pudo borrar.");
      setBorrando(false);
    }
  }

  if (!m) {
    return (
      <Pantalla titulo="Movimiento" onAtras={() => router.back()}>
        <Nota>No se encontró el movimiento {id}.</Nota>
      </Pantalla>
    );
  }

  const esCargo = m.monto < 0;
  const tipo = tipoCuenta(m, conexiones);
  const subtitulo = [m.institucion, tipo !== m.institucion ? tipo : null, fechaHora(m.fecha)]
    .filter(Boolean)
    .join(" · ");
  const sinIdentificar = m.comercio === null;
  const decision = describirClasificacion(m);
  const original = m.duplicadoDe ? movimientos.find((x) => x.id === m.duplicadoDe) : undefined;
  const candidatos = panel === "duplicado" ? candidatosADuplicado(m, movimientos) : [];
  const alternar = (p: Panel) => () => {
    setErrorCorregir(null);
    setPanel(panel === p ? null : p);
  };

  // Solo lo que tiene sentido para este movimiento. Un excluido no se corrige
  // más: primero vuelve a contar. Un abono no tiene categoría de gasto.
  const acciones: { texto: string; alTocar: () => void; panel?: Panel }[] = m.excluido
    ? []
    : [
        ...(esCargo
          ? [{ texto: "Asignar categoría", alTocar: alternar("categoria"), panel: "categoria" as Panel }]
          : []),
        ...(esCargo && !m.partes?.length
          ? [{ texto: "Dividir en varias", alTocar: () => router.push(`/gastos/dividir?id=${m.id}`) }]
          : []),
        { texto: "Marcar duplicado", alTocar: alternar("duplicado"), panel: "duplicado" as Panel },
        {
          texto: esCargo ? "Excluir del gasto" : "No es ingreso",
          alTocar: () => corregir(() => excluirMovimiento(m.id)),
        },
      ];

  return (
    <Pantalla titulo="Movimiento" etiqueta={fechaCorta(m.fecha)} onAtras={() => router.back()}>
      <Ficha
        encabezado={
          <View style={estilos.encabezado}>
            <Text style={estilos.monto}>
              {esCargo ? "" : "+"}
              {pesos(Math.abs(m.monto))}
            </Text>
            <Text style={estilos.subtitulo}>{subtitulo}</Text>
          </View>
        }
        filas={[
          { etiqueta: "Glosa original", valor: m.glosaOriginal, mono: true },
          { etiqueta: "Comercio", valor: m.comercio ?? "No identificado", destacar: sinIdentificar },
          {
            etiqueta: "Categoría",
            valor: m.partes?.length
              ? m.partes.map((p) => p.categoria).join(" + ")
              : (m.categoria ?? "Sin categorizar"),
            destacar: m.categoria === null && !m.partes?.length,
          },
          { etiqueta: "Clasificó", valor: decision, destacar: m.categoria === null },
          ...(m.categoriaBanco ? [{ etiqueta: "Categoría del banco", valor: m.categoriaBanco }] : []),
          {
            etiqueta: "Estado",
            valor: !m.excluido ? "Cuenta" : m.motivoExclusion === "duplicado" ? "Duplicado" : "Excluido",
          },
          {
            etiqueta: (m.fuentes?.length ?? 1) > 1 ? "Fuentes" : "Origen",
            // Llegó por dos caminos y es UN movimiento: se dicen los dos (RF-09).
            valor: (m.fuentes?.length ? m.fuentes : [m.origen]).map((f) => ORIGEN[f]).join(" + "),
          },
        ]}
      />

      {m.excluido ? (
        <View style={estilos.estado}>
          <Text style={estilos.estadoTitulo}>
            {m.motivoExclusion === "duplicado" ? "Es un duplicado: no cuenta" : "No cuenta como gasto"}
          </Text>
          {original ? (
            <Text style={estilos.estadoDetalle} onPress={() => router.push(`/gastos/${original.id}`)}>
              El que cuenta: {original.comercio ?? original.glosaOriginal} ·{" "}
              {fechaCorta(original.fecha)} · {original.institucion}
            </Text>
          ) : null}
          <Text style={estilos.enlace} onPress={() => corregir(() => volverAContar(m.id))}>
            Volver a contarlo
          </Text>
        </View>
      ) : null}

      {m.partes?.length ? (
        <View style={estilos.estado}>
          <Text style={estilos.estadoTitulo}>Repartido entre categorías</Text>
          {m.partes.map((p) => (
            <View key={p.categoria} style={estilos.parte}>
              <Text style={estilos.parteNombre}>{p.categoria}</Text>
              <Text style={estilos.parteMonto}>{pesos(Math.abs(p.monto))}</Text>
            </View>
          ))}
          <Text style={estilos.enlace} onPress={() => corregir(() => unirMovimiento(m.id))}>
            Deshacer el reparto
          </Text>
        </View>
      ) : null}

      {acciones.length > 0 ? (
        <>
          <Seccion titulo="Corregir" />
          <View style={estilos.acciones}>
            {acciones.map((a) => (
              <Tocable
                key={a.texto}
                onPress={a.alTocar}
                style={[estilos.accion, panel === a.panel && a.panel !== undefined && estilos.accionActiva]}
              >
                <Text style={estilos.accionTexto}>{a.texto}</Text>
              </Tocable>
            ))}
          </View>
        </>
      ) : null}

      {panel === "categoria" ? (
        <View style={estilos.panel}>
          {CATEGORIAS_DE_GASTO.map((c) => (
            <Tocable
              key={c}
              onPress={() => {
                corregirCategoria(m.id, c);
                setPanel(null);
              }}
              style={[estilos.chip, c === m.categoria && estilos.chipActivo]}
            >
              <Text style={[estilos.chipTexto, c === m.categoria && estilos.chipTextoActivo]}>{c}</Text>
            </Tocable>
          ))}
        </View>
      ) : null}

      {panel === "duplicado" ? (
        <View style={estilos.estado}>
          {candidatos.length === 0 ? (
            <Text style={estilos.estadoDetalle}>
              No hay otro movimiento por {pesos(Math.abs(m.monto))} cerca de esta fecha. Si este no
              corresponde, usa Excluir del gasto.
            </Text>
          ) : (
            <>
              <Text style={estilos.estadoTitulo}>¿De cuál es duplicado?</Text>
              {candidatos.slice(0, 5).map((c) => (
                <Tocable
                  key={c.id}
                  onPress={() => corregir(() => marcarDuplicado(m.id, c.id))}
                  style={estilos.candidato}
                >
                  <Text style={estilos.parteNombre} numberOfLines={1}>
                    {c.comercio ?? c.glosaOriginal}
                  </Text>
                  <Text style={estilos.estadoDetalle}>
                    {fechaCorta(c.fecha)} · {c.institucion}
                  </Text>
                </Tocable>
              ))}
            </>
          )}
        </View>
      ) : null}

      {trabajando ? <Text style={estilos.estadoDetalle}>Guardando…</Text> : null}
      {errorCorregir ? <Text style={estilos.errorBorrar}>{errorCorregir}</Text> : null}

      <Seccion titulo="Trazabilidad" />
      <Ficha
        filas={[
          { etiqueta: "Recibido", valor: fechaHora(m.recibidoEn) },
          { etiqueta: "Payload crudo", valor: m.payloadCrudoRef ?? "—", mono: true },
          { etiqueta: "Correcciones", valor: resumenCorrecciones(m.correcciones) },
        ]}
      />

      {m.origen === "manual" ? (
        <>
          {confirmarBorrar ? (
            <View style={estilos.borrar}>
              <Text style={estilos.borrarTexto}>¿Borrar este movimiento?</Text>
              <Boton titulo="Sí, borrar" onPress={borrar} cargando={borrando} />
              <Boton titulo="No" onPress={() => setConfirmarBorrar(false)} secundario />
            </View>
          ) : (
            <Text style={estilos.enlaceBorrar} onPress={() => setConfirmarBorrar(true)}>
              Borrar este movimiento
            </Text>
          )}
          {errorBorrar ? <Text style={estilos.errorBorrar}>{errorBorrar}</Text> : null}
          <Text style={estilos.pie}>Lo anotaste tú: lo puedes borrar si te equivocaste.</Text>
        </>
      ) : (
        <Text style={estilos.pie}>Tu corrección no modifica el dato del banco.</Text>
      )}
    </Pantalla>
  );
}

const estilos = StyleSheet.create({
  encabezado: { paddingTop: espacio.l, paddingBottom: espacio.m, gap: espacio.xs },
  monto: { color: colores.texto, fontFamily: fuente.titulo, fontSize: 40, letterSpacing: -1 },
  subtitulo: { color: colores.texto2, fontFamily: fuente.texto, fontSize: 15 },
  acciones: { flexDirection: "row", flexWrap: "wrap", gap: espacio.m },
  accion: {
    // Dos por fila: mitad del ancho menos la mitad del espacio entre ambas
    width: "48%",
    flexGrow: 1,
    backgroundColor: colores.tarjeta,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colores.borde,
    borderTopColor: colores.bordeAlto,
    borderRadius: radio.m,
    paddingVertical: espacio.l,
    alignItems: "center",
  },
  accionTexto: { color: colores.texto, fontFamily: fuente.textoFuerte, fontSize: 15 },
  accionActiva: { borderColor: colores.acento, borderTopColor: colores.acento },
  estado: {
    backgroundColor: colores.tarjeta,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colores.borde,
    borderTopColor: colores.bordeAlto,
    borderRadius: radio.m,
    padding: espacio.l,
    gap: espacio.s,
    marginTop: espacio.l,
  },
  estadoTitulo: { color: colores.texto, fontFamily: fuente.textoFuerte, fontSize: 15 },
  estadoDetalle: { color: colores.texto2, fontFamily: fuente.texto, fontSize: 14 },
  enlace: { color: colores.acento, fontFamily: fuente.textoFuerte, fontSize: 14, marginTop: espacio.xs },
  parte: { flexDirection: "row", justifyContent: "space-between", gap: espacio.m },
  parteNombre: { color: colores.texto, fontFamily: fuente.textoMedio, fontSize: 15, flexShrink: 1 },
  parteMonto: { color: colores.texto, fontFamily: fuente.textoFuerte, fontSize: 15 },
  candidato: {
    paddingVertical: espacio.s,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colores.linea,
    gap: 2,
  },
  panel: { flexDirection: "row", flexWrap: "wrap", gap: espacio.s, marginTop: espacio.l },
  chip: {
    paddingHorizontal: espacio.m,
    paddingVertical: espacio.s,
    borderRadius: radio.m,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colores.borde,
    backgroundColor: colores.tarjeta,
  },
  chipActivo: { backgroundColor: colores.acentoSuave, borderColor: colores.acento },
  chipTexto: { color: colores.texto2, fontFamily: fuente.textoMedio, fontSize: 14 },
  chipTextoActivo: { color: colores.acento },
  borrar: { gap: espacio.s, marginTop: espacio.l },
  borrarTexto: { color: colores.texto, fontFamily: fuente.textoFuerte, fontSize: 15, textAlign: "center" },
  enlaceBorrar: {
    color: colores.alerta,
    fontFamily: fuente.textoFuerte,
    fontSize: 15,
    textAlign: "center",
    marginTop: espacio.l,
  },
  errorBorrar: { color: colores.acento, fontFamily: fuente.textoMedio, fontSize: 14, textAlign: "center" },
  pie: {
    color: colores.texto2,
    fontFamily: fuente.texto,
    fontSize: 14,
    textAlign: "center",
    marginTop: espacio.l,
  },
});
