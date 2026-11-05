/**
 * Cuentas — instituciones conectadas y derechos sobre los datos.
 *
 * Los enlaces de "Tus datos" corresponden a derechos de la Ley 21.719:
 * información sobre las finalidades, acceso a lo autorizado, portabilidad,
 * registro de tratamiento, notificación de brechas y supresión.
 */
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { StyleSheet, View } from "react-native";

import { Boton } from "@/components/Boton";
import { Fila, GrupoDeFilas } from "@/components/Fila";
import { FilaConexion } from "@/components/FilaConexion";
import { Ficha } from "@/components/Ficha";
import { Aparecer } from "@/components/Movimiento";
import { Nota, Pantalla, Seccion } from "@/components/Pantalla";
import { colores, espacio, movimiento, radio } from "@/constants/tema";
import { useMovimientos } from "@/datos/MovimientosContexto";
import { useSesion } from "@/sesion/SesionContexto";
import { pesos } from "@/utils/formato";

/**
 * Los derechos del titular que reconoce la Ley 21.719, cada uno con su
 * pantalla. `peligro` marca el que no tiene vuelta atrás.
 *
 * El detalle no es decorativo: nombra el derecho legal que hay detrás, que es
 * justamente lo que un evaluador quiere ver conectado con la ley. El icono
 * además deja la lista legible de un vistazo, sin tener que leer seis títulos
 * parecidos.
 */
const DERECHOS: {
  texto: string;
  detalle: string;
  icono: keyof typeof Ionicons.glyphMap;
  ruta: string;
  peligro?: boolean;
}[] = [
  {
    texto: "Para qué usamos tus datos",
    detalle: "Finalidades del tratamiento",
    icono: "information-circle-outline",
    ruta: "/cuentas/privacidad",
  },
  {
    texto: "Qué autorizaste y por cuánto tiempo",
    detalle: "Consentimientos vigentes y revocación",
    icono: "key-outline",
    ruta: "/cuentas/autorizaciones",
  },
  {
    texto: "Descargar todos mis datos",
    detalle: "Derecho de portabilidad",
    icono: "download-outline",
    ruta: "/cuentas/exportar",
  },
  {
    texto: "Bitácora de accesos",
    detalle: "Registro de actividades de tratamiento",
    icono: "time-outline",
    ruta: "/cuentas/bitacora",
  },
  {
    texto: "Avisos de seguridad",
    detalle: "Notificación de brechas",
    icono: "shield-outline",
    ruta: "/cuentas/incidentes",
  },
  {
    texto: "Eliminar mi cuenta y mis datos",
    detalle: "Derecho de supresión",
    icono: "trash-outline",
    ruta: "/cuentas/eliminar",
    peligro: true,
  },
];

export default function Cuentas() {
  const router = useRouter();
  const { usuario, salir } = useSesion();
  // Las instituciones salen del backend, que es el único que sabe qué permiso
  // está vigente y de cuándo es el dato. La vinculación y la desvinculación
  // viven en Inicio: aquí solo se muestra el estado.
  const { conexiones, sincronizando, irAlBanco, completarVinculacion, desvincular } = useMovimientos();

  /** Renovar el permiso de ESE banco. En web la página se va al banco y vuelve a Inicio. */
  async function reautorizar(institucion: string) {
    try {
      const vuelta = await irAlBanco(institucion);
      if (vuelta?.banco === "vinculado") await completarVinculacion();
    } catch {
      // El mensaje queda en el error del contexto.
    }
  }

  // "Conectada" es una institución con permiso por el SFA: el efectivo y las
  // cartolas se muestran en la lista, pero no son conexiones.
  const conectadas = conexiones.filter((c) => (c.fuente ?? "sfa") === "sfa").length;
  const etiqueta = conectadas === 1 ? "1 conectada" : `${conectadas} conectadas`;

  return (
    <Pantalla titulo="Cuentas" etiqueta={sincronizando ? "Actualizando…" : etiqueta}>
      <Seccion titulo="Tu perfil" />
      <Ficha
        filas={[
          { etiqueta: "Nombre", valor: usuario?.nombre ?? "—" },
          { etiqueta: "Correo", valor: usuario?.email ?? "—" },
          {
            etiqueta: "Sueldo mensual",
            // Sin declarar no se muestra el estimado: aquí solo cabe una línea
            // y un número sin su evidencia al lado se lee como un hecho. La
            // estimación se explica en su pantalla, donde sí cabe justificarla.
            valor: usuario?.sueldoDeclarado != null ? pesos(usuario.sueldoDeclarado) : "Sin declarar",
            destacar: usuario?.sueldoDeclarado == null,
          },
        ]}
      />
      <View style={estilos.sueldo}>
        <GrupoDeFilas>
          <Fila
            titulo={usuario?.sueldoDeclarado != null ? "Cambiar mi sueldo" : "Configurar mi sueldo"}
            icono="wallet-outline"
            onPress={() => router.push("/cuentas/sueldo")}
            ultima
          />
        </GrupoDeFilas>
      </View>

      <Seccion titulo="Instituciones" />
      {conexiones.length === 0 ? (
        <Nota>
          Todavía no tienes instituciones. Puedes conectar tu banco desde Inicio, o importar una
          cartola.
        </Nota>
      ) : (
        <View style={estilos.instituciones}>
          {conexiones.map((c) => (
            <FilaConexion
              key={c.id}
              conexion={c}
              onReautorizar={(x) => reautorizar(x.institucion)}
              onDesvincular={(x) => desvincular(x.id).catch(() => {})}
            />
          ))}
        </View>
      )}

      {/* Lo que no llega por el SFA: otro banco, meses anteriores, efectivo. */}
      <View style={estilos.cargas}>
        <GrupoDeFilas>
          <Fila
            titulo="Importar una cartola"
            detalle="Otro banco o meses anteriores, en CSV"
            icono="document-text-outline"
            onPress={() => router.push("/cuentas/cartola")}
          />
          <Fila
            titulo="Anotar un gasto en efectivo"
            icono="cash-outline"
            onPress={() => router.push("/gastos/nuevo")}
            ultima
          />
        </GrupoDeFilas>
      </View>

      <Seccion titulo="Tus datos" />
      <Aparecer demora={movimiento.escalon}>
        <GrupoDeFilas>
          {DERECHOS.map(({ texto, detalle, icono, ruta, peligro }, i) => (
            <Fila
              key={texto}
              titulo={texto}
              detalle={detalle}
              icono={icono}
              tono={peligro ? "peligro" : "normal"}
              onPress={() => router.push(ruta as never)}
              ultima={i === DERECHOS.length - 1}
            />
          ))}
        </GrupoDeFilas>
      </Aparecer>

      <Nota>
        Velvet Wallet nunca pide ni guarda tu clave del banco. La autorización ocurre en el sitio de
        la institución.
      </Nota>

      <Boton titulo="Cerrar sesión" onPress={salir} secundario style={estilos.salir} />
    </Pantalla>
  );
}

const estilos = StyleSheet.create({
  sueldo: { marginTop: espacio.m },
  // Las instituciones iban sueltas sobre el fondo mientras todo lo demás
  // estaba en tarjetas: se leían como si no pertenecieran a la pantalla.
  instituciones: {
    backgroundColor: colores.tarjeta,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colores.borde,
    borderTopColor: colores.bordeAlto,
    borderRadius: radio.l,
    paddingHorizontal: espacio.l,
  },
  cargas: { marginTop: espacio.m },
  salir: { marginTop: espacio.xl },
});
