/**
 * Inicio — responde la primera pregunta del producto:
 * "¿Cuánto tengo disponible este mes?"
 *
 * Se muestra lo que ya funciona con datos reales del backend: disponible,
 * ingresos y gastos del mes, en qué se va la plata (por categoría) y cómo
 * cambió respecto al mes anterior.
 */
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { Platform, Pressable, StyleSheet, Text, View } from "react-native";

import { Aviso } from "@/components/Aviso";
import { AvisoClasificacion } from "@/components/AvisoClasificacion";
import { BarraCategorias } from "@/components/BarraCategorias";
import { Boton } from "@/components/Boton";
import { Chips } from "@/components/Chips";
import { Cifra } from "@/components/Cifra";
import { Comparacion } from "@/components/Comparacion";
import { EsqueletoInicio } from "@/components/Esqueleto";
import { GastoMasGrande } from "@/components/GastoMasGrande";
import { GraficoCategorias } from "@/components/GraficoCategorias";
import { GraficoMeses } from "@/components/GraficoMeses";
import { Aparecer } from "@/components/Movimiento";
import { PanelFlujo } from "@/components/PanelFlujo";
import { Pantalla, Seccion } from "@/components/Pantalla";
import { Superficie } from "@/components/Superficie";
import { colores, espacio, fuente, movimiento, radio } from "@/constants/tema";
import { useMovimientos, type VueltaDelBanco } from "@/datos/MovimientosContexto";
import { marcarVisto, yaSeVio } from "@/datos/primeraVez";
import { useSesion } from "@/sesion/SesionContexto";
import { ErrorSincronizacion } from "@/servicios/sincronizacion";
import { claveMes, nombreMes, pesos } from "@/utils/formato";
import { categoriaMasGrande, desglosar } from "@/utils/desglose";
import type { Conexion } from "@/modelo/tipos";
import {
  compararConMesAnterior,
  conexionesConProblema,
  gastoUltimosMeses,
  mesAnterior,
  promedioMensual,
  repartoPorCategoria,
  resumenDelMes,
} from "@/utils/resumen";

/** Resumen de la última sincronización, en lenguaje natural. */
function describirResultado(r: { nuevos: number; actualizados: number }): string {
  const partes: string[] = [];
  if (r.nuevos > 0) partes.push(`${r.nuevos} ${r.nuevos === 1 ? "movimiento nuevo" : "movimientos nuevos"}`);
  if (r.actualizados > 0) {
    partes.push(`${r.actualizados} ${r.actualizados === 1 ? "actualizado" : "actualizados"}`);
  }
  return partes.length > 0 ? partes.join(" · ") : "Todo al día. No hay movimientos nuevos.";
}

/** Mensaje para el usuario según cómo volvió del sitio del banco. */
/** Por qué el dato de un banco no está completo, en pocas palabras. */
function problemaDe(c: Conexion): string {
  if (c.estado === "sin_respuesta") return "no respondió";
  if (c.estado === "autorizacion_vencida") return "tiene el permiso vencido";
  return "no se actualiza hace rato";
}

function mensajeDeVuelta(v: VueltaDelBanco): string {
  if (v.banco === "rechazado") return "Rechazaste el acceso en tu banco. No se compartió nada.";
  if (v.motivo === "otro_cliente") {
    return "Este banco ya está vinculado a otro RUT en tu cuenta. Desvincúlalo antes de autorizar con otro.";
  }
  if (v.motivo === "expirado") {
    return "La autorización venció o ya se había usado. Vuelve a intentarlo.";
  }
  return "No se pudo completar la vinculación con tu banco. Intenta de nuevo.";
}

/**
 * Panel de autorización: explica qué se pide y manda al usuario al SITIO DE SU
 * BANCO. Allá inicia sesión con su RUT y su clave y aprueba; Velvet no ve ni
 * guarda esos datos (OAuth del SFA). El banco lo devuelve a la app.
 */
