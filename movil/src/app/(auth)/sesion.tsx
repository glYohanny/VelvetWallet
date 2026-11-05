/**
 * Inicio de sesión (RF-33).
 *
 * Abajo, discreta, la dirección del servidor: hace falta cambiarla cuando la
 * app corre en un celular y el servidor es otro computador de la red (la
 * presentación). En el uso normal se deduce sola y no hay que tocarla.
 */
import { Link } from "expo-router";
import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { Boton } from "@/components/Boton";
import { Campo } from "@/components/Campo";
import { MarcoAuth } from "@/components/MarcoAuth";
import { colores, espacio, fuente, radio } from "@/constants/tema";
import { useSesion } from "@/sesion/SesionContexto";
import { ErrorAuth, emailValido } from "@/servicios/auth";
import { elegirServidor, probarServidor, servidorActual } from "@/servicios/servidor";
import type { Servidor } from "@/utils/servidor";

const DE_DONDE: Record<Servidor["origen"], string> = {
  escrito: "la elegiste tú",
  compilado: "la de esta instalación",
  pagina: "la misma de esta página",
  expo: "la del computador que cargó la app",
  local: "este mismo equipo",
};

/** La dirección del servidor, y cambiarla probando antes que responda. */
function ElegirServidor() {
  const [servidor, setServidor] = useState<Servidor>(servidorActual());
  const [abierto, setAbierto] = useState(false);
  const [texto, setTexto] = useState("");
  const [probando, setProbando] = useState(false);
  const [resultado, setResultado] = useState<{ ok: boolean; mensaje: string } | null>(null);

  async function probarYGuardar() {
    setProbando(true);
    setResultado(null);
    try {
      const r = await probarServidor(texto);
      setResultado(r);
      if (r.ok && r.url) {
        setServidor(await elegirServidor(r.url));
        setAbierto(false);
      }
    } finally {
      setProbando(false);
    }
  }

  async function volverALaAutomatica() {
    setServidor(await elegirServidor(null));
    setResultado(null);
    setAbierto(false);
  }

  return (
    <View style={estilos.servidor}>
      <Text style={estilos.servidorTexto}>
        Servidor: <Text style={estilos.servidorUrl}>{servidor.url}</Text> · {DE_DONDE[servidor.origen]}
      </Text>
      {!abierto ? (
        <Text
          style={estilos.servidorEnlace}
          onPress={() => {
            setTexto(servidor.origen === "escrito" ? servidor.url : "");
            setResultado(null);
            setAbierto(true);
          }}
        >
          Cambiar
        </Text>
      ) : (
        <View style={estilos.servidorEditor}>
          <Campo
            etiqueta="IP o dirección del computador servidor"
            value={texto}
            onChangeText={(t) => {
              setTexto(t);
              setResultado(null);
            }}
            placeholder="192.168.1.20"
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
            onSubmitEditing={() => texto.trim() && probarYGuardar()}
          />
          <Boton
            titulo="Probar y usar"
            onPress={probarYGuardar}
            cargando={probando}
            deshabilitado={!texto.trim()}
            secundario
          />
          <View style={estilos.servidorAcciones}>
            {servidor.origen === "escrito" ? (
              <Text style={estilos.servidorEnlace} onPress={volverALaAutomatica}>
                Volver a la automática
              </Text>
            ) : null}
            <Text style={estilos.servidorEnlaceApagado} onPress={() => setAbierto(false)}>
              Cancelar
            </Text>
          </View>
        </View>
      )}
      {resultado ? (
        <Text style={resultado.ok ? estilos.servidorOk : estilos.servidorError}>{resultado.mensaje}</Text>
      ) : null}
    </View>
  );
}

export default function IniciarSesion() {
  const { entrar } = useSesion();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  const completo = emailValido(email) && password.length > 0;

  async function enviar() {
    setError(null);
    setEnviando(true);
    try {
      await entrar({ email, password });
      // No se navega: el layout raíz detecta la sesión y entra solo.
    } catch (e) {
      setError(e instanceof ErrorAuth ? e.message : "No se pudo conectar. Intenta de nuevo.");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <MarcoAuth
      titulo="Hola de nuevo"
      bajada="Entra para ver en qué se te va la plata este mes."
      pie={
        <Text style={estilos.pieTexto}>
          ¿No tienes cuenta?{" "}
          <Link href="/registro" style={estilos.enlace}>
            Crear una
          </Link>
        </Text>
      }
    >
      <Campo
        etiqueta="Correo"
        value={email}
        onChangeText={setEmail}
        placeholder="tu@correo.cl"
        keyboardType="email-address"
        autoCapitalize="none"
        autoComplete="email"
        textContentType="emailAddress"
      />

      <Campo
        etiqueta="Contraseña"
        value={password}
        onChangeText={setPassword}
        placeholder="Tu contraseña"
        secreto
        autoComplete="current-password"
        textContentType="password"
        onSubmitEditing={() => completo && enviar()}
        returnKeyType="go"
      />

      {error ? <Text style={estilos.error}>{error}</Text> : null}

      <Boton titulo="Entrar" onPress={enviar} cargando={enviando} deshabilitado={!completo} />

      <View style={estilos.demo}>
        <Text style={estilos.demoTitulo}>Cuenta de prueba</Text>
        <Text style={estilos.demoTexto}>demo@velvetwallet.cl · velvet2026</Text>
      </View>

      <ElegirServidor />
    </MarcoAuth>
  );
}

const estilos = StyleSheet.create({
  error: { color: colores.acento, fontFamily: fuente.textoMedio, fontSize: 14, textAlign: "center" },
  pieTexto: { color: colores.texto2, fontFamily: fuente.texto, fontSize: 15 },
  enlace: { color: colores.acento, fontFamily: fuente.textoFuerte },
  demo: {
    backgroundColor: colores.tarjeta,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colores.borde,
    borderTopColor: colores.bordeAlto,
    borderRadius: radio.m,
    padding: espacio.m,
    alignItems: "center",
    gap: 2,
  },
  demoTitulo: { color: colores.texto3, fontFamily: fuente.tituloMedio, fontSize: 11, letterSpacing: 1 },
  demoTexto: { color: colores.texto2, fontFamily: fuente.mono, fontSize: 13 },
  servidor: { alignItems: "center", gap: espacio.s },
  servidorTexto: { color: colores.texto3, fontFamily: fuente.texto, fontSize: 12, textAlign: "center" },
  servidorUrl: { fontFamily: fuente.mono },
  servidorEnlace: { color: colores.acento, fontFamily: fuente.textoFuerte, fontSize: 13 },
  servidorEnlaceApagado: { color: colores.texto2, fontFamily: fuente.textoMedio, fontSize: 13 },
  servidorEditor: { alignSelf: "stretch", gap: espacio.m },
  servidorAcciones: { flexDirection: "row", justifyContent: "center", gap: espacio.l },
  servidorOk: { color: colores.ok, fontFamily: fuente.textoMedio, fontSize: 13, textAlign: "center" },
  servidorError: { color: colores.acento, fontFamily: fuente.textoMedio, fontSize: 13, textAlign: "center" },
});
