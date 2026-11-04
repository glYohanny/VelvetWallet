/**
 * Bitácora: qué se hizo con tus datos y cuándo.
 *
 * Es el registro de actividades de tratamiento que exige la Ley 21.719, visto
 * desde el lado del titular. La ley obliga a llevarlo; mostrárselo a la persona
 * es lo que lo convierte en un derecho y no en un trámite interno.
 *
 * Se agrupa por día porque la pregunta real nunca es "¿qué pasó a las 14:32?"
 * sino "¿qué pasó con mis datos esta semana?".
 */
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, StyleSheet, Text, View } from "react-native";

import { Nota, Pantalla } from "@/components/Pantalla";
import { colores, espacio, fuente, radio } from "@/constants/tema";
import { fechaConAnio, hora } from "@/utils/formato";
import { obtenerBitacora, type EventoBitacora } from "@/servicios/privacidad";

type NombreIcono = keyof typeof Ionicons.glyphMap;

/** Un icono por tipo de hecho, para poder recorrer la lista con la vista. */
const ICONO: Record<string, NombreIcono> = {
  "datos.leer": "eye-outline",
  "datos.exportar": "download-outline",
  "consentimiento.otorgar": "checkmark-circle-outline",
  "consentimiento.revocar": "close-circle-outline",
  "banco.vincular": "link-outline",
  "banco.desvincular": "unlink-outline",
  "cuenta.suprimir": "trash-outline",
  "categoria.corregir": "create-outline",
  "datos.importar": "document-text-outline",
  "datos.registrar_manual": "cash-outline",
  "datos.borrar_manual": "remove-circle-outline",
};

/** Agrupa por día conservando el orden que vino del servidor. */
function porDia(eventos: EventoBitacora[]): [string, EventoBitacora[]][] {
  const mapa = new Map<string, EventoBitacora[]>();
  for (const e of eventos) {
    const dia = e.cuando.slice(0, 10);
    const delDia = mapa.get(dia);
    if (delDia) delDia.push(e);
    else mapa.set(dia, [e]);
  }
  return [...mapa.entries()];
}

export default function Bitacora() {
  const router = useRouter();
  const [eventos, setEventos] = useState<EventoBitacora[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useFocusEffect(
    useCallback(() => {
      obtenerBitacora().then(setEventos).catch((e) => setError(e.message));
    }, []),
  );

  if (error) {
    return (
      <Pantalla titulo="Bitácora" onAtras={() => router.back()}>
        <Nota>{error}</Nota>
      </Pantalla>
    );
  }

  if (!eventos) {
    return (
      <Pantalla titulo="Bitácora" onAtras={() => router.back()}>
        <ActivityIndicator color={colores.acento} style={estilos.cargando} />
      </Pantalla>
    );
  }

  return (
    <Pantalla titulo="Bitácora" onAtras={() => router.back()}>
      <Text style={estilos.entrada}>
        Cada vez que se accede a tus datos o cambias un permiso, queda anotado acá. El registro no
        se puede editar ni borrar, ni siquiera por nosotros.
      </Text>

      {eventos.length === 0 ? (
        <Nota>Todavía no hay movimientos registrados en tu bitácora.</Nota>
      ) : (
        porDia(eventos).map(([dia, delDia]) => (
          <View key={dia}>
            <Text style={estilos.dia}>{fechaConAnio(dia)}</Text>
            <View style={estilos.grupo}>
              {delDia.map((e, i) => (
                <View key={`${e.cuando}-${i}`} style={[estilos.fila, i > 0 && estilos.conLinea]}>
                  <View style={estilos.icono}>
                    <Ionicons
                      name={ICONO[e.accion] ?? "ellipse-outline"}
                      size={17}
                      color={colores.texto2}
                    />
                  </View>
                  <View style={estilos.cuerpo}>
                    <Text style={estilos.descripcion}>{e.descripcion}</Text>
                    <Text style={estilos.detalle}>
                      {hora(e.cuando)}
                      {e.recurso ? ` · ${e.recurso}` : ""}
                      {e.ip ? ` · ${e.ip}` : ""}
                    </Text>
                  </View>
                </View>
              ))}
            </View>
          </View>
        ))
      )}

      <Nota>
        Se anota qué se tocó y cuándo, nunca el contenido de tus datos: la bitácora no puede
        convertirse ella misma en una copia de tu información.
      </Nota>
    </Pantalla>
  );
}

const estilos = StyleSheet.create({
  cargando: { marginTop: espacio.xl },
  entrada: { color: colores.texto2, fontFamily: fuente.texto, fontSize: 15, lineHeight: 22 },
  dia: {
    color: colores.texto3,
    fontFamily: fuente.tituloMedio,
    fontSize: 12,
    letterSpacing: 1.2,
    textTransform: "uppercase",
    marginTop: espacio.xl,
    marginBottom: espacio.s,
  },
  grupo: { backgroundColor: colores.tarjeta, borderRadius: radio.l, paddingHorizontal: espacio.l },
  fila: { flexDirection: "row", alignItems: "flex-start", gap: espacio.m, paddingVertical: espacio.m },
  conLinea: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colores.linea },
  icono: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: colores.chip,
    alignItems: "center",
    justifyContent: "center",
  },
  cuerpo: { flex: 1, gap: 2 },
  descripcion: { color: colores.texto, fontFamily: fuente.textoMedio, fontSize: 14.5 },
  detalle: { color: colores.texto3, fontFamily: fuente.texto, fontSize: 12.5 },
});
