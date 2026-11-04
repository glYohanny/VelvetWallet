/**
 * Importar una cartola CSV (RF-12).
 *
 * Para lo que el SFA no cubre: un banco que no participa del sistema, o los
 * meses anteriores a conectar el banco. El flujo tiene un paso de revisión a
 * propósito: antes de guardar nada se muestra qué se entendió del archivo
 * (qué columna es la fecha, cuántos movimientos, cuáles ya estaban) y qué
 * líneas no se pudieron leer. Un archivo mal interpretado que entra directo
 * ensucia meses de datos; uno revisado, no.
 */
import { useRouter } from "expo-router";
import { useMemo, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { Boton } from "@/components/Boton";
import { Campo } from "@/components/Campo";
import { Chips } from "@/components/Chips";
import { Ficha } from "@/components/Ficha";
import { Nota, Pantalla, Seccion } from "@/components/Pantalla";
import { colores, espacio, fuente, radio } from "@/constants/tema";
import { useMovimientos } from "@/datos/MovimientosContexto";
import {
  elegirCartola,
  importarCartola,
  type ArchivoElegido,
  type Destino,
  type ResultadoCartola,
} from "@/servicios/cargas";
import { fechaConAnio } from "@/utils/formato";

const OTRO_BANCO = "otro";

const TIPOS_CUENTA = [
  { valor: "corriente", etiqueta: "Cuenta corriente" },
  { valor: "vista", etiqueta: "Cuenta vista" },
  { valor: "ahorro", etiqueta: "Ahorro" },
  { valor: "tarjeta", etiqueta: "Tarjeta de crédito" },
];

/** Cómo se le llama a cada columna que el lector reconoció. */
const ROL: Record<string, string> = {
  fecha: "Fecha",
  glosa: "Descripción",
  monto: "Monto",
  cargo: "Cargos",
  abono: "Abonos",
};

const MAX_RECHAZADAS_A_LA_VISTA = 5;

function plural(n: number, uno: string, varios: string): string {
  return `${n} ${n === 1 ? uno : varios}`;
}

export default function ImportarCartola() {
  const router = useRouter();
  const { conexiones, recargar } = useMovimientos();

  // Solo las cuentas que pueden tener cartola: el efectivo se anota a mano.
  const cuentas = useMemo(
    () =>
      conexiones
        .filter((c) => c.fuente !== "manual")
        .flatMap((c) => c.cuentas.map((cu) => ({
          valor: cu.id,
          etiqueta: `${c.institucion} · ${cu.tipo}${cu.numeroEnmascarado ? " " + cu.numeroEnmascarado : ""}`,
        }))),
    [conexiones],
  );

  const [destino, setDestino] = useState<string>(cuentas[0]?.valor ?? OTRO_BANCO);
  const [institucion, setInstitucion] = useState("");
  const [tipoCuenta, setTipoCuenta] = useState("corriente");
  const [archivo, setArchivo] = useState<ArchivoElegido | null>(null);
  const [vista, setVista] = useState<ResultadoCartola | null>(null);
  const [trabajando, setTrabajando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [listo, setListo] = useState<string | null>(null);

  const elDestino: Destino | null =
    destino !== OTRO_BANCO
      ? { cuentaId: destino }
      : institucion.trim().length >= 2
        ? { institucion: institucion.trim(), tipoCuenta }
        : null;

  /** Cualquier cambio de destino o de archivo invalida la vista previa. */
  function cambiar<T>(poner: (v: T) => void) {
    return (v: T) => {
      poner(v);
      setVista(null);
      setListo(null);
      setError(null);
    };
  }

  async function elegir() {
    setError(null);
    setListo(null);
    try {
      const a = await elegirCartola();
      if (a) {
        setArchivo(a);
        setVista(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo abrir el archivo.");
    }
  }

  async function revisar() {
    if (!archivo || !elDestino) return;
    setTrabajando(true);
    setError(null);
    try {
      setVista(await importarCartola(archivo, elDestino, true));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo leer la cartola.");
    } finally {
      setTrabajando(false);
    }
  }

  async function confirmar() {
    if (!archivo || !elDestino) return;
    setTrabajando(true);
    setError(null);
    try {
      const r = await importarCartola(archivo, elDestino, false);
      await recargar();
      setListo(
        r.nuevas + r.fusionadas === 0
          ? "No había nada nuevo: todo ya estaba en Velvet."
          : `Listo: ${plural(r.nuevas, "movimiento nuevo", "movimientos nuevos")}` +
              (r.fusionadas ? `, y ${r.fusionadas} que ya tenías quedaron con las dos fuentes.` : "."),
      );
      setArchivo(null);
      setVista(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo importar la cartola.");
    } finally {
      setTrabajando(false);
    }
  }

  const columnas = vista
    ? Object.entries(vista.columnas).map(([rol, nombre]) => `${ROL[rol] ?? rol}: "${nombre}"`).join(" · ")
    : "";

  return (
    <Pantalla titulo="Importar cartola" onAtras={() => router.back()}>
      <Nota>
        Sirve para un banco que no está en el Sistema de Finanzas Abiertas, o para traer los meses
        anteriores a conectar tu banco. Descárgala desde el sitio de tu banco en formato CSV.
      </Nota>

      <Seccion titulo="¿De qué cuenta es?" />
      <Chips
        opciones={[...cuentas, { valor: OTRO_BANCO, etiqueta: "Otro banco" }]}
        valor={destino}
        onCambio={cambiar(setDestino)}
      />
      {destino === OTRO_BANCO ? (
        <View style={estilos.campos}>
          <Campo
            etiqueta="Nombre del banco"
            placeholder="Banco Estado"
            value={institucion}
            onChangeText={cambiar(setInstitucion)}
            maxLength={80}
          />
          <Chips opciones={TIPOS_CUENTA} valor={tipoCuenta} onCambio={cambiar(setTipoCuenta)} />
        </View>
      ) : null}

      <Seccion titulo="Archivo" />
      {archivo ? (
        <View style={estilos.archivo}>
          <Text style={estilos.archivoNombre} numberOfLines={1}>{archivo.nombre}</Text>
          <Text style={estilos.enlace} onPress={elegir}>Cambiar</Text>
        </View>
      ) : (
        <Boton titulo="Elegir archivo CSV" onPress={elegir} secundario />
      )}

      {vista ? (
        <>
          <Seccion titulo="Esto vamos a importar" />
          <Ficha
            filas={[
              { etiqueta: "Leídos", valor: plural(vista.leidas, "movimiento", "movimientos") },
              { etiqueta: "Nuevos", valor: String(vista.nuevas), destacar: vista.nuevas > 0 },
              ...(vista.fusionadas
                ? [{ etiqueta: "Ya los trajo tu banco", valor: `${vista.fusionadas} (no se duplican)` }]
                : []),
              ...(vista.repetidas
                ? [{ etiqueta: "Ya importados antes", valor: String(vista.repetidas) }]
                : []),
              ...(vista.desde && vista.hasta
                ? [{ etiqueta: "Período", valor: `${fechaConAnio(vista.desde)} – ${fechaConAnio(vista.hasta)}` }]
                : []),
            ]}
          />
          <Text style={estilos.columnas}>Columnas que reconocimos · {columnas}</Text>
          {vista.rechazadas.length > 0 ? (
            <View style={estilos.rechazadas}>
              <Text style={estilos.rechazadasTitulo}>
                {vista.rechazadas.length === 1
                  ? "1 línea no se pudo leer y no se importa:"
                  : `${vista.rechazadas.length} líneas no se pudieron leer y no se importan:`}
              </Text>
              {vista.rechazadas.slice(0, MAX_RECHAZADAS_A_LA_VISTA).map((r) => (
                <Text key={r.linea} style={estilos.rechazada}>
                  Línea {r.linea}: {r.motivo}
                </Text>
              ))}
              {vista.rechazadas.length > MAX_RECHAZADAS_A_LA_VISTA ? (
                <Text style={estilos.rechazada}>
                  y {vista.rechazadas.length - MAX_RECHAZADAS_A_LA_VISTA} más.
                </Text>
              ) : null}
            </View>
          ) : null}
          <Boton
            titulo={vista.nuevas > 0 ? `Importar ${plural(vista.nuevas, "movimiento", "movimientos")}` : "Importar"}
            onPress={confirmar}
            cargando={trabajando}
            deshabilitado={vista.nuevas + vista.fusionadas === 0}
            style={estilos.boton}
          />
        </>
      ) : archivo ? (
        <Boton
          titulo="Revisar antes de importar"
          onPress={revisar}
          cargando={trabajando}
          deshabilitado={!elDestino}
          style={estilos.boton}
        />
      ) : null}

      {listo ? <Text style={estilos.listo}>{listo}</Text> : null}
      {error ? <Text style={estilos.error}>{error}</Text> : null}

      <Nota>
        Si un movimiento de la cartola ya llegó desde tu banco, no se duplica: queda uno solo, con
        las dos fuentes anotadas. Puedes importar la misma cartola dos veces sin problema.
      </Nota>
    </Pantalla>
  );
}

const estilos = StyleSheet.create({
  campos: { gap: espacio.m },
  archivo: {
    flexDirection: "row",
    alignItems: "center",
    gap: espacio.m,
    backgroundColor: colores.tarjeta,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colores.borde,
    borderTopColor: colores.bordeAlto,
    borderRadius: radio.m,
    padding: espacio.l,
  },
  archivoNombre: { flex: 1, color: colores.texto, fontFamily: fuente.textoMedio, fontSize: 15 },
  enlace: { color: colores.acento, fontFamily: fuente.textoFuerte, fontSize: 14 },
  columnas: { color: colores.texto3, fontFamily: fuente.texto, fontSize: 13, marginTop: espacio.s },
  rechazadas: { marginTop: espacio.m, gap: 2 },
  rechazadasTitulo: { color: colores.alerta, fontFamily: fuente.textoFuerte, fontSize: 14 },
  rechazada: { color: colores.texto2, fontFamily: fuente.texto, fontSize: 13 },
  boton: { marginTop: espacio.l },
  listo: { color: colores.ok, fontFamily: fuente.textoMedio, fontSize: 14, marginTop: espacio.m },
  error: { color: colores.acento, fontFamily: fuente.textoMedio, fontSize: 14, marginTop: espacio.m },
});
