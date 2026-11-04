/**
 * Repartir un gasto entre categorías (RF-14).
 *
 * La compra del supermercado que fue comida y cosas de la casa. El movimiento
 * sigue siendo uno y por el mismo monto; lo que cambia es en qué categorías
 * cuenta. Por eso las partes tienen que sumar exactamente el total: la
 * pantalla dice cuánto falta y no deja guardar hasta que cuadre.
 */
import { useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { Boton } from "@/components/Boton";
import { Campo } from "@/components/Campo";
import { Chips } from "@/components/Chips";
import { Nota, Pantalla, Seccion } from "@/components/Pantalla";
import { colores, espacio, fuente } from "@/constants/tema";
import { CATEGORIAS_DE_GASTO } from "@/datos/categorias";
import { useMovimientos } from "@/datos/MovimientosContexto";
import { dividirMovimiento } from "@/servicios/cargas";
import { pesos } from "@/utils/formato";

const MAX_PARTES = 8;
/** Todas las categorías, con la que ya tenía el gasto primero: es la que más se usa. */
function opciones(primera: string) {
  return [primera, ...CATEGORIAS_DE_GASTO.filter((c) => c !== primera)].map((c) => ({
    valor: c as string,
    etiqueta: c,
  }));
}

type Borrador = { monto: string; categoria: string };

function aMonto(texto: string): number {
  const limpio = texto.replace(/[^\d]/g, "");
  return limpio ? Number(limpio) : 0;
}

/** La primera categoría que todavía no usa ninguna parte. */
function libre(partes: Borrador[]): string {
  return CATEGORIAS_DE_GASTO.find((c) => !partes.some((p) => p.categoria === c)) ?? CATEGORIAS_DE_GASTO[0];
}

export default function Dividir() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { movimientos, reemplazarMovimiento } = useMovimientos();
  const m = movimientos.find((x) => x.id === id);

  const inicial = m?.categoria && (CATEGORIAS_DE_GASTO as readonly string[]).includes(m.categoria)
    ? m.categoria
    : CATEGORIAS_DE_GASTO[0];
  const [partes, setPartes] = useState<Borrador[]>(() => [
    { monto: "", categoria: inicial },
    { monto: "", categoria: inicial === "Hogar" ? "Supermercado" : "Hogar" },
  ]);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!m) {
    return (
      <Pantalla titulo="Dividir" onAtras={() => router.back()}>
        <Nota>No se encontró el movimiento.</Nota>
      </Pantalla>
    );
  }

  const total = Math.abs(m.monto);
  const suma = partes.reduce((s, p) => s + aMonto(p.monto), 0);
  const falta = total - suma;
  const repetida = new Set(partes.map((p) => p.categoria)).size !== partes.length;
  const vacias = partes.some((p) => aMonto(p.monto) === 0);
  const listo = falta === 0 && !repetida && !vacias;

  function cambiar(i: number, cambio: Partial<Borrador>) {
    setError(null);
    setPartes((lista) => lista.map((p, j) => (j === i ? { ...p, ...cambio } : p)));
  }

  async function guardar() {
    if (!m || !listo) return;
    setGuardando(true);
    setError(null);
    try {
      reemplazarMovimiento(
        await dividirMovimiento(m.id, partes.map((p) => ({ monto: aMonto(p.monto), categoria: p.categoria }))),
      );
      router.back();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo dividir.");
      setGuardando(false);
    }
  }

  return (
    <Pantalla titulo="Dividir" onAtras={() => router.back()}>
      <View style={estilos.encabezado}>
        <Text style={estilos.total}>{pesos(total)}</Text>
        <Text style={estilos.comercio}>{m.comercio ?? m.glosaOriginal}</Text>
      </View>

      {partes.map((p, i) => (
        <View key={i}>
          <Seccion titulo={`Parte ${i + 1}`} />
          <Campo
            etiqueta="Monto"
            placeholder={falta > 0 && !p.monto ? String(falta) : "0"}
            value={p.monto}
            onChangeText={(t) => cambiar(i, { monto: t })}
            keyboardType="number-pad"
          />
          <View style={estilos.categorias}>
            <Chips opciones={opciones(inicial)} valor={p.categoria} onCambio={(c) => cambiar(i, { categoria: c })} />
          </View>
          {partes.length > 2 ? (
            <Text
              style={estilos.quitar}
              onPress={() => setPartes((lista) => lista.filter((_, j) => j !== i))}
            >
              Quitar esta parte
            </Text>
          ) : null}
        </View>
      ))}

      {partes.length < MAX_PARTES ? (
        <Text
          style={estilos.agregar}
          onPress={() => setPartes((lista) => [...lista, { monto: "", categoria: libre(lista) }])}
        >
          + Agregar otra parte
        </Text>
      ) : null}

      <Text style={[estilos.cuadre, falta === 0 ? estilos.cuadreOk : estilos.cuadreFalta]}>
        {falta === 0
          ? "Las partes suman el total."
          : falta > 0
            ? `Falta repartir ${pesos(falta)}.`
            : `Te pasaste por ${pesos(-falta)}.`}
        {repetida ? " Cada parte va en una categoría distinta." : ""}
      </Text>

      <Boton titulo="Guardar reparto" onPress={guardar} cargando={guardando} deshabilitado={!listo}
             style={estilos.guardar} />
      {error ? <Text style={estilos.error}>{error}</Text> : null}

      <Nota>
        El movimiento del banco no cambia: sigue siendo uno, por {pesos(total)}. Lo que cambia es en
        qué categorías cuenta. Lo puedes deshacer cuando quieras.
      </Nota>
    </Pantalla>
  );
}

const estilos = StyleSheet.create({
  encabezado: { paddingTop: espacio.m, gap: espacio.xs },
  total: { color: colores.texto, fontFamily: fuente.titulo, fontSize: 36, letterSpacing: -1 },
  comercio: { color: colores.texto2, fontFamily: fuente.texto, fontSize: 15 },
  categorias: { marginTop: espacio.m },
  quitar: { color: colores.texto2, fontFamily: fuente.textoMedio, fontSize: 14, marginTop: -espacio.s },
  agregar: { color: colores.acento, fontFamily: fuente.textoFuerte, fontSize: 15, marginTop: espacio.l },
  cuadre: { fontFamily: fuente.textoMedio, fontSize: 14, marginTop: espacio.l },
  cuadreOk: { color: colores.ok },
  cuadreFalta: { color: colores.alerta },
  guardar: { marginTop: espacio.m },
  error: { color: colores.acento, fontFamily: fuente.textoMedio, fontSize: 14, marginTop: espacio.m },
});
