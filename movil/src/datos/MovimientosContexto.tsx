/**
 * Los movimientos del usuario, como estado compartido.
 *
 * Se cargan desde el backend cuando el usuario inicia sesión (solo los suyos) y
 * se limpian cuando cierra sesión. Antes se partía de un archivo local igual
 * para todos; ahora cada usuario ve únicamente su propia información.
 *
 * Al recibir los datos se corre la PRIMERA CAPA del clasificador (reglas por
 * palabra clave, ver utils/sugerencias). El backend todavía no categoriza, así
 * que esto vive en la app de forma provisional: cuando el clasificador exista
 * en el backend, la categoría llegará ya puesta y este paso se quita.
 *
 * `novedades` guarda qué cambió en la última sincronización para que la lista
 * pueda destacarlo. Se limpia cuando el usuario las mira.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Platform } from "react-native";
import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";

import type { Correccion, Movimiento } from "@/modelo/tipos";
import {
  conectarBanco,
  desvincularBanco,
  guardarCategoria,
  iniciarVinculacion,
  obtenerConexiones,
  obtenerMovimientos,
  type ConexionBanco,
} from "@/servicios/sincronizacion";
import { useSesion } from "@/sesion/SesionContexto";
import { fusionar } from "@/utils/fusion";

export type Novedades = {
  nuevos: string[];
  /** id → monto que tenía antes de actualizarse. */
  actualizados: Record<string, number>;
};

const SIN_NOVEDADES: Novedades = { nuevos: [], actualizados: {} };

/** Con qué vuelve el usuario desde el sitio del banco. */
export type VueltaDelBanco = { banco: string; motivo?: string };

/** A dónde debe volver el usuario después de autorizar en su banco. */
function urlDeRetorno(): string {
  if (Platform.OS === "web" && typeof window !== "undefined") {
    return window.location.origin + "/";
  }
  return Linking.createURL("/"); // velvetwallet://  ó  exp://… en Expo Go
}

type ValorMovimientos = {
  movimientos: Movimiento[];
  novedades: Novedades;
  sincronizando: boolean;
  /**
   * La PRIMERA carga del usuario todavía no termina.
   *
   * No alcanza con `sincronizando` para esto: esa bandera también se levanta al
   * resincronizar, cuando ya hay datos en pantalla. Mientras no se distinga
   * "aún no sé" de "ya pregunté y no hay nada", la app muestra "No hay
   * movimientos" o "Conecta tu primer banco" a alguien que sí tiene datos —
   * dice algo falso durante el segundo que tarda la respuesta.
   */
  cargaInicial: boolean;
  ultimaSincronizacion: string | null;
  error: string | null;
  /** Vuelve a consultar el backend y fusiona. Devuelve cuántos cambiaron. */
  sincronizar: () => Promise<{ nuevos: number; actualizados: number }>;
  /**
   * Manda al usuario al SITIO DE SU BANCO para que inicie sesión y autorice.
   * En web la página se va al banco (y vuelve con ?banco=…): devuelve null.
   * En el celular se abre el navegador y devuelve cómo volvió.
   */
  irAlBanco: () => Promise<VueltaDelBanco | null>;
  /** Después de volver con ?banco=vinculado: trae los datos del banco. */
  completarVinculacion: () => Promise<void>;
  /** Retira el permiso del banco y borra sus datos de Velvet. */
  desvincular: () => Promise<void>;
  /** Con qué cliente del banco quedó vinculado el usuario (null si no se sabe). */
  clienteBanco: { rut: string; nombre: string } | null;
  /** Instituciones vinculadas, con su estado y sus cuentas, como las da el backend. */
  conexiones: ConexionBanco[];
  /** Asigna o corrige la categoría de un movimiento (el usuario en "Por revisar"). */
  corregirCategoria: (id: string, categoria: string) => void;
  /** Apaga el destacado y el contador de la pestaña. */
  marcarVistas: () => void;
  /** Un movimiento recién anotado a mano: entra a la lista sin volver a pedirla entera. */
  agregarMovimiento: (m: Movimiento) => void;
  /** Saca de la lista uno que se borró (solo los anotados a mano se pueden borrar). */
  quitarMovimiento: (id: string) => void;
  /** Vuelve a traer movimientos e instituciones, p. ej. después de importar una cartola. */
  recargar: () => Promise<void>;
};

const Contexto = createContext<ValorMovimientos | null>(null);

