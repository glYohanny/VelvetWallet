/**
 * Servicio de autenticación.
 *
 * Habla con el backend de Velvet Wallet (FastAPI, puerto 8000):
 *
 *   POST /api/auth/registro  { nombre, email, password }  -> SesionIniciada
 *   POST /api/auth/sesion    { email, password }          -> SesionIniciada
 *
 * Reglas:
 *  · La contraseña se envía una vez y no se guarda nunca en el dispositivo.
 *  · Lo que se guarda es el token, en el almacén seguro del sistema.
 *  · El error de credenciales no dice si falló el correo o la contraseña:
 *    distinguirlos permitiría averiguar qué correos están registrados.
 */
import type { Credenciales, DatosRegistro, SesionIniciada, Usuario } from "@/modelo/tipos";
import { borrar, guardar, leer } from "@/servicios/almacenamiento";
import { api } from "@/servicios/servidor";

// URL del backend. En web, localhost funciona. En un celular físico, cámbiala
// por la IP de tu PC en la red (ej: http://192.168.1.20:8000).
const CLAVE_SESION = "velvet.sesion";

/** Error con mensaje pensado para mostrarse tal cual al usuario. */
export class ErrorAuth extends Error {}

// ───────────────────────── validaciones ─────────────────────────
// Las mismas reglas las aplica también el backend: validar solo en el cliente
// no sirve, porque se puede llamar a la API directamente.

export function emailValido(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email.trim());
}

/** Mínimo 8 caracteres. Devuelve null si está bien, o el motivo. */
export function problemaPassword(password: string): string | null {
  if (password.length < 8) return "La contraseña debe tener al menos 8 caracteres.";
  return null;
}

// ───────────────────────── llamada al backend ─────────────────────────

async function pedirSesion(ruta: string, cuerpo: object): Promise<SesionIniciada> {
  let respuesta: Response;
  try {
    respuesta = await fetch(`${api()}${ruta}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cuerpo),
    });
  } catch {
    throw new ErrorAuth("No se pudo conectar con el servidor. Revisa tu conexión.");
  }

  const datos = await respuesta.json().catch(() => null);
  if (!respuesta.ok) {
    // El backend manda el mensaje de error en el campo "detail".
    const mensaje = datos?.detail ?? "Ocurrió un error. Intenta de nuevo.";
    throw new ErrorAuth(mensaje);
  }
  return datos as SesionIniciada;
}

// ───────────────────────── operaciones ─────────────────────────

export async function registrar(datos: DatosRegistro): Promise<SesionIniciada> {
  const sesion = await pedirSesion("/api/auth/registro", {
    nombre: datos.nombre.trim(),
    email: datos.email.trim().toLowerCase(),
    password: datos.password,
  });
  await guardarSesion(sesion);
  return sesion;
}

export async function iniciarSesion({ email, password }: Credenciales): Promise<SesionIniciada> {
  const sesion = await pedirSesion("/api/auth/sesion", {
    email: email.trim().toLowerCase(),
    password,
  });
  await guardarSesion(sesion);
  return sesion;
}

export async function cerrarSesion(): Promise<void> {
  await borrar(CLAVE_SESION);
}

// ───────────────────── persistencia de la sesión ─────────────────────

async function guardarSesion(sesion: SesionIniciada): Promise<void> {
  await guardar(CLAVE_SESION, JSON.stringify(sesion));
}

/** Sesión guardada, si existe y no expiró. Se llama al arrancar la app. */
export async function sesionGuardada(): Promise<SesionIniciada | null> {
  const bruto = await leer(CLAVE_SESION);
  if (!bruto) return null;

  try {
    const sesion = JSON.parse(bruto) as SesionIniciada;
    if (new Date(sesion.expiraEn) <= new Date()) {
      await borrar(CLAVE_SESION);
      return null;
    }
    return sesion;
  } catch {
    // Dato corrupto: se descarta y se empieza de nuevo.
    await borrar(CLAVE_SESION);
    return null;
  }
}

/**
 * Actualiza los datos del usuario dentro de la sesión guardada, sin tocar el
 * token ni su vencimiento.
 *
 * Hace falta porque el usuario viaja dentro de la sesión: si solo se cambiara
 * en memoria, al reabrir la app volvería el valor viejo. Devuelve el usuario
 * ya guardado, o null si entremedio se cerró la sesión.
 */
export async function actualizarUsuario(cambios: Partial<Usuario>): Promise<Usuario | null> {
  const sesion = await sesionGuardada();
  if (!sesion) return null;
  const usuario = { ...sesion.usuario, ...cambios };
  await guardarSesion({ ...sesion, usuario });
  return usuario;
}

/**
 * Token de la sesión actual (o null si no hay sesión válida). Lo usan los
 * servicios que llaman al backend para mandar `Authorization: Bearer <token>`.
 */
export async function tokenActual(): Promise<string | null> {
  const sesion = await sesionGuardada();
  return sesion?.token ?? null;
}
