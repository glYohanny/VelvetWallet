/**
 * Las fuentes que no son la API del banco (OE-1):
 *
 *   POST   /api/cartolas          -> importar una cartola CSV (RF-12), con vista previa
 *   POST   /api/movimientos       -> anotar un gasto o ingreso en efectivo (RF-13)
 *   DELETE /api/movimientos/{id}  -> borrar uno anotado a mano
 *
 * La app no lee la cartola: la manda tal cual (en base64) y el backend la
 * interpreta. Así hay un solo lector de cartolas, probado, y no uno en el
 * teléfono y otro en el servidor que podrían entender distinto el mismo archivo.
 */
import { Platform } from "react-native";

import type { Movimiento } from "@/modelo/tipos";
import { tokenActual } from "@/servicios/auth";
import { api } from "@/servicios/servidor";

export class ErrorCarga extends Error {}

async function pedir<T>(ruta: string, opciones: RequestInit, porDefecto: string): Promise<T> {
  const token = await tokenActual();
  if (!token) throw new ErrorCarga("Tu sesión no está activa. Inicia sesión de nuevo.");

  let respuesta: Response;
  try {
    respuesta = await fetch(`${api()}${ruta}`, {
      ...opciones,
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    });
  } catch {
    throw new ErrorCarga("No se pudo conectar con el servidor.");
  }
  if (!respuesta.ok) {
    // El backend explica qué estuvo mal (qué columna falta, qué fecha no
    // sirve): ese texto es para la persona.
    const detalle = await respuesta.json().catch(() => null);
    throw new ErrorCarga(typeof detalle?.detail === "string" ? detalle.detail : porDefecto);
  }
  return (respuesta.status === 204 ? null : await respuesta.json()) as T;
}

// ───────────────────────────── carga manual ─────────────────────────────

export type MovimientoAMano = {
  /** Siempre positivo; `tipo` dice si sale o entra. */
  monto: number;
  tipo: "gasto" | "ingreso";
  glosa: string;
  /** "AAAA-MM-DD". Si no se manda, hoy. */
  fecha?: string;
  /** Si la elige la persona; si no, la propone el clasificador. */
  categoria?: string | null;
};

export function anotarMovimiento(datos: MovimientoAMano): Promise<Movimiento> {
  return pedir<Movimiento>("/api/movimientos", { method: "POST", body: JSON.stringify(datos) },
    "No se pudo guardar el movimiento.");
}

export async function borrarMovimiento(id: string): Promise<void> {
  await pedir<null>(`/api/movimientos/${encodeURIComponent(id)}`, { method: "DELETE" },
    "No se pudo borrar el movimiento.");
}

// ─────────────────────────────── cartolas ───────────────────────────────

export type ArchivoElegido = { nombre: string; base64: string; bytes: number };

/** A qué cuenta va la cartola: una que ya existe, o un banco fuera del SFA. */
export type Destino =
  | { cuentaId: string }
  | { institucion: string; tipoCuenta?: string };

export type ResultadoCartola = {
  simulado: boolean;
  cuenta: { id: string; institucion: string; idExterno: string } | null;
  /** Qué columna del archivo se entendió como fecha, glosa, monto… */
  columnas: Record<string, string>;
  leidas: number;
  nuevas: number;
  /** Coincidían con un movimiento que ya trajo el banco: se anotó la fuente, no se duplicó. */
  fusionadas: number;
  /** Ya se habían importado antes. */
  repetidas: number;
  rechazadas: { linea: number; motivo: string }[];
  desde: string | null;
  hasta: string | null;
};

export function importarCartola(archivo: ArchivoElegido, destino: Destino,
                                simular: boolean): Promise<ResultadoCartola> {
  return pedir<ResultadoCartola>("/api/cartolas", {
    method: "POST",
    body: JSON.stringify({
      contenidoBase64: archivo.base64,
      nombreArchivo: archivo.nombre,
      simular,
      ...destino,
    }),
  }, "No se pudo importar la cartola.");
}

function base64DeArchivoWeb(archivo: Blob): Promise<string> {
  return new Promise((resolver, fallar) => {
    const lector = new FileReader();
    lector.onload = () => resolver(String(lector.result).split(",", 2)[1] ?? "");
    lector.onerror = () => fallar(new ErrorCarga("No se pudo leer el archivo."));
    lector.readAsDataURL(archivo);
  });
}

/** Abre el selector de archivos. null si la persona cerró sin elegir. */
export async function elegirCartola(): Promise<ArchivoElegido | null> {
  const DocumentPicker = await import("expo-document-picker");
  const r = await DocumentPicker.getDocumentAsync({
    // Los bancos y los sistemas operativos no se ponen de acuerdo en el tipo
    // de un CSV: se aceptan los habituales y el backend decide si lo entiende.
    type: ["text/csv", "text/comma-separated-values", "text/plain",
           "application/vnd.ms-excel", "application/csv"],
    copyToCacheDirectory: true,
    multiple: false,
  });
  if (r.canceled || !r.assets?.length) return null;
  const a = r.assets[0];

  let base64: string;
  if (Platform.OS === "web" && a.file) {
    base64 = await base64DeArchivoWeb(a.file);
  } else {
    const { default: FileSystem } = await import("expo-file-system/legacy");
    base64 = await FileSystem.readAsStringAsync(a.uri, { encoding: "base64" });
  }
  return { nombre: a.name, base64, bytes: a.size ?? Math.round((base64.length * 3) / 4) };
}

// ───────────────────── correcciones sobre un movimiento (RF-14) ─────────────────────
// Todas devuelven el movimiento como quedó: la app lo reemplaza tal cual, sin
// adivinar qué cambió.

const enc = encodeURIComponent;

export function excluirMovimiento(id: string): Promise<Movimiento> {
  return pedir<Movimiento>(`/api/movimientos/${enc(id)}/excluir`, { method: "POST" },
    "No se pudo excluir el movimiento.");
}

export function marcarDuplicado(id: string, duplicadoDe: string): Promise<Movimiento> {
  return pedir<Movimiento>(`/api/movimientos/${enc(id)}/duplicado`,
    { method: "POST", body: JSON.stringify({ duplicadoDe }) },
    "No se pudo marcar como duplicado.");
}

export function volverAContar(id: string): Promise<Movimiento> {
  return pedir<Movimiento>(`/api/movimientos/${enc(id)}/exclusion`, { method: "DELETE" },
    "No se pudo deshacer.");
}

/** `partes` con montos positivos, como los escribe la persona. */
export function dividirMovimiento(id: string,
                                  partes: { monto: number; categoria: string }[]): Promise<Movimiento> {
  return pedir<Movimiento>(`/api/movimientos/${enc(id)}/division`,
    { method: "PUT", body: JSON.stringify({ partes }) },
    "No se pudo dividir el movimiento.");
}

export function unirMovimiento(id: string): Promise<Movimiento> {
  return pedir<Movimiento>(`/api/movimientos/${enc(id)}/division`, { method: "DELETE" },
    "No se pudo deshacer la división.");
}