export function ProveedorMovimientos({ children }: { children: ReactNode }) {
  const { usuario } = useSesion();

  const [movimientos, setMovimientos] = useState<Movimiento[]>([]);
  // Espejo de `movimientos` para fusionar sin depender de cuándo React aplique
  // el cambio de estado.
  const actualesRef = useRef<Movimiento[]>([]);
  const [novedades, setNovedades] = useState<Novedades>(SIN_NOVEDADES);
  const [sincronizando, setSincronizando] = useState(false);
  // Arranca en true cuando ya hay sesión, para que el primer cuadro que se
  // pinta sean los esqueletos y no un "no hay nada" que todavía no sabemos.
  const [cargaInicial, setCargaInicial] = useState<boolean>(() => usuario != null);
  const [ultimaSincronizacion, setUltima] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [clienteBanco, setClienteBanco] = useState<{ rut: string; nombre: string } | null>(null);
  const [conexiones, setConexiones] = useState<ConexionBanco[]>([]);

  // Cada operación que carga datos sube la generación; la carga inicial solo se
  // aplica si nadie cargó algo más nuevo mientras tanto (evita que una carga
  // vieja y vacía pise lo recién vinculado al volver del banco).
  const generacion = useRef(0);

  const reemplazar = useCallback((lista: Movimiento[]) => {
    actualesRef.current = lista;
    setMovimientos(lista);
  }, []);

  /**
   * Vuelve a preguntar en qué estado están los bancos vinculados.
   *
   * Es a mejor esfuerzo: si falla, la app sigue andando con los movimientos que
   * ya tiene. Sacar el cliente del banco de la misma respuesta evita que la
   * lista y el nombre que se muestra arriba queden describiendo momentos
   * distintos.
   */
  const refrescarConexiones = useCallback(async () => {
    try {
      const lista = await obtenerConexiones();
      setConexiones(lista);
      const c = lista.find((x) => x.nombreCliente);
      setClienteBanco(c ? { rut: c.rutCliente ?? "", nombre: c.nombreCliente ?? "" } : null);
    } catch {
      // Información de estado, no de uso: no vale la pena interrumpir por esto.
    }
  }, []);

  // Carga inicial de los datos del usuario al entrar; limpieza al salir.
  useEffect(() => {
    let vivo = true;

    if (!usuario) {
      reemplazar([]);
      setClienteBanco(null);
      setConexiones([]);
      setNovedades(SIN_NOVEDADES);
      setUltima(null);
      setError(null);
      setCargaInicial(false);
      return;
    }

    setSincronizando(true);
    setCargaInicial(true);
    setError(null);
    const miGeneracion = ++generacion.current;
    obtenerMovimientos()
      .then((lista) => {
        if (!vivo || miGeneracion !== generacion.current) return;
        reemplazar(lista);
        setUltima(new Date().toISOString());
        if (vivo) refrescarConexiones();
      })
      .catch((e) => {
        if (vivo) setError(e instanceof Error ? e.message : "No se pudieron cargar los datos.");
      })
      .finally(() => {
        if (!vivo) return;
        setSincronizando(false);
        // Se baja pase lo que pase: si falló, lo que corresponde mostrar es el
        // error, no esqueletos girando para siempre.
        setCargaInicial(false);
      });

    return () => {
      vivo = false;
    };
  }, [usuario?.id, reemplazar, refrescarConexiones]);

  const sincronizar = useCallback(async () => {
    setSincronizando(true);
    setError(null);
    try {
      generacion.current++;
      // Vuelve a pedir al banco (re-corre la ingesta): así llegan los
      // movimientos nuevos que el banco generó desde la última vez.
      await conectarBanco();   // sin clave: usa el permiso guardado
      const entrantes = await obtenerMovimientos();

      const r = fusionar(actualesRef.current, entrantes);
      actualesRef.current = r.movimientos;
      setMovimientos(r.movimientos);

      if (r.nuevos.length > 0 || r.actualizados.length > 0) {
        setNovedades((previas) => ({
          nuevos: [...new Set([...previas.nuevos, ...r.nuevos])],
          actualizados: {
            ...previas.actualizados,
            ...Object.fromEntries(r.actualizados.map((a) => [a.id, a.montoAnterior])),
          },
        }));
      }

      setUltima(new Date().toISOString());
      // Cambió la fecha de la última sincronización y puede haber cambiado el
      // estado del permiso: la pantalla de Cuentas tiene que reflejarlo.
      refrescarConexiones();
      return { nuevos: r.nuevos.length, actualizados: r.actualizados.length };
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo sincronizar.");
      throw e;
    } finally {
      setSincronizando(false);
    }
  }, [refrescarConexiones]);

  const irAlBanco = useCallback(async (): Promise<VueltaDelBanco | null> => {
    setError(null);
    const retorno = urlDeRetorno();
    let url: string;
    try {
      url = await iniciarVinculacion(retorno);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo abrir el sitio del banco.");
      throw e;
    }
    if (Platform.OS === "web") {
      window.location.assign(url); // la app vuelve sola con ?banco=…
      return null;
    }
    const r = await WebBrowser.openAuthSessionAsync(url, retorno);
    if (r.type !== "success") return null; // cerró el navegador sin terminar
    const q = Linking.parse(r.url).queryParams ?? {};
    return { banco: String(q.banco ?? "error"), motivo: q.motivo ? String(q.motivo) : undefined };
  }, []);

  const completarVinculacion = useCallback(async () => {
    setSincronizando(true);
    setError(null);
    generacion.current++;
    try {
      // El permiso ya lo dio el usuario en su banco: ahora se traen SUS datos.
      await conectarBanco();
      const lista = await obtenerMovimientos();  // y cargamos lo que llegó
      reemplazar(lista);
      setUltima(new Date().toISOString());
      refrescarConexiones();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo conectar el banco.");
      throw e;
    } finally {
      setSincronizando(false);
    }
  }, [reemplazar, refrescarConexiones]);

  // El usuario asigna o corrige una categoría (p. ej. en "Por revisar"). Se ve
  // al tiro y se guarda en el backend como corrección: el dato del banco no se
  // toca, sobrevive a las resincronizaciones y, si la persona consintió,
  // alimenta el reentrenamiento del clasificador. Si no se puede guardar, se
  // deshace y se avisa.
  const corregirCategoria = useCallback((id: string, categoria: string) => {
    const antes = actualesRef.current.find((m) => m.id === id);
    const correccion: Correccion = {
      tipo: "recategorizar",
      fecha: new Date().toISOString(),
      detalle: categoria,
    };
    const aplicar = (lista: Movimiento[]) =>
      lista.map((m) =>
        m.id === id
          ? {
              ...m,
              categoria,
              estadoCategoria: "corregida" as const,
              origenClasificacion: "usuario" as const,
              confianza: null,
              correcciones: [...m.correcciones, correccion],
            }
          : m,
      );
    const poner = (lista: Movimiento[]) => {
      actualesRef.current = lista;
      setMovimientos(lista);
    };
    poner(aplicar(actualesRef.current));

    guardarCategoria(id, categoria)
      .then((guardado) => poner(actualesRef.current.map((m) => (m.id === id ? guardado : m))))
      .catch((e) => {
        if (antes) poner(actualesRef.current.map((m) => (m.id === id ? antes : m)));
        setError(e instanceof Error ? e.message : "No se pudo guardar la categoría.");
      });
  }, []);

  const desvincular = useCallback(async () => {
    setSincronizando(true);
    setError(null);
    try {
      // Solo los bancos del SFA: el efectivo y las cartolas no tienen un
      // permiso que retirar, y desvincular el banco no debería borrar lo que
      // la persona anotó a mano o importó de otra institución.
      const deBanco = (await obtenerConexiones()).filter((c) => (c.fuente ?? "sfa") === "sfa");
      for (const c of deBanco) {
        await desvincularBanco(c.id);
      }
      const quitadas = new Set(deBanco.map((c) => c.institucion));
      const quedan = actualesRef.current.filter((m) => !quitadas.has(m.institucion));
      reemplazar(quedan);
      setNovedades(SIN_NOVEDADES);
      setClienteBanco(null);
      refrescarConexiones();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo desvincular el banco.");
      throw e;
    } finally {
      setSincronizando(false);
    }
  }, [reemplazar, refrescarConexiones]);

  const marcarVistas = useCallback(() => setNovedades(SIN_NOVEDADES), []);

  const agregarMovimiento = useCallback((m: Movimiento) => {
    const lista = [m, ...actualesRef.current.filter((x) => x.id !== m.id)];
    actualesRef.current = lista;
    setMovimientos(lista);
    setNovedades((previas) => ({ ...previas, nuevos: [...previas.nuevos, m.id] }));
    // Puede haber nacido la cuenta Efectivo: la pantalla de Cuentas la muestra.
    refrescarConexiones();
  }, [refrescarConexiones]);

  const quitarMovimiento = useCallback((id: string) => {
    const lista = actualesRef.current.filter((x) => x.id !== id);
    actualesRef.current = lista;
    setMovimientos(lista);
  }, []);

  const recargar = useCallback(async () => {
    generacion.current++;
    try {
      const entrantes = await obtenerMovimientos();
      const r = fusionar(actualesRef.current, entrantes);
      actualesRef.current = r.movimientos;
      setMovimientos(r.movimientos);
      if (r.nuevos.length > 0) {
        setNovedades((previas) => ({
          ...previas,
          nuevos: [...new Set([...previas.nuevos, ...r.nuevos])],
        }));
      }
    } finally {
      refrescarConexiones();
    }
  }, [refrescarConexiones]);

  const valor = useMemo(
    () => ({
      movimientos,
      novedades,
      sincronizando,
      cargaInicial,
      ultimaSincronizacion,
      error,
      sincronizar,
      irAlBanco,
      completarVinculacion,
      desvincular,
      clienteBanco,
      conexiones,
      corregirCategoria,
      marcarVistas,
      agregarMovimiento,
      quitarMovimiento,
      recargar,
    }),
    [movimientos, novedades, sincronizando, cargaInicial, ultimaSincronizacion, error, sincronizar, irAlBanco, completarVinculacion, desvincular, clienteBanco, conexiones, corregirCategoria, marcarVistas, agregarMovimiento, quitarMovimiento, recargar],
  );

  return <Contexto.Provider value={valor}>{children}</Contexto.Provider>;
}

export function useMovimientos(): ValorMovimientos {
  const valor = useContext(Contexto);
  if (!valor) throw new Error("useMovimientos se usó fuera de ProveedorMovimientos");
  return valor;
}

/** Cantidad de novedades sin mirar, para el contador de la pestaña. */
export function contarNovedades(n: Novedades): number {
  return n.nuevos.length + Object.keys(n.actualizados).length;
}
