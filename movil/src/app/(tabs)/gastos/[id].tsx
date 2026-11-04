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
import { borrarMovimiento } from "@/servicios/cargas";
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

const ACCIONES = ["Asignar categoría", "Dividir en varias", "Marcar duplicado", "Excluir del gasto"];

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
  return `${lista.length} correcciones`;
}

export default function DetalleMovimiento() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { movimientos, conexiones, quitarMovimiento } = useMovimientos();
  const m = movimientos.find((x) => x.id === id);
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
          { etiqueta: "Categoría", valor: m.categoria ?? "Sin categorizar", destacar: m.categoria === null },
          { etiqueta: "Clasificó", valor: decision, destacar: m.categoria === null },
          ...(m.categoriaBanco ? [{ etiqueta: "Categoría del banco", valor: m.categoriaBanco }] : []),
          { etiqueta: "Estado", valor: m.excluido ? "Excluido" : "Confirmado" },
          {
            etiqueta: (m.fuentes?.length ?? 1) > 1 ? "Fuentes" : "Origen",
            // Llegó por dos caminos y es UN movimiento: se dicen los dos (RF-09).
            valor: (m.fuentes?.length ? m.fuentes : [m.origen]).map((f) => ORIGEN[f]).join(" + "),
          },
        ]}
      />

      <Seccion titulo="Corregir" />
      <View style={estilos.acciones}>
        {ACCIONES.map((texto) => (
          <Tocable key={texto} style={estilos.accion}>
            <Text style={estilos.accionTexto}>{texto}</Text>
          </Tocable>
        ))}
      </View>

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
