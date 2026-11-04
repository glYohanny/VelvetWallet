/**
 * Anotar un movimiento a mano (RF-13): lo que no pasa por ningún banco,
 * principalmente el efectivo.
 *
 * Tiene que ser más rápido que no anotarlo. Por eso lo único obligatorio es el
 * monto y en qué fue; la fecha parte en hoy y la categoría, si no se elige, la
 * propone el mismo clasificador que categoriza lo que llega del banco.
 */
import { useRouter } from "expo-router";
import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { Boton } from "@/components/Boton";
import { Campo } from "@/components/Campo";
import { Chips } from "@/components/Chips";
import { Nota, Pantalla, Seccion } from "@/components/Pantalla";
import { Segmentos } from "@/components/Segmentos";
import { colores, espacio, fuente } from "@/constants/tema";
import { CATEGORIAS_DE_GASTO } from "@/datos/categorias";
import { useMovimientos } from "@/datos/MovimientosContexto";
import { anotarMovimiento } from "@/servicios/cargas";
import { pesos } from "@/utils/formato";

type Tipo = "gasto" | "ingreso";
type Cuando = "hoy" | "ayer" | "otro";

const TIPOS: { valor: Tipo; etiqueta: string }[] = [
  { valor: "gasto", etiqueta: "Gasto" },
  { valor: "ingreso", etiqueta: "Ingreso" },
];

const CUANDO: { valor: Cuando; etiqueta: string }[] = [
  { valor: "hoy", etiqueta: "Hoy" },
  { valor: "ayer", etiqueta: "Ayer" },
  { valor: "otro", etiqueta: "Otro día" },
];

const SUGERIDA = "sugerida";
const OPCIONES_CATEGORIA = [
  { valor: SUGERIDA, etiqueta: "Que la sugiera Velvet" },
  ...CATEGORIAS_DE_GASTO.map((c) => ({ valor: c as string, etiqueta: c })),
];

/** "3.500" o "$3500" → 3500. null si no hay un número válido. */
function aMonto(texto: string): number | null {
  const limpio = texto.replace(/[^\d]/g, "");
  if (!limpio) return null;
  const n = Number(limpio);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function isoLocal(d: Date): string {
  const dos = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${dos(d.getMonth() + 1)}-${dos(d.getDate())}`;
}

/** "20-10-2026" o "20/10/2026" → "2026-10-20". null si no es una fecha real o es futura. */
function aFechaIso(texto: string): string | null {
  const m = texto.trim().match(/^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$/);
  if (!m) return null;
  const [d, mes, a] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const f = new Date(a, mes - 1, d);
  if (f.getFullYear() !== a || f.getMonth() !== mes - 1 || f.getDate() !== d) return null;
  if (f > new Date()) return null;
  return isoLocal(f);
}

export default function NuevoMovimiento() {
  const router = useRouter();
  const { agregarMovimiento } = useMovimientos();

  const [tipo, setTipo] = useState<Tipo>("gasto");
  const [monto, setMonto] = useState("");
  const [glosa, setGlosa] = useState("");
  const [cuando, setCuando] = useState<Cuando>("hoy");
  const [otroDia, setOtroDia] = useState("");
  const [categoria, setCategoria] = useState<string>(SUGERIDA);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const valor = aMonto(monto);
  const ayer = new Date();
  ayer.setDate(ayer.getDate() - 1);
  const fecha =
    cuando === "hoy" ? isoLocal(new Date()) : cuando === "ayer" ? isoLocal(ayer) : aFechaIso(otroDia);
  const fechaInvalida = cuando === "otro" && otroDia.trim() !== "" && fecha === null;
  const listo = valor !== null && glosa.trim() !== "" && fecha !== null;

  async function guardar() {
    if (!listo || valor === null || fecha === null) return;
    setGuardando(true);
    setError(null);
    try {
      const m = await anotarMovimiento({
        monto: valor,
        tipo,
        glosa: glosa.trim(),
        fecha,
        categoria: tipo === "gasto" && categoria !== SUGERIDA ? categoria : null,
      });
      agregarMovimiento(m);
      router.back();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar.");
    } finally {
      setGuardando(false);
    }
  }

  return (
    <Pantalla titulo="Anotar a mano" onAtras={() => router.back()}>
      <Segmentos opciones={TIPOS} valor={tipo} onCambio={setTipo} />

      <View style={estilos.campos}>
        <Campo
          etiqueta="Monto"
          placeholder="3500"
          value={monto}
          onChangeText={setMonto}
          keyboardType="number-pad"
          autoFocus
        />
        {valor !== null ? (
          <Text style={estilos.eco}>
            {tipo === "gasto" ? "−" : "+"}
            {pesos(valor)}
          </Text>
        ) : null}

        <Campo
          etiqueta={tipo === "gasto" ? "¿En qué fue?" : "¿De qué fue?"}
          placeholder={tipo === "gasto" ? "Almuerzo en la feria" : "Venta de la bicicleta"}
          value={glosa}
          onChangeText={setGlosa}
          maxLength={120}
        />
      </View>

      <Seccion titulo="Cuándo" />
      <Chips opciones={CUANDO} valor={cuando} onCambio={setCuando} />
      {cuando === "otro" ? (
        <Campo
          etiqueta="Fecha"
          placeholder="dd-mm-aaaa"
          value={otroDia}
          onChangeText={setOtroDia}
          keyboardType="numbers-and-punctuation"
          error={fechaInvalida ? "Escribe una fecha real que no sea futura, como 20-10-2026." : null}
        />
      ) : null}

      {tipo === "gasto" ? (
        <>
          <Seccion titulo="Categoría" />
          <Chips opciones={OPCIONES_CATEGORIA} valor={categoria} onCambio={setCategoria} />
        </>
      ) : null}

      <Boton
        titulo="Guardar"
        onPress={guardar}
        cargando={guardando}
        deshabilitado={!listo}
        style={estilos.guardar}
      />
      {error ? <Text style={estilos.error}>{error}</Text> : null}

      <Nota>
        Queda en tu cuenta Efectivo y cuenta igual que lo que llega del banco: en tu resumen, tus
        metas y tus gastos fijos. Si te equivocas, puedes borrarlo desde el detalle.
      </Nota>
    </Pantalla>
  );
}

const estilos = StyleSheet.create({
  campos: { gap: espacio.l, marginTop: espacio.l },
  eco: { color: colores.texto3, fontFamily: fuente.textoMedio, fontSize: 13, marginTop: -espacio.m },
  guardar: { marginTop: espacio.l },
  error: { color: colores.acento, fontFamily: fuente.textoMedio, fontSize: 14, marginTop: espacio.m },
});