function PanelAutorizacion({
  motivo,
  ocupado,
  onIrAlBanco,
  onCancelar,
  bancos,
  banco,
  onElegir,
}: {
  motivo?: string | null;
  ocupado: boolean;
  onIrAlBanco: () => void;
  onCancelar?: () => void;
  /** Los bancos que se pueden elegir. Con uno solo no se muestra la elección. */
  bancos: string[];
  banco: string;
  onElegir: (banco: string) => void;
}) {
  return (
    <View style={estilos.consent}>
      <Text style={estilos.consentTitulo}>Autorización de acceso</Text>
      {motivo ? <Text style={estilos.consentMotivo}>{motivo}</Text> : null}
      {bancos.length > 1 ? (
        <View style={estilos.elegirBanco}>
          <Chips
            opciones={bancos.map((b) => ({ valor: b, etiqueta: b }))}
            valor={banco}
            onCambio={onElegir}
          />
        </View>
      ) : null}
      <Text style={estilos.consentTexto}>
        Velvet Wallet solicita tu permiso para leer, en tu banco:
      </Text>
      <Text style={estilos.consentItem}>•  Tus cuentas y saldos</Text>
      <Text style={estilos.consentItem}>•  Tus movimientos</Text>

      <Text style={estilos.consentNota}>
        Te llevaremos al sitio de {banco}. Inicias sesión allá con tu RUT y tu clave y decides si
        autorizas. Velvet nunca ve tu clave, y puedes revocar el acceso cuando quieras.
      </Text>

      <Boton
        titulo={ocupado ? "Abriendo tu banco…" : `Ir a ${banco}`}
        onPress={onIrAlBanco}
        cargando={ocupado}
        style={estilos.autorizar}
      />
      {!ocupado && onCancelar ? (
        <Pressable onPress={onCancelar} style={estilos.cancelar}>
          <Text style={estilos.cancelarTexto}>Cancelar</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

export default function Inicio() {
  const router = useRouter();
  const {
    movimientos, sincronizando, cargaInicial, sincronizar, irAlBanco, completarVinculacion,
    clienteBanco, conexiones, instituciones, error,
  } = useMovimientos();
  // Vuelta desde el sitio del banco (web): ?banco=vinculado|rechazado|error&motivo=…
  const parametros = useLocalSearchParams<{ banco?: string; motivo?: string }>();
  const vueltaProcesada = useRef(false);
  const [abriendoBanco, setAbriendoBanco] = useState(false);
  const [aviso, setAviso] = useState<string | null>(null);
  const [resultado, setResultado] = useState<string | null>(null);
  const [solicitando, setSolicitando] = useState(false);
  // Cuando el permiso guardado ya no sirve, hay que volver a autorizar en el banco.
  const [reautorizar, setReautorizar] = useState<string | null>(null);
  // A qué banco se va a autorizar. null = el primero que falte por conectar.
  const [bancoElegido, setBancoElegido] = useState<string | null>(null);
  // Mes que mira el panel. null = el más reciente con datos; cambia al tocar
  // una barra del gráfico de meses.
  const [mesElegido, setMesElegido] = useState<string | null>(null);

  // Aviso de primera vez: explica la clasificación automática y que usar los
  // datos para mejorarla es opcional y viene apagado. Se consulta una sola vez
  // al entrar, por usuario.
  const { usuario } = useSesion();
  const [mostrarAviso, setMostrarAviso] = useState(false);

  useEffect(() => {
    const id = usuario?.id;
    if (!id) return;
    let vivo = true;
    yaSeVio("clasificacion", id).then((visto) => {
      if (vivo && !visto) setMostrarAviso(true);
    });
    return () => {
      vivo = false;
    };
  }, [usuario?.id]);

  /** Las dos salidas del aviso lo marcan como visto; ninguna activa nada. */
  async function cerrarAviso(ir: boolean) {
    setMostrarAviso(false);
    if (usuario?.id) await marcarVisto("clasificacion", usuario.id);
    if (ir) router.push("/cuentas/privacidad");
  }

  // Los bancos del SFA que se pueden ofrecer y el que está elegido. Sin la
  // lista (backend antiguo), queda el de siempre.
  const nombresBancos = instituciones.length ? instituciones.map((i) => i.nombre) : ["tu banco"];
  const porConectar = instituciones.filter((i) => !i.conectada).map((i) => i.nombre);
  const banco = bancoElegido ?? porConectar[0] ?? nombresBancos[0];
  const bancosVinculados = conexiones.filter((c) => (c.fuente ?? "sfa") === "sfa").length;
  const conProblema = conexionesConProblema(conexiones);

  async function alSincronizar() {
    setResultado(null);
    try {
      const r = await sincronizar();
      // Cada banco por separado (RF-07): si uno no respondió, el resto llegó
      // igual, y se dice cuál faltó en vez de esconderlo.
      const fallidos = r.bancos.filter((b) => !b.ok && b.codigo === "sin_respuesta");
      const vencido = r.bancos.find((b) => !b.ok && b.codigo === "reautorizar");
      setResultado(
        [describirResultado(r), ...fallidos.map((b) => `${b.institucion} no respondió: se muestran sus datos de la última vez.`)]
          .join("\n"),
      );
      if (vencido) {
        setBancoElegido(vencido.institucion);
        setReautorizar(`El permiso de ${vencido.institucion} venció. Renuévalo en su sitio.`);
      }
    } catch (e) {
      if (e instanceof ErrorSincronizacion && e.codigo === "reautorizar") {
        setReautorizar(e.message);
      }
      // El mensaje ya quedó en `error`; se muestra abajo del botón.
    }
  }

  /** Cómo volvió el usuario del banco: si autorizó, se traen sus datos. */
  async function procesarVuelta(v: VueltaDelBanco) {
    setReautorizar(null);
    setSolicitando(false);
    if (v.banco !== "vinculado") {
      setAviso(mensajeDeVuelta(v));
      return;
    }
    setAviso(null);
    try {
      await completarVinculacion();
    } catch {
      // El mensaje ya quedó en `error`.
    }
  }

  async function alIrAlBanco() {
    setAviso(null);
    setAbriendoBanco(true);
    try {
      const vuelta = await irAlBanco(banco); // en web la página se va al banco
      if (vuelta) await procesarVuelta(vuelta);
    } catch {
      // El mensaje ya quedó en `error`.
    } finally {
      setAbriendoBanco(false);
    }
  }

  // En web el banco devuelve al usuario a esta pantalla con ?banco=…: se
  // procesa una sola vez y se limpia la URL.
  useEffect(() => {
    // Solo web: en el celular la vuelta llega como resultado de irAlBanco().
    if (Platform.OS !== "web" || !parametros.banco || vueltaProcesada.current) return;
    vueltaProcesada.current = true;
    const vuelta: VueltaDelBanco = { banco: String(parametros.banco), motivo: parametros.motivo };
    router.replace("/");
    procesarVuelta(vuelta);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [parametros.banco]);

  // La primera carga todavía viene en camino: no se sabe si hay movimientos o
  // no. Mostrar "Conecta tu primer banco" aquí sería afirmar algo que puede
  // ser falso, y la pantalla saltaría sola al llegar la respuesta.
  if (cargaInicial) {
    return (
      <Pantalla titulo="Velvet Wallet" marca>
        <EsqueletoInicio />
      </Pantalla>
    );
  }

  // Usuario sin movimientos todavía (p. ej. recién registrado): aún no vinculó
  // ningún banco. Aquí PIDE el permiso explícitamente — no se conecta solo.
  if (movimientos.length === 0) {
    return (
      <Pantalla titulo="Velvet Wallet" marca>
        <Text style={estilos.rotulo}>CONECTA TU PRIMER BANCO</Text>
        <Text style={estilos.bienvenida}>
          Aún no has vinculado ninguna cuenta. Conecta tu banco para traer tus movimientos.
        </Text>

        {aviso ? <Text style={estilos.aviso}>{aviso}</Text> : null}

        {sincronizando && !solicitando && !reautorizar ? (
          <Boton titulo="Trayendo tus datos del banco…" onPress={() => {}} cargando style={estilos.sincronizar} />
        ) : !solicitando && !reautorizar ? (
          <Boton
            titulo="Conectar mi banco"
            onPress={() => setSolicitando(true)}
            style={estilos.sincronizar}
          />
        ) : (
          <PanelAutorizacion
            motivo={reautorizar}
            ocupado={abriendoBanco || sincronizando}
            onIrAlBanco={alIrAlBanco}
            onCancelar={() => {
              setSolicitando(false);
              setReautorizar(null);
            }}
            bancos={nombresBancos}
            banco={banco}
            onElegir={setBancoElegido}
          />
        )}

        {error ? <Text style={estilos.error}>{error}</Text> : null}

        <AvisoClasificacion
          visible={mostrarAviso}
          onDespues={() => cerrarAviso(false)}
          onIr={() => cerrarAviso(true)}
        />
      </Pantalla>
    );
  }

  const mes = mesElegido ?? claveMes(movimientos[0].fecha);
  const resumen = resumenDelMes(movimientos, mes);
  const reparto = repartoPorCategoria(movimientos, mes);
  const comparacion = compararConMesAnterior(movimientos, mes);

  // Serie de los últimos seis meses. El gráfico la muestra y, al tocar una
  // barra, el resto del panel se mueve a ese mes.
  const serie = gastoUltimosMeses(movimientos, 6);
  const promedio = promedioMensual(serie);
  const mesesDelPeriodo = new Set(serie.map((g) => g.mes));
  const repartoPeriodo = repartoPorCategoria(movimientos, mesesDelPeriodo);

  // El gasto más grande del mes, ya desglosado. El panel lo nombra en vez de
  // dejar al usuario buscando con la vista cuál es la porción más gruesa.
  const mayor = categoriaMasGrande(movimientos, mes);
  const desgloseMayor = mayor ? desglosar(movimientos, mayor.categoria, mes) : null;

  /**
   * Abre el desglose de una categoría manteniendo el período que se está
   * mirando: desde el anillo va el mes, desde la barra van los seis meses. Si
   * cambiara de período, las cifras no cuadrarían con las de esta pantalla.
   */
  function abrirCategoria(categoria: string, deTodoElPeriodo = false) {
    router.push({
      pathname: "/gastos/categoria",
      params: deTodoElPeriodo
        ? { nombre: categoria, meses: serie.map((g) => g.mes).join(",") }
        : { nombre: categoria, mes },
    });
  }

  return (
    <Pantalla
      titulo="Velvet Wallet"
      marca
      etiqueta={nombreMes(mes)}
      resumen={{
        rotulo: "DISPONIBLE",
        valor: pesos(resumen.disponible),
        negativo: resumen.disponible < 0,
      }}
    >
      {/* La zona héroe es una superficie de nivel 1 que CONTIENE a las
          tarjetas de ingresos y gastos. Antes eran cinco rectángulos iguales
          apilados y nada pesaba más que nada; ahora la jerarquía se ve: esto
          es el resumen del mes, y lo de abajo son sus detalles. */}
      <Superficie nivel={1} style={estilos.zona}>
        <Text style={estilos.rotulo}>DISPONIBLE ESTE MES</Text>
        <Cifra
          valor={resumen.disponible}
          style={[estilos.disponible, resumen.disponible < 0 && estilos.negativo]}
        />

        <Boton
          titulo={sincronizando ? "Consultando tu banco…" : "Sincronizar"}
          onPress={alSincronizar}
          cargando={sincronizando}
          secundario
          style={estilos.sincronizar}
        />
        {/* Siempre visible con datos: también para vínculos hechos antes de que
            se guardara el cliente del banco (sin nombre), para poder cambiarlo. */}
        <View style={estilos.vinculoFila}>
          <Text style={estilos.vinculo}>
            {bancosVinculados > 1
              ? `${bancosVinculados} bancos vinculados${clienteBanco?.nombre ? " como " + clienteBanco.nombre : ""}`
              : clienteBanco?.nombre
                ? `Banco vinculado como ${clienteBanco.nombre} · ${clienteBanco.rut}`
                : "Banco vinculado"}
          </Text>
          {porConectar.length > 0 && !solicitando ? (
            <Pressable
              onPress={() => {
                setBancoElegido(porConectar[0]);
                setSolicitando(true);
              }}
              hitSlop={8}
            >
              <Text style={estilos.vinculoAccion}>Conectar otro</Text>
            </Pressable>
          ) : (
            // Desvincular o renovar va banco por banco, en Cuentas.
            <Pressable onPress={() => router.push("/cuentas")} hitSlop={8}>
              <Text style={estilos.vinculoAccion}>Administrar</Text>
            </Pressable>
          )}
        </View>

        <Aparecer style={estilos.par} demora={movimiento.escalon}>
          <Superficie nivel={2} style={estilos.tarjeta}>
            <Text style={estilos.rotuloTarjeta}>INGRESOS</Text>
            <Cifra valor={resumen.ingresos} style={estilos.cifra} />
          </Superficie>
          <Superficie nivel={2} style={estilos.tarjeta}>
            <Text style={estilos.rotuloTarjeta}>GASTOS</Text>
            <Cifra valor={resumen.gastos} style={estilos.cifra} />
            <Text style={estilos.pieTarjeta}>{resumen.cantidadGastos} movimientos</Text>
          </Superficie>
        </Aparecer>
      </Superficie>

      {/* RF-35: si un banco no está al día, el disponible de arriba no incluye
          lo más reciente de ese banco. Se dice, no se esconde. */}
      {conProblema.length > 0 ? (
        <View style={estilos.avisoBancos}>
          <Aviso detalle="Tócalo para ver el estado de cada banco." onPress={() => router.push("/cuentas")}>
            {conProblema.length === 1
              ? `${conProblema[0].institucion} ${problemaDe(conProblema[0])}: el total no incluye lo más reciente de ese banco.`
              : `${conProblema.length} bancos sin datos al día (${conProblema.map((c) => c.institucion).join(", ")}): el total no incluye lo más reciente de ellos.`}
          </Aviso>
        </View>
      ) : null}

      {reautorizar || solicitando ? (
        <PanelAutorizacion
          motivo={reautorizar}
          ocupado={abriendoBanco || sincronizando}
          onIrAlBanco={alIrAlBanco}
          onCancelar={() => {
            setReautorizar(null);
            setSolicitando(false);
          }}
          // Al renovar un permiso se va a ESE banco; al conectar otro, a los que faltan.
          bancos={reautorizar ? [banco] : porConectar}
          banco={banco}
          onElegir={setBancoElegido}
        />
      ) : null}

      {aviso ? <Text style={estilos.aviso}>{aviso}</Text> : null}

      {resultado ? (
        <Pressable onPress={() => router.push("/gastos")} style={estilos.resultado}>
          <Text style={estilos.resultadoTexto}>{resultado}</Text>
        </Pressable>
      ) : null}

      {error ? <Text style={estilos.error}>{error}</Text> : null}

      {/* Se le pasa `movimientos` para que se recalcule cuando cambian: una
          sincronización o una corrección mueven estas cifras. */}
      <PanelFlujo recalcularCon={movimientos} />

      <Seccion titulo="Gasto de los últimos meses" />
      <GraficoMeses
        serie={serie}
        promedio={promedio}
        seleccionado={mes}
        onSeleccionar={setMesElegido}
      />

      {repartoPeriodo.porciones.length > 0 ? (
        <>
          <Seccion titulo="En qué se fue en esos meses" />
          <BarraCategorias
            porciones={repartoPeriodo.porciones}
            total={repartoPeriodo.total}
            periodo={`en los últimos ${serie.length} meses`}
            onSeleccionar={(c) => abrirCategoria(c, true)}
          />
        </>
      ) : null}

      {reparto.porciones.length > 0 ? (
        <>
          <Seccion titulo={`En qué se te va · ${nombreMes(mes)}`} />
          {desgloseMayor ? (
            <GastoMasGrande
              desglose={desgloseMayor}
              periodo={`en ${nombreMes(mes).toLowerCase()}`}
              onPress={() => abrirCategoria(desgloseMayor.categoria)}
            />
          ) : null}
          <GraficoCategorias
            porciones={reparto.porciones}
            total={reparto.total}
            onSeleccionar={(c) => abrirCategoria(c)}
          />
        </>
      ) : null}

      {comparacion ? (
        <>
          <Seccion titulo={`Comparado con ${nombreMes(mesAnterior(mes))}`} />
          <Comparacion variaciones={comparacion.variaciones} total={comparacion.total} />
        </>
      ) : null}

      <AvisoClasificacion
        visible={mostrarAviso}
        onDespues={() => cerrarAviso(false)}
        onIr={() => cerrarAviso(true)}
      />
    </Pantalla>
  );
}

/**
 * Relleno de la zona héroe.
 *
 * No sale de la escala de espacios: es el valor que deja las curvas
 * concéntricas. La tarjeta de adentro vale `radio.l`, y para que su curva sea
 * paralela a la de la zona tiene que valer el radio de la zona menos todo lo
 * que las separa — este relleno más el borde de un píxel de la propia zona.
 * Despejando: relleno = radio.xl − radio.l − 1. Se escribe así y no como "11"
 * para que al mover cualquiera de los dos radios siga cuadrando solo.
 */
const HUECO_ZONA = radio.xl - radio.l - 1;

const estilos = StyleSheet.create({
  // El relleno de la zona es lo que fija el radio de las tarjetas que lleva
  // dentro: `radio.xl` menos este hueco tiene que dar `radio.l`. Si se cambia
  // uno hay que cambiar el otro, o las curvas dejan de ser concéntricas.
  zona: { padding: HUECO_ZONA, paddingTop: HUECO_ZONA + 2 },
  rotulo: {
    color: colores.texto3,
    fontFamily: fuente.tituloMedio,
    fontSize: 12,
    letterSpacing: 1.4,
  },
  disponible: {
    color: colores.texto,
    fontFamily: fuente.titulo,
    fontSize: 52,
    letterSpacing: -1.5,
    marginTop: espacio.xs,
    marginBottom: espacio.s,
  },
  negativo: { color: colores.acento },
  bienvenida: {
    color: colores.texto2,
    fontFamily: fuente.texto,
    fontSize: 15,
    lineHeight: 22,
    marginTop: espacio.xs,
    marginBottom: espacio.m,
  },
  sincronizar: { marginTop: espacio.s },
  // ── panel de consentimiento ──
  consent: {
    backgroundColor: colores.tarjeta,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colores.borde,
    borderTopColor: colores.bordeAlto,
    borderRadius: radio.l,
    padding: espacio.l,
    marginTop: espacio.s,
    gap: espacio.s,
  },
  consentTitulo: { color: colores.texto, fontFamily: fuente.tituloMedio, fontSize: 16, marginBottom: espacio.xs },
  consentTexto: { color: colores.texto2, fontFamily: fuente.texto, fontSize: 14, lineHeight: 20 },
  consentItem: { color: colores.texto, fontFamily: fuente.textoFuerte, fontSize: 14, lineHeight: 22 },
  consentNota: { color: colores.texto3, fontFamily: fuente.texto, fontSize: 12, lineHeight: 18, marginTop: espacio.xs },
  aviso: {
    color: colores.texto,
    backgroundColor: colores.alertaSuave,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colores.borde,
    borderTopColor: colores.bordeAlto,
    borderRadius: radio.m,
    padding: espacio.m,
    marginTop: espacio.m,
    fontFamily: fuente.texto,
    fontSize: 13,
    lineHeight: 19,
  },
  consentMotivo: { color: colores.alerta, fontFamily: fuente.texto, fontSize: 13, lineHeight: 19 },
  vinculoFila: { flexDirection: "row", justifyContent: "center", alignItems: "center", gap: espacio.s, marginTop: espacio.s, flexWrap: "wrap" },
  vinculo: { color: colores.texto3, fontFamily: fuente.texto, fontSize: 12, textAlign: "center" },
  // Desvincular es destructivo, y lo destructivo no se pinta de rojo en su
  // puerta de entrada: el rojo va en la confirmación, que es donde la persona
  // decide de verdad. Un enlace rojo bajo la cifra principal invita a tocar
  // justo lo que no queremos que se toque sin pensarlo.
  vinculoAccion: {
    color: colores.texto2,
    fontFamily: fuente.textoFuerte,
    fontSize: 12,
    textDecorationLine: "underline",
  },
  confirmar: { backgroundColor: colores.alertaSuave, borderRadius: radio.m, padding: espacio.m, marginTop: espacio.s, gap: espacio.xs },
  confirmarTexto: { color: colores.texto, fontFamily: fuente.texto, fontSize: 13, lineHeight: 19 },
  confirmarAcciones: { flexDirection: "row", justifyContent: "flex-end", gap: espacio.l },
  confirmarSi: { color: colores.acento, fontFamily: fuente.textoFuerte, fontSize: 14 },
  autorizar: { marginTop: espacio.m },
  elegirBanco: { marginTop: espacio.m, marginBottom: -espacio.s },
  avisoBancos: { marginTop: espacio.l },
  cancelar: { alignItems: "center", paddingVertical: espacio.s, marginTop: espacio.xs },
  cancelarTexto: { color: colores.texto3, fontFamily: fuente.texto, fontSize: 14 },
  // ── resto ──
  resultado: {
    backgroundColor: colores.acentoSuave,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colores.acentoBorde,
    borderRadius: radio.m,
    padding: espacio.m,
    marginTop: espacio.m,
    alignItems: "center",
  },
  resultadoTexto: { color: colores.texto, fontFamily: fuente.textoFuerte, fontSize: 14 },
  error: { color: colores.acento, fontFamily: fuente.texto, fontSize: 13, marginTop: espacio.m, textAlign: "center" },
  par: { flexDirection: "row", gap: espacio.m, marginTop: espacio.l },
  tarjeta: { flex: 1, padding: espacio.l, gap: espacio.s },
  rotuloTarjeta: { color: colores.texto3, fontFamily: fuente.tituloMedio, fontSize: 12, letterSpacing: 1.2 },
  cifra: { color: colores.texto, fontFamily: fuente.titulo, fontSize: 24, letterSpacing: -0.5, marginTop: espacio.s },
  pieTarjeta: { color: colores.texto3, fontFamily: fuente.texto, fontSize: 12 },
});
