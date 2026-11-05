/**
 * Estado de sesión compartido por toda la aplicación.
 *
 * Cualquier pantalla pregunta `useSesion()` y obtiene el usuario conectado y
 * las operaciones de entrar y salir. Es el único lugar que conoce el token.
 *
 * `cargando` es true mientras se revisa el almacenamiento al arrancar: sin él,
 * la app mostraría el login por un instante antes de reconocer la sesión.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import type { Credenciales, DatosRegistro, Usuario } from "@/modelo/tipos";
import * as auth from "@/servicios/auth";
import { cargarServidor } from "@/servicios/servidor";

type ValorSesion = {
  usuario: Usuario | null;
  cargando: boolean;
  entrar: (c: Credenciales) => Promise<void>;
  registrarse: (d: DatosRegistro) => Promise<void>;
  salir: () => Promise<void>;
  /**
   * Deja anotado el sueldo que la persona acabó de declarar en el backend
   * (RF-36). Se guarda también en la sesión del dispositivo: si solo cambiara
   * en memoria, al reabrir la app volvería el valor viejo.
   */
  anotarSueldo: (monto: number | null) => Promise<void>;
};

const Contexto = createContext<ValorSesion | null>(null);

export function ProveedorSesion({ children }: { children: ReactNode }) {
  const [usuario, setUsuario] = useState<Usuario | null>(null);
  const [cargando, setCargando] = useState(true);

  // Al arrancar: primero a qué servidor hablarle (la dirección que se haya
  // guardado para usar la app desde un celular), y después, ¿hay una sesión
  // guardada de la vez anterior? En ese orden: la primera petición ya tiene
  // que ir al servidor correcto.
  useEffect(() => {
    cargarServidor()
      .then(() => auth.sesionGuardada())
      .then((s) => setUsuario(s?.usuario ?? null))
      .catch(() => setUsuario(null))
      .finally(() => setCargando(false));
  }, []);

  const entrar = useCallback(async (c: Credenciales) => {
    const sesion = await auth.iniciarSesion(c);
    setUsuario(sesion.usuario);
  }, []);

  const registrarse = useCallback(async (d: DatosRegistro) => {
    const sesion = await auth.registrar(d);
    setUsuario(sesion.usuario);
  }, []);

  const salir = useCallback(async () => {
    await auth.cerrarSesion();
    setUsuario(null);
  }, []);

  const anotarSueldo = useCallback(async (monto: number | null) => {
    const actualizado = await auth.actualizarUsuario({ sueldoDeclarado: monto });
    if (actualizado) setUsuario(actualizado);
  }, []);

  const valor = useMemo(
    () => ({ usuario, cargando, entrar, registrarse, salir, anotarSueldo }),
    [usuario, cargando, entrar, registrarse, salir, anotarSueldo],
  );

  return <Contexto.Provider value={valor}>{children}</Contexto.Provider>;
}

export function useSesion(): ValorSesion {
  const valor = useContext(Contexto);
  if (!valor) throw new Error("useSesion se usó fuera de ProveedorSesion");
  return valor;
}
